from __future__ import annotations

import secrets
import threading
import time
from typing import Any

from services.config import get_settings
from services.mesh.mesh_local_custody import (
    read_sensitive_domain_json as _read_sensitive_domain_json,
    write_sensitive_domain_json as _write_sensitive_domain_json,
)

POLICY_DOMAIN = "private_relay_policy"
POLICY_FILENAME = "scoped_relay_policy.json"
POLICY_CUSTODY_SCOPE = "private_relay_policy"
_ALLOWED_SCOPE_TYPES = {"dm_contact", "gate", "profile"}
_LOCK = threading.RLock()


def read_sensitive_domain_json(_domain: str, _filename: str, default_factory):
    return _read_sensitive_domain_json(
        POLICY_DOMAIN,
        POLICY_FILENAME,
        default_factory,
        custody_scope=POLICY_CUSTODY_SCOPE,
    )


def write_sensitive_domain_json(_domain: str, _filename: str, payload: dict[str, Any]):
    _write_sensitive_domain_json(
        POLICY_DOMAIN,
        POLICY_FILENAME,
        payload,
        custody_scope=POLICY_CUSTODY_SCOPE,
    )


def _now() -> float:
    return float(time.time())


def _default_state() -> dict[str, Any]:
    return {"version": 1, "updated_at": 0, "grants": []}


def _normalize_profile(profile: str) -> str:
    return str(profile or "dev").strip().lower() or "dev"


def _normalize_scope(scope_type: str, scope_id: str) -> tuple[str, str]:
    normalized_type = str(scope_type or "").strip().lower()
    normalized_id = str(scope_id or "").strip()
    if normalized_type not in _ALLOWED_SCOPE_TYPES:
        raise ValueError("scope_type must be dm_contact, gate, or profile")
    if not normalized_id:
        raise ValueError("scope_id is required")
    return normalized_type, normalized_id


def _read_state(now: float | None = None) -> dict[str, Any]:
    current_now = float(now if now is not None else _now())
    raw = read_sensitive_domain_json(POLICY_DOMAIN, POLICY_FILENAME, _default_state)
    grants: list[dict[str, Any]] = []
    for grant in list((raw or {}).get("grants") or []):
        if not isinstance(grant, dict):
            continue
        try:
            scope_type, scope_id = _normalize_scope(
                str(grant.get("scope_type", "") or ""),
                str(grant.get("scope_id", "") or ""),
            )
        except ValueError:
            continue
        expires_at = float(grant.get("expires_at", 0.0) or 0.0)
        if expires_at <= current_now:
            continue
        grants.append(
            {
                "grant_id": str(grant.get("grant_id", "") or ""),
                "scope_type": scope_type,
                "scope_id": scope_id,
                "profile": _normalize_profile(str(grant.get("profile", "") or "")),
                "hidden_transport_required": bool(
                    grant.get("hidden_transport_required", True)
                ),
                "reason": str(grant.get("reason", "") or ""),
                "created_at": float(grant.get("created_at", current_now) or current_now),
                "expires_at": expires_at,
                "revoked": bool(grant.get("revoked", False)),
            }
        )
    return {
        "version": 1,
        "updated_at": int(float((raw or {}).get("updated_at", 0) or 0)),
        "grants": [grant for grant in grants if not bool(grant.get("revoked", False))],
    }


def _write_state(state: dict[str, Any]) -> None:
    write_sensitive_domain_json(
        POLICY_DOMAIN,
        POLICY_FILENAME,
        {
            "version": 1,
            "updated_at": int(_now()),
            "grants": list(state.get("grants") or []),
        },
    )


def _configured_ttl_s(ttl_s: int | None = None) -> int:
    if ttl_s is not None:
        return max(1, int(ttl_s or 1))
    try:
        return max(1, int(get_settings().MESH_PRIVATE_RELAY_POLICY_TTL_S or 1))
    except Exception:
        return 3600


def grant_relay_policy(
    *,
    scope_type: str,
    scope_id: str,
    profile: str = "dev",
    hidden_transport_required: bool = True,
    ttl_s: int | None = None,
    reason: str = "",
    now: float | None = None,
) -> dict[str, Any]:
    current_now = float(now if now is not None else _now())
    normalized_type, normalized_id = _normalize_scope(scope_type, scope_id)
    normalized_profile = _normalize_profile(profile)
    expires_at = current_now + _configured_ttl_s(ttl_s)
    grant = {
        "grant_id": f"relay_policy_{secrets.token_hex(8)}",
        "scope_type": normalized_type,
        "scope_id": normalized_id,
        "profile": normalized_profile,
        "hidden_transport_required": bool(hidden_transport_required),
        "reason": str(reason or ""),
        "created_at": current_now,
        "expires_at": expires_at,
        "revoked": False,
    }
    with _LOCK:
        state = _read_state(now=current_now)
        state["grants"] = [
            existing
            for existing in list(state.get("grants") or [])
            if not (
                str(existing.get("scope_type", "") or "") == normalized_type
                and str(existing.get("scope_id", "") or "") == normalized_id
                and str(existing.get("profile", "") or "") == normalized_profile
            )
        ]
        state["grants"].append(grant)
        _write_state(state)
    return dict(grant)


def evaluate_relay_policy(
    *,
    scope_type: str,
    scope_id: str,
    profile: str = "dev",
    hidden_transport_effective: bool = False,
    now: float | None = None,
) -> dict[str, Any]:
    current_now = float(now if now is not None else _now())
    try:
        normalized_type, normalized_id = _normalize_scope(scope_type, scope_id)
    except ValueError as exc:
        return {"granted": False, "reason_code": "relay_policy_invalid_scope", "detail": str(exc)}
    normalized_profile = _normalize_profile(profile)
    with _LOCK:
        state = _read_state(now=current_now)
    for grant in list(state.get("grants") or []):
        if str(grant.get("scope_type", "") or "") != normalized_type:
            continue
        if str(grant.get("scope_id", "") or "") != normalized_id:
            continue
        if str(grant.get("profile", "") or "") != normalized_profile:
            continue
        if bool(grant.get("hidden_transport_required", True)) and not bool(hidden_transport_effective):
            return {
                "granted": False,
                "reason_code": "relay_policy_hidden_transport_required",
                "grant": dict(grant),
            }
        return {
            "granted": True,
            "reason_code": "relay_policy_granted",
            "grant": dict(grant),
        }
    return {"granted": False, "reason_code": "relay_policy_not_granted"}


def relay_policy_grants_dm(
    *,
    recipient_id: str,
    profile: str = "dev",
    hidden_transport_effective: bool = False,
    now: float | None = None,
) -> dict[str, Any]:
    normalized_recipient = str(recipient_id or "").strip()
    if not normalized_recipient:
        return {"granted": False, "reason_code": "relay_policy_missing_recipient"}
    contact_decision = evaluate_relay_policy(
        scope_type="dm_contact",
        scope_id=normalized_recipient,
        profile=profile,
        hidden_transport_effective=hidden_transport_effective,
        now=now,
    )
    if bool(contact_decision.get("granted", False)) or str(
        contact_decision.get("reason_code", "") or ""
    ) == "relay_policy_hidden_transport_required":
        return contact_decision
    profile_key = _normalize_profile(profile)
    return evaluate_relay_policy(
        scope_type="profile",
        scope_id=profile_key,
        profile=profile_key,
        hidden_transport_effective=hidden_transport_effective,
        now=now,
    )


def revoke_relay_policy(*, scope_type: str, scope_id: str, profile: str = "dev") -> int:
    normalized_type, normalized_id = _normalize_scope(scope_type, scope_id)
    normalized_profile = _normalize_profile(profile)
    revoked = 0
    with _LOCK:
        state = _read_state()
        remaining: list[dict[str, Any]] = []
        for grant in list(state.get("grants") or []):
            if (
                str(grant.get("scope_type", "") or "") == normalized_type
                and str(grant.get("scope_id", "") or "") == normalized_id
                and str(grant.get("profile", "") or "") == normalized_profile
            ):
                revoked += 1
                continue
            remaining.append(grant)
        state["grants"] = remaining
        _write_state(state)
    return revoked


def relay_policy_snapshot(*, now: float | None = None) -> dict[str, Any]:
    with _LOCK:
        return _read_state(now=now)


def reset_relay_policy_for_tests() -> None:
    with _LOCK:
        _write_state(_default_state())
