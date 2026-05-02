from __future__ import annotations

import threading
import time
from typing import Any

from services.mesh.mesh_privacy_policy import (
    PRIVATE_LANE_READINESS_LABELS,
    normalize_transport_tier,
    private_lane_readiness_status,
    transport_tier_is_sufficient,
)

WARMUP_REASON_DEFAULTS = {
    "queued_dm_delivery": "private_strong",
    # Hardening Rec #4: gate content release now requires private_strong
    # (same floor as DM). Warmup request for queued gate delivery targets
    # the elevated tier so the transport manager bootstraps accordingly.
    "queued_gate_delivery": "private_strong",
    "dm_surface_open": "private_control_only",
    "gate_surface_open": "private_control_only",
    "invite_bootstrap": "private_control_only",
    "startup_resume": "private_control_only",
}

_REASON_RETENTION_S = 180.0
_WARMUP_COOLDOWN_S = 5.0
_UNAVAILABLE_AFTER_ATTEMPTS = 3


def _highest_required_tier(tiers: list[str]) -> str:
    ordered = [
        "public_degraded",
        "private_control_only",
        "private_transitional",
        "private_strong",
    ]
    highest = "public_degraded"
    for tier in tiers:
        normalized = normalize_transport_tier(tier)
        if ordered.index(normalized) > ordered.index(highest):
            highest = normalized
    return highest


class PrivateTransportManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.reset_for_tests()

    def reset_for_tests(self) -> None:
        with self._lock:
            self._reason_requests: dict[str, dict[str, Any]] = {}
            self._last_reason = ""
            self._last_attempt_reason = ""
            self._last_attempt_at = 0.0
            self._last_ready_at = 0.0
            self._cooldown_until = 0.0
            self._attempt_count = 0
            self._suppressed_count = 0
            self._approval_required = False

    def _cleanup_locked(self, now: float) -> None:
        expired = [
            reason
            for reason, entry in self._reason_requests.items()
            if (now - float(entry.get("requested_at", 0.0) or 0.0)) > _REASON_RETENTION_S
        ]
        for reason in expired:
            self._reason_requests.pop(reason, None)

    def _active_reasons_locked(self) -> list[str]:
        return sorted(self._reason_requests.keys())

    def _required_tier_locked(self) -> str:
        tiers = [
            str(entry.get("required_tier", "public_degraded") or "public_degraded")
            for entry in self._reason_requests.values()
        ]
        return _highest_required_tier(tiers) if tiers else "public_degraded"

    def _status_code_locked(self, current_tier: str, required_tier: str, now: float) -> str:
        if self._approval_required:
            return "weaker_privacy_approval_required"
        if transport_tier_is_sufficient(current_tier, required_tier):
            return "private_lane_ready"
        if self._attempt_count <= 0:
            return "private_lane_unavailable"
        if now < self._cooldown_until:
            return "preparing_private_lane" if self._attempt_count == 1 else "retrying_private_lane"
        if self._attempt_count >= _UNAVAILABLE_AFTER_ATTEMPTS:
            return "private_lane_unavailable"
        return "retrying_private_lane"

    def _snapshot_locked(self, current_tier: str, now: float) -> dict[str, Any]:
        reasons = self._active_reasons_locked()
        required_tier = self._required_tier_locked()
        status_code = self._status_code_locked(current_tier, required_tier, now)
        reason_text = {
            "preparing_private_lane": "The app is preparing the private lane in the background.",
            "private_lane_ready": "The private lane is ready.",
            "retrying_private_lane": "The app is retrying the private lane in the background.",
            "private_lane_unavailable": "The private lane is not ready yet.",
            "weaker_privacy_approval_required": "Sending with weaker privacy needs your approval.",
        }.get(status_code, "The private lane is not ready yet.")
        return {
            "status": private_lane_readiness_status(
                status_code,
                reason_code=self._last_attempt_reason or self._last_reason,
                plain_reason=reason_text,
            ),
            "current_reason": self._last_reason,
            "reasons": reasons,
            "current_tier": current_tier,
            "required_tier": required_tier,
            "last_attempt_reason": self._last_attempt_reason,
            "last_attempt_at": int(self._last_attempt_at) if self._last_attempt_at > 0 else 0,
            "last_ready_at": int(self._last_ready_at) if self._last_ready_at > 0 else 0,
            "cooldown_until": int(self._cooldown_until) if self._cooldown_until > 0 else 0,
            "attempt_count": int(self._attempt_count),
            "suppressed_count": int(self._suppressed_count),
            "labels": dict(PRIVATE_LANE_READINESS_LABELS),
        }

    def observe_state(
        self,
        *,
        current_tier: str | None = None,
        approval_required: bool = False,
        now: float | None = None,
    ) -> dict[str, Any]:
        current = normalize_transport_tier(current_tier or self._get_current_tier())
        current_now = float(now if now is not None else time.time())
        with self._lock:
            self._cleanup_locked(current_now)
            self._approval_required = bool(approval_required)
            if transport_tier_is_sufficient(current, self._required_tier_locked()):
                self._last_ready_at = current_now
                self._attempt_count = 0
                self._cooldown_until = 0.0
            return self._snapshot_locked(current, current_now)

    def request_warmup(
        self,
        *,
        reason: str,
        current_tier: str | None = None,
        required_tier: str | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        normalized_reason = str(reason or "").strip().lower()
        if normalized_reason not in WARMUP_REASON_DEFAULTS:
            raise ValueError(f"unsupported warmup reason: {reason}")
        current_now = float(now if now is not None else time.time())
        current = normalize_transport_tier(current_tier or self._get_current_tier())
        required = normalize_transport_tier(required_tier or WARMUP_REASON_DEFAULTS[normalized_reason])

        with self._lock:
            self._cleanup_locked(current_now)
            self._reason_requests[normalized_reason] = {
                "requested_at": current_now,
                "required_tier": required,
            }
            self._last_reason = normalized_reason
            self._approval_required = False
            if transport_tier_is_sufficient(current, required):
                self._last_ready_at = current_now
                self._attempt_count = 0
                self._cooldown_until = 0.0
                return self._snapshot_locked(current, current_now)
            if current_now < self._cooldown_until:
                self._suppressed_count += 1
                return self._snapshot_locked(current, current_now)

        prewarm = self._request_privacy_prewarm(
            reason=normalized_reason,
            current_tier=current,
            required_tier=required,
            now=current_now,
        )
        if bool(prewarm.get("transport_bootstrap_allowed", True)):
            triggered = self._kickoff_background_bootstrap(reason=normalized_reason)
        else:
            triggered = False

        with self._lock:
            self._last_attempt_reason = normalized_reason
            self._last_attempt_at = current_now
            self._attempt_count += 1
            self._cooldown_until = current_now + _WARMUP_COOLDOWN_S
            if not triggered:
                self._suppressed_count += 1
            return self._snapshot_locked(current, current_now)

    def _get_current_tier(self) -> str:
        try:
            from services.wormhole_supervisor import get_transport_tier

            return get_transport_tier()
        except Exception:
            return "public_degraded"

    def _kickoff_background_bootstrap(self, *, reason: str) -> bool:
        try:
            from services.wormhole_supervisor import kickoff_wormhole_bootstrap

            return bool(kickoff_wormhole_bootstrap(reason=f"private_transport_manager:{reason}"))
        except Exception:
            return False

    def _request_privacy_prewarm(
        self,
        *,
        reason: str,
        current_tier: str,
        required_tier: str,
        now: float,
    ) -> dict[str, Any]:
        try:
            from services.mesh.mesh_privacy_prewarm import privacy_prewarm_service

            return privacy_prewarm_service.request_prewarm(
                reason=reason,
                current_tier=current_tier,
                required_tier=required_tier,
                now=now,
            )
        except Exception:
            return {
                "ok": False,
                "transport_bootstrap_allowed": True,
                "background_prewarm_allowed": False,
            }


private_transport_manager = PrivateTransportManager()


def reset_private_transport_manager_for_tests() -> None:
    private_transport_manager.reset_for_tests()
