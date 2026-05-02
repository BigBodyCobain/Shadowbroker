"""Tier 1 / Tier 2 event-type classification.

Source of truth: ``infonet-economy/RULES_SKELETON.md`` §3.14 Rule 4.

Tier 1 events:

- **Eventually consistent.** A node operating in a partition can
  produce them locally; on reconnect they merge into the global
  view without conflict.
- **CRDT-friendly.** No total ordering required.
- Examples: upreps, gate enter/exit, gate messages (off-chain),
  citizenship claim signal, content posts.

Tier 2 events:

- **Epoch finality required.** A node operating in a partition can
  *propose* them locally with ``is_provisional=True``, but they MUST
  NOT become economically final until an epoch checkpoint confirms
  the chain head.
- Examples: oracle rep minting (via ``resolution_finalize``),
  governance execution, dispute outcomes.

The classifier returns "tier1", "tier2", or "infrastructure" (for
event types that don't directly affect economic state — e.g.
``node_register``).
"""

from __future__ import annotations

from services.infonet.schema import INFONET_ECONOMY_EVENT_TYPES


# Sprint 10 baseline classification. Future governance can rebalance
# via upgrade-hash governance (the classification is a constitutional
# property — moving an event between tiers changes finality semantics).

TIER1_EVENT_TYPES: frozenset[str] = frozenset({
    # Reputation surface — common rep is fully chain-derived and
    # CRDT-friendly. Upreps from disjoint partitions add commutatively.
    "uprep",
    "downrep",
    # Gate membership — entering / exiting a gate is local action;
    # final view is just the union (modulo exit removals).
    "gate_enter",
    "gate_exit",
    "gate_lock",  # locking is a vote — partition-local locks count
    # Content / citizenship signals — pure local actions.
    "post_create",
    "post_reply",
    "citizenship_claim",
    # Predictions are local; what's NOT Tier 1 is the resolution.
    "prediction_create",
    "prediction_place",
    # Truth stakes — same: placing is Tier 1, resolving is Tier 2.
    "truth_stake_place",
    # Bounty creation / claim acknowledgements — local action.
    "bounty_create",
    "bounty_claim",
})


TIER2_EVENT_TYPES: frozenset[str] = frozenset({
    # Resolution finality — must be confirmed by epoch checkpoint
    # before oracle_rep mints.
    "market_snapshot",
    "evidence_submit",
    "resolution_stake",
    "bootstrap_resolution_vote",
    "resolution_finalize",
    # Truth stake resolution.
    "truth_stake_resolve",
    # Disputes — the bounded-reversal mechanic depends on a stable
    # global view; partition-only dispute resolution would diverge.
    "dispute_open",
    "dispute_stake",
    "dispute_resolve",
    # Gate shutdown — irreversible state change; must reach global
    # consensus before execute.
    "gate_suspend_file",
    "gate_suspend_vote",
    "gate_suspend_execute",
    "gate_shutdown_file",
    "gate_shutdown_vote",
    "gate_shutdown_execute",
    "gate_unsuspend",
    "gate_shutdown_appeal_file",
    "gate_shutdown_appeal_vote",
    "gate_shutdown_appeal_resolve",
    # Governance — petitions and upgrades affect protocol params /
    # release hash globally. Must not execute provisionally.
    "petition_file",
    "petition_sign",
    "petition_vote",
    "challenge_file",
    "challenge_vote",
    "petition_execute",
    "upgrade_propose",
    "upgrade_sign",
    "upgrade_vote",
    "upgrade_challenge",
    "upgrade_challenge_vote",
    "upgrade_signal_ready",
    "upgrade_activate",
    # Coin events — when shipped, must not double-mint across
    # partitions. (Sprint 9 currently SKIPPED; classification kept
    # so it's ready when un-skipped.)
    "coin_transfer",
    "coin_mint",
    # Identity rotation — re-keying must reach global consensus.
    "identity_rotate",
})


# Infrastructure events — neither tier (don't directly drive
# economic state). Currently just node_register.
_INFRASTRUCTURE_TYPES: frozenset[str] = frozenset({
    "node_register",
})


def classify_event_type(event_type: str) -> str:
    """Return ``"tier1"`` / ``"tier2"`` / ``"infrastructure"`` /
    ``"unknown"``.

    Validates the classification covers the entire
    ``INFONET_ECONOMY_EVENT_TYPES`` surface — Sprint 10's invariant
    test asserts this.
    """
    if event_type in TIER1_EVENT_TYPES:
        return "tier1"
    if event_type in TIER2_EVENT_TYPES:
        return "tier2"
    if event_type in _INFRASTRUCTURE_TYPES:
        return "infrastructure"
    return "unknown"


def assert_classification_complete() -> None:
    """Sprint 10 invariant: every economy event type is classified.

    Called from the test suite. Raising at import time would be too
    aggressive — a future event type added without a tier assignment
    should fail loudly in CI, not crash production.
    """
    classified = TIER1_EVENT_TYPES | TIER2_EVENT_TYPES | _INFRASTRUCTURE_TYPES
    missing = sorted(INFONET_ECONOMY_EVENT_TYPES - classified)
    if missing:
        raise AssertionError(
            f"Tier classification incomplete — these event types have no "
            f"tier assignment: {missing}. Add them to TIER1_EVENT_TYPES, "
            f"TIER2_EVENT_TYPES, or _INFRASTRUCTURE_TYPES."
        )
    overlap = TIER1_EVENT_TYPES & TIER2_EVENT_TYPES
    if overlap:
        raise AssertionError(
            f"Tier classification overlapping — these types are in both "
            f"Tier 1 and Tier 2: {sorted(overlap)}"
        )


__all__ = [
    "TIER1_EVENT_TYPES",
    "TIER2_EVENT_TYPES",
    "assert_classification_complete",
    "classify_event_type",
]
