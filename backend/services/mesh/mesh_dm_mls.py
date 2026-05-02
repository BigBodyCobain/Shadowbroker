"""MLS-backed DM session manager.

This module keeps DM session orchestration in Python while privacy-core owns
the MLS session state. Python-side metadata survives via domain storage, and
Rust session state is exported/imported through the privacy-core bridge so
restart can restore sessions. Restored sessions still fail closed if the
underlying Rust state is stale or invalid.
"""

from __future__ import annotations

import base64
import logging
import secrets
import struct
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from services.mesh.mesh_local_custody import (
    read_sensitive_domain_json,
    write_sensitive_domain_json,
)
from services.mesh.mesh_secure_storage import (
    read_secure_json,
)
from services.mesh.mesh_privacy_policy import (
    TRANSPORT_TIER_ORDER as _TRANSPORT_TIER_ORDER,
    transport_tier_is_sufficient,
)
from services.mesh.mesh_metrics import increment as metrics_inc
from services.mesh.mesh_privacy_logging import privacy_log_label
from services.mesh.mesh_wormhole_persona import sign_dm_alias_blob, verify_dm_alias_blob
from services.privacy_core_client import PrivacyCoreClient, PrivacyCoreError
from services.wormhole_supervisor import (
    connect_wormhole,
    get_wormhole_state,
    transport_tier_from_state,
)

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
STATE_FILE = DATA_DIR / "wormhole_dm_mls.json"
STATE_FILENAME = "wormhole_dm_mls.json"
STATE_DOMAIN = "dm_alias"
STATE_CUSTODY_SCOPE = "dm_mls_state"
RUST_STATE_FILENAME = "wormhole_dm_mls_rust.bin"
RUST_STATE_DOMAIN = "dm_alias_rust"
RUST_STATE_CUSTODY_SCOPE = "dm_mls_rust_state"
_STATE_LOCK = threading.RLock()
_PRIVACY_CLIENT: PrivacyCoreClient | None = None
_STATE_LOADED = False
MLS_DM_FORMAT = "mls1"
MAX_DM_PLAINTEXT_SIZE = 65_536
PAD_MAGIC = b"SBP1"
PAD_HEADER_SIZE = 8  # 4-byte magic + 4-byte uint32 BE length
PAD_BUCKET_STEP = 512

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


def _pad_plaintext(data: bytes) -> bytes:
    """Wrap plaintext in a bucket-padded envelope: SBP1 + uint32BE(len) + data + zero-fill."""
    payload_size = PAD_HEADER_SIZE + len(data)
    # Round up to next PAD_BUCKET_STEP boundary (minimum one full bucket).
    padded_size = ((payload_size + PAD_BUCKET_STEP - 1) // PAD_BUCKET_STEP) * PAD_BUCKET_STEP
    header = PAD_MAGIC + struct.pack(">I", len(data))
    return header + data + b"\x00" * (padded_size - payload_size)


def _unpad_plaintext(data: bytes) -> bytes:
    """Remove bucket-padding envelope. Returns raw bytes unchanged if magic is absent (legacy)."""
    if len(data) < PAD_HEADER_SIZE or data[:4] != PAD_MAGIC:
        return data  # legacy unpadded ciphertext
    original_len = struct.unpack(">I", data[4:8])[0]
    if PAD_HEADER_SIZE + original_len > len(data):
        raise PrivacyCoreError("padded DM plaintext is truncated")
    return data[PAD_HEADER_SIZE : PAD_HEADER_SIZE + original_len]


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
    restored: bool = False


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


# Cooldown on auto-upgrade attempts so we don't thrash connect_wormhole()
# on every DM call when the supervisor is unavailable.
_AUTO_UPGRADE_COOLDOWN_S = 30.0
_last_auto_upgrade_attempt: float = 0.0
_auto_upgrade_lock = threading.Lock()


def _attempt_transport_auto_upgrade() -> str:
    """Best-effort background attempt to bring the wormhole supervisor up.

    Returns the current transport tier after the attempt (or after the
    cooldown, if an attempt was skipped). Never raises — the caller then
    decides whether the resulting tier is high enough to proceed.
    """
    global _last_auto_upgrade_attempt
    with _auto_upgrade_lock:
        now = time.time()
        if (now - _last_auto_upgrade_attempt) < _AUTO_UPGRADE_COOLDOWN_S:
            return _current_transport_tier()
        _last_auto_upgrade_attempt = now
    try:
        connect_wormhole(reason="dm_auto_upgrade")
    except Exception:
        logger.debug("DM auto-upgrade of wormhole supervisor failed", exc_info=True)
    return _current_transport_tier()


def _require_private_transport() -> tuple[bool, str]:
    """Transparent transport gate for DM MLS local operations.

    MLS session setup, encryption, and decryption are purely local actions
    against Rust-held privacy-core state. The *network release* of ciphertext
    has its own tier floor (see ``_dm_send_from_signed_request`` +
    ``_queue_dm_release``) which silently queues until the floor is met — so
    this gate no longer returns a consent-prompt or hostile refusal.

    Instead: if the tier is already sufficient, return it. If not, kick off
    a background warmup so the release path will unblock, and return
    ``(True, current_tier)`` anyway so local MLS work proceeds. The caller
    doesn't see a "needs approval" detail and neither does the user.
    """
    current = _current_transport_tier()
    if transport_tier_is_sufficient(current, "private_control_only"):
        return True, current
    try:
        upgraded = _attempt_transport_auto_upgrade()
    except Exception:
        logger.debug("DM background transport auto-upgrade errored", exc_info=True)
        upgraded = current
    if transport_tier_is_sufficient(upgraded, "private_control_only"):
        logger.info("DM auto-upgraded transport tier to %s", upgraded)
        return True, upgraded
    # Still below floor. Don't refuse — local MLS work is safe at any tier
    # and the outbound release path will queue until the lane is ready.
    return True, upgraded or current


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
                write_sensitive_domain_json(
                    STATE_DOMAIN,
                    STATE_FILENAME,
                    legacy,
                    custody_scope=STATE_CUSTODY_SCOPE,
                )
                STATE_FILE.unlink(missing_ok=True)
            except Exception:
                logger.warning(
                    "Legacy DM MLS state could not be decrypted — "
                    "discarding stale file and starting fresh"
                )
                STATE_FILE.unlink(missing_ok=True)
        raw = read_sensitive_domain_json(
            STATE_DOMAIN,
            STATE_FILENAME,
            _default_state,
            custody_scope=STATE_CUSTODY_SCOPE,
        )
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

        # Attempt to restore Rust DM state and remap handles.
        try:
            restored = _load_rust_dm_state()
            if restored:
                _probe_restored_sessions_locked()
        except Exception:
            logger.warning(
                "Persisted Rust DM state is corrupt or incompatible — "
                "clearing stale sessions",
                exc_info=True,
            )
            _SESSIONS.clear()
            _ALIAS_IDENTITIES.clear()
            _ALIAS_BINDINGS.clear()
            _clear_rust_dm_state()

        _STATE_LOADED = True


def _save_state() -> None:
    with _STATE_LOCK:
        write_sensitive_domain_json(
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
            custody_scope=STATE_CUSTODY_SCOPE,
        )
        STATE_FILE.unlink(missing_ok=True)
        _save_rust_dm_state()


def _save_rust_dm_state() -> None:
    """Export Rust DM state blob and persist it via domain storage."""
    try:
        blob = _privacy_client().export_dm_state()
        if blob:
            write_sensitive_domain_json(
                RUST_STATE_DOMAIN,
                RUST_STATE_FILENAME,
                {"version": 1, "blob_b64": _b64(blob)},
                custody_scope=RUST_STATE_CUSTODY_SCOPE,
            )
    except Exception:
        logger.warning("failed to export Rust DM state for persistence", exc_info=True)


def _load_rust_dm_state() -> bool:
    """Import persisted Rust DM state and remap Python handle metadata.

    Returns True if Rust state was successfully imported and handles remapped.
    Returns False if no Rust state was found (legacy/fresh install).
    Raises on corruption or version mismatch (caller must invalidate).
    """
    raw = read_sensitive_domain_json(
        RUST_STATE_DOMAIN,
        RUST_STATE_FILENAME,
        lambda: None,
        custody_scope=RUST_STATE_CUSTODY_SCOPE,
    )
    if raw is None:
        return False
    if not isinstance(raw, dict) or raw.get("version") != 1 or not raw.get("blob_b64"):
        raise PrivacyCoreError("persisted Rust DM state has invalid format or version")
    blob = _unb64(raw["blob_b64"])
    mapping = _privacy_client().import_dm_state(blob)
    id_map = {int(k): int(v) for k, v in (mapping.get("identities") or {}).items()}
    session_map = {int(k): int(v) for k, v in (mapping.get("dm_sessions") or {}).items()}
    # Remap alias identity handles.
    for alias in list(_ALIAS_IDENTITIES):
        old_handle = _ALIAS_IDENTITIES[alias]
        if old_handle in id_map:
            new_handle = id_map[old_handle]
            _ALIAS_IDENTITIES[alias] = new_handle
            binding = _ALIAS_BINDINGS.get(alias)
            if binding:
                binding["handle"] = int(new_handle)
    # Remap session handles and mark as restored.
    for session_id in list(_SESSIONS):
        binding = _SESSIONS[session_id]
        old_handle = binding.session_handle
        if old_handle in session_map:
            binding.session_handle = session_map[old_handle]
            binding.restored = True
    return True


def _drop_session_binding_locked(session_id: str, *, count_failure: bool) -> _SessionBinding | None:
    binding = _SESSIONS.pop(str(session_id or ""), None)
    if binding is None:
        return None
    try:
        _privacy_client().release_dm_session(binding.session_handle)
    except Exception as exc:
        logger.debug("release_dm_session cleanup failed: %s", type(exc).__name__)
    if count_failure:
        metrics_inc("session_restore_failures")
    return binding


def _probe_restored_sessions_locked() -> None:
    from services.mesh.mesh_rollout_flags import dm_restored_session_boot_probe_enabled

    if not dm_restored_session_boot_probe_enabled():
        return
    restored_ids = sorted(session_id for session_id, binding in _SESSIONS.items() if binding.restored)
    if not restored_ids:
        return

    client = _privacy_client()
    dropped: set[str] = set()
    changed = False
    for session_id in restored_ids:
        if session_id in dropped:
            continue
        binding = _SESSIONS.get(session_id)
        if binding is None or not binding.restored:
            continue
        reverse_id = _session_id(binding.remote_alias, binding.local_alias)
        reverse = _SESSIONS.get(reverse_id)
        if reverse is None or not reverse.restored:
            logger.warning(
                "restored DM session boot probe missing reverse pair for %s",
                privacy_log_label(session_id, label="session"),
            )
            dropped.add(session_id)
            continue
        try:
            before_out = client.dm_session_fingerprint(binding.session_handle)
            before_in = client.dm_session_fingerprint(reverse.session_handle)
            ciphertext = client.dm_encrypt(binding.session_handle, b"\x00")
            plaintext = client.dm_decrypt(reverse.session_handle, ciphertext)
            after_out = client.dm_session_fingerprint(binding.session_handle)
            after_in = client.dm_session_fingerprint(reverse.session_handle)
        except Exception as exc:
            logger.warning(
                "restored DM session boot probe failed for %s <-> %s: %s",
                privacy_log_label(binding.local_alias, label="alias"),
                privacy_log_label(binding.remote_alias, label="alias"),
                type(exc).__name__,
            )
            dropped.update({session_id, reverse_id})
            continue
        if plaintext != b"\x00" or before_out == after_out or before_in == after_in:
            logger.warning(
                "restored DM session boot probe did not advance state for %s <-> %s",
                privacy_log_label(binding.local_alias, label="alias"),
                privacy_log_label(binding.remote_alias, label="alias"),
            )
            dropped.update({session_id, reverse_id})
            continue
        binding.restored = False
        reverse.restored = False
        changed = True

    if dropped:
        for session_id in sorted(dropped):
            if _drop_session_binding_locked(session_id, count_failure=True) is not None:
                changed = True
        _clear_rust_dm_state()
    if changed:
        _save_state()


def _clear_rust_dm_state() -> None:
    """Delete persisted Rust DM state blob."""
    try:
        rust_path = DATA_DIR / RUST_STATE_DOMAIN / RUST_STATE_FILENAME
        rust_path.unlink(missing_ok=True)
    except Exception:
        logger.debug("failed to clear persisted Rust DM state", exc_info=True)


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
        if clear_persistence:
            if STATE_FILE.exists():
                STATE_FILE.unlink()
            _clear_rust_dm_state()


def forget_dm_aliases(aliases: list[str]) -> dict[str, Any]:
    """Remove dedicated DM aliases and any sessions that reference them.

    This is intentionally narrow: production contacts are not touched unless
    the caller passes their exact alias. It exists for local diagnostics that
    need to exercise the MLS path without leaving synthetic peers behind.
    """
    normalized_aliases = {
        _normalize_alias(alias)
        for alias in aliases
        if _normalize_alias(alias)
    }
    if not normalized_aliases:
        return {"ok": True, "aliases_removed": 0, "sessions_removed": 0}
    aliases_removed = 0
    sessions_removed = 0
    with _STATE_LOCK:
        _load_state()
        for session_id, binding in list(_SESSIONS.items()):
            if binding.local_alias in normalized_aliases or binding.remote_alias in normalized_aliases:
                if _drop_session_binding_locked(session_id, count_failure=False) is not None:
                    sessions_removed += 1
                _DM_FORMAT_LOCKS.pop(session_id, None)
        for alias in sorted(normalized_aliases):
            handle = _ALIAS_IDENTITIES.pop(alias, None)
            if handle:
                aliases_removed += 1
                try:
                    _privacy_client().release_identity(handle)
                except Exception as exc:
                    logger.debug("release_identity cleanup failed: %s", type(exc).__name__)
            if _ALIAS_BINDINGS.pop(alias, None) is not None and not handle:
                aliases_removed += 1
            _ALIAS_SEAL_KEYS.pop(alias, None)
        _save_state()
    return {
        "ok": True,
        "aliases_removed": aliases_removed,
        "sessions_removed": sessions_removed,
    }


def _identity_handle_for_alias(alias: str) -> int:
    alias_key = _normalize_alias(alias)
    if not alias_key:
        raise PrivacyCoreError("dm alias is required")
    _load_state()
    with _STATE_LOCK:
        handle = _ALIAS_IDENTITIES.get(alias_key)
        if handle:
            # Probe whether the Rust identity is still live.  After a
            # privacy-core restart the handle may be stale (identity no longer
            # exists in the current process).  If so, fall through to recreate.
            try:
                _privacy_client().export_public_bundle(handle)
                return handle
            except PrivacyCoreError:
                logger.warning(
                    "Stale alias identity handle %d for %s — recreating",
                    handle,
                    privacy_log_label(alias_key, label="alias"),
                )
                # Fall through to create a fresh identity below.

        handle = _privacy_client().create_identity()
        public_bundle = _privacy_client().export_public_bundle(handle)
        signed = sign_dm_alias_blob(alias_key, public_bundle)
        if not signed.get("ok"):
            try:
                _privacy_client().release_identity(handle)
            except Exception as exc:
                logger.debug("release_identity cleanup failed: %s", type(exc).__name__)
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
            except Exception as exc:
                logger.debug("release_dm_session cleanup failed: %s", type(exc).__name__)
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
            except Exception as exc:
                logger.debug("release_key_package cleanup failed: %s", type(exc).__name__)
        if session_handle and not remembered:
            try:
                _privacy_client().release_dm_session(session_handle)
            except Exception as exc:
                logger.debug("release_dm_session cleanup failed: %s", type(exc).__name__)


def accept_dm_session(
    local_alias: str,
    remote_alias: str,
    welcome_b64: str,
    local_dh_secret: str = "",
    identity_alias: str = "",
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
        identity_handle = _identity_handle_for_alias(str(identity_alias or local_key))
        seal_keypair = _seal_keypair_for_alias(local_key)
        welcome_payload = _unb64(welcome_b64)
        welcome = None
        last_unseal_error: Exception | None = None
        candidate_private_keys: list[str] = []
        injected_private_key = str(local_dh_secret or "").strip()
        alias_private_key = str(seal_keypair.get("private_key") or "").strip()
        if injected_private_key:
            candidate_private_keys.append(injected_private_key)
        if alias_private_key and alias_private_key not in candidate_private_keys:
            candidate_private_keys.append(alias_private_key)
        for private_key in candidate_private_keys:
            try:
                welcome = _unseal_welcome_for_private_key(welcome_payload, private_key)
                break
            except Exception as exc:
                last_unseal_error = exc
        if welcome is None:
            if last_unseal_error is not None:
                raise last_unseal_error
            raise ValueError("welcome_private_key_unavailable")
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
            except Exception as exc:
                logger.debug("release_dm_session cleanup failed: %s", type(exc).__name__)


def has_dm_session(local_alias: str, remote_alias: str) -> dict[str, Any]:
    ok, detail = _require_private_transport()
    if not ok:
        return {"ok": False, "detail": detail}
    try:
        binding = _session_binding(local_alias, remote_alias)
        return {"ok": True, "exists": True, "session_id": binding.session_id}
    except Exception:
        return {"ok": True, "exists": False, "session_id": _session_id(local_alias, remote_alias)}


def ensure_dm_session(
    local_alias: str,
    remote_alias: str,
    welcome_b64: str,
    local_dh_secret: str = "",
    identity_alias: str = "",
) -> dict[str, Any]:
    ok, detail = _require_private_transport()
    if not ok:
        return {"ok": False, "detail": detail}
    has_session = has_dm_session(local_alias, remote_alias)
    if not has_session.get("ok"):
        return has_session
    if has_session.get("exists"):
        return {"ok": True, "session_id": _session_id(local_alias, remote_alias)}
    return accept_dm_session(
        local_alias,
        remote_alias,
        welcome_b64,
        local_dh_secret=local_dh_secret,
        identity_alias=identity_alias,
    )


def _session_expired_result(local_alias: str, remote_alias: str) -> dict[str, Any]:
    binding = _forget_session(local_alias, remote_alias)
    session_id = binding.session_id if binding is not None else _session_id(local_alias, remote_alias)
    return {"ok": False, "detail": "session_expired", "session_id": session_id}


def _invalidate_restored_session(local_alias: str, remote_alias: str) -> dict[str, Any]:
    """Fail-closed for a restored session that proved stale/unusable.

    Clears the stale session mapping AND deletes the persisted Rust DM state
    blob so that a corrupt/stale blob cannot be reloaded on next restart.
    """
    result = _session_expired_result(local_alias, remote_alias)
    metrics_inc("session_restore_failures")
    # Delete after _session_expired_result because _forget_session → _save_state
    # re-exports the Rust blob.  The blob is stale, so remove it.
    _clear_rust_dm_state()
    return result


def encrypt_dm(local_alias: str, remote_alias: str, plaintext: str) -> dict[str, Any]:
    ok, detail = _require_private_transport()
    if not ok:
        return {"ok": False, "detail": detail}
    plaintext_bytes = str(plaintext or "").encode("utf-8")
    if len(plaintext_bytes) > MAX_DM_PLAINTEXT_SIZE:
        return {"ok": False, "detail": "plaintext exceeds maximum size"}
    binding: _SessionBinding | None = None
    try:
        binding = _session_binding(local_alias, remote_alias)
        padded = _pad_plaintext(plaintext_bytes)
        ciphertext = _privacy_client().dm_encrypt(binding.session_handle, padded)
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
        if binding is not None and binding.restored:
            logger.warning(
                "restored DM session stale during encrypt for %s -> %s: %s",
                privacy_log_label(local_alias, label="alias"),
                privacy_log_label(remote_alias, label="alias"),
                exc,
            )
            return _invalidate_restored_session(local_alias, remote_alias)
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
    binding: _SessionBinding | None = None
    try:
        binding = _session_binding(local_alias, remote_alias)
        raw_plaintext = _privacy_client().dm_decrypt(binding.session_handle, _unb64(ciphertext_b64))
        plaintext = _unpad_plaintext(raw_plaintext)
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
        if binding is not None and binding.restored:
            logger.warning(
                "restored DM session stale during decrypt for %s <- %s: %s",
                privacy_log_label(local_alias, label="alias"),
                privacy_log_label(remote_alias, label="alias"),
                exc,
            )
            return _invalidate_restored_session(local_alias, remote_alias)
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
