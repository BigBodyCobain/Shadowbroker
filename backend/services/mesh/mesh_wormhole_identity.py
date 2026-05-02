"""Wormhole-managed DM identity wrappers.

This module preserves the legacy DM identity API while sourcing its state from
the Wormhole persona manager. Public transport identity stays separate, and DM
operations now use the dedicated DM alias compartment.
"""

from __future__ import annotations

import base64
import hmac
import hashlib
import json
import secrets
import time
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from services.mesh.mesh_crypto import (
    build_signature_payload,
    derive_node_id,
    verify_node_binding,
    verify_signature,
)
from services.config import get_settings
from services.mesh.mesh_protocol import PROTOCOL_VERSION
from services.mesh.mesh_wormhole_persona import (
    bootstrap_wormhole_persona_state,
    ensure_dm_mailbox_client_secret,
    get_dm_identity,
    read_dm_identity,
    read_wormhole_persona_state,
    sign_root_wormhole_event,
    sign_dm_wormhole_event,
    sign_dm_wormhole_message,
    write_dm_identity,
)

DM_INVITE_EVENT_TYPE = "dm_invite"
DM_INVITE_ATTESTATION_EVENT_TYPE = "dm_invite_identity_attestation"
DM_INVITE_VERSION = 3
DM_INVITE_VERSION_COMPAT = 2
DM_INVITE_VERSION_LEGACY = 1
MAX_PREKEY_LOOKUP_HANDLES = 16
PREKEY_LOOKUP_HANDLE_TTL_CAP_DAYS = 3
PREKEY_LOOKUP_HANDLE_MAX_USES = 32
PREKEY_LOOKUP_ROTATE_BEFORE_EXPIRES_S = 24 * 60 * 60
PREKEY_LOOKUP_ROTATE_BEFORE_REMAINING_USES = 8
PREKEY_LOOKUP_ROTATION_OVERLAP_S = 12 * 60 * 60
PREKEY_LOOKUP_ROTATION_ACTIVE_CAP = 4


def _safe_int(val, default=0) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


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
        "prekey_transparency_head": "",
        "prekey_transparency_size": 0,
        "prekey_republish_threshold": 0,
        "prekey_republish_target": 0,
        "prekey_next_republish_after": 0,
        "prekey_lookup_handles": [],
        "prekey_lookup_rotation_state": "lookup_handle_rotation_ok",
        "prekey_lookup_rotation_checked_at": 0,
        "prekey_lookup_rotation_detail": "",
        "prekey_lookup_rotation_last_success_at": 0,
        "prekey_lookup_rotation_last_failure_at": 0,
    }


def _prekey_lookup_handle_record(
    handle: str,
    *,
    issued_at: int = 0,
    expires_at: int = 0,
    max_uses: int = 0,
    use_count: int = 0,
    last_used_at: int = 0,
) -> dict[str, Any]:
    issued = _safe_int(issued_at or 0, 0)
    ttl_cap_seconds = _prekey_lookup_handle_ttl_cap_s()
    bounded_expires_at = _safe_int(expires_at or 0, 0)
    if ttl_cap_seconds > 0 and issued > 0:
        ttl_cap_at = issued + ttl_cap_seconds
        if bounded_expires_at > 0:
            bounded_expires_at = min(bounded_expires_at, ttl_cap_at)
        else:
            bounded_expires_at = ttl_cap_at
    bounded_max_uses = max(1, _safe_int(max_uses or PREKEY_LOOKUP_HANDLE_MAX_USES, PREKEY_LOOKUP_HANDLE_MAX_USES))
    return {
        "handle": str(handle or "").strip(),
        "issued_at": issued,
        "expires_at": bounded_expires_at,
        "max_uses": bounded_max_uses,
        "use_count": max(0, _safe_int(use_count or 0, 0)),
        "last_used_at": max(0, _safe_int(last_used_at or 0, 0)),
    }


def _coerce_prekey_lookup_handle_record(
    value: Any,
    *,
    fallback_issued_at: int = 0,
) -> dict[str, Any] | None:
    if isinstance(value, dict):
        handle = str(
            value.get("handle", value.get("prekey_lookup_handle", value.get("token", ""))) or ""
        ).strip()
        if not handle:
            return None
        issued_at = _safe_int(
            value.get("issued_at", value.get("updated_at", value.get("created_at", fallback_issued_at))) or 0,
            fallback_issued_at,
        )
        expires_at = _safe_int(value.get("expires_at", 0) or 0, 0)
        max_uses = _safe_int(value.get("max_uses", PREKEY_LOOKUP_HANDLE_MAX_USES) or PREKEY_LOOKUP_HANDLE_MAX_USES)
        use_count = _safe_int(value.get("use_count", value.get("uses", 0)) or 0, 0)
        last_used_at = _safe_int(value.get("last_used_at", value.get("last_used", 0)) or 0, 0)
        return _prekey_lookup_handle_record(
            handle,
            issued_at=issued_at,
            expires_at=expires_at,
            max_uses=max_uses,
            use_count=use_count,
            last_used_at=last_used_at,
        )
    handle = str(value or "").strip()
    if not handle:
        return None
    return _prekey_lookup_handle_record(handle, issued_at=fallback_issued_at, expires_at=0)


def _prekey_lookup_handle_stale_after_s() -> int:
    return max(
        1,
        int(getattr(get_settings(), "MESH_DM_PREKEY_LOOKUP_ALIAS_TTL_DAYS", 14) or 14),
    ) * 86400


def _prekey_lookup_handle_ttl_cap_s() -> int:
    return min(_prekey_lookup_handle_stale_after_s(), PREKEY_LOOKUP_HANDLE_TTL_CAP_DAYS * 86400)


def _effective_prekey_lookup_handle_expires_at(record: dict[str, Any]) -> int:
    explicit_expires_at = _safe_int(record.get("expires_at", 0) or 0, 0)
    if explicit_expires_at > 0:
        return explicit_expires_at
    issued_at = _safe_int(record.get("issued_at", 0) or 0, 0)
    if issued_at <= 0:
        return 0
    return issued_at + _prekey_lookup_handle_stale_after_s()


def _prekey_lookup_handle_exhausted(record: dict[str, Any]) -> bool:
    max_uses = max(1, _safe_int(record.get("max_uses", PREKEY_LOOKUP_HANDLE_MAX_USES) or PREKEY_LOOKUP_HANDLE_MAX_USES))
    use_count = max(0, _safe_int(record.get("use_count", 0) or 0, 0))
    return use_count >= max_uses


def _prekey_lookup_handle_remaining_ttl_s(record: dict[str, Any], *, now: int | None = None) -> int:
    current_time = _safe_int(now or time.time(), int(time.time()))
    expires_at = _effective_prekey_lookup_handle_expires_at(record)
    if expires_at <= 0:
        return 0
    return max(0, expires_at - current_time)


def _prekey_lookup_handle_remaining_uses(record: dict[str, Any]) -> int:
    max_uses = max(1, _safe_int(record.get("max_uses", PREKEY_LOOKUP_HANDLE_MAX_USES) or PREKEY_LOOKUP_HANDLE_MAX_USES))
    use_count = max(0, _safe_int(record.get("use_count", 0) or 0, 0))
    return max(0, max_uses - use_count)


def _prekey_lookup_handle_needs_rotation(record: dict[str, Any], *, now: int | None = None) -> bool:
    if _prekey_lookup_handle_exhausted(record):
        return True
    return (
        _prekey_lookup_handle_remaining_ttl_s(record, now=now) <= PREKEY_LOOKUP_ROTATE_BEFORE_EXPIRES_S
        or _prekey_lookup_handle_remaining_uses(record) <= PREKEY_LOOKUP_ROTATE_BEFORE_REMAINING_USES
    )


def _fresh_prekey_lookup_handle_record(*, now: int | None = None) -> dict[str, Any]:
    current_time = _safe_int(now or time.time(), int(time.time()))
    return _prekey_lookup_handle_record(
        secrets.token_hex(24),
        issued_at=current_time,
        expires_at=0,
        max_uses=PREKEY_LOOKUP_HANDLE_MAX_USES,
        use_count=0,
        last_used_at=0,
    )


def _bounded_lookup_handle_records(
    records: list[dict[str, Any]],
    *,
    now: int | None = None,
) -> list[dict[str, Any]]:
    current_time = _safe_int(now or time.time(), int(time.time()))
    normalized, _ = _normalize_prekey_lookup_handles(
        records,
        fallback_issued_at=current_time,
        now=current_time,
    )
    if len(normalized) <= PREKEY_LOOKUP_ROTATION_ACTIVE_CAP:
        return normalized

    def _sort_key(record: dict[str, Any]) -> tuple[int, int, int]:
        fresh_rank = 1 if not _prekey_lookup_handle_needs_rotation(record, now=current_time) else 0
        expires_at = _effective_prekey_lookup_handle_expires_at(record)
        return (
            fresh_rank,
            _safe_int(record.get("issued_at", 0) or 0, 0),
            expires_at,
        )

    ordered = sorted(normalized, key=_sort_key, reverse=True)
    bounded = ordered[:PREKEY_LOOKUP_ROTATION_ACTIVE_CAP]
    bounded_sorted = sorted(
        bounded,
        key=lambda record: (
            _safe_int(record.get("issued_at", 0) or 0, 0),
            _effective_prekey_lookup_handle_expires_at(record),
        ),
    )
    return bounded_sorted


def _lookup_handle_rotation_observed_state(
    *,
    data: dict[str, Any] | None = None,
    records: list[dict[str, Any]] | None = None,
    now: int | None = None,
) -> tuple[str, str]:
    current_time = _safe_int(now or time.time(), int(time.time()))
    current_data = dict(data or read_wormhole_identity())
    current_records = list(records or get_prekey_lookup_handle_records())
    if not current_records:
        return "lookup_handle_rotation_ok", "no active lookup handles"
    fresh_available = any(
        not _prekey_lookup_handle_needs_rotation(record, now=current_time)
        for record in current_records
    )
    persisted_state = str(current_data.get("prekey_lookup_rotation_state", "") or "").strip()
    persisted_detail = str(current_data.get("prekey_lookup_rotation_detail", "") or "").strip()
    if fresh_available:
        return "lookup_handle_rotation_ok", "lookup handles healthy"
    if persisted_state == "lookup_handle_rotation_failed":
        return "lookup_handle_rotation_failed", persisted_detail or "lookup handle rotation failed"
    return "lookup_handle_rotation_pending", "lookup handle rollover pending"


def _normalize_prekey_lookup_handles(
    values: Any,
    *,
    fallback_issued_at: int = 0,
    now: int | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    current_time = _safe_int(now or time.time(), int(time.time()))
    changed = False
    normalized: list[dict[str, Any]] = []
    index_by_handle: dict[str, int] = {}

    for value in list(values or []):
        record = _coerce_prekey_lookup_handle_record(value, fallback_issued_at=fallback_issued_at)
        if not record:
            changed = True
            continue
        effective_expires_at = _effective_prekey_lookup_handle_expires_at(record)
        if effective_expires_at > 0 and effective_expires_at < current_time:
            changed = True
            continue
        if _prekey_lookup_handle_exhausted(record):
            changed = True
            continue
        handle = str(record.get("handle", "") or "").strip()
        if not handle:
            changed = True
            continue
        existing_index = index_by_handle.get(handle)
        if existing_index is not None:
            normalized[existing_index] = record
            changed = True
            continue
        normalized.append(record)
        index_by_handle[handle] = len(normalized) - 1
        if value != record:
            changed = True

    if len(normalized) > MAX_PREKEY_LOOKUP_HANDLES:
        normalized = normalized[-MAX_PREKEY_LOOKUP_HANDLES:]
        changed = True

    return normalized, changed


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
        "prekey_transparency_head": str(data.get("prekey_transparency_head", "") or ""),
        "prekey_transparency_size": _safe_int(data.get("prekey_transparency_size", 0) or 0),
        "protocol_version": PROTOCOL_VERSION,
    }


def read_wormhole_identity() -> dict[str, Any]:
    bootstrap_wormhole_persona_state()
    persona_state = read_wormhole_persona_state()
    data = {**_default_identity(), **read_dm_identity()}
    fallback_issued_at = max(
        _safe_int(data.get("updated_at", 0) or 0, 0),
        _safe_int(data.get("bundle_registered_at", 0) or 0, 0),
        _safe_int(persona_state.get("bootstrapped_at", 0) or 0, 0),
    )
    normalized_handles, handles_changed = _normalize_prekey_lookup_handles(
        data.get("prekey_lookup_handles", []),
        fallback_issued_at=fallback_issued_at,
    )
    data["prekey_lookup_handles"] = normalized_handles
    if handles_changed:
        saved = write_dm_identity({"prekey_lookup_handles": normalized_handles})
        data = {**_default_identity(), **saved}
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
        data["prekey_transparency_head"] = ""
        data["prekey_transparency_size"] = 0
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


def trust_fingerprint_for_identity_material(
    *,
    agent_id: str,
    identity_dh_pub_key: str,
    dh_algo: str,
    public_key: str,
    public_key_algo: str,
    protocol_version: str,
) -> str:
    material = {
        "agent_id": str(agent_id or "").strip(),
        "identity_dh_pub_key": str(identity_dh_pub_key or "").strip(),
        "dh_algo": str(dh_algo or "X25519") or "X25519",
        "public_key": str(public_key or "").strip(),
        "public_key_algo": str(public_key_algo or "Ed25519") or "Ed25519",
        "protocol_version": str(protocol_version or PROTOCOL_VERSION) or PROTOCOL_VERSION,
    }
    return hashlib.sha256(_stable_json(material).encode("utf-8")).hexdigest()


def root_identity_fingerprint_for_material(
    *,
    root_node_id: str,
    root_public_key: str,
    root_public_key_algo: str,
    protocol_version: str,
) -> str:
    material = {
        "root_node_id": str(root_node_id or "").strip(),
        "root_public_key": str(root_public_key or "").strip(),
        "root_public_key_algo": str(root_public_key_algo or "Ed25519") or "Ed25519",
        "protocol_version": str(protocol_version or PROTOCOL_VERSION) or PROTOCOL_VERSION,
    }
    return hashlib.sha256(_stable_json(material).encode("utf-8")).hexdigest()


def invite_identity_commitment_for_identity_material(
    *,
    identity_dh_pub_key: str,
    dh_algo: str,
    public_key: str,
    public_key_algo: str,
    protocol_version: str,
) -> str:
    material = {
        "identity_dh_pub_key": str(identity_dh_pub_key or "").strip(),
        "dh_algo": str(dh_algo or "X25519") or "X25519",
        "public_key": str(public_key or "").strip(),
        "public_key_algo": str(public_key_algo or "Ed25519") or "Ed25519",
        "protocol_version": str(protocol_version or PROTOCOL_VERSION) or PROTOCOL_VERSION,
    }
    return hashlib.sha256(_stable_json(material).encode("utf-8")).hexdigest()


def _dm_invite_payload(
    data: dict[str, Any],
    *,
    issued_at: int,
    expires_at: int = 0,
    label: str = "",
) -> dict[str, Any]:
    payload = {
        "invite_version": DM_INVITE_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "issued_at": int(issued_at or 0),
        "expires_at": int(expires_at or 0),
        "label": str(label or "").strip(),
        "attestations": [],
    }
    payload["identity_commitment"] = invite_identity_commitment_for_identity_material(
        identity_dh_pub_key=str(data.get("dh_pub_key", "") or "").strip(),
        dh_algo=str(data.get("dh_algo", "X25519") or "X25519"),
        public_key=str(data.get("public_key", "") or "").strip(),
        public_key_algo=str(data.get("public_key_algo", "Ed25519") or "Ed25519"),
        protocol_version=str(payload["protocol_version"]),
    )
    return payload


def _dm_invite_identity_attestation_payload(
    *,
    payload: dict[str, Any],
    invite_node_id: str,
    invite_public_key: str,
    invite_public_key_algo: str,
) -> dict[str, Any]:
    root_manifest = dict(payload.get("root_manifest") or {})
    root_manifest_fingerprint = ""
    if root_manifest:
        from services.mesh.mesh_wormhole_root_manifest import manifest_fingerprint_for_envelope

        root_manifest_fingerprint = manifest_fingerprint_for_envelope(root_manifest)
    return {
        "invite_version": _safe_int(payload.get("invite_version", 0) or 0, 0),
        "protocol_version": str(payload.get("protocol_version", PROTOCOL_VERSION) or PROTOCOL_VERSION),
        "issued_at": _safe_int(payload.get("issued_at", 0) or 0, 0),
        "expires_at": _safe_int(payload.get("expires_at", 0) or 0, 0),
        "identity_commitment": str(payload.get("identity_commitment", "") or "").strip().lower(),
        "prekey_lookup_handle": str(payload.get("prekey_lookup_handle", "") or "").strip(),
        "root_manifest_fingerprint": root_manifest_fingerprint,
        "invite_node_id": str(invite_node_id or "").strip(),
        "invite_public_key": str(invite_public_key or "").strip(),
        "invite_public_key_algo": str(invite_public_key_algo or "Ed25519") or "Ed25519",
    }


def _attach_dm_invite_identity_attestation(
    payload: dict[str, Any],
    *,
    invite_node_id: str,
    invite_public_key: str,
    invite_public_key_algo: str = "Ed25519",
) -> dict[str, Any]:
    attestation_payload = _dm_invite_identity_attestation_payload(
        payload=payload,
        invite_node_id=invite_node_id,
        invite_public_key=invite_public_key,
        invite_public_key_algo=invite_public_key_algo,
    )
    signed = sign_root_wormhole_event(
        event_type=DM_INVITE_ATTESTATION_EVENT_TYPE,
        payload=attestation_payload,
    )
    attestations = list(payload.get("attestations") or [])
    attestations.append(
        {
            "type": "stable_dm_identity",
            "event_type": DM_INVITE_ATTESTATION_EVENT_TYPE,
            "protocol_version": str(signed.get("protocol_version", PROTOCOL_VERSION) or PROTOCOL_VERSION),
            "public_key_algo": str(signed.get("public_key_algo", "Ed25519") or "Ed25519"),
            "sequence": _safe_int(signed.get("sequence", 0) or 0, 0),
            "signature": str(signed.get("signature", "") or "").strip(),
            "signer_scope": str(signed.get("identity_scope", "root") or "root"),
            "root_node_id": str(signed.get("node_id", "") or "").strip(),
            "root_public_key": str(signed.get("public_key", "") or "").strip(),
            "root_public_key_algo": str(signed.get("public_key_algo", "Ed25519") or "Ed25519"),
            "root_manifest_fingerprint": str(
                signed.get("payload", {}).get("root_manifest_fingerprint", "") or ""
            ).strip().lower(),
        }
    )
    payload["attestations"] = attestations
    return payload


def _attach_dm_invite_root_distribution(payload: dict[str, Any]) -> dict[str, Any]:
    current = dict(payload or {})
    from services.mesh.mesh_wormhole_root_manifest import get_current_root_manifest
    from services.mesh.mesh_wormhole_root_transparency import get_current_root_transparency_record

    distribution = get_current_root_manifest()
    transparency = get_current_root_transparency_record(distribution=distribution)
    current["root_manifest"] = dict(distribution.get("manifest") or {})
    current["root_manifest_witness"] = dict(distribution.get("witness") or {})
    current["root_manifest_witnesses"] = [
        dict(item or {}) for item in list(distribution.get("witnesses") or []) if isinstance(item, dict)
    ]
    current["root_transparency_record"] = dict(transparency.get("record") or {})
    return current


def _verify_dm_invite_root_distribution(payload: dict[str, Any]) -> dict[str, Any]:
    manifest = dict(payload.get("root_manifest") or {})
    witnesses = [
        dict(item or {})
        for item in list(payload.get("root_manifest_witnesses") or [])
        if isinstance(item, dict)
    ]
    legacy_witness = dict(payload.get("root_manifest_witness") or {})
    if legacy_witness and not witnesses:
        witnesses = [legacy_witness]
    transparency_record = dict(payload.get("root_transparency_record") or {})
    if not manifest:
        return {"ok": False, "detail": "invite root manifest required"}
    if not witnesses:
        return {"ok": False, "detail": "invite root witness receipts required"}
    if not transparency_record:
        return {"ok": False, "detail": "invite root transparency record required"}

    from services.mesh.mesh_wormhole_root_manifest import (
        verify_root_manifest,
        verify_root_manifest_witness_set,
    )
    from services.mesh.mesh_wormhole_root_transparency import (
        verify_root_transparency_record,
    )

    manifest_verified = verify_root_manifest(manifest)
    if not manifest_verified.get("ok"):
        return {"ok": False, "detail": str(manifest_verified.get("detail", "") or "invite root manifest invalid")}
    witness_verified = verify_root_manifest_witness_set(manifest, witnesses)
    if not witness_verified.get("ok"):
        return {"ok": False, "detail": str(witness_verified.get("detail", "") or "invite root witness invalid")}
    transparency_verified = verify_root_transparency_record(transparency_record, manifest, witnesses)
    if not transparency_verified.get("ok"):
        return {
            "ok": False,
            "detail": str(
                transparency_verified.get("detail", "") or "invite root transparency record invalid"
            ),
        }
    resolved = {
        "ok": True,
        "root_manifest_fingerprint": str(manifest_verified.get("manifest_fingerprint", "") or "").strip().lower(),
        "root_manifest_generation": _safe_int(manifest_verified.get("generation", 0) or 0, 0),
        "root_manifest_policy_version": _safe_int(manifest_verified.get("policy_version", 1) or 1, 1),
        "root_witness_policy_fingerprint": str(
            manifest_verified.get("witness_policy_fingerprint", "") or ""
        ).strip().lower(),
        "root_witness_threshold": _safe_int(witness_verified.get("witness_threshold", 0) or 0, 0),
        "root_witness_count": _safe_int(witness_verified.get("witness_count", 0) or 0, 0),
        "root_witness_domain_count": _safe_int(witness_verified.get("witness_domain_count", 0) or 0, 0),
        "root_witness_independent_quorum_met": bool(
            witness_verified.get("witness_independent_quorum_met")
        ),
        "root_witness_finality_met": bool(witness_verified.get("witness_finality_met")),
        "root_rotation_proven": bool(manifest_verified.get("rotation_proven")),
        "root_witness_policy_change_proven": bool(manifest_verified.get("policy_change_proven")),
        "root_transparency_fingerprint": str(
            transparency_verified.get("record_fingerprint", "") or ""
        ).strip().lower(),
        "root_transparency_binding_fingerprint": str(
            transparency_verified.get("binding_fingerprint", "") or ""
        ).strip().lower(),
        "root_node_id": str(manifest_verified.get("root_node_id", "") or "").strip(),
        "root_public_key": str(manifest_verified.get("root_public_key", "") or "").strip(),
        "root_public_key_algo": str(manifest_verified.get("root_public_key_algo", "Ed25519") or "Ed25519"),
        "root_fingerprint": str(manifest_verified.get("root_fingerprint", "") or "").strip().lower(),
        "root_external_witness_source_configured": False,
        "root_external_transparency_readback_configured": False,
    }
    if resolved["root_manifest_generation"] > 1 and not resolved["root_rotation_proven"]:
        return {**resolved, "ok": False, "detail": "invite root rotation proof required"}
    if not resolved["root_witness_policy_change_proven"]:
        return {**resolved, "ok": False, "detail": "invite root witness policy change proof required"}
    return resolved


def _verify_dm_invite_identity_attestation(
    *,
    envelope: dict[str, Any],
    payload: dict[str, Any],
    resolved_root_node_id: str,
    resolved_root_public_key: str,
    resolved_root_public_key_algo: str,
    resolved_root_manifest_fingerprint: str,
) -> dict[str, Any]:
    attestations = list(payload.get("attestations") or [])
    attestation = next(
        (
            dict(item or {})
            for item in attestations
            if isinstance(item, dict) and str(item.get("type", "") or "").strip().lower() == "stable_dm_identity"
        ),
        {},
    )
    if not attestation:
        return {"ok": False, "detail": "invite stable identity attestation required"}

    sequence = _safe_int(attestation.get("sequence", 0) or 0, 0)
    signature = str(attestation.get("signature", "") or "").strip()
    protocol_version = str(attestation.get("protocol_version", PROTOCOL_VERSION) or PROTOCOL_VERSION).strip()
    public_key_algo = str(
        attestation.get("root_public_key_algo", attestation.get("public_key_algo", resolved_root_public_key_algo))
        or resolved_root_public_key_algo
    ).strip()
    root_manifest_fingerprint = str(attestation.get("root_manifest_fingerprint", "") or "").strip().lower()
    if not signature or sequence <= 0:
        return {"ok": False, "detail": "invite stable identity attestation incomplete"}
    if not root_manifest_fingerprint:
        return {"ok": False, "detail": "invite stable identity attestation manifest required"}
    if protocol_version != str(payload.get("protocol_version", PROTOCOL_VERSION) or PROTOCOL_VERSION).strip():
        return {"ok": False, "detail": "invite stable identity attestation protocol mismatch"}
    root_node_id = str(attestation.get("root_node_id", "") or "").strip() or str(resolved_root_node_id or "").strip()
    root_public_key = str(attestation.get("root_public_key", "") or "").strip() or str(
        resolved_root_public_key or ""
    ).strip()
    if not root_node_id or not root_public_key:
        return {"ok": False, "detail": "invite stable identity root required"}
    if root_node_id != str(resolved_root_node_id or "").strip():
        return {"ok": False, "detail": "invite stable identity attestation root mismatch"}
    if root_public_key != str(resolved_root_public_key or "").strip():
        return {"ok": False, "detail": "invite stable identity attestation root mismatch"}
    if public_key_algo != str(resolved_root_public_key_algo or "Ed25519").strip():
        return {"ok": False, "detail": "invite stable identity attestation root mismatch"}
    if root_manifest_fingerprint != str(resolved_root_manifest_fingerprint or "").strip().lower():
        return {"ok": False, "detail": "invite stable identity attestation manifest mismatch"}
    if not verify_node_binding(root_node_id, root_public_key):
        return {"ok": False, "detail": "invite stable identity attestation root binding invalid"}

    attestation_payload = _dm_invite_identity_attestation_payload(
        payload=payload,
        invite_node_id=str(envelope.get("node_id", "") or "").strip(),
        invite_public_key=str(envelope.get("public_key", "") or "").strip(),
        invite_public_key_algo=str(envelope.get("public_key_algo", "Ed25519") or "Ed25519"),
    )
    signed_payload = build_signature_payload(
        event_type=DM_INVITE_ATTESTATION_EVENT_TYPE,
        node_id=root_node_id,
        sequence=sequence,
        payload=attestation_payload,
    )
    if not verify_signature(
        public_key_b64=root_public_key,
        public_key_algo=str(public_key_algo or resolved_root_public_key_algo or "Ed25519"),
        signature_hex=signature,
        payload=signed_payload,
    ):
        return {"ok": False, "detail": "invite stable identity attestation invalid"}
    return {
        "ok": True,
        "root_node_id": root_node_id,
        "root_public_key": root_public_key,
        "root_public_key_algo": str(public_key_algo or resolved_root_public_key_algo or "Ed25519"),
        "root_fingerprint": root_identity_fingerprint_for_material(
            root_node_id=root_node_id,
            root_public_key=root_public_key,
            root_public_key_algo=str(public_key_algo or resolved_root_public_key_algo or "Ed25519"),
            protocol_version=str(payload.get("protocol_version", PROTOCOL_VERSION) or PROTOCOL_VERSION),
        ),
    }


def _generate_invite_signing_identity() -> tuple[str, str, str]:
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
    public_key = base64.b64encode(signing_pub_raw).decode("ascii")
    private_key = base64.b64encode(signing_priv_raw).decode("ascii")
    return derive_node_id(public_key), public_key, private_key


def _sign_dm_invite_payload(
    *,
    node_id: str,
    public_key: str,
    private_key: str,
    payload: dict[str, Any],
    sequence: int = 1,
) -> dict[str, Any]:
    signature_payload = build_signature_payload(
        event_type=DM_INVITE_EVENT_TYPE,
        node_id=node_id,
        sequence=sequence,
        payload=payload,
    )
    signer = ed25519.Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_key.encode("ascii")))
    return {
        "node_id": node_id,
        "public_key": public_key,
        "public_key_algo": "Ed25519",
        "protocol_version": PROTOCOL_VERSION,
        "sequence": int(sequence),
        "signature": signer.sign(signature_payload.encode("utf-8")).hex(),
    }


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


def export_wormhole_dm_invite(*, label: str = "", expires_in_s: int = 0) -> dict[str, Any]:
    data = read_wormhole_identity()
    if not data.get("bootstrapped"):
        bootstrap_wormhole_identity()
        data = read_wormhole_identity()

    issued_at = int(time.time())
    expiry_window = max(0, _safe_int(expires_in_s or 0, 0))
    expires_at = issued_at + expiry_window if expiry_window > 0 else 0
    payload = _dm_invite_payload(
        data,
        issued_at=issued_at,
        expires_at=expires_at,
        label=str(label or "").strip(),
    )

    # Generate an invite-scoped prekey lookup handle so the recipient can
    # fetch our prekey bundle without using our stable agent_id.
    lookup_handle = secrets.token_hex(24)
    payload["prekey_lookup_handle"] = lookup_handle

    # Persist the handle so it is included in future prekey registrations.
    existing_handles, _ = _normalize_prekey_lookup_handles(
        data.get("prekey_lookup_handles", []),
        fallback_issued_at=issued_at,
        now=issued_at,
    )
    existing_handles.append(
        _prekey_lookup_handle_record(
            lookup_handle,
            issued_at=issued_at,
            expires_at=expires_at,
        )
    )
    data["prekey_lookup_handles"], _ = _normalize_prekey_lookup_handles(
        existing_handles,
        fallback_issued_at=issued_at,
        now=issued_at,
    )
    saved = _write_identity(data)
    saved_record = next(
        (
            dict(item)
            for item in list(saved.get("prekey_lookup_handles") or [])
            if str(item.get("handle", "") or "").strip() == lookup_handle
        ),
        {},
    )

    # Also register the alias immediately with the local relay so invite-scoped
    # lookup works right away even if the next full prekey republish has not
    # happened yet.
    try:
        from services.mesh.mesh_dm_relay import dm_relay

        dm_relay.register_prekey_lookup_alias(
            lookup_handle,
            str(saved.get("node_id", "") or ""),
            expires_at=_safe_int(saved_record.get("expires_at", 0) or 0, 0),
            max_uses=_safe_int(saved_record.get("max_uses", PREKEY_LOOKUP_HANDLE_MAX_USES) or PREKEY_LOOKUP_HANDLE_MAX_USES),
            use_count=_safe_int(saved_record.get("use_count", 0) or 0, 0),
            last_used_at=_safe_int(saved_record.get("last_used_at", 0) or 0, 0),
        )
    except Exception:
        pass

    try:
        from services.mesh.mesh_wormhole_prekey import register_wormhole_prekey_bundle

        registered = register_wormhole_prekey_bundle()
        if not registered.get("ok"):
            return {"ok": False, "detail": str(registered.get("detail", "") or "prekey bundle registration failed")}
    except Exception as exc:
        return {"ok": False, "detail": str(exc) or "prekey bundle registration failed"}

    invite_node_id, invite_public_key, invite_private_key = _generate_invite_signing_identity()
    payload = _attach_dm_invite_root_distribution(payload)
    payload = _attach_dm_invite_identity_attestation(
        payload,
        invite_node_id=invite_node_id,
        invite_public_key=invite_public_key,
    )
    signed = _sign_dm_invite_payload(
        node_id=invite_node_id,
        public_key=invite_public_key,
        private_key=invite_private_key,
        payload=payload,
    )
    invite = {
        "event_type": DM_INVITE_EVENT_TYPE,
        "payload": payload,
        "node_id": str(signed.get("node_id", "") or ""),
        "public_key": str(signed.get("public_key", "") or ""),
        "public_key_algo": str(signed.get("public_key_algo", "") or ""),
        "protocol_version": str(signed.get("protocol_version", PROTOCOL_VERSION) or PROTOCOL_VERSION),
        "sequence": _safe_int(signed.get("sequence", 0) or 0),
        "signature": str(signed.get("signature", "") or ""),
        "identity_scope": str(signed.get("identity_scope", "dm_alias") or "dm_alias"),
    }
    return {
        "ok": True,
        "peer_id": str(invite_node_id or ""),
        "trust_fingerprint": str(payload.get("identity_commitment", "") or ""),
        "invite": invite,
    }


def get_prekey_lookup_handles() -> list[str]:
    """Return active prekey lookup handles for prekey bundle registration."""
    return [
        str(item.get("handle", "") or "").strip()
        for item in get_prekey_lookup_handle_records()
        if str(item.get("handle", "") or "").strip()
    ]


def get_prekey_lookup_handle_records() -> list[dict[str, Any]]:
    """Return active prekey lookup handle records with bounded lifetime/use metadata."""
    data = read_wormhole_identity()
    return [
        dict(item)
        for item in list(data.get("prekey_lookup_handles") or [])
        if isinstance(item, dict) and str(item.get("handle", "") or "").strip()
    ]


def record_prekey_lookup_handle_use(handle: str, *, now: int | None = None) -> dict[str, Any] | None:
    lookup_handle = str(handle or "").strip()
    if not lookup_handle:
        return None
    data = read_wormhole_identity()
    current_time = _safe_int(now or time.time(), int(time.time()))
    existing, _ = _normalize_prekey_lookup_handles(
        data.get("prekey_lookup_handles", []),
        fallback_issued_at=current_time,
        now=current_time,
    )
    updated = False
    next_records: list[dict[str, Any]] = []
    matched: dict[str, Any] | None = None
    for record in existing:
        current = dict(record)
        if str(current.get("handle", "") or "").strip() == lookup_handle:
            current = _prekey_lookup_handle_record(
                lookup_handle,
                issued_at=_safe_int(current.get("issued_at", 0) or 0, current_time),
                expires_at=_safe_int(current.get("expires_at", 0) or 0, 0),
                max_uses=_safe_int(current.get("max_uses", PREKEY_LOOKUP_HANDLE_MAX_USES) or PREKEY_LOOKUP_HANDLE_MAX_USES),
                use_count=_safe_int(current.get("use_count", 0) or 0, 0) + 1,
                last_used_at=current_time,
            )
            updated = True
            matched = current
        next_records.append(current)
    normalized_records, _ = _normalize_prekey_lookup_handles(
        next_records,
        fallback_issued_at=current_time,
        now=current_time,
    )
    if updated:
        _write_identity({"prekey_lookup_handles": normalized_records})
    if not matched:
        return None
    for record in normalized_records:
        if str(record.get("handle", "") or "").strip() == lookup_handle:
            return dict(record)
    return None


def lookup_handle_rotation_status_snapshot(*, now: int | None = None) -> dict[str, Any]:
    current_time = _safe_int(now or time.time(), int(time.time()))
    data = read_wormhole_identity()
    records = get_prekey_lookup_handle_records()
    state, detail = _lookup_handle_rotation_observed_state(
        data=data,
        records=records,
        now=current_time,
    )
    return {
        "state": state,
        "detail": detail,
        "checked_at": _safe_int(data.get("prekey_lookup_rotation_checked_at", 0) or 0, 0),
        "last_success_at": _safe_int(data.get("prekey_lookup_rotation_last_success_at", 0) or 0, 0),
        "last_failure_at": _safe_int(data.get("prekey_lookup_rotation_last_failure_at", 0) or 0, 0),
        "active_handle_count": len(records),
        "fresh_handle_available": any(
            not _prekey_lookup_handle_needs_rotation(record, now=current_time)
            for record in records
        ),
    }


def maybe_rotate_prekey_lookup_handles(*, now: int | None = None) -> dict[str, Any]:
    current_time = _safe_int(now or time.time(), int(time.time()))
    data = read_wormhole_identity()
    current_records = get_prekey_lookup_handle_records()
    if not current_records:
        observed_state, observed_detail = _lookup_handle_rotation_observed_state(
            data=data,
            records=[],
            now=current_time,
        )
        if (
            observed_state != str(data.get("prekey_lookup_rotation_state", "") or "").strip()
            or observed_detail != str(data.get("prekey_lookup_rotation_detail", "") or "").strip()
            or _safe_int(data.get("prekey_lookup_rotation_checked_at", 0) or 0, 0) != current_time
        ):
            _write_identity(
                {
                    "prekey_lookup_rotation_state": observed_state,
                    "prekey_lookup_rotation_checked_at": current_time,
                    "prekey_lookup_rotation_detail": observed_detail,
                }
            )
        return {
            "ok": True,
            "rotated": False,
            "state": observed_state,
            "detail": observed_detail,
            "active_handle_count": 0,
        }
    healthy_records = [
        dict(record)
        for record in current_records
        if not _prekey_lookup_handle_needs_rotation(record, now=current_time)
    ]
    stale_records = [
        dict(record)
        for record in current_records
        if _prekey_lookup_handle_needs_rotation(record, now=current_time)
    ]
    if healthy_records:
        observed_state, observed_detail = _lookup_handle_rotation_observed_state(
            data=data,
            records=current_records,
            now=current_time,
        )
        if (
            observed_state != str(data.get("prekey_lookup_rotation_state", "") or "").strip()
            or observed_detail != str(data.get("prekey_lookup_rotation_detail", "") or "").strip()
        ):
            _write_identity(
                {
                    "prekey_lookup_rotation_state": observed_state,
                    "prekey_lookup_rotation_detail": observed_detail,
                }
            )
        return {
            "ok": True,
            "rotated": False,
            "state": observed_state,
            "detail": observed_detail,
            "active_handle_count": len(current_records),
        }

    previous_records = [dict(record) for record in current_records]
    replacement = _fresh_prekey_lookup_handle_record(now=current_time)
    replacement_handle = str(replacement.get("handle", "") or "").strip()
    rollover_mapping: dict[str, str] = {}
    candidate_records: list[dict[str, Any]] = []
    for record in stale_records:
        old_handle = str(record.get("handle", "") or "").strip()
        if old_handle:
            rollover_mapping[old_handle] = replacement_handle
        if _prekey_lookup_handle_exhausted(record):
            continue
        overlap_expires_at = current_time + PREKEY_LOOKUP_ROTATION_OVERLAP_S
        existing_expires_at = _effective_prekey_lookup_handle_expires_at(record)
        if existing_expires_at > 0:
            overlap_expires_at = min(overlap_expires_at, existing_expires_at)
        if overlap_expires_at <= current_time:
            continue
        candidate_records.append(
            _prekey_lookup_handle_record(
                old_handle,
                issued_at=_safe_int(record.get("issued_at", 0) or 0, current_time),
                expires_at=overlap_expires_at,
                max_uses=_safe_int(record.get("max_uses", PREKEY_LOOKUP_HANDLE_MAX_USES) or PREKEY_LOOKUP_HANDLE_MAX_USES),
                use_count=_safe_int(record.get("use_count", 0) or 0, 0),
                last_used_at=_safe_int(record.get("last_used_at", 0) or 0, 0),
            )
        )
    candidate_records.extend(healthy_records)
    candidate_records.append(replacement)
    candidate_records = _bounded_lookup_handle_records(candidate_records, now=current_time)
    if not candidate_records:
        candidate_records = [replacement]

    pending_detail = "lookup handle rollover pending"
    _write_identity(
        {
            "prekey_lookup_handles": candidate_records,
            "prekey_lookup_rotation_state": "lookup_handle_rotation_pending",
            "prekey_lookup_rotation_checked_at": current_time,
            "prekey_lookup_rotation_detail": pending_detail,
        }
    )
    try:
        from services.mesh.mesh_wormhole_prekey import register_wormhole_prekey_bundle

        published = register_wormhole_prekey_bundle()
    except Exception as exc:
        published = {"ok": False, "detail": str(exc) or "lookup handle rotation failed"}
    if not bool(published.get("ok")):
        _write_identity(
            {
                "prekey_lookup_handles": previous_records,
                "prekey_lookup_rotation_state": "lookup_handle_rotation_failed",
                "prekey_lookup_rotation_checked_at": current_time,
                "prekey_lookup_rotation_last_failure_at": current_time,
                "prekey_lookup_rotation_detail": str(
                    published.get("detail", "") or "lookup handle rotation failed"
                ).strip(),
            }
        )
        return {
            "ok": False,
            "rotated": False,
            "state": "lookup_handle_rotation_failed",
            "detail": str(published.get("detail", "") or "lookup handle rotation failed").strip(),
            "active_handle_count": len(previous_records),
        }

    try:
        from services.mesh.mesh_wormhole_contacts import roll_forward_invite_lookup_handles

        updated_contacts = roll_forward_invite_lookup_handles(
            rollover_mapping,
            invite_node_id=str(data.get("node_id", "") or "").strip(),
        )
    except Exception:
        updated_contacts = 0
    saved = _write_identity(
        {
            "prekey_lookup_rotation_state": "lookup_handle_rotation_ok",
            "prekey_lookup_rotation_checked_at": current_time,
            "prekey_lookup_rotation_last_success_at": current_time,
            "prekey_lookup_rotation_detail": "lookup handle rotation healthy",
        }
    )
    active_records = [
        dict(item)
        for item in list(saved.get("prekey_lookup_handles") or [])
        if isinstance(item, dict)
    ]
    return {
        "ok": True,
        "rotated": True,
        "state": "lookup_handle_rotation_ok",
        "detail": "lookup handle rotation healthy",
        "active_handle_count": len(active_records),
        "updated_contacts": updated_contacts,
    }


def verify_wormhole_dm_invite(invite: dict[str, Any]) -> dict[str, Any]:
    envelope = dict(invite or {})
    payload = dict(envelope.get("payload") or {})
    if not payload:
        return {"ok": False, "detail": "invite payload required"}
    if str(envelope.get("event_type", DM_INVITE_EVENT_TYPE) or DM_INVITE_EVENT_TYPE) != DM_INVITE_EVENT_TYPE:
        return {"ok": False, "detail": "unsupported invite event_type"}

    peer_id = str(envelope.get("node_id", "") or "").strip()
    public_key = str(envelope.get("public_key", "") or "").strip()
    public_key_algo = str(envelope.get("public_key_algo", "") or "").strip()
    protocol_version = str(envelope.get("protocol_version", PROTOCOL_VERSION) or PROTOCOL_VERSION).strip()
    signature = str(envelope.get("signature", "") or "").strip()
    sequence = _safe_int(envelope.get("sequence", 0) or 0)

    if not peer_id or not public_key or not public_key_algo or not signature:
        return {"ok": False, "detail": "invite signature envelope incomplete"}
    if protocol_version != str(payload.get("protocol_version", PROTOCOL_VERSION) or PROTOCOL_VERSION).strip():
        return {"ok": False, "detail": "invite protocol version mismatch"}
    invite_version = _safe_int(payload.get("invite_version", 0) or 0, 0)
    if invite_version not in (DM_INVITE_VERSION_LEGACY, DM_INVITE_VERSION_COMPAT, DM_INVITE_VERSION):
        return {"ok": False, "detail": "unsupported invite version"}
    if not verify_node_binding(peer_id, public_key):
        return {"ok": False, "detail": "invite node binding invalid"}

    expires_at = _safe_int(payload.get("expires_at", 0) or 0, 0)
    if expires_at > 0 and expires_at < int(time.time()):
        return {"ok": False, "detail": "invite expired"}

    if invite_version == DM_INVITE_VERSION_LEGACY:
        if peer_id != str(payload.get("agent_id", "") or "").strip():
            return {"ok": False, "detail": "invite agent_id mismatch"}
        if public_key != str(payload.get("public_key", "") or "").strip():
            return {"ok": False, "detail": "invite public key mismatch"}
        if public_key_algo != str(payload.get("public_key_algo", "") or "").strip():
            return {"ok": False, "detail": "invite public key algo mismatch"}
        expected_trust_fingerprint = trust_fingerprint_for_identity_material(
            agent_id=peer_id,
            identity_dh_pub_key=str(payload.get("identity_dh_pub_key", "") or ""),
            dh_algo=str(payload.get("dh_algo", "X25519") or "X25519"),
            public_key=public_key,
            public_key_algo=public_key_algo,
            protocol_version=protocol_version,
        )
        if expected_trust_fingerprint != str(payload.get("trust_fingerprint", "") or "").strip().lower():
            return {"ok": False, "detail": "invite trust fingerprint mismatch"}
    else:
        if not str(payload.get("prekey_lookup_handle", "") or "").strip():
            return {"ok": False, "detail": "invite prekey lookup handle required"}
        expected_trust_fingerprint = str(payload.get("identity_commitment", "") or "").strip().lower()
        if not expected_trust_fingerprint:
            return {"ok": False, "detail": "invite identity commitment required"}
        if invite_version >= DM_INVITE_VERSION:
            root_distribution = _verify_dm_invite_root_distribution(payload)
            if not root_distribution.get("ok"):
                return root_distribution
            attestations = list(payload.get("attestations") or [])
            has_stable_attestation = any(
                isinstance(item, dict)
                and str(item.get("type", "") or "").strip().lower() == "stable_dm_identity"
                for item in attestations
            )
            if not has_stable_attestation:
                return {"ok": False, "detail": "invite stable identity attestation required"}

    signed_payload = build_signature_payload(
        event_type=DM_INVITE_EVENT_TYPE,
        node_id=peer_id,
        sequence=sequence,
        payload=payload,
    )
    if not verify_signature(
        public_key_b64=public_key,
        public_key_algo=public_key_algo,
        signature_hex=signature,
        payload=signed_payload,
    ):
        return {"ok": False, "detail": "invite signature invalid"}

    return {
        "ok": True,
        "peer_id": peer_id,
        "trust_fingerprint": expected_trust_fingerprint,
        "invite": envelope,
        "payload": payload,
        "root_manifest_fingerprint": str(root_distribution.get("root_manifest_fingerprint", "") or "").strip().lower()
        if invite_version >= DM_INVITE_VERSION
        else "",
    }


def import_wormhole_dm_invite(invite: dict[str, Any], *, alias: str = "") -> dict[str, Any]:
    verified = verify_wormhole_dm_invite(invite)
    if not verified.get("ok"):
        return verified

    envelope = dict(verified.get("invite") or invite or {})
    payload = dict(verified.get("payload") or {})
    resolved_alias = str(alias or "").strip() or str(payload.get("label", "") or "").strip()
    invite_version = _safe_int(payload.get("invite_version", 0) or 0, 0)

    from services.mesh.mesh_wormhole_contacts import (
        list_wormhole_dm_contacts,
        observe_remote_prekey_identity,
        pin_wormhole_dm_invite,
    )
    legacy_or_compat_detail = "legacy invite imported as tofu_pinned; SAS verification required before first contact"
    from services.mesh.mesh_compatibility import compat_dm_invite_import_override_active

    allow_compat_import = bool(compat_dm_invite_import_override_active())

    if invite_version == DM_INVITE_VERSION_LEGACY:
        if not allow_compat_import:
            return {
                "ok": False,
                "detail": "legacy dm invite import disabled; ask the sender to re-export a current signed invite",
            }
        contact = pin_wormhole_dm_invite(
            str(verified.get("peer_id", "") or ""),
            invite_payload=payload,
            alias=resolved_alias,
            attested=False,
        )
        return {
            "ok": True,
            "peer_id": str(verified.get("peer_id", "") or ""),
            "trust_fingerprint": str(verified.get("trust_fingerprint", "") or ""),
            "trust_level": str(contact.get("trust_level", "") or ""),
            "detail": legacy_or_compat_detail,
            "invite_attested": False,
            "contact": contact,
        }

    lookup_handle = str(payload.get("prekey_lookup_handle", "") or "").strip()
    if not lookup_handle:
        return {"ok": False, "detail": "invite prekey lookup handle required"}
    if invite_version == DM_INVITE_VERSION_COMPAT and not allow_compat_import:
        return {
            "ok": False,
            "detail": "compat dm invite import disabled; ask the sender to re-export a current signed invite",
        }

    from services.mesh.mesh_wormhole_prekey import fetch_dm_prekey_bundle

    fetched = fetch_dm_prekey_bundle(lookup_token=lookup_handle)
    if not fetched.get("ok"):
        return {"ok": False, "detail": str(fetched.get("detail", "") or "invite prekey bundle not found")}

    resolved_peer_id = str(fetched.get("agent_id", "") or "").strip()
    if not resolved_peer_id:
        return {"ok": False, "detail": "invite prekey bundle missing agent_id"}

    observed_commitment = invite_identity_commitment_for_identity_material(
        identity_dh_pub_key=str(fetched.get("identity_dh_pub_key", "") or ""),
        dh_algo=str(fetched.get("dh_algo", "X25519") or "X25519"),
        public_key=str(fetched.get("public_key", "") or ""),
        public_key_algo=str(fetched.get("public_key_algo", "Ed25519") or "Ed25519"),
        protocol_version=str(fetched.get("protocol_version", PROTOCOL_VERSION) or PROTOCOL_VERSION),
    )
    if observed_commitment != str(payload.get("identity_commitment", "") or "").strip().lower():
        return {"ok": False, "detail": "invite identity commitment mismatch"}
    root_attested: dict[str, Any] = {}
    if invite_version >= DM_INVITE_VERSION:
        invite_root_distribution = _verify_dm_invite_root_distribution(payload)
        if not invite_root_distribution.get("ok"):
            return invite_root_distribution
        from services.mesh.mesh_wormhole_prekey import verify_bundle_root_attestation

        root_attested = verify_bundle_root_attestation(
            {
                "agent_id": resolved_peer_id,
                "bundle": dict(fetched.get("bundle") or {}),
                "public_key": str(fetched.get("public_key", "") or ""),
                "public_key_algo": str(fetched.get("public_key_algo", "Ed25519") or "Ed25519"),
                "protocol_version": str(fetched.get("protocol_version", PROTOCOL_VERSION) or PROTOCOL_VERSION),
            }
        )
        if not root_attested.get("ok"):
            return root_attested
        if str(root_attested.get("root_manifest_fingerprint", "") or "").strip().lower() != str(
            invite_root_distribution.get("root_manifest_fingerprint", "") or ""
        ).strip().lower():
            return {"ok": False, "detail": "invite root manifest mismatch"}
        if str(root_attested.get("root_transparency_binding_fingerprint", "") or "").strip().lower() != str(
            invite_root_distribution.get("root_transparency_binding_fingerprint", "") or ""
        ).strip().lower():
            return {"ok": False, "detail": "invite root transparency mismatch"}
        attested = _verify_dm_invite_identity_attestation(
            envelope=envelope,
            payload=payload,
            resolved_root_node_id=str(root_attested.get("root_node_id", "") or ""),
            resolved_root_public_key=str(root_attested.get("root_public_key", "") or ""),
            resolved_root_public_key_algo=str(root_attested.get("root_public_key_algo", "Ed25519") or "Ed25519"),
            resolved_root_manifest_fingerprint=str(
                invite_root_distribution.get("root_manifest_fingerprint", "") or ""
            ).strip().lower(),
        )
        if not attested.get("ok"):
            return attested

    trust_fingerprint = trust_fingerprint_for_identity_material(
        agent_id=resolved_peer_id,
        identity_dh_pub_key=str(fetched.get("identity_dh_pub_key", "") or ""),
        dh_algo=str(fetched.get("dh_algo", "X25519") or "X25519"),
        public_key=str(fetched.get("public_key", "") or ""),
        public_key_algo=str(fetched.get("public_key_algo", "Ed25519") or "Ed25519"),
        protocol_version=str(fetched.get("protocol_version", PROTOCOL_VERSION) or PROTOCOL_VERSION),
    )
    incoming_root_fingerprint = str(root_attested.get("root_fingerprint", "") or "").strip().lower()
    current_contact = list_wormhole_dm_contacts().get(resolved_peer_id) if invite_version >= DM_INVITE_VERSION else None
    current_root_fingerprint = (
        str(
            (current_contact or {}).get("invitePinnedRootFingerprint")
            or (current_contact or {}).get("remotePrekeyRootFingerprint")
            or ""
        )
        .strip()
        .lower()
    )
    if current_root_fingerprint and incoming_root_fingerprint and current_root_fingerprint != incoming_root_fingerprint:
        observed = observe_remote_prekey_identity(
            resolved_peer_id,
            fingerprint=trust_fingerprint,
            sequence=int(fetched.get("sequence", 0) or 0),
            signed_at=int(fetched.get("signed_at", 0) or 0),
            root_fingerprint=incoming_root_fingerprint,
            root_manifest_fingerprint=str(root_attested.get("root_manifest_fingerprint", "") or ""),
            root_witness_policy_fingerprint=str(root_attested.get("root_witness_policy_fingerprint", "") or ""),
            root_witness_threshold=_safe_int(root_attested.get("root_witness_threshold", 0) or 0, 0),
            root_witness_count=_safe_int(root_attested.get("root_witness_count", 0) or 0, 0),
            root_witness_domain_count=_safe_int(root_attested.get("root_witness_domain_count", 0) or 0, 0),
            root_manifest_generation=_safe_int(root_attested.get("root_manifest_generation", 0) or 0, 0),
            root_rotation_proven=bool(root_attested.get("root_rotation_proven")),
            root_node_id=str(root_attested.get("root_node_id", "") or ""),
            root_public_key=str(root_attested.get("root_public_key", "") or ""),
            root_public_key_algo=str(root_attested.get("root_public_key_algo", "Ed25519") or "Ed25519"),
        )
        return {
            "ok": False,
            "peer_id": resolved_peer_id,
            "trust_fingerprint": trust_fingerprint,
            "trust_level": str(observed.get("trust_level", "") or ""),
            "detail": (
                "signed invite root continuity mismatch; re-verify SAS or replace the signed invite "
                "before trusting this root change"
            ),
            "invite_attested": True,
            "contact": observed.get("contact"),
        }
    contact = pin_wormhole_dm_invite(
        resolved_peer_id,
        invite_payload={
            "trust_fingerprint": trust_fingerprint,
            "public_key": str(fetched.get("public_key", "") or ""),
            "public_key_algo": str(fetched.get("public_key_algo", "Ed25519") or "Ed25519"),
            "identity_dh_pub_key": str(fetched.get("identity_dh_pub_key", "") or ""),
            "dh_algo": str(fetched.get("dh_algo", "X25519") or "X25519"),
            "prekey_lookup_handle": lookup_handle,
            "issued_at": int(payload.get("issued_at", 0) or 0),
            "expires_at": int(payload.get("expires_at", 0) or 0),
            "label": str(payload.get("label", "") or ""),
            "root_node_id": str(root_attested.get("root_node_id", "") or ""),
            "root_public_key": str(root_attested.get("root_public_key", "") or ""),
            "root_public_key_algo": str(root_attested.get("root_public_key_algo", "Ed25519") or "Ed25519"),
            "root_fingerprint": str(root_attested.get("root_fingerprint", "") or ""),
            "root_manifest_fingerprint": str(root_attested.get("root_manifest_fingerprint", "") or ""),
            "root_witness_policy_fingerprint": str(
                root_attested.get("root_witness_policy_fingerprint", "") or ""
            ),
            "root_witness_threshold": _safe_int(root_attested.get("root_witness_threshold", 0) or 0, 0),
            "root_witness_count": _safe_int(root_attested.get("root_witness_count", 0) or 0, 0),
            "root_witness_domain_count": _safe_int(root_attested.get("root_witness_domain_count", 0) or 0, 0),
            "root_manifest_generation": _safe_int(root_attested.get("root_manifest_generation", 0) or 0, 0),
            "root_rotation_proven": bool(root_attested.get("root_rotation_proven")),
        },
        alias=resolved_alias,
        attested=invite_version >= DM_INVITE_VERSION,
    )
    invite_attested = invite_version >= DM_INVITE_VERSION
    return {
        "ok": True,
        "peer_id": resolved_peer_id,
        "invite_peer_id": str(verified.get("peer_id", "") or ""),
        "trust_fingerprint": trust_fingerprint,
        "trust_level": str(contact.get("trust_level", "") or ""),
        "detail": "" if invite_attested else legacy_or_compat_detail,
        "invite_attested": invite_attested,
        "contact": contact,
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
