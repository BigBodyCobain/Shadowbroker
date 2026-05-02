from __future__ import annotations

import hashlib
from typing import Any

ORDINARY_METADATA_EXPOSURE = "ordinary"
DIAGNOSTIC_METADATA_EXPOSURE = "diagnostic"


def normalize_metadata_exposure(exposure: str = "") -> str:
    normalized = str(exposure or "").strip().lower()
    if normalized in {"diagnostic", "diag", "debug", "admin"}:
        return DIAGNOSTIC_METADATA_EXPOSURE
    return ORDINARY_METADATA_EXPOSURE


def metadata_exposure_for_request(
    request: Any | None = None,
    *,
    authenticated: bool = False,
) -> str:
    if not authenticated or request is None:
        return ORDINARY_METADATA_EXPOSURE
    try:
        query_params = getattr(request, "query_params", {}) or {}
        requested = str(
            query_params.get("private_metadata")
            or query_params.get("metadata")
            or query_params.get("exposure")
            or ""
        ).strip()
    except Exception:
        requested = ""
    return normalize_metadata_exposure(requested)


def stable_metadata_log_ref(value: str, *, prefix: str = "ref") -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return f"{prefix}:unknown"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}:{digest}"


def _generic_lookup_detail(*, lookup_token_present: bool = False) -> str:
    if lookup_token_present:
        return "Invite lookup unavailable"
    return "Lookup unavailable"


def _generic_mailbox_detail() -> str:
    return "Mailbox unavailable"


def private_delivery_result_view(result: dict[str, Any], *, exposure: str = "") -> dict[str, Any]:
    normalized = normalize_metadata_exposure(exposure)
    raw = {
        key: value
        for key, value in dict(result or {}).items()
        if key not in {"payload", "envelope", "event"}
    }
    if normalized == DIAGNOSTIC_METADATA_EXPOSURE:
        return raw
    return {}


def private_delivery_item_view(item: dict[str, Any], *, exposure: str = "") -> dict[str, Any]:
    normalized = normalize_metadata_exposure(exposure)
    payload = dict(item.get("payload") or {})
    result = dict(item.get("result") or {})
    view = {
        "id": str(item.get("id", "") or ""),
        "lane": str(item.get("lane", "") or ""),
        "release_key": "",
        "release_state": str(item.get("release_state", "") or ""),
        "canonical_release_state": str(item.get("canonical_release_state", "") or ""),
        "local_state": str(item.get("local_state", "") or ""),
        "network_state": str(item.get("network_state", "") or ""),
        "required_tier": str(item.get("required_tier", "") or ""),
        "current_tier": str(item.get("current_tier", "") or ""),
        "status": dict(item.get("status") or {}),
        "delivery_phase": dict(item.get("delivery_phase") or {}),
        "attempts": int(item.get("attempts", 0) or 0),
        "created_at": float(item.get("created_at", 0.0) or 0.0),
        "updated_at": float(item.get("updated_at", 0.0) or 0.0),
        "released_at": float(item.get("released_at", 0.0) or 0.0),
        "last_error": "",
        "result": private_delivery_result_view(result, exposure=normalized),
        "approval": dict(item.get("approval") or {}),
        "meta": {
            "msg_id": "",
            "event_id": "",
            "gate_id": "",
            "peer_id": "",
        },
    }
    if normalized == DIAGNOSTIC_METADATA_EXPOSURE:
        view["release_key"] = str(item.get("release_key", "") or "")
        view["last_error"] = str(item.get("last_error", "") or "")
        view["meta"] = {
            "msg_id": str(payload.get("msg_id", "") or ""),
            "event_id": str(payload.get("event_id", "") or ""),
            "gate_id": str(payload.get("gate_id", "") or ""),
            "peer_id": str(payload.get("peer_id", "") or ""),
        }
    return view


def dm_lookup_response_view(
    payload: dict[str, Any],
    *,
    exposure: str = "",
    lookup_token_present: bool = False,
) -> dict[str, Any]:
    normalized = normalize_metadata_exposure(exposure)
    view = dict(payload or {})
    invite_lookup = (
        lookup_token_present
        or str(view.get("lookup_mode", "") or "").strip() == "invite_lookup_handle"
    )
    if normalized != DIAGNOSTIC_METADATA_EXPOSURE:
        if not bool(view.get("ok")):
            view["detail"] = _generic_lookup_detail(lookup_token_present=invite_lookup)
            view.pop("agent_id", None)
            view.pop("lookup_mode", None)
            view.pop("removal_target", None)
            return view
        if invite_lookup:
            view.pop("agent_id", None)
    return view


def dm_mailbox_response_view(
    payload: dict[str, Any],
    *,
    exposure: str = "",
    diagnostic: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = normalize_metadata_exposure(exposure)
    view = dict(payload or {})
    if normalized != DIAGNOSTIC_METADATA_EXPOSURE:
        if not bool(view.get("ok")):
            view["detail"] = _generic_mailbox_detail()
        return view
    if diagnostic:
        view.update(dict(diagnostic))
    return view
