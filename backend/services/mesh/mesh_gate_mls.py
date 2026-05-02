"""MLS-backed gate confidentiality path.

Gate encryption now routes exclusively through privacy-core. This module keeps
the gate -> MLS mapping and confidentiality state in Python while Rust owns the
actual MLS group state.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import math
import secrets
import struct
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from services.mesh.mesh_local_custody import (
    read_sensitive_domain_json,
    write_sensitive_domain_json,
)
from services.mesh.mesh_secure_storage import (
    read_secure_json,
)
from services.mesh.mesh_privacy_logging import privacy_log_label
from services.mesh.mesh_wormhole_persona import (
    bootstrap_wormhole_persona_state,
    get_active_gate_identity,
    read_wormhole_persona_state,
    sign_gate_persona_blob,
    sign_gate_session_blob,
    sign_gate_wormhole_event,
    verify_gate_persona_blob,
    verify_gate_session_blob,
)
from services.privacy_core_client import PrivacyCoreClient, PrivacyCoreError

logger = logging.getLogger(__name__)

import os as _os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM as _AESGCM

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
STATE_FILE = DATA_DIR / "wormhole_gate_mls.json"
STATE_FILENAME = "wormhole_gate_mls.json"
STATE_DOMAIN = "gate_persona"
RUST_GATE_STATE_DOMAIN = "gate_rust"
MLS_GATE_FORMAT = "mls1"
STATE_CUSTODY_SCOPE = "gate_mls_binding_store"


class GateSecretUnavailableError(Exception):
    """Raised when gate-secret resolution fails or returns empty.

    New envelope encryption must not silently fall back to the Phase-1
    gate-name-only key derivation.  Callers should catch this and either
    skip the durable envelope (MLS-only) or surface a structured failure.
    """


def _gate_envelope_key_shared(gate_id: str, gate_secret: str) -> bytes:
    """Derive a 256-bit AES key for gate envelope encryption.

    Sprint 1 / Rec #6: the legacy gate-name-only derivation has been
    removed. A non-empty ``gate_secret`` is required; passing an empty
    secret is a programming error and raises GateSecretUnavailableError.
    """
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives import hashes

    if not gate_secret:
        raise GateSecretUnavailableError(
            f"gate secret required for {privacy_log_label(gate_id, label='gate')} — "
            "legacy gate-name-only envelope key has been removed"
        )
    gate_key = gate_id.strip().lower()
    ikm = gate_secret.encode("utf-8")
    info = f"gate_envelope_aes256gcm|{gate_key}".encode("utf-8")
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"shadowbroker-gate-envelope-v1",
        info=info,
    ).derive(ikm)


def _gate_envelope_key_scoped(gate_id: str, gate_secret: str, *, message_nonce: str) -> bytes:
    """Derive a 256-bit AES key scoped to one gate message envelope."""
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives import hashes

    if not gate_secret:
        raise GateSecretUnavailableError(
            f"gate secret required for {privacy_log_label(gate_id, label='gate')} — "
            "legacy gate-name-only envelope key has been removed"
        )
    nonce_value = str(message_nonce or "").strip()
    if not nonce_value:
        raise GateSecretUnavailableError(
            f"message nonce required for {privacy_log_label(gate_id, label='gate')} envelope scoping"
        )
    gate_key = gate_id.strip().lower()
    ikm = gate_secret.encode("utf-8")
    info = f"gate_envelope_aes256gcm|{gate_key}|{nonce_value}".encode("utf-8")
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"shadowbroker-gate-envelope-v2",
        info=info,
    ).derive(ikm)


def _resolve_gate_secret(gate_id: str) -> str:
    """Look up the per-gate content key from the gate manager.

    Returns the secret string (may be empty if the gate has no secret configured).
    Raises GateSecretUnavailableError if the gate manager lookup itself fails.
    """
    try:
        from services.mesh.mesh_reputation import gate_manager
        secret = gate_manager.get_gate_secret(gate_id)
        if not secret:
            secret = gate_manager.ensure_gate_secret(gate_id)
        return secret
    except Exception as exc:
        raise GateSecretUnavailableError(
            f"gate_manager lookup failed for gate {privacy_log_label(gate_id, label='gate')}"
        ) from exc


def _resolve_gate_secret_archive(gate_id: str) -> dict[str, Any]:
    try:
        from services.mesh.mesh_reputation import gate_manager

        return dict(gate_manager.get_gate_secret_archive(gate_id) or {})
    except Exception:
        return {}


def _resolve_gate_envelope_policy(gate_id: str) -> str:
    """Return the gate envelope policy.

    The per-gate ``envelope_policy`` is the source of truth. If the operator
    (or the seed catalog) has configured a gate for ``envelope_always`` or
    ``envelope_recovery``, that IS the acknowledgment — a gate-level opt-in
    to durable recovery envelopes. A second global runtime gate would be
    redundant and silently downgrades working configurations to
    ``envelope_disabled`` without surfacing any error; that's the exact
    "hostile silent downgrade" pattern this codebase used to perform.
    """
    try:
        from services.mesh.mesh_reputation import gate_manager

        return str(gate_manager.get_envelope_policy(gate_id) or "envelope_disabled")
    except Exception:
        return "envelope_disabled"


def _gate_envelope_encrypt(gate_id: str, plaintext: str, *, message_nonce: str = "") -> str:
    """Encrypt plaintext under the gate secret, scoped to one message when possible.

    Raises GateSecretUnavailableError if the gate secret cannot be resolved
    or is empty — new envelopes must never silently use the Phase-1
    gate-name-only derivation.
    """
    gate_secret = _resolve_gate_secret(gate_id)  # raises on lookup failure
    if not gate_secret:
        raise GateSecretUnavailableError(
            f"gate secret is empty for {privacy_log_label(gate_id, label='gate')} — "
            "refusing Phase-1 fallback for new encryption"
        )
    nonce_value = str(message_nonce or "").strip()
    if nonce_value:
        key = _gate_envelope_key_scoped(gate_id, gate_secret, message_nonce=nonce_value)
        aad = f"gate_envelope|{gate_id}|{nonce_value}".encode("utf-8")
    else:
        key = _gate_envelope_key_shared(gate_id, gate_secret)
        aad = f"gate_envelope|{gate_id}".encode("utf-8")
    nonce = _os.urandom(12)
    ct = _AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), aad)
    return base64.b64encode(nonce + ct).decode("ascii")


def _gate_envelope_hash(token: str) -> str:
    """Return the canonical signed binding for a gate envelope token."""
    token_value = str(token or "").strip()
    if not token_value:
        return ""
    try:
        token_bytes = token_value.encode("ascii")
    except UnicodeEncodeError:
        return ""
    return hashlib.sha256(token_bytes).hexdigest()


def _try_gate_envelope_decrypt(
    gate_id: str,
    gate_secret: str,
    nonce: bytes,
    ct: bytes,
    *,
    message_nonce: str = "",
) -> str | None:
    try:
        nonce_value = str(message_nonce or "").strip()
        if nonce_value:
            scoped_aad = f"gate_envelope|{gate_id}|{nonce_value}".encode("utf-8")
            scoped_key = _gate_envelope_key_scoped(gate_id, gate_secret, message_nonce=nonce_value)
            return _AESGCM(scoped_key).decrypt(nonce, ct, scoped_aad).decode("utf-8")
    except Exception:
        pass
    try:
        aad = f"gate_envelope|{gate_id}".encode("utf-8")
        return _AESGCM(_gate_envelope_key_shared(gate_id, gate_secret)).decrypt(nonce, ct, aad).decode("utf-8")
    except Exception:
        return None


def _archived_gate_secret_allowed(
    archive: dict[str, Any],
    *,
    message_epoch: int = 0,
    event_id: str = "",
) -> bool:
    if not str((archive or {}).get("previous_secret", "") or "").strip():
        return False
    ceiling_epoch = int((archive or {}).get("previous_valid_through_epoch", 0) or 0)
    if message_epoch > 0 and ceiling_epoch > 0:
        return message_epoch <= ceiling_epoch
    ceiling_event_id = str((archive or {}).get("previous_valid_through_event_id", "") or "").strip()
    target_event_id = str(event_id or "").strip()
    return bool(ceiling_event_id and target_event_id and target_event_id == ceiling_event_id)


def _gate_envelope_decrypt(
    gate_id: str,
    token: str,
    *,
    message_nonce: str = "",
    message_epoch: int = 0,
    event_id: str = "",
) -> str | None:
    """Decrypt a gate envelope token using the current scoped derivation first.

    New envelopes are keyed from the gate secret plus the signed message
    nonce so one long-lived gate key no longer directly wraps every recovery
    envelope for the gate. Old per-gate envelopes still decrypt via the
    shared-key fallback so stored recovery material survives upgrade.
    """
    try:
        raw = base64.b64decode(token)
        if len(raw) < 13:
            return None
        nonce, ct = raw[:12], raw[12:]
        try:
            gate_secret = _resolve_gate_secret(gate_id)
        except GateSecretUnavailableError:
            return None
        if not gate_secret:
            return None
        plaintext = _try_gate_envelope_decrypt(
            gate_id,
            gate_secret,
            nonce,
            ct,
            message_nonce=message_nonce,
        )
        if plaintext is not None:
            return plaintext
        archive = _resolve_gate_secret_archive(gate_id)
        if _archived_gate_secret_allowed(
            archive,
            message_epoch=int(message_epoch or 0),
            event_id=str(event_id or ""),
        ):
            previous_secret = str(archive.get("previous_secret", "") or "")
            if previous_secret:
                return _try_gate_envelope_decrypt(
                    gate_id,
                    previous_secret,
                    nonce,
                    ct,
                    message_nonce=message_nonce,
                )
        return None
    except Exception:
        return None


def _stored_legacy_unbound_envelope_allowed(
    gate_id: str,
    event_id: str,
    gate_envelope: str,
) -> bool:
    """Allow old local history whose envelope predates signed envelope_hash.

    This is deliberately limited to an exact event already present in the
    local private gate store. New writes and network ingest still require the
    signed envelope_hash binding before side effects.
    """
    event_key = str(event_id or "").strip()
    envelope_value = str(gate_envelope or "").strip()
    if not event_key or not envelope_value:
        return False
    try:
        from services.mesh.mesh_hashchain import gate_store

        stored = gate_store.get_event(event_key)
        payload = stored.get("payload") if isinstance(stored, dict) else None
        if not isinstance(payload, dict):
            return False
        stored_gate = _stable_gate_ref(str(payload.get("gate", "") or ""))
        if stored_gate != _stable_gate_ref(gate_id):
            return False
        if str(payload.get("gate_envelope", "") or "").strip() != envelope_value:
            return False
        return not str(payload.get("envelope_hash", "") or "").strip()
    except Exception:
        return False
# Self-echo plaintext cache: MLS cannot decrypt messages authored by the same
# member, so we cache plaintext locally after compose.  The TTL must comfortably
# exceed the frontend poll + batch-decrypt round-trip (often 2-5 s under load).
# 300 s keeps self-authored messages readable for the whole session while still
# bounding memory exposure. Long-term durability is intentionally off by
# default; ordinary reads keep plaintext local/in-memory only unless the caller
# is performing an explicit recovery read or the operator deliberately opted
# into durable plaintext retention.
LOCAL_CIPHERTEXT_CACHE_MAX = 128
LOCAL_CIPHERTEXT_CACHE_TTL_S = 300

_CT_BUCKETS = (192, 384, 768, 1536, 3072, 6144)


class _ComposeResult(dict[str, Any]):
    """Dict response with hidden legacy epoch access for in-process callers/tests."""

    def __init__(self, *args: Any, legacy_epoch: int = 0, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._legacy_epoch = int(legacy_epoch or 0)

    def __getitem__(self, key: str) -> Any:
        if key == "epoch":
            return self._legacy_epoch
        return super().__getitem__(key)

    def get(self, key: str, default: Any = None) -> Any:
        if key == "epoch":
            return self._legacy_epoch
        return super().get(key, default)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(data: str | bytes | None) -> bytes:
    if not data:
        return b""
    if isinstance(data, bytes):
        return base64.b64decode(data)
    return base64.b64decode(data.encode("ascii"))


def _pad_ciphertext_raw(raw_ct: bytes) -> bytes:
    """Length-prefix + pad raw ciphertext to the next bucket size."""
    prefixed = struct.pack(">H", len(raw_ct)) + raw_ct
    prefixed_len = len(prefixed)
    for bucket in _CT_BUCKETS:
        if prefixed_len <= bucket:
            return prefixed + (b"\x00" * (bucket - prefixed_len))
    target = (((prefixed_len - 1) // _CT_BUCKETS[-1]) + 1) * _CT_BUCKETS[-1]
    return prefixed + (b"\x00" * (target - prefixed_len))


def _unpad_ciphertext_raw(padded: bytes) -> bytes:
    """Read length prefix and extract original ciphertext."""
    if len(padded) < 2:
        return padded
    original_len = struct.unpack(">H", padded[:2])[0]
    if original_len == 0 or 2 + original_len > len(padded):
        return padded
    return padded[2 : 2 + original_len]


def _stable_gate_ref(gate_id: str) -> str:
    return str(gate_id or "").strip().lower()


def _sender_ref_seed(identity: dict[str, Any]) -> str:
    return str(identity.get("persona_id", "") or identity.get("node_id", "") or "").strip()


def _sender_ref(persona_id: str, msg_id: str) -> str:
    persona_key = str(persona_id or "").strip()
    message_id = str(msg_id or "").strip()
    if not persona_key or not message_id:
        return ""
    return hmac.new(
        persona_key.encode("utf-8"),
        message_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:16]


def _gate_plaintext_persist_enabled() -> bool:
    try:
        from services.config import gate_plaintext_persist_effective

        return bool(gate_plaintext_persist_effective())
    except Exception:
        return False


@dataclass
class _GateMemberBinding:
    persona_id: str
    node_id: str
    label: str
    identity_scope: str
    identity_handle: int
    group_handle: int
    member_ref: int
    is_creator: bool = False
    key_package_handle: int | None = None
    public_bundle: bytes = b""
    binding_signature: str = ""


@dataclass
class _GateBinding:
    gate_id: str
    epoch: int
    root_persona_id: str
    root_group_handle: int
    next_member_ref: int = 1
    members: dict[str, _GateMemberBinding] = field(default_factory=dict)


_STATE_LOCK = threading.RLock()
_PRIVACY_CLIENT: PrivacyCoreClient | None = None
# Rust group state is exported/imported via the privacy-core bridge so gate
# bindings can survive restart. Python-side metadata (bindings, epochs,
# personas) is still persisted via domain storage, and restored bindings fail
# closed if the Rust state cannot be reloaded safely.
_GATE_BINDINGS: dict[str, _GateBinding] = {}
_LOCAL_CIPHERTEXT_CACHE: OrderedDict[
    tuple[str, str, str],
    tuple[str, str, float],
] = OrderedDict()
_HIGH_WATER_EPOCHS: dict[str, int] = {}


def _default_binding_store() -> dict[str, Any]:
    return {
        "version": 1,
        "updated_at": 0,
        "gates": {},
        "high_water_epochs": {},
        "gate_format_locks": {},
    }


def _privacy_client() -> PrivacyCoreClient:
    global _PRIVACY_CLIENT
    if _PRIVACY_CLIENT is None:
        _PRIVACY_CLIENT = PrivacyCoreClient.load()
    return _PRIVACY_CLIENT


def reset_gate_mls_state(*, clear_persistence: bool = True) -> None:
    """Clear in-memory gate -> MLS bindings and optionally persisted Rust state."""

    global _PRIVACY_CLIENT
    with _STATE_LOCK:
        if _PRIVACY_CLIENT is not None:
            try:
                _PRIVACY_CLIENT.reset_all_state()
            except Exception:
                logger.exception("privacy-core reset failed while clearing gate MLS state")
        _GATE_BINDINGS.clear()
        _LOCAL_CIPHERTEXT_CACHE.clear()
        _HIGH_WATER_EPOCHS.clear()
        if clear_persistence:
            _clear_gate_rust_state()


def _gate_personas(gate_id: str) -> list[dict[str, Any]]:
    gate_key = _stable_gate_ref(gate_id)
    bootstrap_wormhole_persona_state()
    state = read_wormhole_persona_state()
    return [dict(item or {}) for item in list(state.get("gate_personas", {}).get(gate_key) or [])]


def _gate_session_identity(gate_id: str) -> dict[str, Any] | None:
    gate_key = _stable_gate_ref(gate_id)
    bootstrap_wormhole_persona_state()
    state = read_wormhole_persona_state()
    session = dict(state.get("gate_sessions", {}).get(gate_key) or {})
    if not session.get("private_key"):
        return None
    return session


def _gate_member_identity_id(identity: dict[str, Any]) -> str:
    persona_id = str(identity.get("persona_id", "") or "").strip()
    if persona_id:
        return persona_id
    node_id = str(identity.get("node_id", "") or "").strip()
    if not node_id:
        raise PrivacyCoreError("gate member identity requires node_id")
    return f"session:{node_id}"


def _gate_member_identity_scope(identity: dict[str, Any]) -> str:
    scope = str(identity.get("scope", "") or "").strip().lower()
    if scope == "gate_persona":
        return "persona"
    return "anonymous"


def _active_gate_member(gate_id: str) -> tuple[dict[str, Any] | None, str]:
    active = get_active_gate_identity(gate_id)
    if not active.get("ok"):
        return None, ""
    return dict(active.get("identity") or {}), str(active.get("source", "") or "")


def _active_gate_persona(gate_id: str) -> dict[str, Any] | None:
    active = get_active_gate_identity(gate_id)
    if not active.get("ok") or str(active.get("source", "") or "") != "persona":
        return None
    return dict(active.get("identity") or {})


def _prune_local_plaintext_cache(now: float) -> None:
    expired_keys = [
        key
        for key, (_plaintext, _reply_to, inserted_at) in _LOCAL_CIPHERTEXT_CACHE.items()
        if now - inserted_at > LOCAL_CIPHERTEXT_CACHE_TTL_S
    ]
    for key in expired_keys:
        _LOCAL_CIPHERTEXT_CACHE.pop(key, None)


def _cache_local_plaintext(
    gate_id: str,
    ciphertext: str,
    sender_ref: str,
    plaintext: str,
    reply_to: str = "",
) -> None:
    now = time.time()
    cache_key = (gate_id, ciphertext, sender_ref)
    with _STATE_LOCK:
        _prune_local_plaintext_cache(now)
        if cache_key not in _LOCAL_CIPHERTEXT_CACHE and len(_LOCAL_CIPHERTEXT_CACHE) >= LOCAL_CIPHERTEXT_CACHE_MAX:
            _LOCAL_CIPHERTEXT_CACHE.popitem(last=False)
        _LOCAL_CIPHERTEXT_CACHE[cache_key] = (plaintext, str(reply_to or "").strip(), now)
        _LOCAL_CIPHERTEXT_CACHE.move_to_end(cache_key)


def _consume_cached_plaintext(
    gate_id: str,
    ciphertext: str,
    sender_ref: str,
) -> tuple[str, str] | None:
    """Non-destructive read so repeated decrypt polls still find the entry."""
    now = time.time()
    cache_key = (gate_id, ciphertext, sender_ref)
    with _STATE_LOCK:
        _prune_local_plaintext_cache(now)
        entry = _LOCAL_CIPHERTEXT_CACHE.get(cache_key)
        if entry is None:
            return None
        plaintext, reply_to, inserted_at = entry
        if now - inserted_at > LOCAL_CIPHERTEXT_CACHE_TTL_S:
            _LOCAL_CIPHERTEXT_CACHE.pop(cache_key, None)
            return None
        _LOCAL_CIPHERTEXT_CACHE.move_to_end(cache_key)
        return plaintext, reply_to


def _peek_cached_plaintext(
    gate_id: str,
    ciphertext: str,
    sender_ref: str,
) -> tuple[str, str] | None:
    now = time.time()
    cache_key = (gate_id, ciphertext, sender_ref)
    with _STATE_LOCK:
        _prune_local_plaintext_cache(now)
        entry = _LOCAL_CIPHERTEXT_CACHE.get(cache_key)
        if entry is None:
            return None
        plaintext, reply_to, inserted_at = entry
        if now - inserted_at > LOCAL_CIPHERTEXT_CACHE_TTL_S:
            _LOCAL_CIPHERTEXT_CACHE.pop(cache_key, None)
            return None
        _LOCAL_CIPHERTEXT_CACHE.move_to_end(cache_key)
        return plaintext, reply_to


def _encode_gate_plaintext_envelope(plaintext: str, epoch: int, reply_to: str = "") -> str:
    payload: dict[str, Any] = {
        "m": str(plaintext or ""),
        "e": int(epoch or 0),
    }
    reply_to_val = str(reply_to or "").strip()
    if reply_to_val:
        payload["r"] = reply_to_val
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def _decode_gate_plaintext_envelope(raw: str, fallback_epoch: int) -> tuple[str, int, str]:
    try:
        envelope = json.loads(raw)
        if isinstance(envelope, dict):
            plaintext = str(envelope.get("m", raw))
            epoch = int(envelope.get("e", fallback_epoch) or fallback_epoch)
            reply_to = str(envelope.get("r", "") or "").strip()
            return plaintext, epoch, reply_to
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    return raw, int(fallback_epoch or 0), ""


def _load_binding_store() -> dict[str, Any]:
    # KNOWN LIMITATION: Persistence integrity depends on the gate_persona domain key.
    # Cross-domain compromise no longer follows from a single derived root key,
    # but any process that can read this domain's key envelope can still forge this file.
    domain_path = DATA_DIR / STATE_DOMAIN / STATE_FILENAME
    if not domain_path.exists() and STATE_FILE.exists():
        try:
            legacy = read_secure_json(STATE_FILE, _default_binding_store)
            write_sensitive_domain_json(
                STATE_DOMAIN,
                STATE_FILENAME,
                legacy,
                custody_scope=STATE_CUSTODY_SCOPE,
            )
            STATE_FILE.unlink(missing_ok=True)
        except Exception:
            logger.warning(
                "Legacy gate MLS binding store could not be decrypted — "
                "discarding stale file and starting fresh"
            )
            STATE_FILE.unlink(missing_ok=True)
    raw = read_sensitive_domain_json(
        STATE_DOMAIN,
        STATE_FILENAME,
        _default_binding_store,
        custody_scope=STATE_CUSTODY_SCOPE,
    )
    state = _default_binding_store()
    if isinstance(raw, dict):
        state.update(raw)
    state["version"] = int(state.get("version", 1) or 1)
    state["updated_at"] = int(state.get("updated_at", 0) or 0)
    state["gates"] = {
        _stable_gate_ref(gate_id): dict(item or {})
        for gate_id, item in dict(state.get("gates") or {}).items()
    }
    state["high_water_epochs"] = {
        _stable_gate_ref(gate_id): int(epoch or 0)
        for gate_id, epoch in dict(state.get("high_water_epochs") or {}).items()
    }
    state["gate_format_locks"] = {
        _stable_gate_ref(gate_id): str(payload_format or "").strip().lower()
        for gate_id, payload_format in dict(state.get("gate_format_locks") or {}).items()
        if str(payload_format or "").strip().lower()
    }
    return state


def _save_binding_store(state: dict[str, Any]) -> None:
    # KNOWN LIMITATION: Persistence integrity depends on the gate_persona domain key.
    # Cross-domain compromise no longer follows from a single derived root key,
    # but any process that can read this domain's key envelope can still forge this file.
    payload = dict(state)
    payload["updated_at"] = int(time.time())
    write_sensitive_domain_json(
        STATE_DOMAIN,
        STATE_FILENAME,
        payload,
        custody_scope=STATE_CUSTODY_SCOPE,
    )
    STATE_FILE.unlink(missing_ok=True)


def _rust_gate_state_filename(gate_id: str) -> str:
    gate_key = _stable_gate_ref(gate_id)
    safe_id = hashlib.sha256(gate_key.encode("utf-8")).hexdigest()[:16]
    return f"gate_rust_{safe_id}.bin"


def _read_gate_rust_state_snapshot(gate_id: str) -> dict[str, Any] | None:
    gate_key = _stable_gate_ref(gate_id)
    return read_sensitive_domain_json(
        RUST_GATE_STATE_DOMAIN,
        _rust_gate_state_filename(gate_key),
        lambda: None,
        custody_scope=f"gate_mls_rust_state::{gate_key}",
    )


def _write_gate_rust_state_snapshot(gate_id: str, payload: dict[str, Any] | None) -> None:
    gate_key = _stable_gate_ref(gate_id)
    if payload is None:
        _clear_gate_rust_state(gate_key)
        return
    write_sensitive_domain_json(
        RUST_GATE_STATE_DOMAIN,
        _rust_gate_state_filename(gate_key),
        payload,
        custody_scope=f"gate_mls_rust_state::{gate_key}",
    )


def _save_gate_rust_state(binding: _GateBinding) -> None:
    """Export Rust gate state blob for a single gate and persist via domain storage."""
    try:
        identity_handles = []
        group_handles = []
        seen_ids = set()
        for member in binding.members.values():
            if member.identity_handle not in seen_ids:
                identity_handles.append(member.identity_handle)
                seen_ids.add(member.identity_handle)
            if member.group_handle > 0:
                group_handles.append(member.group_handle)
        if binding.root_group_handle > 0 and binding.root_group_handle not in group_handles:
            group_handles.append(binding.root_group_handle)
        if not identity_handles or not group_handles:
            return
        blob = _privacy_client().export_gate_state(identity_handles, group_handles)
        if blob:
            write_sensitive_domain_json(
                RUST_GATE_STATE_DOMAIN,
                _rust_gate_state_filename(binding.gate_id),
                {"version": 1, "blob_b64": _b64(blob)},
                custody_scope=f"gate_mls_rust_state::{_stable_gate_ref(binding.gate_id)}",
            )
    except Exception:
        logger.warning(
            "failed to export Rust gate state for %s",
            privacy_log_label(binding.gate_id, label="gate"),
            exc_info=True,
        )


def _load_gate_rust_state(gate_id: str, binding: _GateBinding) -> bool:
    """Import persisted Rust gate state and remap Python binding handles.

    Returns True if Rust state was successfully imported and handles remapped.
    Returns False if no Rust state was found (legacy/fresh install).
    Raises on corruption or version mismatch (caller must handle).
    """
    gate_key = _stable_gate_ref(gate_id)
    filename = _rust_gate_state_filename(gate_key)
    raw = read_sensitive_domain_json(
        RUST_GATE_STATE_DOMAIN,
        filename,
        lambda: None,
        custody_scope=f"gate_mls_rust_state::{gate_key}",
    )
    if raw is None:
        return False
    if not isinstance(raw, dict) or raw.get("version") != 1 or not raw.get("blob_b64"):
        raise PrivacyCoreError("persisted Rust gate state has invalid format or version")
    blob = _unb64(raw["blob_b64"])
    mapping = _privacy_client().import_gate_state(blob)
    id_map = {int(k): int(v) for k, v in (mapping.get("identities") or {}).items()}
    group_map = {int(k): int(v) for k, v in (mapping.get("groups") or {}).items()}
    # Remap root_group_handle.
    if binding.root_group_handle in group_map:
        binding.root_group_handle = group_map[binding.root_group_handle]
    # Remap per-member handles.
    for member in binding.members.values():
        if member.identity_handle in id_map:
            member.identity_handle = id_map[member.identity_handle]
        if member.group_handle in group_map:
            member.group_handle = group_map[member.group_handle]
    return True


def _clear_gate_rust_state(gate_id: str | None = None) -> None:
    """Delete persisted Rust gate state blob(s).

    If gate_id is provided, delete only that gate's blob.
    If gate_id is None, delete all gate Rust state blobs.
    """
    try:
        domain_dir = DATA_DIR / RUST_GATE_STATE_DOMAIN
        if not domain_dir.exists():
            return
        if gate_id:
            (domain_dir / _rust_gate_state_filename(gate_id)).unlink(missing_ok=True)
        else:
            for f in domain_dir.glob("gate_rust_*.bin"):
                f.unlink(missing_ok=True)
    except Exception:
        logger.debug("failed to clear persisted Rust gate state", exc_info=True)


def _serialize_member_binding(member: _GateMemberBinding) -> dict[str, Any]:
    return {
        "persona_id": member.persona_id,
        "node_id": member.node_id,
        "label": member.label,
        "identity_scope": member.identity_scope,
        "member_ref": int(member.member_ref),
        "is_creator": bool(member.is_creator),
        "public_bundle": _b64(member.public_bundle),
        "binding_signature": member.binding_signature,
        "identity_handle": int(member.identity_handle),
        "group_handle": int(member.group_handle),
    }


def _persist_binding(binding: _GateBinding) -> None:
    for persona_id, member in binding.members.items():
        if member.identity_scope == "anonymous":
            ok, reason = verify_gate_session_blob(
                binding.gate_id,
                member.node_id,
                member.public_bundle,
                member.binding_signature,
            )
        else:
            ok, reason = verify_gate_persona_blob(
                binding.gate_id,
                persona_id,
                member.public_bundle,
                member.binding_signature,
            )
        if not ok:
            logger.warning(
                "Skipping MLS binding persistence for %s member %s: binding proof invalid",
                privacy_log_label(binding.gate_id, label="gate"),
                privacy_log_label(member.node_id if member.identity_scope == "anonymous" else persona_id, label="member"),
            )
            return
    state = _load_binding_store()
    state.setdefault("gates", {})[binding.gate_id] = {
        "gate_id": binding.gate_id,
        "epoch": int(binding.epoch),
        "root_persona_id": binding.root_persona_id,
        "root_group_handle": int(binding.root_group_handle),
        "next_member_ref": int(binding.next_member_ref),
        "members": {
            persona_id: _serialize_member_binding(member)
            for persona_id, member in binding.members.items()
        },
    }
    high_water = max(
        int(binding.epoch),
        int(_HIGH_WATER_EPOCHS.get(binding.gate_id, 0) or 0),
    )
    _HIGH_WATER_EPOCHS[binding.gate_id] = high_water
    state.setdefault("high_water_epochs", {})[binding.gate_id] = high_water
    _save_binding_store(state)
    _save_gate_rust_state(binding)


def _persist_delete_binding(gate_id: str) -> None:
    state = _load_binding_store()
    gate_key = _stable_gate_ref(gate_id)
    state.setdefault("gates", {}).pop(gate_key, None)
    state.setdefault("high_water_epochs", {}).pop(gate_key, None)
    _HIGH_WATER_EPOCHS.pop(gate_key, None)
    _save_binding_store(state)
    _clear_gate_rust_state(gate_key)


def inspect_local_gate_state(gate_id: str, *, expected_epoch: int = 0) -> dict[str, Any]:
    gate_key = _stable_gate_ref(gate_id)
    if not gate_key:
        return {
            "ok": False,
            "gate_id": "",
            "repair_state": "gate_state_stale",
            "detail": "gate_id required",
            "repairable": False,
            "has_metadata": False,
            "has_rust_state": False,
            "has_local_access": False,
            "current_epoch": 0,
            "identity_scope": "",
        }

    metadata = _persisted_gate_metadata(gate_key) or {}
    rust_state = _read_gate_rust_state_snapshot(gate_key)
    active_identity, active_source = _active_gate_member(gate_key)
    identity_scope = "anonymous" if active_source == "anonymous" else "persona"
    current_epoch = int(metadata.get("epoch", 0) or 0)
    has_metadata = bool(metadata)
    has_rust_state = isinstance(rust_state, dict) and bool(rust_state.get("blob_b64"))
    has_local_access = False
    member_identity_id = ""
    if active_identity:
        member_identity_id = _gate_member_identity_id(active_identity)
        with _STATE_LOCK:
            binding = _GATE_BINDINGS.get(gate_key)
        if binding is not None:
            has_local_access = member_identity_id in binding.members
            current_epoch = max(current_epoch, int(binding.epoch or 0))
        if not has_local_access and has_metadata:
            members_meta = dict(metadata.get("members") or {})
            has_local_access = member_identity_id in members_meta

    result = {
        "ok": True,
        "gate_id": gate_key,
        "repair_state": "gate_state_ok",
        "detail": "gate access ready",
        "repairable": False,
        "has_metadata": has_metadata,
        "has_rust_state": has_rust_state,
        "has_local_access": has_local_access,
        "current_epoch": current_epoch,
        "expected_epoch": int(expected_epoch or 0),
        "identity_scope": identity_scope,
    }

    if not active_identity:
        result.update(
            {
                "ok": False,
                "repair_state": "gate_state_recovery_only",
                "detail": "no active gate identity",
                "repairable": False,
                "has_local_access": False,
                "identity_scope": "",
            }
        )
        return result

    if int(expected_epoch or 0) > 0 and current_epoch > 0 and int(expected_epoch or 0) != current_epoch:
        result.update(
            {
                "ok": False,
                "repair_state": "gate_state_stale",
                "detail": "gate state epoch mismatch",
                "repairable": True,
            }
        )
        return result

    if not has_metadata:
        result.update(
            {
                "ok": False,
                "repair_state": "gate_state_stale",
                "detail": "local gate state is missing",
                "repairable": True,
                "has_local_access": False,
            }
        )
        return result

    if not has_rust_state:
        result.update(
            {
                "ok": False,
                "repair_state": "gate_state_stale",
                "detail": "persisted gate state is incomplete",
                "repairable": True,
            }
        )
        return result

    if not has_local_access:
        result.update(
            {
                "ok": False,
                "repair_state": "gate_state_stale",
                "detail": "active gate identity is not mapped into the MLS group",
                "repairable": True,
            }
        )
        return result

    return result


def resync_local_gate_state(gate_id: str, *, reason: str = "automatic_resync") -> dict[str, Any]:
    gate_key = _stable_gate_ref(gate_id)
    if not gate_key:
        return {"ok": False, "gate_id": "", "detail": "gate_id required", "reason": str(reason or "automatic_resync")}

    store_backup = _load_binding_store()
    rust_backup = _read_gate_rust_state_snapshot(gate_key)
    client = _privacy_client()

    with _STATE_LOCK:
        existing = _GATE_BINDINGS.pop(gate_key, None)
    if existing is not None:
        try:
            _release_binding(client, existing)
        except Exception:
            logger.exception(
                "Failed to release in-memory gate binding before resync for %s",
                privacy_log_label(gate_key, label="gate"),
            )

    _persist_delete_binding(gate_key)

    try:
        binding = _sync_binding(gate_key)
        return {
            "ok": True,
            "gate_id": gate_key,
            "epoch": int(binding.epoch),
            "detail": "gate MLS state synchronized",
            "reason": str(reason or "automatic_resync"),
        }
    except Exception as exc:
        logger.warning(
            "Gate MLS resync failed for %s; restoring last-known-good state",
            privacy_log_label(gate_key, label="gate"),
            exc_info=True,
        )
        with _STATE_LOCK:
            failed_binding = _GATE_BINDINGS.pop(gate_key, None)
        if failed_binding is not None:
            try:
                _release_binding(client, failed_binding)
            except Exception:
                logger.exception(
                    "Failed to release failed gate binding during rollback for %s",
                    privacy_log_label(gate_key, label="gate"),
                )
        _save_binding_store(store_backup)
        _write_gate_rust_state_snapshot(gate_key, rust_backup)
        return {
            "ok": False,
            "gate_id": gate_key,
            "detail": "gate_state_resync_failed",
            "reason": str(reason or "automatic_resync"),
            "error_detail": str(exc) or type(exc).__name__,
        }


def _force_rebuild_binding(gate_id: str) -> None:
    """Tear down the in-memory and persisted MLS binding for a gate.

    The next call to ``_sync_binding`` will create a fresh MLS group
    with the current set of identities.  The _reader identity is also
    rotated so that each MLS epoch gets a fresh reader key, limiting
    key-custody exposure (Rec #9 remediation).
    """
    gate_key = _stable_gate_ref(gate_id)
    client = _privacy_client()
    with _STATE_LOCK:
        binding = _GATE_BINDINGS.pop(gate_key, None)
        if binding is not None:
            _release_binding(client, binding)
    _persist_delete_binding(gate_key)
    # Rotate the _reader identity so the new epoch gets a fresh key
    try:
        _ensure_reader_identity(gate_key, rotate=True)
    except Exception:
        pass  # non-fatal — _sync_binding will create one if missing
    logger.info(
        "Forced MLS binding rebuild for %s",
        privacy_log_label(gate_key, label="gate"),
    )


def _persisted_gate_metadata(gate_id: str) -> dict[str, Any] | None:
    state = _load_binding_store()
    metadata = dict(state.get("gates", {}).get(_stable_gate_ref(gate_id)) or {})
    return metadata or None


def _lock_gate_format(gate_id: str, payload_format: str) -> None:
    state = _load_binding_store()
    gate_key = _stable_gate_ref(gate_id)
    state.setdefault("gate_format_locks", {})[gate_key] = str(payload_format or "").strip().lower()
    _save_binding_store(state)


def is_gate_locked_to_format(gate_id: str, payload_format: str) -> bool:
    gate_key = _stable_gate_ref(gate_id)
    locked_format = str(
        _load_binding_store().get("gate_format_locks", {}).get(gate_key, "") or ""
    ).strip().lower()
    return bool(locked_format) and locked_format == str(payload_format or "").strip().lower()


def is_gate_locked_to_mls(gate_id: str) -> bool:
    gate_key = _stable_gate_ref(gate_id)
    if not gate_key:
        return False
    locked_format = str(
        _load_binding_store().get("gate_format_locks", {}).get(gate_key, MLS_GATE_FORMAT) or MLS_GATE_FORMAT
    ).strip().lower()
    return locked_format == MLS_GATE_FORMAT


def get_local_gate_key_status(gate_id: str) -> dict[str, Any]:
    gate_key = _stable_gate_ref(gate_id)
    if not gate_key:
        return {"ok": False, "detail": "gate_id required"}
    active = get_active_gate_identity(gate_key)
    if not active.get("ok"):
        return {
            "ok": False,
            "gate_id": gate_key,
            "detail": str(active.get("detail") or "no active gate identity"),
        }
    source = str(active.get("source", "") or "")
    identity = dict(active.get("identity") or {})
    metadata = _persisted_gate_metadata(gate_key) or {}
    member_key = _gate_member_identity_id(identity)
    has_local_access = False
    try:
        binding = _sync_binding(gate_key)
        has_local_access = binding.members.get(member_key) is not None
    except Exception:
        has_local_access = False
    if not has_local_access:
        # Identity may have rotated — force rebuild and retry once.
        try:
            _force_rebuild_binding(gate_key)
            binding = _sync_binding(gate_key)
            pid = _gate_member_identity_id(identity)
            has_local_access = pid in binding.members
            if not has_local_access:
                logger.warning(
                    "Gate status: identity %s not in binding members %s",
                    pid,
                    list(binding.members.keys()),
                )
        except Exception as exc:
            logger.warning("Gate status rebuild failed: %s", exc)
            has_local_access = False
    return {
        "ok": True,
        "gate_id": gate_key,
        "current_epoch": int(metadata.get("epoch", 1) or 1),
        "has_local_access": has_local_access,
        "identity_scope": "anonymous" if source == "anonymous" else "persona",
        "identity_node_id": str(identity.get("node_id", "") or ""),
        "identity_persona_id": str(identity.get("persona_id", "") or ""),
        "detail": "gate access ready" if has_local_access else "active gate identity is not mapped into the MLS group",
        "format": MLS_GATE_FORMAT,
    }


def export_gate_state_snapshot(gate_id: str) -> dict[str, Any]:
    """Export opaque gate MLS state for native client-side gate operations.

    The response includes only the Rust MLS state blob plus the legacy handles
    needed to remap imported group handles on the native client. It does not
    return plaintext, durable envelopes, or gate secrets.
    """
    gate_key = _stable_gate_ref(gate_id)
    if not gate_key:
        return {"ok": False, "detail": "gate_id required"}
    try:
        binding = _sync_binding(gate_key)
        active_identity, active_source = _active_gate_member(gate_key)
        identity_handles: list[int] = []
        group_handles: list[int] = []
        seen_identity_handles: set[int] = set()
        members: list[dict[str, Any]] = []
        for member in binding.members.values():
            if member.identity_handle not in seen_identity_handles:
                identity_handles.append(member.identity_handle)
                seen_identity_handles.add(member.identity_handle)
            if member.group_handle > 0:
                group_handles.append(member.group_handle)
                members.append(
                    {
                        "persona_id": member.persona_id,
                        "node_id": member.node_id,
                        "identity_scope": member.identity_scope,
                        "group_handle": int(member.group_handle),
                    }
                )
        if binding.root_group_handle > 0 and binding.root_group_handle not in group_handles:
            group_handles.append(binding.root_group_handle)
        if not identity_handles or not group_handles:
            return {"ok": False, "detail": "gate_state_export_empty"}
        blob = _privacy_client().export_gate_state(identity_handles, group_handles)
        return {
            "ok": True,
            "gate_id": gate_key,
            "epoch": int(binding.epoch),
            "rust_state_blob_b64": _b64(blob),
            "members": members,
            "active_identity_scope": "anonymous" if active_source == "anonymous" else "persona",
            "active_persona_id": str((active_identity or {}).get("persona_id", "") or ""),
            "active_node_id": str((active_identity or {}).get("node_id", "") or ""),
        }
    except Exception:
        logger.exception(
            "MLS gate state export failed for %s",
            privacy_log_label(gate_key, label="gate"),
        )
        return {"ok": False, "detail": "gate_state_export_failed"}


def ensure_gate_member_access(
    *,
    gate_id: str,
    recipient_node_id: str,
    recipient_dh_pub: str,
    recipient_scope: str = "member",
) -> dict[str, Any]:
    gate_key = _stable_gate_ref(gate_id)
    recipient_node_id = str(recipient_node_id or "").strip()
    if not gate_key or not recipient_node_id:
        return {"ok": False, "detail": "gate_id and recipient_node_id required"}
    personas = _gate_personas(gate_key)
    recipient = next(
        (
            persona
            for persona in personas
            if str(persona.get("node_id", "") or "").strip() == recipient_node_id
        ),
        None,
    )
    if recipient is None:
        return {"ok": False, "detail": "recipient identity is not a known gate member"}
    binding = _sync_binding(gate_key)
    return {
        "ok": True,
        "gate_id": gate_key,
        "epoch": int(binding.epoch),
        "recipient_node_id": recipient_node_id,
        "recipient_scope": str(recipient_scope or "member"),
        "format": MLS_GATE_FORMAT,
        "detail": "MLS gate membership is synchronized through privacy-core; no wrapped key required",
    }


def mark_gate_rekey_recommended(gate_id: str, *, reason: str = "manual_review") -> dict[str, Any]:
    gate_key = _stable_gate_ref(gate_id)
    if not gate_key:
        return {"ok": False, "detail": "gate_id required"}
    return {
        "ok": True,
        "gate_id": gate_key,
        "format": MLS_GATE_FORMAT,
        "detail": "MLS gate sessions rekey through membership commits; manual review recorded",
        "reason": str(reason or "manual_review"),
    }


def rotate_gate_epoch(gate_id: str, *, reason: str = "manual_rotate") -> dict[str, Any]:
    gate_key = _stable_gate_ref(gate_id)
    if not gate_key:
        return {"ok": False, "detail": "gate_id required"}
    with _STATE_LOCK:
        _GATE_BINDINGS.pop(gate_key, None)
    binding = _sync_binding(gate_key)
    return {
        "ok": True,
        "gate_id": gate_key,
        "epoch": int(binding.epoch),
        "format": MLS_GATE_FORMAT,
        "detail": "gate MLS state synchronized",
        "reason": str(reason or "manual_rotate"),
    }


def _validate_persisted_member(
    gate_id: str,
    member_meta: dict[str, Any],
    identity: dict[str, Any] | None,
) -> tuple[bool, str]:
    persona_id = str(member_meta.get("persona_id", "") or "")
    identity_scope = str(member_meta.get("identity_scope", "") or "persona").strip().lower()
    if identity is None:
        return False, f"persisted MLS member identity is unknown: {persona_id}"
    if str(identity.get("node_id", "") or "") != str(member_meta.get("node_id", "") or ""):
        return False, f"persisted MLS member node mismatch: {persona_id}"
    try:
        bundle_bytes = _unb64(member_meta.get("public_bundle"))
    except Exception as exc:
        return False, f"persisted MLS bundle decode failed for {persona_id}: {exc}"
    if identity_scope == "anonymous" or persona_id.startswith("session:"):
        ok, reason = verify_gate_session_blob(
            gate_id,
            str(member_meta.get("node_id", "") or ""),
            bundle_bytes,
            str(member_meta.get("binding_signature", "") or ""),
        )
    else:
        if str(identity.get("persona_id", "") or "") != persona_id:
            return False, f"persisted MLS member persona mismatch: {persona_id}"
        ok, reason = verify_gate_persona_blob(
            gate_id,
            persona_id,
            bundle_bytes,
            str(member_meta.get("binding_signature", "") or ""),
        )
    if not ok:
        return False, f"persisted MLS binding proof invalid for {persona_id}: {reason}"
    return True, "ok"


def _try_rust_gate_restore(
    gate_key: str,
    metadata: dict[str, Any],
    ordered_members: list[dict[str, Any]],
    identities_by_id: dict[str, dict[str, Any]],
) -> _GateBinding | None:
    """Attempt to restore a gate binding from persisted Rust state.

    Reconstructs a _GateBinding with fresh Rust handles remapped from persisted
    metadata. Returns None if no Rust state exists or if import fails (caller
    should fall back to the rebuild path).
    """
    root_group_handle = int(metadata.get("root_group_handle", 0) or 0)
    if root_group_handle <= 0:
        return None  # no persisted handles — legacy metadata
    # Build a preliminary binding with old handles from metadata.
    root_persona_id = str(metadata.get("root_persona_id", "") or "")
    binding = _GateBinding(
        gate_id=gate_key,
        epoch=max(1, int(metadata.get("epoch", 1) or 1)),
        root_persona_id=root_persona_id,
        root_group_handle=root_group_handle,
        next_member_ref=int(metadata.get("next_member_ref", 1) or 1),
    )
    for member_meta in ordered_members:
        persona_id = str(member_meta.get("persona_id", "") or "")
        identity_handle = int(member_meta.get("identity_handle", 0) or 0)
        group_handle = int(member_meta.get("group_handle", 0) or 0)
        if identity_handle <= 0:
            return None  # member has no persisted handle — can't restore
        binding.members[persona_id] = _GateMemberBinding(
            persona_id=persona_id,
            node_id=str(member_meta.get("node_id", "") or ""),
            label=str(member_meta.get("label", "") or ""),
            identity_scope=str(member_meta.get("identity_scope", "persona") or "persona"),
            identity_handle=identity_handle,
            group_handle=group_handle,
            member_ref=int(member_meta.get("member_ref", 0) or 0),
            is_creator=bool(member_meta.get("is_creator")),
            public_bundle=_unb64(member_meta.get("public_bundle")),
            binding_signature=str(member_meta.get("binding_signature", "") or ""),
        )
    try:
        loaded = _load_gate_rust_state(gate_key, binding)
        if not loaded:
            return None  # no Rust blob found — fall back to rebuild
        logger.info(
            "Rust gate state restored for %s",
            privacy_log_label(gate_key, label="gate"),
        )
        return binding
    except Exception:
        logger.warning(
            "Persisted Rust gate state is corrupt or incompatible for %s — "
            "invalidating and falling back to rebuild",
            privacy_log_label(gate_key, label="gate"),
            exc_info=True,
        )
        _clear_gate_rust_state(gate_key)
        return None


def _restore_binding_from_metadata(
    gate_id: str,
    identities_by_id: dict[str, dict[str, Any]],
    metadata: dict[str, Any],
) -> _GateBinding | None:
    gate_key = _stable_gate_ref(gate_id)
    members_meta = dict(metadata.get("members") or {})
    if not members_meta:
        return None
    restored_epoch = max(1, int(metadata.get("epoch", 1) or 1))
    persisted_high_water = int(
        _load_binding_store().get("high_water_epochs", {}).get(gate_key, _HIGH_WATER_EPOCHS.get(gate_key, 0)) or 0
    )
    _HIGH_WATER_EPOCHS[gate_key] = max(int(_HIGH_WATER_EPOCHS.get(gate_key, 0) or 0), persisted_high_water)
    if restored_epoch < int(_HIGH_WATER_EPOCHS.get(gate_key, 0) or 0):
        logger.warning(
            "Persisted MLS epoch regressed for %s: restored=%s high_water=%s — rebuilding",
            privacy_log_label(gate_key, label="gate"),
            restored_epoch,
            _HIGH_WATER_EPOCHS.get(gate_key, 0),
        )
        return None
    ordered = sorted(
        members_meta.values(),
        key=lambda item: (
            0 if bool(item.get("is_creator")) else 1,
            int(item.get("member_ref", 0) or 0),
            str(item.get("persona_id", "") or ""),
        ),
    )
    identities: list[dict[str, Any]] = []
    for member_meta in ordered:
        persona_id = str(member_meta.get("persona_id", "") or "")
        identity = identities_by_id.get(persona_id)
        ok, reason = _validate_persisted_member(gate_id, member_meta, identity)
        if not ok:
            logger.warning(
                "Corrupted binding for %s member %s: %s — rebuilding",
                privacy_log_label(gate_key, label="gate"),
                privacy_log_label(persona_id, label="persona"),
                type(reason).__name__ if not isinstance(reason, str) else "binding_invalid",
            )
            state = _load_binding_store()
            gate_entry = dict(state.get("gates", {}).get(gate_key) or {})
            members = dict(gate_entry.get("members") or {})
            members.pop(persona_id, None)
            gate_entry["members"] = members
            if members:
                state.setdefault("gates", {})[gate_key] = gate_entry
            else:
                state.setdefault("gates", {}).pop(gate_key, None)
            _save_binding_store(state)
            return None
        identities.append(dict(identity or {}))

    # Try Rust state restore before falling back to rebuild.
    rust_restored = _try_rust_gate_restore(gate_key, metadata, ordered, identities_by_id)
    if rust_restored is not None:
        _HIGH_WATER_EPOCHS[gate_key] = max(
            int(rust_restored.epoch),
            int(_HIGH_WATER_EPOCHS.get(gate_key, 0) or 0),
        )
        return rust_restored

    rebuilt = _build_binding(gate_id, identities)
    rebuilt.epoch = max(1, int(metadata.get("epoch", rebuilt.epoch) or rebuilt.epoch))
    rebuilt.next_member_ref = max(
        int(metadata.get("next_member_ref", rebuilt.next_member_ref) or rebuilt.next_member_ref),
        max((int(item.get("member_ref", 0) or 0) for item in ordered), default=0) + 1,
    )
    for member_meta in ordered:
        persona_id = str(member_meta.get("persona_id", "") or "")
        member = rebuilt.members.get(persona_id)
        if member is None:
            continue
        member.member_ref = int(member_meta.get("member_ref", member.member_ref) or member.member_ref)
        member.is_creator = bool(member_meta.get("is_creator"))
    _HIGH_WATER_EPOCHS[gate_key] = max(
        int(rebuilt.epoch),
        int(_HIGH_WATER_EPOCHS.get(gate_key, 0) or 0),
    )
    _persist_binding(rebuilt)
    return rebuilt


def _release_member(client: PrivacyCoreClient, member: _GateMemberBinding) -> None:
    if member.group_handle > 0:
        try:
            client.release_group(member.group_handle)
        except Exception:
            logger.exception(
                "Failed to release MLS group handle for %s",
                privacy_log_label(member.persona_id, label="persona"),
            )
    if member.key_package_handle is not None:
        try:
            client.release_key_package(member.key_package_handle)
        except Exception:
            logger.exception(
                "Failed to release MLS key package handle for %s",
                privacy_log_label(member.persona_id, label="persona"),
            )
    try:
        client.release_identity(member.identity_handle)
    except Exception:
        logger.exception(
            "Failed to release MLS identity handle for %s",
            privacy_log_label(member.persona_id, label="persona"),
        )


def _release_binding(client: PrivacyCoreClient, binding: _GateBinding) -> None:
    for member in list(binding.members.values()):
        _release_member(client, member)


def _create_member_binding(
    client: PrivacyCoreClient,
    *,
    gate_id: str,
    identity: dict[str, Any],
    member_ref: int,
    is_creator: bool,
    group_handle: int | None = None,
) -> _GateMemberBinding:
    identity_handle = client.create_identity()
    public_bundle = client.export_public_bundle(identity_handle)
    identity_scope = _gate_member_identity_scope(identity)
    binding_identity_id = _gate_member_identity_id(identity)
    if identity_scope == "anonymous":
        proof = sign_gate_session_blob(
            gate_id,
            str(identity.get("node_id", "") or ""),
            public_bundle,
        )
    else:
        proof = sign_gate_persona_blob(
            gate_id,
            str(identity.get("persona_id", "") or ""),
            public_bundle,
        )
    if not proof.get("ok"):
        try:
            client.release_identity(identity_handle)
        except Exception:
            logger.exception("Failed to release MLS identity after binding proof failure")
        raise PrivacyCoreError(str(proof.get("detail") or "persona MLS binding proof failed"))
    key_package_handle: int | None = None
    resolved_group_handle = group_handle
    if not is_creator:
        key_package_bytes = client.export_key_package(identity_handle)
        key_package_handle = client.import_key_package(key_package_bytes)
        resolved_group_handle = 0
    elif resolved_group_handle is None:
        resolved_group_handle = client.create_group(identity_handle)

    assert resolved_group_handle is not None
    return _GateMemberBinding(
        persona_id=binding_identity_id,
        node_id=str(identity.get("node_id", "") or ""),
        label=str(identity.get("label", "") or ""),
        identity_scope=identity_scope,
        identity_handle=identity_handle,
        group_handle=resolved_group_handle,
        member_ref=member_ref,
        is_creator=is_creator,
        key_package_handle=key_package_handle,
        public_bundle=public_bundle,
        binding_signature=str(proof.get("signature", "") or ""),
    )


def _build_binding(gate_id: str, identities: list[dict[str, Any]]) -> _GateBinding:
    if not identities:
        raise PrivacyCoreError("no gate identities are available for MLS mapping")

    client = _privacy_client()
    creator = identities[0]
    creator_binding = _create_member_binding(
        client,
        gate_id=gate_id,
        identity=creator,
        member_ref=0,
        is_creator=True,
    )
    binding = _GateBinding(
        gate_id=_stable_gate_ref(gate_id),
        epoch=1,
        root_persona_id=creator_binding.persona_id,
        root_group_handle=creator_binding.group_handle,
        members={creator_binding.persona_id: creator_binding},
    )

    for identity in identities[1:]:
        member_binding: _GateMemberBinding | None = None
        commit_handle = 0
        try:
            member_binding = _create_member_binding(
                client,
                gate_id=gate_id,
                identity=identity,
                member_ref=binding.next_member_ref,
                is_creator=False,
            )
            commit_handle = client.add_member(binding.root_group_handle, member_binding.key_package_handle or 0)
            member_binding.group_handle = client.commit_joined_group_handle(commit_handle, 0)
            binding.members[member_binding.persona_id] = member_binding
            binding.next_member_ref += 1
        except Exception:
            if member_binding is not None:
                _release_member(client, member_binding)
            raise
        finally:
            if commit_handle:
                try:
                    client.release_commit(commit_handle)
                except Exception:
                    pass

    return binding


def _ensure_reader_identity(gate_key: str, *, rotate: bool = False) -> dict[str, Any]:
    """Create or rotate a dedicated reader identity for cross-member MLS decrypt.

    MLS does not let the sender decrypt their own ciphertext.  On a
    single-operator node every message is "from self".  By ensuring
    the MLS group always has at least two members, the non-sender
    member can always decrypt what the sender encrypted — giving
    every gate member (including the author) read access.

    The reader is stored as a gate persona so existing signing
    infrastructure (``sign_gate_persona_blob``) can bind it into the
    MLS group, but it is **never** activated as the event-signing
    persona and is excluded from ``sign_gate_wormhole_event``.

    When ``rotate=True`` (e.g. on binding rebuild / epoch advance),
    the old reader is retired and a fresh one is minted — limiting
    the key-custody window per Rec #9 remediation.
    """
    from services.mesh.mesh_wormhole_persona import (
        _identity_record,          # type: ignore[attr-defined]
        read_wormhole_persona_state,
        _write_wormhole_persona_state,
        bootstrap_wormhole_persona_state,
    )

    bootstrap_wormhole_persona_state()
    state = read_wormhole_persona_state()
    personas = list(state.get("gate_personas", {}).get(gate_key) or [])

    if not rotate:
        for p in personas:
            if str(p.get("label", "") or "") == "_reader":
                return p

    # Retire any existing _reader identities for this gate
    remaining = [p for p in personas if str(p.get("label", "") or "") != "_reader"]
    import secrets as _secrets

    reader_persona_id = f"_reader_{_secrets.token_hex(4)}"
    reader = _identity_record(
        scope="gate_persona",
        gate_id=gate_key,
        persona_id=reader_persona_id,
        label="_reader",
    )
    remaining.append(reader)
    state.setdefault("gate_personas", {})[gate_key] = remaining
    # Ensure _reader is never left as the active persona
    active_pid = str(state.get("active_gate_personas", {}).get(gate_key, "") or "")
    if active_pid.startswith("_reader"):
        state.setdefault("active_gate_personas", {}).pop(gate_key, None)
    _write_wormhole_persona_state(state)
    return reader


def _current_gate_identities(gate_key: str) -> list[dict[str, Any]]:
    personas = _gate_personas(gate_key)
    session_identity = _gate_session_identity(gate_key)
    identities: list[dict[str, Any]] = list(personas)
    if session_identity:
        identities.append(session_identity)
    if len(identities) < 2:
        reader = _ensure_reader_identity(gate_key)
        reader_id = _gate_member_identity_id(reader)
        if not any(_gate_member_identity_id(i) == reader_id for i in identities):
            identities.append(reader)
    return identities


def _sync_binding(gate_id: str) -> _GateBinding:
    gate_key = _stable_gate_ref(gate_id)
    identities = _current_gate_identities(gate_key)
    # Ensure we always have ≥2 members so cross-member MLS decrypt works.
    # MLS does not allow a sender to decrypt their own message — on a
    # single-operator node, every member is "self".  The reader identity
    # is a dedicated second member that exists solely for this purpose.
    if not identities:
        _persist_delete_binding(gate_key)
        raise PrivacyCoreError("no gate identities exist for this gate")

    identities_by_id = {
        _gate_member_identity_id(identity): identity
        for identity in identities
    }
    client = _privacy_client()
    active_identity, _active_source = _active_gate_member(gate_key)
    active_identity_id = _gate_member_identity_id(active_identity) if active_identity else ""

    with _STATE_LOCK:
        binding = _GATE_BINDINGS.get(gate_key)
        if binding is None or binding.root_persona_id not in identities_by_id:
            if binding is not None:
                _release_binding(client, binding)
            metadata = _persisted_gate_metadata(gate_key)
            if metadata:
                restored = _restore_binding_from_metadata(gate_key, identities_by_id, metadata)
                if restored is not None:
                    _GATE_BINDINGS[gate_key] = restored
                    return restored
            ordered_identities = sorted(
                identities,
                key=lambda item: (
                    0 if _gate_member_identity_id(item) == active_identity_id else 1,
                    _gate_member_identity_id(item),
                ),
            )
            binding = _build_binding(gate_key, ordered_identities)
            _GATE_BINDINGS[gate_key] = binding
            _persist_binding(binding)
            return binding

        dirty = False
        removed_persona_ids = [persona_id for persona_id in binding.members if persona_id not in identities_by_id]
        for persona_id in removed_persona_ids:
            member = binding.members.get(persona_id)
            if member is None:
                continue
            if member.is_creator:
                _release_binding(client, binding)
                remaining = [identities_by_id[key] for key in sorted(identities_by_id.keys())]
                rebuilt = _build_binding(gate_key, remaining)
                _GATE_BINDINGS[gate_key] = rebuilt
                _persist_binding(rebuilt)
                return rebuilt

            commit_handle = 0
            try:
                commit_handle = client.remove_member(binding.root_group_handle, member.member_ref)
            finally:
                if commit_handle:
                    try:
                        client.release_commit(commit_handle)
                    except Exception:
                        pass
            _release_member(client, member)
            binding.members.pop(persona_id, None)
            binding.epoch += 1
            dirty = True

        for persona_id, persona in identities_by_id.items():
            if persona_id in binding.members:
                continue
            member_binding: _GateMemberBinding | None = None
            commit_handle = 0
            try:
                member_binding = _create_member_binding(
                    client,
                    gate_id=gate_key,
                    identity=persona,
                    member_ref=binding.next_member_ref,
                    is_creator=False,
                )
                commit_handle = client.add_member(
                    binding.root_group_handle,
                    member_binding.key_package_handle or 0,
                )
                member_binding.group_handle = client.commit_joined_group_handle(commit_handle, 0)
                binding.members[persona_id] = member_binding
                binding.next_member_ref += 1
                binding.epoch += 1
                dirty = True
            except Exception:
                if member_binding is not None:
                    _release_member(client, member_binding)
                raise
            finally:
                if commit_handle:
                    try:
                        client.release_commit(commit_handle)
                    except Exception:
                        pass

        if dirty:
            _persist_binding(binding)
        return binding


def _remove_gate_member_from_state(gate_key: str, member_id: str) -> dict[str, Any]:
    from services.mesh.mesh_wormhole_persona import (
        _write_wormhole_persona_state,
        bootstrap_wormhole_persona_state,
        read_wormhole_persona_state,
    )

    target = str(member_id or "").strip()
    bootstrap_wormhole_persona_state()
    state = read_wormhole_persona_state()
    personas = list(state.get("gate_personas", {}).get(gate_key) or [])
    remaining: list[dict[str, Any]] = []
    removed_persona: dict[str, Any] | None = None
    for persona in personas:
        persona_id = str(persona.get("persona_id", "") or "").strip()
        node_id = str(persona.get("node_id", "") or "").strip()
        if not str(persona.get("label", "") or "").startswith("_reader") and target in {persona_id, node_id}:
            removed_persona = persona
            continue
        remaining.append(persona)
    if removed_persona is not None:
        if remaining:
            state.setdefault("gate_personas", {})[gate_key] = remaining
        else:
            state.setdefault("gate_personas", {}).pop(gate_key, None)
        active_persona_id = str(state.get("active_gate_personas", {}).get(gate_key, "") or "")
        if active_persona_id == str(removed_persona.get("persona_id", "") or ""):
            state.setdefault("active_gate_personas", {}).pop(gate_key, None)
        _write_wormhole_persona_state(state)
        return {
            "ok": True,
            "identity_scope": "persona",
            "persona_id": str(removed_persona.get("persona_id", "") or ""),
            "node_id": str(removed_persona.get("node_id", "") or ""),
        }

    session = dict(state.get("gate_sessions", {}).get(gate_key) or {})
    if session.get("private_key"):
        session_node_id = str(session.get("node_id", "") or "").strip()
        if target in {session_node_id}:
            state.setdefault("gate_sessions", {}).pop(gate_key, None)
            _write_wormhole_persona_state(state)
            return {
                "ok": True,
                "identity_scope": "anonymous",
                "persona_id": "",
                "node_id": session_node_id,
            }

    return {"ok": False, "detail": "gate_member_not_found"}


def remove_gate_member(gate_id: str, member_id: str, *, reason: str = "remove") -> dict[str, Any]:
    gate_key = _stable_gate_ref(gate_id)
    target = str(member_id or "").strip()
    if not gate_key:
        return {"ok": False, "detail": "gate_id required"}
    if not target:
        return {"ok": False, "detail": "member_id required"}

    try:
        binding_before = _sync_binding(gate_key)
    except Exception:
        logger.exception(
            "MLS gate member removal preflight failed for %s",
            privacy_log_label(gate_key, label="gate"),
        )
        return {"ok": False, "detail": "gate_mls_remove_failed"}

    previous_epoch = int(binding_before.epoch or 0)
    previous_valid_through_event_id = ""
    try:
        from services.mesh.mesh_hashchain import gate_store

        latest = gate_store.get_messages(gate_key, limit=1)
        if latest:
            previous_valid_through_event_id = str(latest[0].get("event_id", "") or "")
    except Exception:
        previous_valid_through_event_id = ""

    removed = _remove_gate_member_from_state(gate_key, target)
    if not removed.get("ok"):
        return removed

    try:
        binding_after = _sync_binding(gate_key)
    except Exception:
        logger.exception(
            "MLS gate member removal sync failed for %s",
            privacy_log_label(gate_key, label="gate"),
        )
        return {"ok": False, "detail": "gate_mls_remove_failed"}

    _HIGH_WATER_EPOCHS[gate_key] = max(
        int(binding_after.epoch or 0),
        int(_HIGH_WATER_EPOCHS.get(gate_key, 0) or 0),
    )
    return {
        "ok": True,
        "gate_id": gate_key,
        "member_id": target,
        "identity_scope": str(removed.get("identity_scope", "") or ""),
        "persona_id": str(removed.get("persona_id", "") or ""),
        "node_id": str(removed.get("node_id", "") or ""),
        "reason": str(reason or ""),
        "previous_epoch": previous_epoch,
        "epoch": int(binding_after.epoch or 0),
        "previous_valid_through_event_id": previous_valid_through_event_id,
    }


def _gate_is_solo(binding: "_GateBinding") -> bool:
    """Return True when a gate has no real peers (only the operator + the
    synthetic ``_reader`` identity that exists so MLS encrypt-then-self-decrypt
    works on a single-operator node).

    Phase 3.3: this lets compose_encrypted_gate_message surface a
    ``solo_pending`` flag without refusing the compose. The message still
    encrypts and stores normally; the flag tells the caller "no real peers
    yet — your message is sealed but nobody else can read it until someone
    joins this gate." This is the non-hostile pattern: never refuse, always
    surface the state.
    """

    real_members = 0
    for member in binding.members.values():
        label = str(getattr(member, "label", "") or "")
        if label == "_reader":
            continue
        real_members += 1
        if real_members > 1:
            return False
    return real_members <= 1


def compose_encrypted_gate_message(gate_id: str, plaintext: str, reply_to: str = "") -> dict[str, Any]:
    gate_key = _stable_gate_ref(gate_id)
    plaintext = str(plaintext or "")
    if not gate_key:
        return {"ok": False, "detail": "gate_id required"}
    if not plaintext.strip():
        return {"ok": False, "detail": "plaintext required"}

    active_identity, active_source = _active_gate_member(gate_key)
    if not active_identity:
        return {"ok": False, "detail": "no active gate identity"}
    raw_ts = time.time()
    bucket_s = 60
    ts = float(math.floor(raw_ts / bucket_s) * bucket_s)

    try:
        binding = _sync_binding(gate_key)
        persona_id = _gate_member_identity_id(active_identity)
        member = binding.members.get(persona_id)
        if member is None:
            _force_rebuild_binding(gate_key)
            binding = _sync_binding(gate_key)
            member = binding.members.get(persona_id)
            if member is None:
                return {"ok": False, "detail": "active gate identity is not mapped into the MLS group"}
        plaintext_with_epoch = _encode_gate_plaintext_envelope(
            plaintext,
            int(binding.epoch),
            reply_to,
        )
        ciphertext = _privacy_client().encrypt_group_message(
            member.group_handle,
            plaintext_with_epoch.encode("utf-8"),
        )
    except Exception:
        logger.exception(
            "MLS gate compose failed for %s",
            privacy_log_label(gate_key, label="gate"),
        )
        return {"ok": False, "detail": "gate_mls_compose_failed"}

    message_id = base64.b64encode(secrets.token_bytes(12)).decode("ascii")
    sender_ref = _sender_ref(_sender_ref_seed(active_identity), message_id)
    padded_ct = _pad_ciphertext_raw(ciphertext)
    # Look up envelope policy for this gate.
    _envelope_policy = _resolve_gate_envelope_policy(gate_key)
    # Create a durable gate envelope: the plaintext encrypted under the
    # gate's domain key (AES-256-GCM).  This survives MLS group rebuilds
    # and process restarts.  Only nodes holding the gate domain key can
    # decrypt — outsiders see opaque base64.
    gate_envelope: str = ""
    if _envelope_policy != "envelope_disabled":
        try:
            gate_envelope = _gate_envelope_encrypt(
                gate_key,
                plaintext,
                message_nonce=message_id,
            )
        except GateSecretUnavailableError:
            return {"ok": False, "detail": "gate_envelope_required", "gate_id": gate_key}
        except Exception:
            logger.warning(
                "gate envelope encrypt failed for %s — MLS-only for this message",
                privacy_log_label(gate_key, label="gate"),
            )
            return {"ok": False, "detail": "gate_envelope_encrypt_failed", "gate_id": gate_key}
    # Compute envelope_hash: cryptographic binding of gate_envelope to the
    # signed payload.  SHA-256 of the envelope ciphertext string.
    # envelope_disabled → no envelope → no hash.
    envelope_hash = ""
    if gate_envelope:
        envelope_hash = _gate_envelope_hash(gate_envelope)
    if _envelope_policy != "envelope_disabled" and (not gate_envelope or not envelope_hash):
        return {"ok": False, "detail": "gate_envelope_required", "gate_id": gate_key}
    payload = {
        "gate": gate_key,
        "ciphertext": _b64(padded_ct),
        "nonce": message_id,
        "sender_ref": sender_ref,
        "format": MLS_GATE_FORMAT,
        "epoch": int(binding.epoch),
        "transport_lock": "private_strong",
    }
    reply_to_val = str(reply_to or "").strip()
    if reply_to_val:
        payload["reply_to"] = reply_to_val
    if envelope_hash:
        payload["envelope_hash"] = envelope_hash
    # gate_envelope itself is NOT in the signed payload — envelope_hash binds it.
    signed = sign_gate_wormhole_event(gate_id=gate_key, event_type="gate_message", payload=payload)
    if not signed.get("signature"):
        return {"ok": False, "detail": str(signed.get("detail") or "gate_sign_failed")}
    _HIGH_WATER_EPOCHS[gate_key] = max(
        int(binding.epoch),
        int(_HIGH_WATER_EPOCHS.get(gate_key, 0) or 0),
    )
    _lock_gate_format(gate_key, MLS_GATE_FORMAT)
    # No local plaintext retention: by design, the node only persists the
    # ciphertext on the private hashchain. The author does NOT keep a local
    # plaintext copy of their own message — if the device is compromised
    # later, the attacker can only decrypt messages for epochs the compromised
    # MLS state holds keys for (which excludes the sender's own sending-
    # ratchet output once it has advanced). The sender does still see what
    # they just typed in the compose response (below), so the UI can render
    # the optimistic post; after that, the ciphertext is the only record.
    # Phase 3.3: surface solo-mode without refusing the compose. A gate with
    # no real peers still encrypts and stores normally — the flag is purely
    # advisory so the UI/caller can show "your message is sealed but nobody
    # else can read it until someone joins this gate."
    solo_pending = _gate_is_solo(binding)
    return _ComposeResult(
        {
        "ok": True,
        "gate_id": gate_key,
        "identity_scope": "anonymous" if active_source == "anonymous" else str(signed.get("identity_scope", "") or "gate_persona"),
        "sender_id": str(signed.get("node_id", "") or ""),
        "public_key": str(signed.get("public_key", "") or ""),
        "public_key_algo": str(signed.get("public_key_algo", "") or ""),
        "protocol_version": str(signed.get("protocol_version", "") or ""),
        "sequence": int(signed.get("sequence", 0) or 0),
        "signature": str(signed.get("signature", "") or ""),
        "ciphertext": payload["ciphertext"],
        "nonce": payload["nonce"],
        "sender_ref": sender_ref,
        "format": MLS_GATE_FORMAT,
        "transport_lock": "private_strong",
        "timestamp": ts,
        "gate_envelope": gate_envelope,
        "envelope_hash": envelope_hash,
        "reply_to": reply_to_val,
        "solo_pending": solo_pending,
        # Echo the composer's plaintext back in the compose response so the
        # UI can render the post optimistically on the author's screen. This
        # is NOT persisted, NOT relayed, NOT cached — it only lives in the
        # HTTP response for this single compose call and in the client's
        # local UI state until the page refreshes. After that, the author
        # sees their own post the same way any other member does (KEY LOCKED
        # if their MLS state can't re-derive the sending-ratchet key, which
        # is MLS's forward-secrecy behavior by design).
        "self_plaintext": plaintext,
        },
        legacy_epoch=int(binding.epoch),
    )


def sign_encrypted_gate_message(
    *,
    gate_id: str,
    epoch: int,
    ciphertext: str,
    nonce: str,
    payload_format: str = MLS_GATE_FORMAT,
    reply_to: str = "",
    compat_reply_to: bool = False,
    recovery_plaintext: str = "",
    envelope_hash: str = "",
    transport_lock: str = "private_strong",
) -> dict[str, Any]:
    """Sign an already encrypted gate payload without receiving plaintext."""
    gate_key = _stable_gate_ref(gate_id)
    ciphertext = str(ciphertext or "").strip()
    nonce = str(nonce or "").strip()
    payload_format = str(payload_format or MLS_GATE_FORMAT).strip().lower() or MLS_GATE_FORMAT
    if not gate_key:
        return {"ok": False, "detail": "gate_id required"}
    if not ciphertext:
        return {"ok": False, "detail": "ciphertext required"}
    if not nonce:
        return {"ok": False, "detail": "nonce required"}
    if payload_format != MLS_GATE_FORMAT:
        return {
            "ok": False,
            "detail": "native encrypted gate signing requires MLS format",
            "required_format": MLS_GATE_FORMAT,
            "current_format": payload_format,
        }
    # Tor-style: gate signing is a LOCAL cryptographic operation on
    # already-encrypted ciphertext. It doesn't leak anything by itself —
    # only network release of the signed envelope does, and the release
    # path has its own tier floor that queues until the lane is ready.
    # Proceed with signing at any tier; kick off a background transport
    # warmup (in a worker thread so signing is never blocked) so the
    # release path unblocks as soon as possible.
    try:
        from services.wormhole_supervisor import get_transport_tier, connect_wormhole

        if get_transport_tier() == "public_degraded":
            import threading as _threading

            def _bg_connect() -> None:
                try:
                    connect_wormhole(reason="gate_sign_auto_upgrade")
                except Exception:
                    logger.debug("gate sign background transport kickoff failed", exc_info=True)

            _threading.Thread(target=_bg_connect, name="gate-sign-warmup", daemon=True).start()
    except Exception:
        logger.debug("gate sign transport probe failed", exc_info=True)

    active_identity, active_source = _active_gate_member(gate_key)
    if not active_identity:
        return {"ok": False, "detail": "no active gate identity"}

    try:
        binding = _sync_binding(gate_key)
    except Exception:
        logger.exception(
            "MLS gate sign failed during binding sync for %s",
            privacy_log_label(gate_key, label="gate"),
        )
        return {"ok": False, "detail": "gate_mls_sign_failed"}

    requested_epoch = int(epoch or 0)
    if requested_epoch > 0 and requested_epoch != int(binding.epoch):
        return {
            "ok": False,
            "detail": "gate_state_stale",
            "gate_id": gate_key,
            "current_epoch": int(binding.epoch),
        }

    sender_ref = _sender_ref(_sender_ref_seed(active_identity), nonce)
    payload = {
        "gate": gate_key,
        "ciphertext": ciphertext,
        "nonce": nonce,
        "sender_ref": sender_ref,
        "format": MLS_GATE_FORMAT,
        "epoch": int(binding.epoch),
    }
    transport_lock_val = str(transport_lock or "private_strong").strip().lower() or "private_strong"
    if transport_lock_val != "private_strong":
        return {"ok": False, "detail": "gate encrypted signing requires private_strong transport_lock"}
    payload["transport_lock"] = transport_lock_val
    reply_to_val = str(reply_to or "").strip()
    if reply_to_val and not compat_reply_to:
        return {
            "ok": False,
            "detail": "gate_encrypted_reply_to_hidden_required",
            "gate_id": gate_key,
            "compat_reply_to": False,
        }
    if reply_to_val:
        payload["reply_to"] = reply_to_val
    envelope_policy = _resolve_gate_envelope_policy(gate_key)
    envelope_hash_val = str(envelope_hash or "").strip()
    gate_envelope_val = ""
    recovery_plaintext_val = str(recovery_plaintext or "").strip()
    if recovery_plaintext_val and envelope_policy in {"envelope_always", "envelope_recovery"}:
        try:
            gate_envelope_val = _gate_envelope_encrypt(
                gate_key,
                recovery_plaintext_val,
                message_nonce=nonce,
            )
        except GateSecretUnavailableError:
            return {"ok": False, "detail": "gate_envelope_required", "gate_id": gate_key}
        except Exception:
            logger.exception(
                "gate envelope encrypt failed during encrypted signing for %s",
                privacy_log_label(gate_key, label="gate"),
            )
            return {"ok": False, "detail": "gate_envelope_encrypt_failed", "gate_id": gate_key}
        if not gate_envelope_val:
            return {"ok": False, "detail": "gate_envelope_required", "gate_id": gate_key}
        envelope_hash_val = _gate_envelope_hash(gate_envelope_val)
    if envelope_policy == "envelope_always" and not gate_envelope_val and not envelope_hash_val:
        return {"ok": False, "detail": "gate_envelope_required", "gate_id": gate_key}
    if envelope_hash_val:
        payload["envelope_hash"] = envelope_hash_val
    signed = sign_gate_wormhole_event(
        gate_id=gate_key,
        event_type="gate_message",
        payload=payload,
    )
    if not signed.get("signature"):
        return {"ok": False, "detail": str(signed.get("detail") or "gate_sign_failed")}

    bucket_s = 60
    ts = float(math.floor(time.time() / bucket_s) * bucket_s)
    return {
        "ok": True,
        "gate_id": gate_key,
        "identity_scope": "anonymous" if active_source == "anonymous" else str(signed.get("identity_scope", "") or "gate_persona"),
        "sender_id": str(signed.get("node_id", "") or ""),
        "public_key": str(signed.get("public_key", "") or ""),
        "public_key_algo": str(signed.get("public_key_algo", "") or ""),
        "protocol_version": str(signed.get("protocol_version", "") or ""),
        "sequence": int(signed.get("sequence", 0) or 0),
        "signature": str(signed.get("signature", "") or ""),
        "epoch": int(binding.epoch),
        "ciphertext": ciphertext,
        "nonce": nonce,
        "sender_ref": sender_ref,
        "format": MLS_GATE_FORMAT,
        "transport_lock": transport_lock_val,
        "timestamp": ts,
        "reply_to": reply_to_val,
        "gate_envelope": gate_envelope_val,
        "envelope_hash": envelope_hash_val,
    }


def _stamp_plaintext_on_chain(
    gate_key: str,
    event_id: str,
    plaintext: str,
    reply_to: str = "",
    *,
    allow_persist: bool = False,
) -> None:
    """Best-effort stamp of decrypted plaintext onto the private hashchain."""
    if not allow_persist or not event_id or not plaintext:
        return
    try:
        from services.mesh.mesh_hashchain import gate_store
        gate_store.stamp_local_plaintext(gate_key, event_id, plaintext, reply_to)
    except Exception:
        pass


def decrypt_gate_message_for_local_identity(
    *,
    gate_id: str,
    epoch: int,
    ciphertext: str,
    nonce: str,
    sender_ref: str = "",
    gate_envelope: str = "",
    envelope_hash: str = "",
    recovery_envelope: bool = False,
    event_id: str = "",
) -> dict[str, Any]:
    gate_key = _stable_gate_ref(gate_id)
    if not gate_key or not ciphertext:
        return {"ok": False, "detail": "gate_id and ciphertext required"}

    envelope_policy = _resolve_gate_envelope_policy(gate_key)
    envelope_fast_path_enabled = envelope_policy == "envelope_always" or (
        recovery_envelope and envelope_policy == "envelope_recovery"
    )

    # Fast path: gate envelope (AES-256-GCM under gate domain key) only for
    # explicit recovery reads or gates that intentionally keep the envelope on
    # the ordinary local-read path. No plaintext is stamped to disk.
    if envelope_fast_path_enabled:
        if gate_envelope:
            if not envelope_hash:
                if _stored_legacy_unbound_envelope_allowed(gate_key, event_id, gate_envelope):
                    envelope_hash = _gate_envelope_hash(gate_envelope)
                else:
                    return {"ok": False, "detail": "gate_envelope missing signed envelope_hash"}
            expected = _gate_envelope_hash(gate_envelope)
            legacy_unbound_envelope = bool(
                event_id
                and envelope_hash == expected
                and _stored_legacy_unbound_envelope_allowed(gate_key, event_id, gate_envelope)
            )
            if expected != envelope_hash:
                return {"ok": False, "detail": "gate_envelope integrity check failed"}
            envelope_pt = _gate_envelope_decrypt(
                gate_key,
                gate_envelope,
                message_nonce=str(nonce or ""),
                message_epoch=int(epoch or 0),
                event_id=event_id,
            )
            if envelope_pt is not None:
                return {
                    "ok": True,
                    "gate_id": gate_key,
                    "epoch": int(epoch or 0),
                    "plaintext": envelope_pt,
                    "identity_scope": "gate_envelope",
                    "legacy_unbound_envelope": legacy_unbound_envelope,
                }
        elif envelope_hash:
            return {"ok": False, "detail": "gate_envelope missing but envelope_hash present"}

    # No-local-plaintext policy: we deliberately do NOT consult any disk-
    # persisted plaintext or in-memory self-echo cache. Every read re-decrypts
    # from ciphertext using the current MLS member state. Messages the caller
    # has keys for decrypt normally; messages authored by the caller at an
    # earlier session (or from epochs before they joined) show as locked.
    active_identity, active_source = _active_gate_member(gate_key)
    if not active_identity:
        return {"ok": False, "detail": "no active gate identity"}

    # Try all group members (verifier path): on a single-operator node the
    # sender is also a member, and MLS's own-author limitation means the
    # sender's own group state can't decrypt their authored ciphertext —
    # but a *different* member state on the same node can. This path is
    # pure ciphertext → plaintext with no disk artifact.
    verifier_open = open_gate_ciphertext_for_verifier(
        gate_id=gate_key,
        ciphertext=str(ciphertext),
        format=MLS_GATE_FORMAT,
        epoch=int(epoch or 0),
    )
    if verifier_open.get("ok"):
        verifier_pt = str(verifier_open.get("plaintext", "") or "")
        verifier_rt = str(verifier_open.get("reply_to", "") or "").strip()
        result = {
            "ok": True,
            "gate_id": gate_key,
            "epoch": int(verifier_open.get("epoch", epoch or 0) or 0),
            "plaintext": verifier_pt,
            "identity_scope": active_source if active_source == "anonymous" else "persona",
        }
        if verifier_rt:
            result["reply_to"] = verifier_rt
        return result
    # All MLS members on this node are the author — MLS's sending-ratchet
    # has advanced past this message so no local member state can decrypt
    # it. Under the no-local-plaintext policy this is the expected outcome
    # for your own past messages; the UI will render KEY LOCKED.
    if verifier_open.get("detail") == "gate_mls_self_authored":
        return {
            "ok": False,
            "detail": "gate_mls_self_authored",
            "self_authored": True,
            "identity_scope": active_source if active_source == "anonymous" else "persona",
        }

    try:
        binding = _sync_binding(gate_key)
        persona_id = _gate_member_identity_id(active_identity)
        member = binding.members.get(persona_id)
        if member is None:
            _force_rebuild_binding(gate_key)
            binding = _sync_binding(gate_key)
            member = binding.members.get(persona_id)
            if member is None:
                return {"ok": False, "detail": "active gate identity is not mapped into the MLS group"}
        decrypted_bytes = _privacy_client().decrypt_group_message(
            member.group_handle,
            _unpad_ciphertext_raw(_unb64(ciphertext)),
        )
    except Exception:
        # No-local-plaintext policy: no cache fallback. If MLS can't decrypt
        # the ciphertext for this member state, the message is KEY LOCKED to
        # this caller — which is the correct behavior for an epoch they don't
        # have keys for, or for their own authored messages after MLS advanced
        # the sending ratchet.
        logger.debug(
            "MLS gate decrypt failed for %s (verifier already attempted)",
            privacy_log_label(gate_key, label="gate"),
        )
        return {"ok": False, "detail": "gate_mls_decrypt_failed"}

    raw = decrypted_bytes.decode("utf-8")
    actual_plaintext, decrypted_epoch, decrypted_reply_to = _decode_gate_plaintext_envelope(raw, int(epoch or 0))

    _lock_gate_format(gate_key, MLS_GATE_FORMAT)
    # No plaintext stamped to disk — every read re-decrypts from ciphertext.
    result = {
        "ok": True,
        "gate_id": gate_key,
        "epoch": int(decrypted_epoch or epoch or 0),
        "plaintext": actual_plaintext,
        "identity_scope": "anonymous" if active_source == "anonymous" else "persona",
    }
    if decrypted_reply_to:
        result["reply_to"] = decrypted_reply_to
    return result


def open_gate_ciphertext_for_verifier(
    *,
    gate_id: str,
    ciphertext: str,
    format: str,
    epoch: int,
) -> dict[str, Any]:
    gate_key = _stable_gate_ref(gate_id)
    if not gate_key or not ciphertext:
        return {"ok": False, "detail": "gate_id and ciphertext required"}
    if str(format or "").strip() != MLS_GATE_FORMAT:
        return {"ok": False, "detail": "unsupported gate ciphertext format"}

    with _STATE_LOCK:
        binding = _GATE_BINDINGS.get(gate_key)
    if binding is None:
        try:
            binding = _sync_binding(gate_key)
        except Exception:
            logger.exception(
                "MLS verifier open sync failed for %s",
                privacy_log_label(gate_key, label="gate"),
            )
            return {"ok": False, "detail": "gate_mls_verifier_open_failed"}

    last_error: Exception | None = None
    all_self_authored = True
    decoded = _unpad_ciphertext_raw(_unb64(ciphertext))
    for persona_id, member in list(binding.members.items()):
        try:
            decrypted_bytes = _privacy_client().decrypt_group_message(
                member.group_handle,
                decoded,
            )
            raw = decrypted_bytes.decode("utf-8")
            actual_plaintext, decrypted_epoch, decrypted_reply_to = _decode_gate_plaintext_envelope(
                raw,
                int(epoch or 0),
            )
            _lock_gate_format(gate_key, MLS_GATE_FORMAT)
            result = {
                "ok": True,
                "gate_id": gate_key,
                "epoch": int(decrypted_epoch or epoch or 0),
                "plaintext": actual_plaintext,
                "opened_by_persona_id": persona_id,
                "identity_scope": "verifier",
            }
            if decrypted_reply_to:
                result["reply_to"] = decrypted_reply_to
            return result
        except Exception as exc:
            if "message from self" not in str(exc):
                all_self_authored = False
            last_error = exc
            continue

    if all_self_authored and last_error is not None:
        logger.debug(
            "MLS verifier open: all members are self for %s (self-authored message)",
            privacy_log_label(gate_key, label="gate"),
        )
        return {"ok": False, "detail": "gate_mls_self_authored"}
    logger.error(
        "MLS verifier open failed for %s",
        privacy_log_label(gate_key, label="gate"),
        exc_info=last_error,
    )
    return {"ok": False, "detail": "gate_mls_verifier_open_failed"}
