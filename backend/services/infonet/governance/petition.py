"""Petition state machine — pure function over chain history.

Source of truth: ``infonet-economy/RULES_SKELETON.md`` §3.15, §5.4.

State diagram:

    petition_file
        │
        ▼  status="signatures"
    petition_sign × N (collect signature_governance_weight)
        │
        ▼  if signature_governance_weight ≥ 25% × network → status="voting"
        │  if 14 days elapsed and threshold not met → status="failed_signatures"
    petition_vote × N (oracle_rep_active weighted)
        │
        ▼  if 7 days elapsed:
        │     check quorum (30%) + supermajority (67%)
        │     status="challenge" (passed) or "failed_vote"
    challenge_file (optional, 48h window) + challenge_vote × N
        │
        ▼  if challenge passes → status="voided_challenge"
        │  else → status="passed"
    petition_execute → status="executed"

Voting weights use ``oracle_rep_active`` (governance-decayed) per
RULES §3.15. Total network weight is the sum across all nodes
referenced by signature/vote events plus any node with chain
activity (we use the union of acting nodes' weights — same as
``compute_network_governance_weight``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from services.infonet.config import CONFIG
from services.infonet.reputation import compute_oracle_rep_active


_DAY_S = 86400.0
_HOUR_S = 3600.0


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    p = event.get("payload")
    return p if isinstance(p, dict) else {}


@dataclass
class PetitionState:
    petition_id: str
    status: str  # "signatures" | "voting" | "challenge" | "passed" |
                 # "executed" | "failed_signatures" | "failed_vote" |
                 # "voided_challenge" | "not_found"
    filer_id: str
    filed_at: float
    petition_payload: dict[str, Any] = field(default_factory=dict)

    signature_governance_weight: float = 0.0
    signature_threshold_at_filing: float = 0.0

    votes_for_weight: float = 0.0
    votes_against_weight: float = 0.0

    voting_started_at: float | None = None
    voting_deadline: float | None = None
    challenge_window_until: float | None = None


def _governance_weight_provider(
    node_id: str,
    chain: list[dict[str, Any]],
    *,
    at: float,
    cache: dict[str, float],
) -> float:
    """Memoize per-call: governance weight for ``node_id`` evaluated at
    chain time ``at``. Cached because petitions iterate signatures and
    votes from many nodes, and recomputing oracle rep per call is
    expensive on long chains."""
    key = node_id
    if key in cache:
        return cache[key]
    w = compute_oracle_rep_active(node_id, chain, now=at)
    cache[key] = w
    return w


def network_governance_weight(
    chain: Iterable[dict[str, Any]],
    *,
    now: float,
) -> float:
    """Total network ``oracle_rep_active`` at chain time ``now``.

    Sum across every node that has authored at least one event on the
    chain. Matches RULES §3.15: "sum(node.oracle_rep_active for all
    nodes)". Newly-created nodes that haven't yet signed any event
    have zero weight and contribute nothing — including them is a
    no-op.
    """
    chain_list = [e for e in chain if isinstance(e, dict)]
    nodes: set[str] = set()
    for ev in chain_list:
        nid = ev.get("node_id")
        if isinstance(nid, str) and nid:
            nodes.add(nid)
    cache: dict[str, float] = {}
    return sum(
        _governance_weight_provider(n, chain_list, at=now, cache=cache)
        for n in nodes
    )


def compute_petition_state(
    petition_id: str,
    chain: Iterable[dict[str, Any]],
    *,
    now: float,
) -> PetitionState:
    """Derive the current state of ``petition_id`` from chain history.

    ``now`` is the evaluation timestamp — pass
    ``time_validity.chain_majority_time(chain)`` in production.
    """
    chain_list = [e for e in chain if isinstance(e, dict)]

    file_event = None
    sign_events: list[dict[str, Any]] = []
    vote_events: list[dict[str, Any]] = []
    execute_event = None
    challenge_filed_event = None
    challenge_vote_events: list[dict[str, Any]] = []

    for ev in chain_list:
        et = ev.get("event_type")
        p = _payload(ev)
        pid = p.get("petition_id")
        if pid != petition_id:
            continue
        if et == "petition_file":
            if file_event is None:  # first-write-wins
                file_event = ev
        elif et == "petition_sign":
            sign_events.append(ev)
        elif et == "petition_vote":
            vote_events.append(ev)
        elif et == "petition_execute":
            execute_event = ev
        elif et == "challenge_file":
            if challenge_filed_event is None:
                challenge_filed_event = ev
        elif et == "challenge_vote":
            challenge_vote_events.append(ev)

    if file_event is None:
        return PetitionState(
            petition_id=petition_id, status="not_found",
            filer_id="", filed_at=0.0,
        )

    state = PetitionState(
        petition_id=petition_id,
        status="signatures",
        filer_id=str(file_event.get("node_id") or ""),
        filed_at=float(file_event.get("timestamp") or 0.0),
        petition_payload=dict(_payload(file_event).get("petition_payload") or {}),
    )

    cache: dict[str, float] = {}
    network_weight = network_governance_weight(chain_list, now=now)
    state.signature_threshold_at_filing = (
        network_weight * float(CONFIG["petition_signature_threshold"])
    )

    # ── Signatures phase ──
    sign_window_s = float(CONFIG["petition_signature_window_days"]) * _DAY_S
    seen_signers: set[str] = set()
    for ev in sorted(sign_events,
                     key=lambda e: (float(e.get("timestamp") or 0.0),
                                    int(e.get("sequence") or 0))):
        signer = ev.get("node_id")
        if not isinstance(signer, str) or not signer:
            continue
        if signer in seen_signers:
            continue
        seen_signers.add(signer)
        ts = float(ev.get("timestamp") or 0.0)
        # Only count signatures that landed within the window.
        if ts > state.filed_at + sign_window_s:
            continue
        weight = _governance_weight_provider(signer, chain_list, at=ts, cache=cache)
        state.signature_governance_weight += weight

    if state.signature_governance_weight >= state.signature_threshold_at_filing > 0:
        # Find the timestamp the threshold was crossed (= last signature
        # that crossed it). Sprint 7 simplification: use the latest
        # signature event timestamp as the voting-phase start.
        latest_sig_ts = max((float(e.get("timestamp") or 0.0) for e in sign_events
                             if e.get("node_id") in seen_signers),
                            default=state.filed_at)
        state.status = "voting"
        state.voting_started_at = latest_sig_ts
        state.voting_deadline = latest_sig_ts + float(CONFIG["petition_vote_window_days"]) * _DAY_S
    else:
        if now > state.filed_at + sign_window_s:
            state.status = "failed_signatures"
            return state
        # Still collecting signatures.
        return state

    # ── Voting phase ──
    seen_voters: dict[str, str] = {}  # node_id → "for"|"against"
    for ev in sorted(vote_events,
                     key=lambda e: (float(e.get("timestamp") or 0.0),
                                    int(e.get("sequence") or 0))):
        voter = ev.get("node_id")
        if not isinstance(voter, str) or not voter:
            continue
        if voter in seen_voters:  # one vote per node — first wins
            continue
        ts = float(ev.get("timestamp") or 0.0)
        if state.voting_started_at is not None and ts < state.voting_started_at:
            continue
        if state.voting_deadline is not None and ts > state.voting_deadline:
            continue
        vote = _payload(ev).get("vote")
        if vote not in ("for", "against"):
            continue
        seen_voters[voter] = vote
        weight = _governance_weight_provider(voter, chain_list, at=ts, cache=cache)
        if vote == "for":
            state.votes_for_weight += weight
        else:
            state.votes_against_weight += weight

    if state.voting_deadline is not None and now <= state.voting_deadline:
        # Voting still open.
        return state

    # Voting closed — tally.
    participating = state.votes_for_weight + state.votes_against_weight
    quorum_required = network_weight * float(CONFIG["petition_quorum"])
    if participating < quorum_required:
        state.status = "failed_vote"
        return state
    if participating == 0:
        state.status = "failed_vote"
        return state
    if state.votes_for_weight / participating < float(CONFIG["petition_supermajority"]):
        state.status = "failed_vote"
        return state

    # Petition passed the vote — enter challenge window.
    state.status = "challenge"
    state.challenge_window_until = (
        (state.voting_deadline or state.filed_at)
        + float(CONFIG["challenge_window_hours"]) * _HOUR_S
    )

    # ── Challenge phase ──
    from services.infonet.governance.challenge import (
        compute_challenge_state as _compute_challenge_state,
    )
    challenge_state = _compute_challenge_state(petition_id, chain_list, now=now)
    if challenge_state.outcome == "voided":
        state.status = "voided_challenge"
        return state
    if state.challenge_window_until is not None and now <= state.challenge_window_until:
        # Challenge window still open.
        return state

    # Challenge window closed without voiding the petition.
    state.status = "passed"

    if execute_event is not None:
        state.status = "executed"
    return state


@dataclass(frozen=True)
class FilingValidation:
    accepted: bool
    reason: str


def validate_petition_filing(
    filer_common_rep: float,
    *,
    petition_payload: dict[str, Any],
) -> FilingValidation:
    """Pre-emit check for a ``petition_file`` event.

    The producer must verify the filer has at least
    ``petition_filing_cost`` common rep available to burn. The
    payload structure is also validated up-front (cheaper to reject
    here than during execution).
    """
    if filer_common_rep < float(CONFIG["petition_filing_cost"]):
        return FilingValidation(False, "insufficient_common_rep")
    if not isinstance(petition_payload, dict):
        return FilingValidation(False, "petition_payload_not_object")
    if "type" not in petition_payload:
        return FilingValidation(False, "petition_payload_missing_type")
    return FilingValidation(True, "ok")


__all__ = [
    "FilingValidation",
    "PetitionState",
    "compute_petition_state",
    "network_governance_weight",
    "validate_petition_filing",
]
