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
from services.mesh.mesh_metadata_exposure import private_delivery_item_view
from services.mesh.mesh_privacy_policy import (
    canonical_release_state,
    network_release_state,
    private_delivery_status,
    queued_delivery_status,
)

OUTBOX_DOMAIN = "private_outbox"
OUTBOX_FILENAME = "sealed_private_outbox.json"
OUTBOX_CUSTODY_SCOPE = "private_outbox"
_RELAY_APPROVAL_WINDOW_S = 15.0
_PREPARING_PRIVATE_LANE_REASON = "Trying more private routing in the background."
_RELAY_APPROVAL_REASON = (
    "This message is still queued. You can keep waiting, or send it now via relay with weaker privacy."
)
_RELAY_APPROVAL_STATUS_LABEL = "More private routing currently unavailable"


def read_sensitive_domain_json(_domain: str, _filename: str, default_factory):
    return _read_sensitive_domain_json(
        OUTBOX_DOMAIN,
        OUTBOX_FILENAME,
        default_factory,
        custody_scope=OUTBOX_CUSTODY_SCOPE,
    )


def write_sensitive_domain_json(_domain: str, _filename: str, payload: dict[str, Any]):
    _write_sensitive_domain_json(
        OUTBOX_DOMAIN,
        OUTBOX_FILENAME,
        payload,
        custody_scope=OUTBOX_CUSTODY_SCOPE,
    )


def read_domain_json(_domain: str, _filename: str, default_factory):
    return read_sensitive_domain_json(_domain, _filename, default_factory)


def write_domain_json(_domain: str, _filename: str, payload: dict[str, Any]):
    write_sensitive_domain_json(_domain, _filename, payload)


def _default_outbox_state() -> dict[str, Any]:
    return {
        "version": 1,
        "updated_at": 0,
        "items": [],
    }


def _now() -> float:
    return float(time.time())


class PrivateOutbox:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._items: dict[str, dict[str, Any]] = {}
        self._index: dict[tuple[str, str], str] = {}
        self._session_release_state: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        with self._lock:
            raw = read_domain_json(
                OUTBOX_DOMAIN,
                OUTBOX_FILENAME,
                _default_outbox_state,
            )
            items = list((raw or {}).get("items") or [])
            self._items.clear()
            self._index.clear()
            for item in items:
                if not isinstance(item, dict):
                    continue
                normalized = self._normalize_item(item)
                item_id = str(normalized.get("id", "") or "").strip()
                release_key = str(normalized.get("release_key", "") or "").strip()
                lane = str(normalized.get("lane", "") or "").strip().lower()
                if not item_id or not lane or not release_key:
                    continue
                self._items[item_id] = normalized
                self._index[(lane, release_key)] = item_id

    def reset_for_tests(self) -> None:
        with self._lock:
            self._items.clear()
            self._index.clear()
            self._session_release_state.clear()

    def _save(self) -> None:
        write_domain_json(
            OUTBOX_DOMAIN,
            OUTBOX_FILENAME,
            {
                "version": 1,
                "updated_at": int(_now()),
                "items": list(self._items.values()),
            },
        )

    def _normalize_item(self, item: dict[str, Any]) -> dict[str, Any]:
        status = dict(item.get("status") or {})
        status_code = str(status.get("code", "") or "").strip() or "queued_private_delivery"
        lane = str(item.get("lane", "") or "").strip().lower()
        current_tier = str(item.get("current_tier", "public_degraded") or "public_degraded")
        normalized = {
            "id": str(item.get("id", "") or ""),
            "lane": lane,
            "release_key": str(item.get("release_key", "") or ""),
            "payload": dict(item.get("payload") or {}),
            "status": private_delivery_status(
                status_code,
                reason_code=str(status.get("reason_code", "") or ""),
                plain_reason=str(status.get("reason", "") or ""),
            ),
            "required_tier": str(item.get("required_tier", "") or ""),
            "current_tier": current_tier,
            "release_state": str(item.get("release_state", "queued") or "queued"),
            "attempts": int(item.get("attempts", 0) or 0),
            "created_at": float(item.get("created_at", _now()) or _now()),
            "updated_at": float(item.get("updated_at", _now()) or _now()),
            "released_at": float(item.get("released_at", 0.0) or 0.0),
            "last_error": str(item.get("last_error", "") or ""),
            "result": dict(item.get("result") or {}),
        }
        if normalized["release_state"] == "releasing":
            normalized["release_state"] = "queued"
        return normalized

    def _release_approval_enabled(self) -> bool:
        return bool(get_settings().MESH_PRIVATE_RELEASE_APPROVAL_ENABLE)

    def _release_state_snapshot_locked(self, item_id: str) -> dict[str, Any]:
        state = dict(self._session_release_state.get(item_id) or {})
        return {
            "first_failure_at": float(state.get("first_failure_at", 0.0) or 0.0),
            "last_failure_at": float(state.get("last_failure_at", 0.0) or 0.0),
            "reason_code": str(state.get("reason_code", "") or ""),
            "approved": bool(state.get("approved", False)),
            "wait_selected": bool(state.get("wait_selected", False)),
            "approval_required": bool(state.get("approval_required", False)),
            "policy_id": str(state.get("policy_id", "") or ""),
            "policy_scope": dict(state.get("policy_scope") or {}),
        }

    def release_approval_state(self, item_id: str) -> dict[str, Any]:
        with self._lock:
            return self._release_state_snapshot_locked(str(item_id or "").strip())

    def note_release_revalidation_failure(
        self,
        item_id: str,
        *,
        reason_code: str,
        now: float | None = None,
    ) -> dict[str, Any]:
        current_now = float(now if now is not None else _now())
        with self._lock:
            normalized_id = str(item_id or "").strip()
            if normalized_id not in self._items or not self._release_approval_enabled():
                return self._release_state_snapshot_locked(normalized_id)
            state = self._release_state_snapshot_locked(normalized_id)
            if state["first_failure_at"] <= 0:
                state["first_failure_at"] = current_now
            state["last_failure_at"] = current_now
            state["reason_code"] = str(reason_code or state["reason_code"] or "")
            if not state["approved"] and not state["wait_selected"]:
                state["approval_required"] = (current_now - state["first_failure_at"]) >= _RELAY_APPROVAL_WINDOW_S
            else:
                state["approval_required"] = False
            self._session_release_state[normalized_id] = state
            return dict(state)

    def approve_relay_release(self, item_id: str) -> dict[str, Any]:
        with self._lock:
            normalized_id = str(item_id or "").strip()
            if normalized_id not in self._items:
                return self._release_state_snapshot_locked(normalized_id)
            state = self._release_state_snapshot_locked(normalized_id)
            state["approved"] = True
            state["wait_selected"] = False
            state["approval_required"] = False
            item = dict(self._items.get(normalized_id) or {})
            policy = self._grant_scoped_relay_policy_locked(item)
            if policy:
                state["policy_id"] = str(policy.get("grant_id", "") or "")
                state["policy_scope"] = {
                    "type": str(policy.get("scope_type", "") or ""),
                    "id": str(policy.get("scope_id", "") or ""),
                    "profile": str(policy.get("profile", "") or ""),
                    "hidden_transport_required": bool(
                        policy.get("hidden_transport_required", True)
                    ),
                    "expires_at": float(policy.get("expires_at", 0.0) or 0.0),
                }
            self._session_release_state[normalized_id] = state
            return dict(state)

    def continue_waiting_for_release(self, item_id: str) -> dict[str, Any]:
        with self._lock:
            normalized_id = str(item_id or "").strip()
            if normalized_id not in self._items:
                return self._release_state_snapshot_locked(normalized_id)
            state = self._release_state_snapshot_locked(normalized_id)
            state["approved"] = False
            state["wait_selected"] = True
            state["approval_required"] = False
            self._session_release_state[normalized_id] = state
            return dict(state)

    def clear_release_session_state(self, item_id: str) -> None:
        with self._lock:
            self._session_release_state.pop(str(item_id or "").strip(), None)

    def _grant_scoped_relay_policy_locked(self, item: dict[str, Any]) -> dict[str, Any]:
        lane = str(item.get("lane", "") or "").strip().lower()
        payload = dict(item.get("payload") or {})
        recipient_id = str(payload.get("recipient_id", "") or "").strip()
        if lane != "dm" or not recipient_id:
            return {}
        try:
            from services.mesh.mesh_relay_policy import grant_relay_policy
            from services.release_profiles import current_release_profile

            profile = current_release_profile()
        except Exception:
            profile = "dev"
        try:
            return grant_relay_policy(
                scope_type="dm_contact",
                scope_id=recipient_id,
                profile=str(profile or "dev"),
                hidden_transport_required=True,
                reason="per_item_relay_approval",
            )
        except Exception:
            return {}

    def enqueue(
        self,
        *,
        lane: str,
        release_key: str,
        payload: dict[str, Any],
        current_tier: str,
        required_tier: str,
    ) -> dict[str, Any]:
        lane_key = str(lane or "").strip().lower()
        release_id = str(release_key or "").strip()
        if not lane_key or not release_id:
            raise ValueError("lane and release_key are required")
        with self._lock:
            existing_id = self._index.get((lane_key, release_id))
            if existing_id:
                existing = dict(self._items[existing_id])
                if existing.get("release_state") != "delivered":
                    previous = dict(existing)
                    existing["status"] = queued_delivery_status(lane_key, current_tier)
                    existing["current_tier"] = str(current_tier or "")
                    existing["updated_at"] = _now()
                    self._items[existing_id] = existing
                    try:
                        self._save()
                    except Exception:
                        self._items[existing_id] = previous
                        raise
                return dict(self._items[existing_id])
            item_id = f"outbox_{secrets.token_hex(8)}"
            item = {
                "id": item_id,
                "lane": lane_key,
                "release_key": release_id,
                "payload": dict(payload or {}),
                "status": queued_delivery_status(lane_key, current_tier),
                "required_tier": str(required_tier or ""),
                "current_tier": str(current_tier or ""),
                "release_state": "queued",
                "attempts": 0,
                "created_at": _now(),
                "updated_at": _now(),
                "released_at": 0.0,
                "last_error": "",
                "result": {},
            }
            self._items[item_id] = item
            self._index[(lane_key, release_id)] = item_id
            try:
                self._save()
            except Exception:
                self._items.pop(item_id, None)
                self._index.pop((lane_key, release_id), None)
                raise
            return dict(item)

    def has_pending(self) -> bool:
        with self._lock:
            return any(item.get("release_state") != "delivered" for item in self._items.values())

    def pending_items(self) -> list[dict[str, Any]]:
        with self._lock:
            items = [
                dict(item)
                for item in self._items.values()
                if str(item.get("release_state", "") or "") != "delivered"
            ]
        return sorted(items, key=lambda item: (str(item.get("lane", "")), float(item.get("created_at", 0.0) or 0.0)))

    def mark_releasing(self, item_id: str, *, current_tier: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._items.get(str(item_id or "").strip())
            if item is None:
                return None
            previous = dict(item)
            item = dict(item)
            item["release_state"] = "releasing"
            item["current_tier"] = str(current_tier or "")
            item["status"] = private_delivery_status(
                "publishing_private",
                reason_code="private_release_in_progress",
                plain_reason="The sealed message is being published on the private lane.",
            )
            item["attempts"] = int(item.get("attempts", 0) or 0) + 1
            item["updated_at"] = _now()
            self._items[item_id] = item
            try:
                self._save()
            except Exception:
                self._items[item_id] = previous
                raise
            return dict(item)

    def mark_queued(
        self,
        item_id: str,
        *,
        current_tier: str,
        status_code: str,
        reason_code: str,
        plain_reason: str,
        error: str = "",
    ) -> dict[str, Any] | None:
        with self._lock:
            item = self._items.get(str(item_id or "").strip())
            if item is None:
                return None
            previous = dict(item)
            updated = dict(item)
            updated["release_state"] = "queued"
            updated["current_tier"] = str(current_tier or "")
            updated["status"] = private_delivery_status(
                status_code,
                reason_code=reason_code,
                plain_reason=plain_reason,
            )
            updated["last_error"] = str(error or "")
            updated["updated_at"] = _now()
            self._items[item_id] = updated
            try:
                self._save()
            except Exception:
                self._items[item_id] = previous
                raise
            return dict(updated)

    def mark_delivered(
        self,
        item_id: str,
        *,
        current_tier: str,
        result: dict[str, Any],
    ) -> dict[str, Any] | None:
        with self._lock:
            item = self._items.get(str(item_id or "").strip())
            if item is None:
                return None
            previous = dict(item)
            updated = dict(item)
            updated["release_state"] = "delivered"
            updated["current_tier"] = str(current_tier or "")
            updated["status"] = private_delivery_status(
                "delivered_privately",
                reason_code="release_completed",
                plain_reason="The message was delivered on the private lane.",
            )
            updated["last_error"] = ""
            updated["result"] = dict(result or {})
            updated["released_at"] = _now()
            updated["updated_at"] = _now()
            self._items[item_id] = updated
            try:
                self._save()
            except Exception:
                self._items[item_id] = previous
                raise
            self._session_release_state.pop(item_id, None)
            return dict(updated)

    def list_items(
        self,
        *,
        lane: str = "",
        limit: int = 50,
        exposure: str = "",
    ) -> list[dict[str, Any]]:
        lane_filter = str(lane or "").strip().lower()
        with self._lock:
            items = [dict(item) for item in self._items.values()]
        if lane_filter:
            items = [item for item in items if str(item.get("lane", "") or "") == lane_filter]
        items.sort(key=lambda item: float(item.get("created_at", 0.0) or 0.0), reverse=True)
        return [
            self._public_item(item, exposure=exposure)
            for item in items[: max(1, int(limit or 1))]
        ]

    def get_item(self, item_id: str, *, exposure: str = "") -> dict[str, Any] | None:
        with self._lock:
            item = self._items.get(str(item_id or "").strip())
            if item is None:
                return None
            return self._public_item(dict(item), exposure=exposure)

    def summary(self, *, current_tier: str, exposure: str = "") -> dict[str, Any]:
        with self._lock:
            items = [dict(item) for item in self._items.values()]
        pending = [item for item in items if item.get("release_state") != "delivered"]
        preparing = [
            item for item in pending if str((item.get("status") or {}).get("code", "") or "") == "preparing_private_lane"
        ]
        queued = [
            item for item in pending if str((item.get("status") or {}).get("code", "") or "") == "queued_private_delivery"
        ]
        approval_required = [
            item
            for item in pending
            if bool((self._approval_overlay(item) or {}).get("required", False))
        ]
        return {
            "pending_count": len(pending),
            "preparing_count": len(preparing),
            "queued_count": len(queued),
            "approval_required_count": len(approval_required),
            "current_tier": str(current_tier or ""),
            "items": [
                self._public_item(item, exposure=exposure)
                for item in sorted(
                    pending,
                    key=lambda item: float(item.get("created_at", 0.0) or 0.0),
                )[:10]
            ],
        }

    def _public_item(self, item: dict[str, Any], *, exposure: str = "") -> dict[str, Any]:
        view_item = dict(item)
        lane = str(view_item.get("lane", "") or "").strip().lower()
        view_item["canonical_release_state"] = canonical_release_state(
            str(view_item.get("release_state", "") or ""),
            local_sealed=True,
        )
        view_item["local_state"] = "sealed_local"
        view_item["network_state"] = network_release_state(
            lane,
            str(view_item.get("release_state", "") or ""),
            result=dict(view_item.get("result") or {}),
            local_sealed=True,
        )
        view_item["delivery_phase"] = {
            "local": view_item["local_state"],
            "network": view_item["network_state"],
            "internal": str(view_item.get("release_state", "") or ""),
        }
        approval = self._approval_overlay(view_item)
        if approval:
            if approval.get("required"):
                view_item["status"] = {
                    "code": "weaker_privacy_approval_required",
                    "label": _RELAY_APPROVAL_STATUS_LABEL,
                    "reason_code": str(approval.get("reason_code", "") or ""),
                    "reason": _RELAY_APPROVAL_REASON,
                }
            else:
                view_item["status"] = private_delivery_status(
                    "preparing_private_lane",
                    reason_code=str(approval.get("reason_code", "") or ""),
                    plain_reason=_PREPARING_PRIVATE_LANE_REASON,
                )
            view_item["approval"] = approval
        return private_delivery_item_view(view_item, exposure=exposure)

    def _approval_overlay(self, item: dict[str, Any]) -> dict[str, Any]:
        item_id = str(item.get("id", "") or "").strip()
        lane = str(item.get("lane", "") or "").strip().lower()
        if not item_id or lane != "dm" or not self._release_approval_enabled():
            return {}
        state = self._release_state_snapshot_locked(item_id)
        first_failure_at = float(state.get("first_failure_at", 0.0) or 0.0)
        if first_failure_at <= 0 or bool(state.get("approved", False)):
            return {}
        required = bool(state.get("approval_required", False)) and not bool(state.get("wait_selected", False))
        return {
            "required": required,
            "reason_code": str(state.get("reason_code", "") or ""),
            "started_at": int(first_failure_at),
            "window_seconds": int(_RELAY_APPROVAL_WINDOW_S),
            "status_label": (
                _RELAY_APPROVAL_STATUS_LABEL if required else "Preparing private lane"
            ),
            "detail": _RELAY_APPROVAL_REASON if required else _PREPARING_PRIVATE_LANE_REASON,
            "actions": (
                [
                    {"code": "wait", "label": "Keep waiting", "emphasis": "primary"},
                    {"code": "relay", "label": "Send via relay", "emphasis": "secondary"},
                ]
                if required
                else []
            ),
        }


private_delivery_outbox = PrivateOutbox()


def reset_private_delivery_outbox_for_tests() -> None:
    private_delivery_outbox.reset_for_tests()
