"""Typed shutdown appeal — pauses execution timer, anti-stall bounded.

Source of truth: ``infonet-economy/RULES_SKELETON.md`` §5.5 step 7.

An appeal pauses the 7-day shutdown execution timer. The
"anti-stall" property limits abuse:

- One appeal per shutdown petition (no infinite re-appeals).
- 48-hour filing window after the shutdown vote passes.
- If the appeal fails, the original shutdown's execution timer
  resumes from where it was paused — the shutdown still happens,
  just delayed by the appeal-vote duration.

This module exposes:

- ``validate_appeal_filing`` — pre-emit checks.
- ``paused_execution_remaining_sec`` — compute how much time was
  remaining on the shutdown timer when the appeal was filed (so the
  resolver can resume the timer from that point).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from services.infonet.config import CONFIG
from services.infonet.gates.shutdown.shutdown import compute_shutdown_state
from services.infonet.gates.state import get_gate_meta


_SECONDS_PER_HOUR = 3600.0
_SECONDS_PER_DAY = 86400.0


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    p = event.get("payload")
    return p if isinstance(p, dict) else {}


@dataclass(frozen=True)
class AppealValidation:
    accepted: bool
    reason: str


def _shutdown_petition_filed_at(
    target_petition_id: str,
    chain: Iterable[dict[str, Any]],
) -> float | None:
    for ev in chain:
        if not isinstance(ev, dict):
            continue
        if ev.get("event_type") != "gate_shutdown_file":
            continue
        if _payload(ev).get("petition_id") == target_petition_id:
            return float(ev.get("timestamp") or 0.0)
    return None


def _shutdown_vote_passed_at(
    target_petition_id: str,
    chain: Iterable[dict[str, Any]],
) -> float | None:
    """Return the timestamp of the ``gate_shutdown_vote`` event whose
    payload says ``vote=="passed"`` for the target petition. The
    appeal window starts here."""
    for ev in chain:
        if not isinstance(ev, dict):
            continue
        if ev.get("event_type") != "gate_shutdown_vote":
            continue
        p = _payload(ev)
        if p.get("petition_id") != target_petition_id:
            continue
        if p.get("vote") == "passed":
            return float(ev.get("timestamp") or 0.0)
    return None


def _has_appeal(
    target_petition_id: str,
    chain: Iterable[dict[str, Any]],
) -> bool:
    for ev in chain:
        if not isinstance(ev, dict):
            continue
        if ev.get("event_type") != "gate_shutdown_appeal_file":
            continue
        if _payload(ev).get("target_petition_id") == target_petition_id:
            return True
    return False


def validate_appeal_filing(
    gate_id: str,
    target_petition_id: str,
    filer_id: str,
    *,
    reason: str,
    evidence_hashes: list[str],
    chain: Iterable[dict[str, Any]],
    now: float,
    filer_cooldown_until: float | None = None,
) -> AppealValidation:
    """Pre-emit validation for ``gate_shutdown_appeal_file``.

    Rejects if:
    - Reason or evidence missing.
    - Gate doesn't exist.
    - Target shutdown petition doesn't exist.
    - Target petition is not currently in "executing" status (i.e.
      vote hasn't passed yet, or shutdown already executed).
    - 48-hour filing window has elapsed since vote passage.
    - Target petition already has an appeal (one per shutdown).
    - Filer cooldown active.
    """
    chain_list = list(chain)
    if not isinstance(reason, str) or not reason.strip():
        return AppealValidation(False, "reason_empty")
    if not isinstance(evidence_hashes, list) or not evidence_hashes:
        return AppealValidation(False, "evidence_required")
    if get_gate_meta(gate_id, chain_list) is None:
        return AppealValidation(False, "gate_not_found")

    if not _shutdown_petition_filed_at(target_petition_id, chain_list):
        return AppealValidation(False, "target_petition_not_found")

    # The "already-filed" check fires before the status check on
    # purpose — once an appeal is filed, the petition status flips
    # from "executing" to "appealed", and surfacing that as
    # "target_not_in_executing_state" would mislead a second filer
    # about *why* their appeal was refused. Spec invariant: one
    # appeal per shutdown; surface that directly.
    if _has_appeal(target_petition_id, chain_list):
        return AppealValidation(False, "appeal_already_filed")

    state = compute_shutdown_state(gate_id, chain_list, now=now)
    if state.pending_status not in ("executing",):
        return AppealValidation(False, "target_not_in_executing_state")

    vote_passed = _shutdown_vote_passed_at(target_petition_id, chain_list)
    if vote_passed is None:
        return AppealValidation(False, "vote_not_passed")
    window_s = float(CONFIG["gate_shutdown_appeal_window_hours"]) * _SECONDS_PER_HOUR
    if now > vote_passed + window_s:
        return AppealValidation(False, "appeal_window_expired")

    if filer_cooldown_until is not None and filer_cooldown_until > now:
        return AppealValidation(False, "filer_cooldown_active")
    # filer_id is consumed by the producer event payload, not by validation here.
    del filer_id
    return AppealValidation(True, "ok")


def paused_execution_remaining_sec(
    target_petition_id: str,
    chain: Iterable[dict[str, Any]],
    *,
    appeal_filed_at: float,
) -> float:
    """Compute how much time was remaining on the shutdown's
    execution timer when the appeal was filed.

    The original shutdown's ``execution_at`` was
    ``vote_passed_at + execution_delay_days * 86400``. The remaining
    time at appeal-filing time is ``execution_at - appeal_filed_at``,
    clamped to ≥ 0.

    The producer of the ``gate_shutdown_appeal_resolve`` event with
    ``outcome="resumed"`` should attach
    ``resumed_execution_at = now + this_value`` so the timer resumes
    from where it paused.
    """
    chain_list = list(chain)
    vote_passed = _shutdown_vote_passed_at(target_petition_id, chain_list)
    if vote_passed is None:
        return 0.0
    delay_s = float(CONFIG["gate_shutdown_execution_delay_days"]) * _SECONDS_PER_DAY
    execution_at = vote_passed + delay_s
    remaining = execution_at - float(appeal_filed_at)
    return max(0.0, remaining)


__all__ = [
    "AppealValidation",
    "paused_execution_remaining_sec",
    "validate_appeal_filing",
]
