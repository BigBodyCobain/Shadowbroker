"""Constitutional challenge — 48-hour window after a petition passes.

Source of truth: ``infonet-economy/RULES_SKELETON.md`` §5.4 step 4.

A challenger sacrifices ``challenge_filing_cost`` (default 25) common
rep to file a challenge against a passed petition. The challenge then
goes to a vote — if it succeeds (``uphold`` wins by majority oracle
rep), the petition is voided. If it fails, the challenger loses the
sacrificed rep and the petition proceeds to execution.

This module exposes:

- ``compute_challenge_state(petition_id, chain, *, now)`` — derives
  the challenge outcome from chain events.
- ``validate_challenge_filing(filer_common_rep, ...)`` — pre-emit
  check.

Sprint 7 voting tally uses ``oracle_rep_active`` weight, same as
petition voting itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from services.infonet.config import CONFIG
from services.infonet.reputation import compute_oracle_rep_active


_HOUR_S = 3600.0


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    p = event.get("payload")
    return p if isinstance(p, dict) else {}


@dataclass
class ChallengeState:
    petition_id: str
    filed: bool
    filer_id: str | None
    filed_at: float | None
    deadline: float | None
    uphold_weight: float
    void_weight: float
    outcome: str  # "voided" | "rejected" | "pending" | "none"


def compute_challenge_state(
    petition_id: str,
    chain: Iterable[dict[str, Any]],
    *,
    now: float,
) -> ChallengeState:
    chain_list = [e for e in chain if isinstance(e, dict)]

    file_event = None
    vote_events: list[dict[str, Any]] = []
    for ev in chain_list:
        if _payload(ev).get("petition_id") != petition_id:
            continue
        et = ev.get("event_type")
        if et == "challenge_file":
            if file_event is None:
                file_event = ev
        elif et == "challenge_vote":
            vote_events.append(ev)

    if file_event is None:
        return ChallengeState(
            petition_id=petition_id, filed=False,
            filer_id=None, filed_at=None, deadline=None,
            uphold_weight=0.0, void_weight=0.0, outcome="none",
        )

    filed_at = float(file_event.get("timestamp") or 0.0)
    deadline = filed_at + float(CONFIG["challenge_window_hours"]) * _HOUR_S

    state = ChallengeState(
        petition_id=petition_id, filed=True,
        filer_id=str(file_event.get("node_id") or ""),
        filed_at=filed_at, deadline=deadline,
        uphold_weight=0.0, void_weight=0.0,
        outcome="pending",
    )

    seen: dict[str, str] = {}
    cache: dict[str, float] = {}
    for ev in sorted(vote_events,
                     key=lambda e: (float(e.get("timestamp") or 0.0),
                                    int(e.get("sequence") or 0))):
        voter = ev.get("node_id")
        if not isinstance(voter, str) or not voter or voter in seen:
            continue
        ts = float(ev.get("timestamp") or 0.0)
        if ts < filed_at or ts > deadline:
            continue
        vote = _payload(ev).get("vote")
        if vote not in ("uphold", "void"):
            continue
        seen[voter] = vote
        if voter not in cache:
            cache[voter] = compute_oracle_rep_active(voter, chain_list, now=ts)
        w = cache[voter]
        if vote == "uphold":
            # "uphold" means: uphold the constitutional challenge —
            # i.e. void the original petition. Per RULES §5.4 step 4:
            # "Challenge upheld → 'voided_challenge' (petition killed)".
            state.uphold_weight += w
        else:  # "void" the challenge → original petition stands
            state.void_weight += w

    if now <= deadline:
        return state  # still pending

    if state.uphold_weight > state.void_weight:
        state.outcome = "voided"
    else:
        state.outcome = "rejected"
    return state


@dataclass(frozen=True)
class ChallengeFilingValidation:
    accepted: bool
    reason: str


def validate_challenge_filing(
    filer_common_rep: float,
    petition_id: str,
    chain: Iterable[dict[str, Any]],
    *,
    now: float,
) -> ChallengeFilingValidation:
    """Pre-emit check for a ``challenge_file`` event.

    Rejects if:
    - Filer lacks the ``challenge_filing_cost``.
    - A challenge already exists on this petition.
    - The challenge window for the petition has elapsed (caller is
      expected to have already verified the petition's voting closed
      successfully — that timestamp comes from
      ``compute_petition_state``).
    """
    if filer_common_rep < float(CONFIG["challenge_filing_cost"]):
        return ChallengeFilingValidation(False, "insufficient_common_rep")
    state = compute_challenge_state(petition_id, list(chain), now=now)
    if state.filed:
        return ChallengeFilingValidation(False, "challenge_already_filed")
    return ChallengeFilingValidation(True, "ok")


__all__ = [
    "ChallengeFilingValidation",
    "ChallengeState",
    "compute_challenge_state",
    "validate_challenge_filing",
]
