"""Sprint 10 — two-tier state + epoch finality + provisional flag.

Maps to IMPLEMENTATION_PLAN §7.1 Sprint 10 row:
"Provisional flag prevents oracle rep minting until epoch finality.
Tier-1 state merges without conflict on partition reconnect."
"""

from __future__ import annotations

from services.infonet.partition import (
    EpochCheckpoint,
    EpochCheckpointStatus,
    TIER1_EVENT_TYPES,
    TIER2_EVENT_TYPES,
    canonical_epoch_root,
    chain_lag_seconds,
    classify_event_type,
    is_chain_stale,
    is_checkpoint_confirmed,
    should_mark_provisional,
)
from services.infonet.partition.two_tier_state import (
    _INFRASTRUCTURE_TYPES,
    assert_classification_complete,
)
from services.infonet.reputation import compute_oracle_rep
from services.infonet.schema import INFONET_ECONOMY_EVENT_TYPES
from services.infonet.tests._chain_factory import make_event, make_market_chain


# ── Tier classification ────────────────────────────────────────────────

def test_classification_covers_every_event_type():
    """Sprint 10 invariant: every economy event type has a tier."""
    assert_classification_complete()


def test_tier1_and_tier2_are_disjoint():
    overlap = TIER1_EVENT_TYPES & TIER2_EVENT_TYPES
    assert overlap == set()


def test_classification_returns_one_of_four_strings():
    valid = {"tier1", "tier2", "infrastructure", "unknown"}
    for et in INFONET_ECONOMY_EVENT_TYPES:
        assert classify_event_type(et) in valid
    assert classify_event_type("not_an_event") == "unknown"


def test_tier1_examples():
    """Spec lists upreps, gate activity, content posting under Tier 1."""
    for et in ("uprep", "gate_enter", "gate_exit", "post_create"):
        assert classify_event_type(et) == "tier1"


def test_tier2_examples():
    """Spec lists oracle rep minting, governance execution, market FINAL,
    dispute outcomes under Tier 2."""
    for et in ("resolution_finalize", "petition_execute", "dispute_resolve",
               "gate_shutdown_execute", "upgrade_activate"):
        assert classify_event_type(et) == "tier2"


# ── Chain staleness ─────────────────────────────────────────────────────

def test_empty_chain_is_infinitely_stale():
    """No events from distinct nodes → infinite lag → Tier 2 events
    must be provisional."""
    assert chain_lag_seconds([], now=1000.0) == float("inf")
    assert is_chain_stale([], now=1000.0)


def test_recent_chain_activity_is_not_stale():
    chain = [
        make_event(f"uprep", f"n{i}",
                   {"target_node_id": "x", "target_event_id": "e"},
                   timestamp=1000.0 + i, sequence=1)
        for i in range(11)  # 11 distinct nodes — feeds chain_majority_time
    ]
    # now = chain end + 1s → tiny lag
    assert not is_chain_stale(chain, now=1011.0 + 1.0)


def test_old_chain_is_stale():
    chain = [
        make_event("uprep", f"n{i}",
                   {"target_node_id": "x", "target_event_id": "e"},
                   timestamp=1000.0 + i, sequence=1)
        for i in range(11)
    ]
    # now is 1 hour past chain end — well past default 60s threshold
    assert is_chain_stale(chain, now=1011.0 + 3600.0)


def test_max_lag_seconds_governs_threshold():
    chain = [
        make_event("uprep", f"n{i}",
                   {"target_node_id": "x", "target_event_id": "e"},
                   timestamp=1000.0 + i, sequence=1)
        for i in range(11)
    ]
    now = 1011.0 + 30.0  # 30-second lag
    assert is_chain_stale(chain, now=now, max_lag_seconds=10.0)
    assert not is_chain_stale(chain, now=now, max_lag_seconds=60.0)


# ── should_mark_provisional ─────────────────────────────────────────────

def test_tier1_event_never_marked_provisional():
    """Even on a partitioned chain, Tier 1 events run live."""
    assert not should_mark_provisional("uprep", [], now=10_000.0)
    assert not should_mark_provisional("gate_enter", [], now=10_000.0)


def test_tier2_event_marked_provisional_on_stale_chain():
    """Empty chain → infinite stale → Tier 2 events provisional."""
    assert should_mark_provisional("resolution_finalize", [], now=10_000.0)
    assert should_mark_provisional("petition_execute", [], now=10_000.0)
    assert should_mark_provisional("dispute_resolve", [], now=10_000.0)


def test_tier2_event_not_provisional_on_fresh_chain():
    chain = [
        make_event("uprep", f"n{i}",
                   {"target_node_id": "x", "target_event_id": "e"},
                   timestamp=1000.0 + i, sequence=1)
        for i in range(11)
    ]
    # Chain freshly active.
    assert not should_mark_provisional("resolution_finalize", chain, now=1011.5)


def test_unknown_event_type_not_provisional():
    """Unknown types don't get the flag — they fail validation
    upstream before ever reaching this check."""
    assert not should_mark_provisional("not_real", [], now=10_000.0)


# ── Provisional flag prevents oracle rep minting ────────────────────────

def test_provisional_market_does_not_mint_oracle_rep():
    """Sprint 2 + Sprint 10 integration: a resolution_finalize event
    with is_provisional=True is structurally barred from minting
    oracle rep until epoch finality clears."""
    chain = make_market_chain(
        "m1", "creator",
        outcome="yes",
        is_provisional=True,
        predictions=[{"node_id": "alice", "side": "yes", "probability_at_bet": 30.0}],
        participants=5, total_stake=10.0,
    )
    assert compute_oracle_rep("alice", chain) == 0


def test_non_provisional_market_does_mint_oracle_rep():
    """Sanity check: when is_provisional=False (epoch finality
    confirmed), minting proceeds normally."""
    chain = make_market_chain(
        "m1", "creator",
        outcome="yes",
        is_provisional=False,
        predictions=[{"node_id": "alice", "side": "yes", "probability_at_bet": 30.0}],
        participants=5, total_stake=10.0,
    )
    assert compute_oracle_rep("alice", chain) > 0


# ── Epoch checkpoint structural model ──────────────────────────────────

def test_canonical_epoch_root_is_deterministic():
    chain = [
        make_event("uprep", "n1",
                   {"target_node_id": "x", "target_event_id": "e1"},
                   timestamp=100.0, sequence=1),
        make_event("uprep", "n2",
                   {"target_node_id": "x", "target_event_id": "e2"},
                   timestamp=200.0, sequence=2),
    ]
    a = canonical_epoch_root(chain, epoch_start_ts=0, epoch_end_ts=300)
    b = canonical_epoch_root(chain, epoch_start_ts=0, epoch_end_ts=300)
    assert a == b
    assert len(a) == 64


def test_canonical_epoch_root_sensitive_to_event_order_in_window():
    """Window inclusion is timestamp-bounded, sorted internally —
    chains submitted in different orders produce the same root."""
    forward = [
        make_event("uprep", "n1", {"target_node_id": "x", "target_event_id": "e1"},
                   timestamp=100.0, sequence=1),
        make_event("uprep", "n2", {"target_node_id": "x", "target_event_id": "e2"},
                   timestamp=200.0, sequence=2),
    ]
    reverse = list(reversed(forward))
    a = canonical_epoch_root(forward, epoch_start_ts=0, epoch_end_ts=300)
    b = canonical_epoch_root(reverse, epoch_start_ts=0, epoch_end_ts=300)
    assert a == b


def test_canonical_epoch_root_excludes_out_of_window_events():
    in_window = [
        make_event("uprep", "n1", {"target_node_id": "x", "target_event_id": "e1"},
                   timestamp=100.0, sequence=1),
    ]
    plus_outside = in_window + [
        make_event("uprep", "n2", {"target_node_id": "x", "target_event_id": "e2"},
                   timestamp=999.0, sequence=2),  # outside window 0..300
    ]
    a = canonical_epoch_root(in_window, epoch_start_ts=0, epoch_end_ts=300)
    b = canonical_epoch_root(plus_outside, epoch_start_ts=0, epoch_end_ts=300)
    assert a == b


def test_empty_epoch_window_has_stable_root():
    a = canonical_epoch_root([], epoch_start_ts=0, epoch_end_ts=300)
    b = canonical_epoch_root([], epoch_start_ts=0, epoch_end_ts=300)
    assert a == b


def test_epoch_checkpoint_pending_when_below_threshold():
    cp = EpochCheckpoint(
        epoch_id=1, root_hash="abc",
        epoch_start_ts=0.0, epoch_end_ts=1000.0,
        participating_heavy_node_ids=frozenset({"h1", "h2"}),
        threshold=0.67,
    )
    # 2 of 10 heavy = 20% — below 67%.
    assert cp.status(total_heavy_nodes=10, now=500.0) == EpochCheckpointStatus.PENDING


def test_epoch_checkpoint_confirmed_at_or_above_threshold():
    cp = EpochCheckpoint(
        epoch_id=1, root_hash="abc",
        epoch_start_ts=0.0, epoch_end_ts=1000.0,
        participating_heavy_node_ids=frozenset({f"h{i}" for i in range(7)}),
        threshold=0.67,
    )
    # 7 of 10 = 70% ≥ 67%.
    assert cp.status(total_heavy_nodes=10, now=500.0) == EpochCheckpointStatus.CONFIRMED
    assert is_checkpoint_confirmed(cp, total_heavy_nodes=10, now=500.0)


def test_epoch_checkpoint_failed_when_window_closes_below_threshold():
    cp = EpochCheckpoint(
        epoch_id=1, root_hash="abc",
        epoch_start_ts=0.0, epoch_end_ts=1000.0,
        participating_heavy_node_ids=frozenset({"h1"}),
        threshold=0.67,
    )
    # 1 of 10 = 10% — and now > epoch_end_ts.
    assert cp.status(total_heavy_nodes=10, now=2000.0) == EpochCheckpointStatus.FAILED


# ── Tier 1 merge on partition heal ──────────────────────────────────────

def test_tier1_upreps_from_disjoint_partitions_merge_additively():
    """Two partitions independently produce Tier 1 upreps; on
    reconnect the union is the merged set. The current chain-derived
    common_rep view does this naturally — Sprint 10 just documents
    the property by composing two synthetic chains.
    """
    base = 1_000_000.0
    # Build partition A: ora1 wins a market, then upreps alice.
    chain_a = make_market_chain(
        "m_A", "creator", outcome="yes",
        predictions=[
            {"node_id": "ora1", "side": "yes", "stake_amount": 10.0},
            {"node_id": "loser_A", "side": "no", "stake_amount": 10.0},
        ],
        base_ts=base, participants=5, total_stake=20.0,
    )
    chain_a.append(make_event(
        "uprep", "ora1",
        {"target_node_id": "alice", "target_event_id": "post1"},
        timestamp=base + 10_000, sequence=99,
    ))

    # Partition B: ora2 wins a different market, upreps alice.
    chain_b = make_market_chain(
        "m_B", "creator", outcome="yes",
        predictions=[
            {"node_id": "ora2", "side": "yes", "stake_amount": 10.0},
            {"node_id": "loser_B", "side": "no", "stake_amount": 10.0},
        ],
        base_ts=base + 100_000, participants=5, total_stake=20.0,
    )
    chain_b.append(make_event(
        "uprep", "ora2",
        {"target_node_id": "alice", "target_event_id": "post2"},
        timestamp=base + 110_000, sequence=99,
    ))

    # Merged chain (partition heal — order doesn't matter for upreps).
    merged = chain_a + chain_b
    from services.infonet.reputation import compute_common_rep
    rep_merged = compute_common_rep("alice", merged)
    rep_alt = compute_common_rep("alice", list(reversed(merged)))
    assert abs(rep_merged - rep_alt) < 1e-9
    # Merge is additive — alice gets contributions from both upreps.
    assert rep_merged > 0


def test_tier1_includes_ramp_independent_event_types():
    """Sanity: Tier 1 includes upreps, gate enter/exit/lock, content
    posts, citizenship claim, and prediction placement (not
    resolution). All of these are partition-tolerant by spec."""
    expected_tier1 = {
        "uprep", "downrep", "gate_enter", "gate_exit", "gate_lock",
        "post_create", "post_reply", "citizenship_claim",
        "prediction_create", "prediction_place", "truth_stake_place",
        "bounty_create", "bounty_claim",
    }
    assert expected_tier1.issubset(TIER1_EVENT_TYPES)


def test_node_register_is_infrastructure_not_either_tier():
    assert "node_register" in _INFRASTRUCTURE_TYPES
    assert "node_register" not in TIER1_EVENT_TYPES
    assert "node_register" not in TIER2_EVENT_TYPES
    assert classify_event_type("node_register") == "infrastructure"
