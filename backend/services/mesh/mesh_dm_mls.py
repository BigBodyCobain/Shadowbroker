"""MLS-backed DM session manager.

This module keeps DM session orchestration in Python while privacy-core owns
the MLS session state. Python-side metadata survives via domain storage, but
Rust session state remains in-memory only. Process restart still requires
session re-establishment until Rust FFI state export is available.
"""

from __future__ import annotations

import base64
import logging
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from services.mesh.mesh_secure_storage import (
    read_domain_json,
    read_secure_json,
    write_domain_json,
)
from services.mesh.mesh_privacy_logging import privacy_log_label
from services.mesh.mesh_wormhole_persona import sign_dm_alias_blob, verify_dm_alias_blob
from services.privacy_core_client import PrivacyCoreClient, PrivacyCoreError
from services.wormhole_supervisor import get_wormhole_state, transport_tier_from_state

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
STATE_FILE = DATA_DIR / "wormhole_dm_mls.json"
STATE_FILENAME = "wormhole_dm_mls.json"
STATE_DOMAIN = "dm_alias"
_STATE_LOCK = threading.RLock()
_PRIVACY_CLIENT: PrivacyCoreClient | None = None
_STATE_LOADED = False
_TRANSPORT_TIER_ORDER = {
    "public_degraded": 0,
    "private_transitional": 1,
    "private_strong": 2,
}
MLS_DM_FORMAT = "mls1"
MAX_DM_PLAINTEXT_SIZE = 65_536

try:
    from nacl.public import PrivateKey as _NaclPrivateKey
    from nacl.public import PublicKey as _NaclPublicKey
    from nacl.public import SealedBox as _NaclSealedBox
except ImportError:
    _NaclPrivateKey = None
    _NaclPublicKey = None
    _NaclSealedBox = None


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(data: str | bytes | None) -> bytes:
    if not data:
        return b""
    if isinstance(data, bytes):
        return base64.b64decode(data)
    return base64.b64decode(data.encode("ascii"))


def _decode_key_text(data: str | bytes | None) -> bytes:
    raw = str(data or "").strip()
    if not raw:
        return b""
    try:
        return bytes.fromhex(raw)
    except ValueError:
        return _unb64(raw)


def _normalize_alias(alias: str) -> str:
    return str(alias or "").strip().lower()


def _session_id(local_alias: str, remote_alias: str) -> str:
    return f"{_normalize_alias(local_alias)}::{_normalize_alias(remote_alias)}"


def _seal_keypair() -> dict[str, str]:
    private_key = x25519.X25519PrivateKey.generate()
    return {
        "public_key": private_key.public_key().public_bytes_raw().hex(),
        "private_key": private_key.private_bytes_raw().hex(),
    }


def _seal_welcome_for_public_key(payload: bytes, public_key_text: str) -> bytes:
    public_key_bytes = _decode_key_text(public_key_text)
    if not public_key_bytes:
        raise PrivacyCoreError("responder_dh_pub is required for sealed welcome")
    if _NaclPublicKey is not None and _NaclSealedBox is not None:
        return _NaclSealedBox(_NaclPublicKey(public_key_bytes)).encrypt(payload)

    ephemeral_private = x25519.X25519PrivateKey.generate()
    ephemeral_public = ephemeral_private.public_key().public_bytes_raw()
    recipient_public = x25519.X25519PublicKey.from_public_bytes(public_key_bytes)
    shared_secret = ephemeral_private.exchange(recipient_public)
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"shadowbroker|dm-mls-welcome|v1",
    ).derive(shared_secret)
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(key).encrypt(
        nonce,
        payload,
        b"shadowbroker|dm-mls-welcome|v1",
    )
    return ephemeral_public + nonce + ciphertext


def _unseal_welcome_for_private_key(payload: bytes, private_key_text: str) -> bytes:
    private_key_bytes = _decode_key_text(private_key_text)
    if not private_key_bytes:
        raise PrivacyCoreError("local DH secret unavailable for DM session acceptance")
    if _NaclPrivateKey is not None and _NaclSealedBox is not None:
        return _NaclSealedBox(_NaclPrivateKey(private_key_bytes)).decrypt(payload)
    if len(payload) < 44:
        raise PrivacyCoreError("sealed DM welcome is truncated")
    ephemeral_public = x25519.X25519PublicKey.from_public_bytes(payload[:32])
    nonce = payload[32:44]
    ciphertext = payload[44:]
    private_key = x25519.X25519PrivateKey.from_private_bytes(private_key_bytes)
    shared_secret = private_key.exchange(ephemeral_public)
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"shadowbroker|dm-mls-welcome|v1",
    ).derive(shared_secret)
    try:
        return AESGCM(key).decrypt(
            nonce,
            ciphertext,
            b"shadowbroker|dm-mls-welcome|v1",
        )
    except Exception as exc:
        raise PrivacyCoreError("sealed DM welcome decrypt failed") from exc


@dataclass
class _SessionBinding:
    session_id: str
    local_alias: str
    remote_alias: str
    role: str
    session_handle: int
    created_at: int


_ALIAS_IDENTITIES: dict[str, int] = {}
_ALIAS_BINDINGS: dict[str, dict[str, str]] = {}
_ALIAS_SEAL_KEYS: dict[str, dict[str, str]] = {}
_SESSIONS: dict[str, _SessionBinding] = {}
_DM_FORMAT_LOCKS: dict[str, str] = {}


def _default_state() -> dict[str, Any]:
    return {
        "version": 2,
        "updated_at": 0,
        "aliases": {},
        "alias_seal_keys": {},
        "sessions": {},
        "dm_format_locks": {},
    }


def _privacy_client() -> PrivacyCoreClient:
    global _PRIVACY_CLIENT
    if _PRIVACY_CLIENT is None:
        _PRIVACY_CLIENT = PrivacyCoreClient.load()
    return _PRIVACY_CLIENT


def _current_transport_tier() -> str:
    return transport_tier_from_state(get_wormhole_state())


def _require_private_transport() -> tuple[bool, str]:
    current = _current_transport_tier()
    if _TRANSPORT_TIER_ORDER.get(current, 0) < _TRANSPORT_TIER_ORDER["private_transitional"]:
        return False, "DM MLS requires PRIVATE transport tier"
    return True, current


def _serialize_session(binding: _SessionBinding) -> dict[str, Any]:
    return {
        "session_id": binding.session_id,
        "local_alias": binding.local_alias,
        "remote_alias": binding.remote_alias,
        "role": binding.role,
        "session_handle": int(binding.session_handle),
        "created_at": int(binding.created_at),
    }


def _binding_record(handle: int, public_bundle: bytes, binding_proof: str) -> dict[str, Any]:
    return {
        "handle": int(handle),
        "public_bundle": _b64(public_bundle),
        "binding_proof": str(binding_proof or ""),
    }


def _load_state() -> None:
    global _STATE_LOADED
    with _STATE_LOCK:
        if _STATE_LOADED:
            return
        # KNOWN LIMITATION: Persisted handles only survive when the privacy-core
        # library instance is still alive in the same process. Full Rust-state
        # export/import is deferred to a later sprint.
        domain_path = DATA_DIR / STATE_DOMAIN / STATE_FILENAME
        if not domain_path.exists() and STATE_FILE.exists():
            try:
                legacy = read_secure_json(STATE_FILE, _default_state)
                write_domain_json(STATE_DOMAIN, STATE_FILENAME, legacy)
                STATE_FILE.unlink(missing_ok=True)
            except Exception:
                logger.warning(
                    "Legacy DM MLS state could not be decrypted — "
                    "discarding stale file and starting fresh"
                )
                STATE_FILE.unlink(missing_ok=True)
        raw = read_domain_json(STATE_DOMAIN, STATE_FILENAME, _default_state)
        state = _default_state()
        if isinstance(raw, dict):
            state.update(raw)

        _ALIAS_IDENTITIES.clear()
        _ALIAS_BINDINGS.clear()
        for alias, payload in dict(state.get("aliases") or {}).items():
            alias_key = _normalize_alias(alias)
            if not alias_key:
                continue
            if isinstance(payload, dict):
                handle = int(payload.get("handle", 0) or 0)
                public_bundle_b64 = str(payload.get("public_bundle", "") or "")
                binding_proof = str(payload.get("binding_proof", "") or "")
            else:
                handle = int(payload or 0)
                public_bundle_b64 = ""
                binding_proof = ""
            if handle <= 0 or not public_bundle_b64 or not binding_proof:
                logger.warning("DM MLS alias binding missing proof; identity will be re-created")
                continue
            try:
                public_bundle = _unb64(public_bundle_b64)
            except Exception as exc:
                logger.warning("DM MLS alias binding decode failed: %s", type(exc).__name__)
                continue
            ok, reason = verify_dm_alias_blob(alias_key, public_bundle, binding_proof)
            if not ok:
                logger.warning("DM MLS alias binding invalid: %s", reason)
                continue
            _ALIAS_IDENTITIES[alias_key] = handle
            _ALIAS_BINDINGS[alias_key] = _binding_record(handle, public_bundle, binding_proof)

        _ALIAS_SEAL_KEYS.clear()
        for alias, keypair in dict(state.get("alias_seal_keys") or {}).items():
            alias_key = _normalize_alias(alias)
            pair = dict(keypair or {})
            public_key = str(pair.get("public_key", "") or "").strip().lower()
            private_key = str(pair.get("private_key", "") or "").strip().lower()
            if alias_key and public_key and private_key:
                _ALIAS_SEAL_KEYS[alias_key] = {
                    "public_key": public_key,
                    "private_key": private_key,
                }

        _SESSIONS.clear()
        for session_id, payload in dict(state.get("sessions") or {}).items():
            if not isinstance(payload, dict):
                continue
            binding = _SessionBinding(
                session_id=str(payload.get("session_id", session_id) or session_id),
                local_alias=_normalize_alias(str(payload.get("local_alias", "") or "")),
                remote_alias=_normalize_alias(str(payload.get("remote_alias", "") or "")),
                role=str(payload.get("role", "initiator") or "initiator"),
                session_handle=int(payload.get("session_handle", 0) or 0),
                created_at=int(payload.get("created_at", 0) or 0),
            )
            if (
                binding.session_id
                and binding.session_handle > 0
                and binding.local_alias in _ALIAS_IDENTITIES
            ):
                _SESSIONS[binding.session_id] = binding

        _DM_FORMAT_LOCKS.clear()
        for session_id, payload_format in dict(state.get("dm_format_locks") or {}).items():
            normalized = str(payload_format or "").strip().lower()
            if normalized:
                _DM_FORMAT_LOCKS[str(session_id or "")] = normalized
        _STATE_LOADED = True


def _save_state() -> None:
    with _STATE_LOCK:
        write_domain_json(
            STATE_DOMAIN,
            STATE_FILENAME,
            {
                "version": 2,
                "updated_at": int(time.time()),
                "aliases": {
                    alias: dict(_ALIAS_BINDINGS.get(alias) or {})
                    for alias, handle in _ALIAS_IDENTITIES.items()
                    if _ALIAS_BINDINGS.get(alias)
                },
                "alias_seal_keys": {
                    alias: dict(keypair or {})
                    for alias, keypair in _ALIAS_SEAL_KEYS.items()
                },
                "sessions": {
                    session_id: _serialize_session(binding)
                    for session_id, binding in _SESSIONS.items()
                },
                "dm_format_locks": dict(_DM_FORMAT_LOCKS),
            },
        )
        STATE_FILE.unlink(missing_ok=True)


def reset_dm_mls_state(*, clear_privacy_core: bool = False, clear_persistence: bool = True) -> None:
    global _PRIVACY_CLIENT, _STATE_LOADED
    with _STATE_LOCK:
        if clear_privacy_core and _PRIVACY_CLIENT is not None:
            try:
                _PRIVACY_CLIENT.reset_all_state()
            except Exception:
                logger.exception("privacy-core reset failed while clearing DM MLS state")
        _ALIAS_IDENTITIES.clear()
        _ALIAS_BINDINGS.clear()
        _ALIAS_SEAL_KEYS.clear()
        _SESSIONS.clear()
        _DM_FORMAT_LOCKS.clear()
        _STATE_LOADED = False
        if clear_persistence and STATE_FILE.exists():
            STATE_FILE.unlink()


def _identity_handle_for_alias(alias: str) -> int:
    alias_key = _normalize_alias(alias)
    if not alias_key:
        raise PrivacyCoreError("dm alias is required")
    _load_state()
    with _STATE_LOCK:
        handle = _ALIAS_IDENTITIES.get(alias_key)
        if handle:
            return handle
        handle = _privacy_client().create_identity()
        public_bundle = _privacy_client().export_public_bundle(handle)
        signed = sign_dm_alias_blob(alias_key, public_bundle)
        if not signed.get("ok"):
            try:
                _privacy_client().release_identity(handle)
            except Exception:
                pass
            raise PrivacyCoreError(str(signed.get("detail") or "dm_mls_identity_binding_failed"))
        _ALIAS_IDENTITIES[alias_key] = handle
        _ALIAS_BINDINGS[alias_key] = _binding_record(
            handle,
            public_bundle,
            str(signed.get("signature", "") or ""),
        )
        _save_state()
        return handle


def _seal_keypair_for_alias(alias: str) -> dict[str, str]:
    alias_key = _normalize_alias(alias)
    if not alias_key:
        raise PrivacyCoreError("dm alias is required")
    _load_state()
    with _STATE_LOCK:
        existing = _ALIAS_SEAL_KEYS.get(alias_key)
        if existing and existing.get("public_key") and existing.get("private_key"):
            return dict(existing)
        created = _seal_keypair()
        _ALIAS_SEAL_KEYS[alias_key] = created
        _save_state()
        return dict(created)


def export_dm_key_package_for_alias(alias: str) -> dict[str, Any]:
    alias_key = _normalize_alias(alias)
    if not alias_key:
        return {"ok": False, "detail": "alias is required"}
    try:
        identity_handle = _identity_handle_for_alias(alias_key)
        key_package = _privacy_client().export_key_package(identity_handle)
        seal_keypair = _seal_keypair_for_alias(alias_key)
        return {
            "ok": True,
            "alias": alias_key,
            "mls_key_package": _b64(key_package),
            "welcome_dh_pub": str(seal_keypair.get("public_key", "") or ""),
        }
    except Exception:
        logger.exception(
            "dm mls key package export failed for %s",
            privacy_log_label(alias_key, label="alias"),
        )
        return {"ok": False, "detail": "dm_mls_key_package_failed"}


def _remember_session(local_alias: str, remote_alias: str, *, role: str, session_handle: int) -> _SessionBinding:
    binding = _SessionBinding(
        session_id=_session_id(local_alias, remote_alias),
        local_alias=_normalize_alias(local_alias),
        remote_alias=_normalize_alias(remote_alias),
        role=str(role or "initiator"),
        session_handle=int(session_handle),
        created_at=int(time.time()),
    )
    with _STATE_LOCK:
        existing = _SESSIONS.get(binding.session_id)
        if existing is not None:
            try:
                _privacy_client().release_dm_session(session_handle)
            except Exception:
                pass
            return existing
        _SESSIONS[binding.session_id] = binding
        _save_state()
    return binding


def _forget_session(local_alias: str, remote_alias: str) -> _SessionBinding | None:
    _load_state()
    with _STATE_LOCK:
        binding = _SESSIONS.pop(_session_id(local_alias, remote_alias), None)
        _save_state()
        return binding


def _lock_dm_format(local_alias: str, remote_alias: str, format_str: str) -> None:
    _load_state()
    with _STATE_LOCK:
        _DM_FORMAT_LOCKS[_session_id(local_alias, remote_alias)] = str(format_str or "").strip().lower()
        _save_state()


def is_dm_locked_to_mls(local_alias: str, remote_alias: str) -> bool:
    _load_state()
    return (
        str(_DM_FORMAT_LOCKS.get(_session_id(local_alias, remote_alias), "") or "").strip().lower()
        == MLS_DM_FORMAT
    )


def _session_binding(local_alias: str, remote_alias: str) -> _SessionBinding:
    _load_state()
    session_id = _session_id(local_alias, remote_alias)
    binding = _SESSIONS.get(session_id)
    if binding is None:
        raise PrivacyCoreError(f"dm session not found for {session_id}")
    return binding


def initiate_dm_session(
    local_alias: str,
    remote_alias: str,
    remote_prekey_bundle: dict,
    responder_dh_pub: str = "",
) -> dict[str, Any]:
    ok, detail = _require_private_transport()
    if not ok:
        return {"ok": False, "detail": detail}
    local_key = _normalize_alias(local_alias)
    remote_key = _normalize_alias(remote_alias)
    remote_key_package_b64 = str(
        (remote_prekey_bundle or {}).get("mls_key_package")
        or (remote_prekey_bundle or {}).get("key_package")
        or ""
    ).strip()
    if not local_key or not remote_key or not remote_key_package_b64:
        return {"ok": False, "detail": "local_alias, remote_alias, and mls_key_package are required"}
    resolved_responder_dh_pub = str(
        responder_dh_pub
        or (remote_prekey_bundle or {}).get("welcome_dh_pub")
        or (remote_prekey_bundle or {}).get("identity_dh_pub_key")
        or ""
    ).strip()
    key_package_handle = 0
    session_handle = 0
    remembered = False
    try:
        identity_handle = _identity_handle_for_alias(local_key)
        key_package_handle = _privacy_client().import_key_package(_unb64(remote_key_package_b64))
        session_handle = _privacy_client().create_dm_session(identity_handle, key_package_handle)
        welcome = _privacy_client().dm_session_welcome(session_handle)
        sealed_welcome = _seal_welcome_for_public_key(welcome, resolved_responder_dh_pub)
        binding = _remember_session(local_key, remote_key, role="initiator", session_handle=session_handle)
        remembered = True
        return {"ok": True, "welcome": _b64(sealed_welcome), "session_id": binding.session_id}
    except Exception:
        logger.exception(
            "dm mls initiate failed for %s -> %s",
            privacy_log_label(local_key, label="alias"),
            privacy_log_label(remote_key, label="alias"),
        )
        return {"ok": False, "detail": "dm_mls_initiate_failed"}
    finally:
        if key_package_handle:
            try:
                _privacy_client().release_key_package(key_package_handle)
            except Exception:
                pass
        if session_handle and not remembered:
            try:
                _privacy_client().release_dm_session(session_handle)
            except Exception:
                pass


def accept_dm_session(
    local_alias: str,
    remote_alias: str,
    welcome_b64: str,
    local_dh_secret: str = "",
) -> dict[str, Any]:
    ok, detail = _require_private_transport()
    if not ok:
        return {"ok": False, "detail": detail}
    local_key = _normalize_alias(local_alias)
    remote_key = _normalize_alias(remote_alias)
    if not local_key or not remote_key or not str(welcome_b64 or "").strip():
        return {"ok": False, "detail": "local_alias, remote_alias, and welcome are required"}
    session_handle = 0
    remembered = False
    try:
        identity_handle = _identity_handle_for_alias(local_key)
        seal_keypair = _seal_keypair_for_alias(local_key)
        welcome = _unseal_welcome_for_private_key(
            _unb64(welcome_b64),
            str(local_dh_secret or seal_keypair.get("private_key") or ""),
        )
        session_handle = _privacy_client().join_dm_session(identity_handle, welcome)
        binding = _remember_session(local_key, remote_key, role="responder", session_handle=session_handle)
        remembered = True
        return {"ok": True, "session_id": binding.session_id}
    except Exception:
        logger.exception(
            "dm mls accept failed for %s <- %s",
            privacy_log_label(local_key, label="alias"),
            privacy_log_label(remote_key, label="alias"),
        )
        return {"ok": False, "detail": "dm_mls_accept_failed"}
    finally:
        if session_handle and not remembered:
            try:
                _privacy_client().release_dm_session(session_handle)
            except Exception:
                pass


def has_dm_session(local_alias: str, remote_alias: str) -> dict[str, Any]:
    ok, detail = _require_private_transport()
    if not ok:
        return {"ok": False, "detail": detail}
    try:
        binding = _session_binding(local_alias, remote_alias)
        return {"ok": True, "exists": True, "session_id": binding.session_id}
    except Exception:
        return {"ok": True, "exists": False, "session_id": _session_id(local_alias, remote_alias)}


def ensure_dm_session(local_alias: str, remote_alias: str, welcome_b64: str) -> dict[str, Any]:
    ok, detail = _require_private_transport()
    if not ok:
        return {"ok": False, "detail": detail}
    has_session = has_dm_session(local_alias, remote_alias)
    if not has_session.get("ok"):
        return has_session
    if has_session.get("exists"):
        return {"ok": True, "session_id": _session_id(local_alias, remote_alias)}
    return accept_dm_session(local_alias, remote_alias, welcome_b64)


def _session_expired_result(local_alias: str, remote_alias: str) -> dict[str, Any]:
    binding = _forget_session(local_alias, remote_alias)
    session_id = binding.session_id if binding is not None else _session_id(local_alias, remote_alias)
    return {"ok": False, "detail": "session_expired", "session_id": session_id}


def encrypt_dm(local_alias: str, remote_alias: str, plaintext: str) -> dict[str, Any]:
    ok, detail = _require_private_transport()
    if not ok:
        return {"ok": False, "detail": detail}
    plaintext_bytes = str(plaintext or "").encode("utf-8")
    if len(plaintext_bytes) > MAX_DM_PLAINTEXT_SIZE:
        return {"ok": False, "detail": "plaintext exceeds maximum size"}
    try:
        binding = _session_binding(local_alias, remote_alias)
        ciphertext = _privacy_client().dm_encrypt(binding.session_handle, plaintext_bytes)
        _lock_dm_format(local_alias, remote_alias, MLS_DM_FORMAT)
        return {
            "ok": True,
            "ciphertext": _b64(ciphertext),
            # NOTE: nonce is generated for DM envelope compatibility with dm1 format.
            # MLS handles its own nonce/IV internally — this field is not consumed by MLS.
            "nonce": _b64(secrets.token_bytes(12)),
            "session_id": binding.session_id,
        }
    except PrivacyCoreError as exc:
        if "unknown dm session handle" in str(exc).lower():
            return _session_expired_result(local_alias, remote_alias)
        logger.exception(
            "dm mls encrypt failed for %s -> %s",
            privacy_log_label(local_alias, label="alias"),
            privacy_log_label(remote_alias, label="alias"),
        )
        return {"ok": False, "detail": "dm_mls_encrypt_failed"}
    except Exception:
        logger.exception(
            "dm mls encrypt failed for %s -> %s",
            privacy_log_label(local_alias, label="alias"),
            privacy_log_label(remote_alias, label="alias"),
        )
        return {"ok": False, "detail": "dm_mls_encrypt_failed"}


def decrypt_dm(local_alias: str, remote_alias: str, ciphertext_b64: str, nonce_b64: str) -> dict[str, Any]:
    ok, detail = _require_private_transport()
    if not ok:
        return {"ok": False, "detail": detail}
    try:
        binding = _session_binding(local_alias, remote_alias)
        plaintext = _privacy_client().dm_decrypt(binding.session_handle, _unb64(ciphertext_b64))
        _lock_dm_format(local_alias, remote_alias, MLS_DM_FORMAT)
        return {
            "ok": True,
            "plaintext": plaintext.decode("utf-8"),
            "session_id": binding.session_id,
            "nonce": str(nonce_b64 or ""),
        }
    except PrivacyCoreError as exc:
        if "unknown dm session handle" in str(exc).lower():
            return _session_expired_result(local_alias, remote_alias)
        logger.exception(
            "dm mls decrypt failed for %s <- %s",
            privacy_log_label(local_alias, label="alias"),
            privacy_log_label(remote_alias, label="alias"),
        )
        return {"ok": False, "detail": "dm_mls_decrypt_failed"}
    except Exception:
        logger.exception(
            "dm mls decrypt failed for %s <- %s",
            privacy_log_label(local_alias, label="alias"),
            privacy_log_label(remote_alias, label="alias"),
        )
        return {"ok": False, "detail": "dm_mls_decrypt_failed"}
