"""Upgrade-hash governance — RULES §3.15 (formalization), §5.6.

Protocol upgrades that need new logic (formulas, event types, state
machines) cannot be expressed as parameter changes — the declarative
DSL has no way to ship new code. The Round 8 formalization replaces
that gap with **upgrade-hash governance**: developers publish a
software release, the network votes on its SHA-256 release hash, and
nodes upgrade their software.

Lifecycle:

1. Filing (``upgrade_propose``) — 25 common rep, includes the
   ``release_hash``, description, target_protocol_version.
2. Signatures (14 days) — 25% of network ``oracle_rep_active``.
3. Voting (14 days) — **80% supermajority + 40% quorum** (higher
   bars than param petitions).
4. Constitutional challenge window (48 hours).
5. Activation (30 days): Heavy Nodes that have downloaded the new
   release emit ``upgrade_signal_ready``. Once **67%** of Heavy
   Nodes have signaled, the upgrade activates and ``protocol_version``
   increments.
6. Failure modes: ``failed_signatures``, ``failed_vote``,
   ``voided_challenge``, ``failed_activation`` (≥33% of Heavy Nodes
   couldn't or wouldn't upgrade — network not ready).

Heavy-Node detection: a node is "Heavy" if its transport tier is
``private_strong`` per IMPLEMENTATION_PLAN §3.5. For Sprint 7's pure
chain-only computation, we rely on the producer to mark
``upgrade_signal_ready`` events with ``release_hash`` matching the
proposal — and only Heavy Nodes can emit that event in production
(producer-side enforcement; this module verifies the chain-derived
state).
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
class HeavyNodeReadinessState:
    total_heavy_nodes: int
    ready_count: int
    fraction: float
    threshold_met: bool


@dataclass
class UpgradeProposalState:
    proposal_id: str
    status: str  # "signatures" | "voting" | "challenge" | "activation" |
                 # "activated" | "failed_signatures" | "failed_vote" |
                 # "voided_challenge" | "failed_activation" | "not_found"
    proposer_id: str
    filed_at: float
    release_hash: str = ""
    target_protocol_version: str = ""
    signature_governance_weight: float = 0.0
    votes_for_weight: float = 0.0
    votes_against_weight: float = 0.0
    voting_started_at: float | None = None
    voting_deadline: float | None = None
    challenge_window_until: float | None = None
    activation_deadline: float | None = None
    readiness: HeavyNodeReadinessState = field(
        default_factory=lambda: HeavyNodeReadinessState(0, 0, 0.0, False),
    )


def compute_upgrade_state(
    proposal_id: str,
    chain: Iterable[dict[str, Any]],
    *,
    now: float,
    heavy_node_ids: set[str] | None = None,
) -> UpgradeProposalState:
    """Derive the proposal's current state from chain events.

    ``heavy_node_ids`` is the set of nodes the caller knows to be
    Heavy at chain time ``now``. Production callers compute this from
    `wormhole_supervisor.get_transport_tier()` × the chain's known
    nodes. Tests pass an explicit set.
    """
    chain_list = [e for e in chain if isinstance(e, dict)]
    heavy_set = set(heavy_node_ids) if heavy_node_ids is not None else set()

    propose_event = None
    sign_events: list[dict[str, Any]] = []
    vote_events: list[dict[str, Any]] = []
    challenge_event = None
    challenge_vote_events: list[dict[str, Any]] = []
    signal_ready_events: list[dict[str, Any]] = []
    activate_event = None

    for ev in chain_list:
        et = ev.get("event_type")
        p = _payload(ev)
        pid = p.get("proposal_id")
        if pid != proposal_id:
            continue
        if et == "upgrade_propose":
            if propose_event is None:
                propose_event = ev
        elif et == "upgrade_sign":
            sign_events.append(ev)
        elif et == "upgrade_vote":
            vote_events.append(ev)
        elif et == "upgrade_challenge":
            if challenge_event is None:
                challenge_event = ev
        elif et == "upgrade_challenge_vote":
            challenge_vote_events.append(ev)
        elif et == "upgrade_signal_ready":
            signal_ready_events.append(ev)
        elif et == "upgrade_activate":
            activate_event = ev

    if propose_event is None:
        return UpgradeProposalState(
            proposal_id=proposal_id, status="not_found",
            proposer_id="", filed_at=0.0,
        )

    pp = _payload(propose_event)
    state = UpgradeProposalState(
        proposal_id=proposal_id,
        status="signatures",
        proposer_id=str(propose_event.get("node_id") or ""),
        filed_at=float(propose_event.get("timestamp") or 0.0),
        release_hash=str(pp.get("release_hash") or ""),
        target_protocol_version=str(pp.get("target_protocol_version") or ""),
    )

    cache: dict[str, float] = {}

    def _w(node_id: str, at: float) -> float:
        if node_id not in cache:
            cache[node_id] = compute_oracle_rep_active(node_id, chain_list, now=at)
        return cache[node_id]

    # Network weight at "now" — used for signature + quorum thresholds.
    nodes: set[str] = set()
    for ev in chain_list:
        nid = ev.get("node_id")
        if isinstance(nid, str) and nid:
            nodes.add(nid)
    network_weight = sum(_w(n, now) for n in nodes)
    sig_threshold = network_weight * float(CONFIG["upgrade_signature_threshold"])

    # ── Signatures ──
    sig_window_s = float(CONFIG["upgrade_signature_window_days"]) * _DAY_S
    seen_sig: set[str] = set()
    for ev in sorted(sign_events,
                     key=lambda e: (float(e.get("timestamp") or 0.0),
                                    int(e.get("sequence") or 0))):
        signer = ev.get("node_id")
        if not isinstance(signer, str) or signer in seen_sig:
            continue
        ts = float(ev.get("timestamp") or 0.0)
        if ts > state.filed_at + sig_window_s:
            continue
        seen_sig.add(signer)
        state.signature_governance_weight += _w(signer, ts)

    if state.signature_governance_weight >= sig_threshold > 0:
        latest_sig_ts = max((float(e.get("timestamp") or 0.0) for e in sign_events
                             if e.get("node_id") in seen_sig),
                            default=state.filed_at)
        state.status = "voting"
        state.voting_started_at = latest_sig_ts
        state.voting_deadline = latest_sig_ts + float(CONFIG["upgrade_vote_window_days"]) * _DAY_S
    else:
        if now > state.filed_at + sig_window_s:
            state.status = "failed_signatures"
            return state
        return state

    # ── Voting ──
    seen_voters: dict[str, str] = {}
    for ev in sorted(vote_events,
                     key=lambda e: (float(e.get("timestamp") or 0.0),
                                    int(e.get("sequence") or 0))):
        voter = ev.get("node_id")
        if not isinstance(voter, str) or voter in seen_voters:
            continue
        ts = float(ev.get("timestamp") or 0.0)
        if state.voting_started_at is None or ts < state.voting_started_at:
            continue
        if state.voting_deadline is None or ts > state.voting_deadline:
            continue
        vote = _payload(ev).get("vote")
        if vote not in ("for", "against"):
            continue
        seen_voters[voter] = vote
        w = _w(voter, ts)
        if vote == "for":
            state.votes_for_weight += w
        else:
            state.votes_against_weight += w

    if state.voting_deadline is not None and now <= state.voting_deadline:
        return state

    participating = state.votes_for_weight + state.votes_against_weight
    quorum_required = network_weight * float(CONFIG["upgrade_quorum"])
    if participating < quorum_required or participating == 0:
        state.status = "failed_vote"
        return state
    if state.votes_for_weight / participating < float(CONFIG["upgrade_supermajority"]):
        state.status = "failed_vote"
        return state

    # Vote passed — challenge window.
    state.status = "challenge"
    state.challenge_window_until = (
        (state.voting_deadline or state.filed_at)
        + float(CONFIG["upgrade_challenge_window_hours"]) * _HOUR_S
    )

    # Process upgrade_challenge_vote — uphold-majority voids the proposal.
    if challenge_event is not None:
        uphold_w = 0.0
        void_w = 0.0
        seen_cv: dict[str, str] = {}
        for ev in sorted(challenge_vote_events,
                         key=lambda e: (float(e.get("timestamp") or 0.0),
                                        int(e.get("sequence") or 0))):
            voter = ev.get("node_id")
            if not isinstance(voter, str) or voter in seen_cv:
                continue
            ts = float(ev.get("timestamp") or 0.0)
            challenge_at = float(challenge_event.get("timestamp") or 0.0)
            if ts < challenge_at or ts > (state.challenge_window_until or 0.0):
                continue
            vote = _payload(ev).get("vote")
            if vote not in ("uphold", "void"):
                continue
            seen_cv[voter] = vote
            w = _w(voter, ts)
            if vote == "uphold":
                uphold_w += w
            else:
                void_w += w
        if (state.challenge_window_until is not None
                and now > state.challenge_window_until
                and uphold_w > void_w):
            state.status = "voided_challenge"
            return state

    if state.challenge_window_until is not None and now <= state.challenge_window_until:
        return state

    # Challenge cleared → activation phase.
    state.status = "activation"
    state.activation_deadline = (
        (state.challenge_window_until or state.filed_at)
        + float(CONFIG["upgrade_activation_window_days"]) * _DAY_S
    )

    # ── Heavy-Node readiness ──
    seen_ready: set[str] = set()
    for ev in signal_ready_events:
        node = ev.get("node_id")
        if not isinstance(node, str) or node in seen_ready:
            continue
        if node not in heavy_set:
            continue  # only Heavy Nodes can signal
        if _payload(ev).get("release_hash") != state.release_hash:
            continue
        seen_ready.add(node)
    total_heavy = max(len(heavy_set), 1)
    fraction = len(seen_ready) / total_heavy if heavy_set else 0.0
    threshold = float(CONFIG["upgrade_activation_threshold"])
    state.readiness = HeavyNodeReadinessState(
        total_heavy_nodes=len(heavy_set),
        ready_count=len(seen_ready),
        fraction=fraction,
        threshold_met=fraction >= threshold,
    )

    if activate_event is not None:
        state.status = "activated"
        return state

    if state.readiness.threshold_met:
        # Producer can emit upgrade_activate now — until then the
        # status is "activation" with threshold_met=True so the UI
        # can prompt.
        return state

    if state.activation_deadline is not None and now > state.activation_deadline:
        state.status = "failed_activation"
    return state


@dataclass(frozen=True)
class UpgradeFilingValidation:
    accepted: bool
    reason: str


def validate_upgrade_proposal(
    filer_common_rep: float,
    *,
    release_hash: str,
    release_description: str,
    target_protocol_version: str,
) -> UpgradeFilingValidation:
    """Pre-emit check for ``upgrade_propose``."""
    if filer_common_rep < float(CONFIG["upgrade_filing_cost"]):
        return UpgradeFilingValidation(False, "insufficient_common_rep")
    if not isinstance(release_hash, str) or not release_hash.strip():
        return UpgradeFilingValidation(False, "release_hash_required")
    if not isinstance(release_description, str) or len(release_description) > 4000:
        return UpgradeFilingValidation(False, "release_description_invalid")
    if not isinstance(target_protocol_version, str) or not target_protocol_version.strip():
        return UpgradeFilingValidation(False, "target_protocol_version_required")
    return UpgradeFilingValidation(True, "ok")


__all__ = [
    "HeavyNodeReadinessState",
    "UpgradeFilingValidation",
    "UpgradeProposalState",
    "compute_upgrade_state",
    "validate_upgrade_proposal",
]
