from __future__ import annotations

import os
import threading

from services.config import get_settings
from services.mesh.mesh_private_dispatcher import (
    _dm_fallback_reason_from_status,
    _anonymous_dm_hidden_transport_enforced,
    _anonymous_dm_hidden_transport_requested,
    _hidden_relay_transport_effective,
    _maybe_apply_dm_relay_jitter,
    _rns_private_dm_status,
    _rns_private_dm_ready,
    _secure_dm_enabled,
    attempt_private_release,
)
from services.mesh.mesh_privacy_policy import (
    evaluate_network_release,
)
from services.mesh.mesh_private_outbox import private_delivery_outbox
from services.mesh.mesh_private_transport_manager import private_transport_manager

_RELAY_APPROVAL_TRIGGER_REASONS = {
    "dm_release_waiting_for_private_lane",
    "dm_release_waiting_for_private_strong",
    "rns_transport_disabled",
    "rns_peer_unknown",
    "rns_peer_offline",
    "rns_link_down",
    "rns_send_failed_unknown",
}


def _background_threads_enabled() -> bool:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    return True


def _release_approval_enabled() -> bool:
    return bool(get_settings().MESH_PRIVATE_RELEASE_APPROVAL_ENABLE)


def _strong_release_runtime_ready() -> tuple[bool, str]:
    try:
        from services.release_profiles import current_release_profile

        profile = current_release_profile()
    except Exception:
        profile = "dev"
    if profile == "dev":
        return True, "dev_profile"
    try:
        from services.privacy_core_attestation import privacy_core_attestation

        attestation = privacy_core_attestation()
        state = str(attestation.get("attestation_state", "") or "").strip()
    except Exception:
        state = "attestation_stale_or_unknown"
    if state == "attested_current":
        return True, state
    return False, state or "attestation_stale_or_unknown"


class PrivateReleaseWorker:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._wake_event = threading.Event()
        self._stop_event = threading.Event()

    def ensure_started(self) -> bool:
        if not _background_threads_enabled():
            return False
        with self._lock:
            if self._thread and self._thread.is_alive():
                return True
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._loop, daemon=True, name="private-release-worker")
            self._thread.start()
            return True

    def wake(self) -> None:
        self._wake_event.set()

    def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=1.0)

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            self.run_once()
            self._wake_event.wait(timeout=2.0)
            self._wake_event.clear()

    def run_once(self) -> None:
        from services.wormhole_supervisor import get_transport_tier

        current_tier = get_transport_tier()
        for item in private_delivery_outbox.pending_items():
            lane = str(item.get("lane", "") or "")
            item_id = str(item.get("id", "") or "")
            decision = evaluate_network_release(lane, current_tier)
            if not decision.allowed:
                private_delivery_outbox.mark_queued(
                    item_id,
                    current_tier=current_tier,
                    status_code=decision.status_code,
                    reason_code=decision.reason_code,
                    plain_reason=decision.plain_reason,
                    error=str(item.get("last_error", "") or ""),
                )
                if (
                    lane == "dm"
                    and _release_approval_enabled()
                    and decision.reason_code in _RELAY_APPROVAL_TRIGGER_REASONS
                ):
                    private_delivery_outbox.note_release_revalidation_failure(
                        item_id,
                        reason_code=decision.reason_code,
                    )
                else:
                    private_delivery_outbox.clear_release_session_state(item_id)
                if decision.should_bootstrap:
                    self._request_warmup_for_lane(lane, current_tier=current_tier)
                continue
            if (
                lane == "dm"
                and _anonymous_dm_hidden_transport_requested()
                and not _anonymous_dm_hidden_transport_enforced()
            ):
                private_delivery_outbox.mark_queued(
                    item_id,
                    current_tier=current_tier,
                    status_code="preparing_private_lane",
                    reason_code="anonymous_mode_waiting_for_hidden_transport",
                    plain_reason="The sealed message is waiting for an anonymous route.",
                    error="",
                )
                private_delivery_outbox.clear_release_session_state(item_id)
                self._request_warmup_for_lane(lane, current_tier=current_tier)
                continue
            if lane == "dm" and self._dm_release_approval_pending(item_id, item):
                private_delivery_outbox.mark_queued(
                    item_id,
                    current_tier=current_tier,
                    status_code="queued_private_delivery",
                    reason_code="dm_release_retry_pending_private_lane",
                    plain_reason="The sealed message remains queued while the app keeps trying more private routing.",
                    error=str(item.get("last_error", "") or ""),
                )
                self._request_warmup_for_lane(lane, current_tier=current_tier)
                continue
            runtime_ready, runtime_state = _strong_release_runtime_ready()
            if not runtime_ready:
                private_delivery_outbox.mark_queued(
                    item_id,
                    current_tier=current_tier,
                    status_code="queued_private_delivery",
                    reason_code="privacy_core_attestation_not_current",
                    plain_reason=(
                        "The sealed message is waiting for secure runtime attestation before private release."
                    ),
                    error=str(runtime_state or "privacy_core_attestation_not_current"),
                )
                continue
            private_delivery_outbox.mark_releasing(item_id, current_tier=current_tier)
            try:
                result = attempt_private_release(
                    lane=lane,
                    payload=dict(item.get("payload") or {}),
                    current_tier=current_tier,
                    secure_dm_enabled=_secure_dm_enabled,
                    rns_private_dm_ready=_rns_private_dm_ready,
                    anonymous_dm_hidden_transport_enforced=_anonymous_dm_hidden_transport_enforced,
                    anonymous_dm_hidden_transport_requested=_anonymous_dm_hidden_transport_requested,
                    relay_hidden_transport_effective=_hidden_relay_transport_effective,
                    apply_dm_relay_jitter=_maybe_apply_dm_relay_jitter,
                    relay_consent_granted=self._relay_consent_granted(item_id, item),
                    relay_consent_explicit=self._relay_consent_explicit(item_id, item),
                )
            except Exception as exc:
                result = {"ok": False, "detail": str(exc) or type(exc).__name__}
            if result.get("ok"):
                delivered = private_delivery_outbox.mark_delivered(item_id, current_tier=current_tier, result=result)
                if delivered is not None and lane == "dm":
                    self._commit_dm_alias_rotation_if_present(dict(item.get("payload") or {}))
                private_delivery_outbox.clear_release_session_state(item_id)
            else:
                fallback_reason = str(result.get("fallback_reason", "") or "").strip()
                if (
                    lane == "dm"
                    and _release_approval_enabled()
                    and fallback_reason in _RELAY_APPROVAL_TRIGGER_REASONS
                ):
                    private_delivery_outbox.note_release_revalidation_failure(
                        item_id,
                        reason_code=fallback_reason,
                    )
                refreshed_tier = get_transport_tier()
                retry = evaluate_network_release(lane, refreshed_tier)
                private_delivery_outbox.mark_queued(
                    item_id,
                    current_tier=refreshed_tier,
                    status_code=retry.status_code if not retry.allowed else "queued_private_delivery",
                    reason_code=retry.reason_code if not retry.allowed else f"{lane}_release_retry",
                    plain_reason=retry.plain_reason if not retry.allowed else "The sealed message remains queued for another private delivery attempt.",
                    error=str(result.get("detail", "") or "private release failed"),
                )
                if retry.should_bootstrap:
                    self._request_warmup_for_lane(lane, current_tier=refreshed_tier)

    def _current_release_profile(self) -> str:
        try:
            from services.release_profiles import current_release_profile

            return str(current_release_profile() or "dev")
        except Exception:
            return "dev"

    def _commit_dm_alias_rotation_if_present(self, payload: dict) -> bool:
        try:
            from services.mesh.mesh_wormhole_dead_drop import commit_outbound_alias_rotation_if_present

            return bool(
                commit_outbound_alias_rotation_if_present(
                    peer_id=str(payload.get("recipient_id", "") or ""),
                    payload_format=str(payload.get("format", "mls1") or "mls1"),
                    ciphertext=str(payload.get("ciphertext", "") or ""),
                )
            )
        except Exception:
            return False

    def _scoped_relay_policy_granted(self, item: dict) -> bool:
        payload = dict(item.get("payload") or {})
        recipient_id = str(payload.get("recipient_id", "") or "").strip()
        if not recipient_id:
            return False
        try:
            from services.mesh.mesh_relay_policy import relay_policy_grants_dm

            decision = relay_policy_grants_dm(
                recipient_id=recipient_id,
                profile=self._current_release_profile(),
                hidden_transport_effective=_hidden_relay_transport_effective(),
            )
            return bool(decision.get("granted", False))
        except Exception:
            return False

    def _relay_consent_granted(self, item_id: str, item: dict | None = None) -> bool:
        if not _release_approval_enabled():
            return True
        state = private_delivery_outbox.release_approval_state(item_id)
        if bool(state.get("approved", False)):
            return True
        return self._scoped_relay_policy_granted(dict(item or {}))

    def _relay_consent_explicit(self, item_id: str, item: dict | None = None) -> bool:
        if not _release_approval_enabled():
            return False
        state = private_delivery_outbox.release_approval_state(item_id)
        if bool(state.get("approved", False)):
            return True
        return self._scoped_relay_policy_granted(dict(item or {}))

    def _dm_release_approval_pending(self, item_id: str, item: dict | None = None) -> bool:
        if not _release_approval_enabled():
            private_delivery_outbox.clear_release_session_state(item_id)
            return False
        if not _secure_dm_enabled():
            private_delivery_outbox.clear_release_session_state(item_id)
            return False
        if _anonymous_dm_hidden_transport_requested():
            private_delivery_outbox.clear_release_session_state(item_id)
            return False
        if _anonymous_dm_hidden_transport_enforced():
            private_delivery_outbox.clear_release_session_state(item_id)
            return False
        if _rns_private_dm_ready():
            private_delivery_outbox.clear_release_session_state(item_id)
            return False
        if self._scoped_relay_policy_granted(dict(item or {})):
            private_delivery_outbox.clear_release_session_state(item_id)
            return False
        fallback_reason = _dm_fallback_reason_from_status(
            direct_attempted=False,
            rns_status=_rns_private_dm_status(False),
        )
        state = private_delivery_outbox.note_release_revalidation_failure(
            item_id,
            reason_code=str(fallback_reason.value),
        )
        return not bool(state.get("approved", False))

    def _request_warmup_for_lane(self, lane: str, *, current_tier: str) -> None:
        normalized_lane = str(lane or "").strip().lower()
        if normalized_lane == "dm":
            reason = "queued_dm_delivery"
        elif normalized_lane == "gate":
            reason = "queued_gate_delivery"
        else:
            return
        private_transport_manager.request_warmup(
            reason=reason,
            current_tier=current_tier,
        )

    def reset_for_tests(self) -> None:
        self.stop()
        with self._lock:
            self._thread = None
            self._wake_event = threading.Event()
            self._stop_event = threading.Event()


private_release_worker = PrivateReleaseWorker()


def reset_private_release_worker_for_tests() -> None:
    private_release_worker.reset_for_tests()
