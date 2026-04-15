"""Wormhole-managed DM identity wrappers.

This module preserves the legacy DM identity API while sourcing its state from
the Wormhole persona manager. Public transport identity stays separate, and DM
operations now use the dedicated DM alias compartment.
"""

from __future__ import annotations

import base64
import hmac
import hashlib
import time
from typing import Any

from services.mesh.mesh_protocol import PROTOCOL_VERSION
from services.mesh.mesh_wormhole_persona import (
    bootstrap_wormhole_persona_state,
    ensure_dm_mailbox_client_secret,
    get_dm_identity,
    read_dm_identity,
    read_wormhole_persona_state,
    sign_dm_wormhole_event,
    sign_dm_wormhole_message,
    write_dm_identity,
)


def _safe_int(val, default=0) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _default_identity() -> dict[str, Any]:
    return {
        "bootstrapped": False,
        "bootstrapped_at": 0,
        "updated_at": 0,
        "scope": "dm_alias",
        "label": "dm-alias",
        "node_id": "",
        "public_key": "",
        "public_key_algo": "Ed25519",
        "private_key": "",
        "sequence": 0,
        "dh_pub_key": "",
        "dh_algo": "X25519",
        "dh_private_key": "",
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
    }


def _public_view(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "bootstrapped": bool(data.get("bootstrapped")),
        "bootstrapped_at": _safe_int(data.get("bootstrapped_at", 0) or 0),
        "scope": str(data.get("scope", "dm_alias") or "dm_alias"),
        "label": str(data.get("label", "dm-alias") or "dm-alias"),
        "node_id": str(data.get("node_id", "") or ""),
        "public_key": str(data.get("public_key", "") or ""),
        "public_key_algo": str(data.get("public_key_algo", "Ed25519") or "Ed25519"),
        "sequence": _safe_int(data.get("sequence", 0) or 0),
        "dh_pub_key": str(data.get("dh_pub_key", "") or ""),
        "dh_algo": str(data.get("dh_algo", "X25519") or "X25519"),
        "last_dh_timestamp": _safe_int(data.get("last_dh_timestamp", 0) or 0),
        "bundle_fingerprint": str(data.get("bundle_fingerprint", "") or ""),
        "bundle_sequence": _safe_int(data.get("bundle_sequence", 0) or 0),
        "bundle_registered_at": _safe_int(data.get("bundle_registered_at", 0) or 0),
        "protocol_version": PROTOCOL_VERSION,
    }


def read_wormhole_identity() -> dict[str, Any]:
    bootstrap_wormhole_persona_state()
    persona_state = read_wormhole_persona_state()
    data = {**_default_identity(), **read_dm_identity()}
    data["bootstrapped"] = True
    data["bootstrapped_at"] = _safe_int(persona_state.get("bootstrapped_at", 0) or 0)
    return data


def _write_identity(data: dict[str, Any]) -> dict[str, Any]:
    current = read_wormhole_identity()
    merged = {**current, **dict(data or {})}
    merged["scope"] = "dm_alias"
    merged["label"] = str(merged.get("label", "dm-alias") or "dm-alias")
    merged["updated_at"] = int(time.time())
    saved = write_dm_identity(merged)
    saved["bootstrapped"] = True
    return {**_default_identity(), **saved}


def bootstrap_wormhole_identity(force: bool = False) -> dict[str, Any]:
    bootstrap_wormhole_persona_state(force=force)
    data = read_wormhole_identity()
    if force:
        data["bundle_fingerprint"] = ""
        data["bundle_sequence"] = 0
        data["bundle_registered_at"] = 0
        data["signed_prekey_id"] = 0
        data["signed_prekey_pub"] = ""
        data["signed_prekey_priv"] = ""
        data["signed_prekey_signature"] = ""
        data["signed_prekey_generated_at"] = 0
        data["signed_prekey_history"] = []
        data["one_time_prekeys"] = []
        data["prekey_bundle_registered_at"] = 0
        data["prekey_republish_threshold"] = 0
        data["prekey_republish_target"] = 0
        data["prekey_next_republish_after"] = 0
        data = _write_identity(data)
    return _public_view(data)


def get_wormhole_identity() -> dict[str, Any]:
    return get_dm_identity()


def sign_wormhole_event(
    *,
    event_type: str,
    payload: dict[str, Any],
    sequence: int | None = None,
) -> dict[str, Any]:
    return sign_dm_wormhole_event(event_type=event_type, payload=payload, sequence=sequence)


def sign_wormhole_message(message: str) -> dict[str, Any]:
    return sign_dm_wormhole_message(message)


def _bundle_fingerprint(data: dict[str, Any]) -> str:
    raw = "|".join(
        [
            str(data.get("dh_pub_key", "")),
            str(data.get("dh_algo", "X25519")),
            str(data.get("public_key", "")),
            str(data.get("public_key_algo", "Ed25519")),
            PROTOCOL_VERSION,
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def register_wormhole_dm_key(force: bool = False) -> dict[str, Any]:
    data = read_wormhole_identity()

    timestamp = int(time.time())
    fingerprint = _bundle_fingerprint(data)
    if not force and fingerprint and fingerprint == data.get("bundle_fingerprint"):
        return {
            "ok": True,
            **_public_view(data),
        }

    payload = {
        "dh_pub_key": str(data.get("dh_pub_key", "")),
        "dh_algo": str(data.get("dh_algo", "X25519")),
        "timestamp": timestamp,
    }
    signed = sign_wormhole_event(event_type="dm_key", payload=payload)

    from services.mesh.mesh_dm_relay import dm_relay

    accepted, detail, metadata = dm_relay.register_dh_key(
        signed["node_id"],
        payload["dh_pub_key"],
        payload["dh_algo"],
        payload["timestamp"],
        signed["signature"],
        signed["public_key"],
        signed["public_key_algo"],
        signed["protocol_version"],
        signed["sequence"],
    )
    if not accepted:
        return {"ok": False, "detail": detail}

    data = read_wormhole_identity()
    data["bundle_fingerprint"] = metadata.get("bundle_fingerprint", fingerprint) if metadata else fingerprint
    data["bundle_sequence"] = _safe_int(
        metadata.get("accepted_sequence", signed["sequence"]) if metadata else signed["sequence"],
        _safe_int(signed.get("sequence", 0), 0),
    )
    data["bundle_registered_at"] = timestamp
    data["last_dh_timestamp"] = timestamp
    saved = _write_identity(data)
    return {
        "ok": True,
        **_public_view(saved),
        **(metadata or {}),
    }


def get_dm_mailbox_client_secret(*, generate: bool = True) -> str:
    return ensure_dm_mailbox_client_secret(generate=generate)


def derive_dm_mailbox_token(
    dm_alias_id: str | None = None,
    *,
    generate_secret: bool = True,
) -> str:
    data = read_wormhole_identity()
    alias_id = str(dm_alias_id or data.get("node_id", "") or "").strip()
    if not alias_id:
        return ""
    secret_b64 = get_dm_mailbox_client_secret(generate=generate_secret)
    if not secret_b64:
        return ""
    try:
        secret = base64.b64decode(secret_b64.encode("ascii"))
    except Exception:
        return ""
    return hmac.new(secret, alias_id.encode("utf-8"), hashlib.sha256).hexdigest()
