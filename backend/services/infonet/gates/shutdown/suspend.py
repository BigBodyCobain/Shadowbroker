"""Tier 1: 30-day reversible suspend.

Source of truth: ``infonet-economy/RULES_SKELETON.md`` §5.5 steps 1-4.

State derivation:

- A gate is "suspended" iff:
  - the most recent ``gate_suspend_execute`` event is more recent
    than any ``gate_unsuspend`` or ``gate_shutdown_execute`` event,
  - AND the suspended_until window has not yet elapsed.
- ``compute_suspension_state`` returns the current suspension status
  including the auto-unsuspend timestamp.
- ``validate_suspend_filing`` is the pre-emit check the UI should use
  before letting a node sign a ``gate_suspend_file`` event.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from services.infonet.config import CONFIG
from services.infonet.gates.state import events_for_gate, get_gate_meta


_SECONDS_PER_DAY = 86400.0


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    p = event.get("payload")
    return p if isinstance(p, dict) else {}


@dataclass(frozen=True)
class SuspensionState:
    """``status`` is one of ``"active"``, ``"suspended"``,
    ``"shutdown"``. ``suspended_until`` is the auto-unsuspend
    timestamp or ``None`` when not currently suspended."""
    status: str
    suspended_at: float | None
    suspended_until: float | None
    last_shutdown_petition_at: float | None
    """Used for 90-day cooldown checks on subsequent shutdown petitions."""


def compute_suspension_state(
    gate_id: str,
    chain: Iterable[dict[str, Any]],
    *,
    now: float,
) -> SuspensionState:
    chain_list = list(chain)
    events = events_for_gate(gate_id, chain_list)

    last_shutdown_filed_ts: float | None = None
    last_shutdown_executed_ts: float | None = None
    suspended_at: float | None = None
    last_unsuspend_ts: float | None = None

    for ev in events:
        et = ev.get("event_type")
        ts = float(ev.get("timestamp") or 0.0)
        if et == "gate_suspend_execute":
            suspended_at = ts
        elif et == "gate_unsuspend":
            last_unsuspend_ts = ts
        elif et == "gate_shutdown_file":
            last_shutdown_filed_ts = ts
        elif et == "gate_shutdown_execute":
            last_shutdown_executed_ts = ts

    if last_shutdown_executed_ts is not None:
        return SuspensionState(
            status="shutdown",
            suspended_at=suspended_at,
            suspended_until=None,
            last_shutdown_petition_at=last_shutdown_filed_ts,
        )

    if suspended_at is None:
        return SuspensionState(
            status="active",
            suspended_at=None,
            suspended_until=None,
            last_shutdown_petition_at=last_shutdown_filed_ts,
        )

    if last_unsuspend_ts is not None and last_unsuspend_ts > suspended_at:
        return SuspensionState(
            status="active",
            suspended_at=None,
            suspended_until=None,
            last_shutdown_petition_at=last_shutdown_filed_ts,
        )

    duration = float(CONFIG["gate_suspend_duration_days"]) * _SECONDS_PER_DAY
    suspended_until = suspended_at + duration

    if now >= suspended_until:
        # Window auto-elapsed; even without an explicit gate_unsuspend
        # event, the gate is logically active again.
        return SuspensionState(
            status="active",
            suspended_at=None,
            suspended_until=None,
            last_shutdown_petition_at=last_shutdown_filed_ts,
        )

    return SuspensionState(
        status="suspended",
        suspended_at=suspended_at,
        suspended_until=suspended_until,
        last_shutdown_petition_at=last_shutdown_filed_ts,
    )


@dataclass(frozen=True)
class FilingValidation:
    accepted: bool
    reason: str


def validate_suspend_filing(
    gate_id: str,
    filer_id: str,
    *,
    reason: str,
    evidence_hashes: list[str],
    chain: Iterable[dict[str, Any]],
    now: float,
    filer_cooldown_until: float | None = None,
) -> FilingValidation:
    """Pre-emit validation for a ``gate_suspend_file`` event.

    Rejects if:
    - Reason is empty.
    - No evidence hashes.
    - Gate doesn't exist.
    - Gate is already suspended or shut down.
    - Filer's cooldown is still active.
    - Gate's 90-day shutdown-petition cooldown is active.
    """
    chain_list = list(chain)
    if not isinstance(reason, str) or not reason.strip():
        return FilingValidation(False, "reason_empty")
    if not isinstance(evidence_hashes, list) or not evidence_hashes:
        return FilingValidation(False, "evidence_required")
    if not all(isinstance(h, str) and h for h in evidence_hashes):
        return FilingValidation(False, "evidence_hashes_invalid")
    if get_gate_meta(gate_id, chain_list) is None:
        return FilingValidation(False, "gate_not_found")
    state = compute_suspension_state(gate_id, chain_list, now=now)
    if state.status == "shutdown":
        return FilingValidation(False, "gate_shutdown")
    if state.status == "suspended":
        return FilingValidation(False, "already_suspended")
    if filer_cooldown_until is not None and filer_cooldown_until > now:
        return FilingValidation(False, "filer_cooldown_active")
    if state.last_shutdown_petition_at is not None:
        cooldown_s = float(CONFIG["gate_shutdown_cooldown_days"]) * _SECONDS_PER_DAY
        if now < state.last_shutdown_petition_at + cooldown_s:
            return FilingValidation(False, "gate_cooldown_active")
    _ = filer_id  # producer logs filer separately; not consulted for validation here.
    return FilingValidation(True, "ok")


__all__ = [
    "FilingValidation",
    "SuspensionState",
    "compute_suspension_state",
    "validate_suspend_filing",
]
