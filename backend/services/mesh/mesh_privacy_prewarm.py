from __future__ import annotations

import os
import threading
import time
from typing import Any

from services.config import get_settings
from services.mesh.mesh_privacy_policy import normalize_transport_tier

_HIDDEN_TRANSPORTS = {"tor", "tor_arti", "i2p", "mixnet"}
_ANON_USER_ACTION_REASONS = {
    "queued_dm_delivery",
    "queued_gate_delivery",
    "dm_surface_open",
    "gate_surface_open",
    "invite_bootstrap",
}
_ANON_CADENCE_REASONS = {"startup_resume", "status_resume", "scheduled_prewarm"}


def _now() -> float:
    return float(time.time())


def _background_threads_enabled() -> bool:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    return True


def _current_transport_tier() -> str:
    try:
        from services.wormhole_supervisor import get_transport_tier

        return normalize_transport_tier(get_transport_tier())
    except Exception:
        return "public_degraded"


def _privacy_mode() -> str:
    try:
        from services.wormhole_settings import read_wormhole_settings

        settings = read_wormhole_settings()
    except Exception:
        settings = {}
    if bool(settings.get("anonymous_mode", False)):
        return "anonymous"
    profile = str(settings.get("privacy_profile", "default") or "default").strip().lower()
    if profile in {"high", "private", "strong"}:
        return "private"
    return "normal"


def _hidden_transport_ready() -> bool:
    try:
        from services.wormhole_settings import read_wormhole_settings
        from services.wormhole_status import read_wormhole_status

        settings = read_wormhole_settings()
        status = read_wormhole_status()
        active = str(
            status.get("transport_active", "") or settings.get("transport", "direct") or "direct"
        ).strip().lower()
        return bool(status.get("running")) and bool(status.get("ready")) and active in _HIDDEN_TRANSPORTS
    except Exception:
        return False


def _kickoff_hidden_transport(reason: str) -> dict[str, Any]:
    try:
        from services.wormhole_supervisor import kickoff_wormhole_bootstrap

        triggered = bool(kickoff_wormhole_bootstrap(reason=f"privacy_prewarm:{reason}"))
        return {"ok": True, "triggered": triggered}
    except Exception as exc:
        return {"ok": False, "detail": str(exc) or type(exc).__name__}


def _register_prekeys() -> dict[str, Any]:
    try:
        from services.mesh.mesh_wormhole_prekey import register_wormhole_prekey_bundle

        result = register_wormhole_prekey_bundle()
        return {"ok": bool(result.get("ok", False)), "detail": dict(result or {})}
    except Exception as exc:
        return {"ok": False, "detail": str(exc) or type(exc).__name__}


def _rotate_lookup_handles() -> dict[str, Any]:
    try:
        from services.mesh.mesh_wormhole_identity import maybe_rotate_prekey_lookup_handles

        return dict(maybe_rotate_prekey_lookup_handles() or {})
    except Exception as exc:
        return {"ok": False, "detail": str(exc) or type(exc).__name__}


def _prepare_gate_personas() -> dict[str, Any]:
    try:
        from services.mesh.mesh_wormhole_persona import bootstrap_wormhole_persona_state

        bootstrap_wormhole_persona_state()
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "detail": str(exc) or type(exc).__name__}


def _probe_rns_readiness() -> dict[str, Any]:
    try:
        from services.mesh.mesh_rns import rns_bridge

        status_reader = getattr(rns_bridge, "status", None)
        status = dict(status_reader() or {}) if callable(status_reader) else {}
        enabled_reader = getattr(rns_bridge, "enabled", None)
        enabled = bool(enabled_reader()) if callable(enabled_reader) else bool(status.get("enabled", False))
        return {
            "ok": True,
            "enabled": enabled,
            "ready": bool(status.get("ready", enabled)),
            "private_dm_direct_ready": bool(status.get("private_dm_direct_ready", False)),
        }
    except Exception as exc:
        return {"ok": False, "detail": str(exc) or type(exc).__name__}


def _outbox_capacity_snapshot() -> dict[str, Any]:
    try:
        from services.mesh.mesh_private_outbox import private_delivery_outbox

        pending = private_delivery_outbox.pending_items()
        return {"ok": True, "pending_count": len(pending)}
    except Exception as exc:
        return {"ok": False, "detail": str(exc) or type(exc).__name__}


class PrivacyPrewarmService:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.reset_for_tests()

    def reset_for_tests(self) -> None:
        with self._lock:
            previous_stop = getattr(self, "_stop_event", None)
            if previous_stop is not None:
                previous_stop.set()
            self._thread: threading.Thread | None = None
            self._scheduler_thread: threading.Thread | None = None
            self._stop_event = threading.Event()
            self._last_request: dict[str, Any] = {}
            self._last_result: dict[str, Any] = {}
            self._last_scheduled_result: dict[str, Any] = {}
            self._next_anonymous_prewarm_at = 0.0
            self._request_count = 0
            self._scheduled_count = 0
            self._suppressed_user_action_count = 0

    def _enabled(self) -> bool:
        try:
            return bool(get_settings().MESH_PRIVACY_PREWARM_ENABLE)
        except Exception:
            return True

    def _anonymous_cadence_s(self) -> int:
        try:
            return max(30, int(get_settings().MESH_PRIVACY_PREWARM_ANON_CADENCE_S or 300))
        except Exception:
            return 300

    def _interval_s(self) -> int:
        try:
            return max(30, int(get_settings().MESH_PRIVACY_PREWARM_INTERVAL_S or 300))
        except Exception:
            return 300

    def _policy_for_request(self, *, reason: str, now: float) -> dict[str, Any]:
        mode = _privacy_mode()
        cadence_due = now >= self._next_anonymous_prewarm_at
        transport_allowed = True
        background_allowed = True
        if mode == "anonymous":
            if reason in _ANON_USER_ACTION_REASONS:
                transport_allowed = False
                background_allowed = False
                if self._next_anonymous_prewarm_at <= 0:
                    self._next_anonymous_prewarm_at = now + self._anonymous_cadence_s()
            elif reason in _ANON_CADENCE_REASONS and cadence_due:
                self._next_anonymous_prewarm_at = now + self._anonymous_cadence_s()
            elif reason in _ANON_CADENCE_REASONS:
                transport_allowed = False
                background_allowed = False
            elif reason not in _ANON_CADENCE_REASONS:
                transport_allowed = False
                background_allowed = False
        return {
            "mode": mode,
            "transport_bootstrap_allowed": transport_allowed,
            "background_prewarm_allowed": background_allowed,
            "anonymous_cadence_due": bool(cadence_due),
            "next_anonymous_prewarm_at": int(self._next_anonymous_prewarm_at),
        }

    def request_prewarm(
        self,
        *,
        reason: str,
        current_tier: str,
        required_tier: str,
        now: float | None = None,
        allow_background_thread: bool = True,
    ) -> dict[str, Any]:
        normalized_reason = str(reason or "").strip().lower()
        current = normalize_transport_tier(current_tier or "public_degraded")
        required = normalize_transport_tier(required_tier or "private_control_only")
        current_now = float(now if now is not None else _now())
        with self._lock:
            self._request_count += 1
            policy = self._policy_for_request(reason=normalized_reason, now=current_now)
            if not bool(policy.get("background_prewarm_allowed", True)):
                self._suppressed_user_action_count += 1
            snapshot = {
                "ok": True,
                "reason": normalized_reason,
                "current_tier": current,
                "required_tier": required,
                "hidden_transport_ready": _hidden_transport_ready(),
                "request_count": self._request_count,
                "suppressed_user_action_count": self._suppressed_user_action_count,
                **policy,
            }
            self._last_request = dict(snapshot)
        if (
            self._enabled()
            and bool(snapshot.get("background_prewarm_allowed", True))
            and _background_threads_enabled()
            and bool(allow_background_thread)
        ):
            self._start_background(reason=normalized_reason, current_tier=current, required_tier=required)
            snapshot["background_started"] = True
        else:
            snapshot["background_started"] = False
        return snapshot

    def ensure_started(self) -> bool:
        if not self._enabled() or not _background_threads_enabled():
            return False
        with self._lock:
            if self._scheduler_thread and self._scheduler_thread.is_alive():
                return True
            self._stop_event.clear()
            self._scheduler_thread = threading.Thread(
                target=self._scheduler_loop,
                daemon=True,
                name="privacy-prewarm-scheduler",
            )
            self._scheduler_thread.start()
            return True

    def stop(self) -> None:
        with self._lock:
            self._stop_event.set()
            thread = self._scheduler_thread
        if thread and thread.is_alive():
            thread.join(timeout=1.0)

    def _scheduled_required_tier(self) -> str:
        mode = _privacy_mode()
        if mode in {"anonymous", "private"}:
            return "private_strong"
        return "private_control_only"

    def _scheduler_loop(self) -> None:
        while not self._stop_event.is_set():
            self.run_scheduled_once(reason="scheduled_prewarm")
            self._stop_event.wait(timeout=float(self._interval_s()))

    def run_scheduled_once(
        self,
        *,
        reason: str = "scheduled_prewarm",
        now: float | None = None,
    ) -> dict[str, Any]:
        normalized_reason = str(reason or "scheduled_prewarm").strip().lower()
        current = _current_transport_tier()
        required = self._scheduled_required_tier()
        request = self.request_prewarm(
            reason=normalized_reason,
            current_tier=current,
            required_tier=required,
            now=now,
            allow_background_thread=False,
        )
        if not bool(request.get("transport_bootstrap_allowed", True)):
            result = {
                "ok": True,
                "skipped": True,
                "reason": normalized_reason,
                "mode": str(request.get("mode", "") or ""),
                "detail": "scheduled prewarm deferred until cadence",
                "next_anonymous_prewarm_at": int(request.get("next_anonymous_prewarm_at", 0) or 0),
            }
        else:
            result = self.run_once(
                reason=normalized_reason,
                current_tier=current,
                required_tier=required,
                include_transport=True,
            )
            result["skipped"] = False
        with self._lock:
            self._scheduled_count += 1
            self._last_scheduled_result = dict(result)
        return result

    def _start_background(self, *, reason: str, current_tier: str, required_tier: str) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self.run_once,
                kwargs={
                    "reason": reason,
                    "current_tier": current_tier,
                    "required_tier": required_tier,
                    "include_transport": False,
                },
                daemon=True,
                name="privacy-prewarm-worker",
            )
            self._thread.start()

    def run_once(
        self,
        *,
        reason: str,
        current_tier: str = "public_degraded",
        required_tier: str = "private_control_only",
        include_transport: bool = True,
    ) -> dict[str, Any]:
        normalized_reason = str(reason or "").strip().lower()
        results: list[dict[str, Any]] = []
        if include_transport:
            results.append(
                {
                    "task": "hidden_transport_warmup",
                    **_kickoff_hidden_transport(normalized_reason),
                }
            )
        results.extend(
            [
                {"task": "dm_prekey_bundle", **_register_prekeys()},
                {"task": "prekey_lookup_rotation", **_rotate_lookup_handles()},
                {"task": "gate_persona_state", **_prepare_gate_personas()},
                {"task": "rns_readiness_probe", **_probe_rns_readiness()},
                {"task": "outbox_capacity", **_outbox_capacity_snapshot()},
            ]
        )
        result = {
            "ok": all(bool(item.get("ok", False)) for item in results if item.get("task") != "rns_readiness_probe"),
            "reason": normalized_reason,
            "mode": _privacy_mode(),
            "current_tier": normalize_transport_tier(current_tier),
            "required_tier": normalize_transport_tier(required_tier),
            "tasks": results,
        }
        with self._lock:
            self._last_result = dict(result)
        return result

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "last_request": dict(self._last_request),
                "last_result": dict(self._last_result),
                "last_scheduled_result": dict(self._last_scheduled_result),
                "next_anonymous_prewarm_at": int(self._next_anonymous_prewarm_at),
                "request_count": self._request_count,
                "scheduled_count": self._scheduled_count,
                "suppressed_user_action_count": self._suppressed_user_action_count,
            }


privacy_prewarm_service = PrivacyPrewarmService()


def reset_privacy_prewarm_for_tests() -> None:
    privacy_prewarm_service.reset_for_tests()
