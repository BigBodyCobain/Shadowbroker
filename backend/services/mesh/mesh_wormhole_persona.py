"""Wormhole-owned public identity compartments.

This module separates Wormhole's internal root trust anchor from the public
identities used for transport and future gate-scoped personas. The current
phase keeps public posting on a dedicated transport identity while preparing
gate session/persona identities for later phases.
"""

from __future__ import annotations

import base64
import logging
import random
import secrets
import time
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, x25519
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from services.mesh.mesh_crypto import build_signature_payload, derive_node_id
from services.mesh.mesh_privacy_logging import privacy_log_label
from services.mesh.mesh_protocol import PROTOCOL_VERSION, normalize_payload
from services.mesh.mesh_secure_storage import (
    read_domain_json,
    read_secure_json,
    write_domain_json,
)

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
PERSONA_FILE = DATA_DIR / "wormhole_persona.json"
LEGACY_DM_IDENTITY_FILE = DATA_DIR / "wormhole_identity.json"
TRANSPORT_DOMAIN = "transport"
ROOT_DOMAIN = "root"
DM_ALIAS_DOMAIN = "dm_alias"
GATE_SESSION_DOMAIN = "gate_session"
GATE_PERSONA_DOMAIN = "gate_persona"
TRANSPORT_FILE = "wormhole_transport.json"
ROOT_FILE = "wormhole_root.json"
DM_ALIAS_FILE = "wormhole_dm_identity.json"
GATE_SESSION_FILE = "wormhole_gate_sessions.json"
GATE_PERSONA_FILE = "wormhole_gate_personas.json"


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(data: str | bytes | None) -> bytes:
    if not data:
        return b""
    if isinstance(data, bytes):
        return base64.b64decode(data)
    return base64.b64decode(data.encode("ascii"))


def _empty_identity(scope: str = "") -> dict[str, Any]:
    return {
        "scope": scope,
        "gate_id": "",
        "persona_id": "",
        "label": "",
        "node_id": "",
        "public_key": "",
        "public_key_algo": "Ed25519",
        "private_key": "",
        "sequence": 0,
        "dh_pub_key": "",
        "dh_algo": "X25519",
        "dh_private_key": "",
        "created_at": 0,
        "last_used_at": 0,
        "last_dh_timestamp": 0,
        "bundle_fingerprint": "",
        "bundle_sequence": 0,
        "bundle_registered_at": 0,
        "signed_prekey_id": 0,
        "signed_prekey_pub": "",
        "signed_prekey_priv": "",
        "signed_prekey_signature": "",
        "signed_prekey_generated_at": 0,
        "signed_prekey_history": [],
        "one_time_prekeys": [],
        "prekey_bundle_registered_at": 0,
        "prekey_republish_threshold": 0,
        "prekey_republish_target": 0,
        "prekey_next_republish_after": 0,
        "mailbox_client_secret": "",
    }


def _default_state() -> dict[str, Any]:
    return {
        "bootstrapped": False,
        "bootstrapped_at": 0,
        "updated_at": 0,
        "root_identity": _empty_identity("root"),
        "previous_root_identity": _empty_identity("previous_root"),
        "transport_identity": _empty_identity("transport"),
        "dm_identity": _empty_identity("dm_alias"),
        # Phase 2: per-alias public key cache. Private keys are NEVER stored here;
        # they are re-derived deterministically via HKDF over dm_identity.private_key
        # on every signing call. See docs/mesh/wormhole-dm-root-operations-runbook.md
        # "Phase 2 — Per-Alias DM Identity Keys (HKDF-Derived)".
        "dm_alias_keys": {},
        "gate_sessions": {},
        "gate_personas": {},
        "active_gate_personas": {},
    }


# Phase 2 HKDF parameters — locked. See runbook §"Phase 2 — Per-Alias DM
# Identity Keys (HKDF-Derived)" for the full design rationale.
_DM_ALIAS_HKDF_SALT = b"shadowbroker/dm-alias-keys/v1"


def _normalize_dm_alias_counter(counter: int | str | None) -> int:
    return max(0, int(counter or 0))


def _dm_alias_cache_key(alias: str, counter: int) -> str:
    alias_key = str(alias or "").strip().lower()
    normalized_counter = _normalize_dm_alias_counter(counter)
    if normalized_counter <= 0:
        return alias_key
    return f"{alias_key}|r{normalized_counter}"


def _derive_dm_alias_keypair(
    master_seed: bytes,
    alias: str,
    *,
    counter: int = 0,
) -> tuple[ed25519.Ed25519PrivateKey, bytes, bytes]:
    """Deterministically derive a per-alias Ed25519 keypair from the DM master seed.

    Returns ``(private_key, private_raw, public_raw)``. Same ``(master_seed, alias)``
    pair always yields the same keypair, so historical alias bindings remain
    verifiable across restarts without persisting per-alias private keys.
    """

    alias_key = str(alias or "").strip().lower()
    if not master_seed:
        raise ValueError("dm master seed required for per-alias HKDF derivation")
    if not alias_key:
        raise ValueError("alias required for per-alias HKDF derivation")
    normalized_counter = _normalize_dm_alias_counter(counter)
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_DM_ALIAS_HKDF_SALT,
        info=(
            b"dm-alias:"
            + alias_key.encode("utf-8")
            + b"|r"
            + str(normalized_counter).encode("ascii")
        ),
    )
    seed = hkdf.derive(master_seed)
    signing_priv = ed25519.Ed25519PrivateKey.from_private_bytes(seed)
    signing_priv_raw = signing_priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    signing_pub_raw = signing_priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return signing_priv, signing_priv_raw, signing_pub_raw


def _identity_record(*, scope: str, gate_id: str = "", persona_id: str = "", label: str = "") -> dict[str, Any]:
    signing_priv = ed25519.Ed25519PrivateKey.generate()
    signing_priv_raw = signing_priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    signing_pub_raw = signing_priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    dh_priv = x25519.X25519PrivateKey.generate()
    dh_priv_raw = dh_priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    dh_pub_raw = dh_priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    now = int(time.time())
    return {
        "scope": scope,
        "gate_id": str(gate_id or "").lower(),
        "persona_id": str(persona_id or ""),
        "label": str(label or ""),
        "node_id": derive_node_id(_b64(signing_pub_raw)),
        "public_key": _b64(signing_pub_raw),
        "public_key_algo": "Ed25519",
        "private_key": _b64(signing_priv_raw),
        "sequence": 0,
        "dh_pub_key": _b64(dh_pub_raw),
        "dh_algo": "X25519",
        "dh_private_key": _b64(dh_priv_raw),
        "created_at": now,
        "last_used_at": now,
    }


def _public_identity_view(identity: dict[str, Any]) -> dict[str, Any]:
    return {
        "scope": str(identity.get("scope", "") or ""),
        "gate_id": str(identity.get("gate_id", "") or ""),
        "persona_id": str(identity.get("persona_id", "") or ""),
        "label": str(identity.get("label", "") or ""),
        "node_id": str(identity.get("node_id", "") or ""),
        "public_key": str(identity.get("public_key", "") or ""),
        "public_key_algo": str(identity.get("public_key_algo", "Ed25519") or "Ed25519"),
        "sequence": int(identity.get("sequence", 0) or 0),
        "dh_pub_key": str(identity.get("dh_pub_key", "") or ""),
        "dh_algo": str(identity.get("dh_algo", "X25519") or "X25519"),
        "last_dh_timestamp": int(identity.get("last_dh_timestamp", 0) or 0),
        "bundle_fingerprint": str(identity.get("bundle_fingerprint", "") or ""),
        "bundle_sequence": int(identity.get("bundle_sequence", 0) or 0),
        "bundle_registered_at": int(identity.get("bundle_registered_at", 0) or 0),
        "created_at": int(identity.get("created_at", 0) or 0),
        "last_used_at": int(identity.get("last_used_at", 0) or 0),
        "protocol_version": PROTOCOL_VERSION,
    }


def _read_legacy_dm_identity() -> dict[str, Any]:
    try:
        raw = read_secure_json(LEGACY_DM_IDENTITY_FILE, lambda: {})
    except Exception:
        logger.warning("Legacy DM identity could not be decrypted — skipping migration")
        LEGACY_DM_IDENTITY_FILE.unlink(missing_ok=True)
        return {}
    if not isinstance(raw, dict):
        return {}
    if not raw.get("private_key"):
        return {}
    return {
        **_empty_identity("dm_alias"),
        **raw,
        "scope": "dm_alias",
        "label": str(raw.get("label", "dm-alias") or "dm-alias"),
        "last_used_at": int(raw.get("last_used_at", raw.get("updated_at", raw.get("bootstrapped_at", 0))) or 0),
        "created_at": int(raw.get("created_at", raw.get("bootstrapped_at", 0)) or 0),
    }


def _transport_domain_default() -> dict[str, Any]:
    return {
        "bootstrapped": False,
        "bootstrapped_at": 0,
        "updated_at": 0,
        "transport_identity": _empty_identity("transport"),
    }


def _root_domain_default() -> dict[str, Any]:
    return {
        "root_identity": _empty_identity("root"),
        "previous_root_identity": _empty_identity("previous_root"),
    }


def _dm_alias_domain_default() -> dict[str, Any]:
    return {"dm_identity": _empty_identity("dm_alias"), "dm_alias_keys": {}}


def _gate_session_domain_default() -> dict[str, Any]:
    return {"gate_sessions": {}, "active_gate_personas": {}}


def _gate_persona_domain_default() -> dict[str, Any]:
    return {"gate_personas": {}}


def _domain_transport_path() -> Path:
    return DATA_DIR / TRANSPORT_DOMAIN / TRANSPORT_FILE


def _any_domain_persona_file_exists() -> bool:
    return any(
        path.exists()
        for path in (
            _domain_transport_path(),
            DATA_DIR / ROOT_DOMAIN / ROOT_FILE,
            DATA_DIR / DM_ALIAS_DOMAIN / DM_ALIAS_FILE,
            DATA_DIR / GATE_SESSION_DOMAIN / GATE_SESSION_FILE,
            DATA_DIR / GATE_PERSONA_DOMAIN / GATE_PERSONA_FILE,
        )
    )


def _migrate_legacy_persona_state_if_needed() -> None:
    if _any_domain_persona_file_exists() or not PERSONA_FILE.exists():
        return
    try:
        legacy_state = read_secure_json(PERSONA_FILE, _default_state)
    except Exception:
        logger.warning("Legacy persona state could not be decrypted — skipping migration")
        PERSONA_FILE.unlink(missing_ok=True)
        return
    state = _default_state()
    if isinstance(legacy_state, dict):
        state.update(legacy_state)
    write_domain_json(
        TRANSPORT_DOMAIN,
        TRANSPORT_FILE,
        {
            "bootstrapped": bool(state.get("bootstrapped")),
            "bootstrapped_at": int(state.get("bootstrapped_at", 0) or 0),
            "updated_at": int(state.get("updated_at", 0) or 0),
            "transport_identity": dict(state.get("transport_identity") or {}),
        },
    )
    write_domain_json(
        ROOT_DOMAIN,
        ROOT_FILE,
        {
            "root_identity": dict(state.get("root_identity") or {}),
            "previous_root_identity": dict(state.get("previous_root_identity") or {}),
        },
    )
    write_domain_json(
        DM_ALIAS_DOMAIN,
        DM_ALIAS_FILE,
        {"dm_identity": dict(state.get("dm_identity") or {})},
    )
    write_domain_json(
        GATE_SESSION_DOMAIN,
        GATE_SESSION_FILE,
        {
            "gate_sessions": dict(state.get("gate_sessions") or {}),
            "active_gate_personas": dict(state.get("active_gate_personas") or {}),
        },
    )
    write_domain_json(
        GATE_PERSONA_DOMAIN,
        GATE_PERSONA_FILE,
        {"gate_personas": dict(state.get("gate_personas") or {})},
    )
    PERSONA_FILE.unlink(missing_ok=True)


def read_wormhole_persona_state() -> dict[str, Any]:
    _migrate_legacy_persona_state_if_needed()
    transport_state = read_domain_json(TRANSPORT_DOMAIN, TRANSPORT_FILE, _transport_domain_default)
    root_state = read_domain_json(ROOT_DOMAIN, ROOT_FILE, _root_domain_default)
    dm_state = read_domain_json(DM_ALIAS_DOMAIN, DM_ALIAS_FILE, _dm_alias_domain_default)
    gate_session_state = read_domain_json(
        GATE_SESSION_DOMAIN,
        GATE_SESSION_FILE,
        _gate_session_domain_default,
    )
    gate_persona_state = read_domain_json(
        GATE_PERSONA_DOMAIN,
        GATE_PERSONA_FILE,
        _gate_persona_domain_default,
    )
    state = _default_state()
    if isinstance(transport_state, dict):
        state["bootstrapped"] = bool(transport_state.get("bootstrapped"))
        state["bootstrapped_at"] = int(transport_state.get("bootstrapped_at", 0) or 0)
        state["updated_at"] = int(transport_state.get("updated_at", 0) or 0)
        state["transport_identity"] = dict(transport_state.get("transport_identity") or {})
    if isinstance(root_state, dict):
        state["root_identity"] = dict(root_state.get("root_identity") or {})
        state["previous_root_identity"] = dict(root_state.get("previous_root_identity") or {})
    if isinstance(dm_state, dict):
        state["dm_identity"] = dict(dm_state.get("dm_identity") or {})
        state["dm_alias_keys"] = {
            str(k).strip().lower(): dict(v or {})
            for k, v in dict(dm_state.get("dm_alias_keys") or {}).items()
            if str(k).strip()
        }
    if isinstance(gate_session_state, dict):
        state["gate_sessions"] = dict(gate_session_state.get("gate_sessions") or {})
        state["active_gate_personas"] = dict(gate_session_state.get("active_gate_personas") or {})
    if isinstance(gate_persona_state, dict):
        state["gate_personas"] = dict(gate_persona_state.get("gate_personas") or {})
    state["bootstrapped"] = bool(state.get("bootstrapped"))
    state["bootstrapped_at"] = int(state.get("bootstrapped_at", 0) or 0)
    state["updated_at"] = int(state.get("updated_at", 0) or 0)
    state["root_identity"] = {**_empty_identity("root"), **dict(state.get("root_identity") or {})}
    state["previous_root_identity"] = {
        **_empty_identity("previous_root"),
        **dict(state.get("previous_root_identity") or {}),
    }
    state["transport_identity"] = {
        **_empty_identity("transport"),
        **dict(state.get("transport_identity") or {}),
    }
    state["dm_identity"] = {
        **_empty_identity("dm_alias"),
        **dict(state.get("dm_identity") or {}),
    }
    state["gate_sessions"] = {
        str(k).lower(): {**_empty_identity("gate_session"), **dict(v or {})}
        for k, v in dict(state.get("gate_sessions") or {}).items()
    }
    state["gate_personas"] = {
        str(k).lower(): [{**_empty_identity("gate_persona"), **dict(item or {})} for item in list(v or [])]
        for k, v in dict(state.get("gate_personas") or {}).items()
    }
    state["active_gate_personas"] = {
        str(k).lower(): str(v or "")
        for k, v in dict(state.get("active_gate_personas") or {}).items()
    }
    return state


def _write_wormhole_persona_state(state: dict[str, Any]) -> dict[str, Any]:
    payload = dict(state)
    payload["updated_at"] = int(time.time())
    write_domain_json(
        TRANSPORT_DOMAIN,
        TRANSPORT_FILE,
        {
            "bootstrapped": bool(payload.get("bootstrapped")),
            "bootstrapped_at": int(payload.get("bootstrapped_at", 0) or 0),
            "updated_at": int(payload.get("updated_at", 0) or 0),
            "transport_identity": dict(payload.get("transport_identity") or {}),
        },
    )
    write_domain_json(
        ROOT_DOMAIN,
        ROOT_FILE,
        {
            "root_identity": dict(payload.get("root_identity") or {}),
            "previous_root_identity": dict(payload.get("previous_root_identity") or {}),
        },
    )
    write_domain_json(
        DM_ALIAS_DOMAIN,
        DM_ALIAS_FILE,
        {
            "dm_identity": dict(payload.get("dm_identity") or {}),
            "dm_alias_keys": dict(payload.get("dm_alias_keys") or {}),
        },
    )
    write_domain_json(
        GATE_SESSION_DOMAIN,
        GATE_SESSION_FILE,
        {
            "gate_sessions": dict(payload.get("gate_sessions") or {}),
            "active_gate_personas": dict(payload.get("active_gate_personas") or {}),
        },
    )
    write_domain_json(
        GATE_PERSONA_DOMAIN,
        GATE_PERSONA_FILE,
        {"gate_personas": dict(payload.get("gate_personas") or {})},
    )
    PERSONA_FILE.unlink(missing_ok=True)
    return payload


def bootstrap_wormhole_persona_state(force: bool = False) -> dict[str, Any]:
    state = read_wormhole_persona_state()
    now = int(time.time())
    changed = force or not bool(state.get("bootstrapped"))
    if force or not state.get("root_identity", {}).get("private_key"):
        prior_root = {**_empty_identity("previous_root"), **dict(state.get("root_identity") or {})}
        if force and str(prior_root.get("private_key", "") or "").strip():
            prior_root["scope"] = "previous_root"
            state["previous_root_identity"] = prior_root
        elif not str((state.get("previous_root_identity") or {}).get("private_key", "") or "").strip():
            state["previous_root_identity"] = _empty_identity("previous_root")
        state["root_identity"] = _identity_record(scope="root", label="root")
        changed = True
    if force or not state.get("transport_identity", {}).get("private_key"):
        state["transport_identity"] = _identity_record(scope="transport", label="transport")
        changed = True
    if force or not state.get("dm_identity", {}).get("private_key"):
        legacy_dm = _read_legacy_dm_identity() if not force else {}
        state["dm_identity"] = legacy_dm or _identity_record(scope="dm_alias", label="dm-alias")
        changed = True
    if changed:
        state["bootstrapped"] = True
        if not state.get("bootstrapped_at") or force:
            state["bootstrapped_at"] = now
        state = _write_wormhole_persona_state(state)
    return {
        "bootstrapped": bool(state.get("bootstrapped")),
        "bootstrapped_at": int(state.get("bootstrapped_at", 0) or 0),
        "transport_identity": _public_identity_view(state.get("transport_identity") or {}),
    }


def get_transport_identity() -> dict[str, Any]:
    bootstrap_wormhole_persona_state()
    full_state = read_wormhole_persona_state()
    return {
        "bootstrapped": bool(full_state.get("bootstrapped")),
        "bootstrapped_at": int(full_state.get("bootstrapped_at", 0) or 0),
        **_public_identity_view(full_state.get("transport_identity") or {}),
    }


def read_root_identity() -> dict[str, Any]:
    bootstrap_wormhole_persona_state()
    state = read_wormhole_persona_state()
    return {**_empty_identity("root"), **dict(state.get("root_identity") or {})}


def get_root_identity() -> dict[str, Any]:
    bootstrap_wormhole_persona_state()
    full_state = read_wormhole_persona_state()
    return {
        "bootstrapped": bool(full_state.get("bootstrapped")),
        "bootstrapped_at": int(full_state.get("bootstrapped_at", 0) or 0),
        **_public_identity_view(full_state.get("root_identity") or {}),
    }


def read_previous_root_identity() -> dict[str, Any]:
    bootstrap_wormhole_persona_state()
    state = read_wormhole_persona_state()
    return {**_empty_identity("previous_root"), **dict(state.get("previous_root_identity") or {})}


def read_dm_identity() -> dict[str, Any]:
    bootstrap_wormhole_persona_state()
    state = read_wormhole_persona_state()
    return {**_empty_identity("dm_alias"), **dict(state.get("dm_identity") or {})}


def write_dm_identity(identity: dict[str, Any]) -> dict[str, Any]:
    bootstrap_wormhole_persona_state()
    state = read_wormhole_persona_state()
    merged = {**_empty_identity("dm_alias"), **dict(identity or {})}
    merged["scope"] = "dm_alias"
    merged["label"] = str(merged.get("label", "dm-alias") or "dm-alias")
    state["dm_identity"] = merged
    updated = _write_wormhole_persona_state(state)
    return {**_empty_identity("dm_alias"), **dict(updated.get("dm_identity") or {})}


def get_dm_identity() -> dict[str, Any]:
    bootstrap_wormhole_persona_state()
    full_state = read_wormhole_persona_state()
    return {
        "bootstrapped": bool(full_state.get("bootstrapped")),
        "bootstrapped_at": int(full_state.get("bootstrapped_at", 0) or 0),
        **_public_identity_view(full_state.get("dm_identity") or {}),
    }


def _touch(identity: dict[str, Any]) -> None:
    identity["last_used_at"] = int(time.time())


def _next_sequence(identity: dict[str, Any], sequence: int | None = None) -> int:
    if sequence is None:
        next_value = int(identity.get("sequence", 0) or 0) + 1
    else:
        next_value = max(int(identity.get("sequence", 0) or 0), int(sequence))
    identity["sequence"] = next_value
    _touch(identity)
    return next_value


def _sign_with_identity(
    *,
    identity: dict[str, Any],
    event_type: str,
    payload: dict[str, Any],
    sequence: int | None = None,
) -> dict[str, Any]:
    normalized = normalize_payload(event_type, dict(payload or {}))
    signed_sequence = _next_sequence(identity, sequence)
    payload_str = build_signature_payload(
        event_type=event_type,
        node_id=str(identity["node_id"]),
        sequence=int(signed_sequence),
        payload=normalized,
    )
    signing_priv = ed25519.Ed25519PrivateKey.from_private_bytes(
        _unb64(str(identity.get("private_key", "")))
    )
    signature = signing_priv.sign(payload_str.encode("utf-8")).hex()
    return {
        "node_id": str(identity["node_id"]),
        "public_key": str(identity["public_key"]),
        "public_key_algo": str(identity.get("public_key_algo", "Ed25519") or "Ed25519"),
        "protocol_version": PROTOCOL_VERSION,
        "sequence": int(signed_sequence),
        "payload": normalized,
        "signature": signature,
        "signature_payload": payload_str,
    }


def sign_public_wormhole_event(
    *,
    event_type: str,
    payload: dict[str, Any],
    sequence: int | None = None,
) -> dict[str, Any]:
    bootstrap_wormhole_persona_state()
    state = read_wormhole_persona_state()
    identity = state.get("transport_identity") or _empty_identity("transport")
    signed = _sign_with_identity(identity=identity, event_type=event_type, payload=payload, sequence=sequence)
    _write_wormhole_persona_state(state)
    return {**signed, "identity_scope": "transport"}


def sign_root_wormhole_event(
    *,
    event_type: str,
    payload: dict[str, Any],
    sequence: int | None = None,
) -> dict[str, Any]:
    bootstrap_wormhole_persona_state()
    state = read_wormhole_persona_state()
    identity = state.get("root_identity") or _empty_identity("root")
    signed = _sign_with_identity(identity=identity, event_type=event_type, payload=payload, sequence=sequence)
    _write_wormhole_persona_state(state)
    return {**signed, "identity_scope": "root"}


def sign_previous_root_wormhole_event(
    *,
    event_type: str,
    payload: dict[str, Any],
    sequence: int | None = None,
) -> dict[str, Any]:
    bootstrap_wormhole_persona_state()
    state = read_wormhole_persona_state()
    identity = state.get("previous_root_identity") or _empty_identity("previous_root")
    if not str(identity.get("private_key", "") or "").strip():
        return {"ok": False, "detail": "previous root identity unavailable"}
    signed = _sign_with_identity(identity=identity, event_type=event_type, payload=payload, sequence=sequence)
    _write_wormhole_persona_state(state)
    return {**signed, "ok": True, "identity_scope": "previous_root"}


def sign_dm_wormhole_event(
    *,
    event_type: str,
    payload: dict[str, Any],
    sequence: int | None = None,
) -> dict[str, Any]:
    bootstrap_wormhole_persona_state()
    state = read_wormhole_persona_state()
    identity = state.get("dm_identity") or _empty_identity("dm_alias")
    signed = _sign_with_identity(identity=identity, event_type=event_type, payload=payload, sequence=sequence)
    _write_wormhole_persona_state(state)
    return {**signed, "identity_scope": "dm_alias"}


def sign_dm_wormhole_message(message: str) -> dict[str, Any]:
    bootstrap_wormhole_persona_state()
    state = read_wormhole_persona_state()
    identity = state.get("dm_identity") or _empty_identity("dm_alias")
    _touch(identity)
    signing_priv = ed25519.Ed25519PrivateKey.from_private_bytes(
        _unb64(str(identity.get("private_key", "")))
    )
    signature = signing_priv.sign(str(message or "").encode("utf-8")).hex()
    _write_wormhole_persona_state(state)
    return {
        "node_id": str(identity.get("node_id", "") or ""),
        "public_key": str(identity.get("public_key", "") or ""),
        "public_key_algo": str(identity.get("public_key_algo", "Ed25519") or "Ed25519"),
        "protocol_version": PROTOCOL_VERSION,
        "signature": signature,
        "message": str(message or ""),
        "identity_scope": "dm_alias",
    }


def sign_root_wormhole_message(message: str) -> dict[str, Any]:
    bootstrap_wormhole_persona_state()
    state = read_wormhole_persona_state()
    identity = state.get("root_identity") or _empty_identity("root")
    _touch(identity)
    signing_priv = ed25519.Ed25519PrivateKey.from_private_bytes(
        _unb64(str(identity.get("private_key", "")))
    )
    signature = signing_priv.sign(str(message or "").encode("utf-8")).hex()
    _write_wormhole_persona_state(state)
    return {
        "node_id": str(identity.get("node_id", "") or ""),
        "public_key": str(identity.get("public_key", "") or ""),
        "public_key_algo": str(identity.get("public_key_algo", "Ed25519") or "Ed25519"),
        "protocol_version": PROTOCOL_VERSION,
        "signature": signature,
        "message": str(message or ""),
        "identity_scope": "root",
    }


def get_dm_alias_public_key(alias: str, *, counter: int = 0) -> dict[str, Any]:
    alias_key = str(alias or "").strip().lower()
    if not alias_key:
        return {"ok": False, "detail": "alias required"}
    bootstrap_wormhole_persona_state()
    state = read_wormhole_persona_state()
    identity = state.get("dm_identity") or _empty_identity("dm_alias")
    master_seed_b64 = str(identity.get("private_key", "") or "")
    if not master_seed_b64:
        return {"ok": False, "detail": "dm master seed unavailable"}
    try:
        master_seed = _unb64(master_seed_b64)
        _signing_priv, _signing_priv_raw, signing_pub_raw = _derive_dm_alias_keypair(
            master_seed,
            alias_key,
            counter=counter,
        )
    except Exception:
        logger.exception(
            "dm alias public key derivation failed for %s",
            privacy_log_label(alias_key, label="alias"),
        )
        return {"ok": False, "detail": "dm_alias_public_key_failed"}

    derived_public_b64 = _b64(signing_pub_raw)
    now = int(time.time())
    cache_key = _dm_alias_cache_key(alias_key, counter)
    alias_keys = dict(state.get("dm_alias_keys") or {})
    existing = dict(alias_keys.get(cache_key) or {})
    alias_keys[cache_key] = {
        "alias": alias_key,
        "counter": _normalize_dm_alias_counter(counter),
        "public_key": derived_public_b64,
        "public_key_algo": "Ed25519",
        "created_at": int(existing.get("created_at", 0) or 0) or now,
        "last_used_at": now,
    }
    state["dm_alias_keys"] = alias_keys
    if not bool(identity.get("legacy_only")):
        identity["legacy_only"] = True
    _touch(identity)
    state["dm_identity"] = identity
    _write_wormhole_persona_state(state)
    return {
        "ok": True,
        "alias": alias_key,
        "counter": _normalize_dm_alias_counter(counter),
        "public_key": derived_public_b64,
        "public_key_algo": "Ed25519",
    }


def _bound_dm_alias_blob(alias: str, payload: bytes, *, counter: int = 0, legacy: bool = False) -> bytes:
    alias_key = str(alias or "").strip().lower()
    if legacy:
        return f"dm-mls-binding|{alias_key}|".encode("utf-8") + bytes(payload or b"")
    return (
        f"dm-mls-binding|{alias_key}|r{_normalize_dm_alias_counter(counter)}|".encode("utf-8")
        + bytes(payload or b"")
    )


def sign_dm_alias_blob(alias: str, payload: bytes, *, counter: int = 0) -> dict[str, Any]:
    """Sign an alias binding with a per-alias HKDF-derived Ed25519 key.

    Phase 2: each alias gets its own public key derived deterministically from
    ``dm_identity.private_key`` via HKDF-SHA256 with alias-bound ``info``.
    Verifiers see a fresh public key per alias and cannot link two aliases
    on the same node to a common identity. The legacy singleton
    ``dm_identity`` keypair is retained on disk indefinitely (flagged
    ``legacy_only=true``) so historical alias bindings remain verifiable
    via :func:`verify_dm_alias_blob`'s legacy-fallback branch.
    """

    alias_key = str(alias or "").strip().lower()
    if not alias_key:
        return {"ok": False, "detail": "alias required"}
    bootstrap_wormhole_persona_state()
    state = read_wormhole_persona_state()
    identity = state.get("dm_identity") or _empty_identity("dm_alias")
    master_seed_b64 = str(identity.get("private_key", "") or "")
    try:
        master_seed = _unb64(master_seed_b64)
        signing_priv, _signing_priv_raw, signing_pub_raw = _derive_dm_alias_keypair(
            master_seed,
            alias_key,
            counter=counter,
        )
        signature = signing_priv.sign(_bound_dm_alias_blob(alias_key, payload, counter=counter)).hex()
    except Exception:
        logger.exception(
            "dm alias blob sign failed for %s",
            privacy_log_label(alias_key, label="alias"),
        )
        return {"ok": False, "detail": "dm_alias_blob_sign_failed"}

    derived_public_b64 = _b64(signing_pub_raw)
    now = int(time.time())

    cache_key = _dm_alias_cache_key(alias_key, counter)
    alias_keys = dict(state.get("dm_alias_keys") or {})
    existing = dict(alias_keys.get(cache_key) or {})
    cached_record = {
        "alias": alias_key,
        "counter": _normalize_dm_alias_counter(counter),
        "public_key": derived_public_b64,
        "public_key_algo": "Ed25519",
        "created_at": int(existing.get("created_at", 0) or 0) or now,
        "last_used_at": now,
    }
    alias_keys[cache_key] = cached_record
    state["dm_alias_keys"] = alias_keys

    # Mark the singleton dm_identity as legacy-only once any per-alias key
    # has been derived. This is the durable signal that Phase 2 has run on
    # this node — verify_dm_alias_blob uses it to gate the legacy fallback.
    if not bool(identity.get("legacy_only")):
        identity["legacy_only"] = True
    _touch(identity)
    state["dm_identity"] = identity
    _write_wormhole_persona_state(state)
    return {
        "ok": True,
        "alias": alias_key,
        "counter": _normalize_dm_alias_counter(counter),
        "signature": signature,
        "public_key": derived_public_b64,
        "public_key_algo": "Ed25519",
    }


def verify_dm_alias_blob(
    alias: str,
    payload: bytes,
    signature: str,
    *,
    counter: int = 0,
    public_key: str = "",
    public_key_algo: str = "Ed25519",
    allow_legacy: bool = True,
) -> tuple[bool, str]:
    """Verify an alias binding signature.

    Phase 2: tries the per-alias HKDF-derived public key first. On failure,
    falls back to the legacy singleton ``dm_identity`` public key, but only
    if ``dm_identity.legacy_only`` is true (i.e., Phase 2 has already run on
    this node). On legacy-fallback success, logs a privacy-safe warning so
    operators can see historical signatures still in flight.
    """

    alias_key = str(alias or "").strip().lower()
    if not alias_key:
        return False, "alias required"
    if not str(signature or "").strip():
        return False, "signature required"
    try:
        signature_bytes = bytes.fromhex(str(signature or ""))
    except Exception:
        return False, "dm alias blob signature invalid"

    bootstrap_wormhole_persona_state()
    state = read_wormhole_persona_state()
    identity = state.get("dm_identity") or _empty_identity("dm_alias")
    bound = _bound_dm_alias_blob(alias_key, payload, counter=counter)

    if str(public_key or "").strip():
        try:
            signing_pub = ed25519.Ed25519PublicKey.from_public_bytes(
                _unb64(str(public_key or ""))
            )
            signing_pub.verify(signature_bytes, bound)
            return True, "ok"
        except Exception:
            if allow_legacy and _normalize_dm_alias_counter(counter) <= 0:
                try:
                    signing_pub = ed25519.Ed25519PublicKey.from_public_bytes(
                        _unb64(str(public_key or ""))
                    )
                    signing_pub.verify(signature_bytes, _bound_dm_alias_blob(alias_key, payload, legacy=True))
                    return True, "ok"
                except Exception:
                    pass
            return False, "dm alias blob signature invalid"

    # Phase 2 path: derive the per-alias public key from the master seed and
    # verify against it. This always succeeds for signatures produced by the
    # Phase 2 sign path.
    master_seed_b64 = str(identity.get("private_key", "") or "")
    if master_seed_b64:
        try:
            master_seed = _unb64(master_seed_b64)
            _signing_priv, _signing_priv_raw, signing_pub_raw = _derive_dm_alias_keypair(
                master_seed,
                alias_key,
                counter=counter,
            )
            ed25519.Ed25519PublicKey.from_public_bytes(signing_pub_raw).verify(
                signature_bytes, bound
            )
            return True, "ok"
        except Exception:
            if allow_legacy and _normalize_dm_alias_counter(counter) <= 0:
                try:
                    _signing_priv, _signing_priv_raw, signing_pub_raw = _derive_dm_alias_keypair(
                        master_seed,
                        alias_key,
                        counter=counter,
                    )
                    ed25519.Ed25519PublicKey.from_public_bytes(signing_pub_raw).verify(
                        signature_bytes,
                        _bound_dm_alias_blob(alias_key, payload, legacy=True),
                    )
                    return True, "ok"
                except Exception:
                    pass

    # Legacy fallback: only enabled if the cutover marker is present.
    # This is what keeps pre-Phase-2 alias bindings verifiable forever.
    if allow_legacy and bool(identity.get("legacy_only")):
        legacy_pub_b64 = str(identity.get("public_key", "") or "")
        if legacy_pub_b64:
            try:
                ed25519.Ed25519PublicKey.from_public_bytes(_unb64(legacy_pub_b64)).verify(
                    signature_bytes,
                    _bound_dm_alias_blob(alias_key, payload, legacy=True),
                )
                logger.warning(
                    "dm alias blob verified via legacy singleton key for %s",
                    privacy_log_label(alias_key, label="alias"),
                )
                return True, "ok"
            except Exception:
                pass

    return False, "dm alias blob signature invalid"


def ensure_dm_mailbox_client_secret(*, generate: bool = True) -> str:
    bootstrap_wormhole_persona_state()
    state = read_wormhole_persona_state()
    identity = state.get("dm_identity") or _empty_identity("dm_alias")
    secret = str(identity.get("mailbox_client_secret", "") or "").strip()
    if secret or not generate:
        return secret
    secret = _b64(secrets.token_bytes(32))
    identity["mailbox_client_secret"] = secret
    _touch(identity)
    state["dm_identity"] = identity
    _write_wormhole_persona_state(state)
    return secret


def _high_privacy_profile_enabled() -> bool:
    try:
        from services.wormhole_settings import read_wormhole_settings

        settings = read_wormhole_settings()
        return str(settings.get("privacy_profile", "default") or "default").strip().lower() == "high"
    except Exception:
        return False


def _high_privacy_cap(value: int, cap: int) -> int:
    configured = int(value or 0)
    if not _high_privacy_profile_enabled():
        return configured
    if configured <= 0:
        return int(cap)
    return min(configured, int(cap))


def _ensure_gate_session(state: dict[str, Any], gate_key: str, *, rotate: bool = False) -> dict[str, Any]:
    existing = dict(state.get("gate_sessions", {}).get(gate_key) or {})
    if not rotate and existing.get("private_key"):
        from services.config import get_settings

        settings = get_settings()
        msg_limit = _high_privacy_cap(int(settings.MESH_GATE_SESSION_ROTATE_MSGS or 0), 10)
        time_limit = _high_privacy_cap(int(settings.MESH_GATE_SESSION_ROTATE_S or 0), 900)
        jitter_limit = max(0.0, float(getattr(settings, "MESH_GATE_SESSION_ROTATE_JITTER_S", 0) or 0.0))
        if _high_privacy_profile_enabled():
            jitter_limit = max(jitter_limit, 60.0)
        msg_count = int(existing.get("_msg_count", 0) or 0)
        created_at = float(existing.get("_created_at", 0) or 0)
        now = time.time()
        rotate_due_at = float(existing.get("_rotate_after", 0) or 0.0)
        threshold_hit = False
        if msg_limit > 0 and msg_count >= msg_limit:
            threshold_hit = True
        elif time_limit > 0 and created_at > 0 and (now - created_at) >= time_limit:
            threshold_hit = True
        if threshold_hit:
            if jitter_limit > 0:
                if rotate_due_at <= 0:
                    rotate_due_at = now + random.uniform(0.0, jitter_limit)
                    existing["_rotate_after"] = rotate_due_at
                    state.setdefault("gate_sessions", {})[gate_key] = existing
                rotate = now >= rotate_due_at
            else:
                rotate = True
        elif rotate_due_at > 0:
            existing["_rotate_after"] = 0.0
            state.setdefault("gate_sessions", {})[gate_key] = existing
    if rotate or not existing.get("private_key"):
        new_identity = _identity_record(
            scope="gate_session",
            gate_id=gate_key,
            label="anonymous",
        )
        new_identity["_msg_count"] = 0
        new_identity["_created_at"] = time.time()
        new_identity["_rotate_after"] = 0.0
        state.setdefault("gate_sessions", {})[gate_key] = new_identity
    return state["gate_sessions"][gate_key]


def enter_gate_anonymously(gate_id: str, *, rotate: bool = False) -> dict[str, Any]:
    gate_key = str(gate_id or "").strip().lower()
    if not gate_key:
        return {"ok": False, "detail": "gate_id required"}
    bootstrap_wormhole_persona_state()
    state = read_wormhole_persona_state()
    # Entering anonymously must clear any previously active persona for the
    # same gate so the caller cannot accidentally keep posting under a stale
    # gate-local face after explicitly choosing anonymous mode.
    state.setdefault("active_gate_personas", {}).pop(gate_key, None)
    session = _ensure_gate_session(state, gate_key, rotate=rotate)
    _touch(session)
    _write_wormhole_persona_state(state)
    return {"ok": True, "identity": _public_identity_view(session)}


def leave_gate(gate_id: str) -> dict[str, Any]:
    gate_key = str(gate_id or "").strip().lower()
    bootstrap_wormhole_persona_state()
    state = read_wormhole_persona_state()
    removed = False
    if gate_key in state.get("gate_sessions", {}):
        state["gate_sessions"].pop(gate_key, None)
        removed = True
    if gate_key in state.get("active_gate_personas", {}):
        state["active_gate_personas"].pop(gate_key, None)
        removed = True
    if removed:
        _write_wormhole_persona_state(state)
    return {"ok": True, "gate_id": gate_key, "cleared": removed}


def _unique_gate_persona_label(gate_key: str, requested_label: str, existing_personas: list[dict[str, Any]]) -> str:
    base_label = str(requested_label or "").strip()
    if not base_label:
        base_label = f"{gate_key}-persona"
    used_labels = {
        str(persona.get("label", "") or "").strip().lower()
        for persona in existing_personas
        if str(persona.get("label", "") or "").strip()
    }
    if base_label.lower() not in used_labels:
        return base_label
    suffix = 2
    while f"{base_label}-{suffix}".lower() in used_labels:
        suffix += 1
    return f"{base_label}-{suffix}"


def create_gate_persona(gate_id: str, *, label: str = "") -> dict[str, Any]:
    gate_key = str(gate_id or "").strip().lower()
    if not gate_key:
        return {"ok": False, "detail": "gate_id required"}
    bootstrap_wormhole_persona_state()
    state = read_wormhole_persona_state()
    personas = list(state.get("gate_personas", {}).get(gate_key) or [])
    persona_id = secrets.token_hex(8)
    requested_label = str(label or f"anon_{persona_id[:4]}").strip()
    persona = _identity_record(
        scope="gate_persona",
        gate_id=gate_key,
        persona_id=persona_id,
        label=_unique_gate_persona_label(gate_key, requested_label, personas),
    )
    persona["_msg_count"] = 0
    persona["_created_at"] = time.time()
    persona["_rotate_after"] = 0.0
    personas.append(persona)
    state.setdefault("gate_personas", {})[gate_key] = personas
    state.setdefault("active_gate_personas", {})[gate_key] = persona_id
    _write_wormhole_persona_state(state)
    return {"ok": True, "identity": _public_identity_view(persona)}


def list_gate_personas(gate_id: str) -> dict[str, Any]:
    gate_key = str(gate_id or "").strip().lower()
    bootstrap_wormhole_persona_state()
    state = read_wormhole_persona_state()
    personas = [
        _public_identity_view(item)
        for item in list(state.get("gate_personas", {}).get(gate_key) or [])
        if not str(item.get("label", "") or "").startswith("_reader")
    ]
    return {
        "ok": True,
        "gate_id": gate_key,
        "active_persona_id": str(state.get("active_gate_personas", {}).get(gate_key, "") or ""),
        "personas": personas,
    }


def activate_gate_persona(gate_id: str, persona_id: str) -> dict[str, Any]:
    gate_key = str(gate_id or "").strip().lower()
    target_persona = str(persona_id or "").strip()
    bootstrap_wormhole_persona_state()
    state = read_wormhole_persona_state()
    personas = list(state.get("gate_personas", {}).get(gate_key) or [])
    for persona in personas:
        if str(persona.get("persona_id", "") or "") == target_persona:
            # _reader personas exist solely for MLS cross-member decrypt;
            # they must never be activated as the event-signing identity.
            if str(persona.get("label", "") or "").startswith("_reader"):
                return {"ok": False, "detail": "reader personas cannot be activated"}
            state.setdefault("active_gate_personas", {})[gate_key] = target_persona
            _touch(persona)
            _write_wormhole_persona_state(state)
            return {"ok": True, "identity": _public_identity_view(persona)}
    return {"ok": False, "detail": "persona not found"}


def retire_gate_persona(gate_id: str, persona_id: str) -> dict[str, Any]:
    gate_key = str(gate_id or "").strip().lower()
    target_persona = str(persona_id or "").strip()
    if not gate_key:
        return {"ok": False, "detail": "gate_id required"}
    if not target_persona:
        return {"ok": False, "detail": "persona_id required"}
    bootstrap_wormhole_persona_state()
    state = read_wormhole_persona_state()
    personas = list(state.get("gate_personas", {}).get(gate_key) or [])
    removed_persona: dict[str, Any] | None = None
    remaining_personas: list[dict[str, Any]] = []
    for persona in personas:
        if str(persona.get("persona_id", "") or "") == target_persona:
            removed_persona = persona
            continue
        remaining_personas.append(persona)
    if removed_persona is None:
        return {"ok": False, "detail": "persona not found"}

    if remaining_personas:
        state.setdefault("gate_personas", {})[gate_key] = remaining_personas
    else:
        state.setdefault("gate_personas", {}).pop(gate_key, None)

    active_persona_id = str(state.get("active_gate_personas", {}).get(gate_key, "") or "")
    active_identity: dict[str, Any] | None = None
    if active_persona_id == target_persona:
        state.setdefault("active_gate_personas", {}).pop(gate_key, None)
        session = _ensure_gate_session(state, gate_key, rotate=True)
        _touch(session)
        active_identity = _public_identity_view(session)
    _write_wormhole_persona_state(state)
    return {
        "ok": True,
        "gate_id": gate_key,
        "retired_persona_id": target_persona,
        "retired_identity": _public_identity_view(removed_persona),
        "active_identity": active_identity,
    }


def rotate_gate_persona(gate_id: str, *, reason: str = "auto") -> dict[str, Any]:
    """Rotate the active gate persona's signing identity.

    Creates a new persona with the same label, retires the old one, and
    activates the replacement.  Does NOT touch MLS group membership — this
    is a pure signer-identity swap.
    """
    gate_key = str(gate_id or "").strip().lower()
    if not gate_key:
        return {"ok": False, "detail": "gate_id required"}
    bootstrap_wormhole_persona_state()
    state = read_wormhole_persona_state()
    active_persona_id = str(state.get("active_gate_personas", {}).get(gate_key, "") or "")
    if not active_persona_id:
        return {"ok": False, "detail": "no active persona to rotate"}
    personas = list(state.get("gate_personas", {}).get(gate_key) or [])
    old_persona: dict[str, Any] | None = None
    remaining: list[dict[str, Any]] = []
    for p in personas:
        if str(p.get("persona_id", "") or "") == active_persona_id:
            old_persona = p
        else:
            remaining.append(p)
    if old_persona is None:
        return {"ok": False, "detail": "active persona not found in roster"}
    old_label = str(old_persona.get("label", "") or "").strip()
    new_persona_id = secrets.token_hex(8)
    new_persona = _identity_record(
        scope="gate_persona",
        gate_id=gate_key,
        persona_id=new_persona_id,
        label=_unique_gate_persona_label(gate_key, old_label, remaining),
    )
    new_persona["_msg_count"] = 0
    new_persona["_created_at"] = time.time()
    new_persona["_rotate_after"] = 0.0
    remaining.append(new_persona)
    state.setdefault("gate_personas", {})[gate_key] = remaining
    state.setdefault("active_gate_personas", {})[gate_key] = new_persona_id
    _write_wormhole_persona_state(state)
    return {
        "ok": True,
        "gate_id": gate_key,
        "reason": reason,
        "retired_persona_id": active_persona_id,
        "new_persona_id": new_persona_id,
        "identity": _public_identity_view(new_persona),
    }


def _should_rotate_persona(persona: dict[str, Any]) -> bool:
    """Check if a gate persona has exceeded its rotation thresholds."""
    try:
        from services.config import get_settings
        settings = get_settings()
    except Exception:
        return False
    msg_limit = _high_privacy_cap(int(getattr(settings, "MESH_GATE_PERSONA_ROTATE_MSGS", 0) or 0), 50)
    time_limit = _high_privacy_cap(int(getattr(settings, "MESH_GATE_PERSONA_ROTATE_S", 0) or 0), 86400)
    msg_count = int(persona.get("_msg_count", 0) or 0)
    created_at = float(persona.get("_created_at", 0) or 0)
    now = time.time()
    if msg_limit > 0 and msg_count >= msg_limit:
        return True
    if time_limit > 0 and created_at > 0 and (now - created_at) >= time_limit:
        return True
    return False


def clear_active_gate_persona(gate_id: str) -> dict[str, Any]:
    gate_key = str(gate_id or "").strip().lower()
    if not gate_key:
        return {"ok": False, "detail": "gate_id required"}
    bootstrap_wormhole_persona_state()
    state = read_wormhole_persona_state()
    state.setdefault("active_gate_personas", {}).pop(gate_key, None)
    # Returning to anonymous mode should yield a fresh, gate-scoped session
    # identity instead of resurrecting an older anonymous session.
    session = _ensure_gate_session(state, gate_key, rotate=True)
    _touch(session)
    _write_wormhole_persona_state(state)
    return {"ok": True, "identity": _public_identity_view(session)}


def get_active_gate_identity(gate_id: str) -> dict[str, Any]:
    gate_key = str(gate_id or "").strip().lower()
    bootstrap_wormhole_persona_state()
    state = read_wormhole_persona_state()
    active_persona_id = str(state.get("active_gate_personas", {}).get(gate_key, "") or "")
    for persona in list(state.get("gate_personas", {}).get(gate_key) or []):
        if str(persona.get("persona_id", "") or "") == active_persona_id:
            return {"ok": True, "identity": _public_identity_view(persona), "source": "persona"}
    session = dict(state.get("gate_sessions", {}).get(gate_key) or {})
    if session.get("private_key"):
        return {"ok": True, "identity": _public_identity_view(session), "source": "anonymous"}
    return {"ok": False, "detail": "no active gate identity"}


def _find_gate_persona_record(state: dict[str, Any], gate_id: str, persona_id: str) -> dict[str, Any] | None:
    gate_key = str(gate_id or "").strip().lower()
    target_persona = str(persona_id or "").strip()
    for persona in list(state.get("gate_personas", {}).get(gate_key) or []):
        if str(persona.get("persona_id", "") or "") == target_persona:
            return persona
    return None


def _find_gate_session_record(state: dict[str, Any], gate_id: str, node_id: str = "") -> dict[str, Any] | None:
    gate_key = str(gate_id or "").strip().lower()
    session = dict(state.get("gate_sessions", {}).get(gate_key) or {})
    if not session.get("private_key"):
        return None
    target_node_id = str(node_id or "").strip()
    if target_node_id and str(session.get("node_id", "") or "").strip() != target_node_id:
        return None
    return session


def _bound_gate_persona_blob(gate_id: str, persona_id: str, payload: bytes) -> bytes:
    gate_key = str(gate_id or "").strip().lower()
    target_persona = str(persona_id or "").strip()
    return (
        f"gate-mls-binding|{gate_key}|{target_persona}|".encode("utf-8")
        + bytes(payload or b"")
    )


def _bound_gate_session_blob(gate_id: str, node_id: str, payload: bytes) -> bytes:
    gate_key = str(gate_id or "").strip().lower()
    target_node_id = str(node_id or "").strip()
    return (
        f"gate-mls-binding|{gate_key}|session:{target_node_id}|".encode("utf-8")
        + bytes(payload or b"")
    )


def sign_gate_persona_blob(gate_id: str, persona_id: str, payload: bytes) -> dict[str, Any]:
    gate_key = str(gate_id or "").strip().lower()
    target_persona = str(persona_id or "").strip()
    if not gate_key:
        return {"ok": False, "detail": "gate_id required"}
    if not target_persona:
        return {"ok": False, "detail": "persona_id required"}
    bootstrap_wormhole_persona_state()
    state = read_wormhole_persona_state()
    persona = _find_gate_persona_record(state, gate_key, target_persona)
    if persona is None:
        return {"ok": False, "detail": "persona not found"}
    try:
        bound_payload = _bound_gate_persona_blob(gate_key, target_persona, bytes(payload or b""))
        signing_priv = ed25519.Ed25519PrivateKey.from_private_bytes(
            _unb64(str(persona.get("private_key", "") or ""))
        )
        signature = signing_priv.sign(bound_payload).hex()
    except Exception:
        logger.exception(
            "gate persona blob sign failed for %s/%s",
            privacy_log_label(gate_key, label="gate"),
            privacy_log_label(target_persona, label="persona"),
        )
        return {"ok": False, "detail": "persona_blob_sign_failed"}
    _touch(persona)
    _write_wormhole_persona_state(state)
    return {
        "ok": True,
        "gate_id": gate_key,
        "persona_id": target_persona,
        "signature": signature,
        "public_key": str(persona.get("public_key", "") or ""),
        "public_key_algo": str(persona.get("public_key_algo", "Ed25519") or "Ed25519"),
    }


def verify_gate_persona_blob(
    gate_id: str,
    persona_id: str,
    payload: bytes,
    signature: str,
) -> tuple[bool, str]:
    gate_key = str(gate_id or "").strip().lower()
    target_persona = str(persona_id or "").strip()
    if not gate_key:
        return False, "gate_id required"
    if not target_persona:
        return False, "persona_id required"
    if not str(signature or "").strip():
        return False, "signature required"
    bootstrap_wormhole_persona_state()
    state = read_wormhole_persona_state()
    persona = _find_gate_persona_record(state, gate_key, target_persona)
    if persona is None:
        return False, "persona not found"
    try:
        bound_payload = _bound_gate_persona_blob(gate_key, target_persona, bytes(payload or b""))
        signing_pub = ed25519.Ed25519PublicKey.from_public_bytes(
            _unb64(str(persona.get("public_key", "") or ""))
        )
        signing_pub.verify(bytes.fromhex(str(signature or "")), bound_payload)
    except Exception:
        return False, "persona blob signature invalid"
    return True, "ok"


def sign_gate_session_blob(gate_id: str, node_id: str, payload: bytes) -> dict[str, Any]:
    gate_key = str(gate_id or "").strip().lower()
    target_node_id = str(node_id or "").strip()
    if not gate_key:
        return {"ok": False, "detail": "gate_id required"}
    if not target_node_id:
        return {"ok": False, "detail": "node_id required"}
    bootstrap_wormhole_persona_state()
    state = read_wormhole_persona_state()
    session = _find_gate_session_record(state, gate_key, target_node_id)
    if session is None:
        return {"ok": False, "detail": "anonymous gate session not found"}
    try:
        bound_payload = _bound_gate_session_blob(gate_key, target_node_id, bytes(payload or b""))
        signing_priv = ed25519.Ed25519PrivateKey.from_private_bytes(
            _unb64(str(session.get("private_key", "") or ""))
        )
        signature = signing_priv.sign(bound_payload).hex()
    except Exception:
        logger.exception(
            "gate session blob sign failed for %s/%s",
            privacy_log_label(gate_key, label="gate"),
            privacy_log_label(target_node_id, label="session"),
        )
        return {"ok": False, "detail": "gate_session_blob_sign_failed"}
    _touch(session)
    state.setdefault("gate_sessions", {})[gate_key] = session
    _write_wormhole_persona_state(state)
    return {
        "ok": True,
        "gate_id": gate_key,
        "node_id": target_node_id,
        "signature": signature,
        "public_key": str(session.get("public_key", "") or ""),
        "public_key_algo": str(session.get("public_key_algo", "Ed25519") or "Ed25519"),
    }


def verify_gate_session_blob(
    gate_id: str,
    node_id: str,
    payload: bytes,
    signature: str,
) -> tuple[bool, str]:
    gate_key = str(gate_id or "").strip().lower()
    target_node_id = str(node_id or "").strip()
    if not gate_key:
        return False, "gate_id required"
    if not target_node_id:
        return False, "node_id required"
    if not str(signature or "").strip():
        return False, "signature required"
    bootstrap_wormhole_persona_state()
    state = read_wormhole_persona_state()
    session = _find_gate_session_record(state, gate_key, target_node_id)
    if session is None:
        return False, "anonymous gate session not found"
    try:
        bound_payload = _bound_gate_session_blob(gate_key, target_node_id, bytes(payload or b""))
        signing_pub = ed25519.Ed25519PublicKey.from_public_bytes(
            _unb64(str(session.get("public_key", "") or ""))
        )
        signing_pub.verify(bytes.fromhex(str(signature or "")), bound_payload)
    except Exception:
        return False, "gate session blob signature invalid"
    return True, "ok"


def sign_gate_wormhole_event(
    *,
    gate_id: str,
    event_type: str,
    payload: dict[str, Any],
    sequence: int | None = None,
) -> dict[str, Any]:
    gate_key = str(gate_id or "").strip().lower()
    if not gate_key:
        return {"ok": False, "detail": "gate_id required"}
    normalized_payload = normalize_payload(event_type, dict(payload or {}))
    payload_gate = str(
        normalized_payload.get("gate")
        or normalized_payload.get("gate_id")
        or ""
    ).strip().lower()
    if payload_gate and payload_gate != gate_key:
        return {"ok": False, "detail": "gate payload mismatch"}
    bootstrap_wormhole_persona_state()
    state = read_wormhole_persona_state()
    active_persona_id = str(state.get("active_gate_personas", {}).get(gate_key, "") or "")
    identity: dict[str, Any] | None = None
    identity_scope = "gate_session"
    for persona in list(state.get("gate_personas", {}).get(gate_key) or []):
        if str(persona.get("persona_id", "") or "") == active_persona_id:
            identity = persona
            identity_scope = "gate_persona"
            break
    # Auto-rotate persona if thresholds exceeded (pure signer swap, no MLS touch)
    if identity is not None and identity_scope == "gate_persona" and _should_rotate_persona(identity):
        try:
            from services.config import get_settings
            jitter_s = max(0.0, float(getattr(get_settings(), "MESH_GATE_PERSONA_ROTATE_JITTER_S", 0) or 0.0))
        except Exception:
            jitter_s = 0.0
        rotate_due_at = float(identity.get("_rotate_after", 0) or 0.0)
        now = time.time()
        if jitter_s > 0 and rotate_due_at <= 0:
            identity["_rotate_after"] = now + random.uniform(0.0, jitter_s)
            _write_wormhole_persona_state(state)
        elif rotate_due_at <= 0 or now >= rotate_due_at:
            _write_wormhole_persona_state(state)
            rotated = rotate_gate_persona(gate_key, reason="threshold")
            if rotated.get("ok"):
                state = read_wormhole_persona_state()
                new_pid = str(rotated.get("new_persona_id", "") or "")
                for persona in list(state.get("gate_personas", {}).get(gate_key) or []):
                    if str(persona.get("persona_id", "") or "") == new_pid:
                        identity = persona
                        break
    if identity is None:
        identity = _ensure_gate_session(state, gate_key, rotate=False)
    signed = _sign_with_identity(
        identity=identity,
        event_type=event_type,
        payload=normalized_payload,
        sequence=sequence,
    )
    if identity_scope == "gate_session":
        identity["_msg_count"] = int(identity.get("_msg_count", 0) or 0) + 1
    elif identity_scope == "gate_persona":
        identity["_msg_count"] = int(identity.get("_msg_count", 0) or 0) + 1
    _write_wormhole_persona_state(state)
    return {**signed, "identity_scope": identity_scope, "gate_id": gate_key}
