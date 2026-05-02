"""Append-only transparency records for stable DM root distribution.

Sprint 11 adds a root-signed transparency/export record that binds the current
stable DM root manifest together with the concrete witness receipt set into a
verifiable append-only publication object. This does not create independent
third-party witnesses by itself, but it gives invite/bootstrap flows a distinct
export record that can later be published to external transparency services.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any
import urllib.error
import urllib.request

from services.mesh.mesh_crypto import build_signature_payload, verify_node_binding, verify_signature
from services.mesh.mesh_protocol import PROTOCOL_VERSION
from services.mesh.mesh_secure_storage import read_domain_json, write_domain_json
from services.mesh.mesh_wormhole_persona import sign_root_wormhole_event

BACKEND_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BACKEND_DIR / "data"
ROOT_TRANSPARENCY_DOMAIN = "root_transparency"
ROOT_TRANSPARENCY_FILE = "wormhole_root_transparency.json"
STABLE_DM_ROOT_TRANSPARENCY_EVENT_TYPE = "stable_dm_root_manifest_transparency"
STABLE_DM_ROOT_TRANSPARENCY_TYPE = "stable_dm_root_manifest_transparency"
STABLE_DM_ROOT_TRANSPARENCY_LEDGER_TYPE = "stable_dm_root_manifest_transparency_ledger"
ROOT_TRANSPARENCY_SCOPE = "local_append_only"
DEFAULT_ROOT_TRANSPARENCY_MAX_RECORDS = 64
DEFAULT_ROOT_TRANSPARENCY_LEDGER_MAX_AGE_S = 3600


def _safe_int(val: Any, default: int = 0) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _resolve_transparency_ledger_path(raw_path: str) -> Path | None:
    raw = str(raw_path or "").strip()
    if not raw:
        return None
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate
    return BACKEND_DIR / candidate


def _root_transparency_ledger_max_age_s() -> int:
    from services.config import get_settings

    return max(
        0,
        _safe_int(
            getattr(
                get_settings(),
                "MESH_DM_ROOT_TRANSPARENCY_LEDGER_MAX_AGE_S",
                DEFAULT_ROOT_TRANSPARENCY_LEDGER_MAX_AGE_S,
            )
            or DEFAULT_ROOT_TRANSPARENCY_LEDGER_MAX_AGE_S,
            DEFAULT_ROOT_TRANSPARENCY_LEDGER_MAX_AGE_S,
        ),
    )


def _root_transparency_ledger_age_s(exported_at: int, *, now: int | None = None) -> int:
    if exported_at <= 0:
        return 0
    current_time = _safe_int(now or time.time(), int(time.time()))
    return max(0, current_time - exported_at)


def _root_transparency_ledger_stale(exported_at: int, *, now: int | None = None) -> bool:
    max_age_s = _root_transparency_ledger_max_age_s()
    if max_age_s <= 0:
        return False
    if exported_at <= 0:
        return True
    return _root_transparency_ledger_age_s(exported_at, now=now) > max_age_s


def _record_ledger_export_status(
    state: dict[str, Any],
    *,
    ok: bool,
    detail: str,
    path: str = "",
    exported_at: int | None = None,
    record_fingerprint: str = "",
    chain_fingerprint: str = "",
) -> None:
    state["ledger_exported_at"] = _safe_int(exported_at or time.time(), int(time.time()))
    state["ledger_export_ok"] = bool(ok)
    state["ledger_export_detail"] = str(detail or "").strip()
    state["ledger_export_path"] = str(path or "").strip()
    state["ledger_export_record_fingerprint"] = str(record_fingerprint or "").strip().lower()
    state["ledger_export_chain_fingerprint"] = str(chain_fingerprint or "").strip().lower()


def _default_state() -> dict[str, Any]:
    return {
        "updated_at": 0,
        "current_record": {},
        "current_record_fingerprint": "",
        "ledger_exported_at": 0,
        "ledger_export_ok": False,
        "ledger_export_detail": "",
        "ledger_export_path": "",
        "ledger_export_record_fingerprint": "",
        "ledger_export_chain_fingerprint": "",
        "ledger_readback_checked_at": 0,
        "ledger_readback_exported_at": 0,
        "ledger_readback_ok": False,
        "ledger_readback_detail": "",
        "ledger_readback_source_ref": "",
        "ledger_readback_record_visible": False,
        "ledger_readback_binding_matches": False,
        "records": [],
    }


def read_root_transparency_state() -> dict[str, Any]:
    raw = read_domain_json(
        ROOT_TRANSPARENCY_DOMAIN,
        ROOT_TRANSPARENCY_FILE,
        _default_state,
        base_dir=DATA_DIR,
    )
    state = {**_default_state(), **dict(raw or {})}
    state["current_record"] = dict(state.get("current_record") or {})
    state["current_record_fingerprint"] = str(state.get("current_record_fingerprint", "") or "").strip().lower()
    state["ledger_exported_at"] = _safe_int(state.get("ledger_exported_at", 0) or 0, 0)
    state["ledger_export_ok"] = bool(state.get("ledger_export_ok", False))
    state["ledger_export_detail"] = str(state.get("ledger_export_detail", "") or "").strip()
    state["ledger_export_path"] = str(state.get("ledger_export_path", "") or "").strip()
    state["ledger_export_record_fingerprint"] = str(
        state.get("ledger_export_record_fingerprint", "") or ""
    ).strip().lower()
    state["ledger_export_chain_fingerprint"] = str(
        state.get("ledger_export_chain_fingerprint", "") or ""
    ).strip().lower()
    state["ledger_readback_checked_at"] = _safe_int(state.get("ledger_readback_checked_at", 0) or 0, 0)
    state["ledger_readback_exported_at"] = _safe_int(state.get("ledger_readback_exported_at", 0) or 0, 0)
    state["ledger_readback_ok"] = bool(state.get("ledger_readback_ok", False))
    state["ledger_readback_detail"] = str(state.get("ledger_readback_detail", "") or "").strip()
    state["ledger_readback_source_ref"] = str(state.get("ledger_readback_source_ref", "") or "").strip()
    state["ledger_readback_record_visible"] = bool(state.get("ledger_readback_record_visible", False))
    state["ledger_readback_binding_matches"] = bool(state.get("ledger_readback_binding_matches", False))
    state["records"] = [dict(item or {}) for item in list(state.get("records") or []) if isinstance(item, dict)]
    return state


def _write_root_transparency_state(state: dict[str, Any]) -> dict[str, Any]:
    records = [dict(item or {}) for item in list((state or {}).get("records") or []) if isinstance(item, dict)]
    payload = {
        **_default_state(),
        **dict(state or {}),
        "updated_at": int(time.time()),
        "current_record": dict((state or {}).get("current_record") or {}),
        "current_record_fingerprint": str((state or {}).get("current_record_fingerprint", "") or "").strip().lower(),
        "ledger_exported_at": _safe_int((state or {}).get("ledger_exported_at", 0) or 0, 0),
        "ledger_export_ok": bool((state or {}).get("ledger_export_ok", False)),
        "ledger_export_detail": str((state or {}).get("ledger_export_detail", "") or "").strip(),
        "ledger_export_path": str((state or {}).get("ledger_export_path", "") or "").strip(),
        "ledger_export_record_fingerprint": str(
            (state or {}).get("ledger_export_record_fingerprint", "") or ""
        ).strip().lower(),
        "ledger_export_chain_fingerprint": str(
            (state or {}).get("ledger_export_chain_fingerprint", "") or ""
        ).strip().lower(),
        "ledger_readback_checked_at": _safe_int((state or {}).get("ledger_readback_checked_at", 0) or 0, 0),
        "ledger_readback_exported_at": _safe_int((state or {}).get("ledger_readback_exported_at", 0) or 0, 0),
        "ledger_readback_ok": bool((state or {}).get("ledger_readback_ok", False)),
        "ledger_readback_detail": str((state or {}).get("ledger_readback_detail", "") or "").strip(),
        "ledger_readback_source_ref": str((state or {}).get("ledger_readback_source_ref", "") or "").strip(),
        "ledger_readback_record_visible": bool((state or {}).get("ledger_readback_record_visible", False)),
        "ledger_readback_binding_matches": bool((state or {}).get("ledger_readback_binding_matches", False)),
        "records": records[-DEFAULT_ROOT_TRANSPARENCY_MAX_RECORDS:],
    }
    write_domain_json(
        ROOT_TRANSPARENCY_DOMAIN,
        ROOT_TRANSPARENCY_FILE,
        payload,
        base_dir=DATA_DIR,
    )
    return payload


def witness_receipt_fingerprint(witness: dict[str, Any]) -> str:
    envelope = dict(witness or {})
    canonical = {
        "type": str(envelope.get("type", "") or "").strip(),
        "event_type": str(envelope.get("event_type", "") or "").strip(),
        "node_id": str(envelope.get("node_id", "") or "").strip(),
        "public_key": str(envelope.get("public_key", "") or "").strip(),
        "public_key_algo": str(envelope.get("public_key_algo", "Ed25519") or "Ed25519").strip(),
        "protocol_version": str(envelope.get("protocol_version", PROTOCOL_VERSION) or PROTOCOL_VERSION).strip(),
        "sequence": _safe_int(envelope.get("sequence", 0) or 0, 0),
        "payload": dict(envelope.get("payload") or {}),
        "signature": str(envelope.get("signature", "") or "").strip(),
    }
    return hashlib.sha256(_stable_json(canonical).encode("utf-8")).hexdigest()


def witness_receipt_set_fingerprint(witnesses: list[dict[str, Any]] | None) -> str:
    fingerprints = sorted(
        witness_receipt_fingerprint(dict(item or {}))
        for item in list(witnesses or [])
        if isinstance(item, dict)
    )
    return hashlib.sha256(_stable_json(fingerprints).encode("utf-8")).hexdigest()


def transparency_binding_fingerprint(
    *,
    manifest_fingerprint: str,
    witness_policy_fingerprint: str,
    witness_set_fingerprint: str,
) -> str:
    payload = {
        "manifest_fingerprint": str(manifest_fingerprint or "").strip().lower(),
        "witness_policy_fingerprint": str(witness_policy_fingerprint or "").strip().lower(),
        "witness_set_fingerprint": str(witness_set_fingerprint or "").strip().lower(),
    }
    return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()


def transparency_record_fingerprint(record: dict[str, Any]) -> str:
    envelope = dict(record or {})
    canonical = {
        "type": str(envelope.get("type", STABLE_DM_ROOT_TRANSPARENCY_TYPE) or STABLE_DM_ROOT_TRANSPARENCY_TYPE),
        "event_type": str(
            envelope.get("event_type", STABLE_DM_ROOT_TRANSPARENCY_EVENT_TYPE)
            or STABLE_DM_ROOT_TRANSPARENCY_EVENT_TYPE
        ),
        "node_id": str(envelope.get("node_id", "") or "").strip(),
        "public_key": str(envelope.get("public_key", "") or "").strip(),
        "public_key_algo": str(envelope.get("public_key_algo", "Ed25519") or "Ed25519").strip(),
        "protocol_version": str(envelope.get("protocol_version", PROTOCOL_VERSION) or PROTOCOL_VERSION).strip(),
        "sequence": _safe_int(envelope.get("sequence", 0) or 0, 0),
        "payload": dict(envelope.get("payload") or {}),
        "signature": str(envelope.get("signature", "") or "").strip(),
    }
    return hashlib.sha256(_stable_json(canonical).encode("utf-8")).hexdigest()


def transparency_record_chain_fingerprint(records: list[dict[str, Any]] | None) -> str:
    fingerprints = [
        transparency_record_fingerprint(dict(item or {}))
        for item in list(records or [])
        if isinstance(item, dict)
    ]
    return hashlib.sha256(_stable_json(fingerprints).encode("utf-8")).hexdigest()


def _record_payload(
    *,
    manifest_verified: dict[str, Any],
    witness_verified: dict[str, Any],
    previous_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    previous_fingerprint = (
        transparency_record_fingerprint(previous_record) if previous_record else ""
    )
    previous_index = _safe_int(dict((previous_record or {}).get("payload") or {}).get("record_index", 0) or 0, 0)
    manifest_fingerprint = str(manifest_verified.get("manifest_fingerprint", "") or "").strip().lower()
    witness_policy_fingerprint = str(
        manifest_verified.get("witness_policy_fingerprint", "") or ""
    ).strip().lower()
    witness_set_fingerprint = witness_receipt_set_fingerprint(
        list(witness_verified.get("validated_witnesses") or [])
    )
    return {
        "transparency_scope": ROOT_TRANSPARENCY_SCOPE,
        "manifest_fingerprint": manifest_fingerprint,
        "root_fingerprint": str(manifest_verified.get("root_fingerprint", "") or "").strip().lower(),
        "generation": _safe_int(manifest_verified.get("generation", 0) or 0, 0),
        "witness_policy_fingerprint": witness_policy_fingerprint,
        "witness_threshold": _safe_int(witness_verified.get("witness_threshold", 0) or 0, 0),
        "witness_count": _safe_int(witness_verified.get("witness_count", 0) or 0, 0),
        "witness_set_fingerprint": witness_set_fingerprint,
        "binding_fingerprint": transparency_binding_fingerprint(
            manifest_fingerprint=manifest_fingerprint,
            witness_policy_fingerprint=witness_policy_fingerprint,
            witness_set_fingerprint=witness_set_fingerprint,
        ),
        "record_index": previous_index + 1 if previous_index > 0 else 1,
        "previous_record_fingerprint": previous_fingerprint,
        "published_at": int(time.time()),
    }


def _record_ledger_readback_status(
    state: dict[str, Any],
    *,
    ok: bool,
    detail: str,
    source_ref: str = "",
    checked_at: int | None = None,
    exported_at: int = 0,
    record_visible: bool = False,
    binding_matches: bool = False,
) -> None:
    state["ledger_readback_checked_at"] = _safe_int(checked_at or time.time(), int(time.time()))
    state["ledger_readback_exported_at"] = _safe_int(exported_at or 0, 0)
    state["ledger_readback_ok"] = bool(ok)
    state["ledger_readback_detail"] = str(detail or "").strip()
    state["ledger_readback_source_ref"] = str(source_ref or "").strip()
    state["ledger_readback_record_visible"] = bool(record_visible)
    state["ledger_readback_binding_matches"] = bool(binding_matches)


def _transparency_operator_status(state: dict[str, Any]) -> dict[str, Any]:
    source_ref = _configured_root_transparency_readback_source_ref()
    source_configured = bool(source_ref)
    now = int(time.time())
    export_at = _safe_int(state.get("ledger_exported_at", 0) or 0, 0)
    readback_at = _safe_int(state.get("ledger_readback_checked_at", 0) or 0, 0)
    readback_exported_at = _safe_int(state.get("ledger_readback_exported_at", 0) or 0, 0)
    export_age_s = max(0, now - export_at) if export_at > 0 else 0
    readback_age_s = max(0, now - readback_at) if readback_at > 0 else 0
    readback_export_age_s = _root_transparency_ledger_age_s(readback_exported_at, now=now)
    export_ok = bool(state.get("ledger_export_ok", False))
    readback_ok = bool(state.get("ledger_readback_ok", False))
    record_visible = bool(state.get("ledger_readback_record_visible", False))
    binding_matches = bool(state.get("ledger_readback_binding_matches", False))
    readback_stale = _root_transparency_ledger_stale(readback_exported_at, now=now)
    if not source_configured:
        operator_state = "not_configured"
    elif readback_ok and record_visible and binding_matches and not readback_stale:
        operator_state = "current"
    elif export_ok or readback_at > 0:
        operator_state = "stale"
    else:
        operator_state = "error"
    return {
        "ledger_readback_configured": source_configured,
        "ledger_operator_state": operator_state,
        "ledger_export_age_s": export_age_s,
        "ledger_readback_age_s": readback_age_s,
        "ledger_readback_exported_at": readback_exported_at,
        "ledger_readback_export_age_s": readback_export_age_s,
        "ledger_freshness_window_s": _root_transparency_ledger_max_age_s(),
        "ledger_external_verification_required": bool(source_configured and (not readback_ok or readback_stale)),
    }


def verify_root_transparency_record(
    record: dict[str, Any],
    manifest: dict[str, Any],
    witnesses: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    envelope = dict(record or {})
    if str(envelope.get("type", STABLE_DM_ROOT_TRANSPARENCY_TYPE) or STABLE_DM_ROOT_TRANSPARENCY_TYPE) != STABLE_DM_ROOT_TRANSPARENCY_TYPE:
        return {"ok": False, "detail": "stable root transparency record type invalid"}
    if str(envelope.get("event_type", "") or "").strip() != STABLE_DM_ROOT_TRANSPARENCY_EVENT_TYPE:
        return {"ok": False, "detail": "stable root transparency record event_type invalid"}
    node_id = str(envelope.get("node_id", "") or "").strip()
    public_key = str(envelope.get("public_key", "") or "").strip()
    public_key_algo = str(envelope.get("public_key_algo", "Ed25519") or "Ed25519").strip()
    protocol_version = str(envelope.get("protocol_version", PROTOCOL_VERSION) or PROTOCOL_VERSION).strip()
    sequence = _safe_int(envelope.get("sequence", 0) or 0, 0)
    signature = str(envelope.get("signature", "") or "").strip()
    payload = dict(envelope.get("payload") or {})
    if not node_id or not public_key or sequence <= 0 or not signature:
        return {"ok": False, "detail": "stable root transparency record incomplete"}
    if str(payload.get("transparency_scope", ROOT_TRANSPARENCY_SCOPE) or ROOT_TRANSPARENCY_SCOPE) != ROOT_TRANSPARENCY_SCOPE:
        return {"ok": False, "detail": "stable root transparency scope invalid"}
    if _safe_int(payload.get("published_at", 0) or 0, 0) <= 0:
        return {"ok": False, "detail": "stable root transparency published_at required"}
    if _safe_int(payload.get("record_index", 0) or 0, 0) <= 0:
        return {"ok": False, "detail": "stable root transparency record_index required"}
    if not verify_node_binding(node_id, public_key):
        return {"ok": False, "detail": "stable root transparency node binding invalid"}

    from services.mesh.mesh_wormhole_root_manifest import verify_root_manifest, verify_root_manifest_witness_set

    manifest_verified = verify_root_manifest(manifest)
    if not manifest_verified.get("ok"):
        return {"ok": False, "detail": str(manifest_verified.get("detail", "") or "stable root manifest invalid")}
    witness_verified = verify_root_manifest_witness_set(manifest, witnesses)
    if not witness_verified.get("ok"):
        return {"ok": False, "detail": str(witness_verified.get("detail", "") or "stable root manifest witness invalid")}
    if node_id != str(manifest_verified.get("root_node_id", "") or "").strip():
        return {"ok": False, "detail": "stable root transparency signer mismatch"}
    if public_key != str(manifest_verified.get("root_public_key", "") or "").strip():
        return {"ok": False, "detail": "stable root transparency signer mismatch"}
    if public_key_algo != str(manifest_verified.get("root_public_key_algo", "Ed25519") or "Ed25519"):
        return {"ok": False, "detail": "stable root transparency signer mismatch"}
    if protocol_version != str((manifest or {}).get("protocol_version", PROTOCOL_VERSION) or PROTOCOL_VERSION).strip():
        return {"ok": False, "detail": "stable root transparency protocol mismatch"}

    manifest_fingerprint = str(manifest_verified.get("manifest_fingerprint", "") or "").strip().lower()
    witness_policy_fingerprint = str(
        manifest_verified.get("witness_policy_fingerprint", "") or ""
    ).strip().lower()
    witness_set_fingerprint = witness_receipt_set_fingerprint(
        list(witness_verified.get("validated_witnesses") or [])
    )
    expected_binding_fingerprint = transparency_binding_fingerprint(
        manifest_fingerprint=manifest_fingerprint,
        witness_policy_fingerprint=witness_policy_fingerprint,
        witness_set_fingerprint=witness_set_fingerprint,
    )

    if str(payload.get("manifest_fingerprint", "") or "").strip().lower() != manifest_fingerprint:
        return {"ok": False, "detail": "stable root transparency manifest mismatch"}
    if str(payload.get("root_fingerprint", "") or "").strip().lower() != str(
        manifest_verified.get("root_fingerprint", "") or ""
    ).strip().lower():
        return {"ok": False, "detail": "stable root transparency root mismatch"}
    if _safe_int(payload.get("generation", 0) or 0, 0) != _safe_int(manifest_verified.get("generation", 0) or 0, 0):
        return {"ok": False, "detail": "stable root transparency generation mismatch"}
    if str(payload.get("witness_policy_fingerprint", "") or "").strip().lower() != witness_policy_fingerprint:
        return {"ok": False, "detail": "stable root transparency witness policy mismatch"}
    if _safe_int(payload.get("witness_threshold", 0) or 0, 0) != _safe_int(
        witness_verified.get("witness_threshold", 0) or 0,
        0,
    ):
        return {"ok": False, "detail": "stable root transparency witness threshold mismatch"}
    if _safe_int(payload.get("witness_count", 0) or 0, 0) != _safe_int(
        witness_verified.get("witness_count", 0) or 0,
        0,
    ):
        return {"ok": False, "detail": "stable root transparency witness count mismatch"}
    if str(payload.get("witness_set_fingerprint", "") or "").strip().lower() != witness_set_fingerprint:
        return {"ok": False, "detail": "stable root transparency witness set mismatch"}
    if str(payload.get("binding_fingerprint", "") or "").strip().lower() != expected_binding_fingerprint:
        return {"ok": False, "detail": "stable root transparency binding mismatch"}

    signed_payload = build_signature_payload(
        event_type=STABLE_DM_ROOT_TRANSPARENCY_EVENT_TYPE,
        node_id=node_id,
        sequence=sequence,
        payload=payload,
    )
    if not verify_signature(
        public_key_b64=public_key,
        public_key_algo=public_key_algo,
        signature_hex=signature,
        payload=signed_payload,
    ):
        return {"ok": False, "detail": "stable root transparency record invalid"}
    return {
        "ok": True,
        "record_fingerprint": transparency_record_fingerprint(envelope),
        "binding_fingerprint": expected_binding_fingerprint,
        "manifest_fingerprint": manifest_fingerprint,
        "witness_policy_fingerprint": witness_policy_fingerprint,
        "witness_set_fingerprint": witness_set_fingerprint,
        "witness_threshold": _safe_int(witness_verified.get("witness_threshold", 0) or 0, 0),
        "witness_count": _safe_int(witness_verified.get("witness_count", 0) or 0, 0),
        "record_index": _safe_int(payload.get("record_index", 0) or 0, 0),
        "previous_record_fingerprint": str(payload.get("previous_record_fingerprint", "") or "").strip().lower(),
        "published_at": _safe_int(payload.get("published_at", 0) or 0, 0),
    }


def publish_root_transparency_record(*, distribution: dict[str, Any] | None = None) -> dict[str, Any]:
    from services.mesh.mesh_wormhole_root_manifest import (
        get_current_root_manifest,
        verify_root_manifest,
        verify_root_manifest_witness_set,
    )

    resolved_distribution = dict(distribution or {}) or get_current_root_manifest()
    manifest = dict(resolved_distribution.get("manifest") or {})
    witnesses = [dict(item or {}) for item in list(resolved_distribution.get("witnesses") or []) if isinstance(item, dict)]
    if not manifest or not witnesses:
        return {"ok": False, "detail": "stable root transparency distribution incomplete"}
    manifest_verified = verify_root_manifest(manifest)
    if not manifest_verified.get("ok"):
        return {"ok": False, "detail": str(manifest_verified.get("detail", "") or "stable root manifest invalid")}
    witness_verified = verify_root_manifest_witness_set(manifest, witnesses)
    if not witness_verified.get("ok"):
        return {"ok": False, "detail": str(witness_verified.get("detail", "") or "stable root manifest witness invalid")}

    state = read_root_transparency_state()
    current_record = dict(state.get("current_record") or {})
    if current_record:
        current_verified = verify_root_transparency_record(current_record, manifest, witnesses)
        if current_verified.get("ok"):
            return {
                "ok": True,
                "record": current_record,
                "record_fingerprint": str(current_verified.get("record_fingerprint", "") or "").strip().lower(),
                "binding_fingerprint": str(current_verified.get("binding_fingerprint", "") or "").strip().lower(),
                "record_index": _safe_int(current_verified.get("record_index", 0) or 0, 0),
                "previous_record_fingerprint": str(
                    current_verified.get("previous_record_fingerprint", "") or ""
                ).strip().lower(),
            }

    records = [dict(item or {}) for item in list(state.get("records") or []) if isinstance(item, dict)]
    previous_record = records[-1] if records else {}
    payload = _record_payload(
        manifest_verified=manifest_verified,
        witness_verified=witness_verified,
        previous_record=previous_record,
    )
    signed = sign_root_wormhole_event(
        event_type=STABLE_DM_ROOT_TRANSPARENCY_EVENT_TYPE,
        payload=payload,
    )
    record = {
        "type": STABLE_DM_ROOT_TRANSPARENCY_TYPE,
        "event_type": STABLE_DM_ROOT_TRANSPARENCY_EVENT_TYPE,
        "node_id": str(signed.get("node_id", "") or "").strip(),
        "public_key": str(signed.get("public_key", "") or "").strip(),
        "public_key_algo": str(signed.get("public_key_algo", "Ed25519") or "Ed25519").strip(),
        "protocol_version": str(signed.get("protocol_version", PROTOCOL_VERSION) or PROTOCOL_VERSION).strip(),
        "sequence": _safe_int(signed.get("sequence", 0) or 0, 0),
        "payload": dict(signed.get("payload") or {}),
        "signature": str(signed.get("signature", "") or "").strip(),
        "identity_scope": str(signed.get("identity_scope", "root") or "root"),
    }
    record_fingerprint = transparency_record_fingerprint(record)
    records.append(record)
    state["current_record"] = record
    state["current_record_fingerprint"] = record_fingerprint
    state["records"] = records[-DEFAULT_ROOT_TRANSPARENCY_MAX_RECORDS:]
    _write_root_transparency_state(state)
    result = {
        "ok": True,
        "record": record,
        "record_fingerprint": record_fingerprint,
        "binding_fingerprint": str(payload.get("binding_fingerprint", "") or "").strip().lower(),
        "record_index": _safe_int(payload.get("record_index", 0) or 0, 0),
        "previous_record_fingerprint": str(payload.get("previous_record_fingerprint", "") or "").strip().lower(),
    }
    export_status = _maybe_publish_root_transparency_ledger_to_configured_file()
    result.update(export_status)
    result.update(_maybe_verify_root_transparency_record_from_configured_source(record))
    result.update(_transparency_operator_status(read_root_transparency_state()))
    return result


def get_current_root_transparency_record(*, distribution: dict[str, Any] | None = None) -> dict[str, Any]:
    from services.mesh.mesh_wormhole_root_manifest import get_current_root_manifest

    resolved_distribution = dict(distribution or {}) or get_current_root_manifest()
    manifest = dict(resolved_distribution.get("manifest") or {})
    witnesses = [dict(item or {}) for item in list(resolved_distribution.get("witnesses") or []) if isinstance(item, dict)]
    state = read_root_transparency_state()
    current_record = dict(state.get("current_record") or {})
    if current_record:
        current_verified = verify_root_transparency_record(current_record, manifest, witnesses)
        if current_verified.get("ok"):
            result = {
                "ok": True,
                "record": current_record,
                "record_fingerprint": str(current_verified.get("record_fingerprint", "") or "").strip().lower(),
                "binding_fingerprint": str(current_verified.get("binding_fingerprint", "") or "").strip().lower(),
                "record_index": _safe_int(current_verified.get("record_index", 0) or 0, 0),
                "previous_record_fingerprint": str(
                    current_verified.get("previous_record_fingerprint", "") or ""
                ).strip().lower(),
            }
            result.update(_maybe_publish_root_transparency_ledger_to_configured_file())
            result.update(_maybe_verify_root_transparency_record_from_configured_source(current_record))
            result.update(_transparency_operator_status(read_root_transparency_state()))
            return result
    return publish_root_transparency_record(distribution=resolved_distribution)


def export_root_transparency_ledger(*, max_records: int | None = None) -> dict[str, Any]:
    state = read_root_transparency_state()
    records = [dict(item or {}) for item in list(state.get("records") or []) if isinstance(item, dict)]
    if max_records is not None:
        limit = max(1, _safe_int(max_records, len(records) or 1))
        records = records[-limit:]
    current_record = dict(records[-1] or {}) if records else dict(state.get("current_record") or {})
    current_record_fingerprint = (
        transparency_record_fingerprint(current_record) if current_record else ""
    )
    current_payload = dict(current_record.get("payload") or {})
    ledger = {
        "type": STABLE_DM_ROOT_TRANSPARENCY_LEDGER_TYPE,
        "schema_version": 1,
        "transparency_scope": ROOT_TRANSPARENCY_SCOPE,
        "exported_at": int(time.time()),
        "record_count": len(records),
        "current_record_fingerprint": current_record_fingerprint,
        "head_binding_fingerprint": str(current_payload.get("binding_fingerprint", "") or "").strip().lower(),
        "chain_fingerprint": transparency_record_chain_fingerprint(records),
        "records": records,
    }
    return {
        "ok": True,
        "ledger": ledger,
        "record_count": len(records),
        "current_record_fingerprint": current_record_fingerprint,
        "head_binding_fingerprint": str(ledger.get("head_binding_fingerprint", "") or "").strip().lower(),
        "chain_fingerprint": str(ledger.get("chain_fingerprint", "") or "").strip().lower(),
    }


def verify_root_transparency_ledger_export(ledger: dict[str, Any] | None) -> dict[str, Any]:
    current = dict(ledger or {})
    if str(
        current.get("type", STABLE_DM_ROOT_TRANSPARENCY_LEDGER_TYPE)
        or STABLE_DM_ROOT_TRANSPARENCY_LEDGER_TYPE
    ) != STABLE_DM_ROOT_TRANSPARENCY_LEDGER_TYPE:
        return {"ok": False, "detail": "stable root transparency ledger type invalid"}
    if _safe_int(current.get("schema_version", 0) or 0, 0) <= 0:
        return {"ok": False, "detail": "stable root transparency ledger schema_version required"}
    if str(current.get("transparency_scope", ROOT_TRANSPARENCY_SCOPE) or ROOT_TRANSPARENCY_SCOPE) != ROOT_TRANSPARENCY_SCOPE:
        return {"ok": False, "detail": "stable root transparency ledger scope invalid"}
    if _safe_int(current.get("exported_at", 0) or 0, 0) <= 0:
        return {"ok": False, "detail": "stable root transparency ledger exported_at required"}

    records = [dict(item or {}) for item in list(current.get("records") or []) if isinstance(item, dict)]
    if _safe_int(current.get("record_count", 0) or 0, 0) != len(records):
        return {"ok": False, "detail": "stable root transparency ledger record_count mismatch"}

    previous_fingerprint = ""
    record_fingerprints: list[str] = []
    head_binding_fingerprint = ""
    for record in records:
        payload = dict(record.get("payload") or {})
        record_fingerprint = transparency_record_fingerprint(record)
        if str(payload.get("previous_record_fingerprint", "") or "").strip().lower() != previous_fingerprint:
            return {"ok": False, "detail": "stable root transparency ledger chain mismatch"}
        previous_fingerprint = record_fingerprint
        head_binding_fingerprint = str(payload.get("binding_fingerprint", "") or "").strip().lower()
        record_fingerprints.append(record_fingerprint)

    current_record_fingerprint = record_fingerprints[-1] if record_fingerprints else ""
    if str(current.get("current_record_fingerprint", "") or "").strip().lower() != current_record_fingerprint:
        return {"ok": False, "detail": "stable root transparency ledger head mismatch"}
    if str(current.get("head_binding_fingerprint", "") or "").strip().lower() != head_binding_fingerprint:
        return {"ok": False, "detail": "stable root transparency ledger binding mismatch"}

    chain_fingerprint = transparency_record_chain_fingerprint(records)
    if str(current.get("chain_fingerprint", "") or "").strip().lower() != chain_fingerprint:
        return {"ok": False, "detail": "stable root transparency ledger fingerprint mismatch"}

    return {
        "ok": True,
        "record_count": len(records),
        "current_record_fingerprint": current_record_fingerprint,
        "head_binding_fingerprint": head_binding_fingerprint,
        "chain_fingerprint": chain_fingerprint,
    }


def publish_root_transparency_ledger_to_file(
    *,
    path: str | None = None,
    max_records: int | None = None,
) -> dict[str, Any]:
    from services.config import get_settings

    configured_path = str(path or getattr(get_settings(), "MESH_DM_ROOT_TRANSPARENCY_LEDGER_EXPORT_PATH", "") or "").strip()
    resolved_path = _resolve_transparency_ledger_path(configured_path)
    if resolved_path is None:
        return {"ok": False, "detail": "root transparency ledger export path required"}

    state = read_root_transparency_state()
    exported = export_root_transparency_ledger(max_records=max_records)
    if not exported.get("ok"):
        return exported
    try:
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = resolved_path.with_suffix(resolved_path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps(exported.get("ledger") or {}, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(resolved_path)
    except OSError:
        _record_ledger_export_status(
            state,
            ok=False,
            detail="root transparency ledger export failed",
            path=str(resolved_path),
        )
        _write_root_transparency_state(state)
        return {"ok": False, "detail": "root transparency ledger export failed"}
    _record_ledger_export_status(
        state,
        ok=True,
        detail="root transparency ledger exported",
        path=str(resolved_path),
        record_fingerprint=str(exported.get("current_record_fingerprint", "") or "").strip().lower(),
        chain_fingerprint=str(exported.get("chain_fingerprint", "") or "").strip().lower(),
    )
    _write_root_transparency_state(state)
    return {
        **exported,
        "path": str(resolved_path),
    }


def _configured_root_transparency_readback_source_ref(source_ref: str | None = None) -> str:
    from services.config import get_settings

    explicit = str(source_ref or "").strip()
    if explicit:
        return explicit
    return str(getattr(get_settings(), "MESH_DM_ROOT_TRANSPARENCY_LEDGER_READBACK_URI", "") or "").strip()


def read_external_root_transparency_ledger(source_ref: str | None = None) -> dict[str, Any]:
    configured_ref = _configured_root_transparency_readback_source_ref(source_ref)
    if not configured_ref:
        return {"ok": False, "detail": "root transparency ledger readback source not configured", "source_ref": ""}
    if "://" in configured_ref:
        try:
            with urllib.request.urlopen(configured_ref, timeout=10) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError:
            return {
                "ok": False,
                "detail": "root transparency ledger readback source unreadable",
                "source_ref": configured_ref,
            }
        except json.JSONDecodeError:
            return {
                "ok": False,
                "detail": "root transparency ledger readback source invalid",
                "source_ref": configured_ref,
            }
        except OSError:
            return {
                "ok": False,
                "detail": "root transparency ledger readback source unreadable",
                "source_ref": configured_ref,
            }
        if not isinstance(raw, dict):
            return {
                "ok": False,
                "detail": "root transparency ledger readback source root must be an object",
                "source_ref": configured_ref,
            }
        verified = verify_root_transparency_ledger_export(dict(raw or {}))
        if not verified.get("ok"):
            return {
                "ok": False,
                "detail": str(verified.get("detail", "") or "root transparency ledger readback invalid"),
                "source_ref": configured_ref,
            }
        return {
            "ok": True,
            "ledger": dict(raw or {}),
            "source_ref": configured_ref,
            **verified,
        }
    loaded = read_exported_root_transparency_ledger(configured_ref)
    if not loaded.get("ok"):
        return {
            "ok": False,
            "detail": str(loaded.get("detail", "") or "root transparency ledger readback invalid"),
            "source_ref": str(configured_ref or "").strip(),
        }
    return {
        **loaded,
        "source_ref": str(configured_ref or "").strip(),
    }


def verify_root_transparency_record_against_external_ledger(
    record: dict[str, Any] | None,
    *,
    source_ref: str | None = None,
) -> dict[str, Any]:
    configured_ref = _configured_root_transparency_readback_source_ref(source_ref)
    if not configured_ref:
        return {
            "ok": True,
            "configured": False,
            "detail": "root transparency ledger readback source not configured",
            "source_ref": "",
        }
    current_record = dict(record or {})
    target_record_fingerprint = transparency_record_fingerprint(current_record) if current_record else ""
    target_binding_fingerprint = str(
        dict(current_record.get("payload") or {}).get("binding_fingerprint", "") or ""
    ).strip().lower()
    if not target_record_fingerprint or not target_binding_fingerprint:
        return {
            "ok": False,
            "configured": True,
            "detail": "root transparency record incomplete for external readback",
            "source_ref": configured_ref,
        }
    loaded = read_external_root_transparency_ledger(configured_ref)
    if not loaded.get("ok"):
        return {
            "ok": False,
            "configured": True,
            "detail": str(loaded.get("detail", "") or "root transparency ledger readback invalid"),
            "source_ref": str(loaded.get("source_ref", configured_ref) or configured_ref).strip(),
        }
    ledger = dict(loaded.get("ledger") or {})
    ledger_exported_at = _safe_int(ledger.get("exported_at", 0) or 0, 0)
    if ledger_exported_at <= 0:
        return {
            "ok": False,
            "configured": True,
            "detail": "root transparency external ledger exported_at required",
            "source_ref": str(loaded.get("source_ref", configured_ref) or configured_ref).strip(),
        }
    if _root_transparency_ledger_stale(ledger_exported_at):
        return {
            "ok": False,
            "configured": True,
            "detail": "root transparency external ledger stale",
            "source_ref": str(loaded.get("source_ref", configured_ref) or configured_ref).strip(),
            "exported_at": ledger_exported_at,
        }
    record_visible = str(loaded.get("current_record_fingerprint", "") or "").strip().lower() == target_record_fingerprint
    binding_matches = str(loaded.get("head_binding_fingerprint", "") or "").strip().lower() == target_binding_fingerprint
    if not record_visible:
        return {
            "ok": False,
            "configured": True,
            "detail": "root transparency external ledger head mismatch",
            "source_ref": str(loaded.get("source_ref", configured_ref) or configured_ref).strip(),
            "record_visible": False,
            "binding_matches": binding_matches,
        }
    if not binding_matches:
        return {
            "ok": False,
            "configured": True,
            "detail": "root transparency external ledger binding mismatch",
            "source_ref": str(loaded.get("source_ref", configured_ref) or configured_ref).strip(),
            "record_visible": True,
            "binding_matches": False,
        }
    return {
        "ok": True,
        "configured": True,
        "source_ref": str(loaded.get("source_ref", configured_ref) or configured_ref).strip(),
        "record_visible": True,
        "binding_matches": True,
        "exported_at": ledger_exported_at,
        "chain_fingerprint": str(loaded.get("chain_fingerprint", "") or "").strip().lower(),
        "current_record_fingerprint": str(loaded.get("current_record_fingerprint", "") or "").strip().lower(),
    }


def read_exported_root_transparency_ledger(path: str | None = None) -> dict[str, Any]:
    from services.config import get_settings

    configured_path = str(path or getattr(get_settings(), "MESH_DM_ROOT_TRANSPARENCY_LEDGER_EXPORT_PATH", "") or "").strip()
    resolved_path = _resolve_transparency_ledger_path(configured_path)
    if resolved_path is None:
        return {"ok": False, "detail": "root transparency ledger export path required"}
    try:
        raw = json.loads(resolved_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"ok": False, "detail": "root transparency ledger export path not found"}
    except json.JSONDecodeError:
        return {"ok": False, "detail": "root transparency ledger export invalid"}
    except OSError:
        return {"ok": False, "detail": "root transparency ledger export unreadable"}
    if not isinstance(raw, dict):
        return {"ok": False, "detail": "root transparency ledger export root must be an object"}
    verified = verify_root_transparency_ledger_export(dict(raw or {}))
    if not verified.get("ok"):
        return verified
    return {
        "ok": True,
        "ledger": dict(raw or {}),
        "path": str(resolved_path),
        **verified,
    }


def _maybe_publish_root_transparency_ledger_to_configured_file() -> dict[str, Any]:
    from services.config import get_settings

    configured_path = str(getattr(get_settings(), "MESH_DM_ROOT_TRANSPARENCY_LEDGER_EXPORT_PATH", "") or "").strip()
    state = read_root_transparency_state()
    if not configured_path:
        _record_ledger_export_status(
            state,
            ok=False,
            detail="root transparency ledger export path not configured",
            path="",
        )
        _write_root_transparency_state(state)
        return {
            "ledger_export_ok": False,
            "ledger_export_detail": "root transparency ledger export path not configured",
            "ledger_export_path": "",
            "ledger_exported_at": _safe_int(state.get("ledger_exported_at", 0) or 0, 0),
            "ledger_export_record_fingerprint": "",
            "ledger_export_chain_fingerprint": "",
        }

    published = publish_root_transparency_ledger_to_file(path=configured_path)
    if not published.get("ok"):
        latest = read_root_transparency_state()
        return {
            "ledger_export_ok": False,
            "ledger_export_detail": str(published.get("detail", "") or "root transparency ledger export failed"),
            "ledger_export_path": str(configured_path or "").strip(),
            "ledger_exported_at": _safe_int(latest.get("ledger_exported_at", 0) or 0, 0),
            "ledger_export_record_fingerprint": str(
                latest.get("ledger_export_record_fingerprint", "") or ""
            ).strip().lower(),
            "ledger_export_chain_fingerprint": str(
                latest.get("ledger_export_chain_fingerprint", "") or ""
            ).strip().lower(),
        }

    latest = read_root_transparency_state()
    return {
        "ledger_export_ok": bool(latest.get("ledger_export_ok", False)),
        "ledger_export_detail": str(latest.get("ledger_export_detail", "") or "").strip(),
        "ledger_export_path": str(latest.get("ledger_export_path", "") or "").strip(),
        "ledger_exported_at": _safe_int(latest.get("ledger_exported_at", 0) or 0, 0),
        "ledger_export_record_fingerprint": str(
            latest.get("ledger_export_record_fingerprint", "") or ""
        ).strip().lower(),
        "ledger_export_chain_fingerprint": str(
            latest.get("ledger_export_chain_fingerprint", "") or ""
        ).strip().lower(),
    }


def _maybe_verify_root_transparency_record_from_configured_source(record: dict[str, Any]) -> dict[str, Any]:
    state = read_root_transparency_state()
    verified = verify_root_transparency_record_against_external_ledger(record)
    if not verified.get("configured"):
        _record_ledger_readback_status(
            state,
            ok=False,
            detail="root transparency ledger readback source not configured",
            source_ref="",
            exported_at=0,
            record_visible=False,
            binding_matches=False,
        )
        _write_root_transparency_state(state)
        latest = read_root_transparency_state()
        return {
            "ledger_readback_ok": False,
            "ledger_readback_detail": str(latest.get("ledger_readback_detail", "") or "").strip(),
            "ledger_readback_source_ref": str(latest.get("ledger_readback_source_ref", "") or "").strip(),
            "ledger_readback_checked_at": _safe_int(latest.get("ledger_readback_checked_at", 0) or 0, 0),
            "ledger_readback_exported_at": _safe_int(latest.get("ledger_readback_exported_at", 0) or 0, 0),
            "ledger_readback_record_visible": False,
            "ledger_readback_binding_matches": False,
        }
    _record_ledger_readback_status(
        state,
        ok=bool(verified.get("ok")),
        detail=str(verified.get("detail", "") or "root transparency ledger readback verified"),
        source_ref=str(verified.get("source_ref", "") or "").strip(),
        exported_at=_safe_int(verified.get("exported_at", 0) or 0, 0),
        record_visible=bool(verified.get("record_visible", verified.get("ok", False))),
        binding_matches=bool(verified.get("binding_matches", verified.get("ok", False))),
    )
    _write_root_transparency_state(state)
    latest = read_root_transparency_state()
    return {
        "ledger_readback_ok": bool(latest.get("ledger_readback_ok", False)),
        "ledger_readback_detail": str(latest.get("ledger_readback_detail", "") or "").strip(),
        "ledger_readback_source_ref": str(latest.get("ledger_readback_source_ref", "") or "").strip(),
        "ledger_readback_checked_at": _safe_int(latest.get("ledger_readback_checked_at", 0) or 0, 0),
        "ledger_readback_exported_at": _safe_int(latest.get("ledger_readback_exported_at", 0) or 0, 0),
        "ledger_readback_record_visible": bool(latest.get("ledger_readback_record_visible", False)),
        "ledger_readback_binding_matches": bool(latest.get("ledger_readback_binding_matches", False)),
    }
