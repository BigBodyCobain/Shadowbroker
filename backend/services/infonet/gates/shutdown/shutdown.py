"""Tier 2: 7-day-delayed shutdown.

Source of truth: ``infonet-economy/RULES_SKELETON.md`` §5.5 steps 5-8.

PREREQUISITE: gate must currently be suspended. The shutdown petition
itself is a vote among oracle-rep holders. If it passes, a 7-day
execution delay opens (the appeal window). After the delay (and any
appeal resolution), the ``gate_shutdown_execute`` event archives the
gate permanently.

State derivation:

- A shutdown petition can be: ``filed``, ``vote_passed``, ``executing``
  (after vote, during 7-day delay), ``appealed`` (timer paused),
  ``executed``, ``failed``, ``voided_appeal``.
- This module computes the petition status from chain events; it does
  NOT execute the petition itself (the producer emits
  ``gate_shutdown_execute`` based on this status).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from services.infonet.config import CONFIG
from services.infonet.gates.shutdown.suspend import (
    FilingValidation,
    compute_suspension_state,
)
from services.infonet.gates.state import events_for_gate, get_gate_meta


_SECONDS_PER_DAY = 86400.0


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    p = event.get("payload")
    return p if isinstance(p, dict) else {}


@dataclass(frozen=True)
class ShutdownState:
    """Derived snapshot of all shutdown petitions filed against a gate."""
    has_pending: bool
    pending_petition_id: str | None
    pending_status: str | None  # "filed" | "vote_passed" | "executing" | "appealed" | "failed"
    execution_at: float | None
    executed: bool


def compute_shutdown_state(
    gate_id: str,
    chain: Iterable[dict[str, Any]],
    *,
    now: float,
) -> ShutdownState:
    chain_list = list(chain)
    events = events_for_gate(gate_id, chain_list)

    petitions: dict[str, dict[str, Any]] = {}
    for ev in events:
        et = ev.get("event_type")
        if et != "gate_shutdown_file":
            continue
        p = _payload(ev)
        pid = p.get("petition_id")
        if not isinstance(pid, str) or not pid:
            continue
        petitions[pid] = {
            "filed_at": float(ev.get("timestamp") or 0.0),
            "status": "filed",
            "execution_at": None,
            "appealed": False,
        }

    # Walk votes/executions/appeals in chain order.
    chain_all = [e for e in chain_list if isinstance(e, dict)]
    chain_all.sort(key=lambda e: (float(e.get("timestamp") or 0.0), int(e.get("sequence") or 0)))

    for ev in chain_all:
        et = ev.get("event_type")
        if et not in ("gate_shutdown_vote", "gate_shutdown_execute",
                      "gate_shutdown_appeal_file", "gate_shutdown_appeal_resolve"):
            continue
        p = _payload(ev)

        if et == "gate_shutdown_vote":
            pid = p.get("petition_id")
            if not isinstance(pid, str) or pid not in petitions:
                continue
            # Sprint 6 simplification: a vote event with payload
            # {"vote": "passed"} is treated as the canonical pass
            # signal. Real production may aggregate per-voter votes
            # in Sprint 7's governance DSL — Sprint 6 honors whichever
            # outcome the spec-side vote tally already reached.
            outcome = p.get("vote")
            if outcome == "passed":
                petitions[pid]["status"] = "executing"
                delay_s = float(CONFIG["gate_shutdown_execution_delay_days"]) * _SECONDS_PER_DAY
                petitions[pid]["execution_at"] = float(ev.get("timestamp") or 0.0) + delay_s
            elif outcome == "failed":
                petitions[pid]["status"] = "failed"

        elif et == "gate_shutdown_appeal_file":
            target = p.get("target_petition_id")
            if isinstance(target, str) and target in petitions:
                petitions[target]["appealed"] = True
                petitions[target]["status"] = "appealed"
                petitions[target]["execution_at"] = None  # paused

        elif et == "gate_shutdown_appeal_resolve":
            target = p.get("target_petition_id")
            outcome = p.get("outcome")
            if isinstance(target, str) and target in petitions:
                if outcome == "voided_shutdown":
                    petitions[target]["status"] = "voided_appeal"
                elif outcome == "resumed":
                    petitions[target]["status"] = "executing"
                    # execution_at restored by the producer who emitted
                    # the resolve event with a fresh execution_at field.
                    new_exec = p.get("resumed_execution_at")
                    try:
                        petitions[target]["execution_at"] = float(new_exec)
                    except (TypeError, ValueError):
                        petitions[target]["execution_at"] = None

        elif et == "gate_shutdown_execute":
            pid = p.get("petition_id")
            if isinstance(pid, str) and pid in petitions:
                petitions[pid]["status"] = "executed"

    executed = any(p["status"] == "executed" for p in petitions.values())
    pending_pid = None
    pending = None
    for pid, p in petitions.items():
        if p["status"] in ("filed", "executing", "appealed"):
            pending_pid = pid
            pending = p
            break

    return ShutdownState(
        has_pending=pending is not None,
        pending_petition_id=pending_pid,
        pending_status=pending["status"] if pending else None,
        execution_at=pending["execution_at"] if pending else None,
        executed=executed,
    )


def validate_shutdown_filing(
    gate_id: str,
    filer_id: str,
    *,
    reason: str,
    evidence_hashes: list[str],
    chain: Iterable[dict[str, Any]],
    now: float,
    filer_cooldown_until: float | None = None,
) -> FilingValidation:
    """Pre-emit validation for ``gate_shutdown_file``.

    Critical Sprint 6 invariant: shutdown filings REQUIRE the gate to
    currently be suspended. This is the spec's two-tier escalation
    safeguard — a gate cannot be shut down without first surviving a
    suspension period.
    """
    chain_list = list(chain)
    if not isinstance(reason, str) or not reason.strip():
        return FilingValidation(False, "reason_empty")
    if not isinstance(evidence_hashes, list) or not evidence_hashes:
        return FilingValidation(False, "evidence_required")
    if get_gate_meta(gate_id, chain_list) is None:
        return FilingValidation(False, "gate_not_found")

    suspension = compute_suspension_state(gate_id, chain_list, now=now)
    if suspension.status == "shutdown":
        return FilingValidation(False, "gate_already_shutdown")
    if suspension.status != "suspended":
        return FilingValidation(False, "gate_not_suspended")

    shutdown = compute_shutdown_state(gate_id, chain_list, now=now)
    if shutdown.has_pending:
        return FilingValidation(False, "shutdown_already_pending")
    if filer_cooldown_until is not None and filer_cooldown_until > now:
        return FilingValidation(False, "filer_cooldown_active")
    _ = filer_id
    return FilingValidation(True, "ok")


__all__ = [
    "ShutdownState",
    "compute_shutdown_state",
    "validate_shutdown_filing",
]
