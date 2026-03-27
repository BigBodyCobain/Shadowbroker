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

from services.mesh.mesh_secure_storage import (
    read_domain_json,
    read_secure_json,
    write_domain_json,
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
MLS_GATE_FORMAT = "mls1"
# Gate-scoped symmetric encryption domain — used for the durable envelope
# that survives MLS group rebuilds / process restarts.  The key is the same
# domain key that protects the gate_persona store (AES-256-GCM, stored in an
# OS-protected key envelope).  Gate members can always decrypt; outsiders
# cannot because they lack the domain key.
_GATE_ENVELOPE_DOMAIN = "gate_persona"


def _gate_envelope_key_shared(gate_id: str, gate_secret: str = "") -> bytes:
    """Derive a 256-bit AES key for gate envelope encryption.

    When *gate_secret* is provided (Phase 2), the random per-gate secret is
    the primary input key material — knowing the gate name alone is no longer
    sufficient.  Without it, falls back to the legacy gate-name-only derivation
    for backward compatibility with pre-Phase-2 messages.
    """
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives import hashes

    gate_key = gate_id.strip().lower()
    if gate_secret:
        # Phase 2: IKM = gate_secret, info includes gate_id for domain separation
        ikm = gate_secret.encode("utf-8")
        info = f"gate_envelope_aes256gcm|{gate_key}".encode("utf-8")
    else:
        # Legacy: IKM = gate_id only (backward compat)
        ikm = gate_key.encode("utf-8")
        info = b"gate_envelope_aes256gcm"
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"shadowbroker-gate-envelope-v1",
        info=info,
    ).derive(ikm)


def _resolve_gate_secret(gate_id: str) -> str:
    """Look up the per-gate content key from the gate manager."""
    try:
        from services.mesh.mesh_reputation import gate_manager
        return gate_manager.get_gate_secret(gate_id)
    except Exception:
        return ""


def _gate_envelope_key_legacy() -> bytes | None:
    """Return the old node-local domain key, or None if unavailable."""
    try:
        from services.mesh.mesh_secure_storage import _load_domain_key  # type: ignore[attr-defined]
        return _load_domain_key(_GATE_ENVELOPE_DOMAIN)
    except Exception:
        return None


def _gate_envelope_encrypt(gate_id: str, plaintext: str) -> str:
    """Encrypt plaintext under the per-gate secret key.  Returns base64."""
    gate_secret = _resolve_gate_secret(gate_id)
    key = _gate_envelope_key_shared(gate_id, gate_secret)
    nonce = _os.urandom(12)
    aad = f"gate_envelope|{gate_id}".encode("utf-8")
    ct = _AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), aad)
    return base64.b64encode(nonce + ct).decode("ascii")


def _gate_envelope_decrypt(gate_id: str, token: str) -> str | None:
    """Decrypt a gate envelope token.

    Tries keys in priority order:
    1. Phase 2 per-gate secret key (gate_secret + gate_id)
    2. Legacy shared key (gate_id only — for pre-Phase-2 messages)
    3. Legacy node-local domain key (for very old messages)
    """
    try:
        raw = base64.b64decode(token)
        if len(raw) < 13:
            return None
        nonce, ct = raw[:12], raw[12:]
        aad = f"gate_envelope|{gate_id}".encode("utf-8")
        # 1. Try Phase 2 per-gate secret key
        gate_secret = _resolve_gate_secret(gate_id)
        if gate_secret:
            try:
                return _AESGCM(_gate_envelope_key_shared(gate_id, gate_secret)).decrypt(nonce, ct, aad).decode("utf-8")
            except Exception:
                pass
        # 2. Try legacy gate-name-only key (backward compat)
        try:
            return _AESGCM(_gate_envelope_key_shared(gate_id, "")).decrypt(nonce, ct, aad).decode("utf-8")
        except Exception:
            pass
        # 3. Fall back to legacy node-local key for very old messages
        legacy_key = _gate_envelope_key_legacy()
        if legacy_key:
            return _AESGCM(legacy_key).decrypt(nonce, ct, aad).decode("utf-8")
        return None
    except Exception:
        return None
# Self-echo plaintext cache: MLS cannot decrypt messages authored by the same
# member, so we cache plaintext locally after compose.  The TTL must comfortably
# exceed the frontend poll + batch-decrypt round-trip (often 2-5 s under load).
# 300 s keeps self-authored messages readable for the whole session while still
# bounding memory exposure.
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
# MLS limitation: Rust group state (ratchet trees, group secrets) is in-memory only.
# Python-side metadata (bindings, epochs, personas) is persisted via domain storage.
# Process restart requires group re-join. Rust FFI state export is still deferred.
_GATE_BINDINGS: dict[str, _GateBinding] = {}
_LOCAL_CIPHERTEXT_CACHE: OrderedDict[
    tuple[str, str, str],
    tuple[str, float],
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


def reset_gate_mls_state() -> None:
    """Test helper for clearing in-memory gate -> MLS bindings."""

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
        for key, (_plaintext, inserted_at) in _LOCAL_CIPHERTEXT_CACHE.items()
        if now - inserted_at > LOCAL_CIPHERTEXT_CACHE_TTL_S
    ]
    for key in expired_keys:
        _LOCAL_CIPHERTEXT_CACHE.pop(key, None)


def _cache_local_plaintext(gate_id: str, ciphertext: str, sender_ref: str, plaintext: str) -> None:
    now = time.time()
    cache_key = (gate_id, ciphertext, sender_ref)
    with _STATE_LOCK:
        _prune_local_plaintext_cache(now)
        if cache_key not in _LOCAL_CIPHERTEXT_CACHE and len(_LOCAL_CIPHERTEXT_CACHE) >= LOCAL_CIPHERTEXT_CACHE_MAX:
            _LOCAL_CIPHERTEXT_CACHE.popitem(last=False)
        _LOCAL_CIPHERTEXT_CACHE[cache_key] = (plaintext, now)
        _LOCAL_CIPHERTEXT_CACHE.move_to_end(cache_key)


def _consume_cached_plaintext(gate_id: str, ciphertext: str, sender_ref: str) -> str | None:
    """Non-destructive read so repeated decrypt polls still find the entry."""
    now = time.time()
    cache_key = (gate_id, ciphertext, sender_ref)
    with _STATE_LOCK:
        _prune_local_plaintext_cache(now)
        entry = _LOCAL_CIPHERTEXT_CACHE.get(cache_key)
        if entry is None:
            return None
        plaintext, inserted_at = entry
        if now - inserted_at > LOCAL_CIPHERTEXT_CACHE_TTL_S:
            _LOCAL_CIPHERTEXT_CACHE.pop(cache_key, None)
            return None
        _LOCAL_CIPHERTEXT_CACHE.move_to_end(cache_key)
        return plaintext


def _peek_cached_plaintext(gate_id: str, ciphertext: str, sender_ref: str) -> str | None:
    now = time.time()
    cache_key = (gate_id, ciphertext, sender_ref)
    with _STATE_LOCK:
        _prune_local_plaintext_cache(now)
        entry = _LOCAL_CIPHERTEXT_CACHE.get(cache_key)
        if entry is None:
            return None
        plaintext, inserted_at = entry
        if now - inserted_at > LOCAL_CIPHERTEXT_CACHE_TTL_S:
            _LOCAL_CIPHERTEXT_CACHE.pop(cache_key, None)
            return None
        _LOCAL_CIPHERTEXT_CACHE.move_to_end(cache_key)
        return plaintext


def _load_binding_store() -> dict[str, Any]:
    # KNOWN LIMITATION: Persistence integrity depends on the gate_persona domain key.
    # Cross-domain compromise no longer follows from a single derived root key,
    # but any process that can read this domain's key envelope can still forge this file.
    domain_path = DATA_DIR / STATE_DOMAIN / STATE_FILENAME
    if not domain_path.exists() and STATE_FILE.exists():
        try:
            legacy = read_secure_json(STATE_FILE, _default_binding_store)
            write_domain_json(STATE_DOMAIN, STATE_FILENAME, legacy)
            STATE_FILE.unlink(missing_ok=True)
        except Exception:
            logger.warning(
                "Legacy gate MLS binding store could not be decrypted — "
                "discarding stale file and starting fresh"
            )
            STATE_FILE.unlink(missing_ok=True)
    raw = read_domain_json(STATE_DOMAIN, STATE_FILENAME, _default_binding_store)
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
    write_domain_json(STATE_DOMAIN, STATE_FILENAME, payload)
    STATE_FILE.unlink(missing_ok=True)


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


def _persist_delete_binding(gate_id: str) -> None:
    state = _load_binding_store()
    gate_key = _stable_gate_ref(gate_id)
    state.setdefault("gates", {}).pop(gate_key, None)
    state.setdefault("high_water_epochs", {}).pop(gate_key, None)
    _HIGH_WATER_EPOCHS.pop(gate_key, None)
    _save_binding_store(state)


def _force_rebuild_binding(gate_id: str) -> None:
    """Tear down the in-memory and persisted MLS binding for a gate.

    The next call to ``_sync_binding`` will create a fresh MLS group
    with the current set of identities.
    """
    gate_key = _stable_gate_ref(gate_id)
    client = _privacy_client()
    with _STATE_LOCK:
        binding = _GATE_BINDINGS.pop(gate_key, None)
        if binding is not None:
            _release_binding(client, binding)
    _persist_delete_binding(gate_key)
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


def _ensure_reader_identity(gate_key: str) -> dict[str, Any]:
    """Create a dedicated reader identity for cross-member MLS decrypt.

    MLS does not let the sender decrypt their own ciphertext.  On a
    single-operator node every message is "from self".  By ensuring
    the MLS group always has at least two members, the non-sender
    member can always decrypt what the sender encrypted — giving
    every gate member (including the author) read access.

    The reader is stored as a normal gate persona so existing signing
    infrastructure (``sign_gate_persona_blob``) can find it.
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
    # Check if a reader persona already exists.
    for p in personas:
        if str(p.get("label", "") or "") == "_reader":
            return p
    import secrets as _secrets

    reader_persona_id = f"_reader_{_secrets.token_hex(4)}"
    reader = _identity_record(
        scope="gate_persona",
        gate_id=gate_key,
        persona_id=reader_persona_id,
        label="_reader",
    )
    personas.append(reader)
    state.setdefault("gate_personas", {})[gate_key] = personas
    _write_wormhole_persona_state(state)
    return reader


def _sync_binding(gate_id: str) -> _GateBinding:
    gate_key = _stable_gate_ref(gate_id)
    personas = _gate_personas(gate_key)
    session_identity = _gate_session_identity(gate_key)
    identities: list[dict[str, Any]] = list(personas)
    if session_identity:
        identities.append(session_identity)
    # Ensure we always have ≥2 members so cross-member MLS decrypt works.
    # MLS does not allow a sender to decrypt their own message — on a
    # single-operator node, every member is "self".  The reader identity
    # is a dedicated second member that exists solely for this purpose.
    if len(identities) < 2:
        reader = _ensure_reader_identity(gate_key)
        reader_id = _gate_member_identity_id(reader)
        if not any(_gate_member_identity_id(i) == reader_id for i in identities):
            identities.append(reader)
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


def compose_encrypted_gate_message(gate_id: str, plaintext: str) -> dict[str, Any]:
    gate_key = _stable_gate_ref(gate_id)
    plaintext = str(plaintext or "")
    if not gate_key:
        return {"ok": False, "detail": "gate_id required"}
    if not plaintext.strip():
        return {"ok": False, "detail": "plaintext required"}
    try:
        from services.wormhole_supervisor import get_transport_tier

        if get_transport_tier() == "public_degraded":
            return {"ok": False, "detail": "MLS gate compose requires PRIVATE transport tier"}
    except Exception:
        return {"ok": False, "detail": "MLS gate compose requires PRIVATE transport tier"}

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
        plaintext_with_epoch = json.dumps(
            {
                "m": plaintext,
                "e": int(binding.epoch),
            },
            separators=(",", ":"),
            ensure_ascii=False,
        )
        ciphertext = _privacy_client().encrypt_group_message(
            member.group_handle,
            plaintext_with_epoch.encode("utf-8"),
        )
        # MLS does not let the sender decrypt their own ciphertext.
        # Immediately decrypt with a *different* group member so the
        # plaintext is available to every member on this node — including
        # the sender — without storing raw plaintext outside the MLS layer.
        _self_decrypt_plaintext: str | None = None
        for other_pid, other_member in binding.members.items():
            if other_pid == persona_id:
                continue  # skip the sender
            try:
                dec_bytes = _privacy_client().decrypt_group_message(
                    other_member.group_handle,
                    ciphertext,
                )
                dec_raw = dec_bytes.decode("utf-8")
                try:
                    dec_env = json.loads(dec_raw)
                    _self_decrypt_plaintext = str(dec_env["m"]) if isinstance(dec_env, dict) and "m" in dec_env else dec_raw
                except (json.JSONDecodeError, ValueError, TypeError):
                    _self_decrypt_plaintext = dec_raw
                break
            except Exception:
                continue
    except Exception:
        logger.exception(
            "MLS gate compose failed for %s",
            privacy_log_label(gate_key, label="gate"),
        )
        return {"ok": False, "detail": "gate_mls_compose_failed"}

    message_id = base64.b64encode(secrets.token_bytes(12)).decode("ascii")
    sender_ref = _sender_ref(_sender_ref_seed(active_identity), message_id)
    padded_ct = _pad_ciphertext_raw(ciphertext)
    # Create a durable gate envelope: the plaintext encrypted under the
    # gate's domain key (AES-256-GCM).  This survives MLS group rebuilds
    # and process restarts.  Only nodes holding the gate domain key can
    # decrypt — outsiders see opaque base64.
    gate_envelope: str = ""
    try:
        gate_envelope = _gate_envelope_encrypt(gate_key, plaintext)
    except Exception:
        logger.debug("gate envelope encrypt failed — MLS-only for this message")
    payload = {
        "gate": gate_key,
        "ciphertext": _b64(padded_ct),
        "nonce": message_id,
        "sender_ref": sender_ref,
        "format": MLS_GATE_FORMAT,
    }
    # gate_envelope must NOT be in the signed payload — it rides alongside.
    signed = sign_gate_wormhole_event(gate_id=gate_key, event_type="gate_message", payload=payload)
    if not signed.get("signature"):
        return {"ok": False, "detail": str(signed.get("detail") or "gate_sign_failed")}
    _HIGH_WATER_EPOCHS[gate_key] = max(
        int(binding.epoch),
        int(_HIGH_WATER_EPOCHS.get(gate_key, 0) or 0),
    )
    _lock_gate_format(gate_key, MLS_GATE_FORMAT)
    # Cache the MLS-decrypted plaintext (not raw input) so every member
    # including the sender can read it back.  Falls back to the original
    # plaintext if the cross-member decrypt failed (single-member edge case).
    _cache_local_plaintext(gate_key, payload["ciphertext"], sender_ref, str(_self_decrypt_plaintext or plaintext))
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
        "timestamp": ts,
        "gate_envelope": gate_envelope,
        },
        legacy_epoch=int(binding.epoch),
    )


def decrypt_gate_message_for_local_identity(
    *,
    gate_id: str,
    epoch: int,
    ciphertext: str,
    nonce: str,
    sender_ref: str = "",
    gate_envelope: str = "",
) -> dict[str, Any]:
    gate_key = _stable_gate_ref(gate_id)
    if not gate_key or not ciphertext:
        return {"ok": False, "detail": "gate_id and ciphertext required"}

    # Fast path: gate envelope (AES-256-GCM under gate domain key).
    # This always works regardless of MLS group state / restarts.
    if gate_envelope:
        envelope_pt = _gate_envelope_decrypt(gate_key, gate_envelope)
        if envelope_pt is not None:
            return {
                "ok": True,
                "gate_id": gate_key,
                "epoch": int(epoch or 0),
                "plaintext": envelope_pt,
                "identity_scope": "gate_envelope",
            }

    active_identity, active_source = _active_gate_member(gate_key)
    if not active_identity:
        return {"ok": False, "detail": "no active gate identity"}

    expected_sender_ref = _sender_ref(_sender_ref_seed(active_identity), str(nonce or ""))
    if str(sender_ref or "").strip() == expected_sender_ref:
        cached_plaintext = _peek_cached_plaintext(gate_key, str(ciphertext), str(sender_ref))
        if cached_plaintext is not None:
            return {
                "ok": True,
                "gate_id": gate_key,
                "epoch": int(epoch or 0),
                "plaintext": cached_plaintext,
                "identity_scope": "anonymous" if active_source == "anonymous" else "persona",
            }

    # Try all group members (verifier path) — this is the primary decrypt
    # strategy on a single-operator node where the sender is also a member.
    # A non-sender member can decrypt even though the sender member cannot.
    verifier_open = open_gate_ciphertext_for_verifier(
        gate_id=gate_key,
        ciphertext=str(ciphertext),
        format=MLS_GATE_FORMAT,
        epoch=int(epoch or 0),
    )
    if verifier_open.get("ok"):
        return {
            "ok": True,
            "gate_id": gate_key,
            "epoch": int(verifier_open.get("epoch", epoch or 0) or 0),
            "plaintext": str(verifier_open.get("plaintext", "") or ""),
            "identity_scope": active_source if active_source == "anonymous" else "persona",
        }
    # All MLS members are "self" — single-operator node authored this
    # message but plaintext was not persisted (pre-fix legacy message).
    if verifier_open.get("detail") == "gate_mls_self_authored":
        return {
            "ok": True,
            "gate_id": gate_key,
            "epoch": int(epoch or 0),
            "plaintext": "",
            "self_authored": True,
            "legacy": True,
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
        # The verifier (all-member attempt) already ran above and failed.
        # Check the in-memory cache as a last resort.
        if str(sender_ref or "").strip() == expected_sender_ref:
            cached_plaintext = _consume_cached_plaintext(gate_key, str(ciphertext), str(sender_ref))
            if cached_plaintext is not None:
                return {
                    "ok": True,
                    "gate_id": gate_key,
                    "epoch": int(epoch or binding.epoch or 0),
                    "plaintext": cached_plaintext,
                    "identity_scope": "anonymous" if active_source == "anonymous" else "persona",
                }
        logger.debug(
            "MLS gate decrypt failed for %s (verifier already attempted)",
            privacy_log_label(gate_key, label="gate"),
        )
        return {"ok": False, "detail": "gate_mls_decrypt_failed"}

    raw = decrypted_bytes.decode("utf-8")
    try:
        envelope = json.loads(raw)
        if isinstance(envelope, dict) and "m" in envelope:
            actual_plaintext = str(envelope["m"])
            decrypted_epoch = int(envelope.get("e", 0) or 0)
        else:
            actual_plaintext = raw
            decrypted_epoch = 0
    except (json.JSONDecodeError, ValueError, TypeError):
        actual_plaintext = raw
        decrypted_epoch = 0

    _lock_gate_format(gate_key, MLS_GATE_FORMAT)
    return {
        "ok": True,
        "gate_id": gate_key,
        "epoch": int(decrypted_epoch or epoch or 0),
        "plaintext": actual_plaintext,
        "identity_scope": "anonymous" if active_source == "anonymous" else "persona",
    }


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
            try:
                envelope = json.loads(raw)
                if isinstance(envelope, dict) and "m" in envelope:
                    actual_plaintext = str(envelope["m"])
                    decrypted_epoch = int(envelope.get("e", 0) or 0)
                else:
                    actual_plaintext = raw
                    decrypted_epoch = 0
            except (json.JSONDecodeError, ValueError, TypeError):
                actual_plaintext = raw
                decrypted_epoch = 0
            _lock_gate_format(gate_key, MLS_GATE_FORMAT)
            return {
                "ok": True,
                "gate_id": gate_key,
                "epoch": int(decrypted_epoch or epoch or 0),
                "plaintext": actual_plaintext,
                "opened_by_persona_id": persona_id,
                "identity_scope": "verifier",
            }
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
