from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Any

from services.mesh.mesh_local_custody import (
    read_sensitive_domain_json as _read_sensitive_domain_json,
    write_sensitive_domain_json as _write_sensitive_domain_json,
)

MIGRATION_DOMAIN = "gate_legacy_migration"
MIGRATION_FILENAME = "gate_legacy_wrappers.json"
MIGRATION_CUSTODY_SCOPE = "gate_legacy_migration"
WRAPPER_EVENT_TYPE = "gate_archival_rewrap"
WRAPPER_KIND = "local_archival_rewrap"
_LOCK = threading.RLock()
_DEFAULT_SCAN_LIMIT = 500


def read_sensitive_domain_json(_domain: str, _filename: str, default_factory):
    return _read_sensitive_domain_json(
        MIGRATION_DOMAIN,
        MIGRATION_FILENAME,
        default_factory,
        custody_scope=MIGRATION_CUSTODY_SCOPE,
    )


def write_sensitive_domain_json(_domain: str, _filename: str, payload: dict[str, Any]):
    _write_sensitive_domain_json(
        MIGRATION_DOMAIN,
        MIGRATION_FILENAME,
        payload,
        custody_scope=MIGRATION_CUSTODY_SCOPE,
    )


def _now() -> float:
    return float(time.time())


def _default_state() -> dict[str, Any]:
    return {"version": 1, "updated_at": 0, "wrappers": []}


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _signature_hash(signature: str) -> str:
    signature_value = str(signature or "").strip()
    if not signature_value:
        return ""
    return hashlib.sha256(signature_value.encode("utf-8")).hexdigest()


def _wrapper_event_id(gate_id: str, payload: dict[str, Any], signer_node_id: str) -> str:
    material = {
        "gate_id": str(gate_id or "").strip().lower(),
        "event_type": WRAPPER_EVENT_TYPE,
        "payload": dict(payload or {}),
        "signer_node_id": str(signer_node_id or ""),
    }
    return hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def build_local_archival_rewrap_payload(
    *,
    gate_id: str,
    original_event: dict[str, Any],
    archival_envelope: str = "",
    reason: str = "",
) -> dict[str, Any]:
    gate_key = str(gate_id or "").strip().lower()
    if not gate_key:
        raise ValueError("gate_id required")
    original = dict(original_event or {})
    original_payload = dict(original.get("payload") or {})
    original_event_id = str(original.get("event_id", "") or "").strip()
    if not original_event_id:
        raise ValueError("original event_id required")
    archival_envelope_value = str(archival_envelope or "").strip()
    original_author = str(original.get("node_id", "") or "").strip()
    return {
        "wrapper_kind": WRAPPER_KIND,
        "gate_id": gate_key,
        "original_event_id": original_event_id,
        "original_event_type": str(original.get("event_type", "") or ""),
        "original_event_hash": _canonical_hash(original),
        "original_author_node_id": original_author,
        "original_signature_hash": _signature_hash(str(original.get("signature", "") or "")),
        "original_payload_format": str(original_payload.get("format", "") or ""),
        "archival_envelope_hash": (
            hashlib.sha256(archival_envelope_value.encode("ascii")).hexdigest()
            if archival_envelope_value
            else ""
        ),
        "migration_semantics": "local archival rewrap of immutable historical event",
        "authorship_semantics": "wrapper signer attests local archival metadata only; original authorship is unchanged",
        "reason": str(reason or "")[:200],
    }


def _load_state() -> dict[str, Any]:
    raw = read_sensitive_domain_json(MIGRATION_DOMAIN, MIGRATION_FILENAME, _default_state)
    state = _default_state()
    if isinstance(raw, dict):
        state.update(raw)
    wrappers = []
    for wrapper in list(state.get("wrappers") or []):
        if isinstance(wrapper, dict):
            wrappers.append(dict(wrapper))
    state["wrappers"] = wrappers
    return state


def _write_state(state: dict[str, Any]) -> None:
    write_sensitive_domain_json(
        MIGRATION_DOMAIN,
        MIGRATION_FILENAME,
        {
            "version": 1,
            "updated_at": int(_now()),
            "wrappers": list(state.get("wrappers") or []),
        },
    )


def create_local_archival_rewrap(
    *,
    gate_id: str,
    event_id: str,
    archival_envelope: str = "",
    reason: str = "",
) -> dict[str, Any]:
    gate_key = str(gate_id or "").strip().lower()
    target_event_id = str(event_id or "").strip()
    if not gate_key or not target_event_id:
        return {"ok": False, "detail": "gate_id and event_id are required"}
    try:
        from services.mesh.mesh_hashchain import gate_store

        original = gate_store.get_event(target_event_id)
    except Exception:
        original = None
    if not isinstance(original, dict):
        return {"ok": False, "detail": "original gate event not found"}
    try:
        payload = build_local_archival_rewrap_payload(
            gate_id=gate_key,
            original_event=dict(original),
            archival_envelope=archival_envelope,
            reason=reason,
        )
    except (UnicodeEncodeError, ValueError) as exc:
        return {"ok": False, "detail": str(exc)}
    try:
        from services.mesh.mesh_wormhole_persona import sign_gate_wormhole_event

        signed = sign_gate_wormhole_event(
            gate_id=gate_key,
            event_type=WRAPPER_EVENT_TYPE,
            payload=payload,
        )
    except Exception as exc:
        return {"ok": False, "detail": str(exc) or type(exc).__name__}
    if not signed.get("signature"):
        return {"ok": False, "detail": str(signed.get("detail") or "gate_archival_rewrap_sign_failed")}
    signer_node_id = str(signed.get("node_id", "") or "")
    wrapper = {
        "ok": True,
        "event_type": WRAPPER_EVENT_TYPE,
        "event_id": _wrapper_event_id(gate_key, payload, signer_node_id),
        "gate_id": gate_key,
        "node_id": signer_node_id,
        "identity_scope": str(signed.get("identity_scope", "") or ""),
        "payload": payload,
        "timestamp": _now(),
        "sequence": int(signed.get("sequence", 0) or 0),
        "signature": str(signed.get("signature", "") or ""),
        "public_key": str(signed.get("public_key", "") or ""),
        "public_key_algo": str(signed.get("public_key_algo", "") or ""),
        "protocol_version": str(signed.get("protocol_version", "") or ""),
    }
    with _LOCK:
        state = _load_state()
        state["wrappers"] = [
            item
            for item in list(state.get("wrappers") or [])
            if not (
                str(item.get("gate_id", "") or "") == gate_key
                and str((item.get("payload") or {}).get("original_event_id", "") or "") == target_event_id
            )
        ]
        state["wrappers"].append(wrapper)
        _write_state(state)
    return dict(wrapper)


def legacy_gate_event_candidate_reason(event: dict[str, Any]) -> str:
    original = dict(event or {})
    if str(original.get("event_type", "") or "") != "gate_message":
        return ""
    event_id = str(original.get("event_id", "") or "").strip()
    if not event_id:
        return ""
    payload = original.get("payload") if isinstance(original.get("payload"), dict) else {}
    if not isinstance(payload, dict):
        return "legacy_missing_payload"
    payload_format = str(payload.get("format", "") or "").strip().lower()
    if payload_format and payload_format != "mls1":
        return "legacy_gate_payload_format"
    gate_envelope = str(payload.get("gate_envelope", "") or "").strip()
    envelope_hash = str(payload.get("envelope_hash", "") or "").strip()
    if gate_envelope and not envelope_hash:
        return "legacy_unbound_gate_envelope"
    if not str(payload.get("transport_lock", "") or "").strip():
        return "legacy_missing_transport_lock"
    protocol_version = str(original.get("protocol_version", "") or "").strip()
    if not protocol_version:
        return "legacy_missing_protocol_version"
    return ""


def _existing_wrapper_event_ids(gate_id: str) -> set[str]:
    refs: set[str] = set()
    for wrapper in list_local_archival_rewraps(gate_id=gate_id):
        payload = wrapper.get("payload") if isinstance(wrapper.get("payload"), dict) else {}
        event_id = str(payload.get("original_event_id", "") or "").strip()
        if event_id:
            refs.add(event_id)
    return refs


def create_missing_local_archival_rewraps(
    *,
    gate_id: str,
    limit: int = _DEFAULT_SCAN_LIMIT,
) -> dict[str, Any]:
    gate_key = str(gate_id or "").strip().lower()
    if not gate_key:
        return {
            "ok": False,
            "detail": "gate_id required",
            "gate_id": "",
            "scanned": 0,
            "created": 0,
            "skipped": 0,
            "failed": 0,
            "wrappers": [],
            "failures": [],
        }
    scan_limit = max(1, int(limit or _DEFAULT_SCAN_LIMIT))
    try:
        from services.mesh.mesh_hashchain import gate_store

        messages = gate_store.get_messages(gate_key, limit=scan_limit)
    except Exception as exc:
        return {
            "ok": False,
            "detail": str(exc) or type(exc).__name__,
            "gate_id": gate_key,
            "scanned": 0,
            "created": 0,
            "skipped": 0,
            "failed": 0,
            "wrappers": [],
            "failures": [],
        }

    existing = _existing_wrapper_event_ids(gate_key)
    created: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    scanned = 0
    skipped = 0
    for event in list(messages or []):
        if not isinstance(event, dict):
            continue
        scanned += 1
        event_id = str(event.get("event_id", "") or "").strip()
        reason = legacy_gate_event_candidate_reason(event)
        if not event_id or not reason or event_id in existing:
            skipped += 1
            continue
        result = create_local_archival_rewrap(
            gate_id=gate_key,
            event_id=event_id,
            archival_envelope=str((event.get("payload") or {}).get("gate_envelope", "") or "")
            if isinstance(event.get("payload"), dict)
            else "",
            reason=reason,
        )
        if result.get("ok"):
            created.append(dict(result))
            existing.add(event_id)
        else:
            failures.append(
                {
                    "event_id": event_id,
                    "reason": reason,
                    "detail": str(result.get("detail", "") or "legacy_archival_rewrap_failed"),
                }
            )
    return {
        "ok": not failures,
        "detail": "ok" if not failures else "one or more legacy archival wrappers failed",
        "gate_id": gate_key,
        "scanned": scanned,
        "created": len(created),
        "skipped": skipped,
        "failed": len(failures),
        "wrappers": created,
        "failures": failures,
    }


def list_local_archival_rewraps(*, gate_id: str = "") -> list[dict[str, Any]]:
    gate_key = str(gate_id or "").strip().lower()
    with _LOCK:
        wrappers = [dict(item) for item in list(_load_state().get("wrappers") or [])]
    if gate_key:
        wrappers = [item for item in wrappers if str(item.get("gate_id", "") or "") == gate_key]
    return sorted(wrappers, key=lambda item: float(item.get("timestamp", 0.0) or 0.0), reverse=True)


def reset_gate_legacy_migration_for_tests() -> None:
    with _LOCK:
        _write_state(_default_state())
