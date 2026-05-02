"""Sprint 2 — governance decay applies to dormant nodes only.

Maps to IMPLEMENTATION_PLAN.md §7.1 Sprint 2 row:
"Decay applies to dormant nodes only."
"""

from __future__ import annotations

from services.infonet.config import CONFIG
from services.infonet.reputation import (
    compute_oracle_rep,
    compute_oracle_rep_active,
    decay_factor_for_age,
)
from services.infonet.tests._chain_factory import make_market_chain


_DECAY_DAYS = float(CONFIG["governance_decay_days"])
_DECAY_FACTOR = float(CONFIG["governance_decay_factor"])
_DAY_S = 86400.0


def test_decay_factor_within_window_is_one():
    assert decay_factor_for_age(0.0) == 1.0
    assert decay_factor_for_age(_DECAY_DAYS - 1) == 1.0
    assert decay_factor_for_age(_DECAY_DAYS) == 1.0


def test_decay_factor_one_period_past_is_factor():
    f = decay_factor_for_age(_DECAY_DAYS + 1)
    # floor((90+1)/90) = 1 → 0.5
    assert f == _DECAY_FACTOR


def test_decay_factor_two_periods_past_is_factor_squared():
    f = decay_factor_for_age(2 * _DECAY_DAYS + 1)
    # floor(181/90) = 2 → 0.25
    assert f == _DECAY_FACTOR ** 2


def test_decay_factor_no_success_is_zero():
    """A node with no qualifying win has zero governance weight."""
    assert decay_factor_for_age(None) == 0.0


def test_active_oracle_at_full_weight_within_window():
    chain = make_market_chain(
        "m1", "creator",
        outcome="yes",
        predictions=[{"node_id": "alice", "side": "yes", "probability_at_bet": 30.0}],
        participants=5, total_stake=10.0,
        base_ts=1_700_000_000.0,
    )
    base = compute_oracle_rep("alice", chain)
    now = 1_700_000_000.0 + 7200.0 + _DECAY_DAYS * _DAY_S - 1
    active = compute_oracle_rep_active("alice", chain, now=now)
    assert active == base


def test_dormant_oracle_decays_one_period():
    chain = make_market_chain(
        "m1", "creator",
        outcome="yes",
        predictions=[{"node_id": "alice", "side": "yes", "probability_at_bet": 30.0}],
        participants=5, total_stake=10.0,
        base_ts=1_700_000_000.0,
    )
    base = compute_oracle_rep("alice", chain)
    # 90 + 5 days past finalize.
    finalize_ts = 1_700_000_000.0 + 7200.0
    now = finalize_ts + _DECAY_DAYS * _DAY_S + 5 * _DAY_S
    active = compute_oracle_rep_active("alice", chain, now=now)
    assert active == base * _DECAY_FACTOR


def test_dormant_oracle_decays_two_periods():
    chain = make_market_chain(
        "m1", "creator",
        outcome="yes",
        predictions=[{"node_id": "alice", "side": "yes", "probability_at_bet": 30.0}],
        participants=5, total_stake=10.0,
        base_ts=1_700_000_000.0,
    )
    base = compute_oracle_rep("alice", chain)
    finalize_ts = 1_700_000_000.0 + 7200.0
    now = finalize_ts + 2 * _DECAY_DAYS * _DAY_S + 1 * _DAY_S
    active = compute_oracle_rep_active("alice", chain, now=now)
    assert active == base * (_DECAY_FACTOR ** 2)


def test_node_with_no_oracle_rep_has_no_active_weight():
    chain = make_market_chain(
        "m1", "creator",
        outcome="yes",
        predictions=[{"node_id": "alice", "side": "yes", "probability_at_bet": 30.0}],
        participants=5, total_stake=10.0,
    )
    assert compute_oracle_rep_active("bob", chain, now=1_700_010_000.0) == 0.0


def test_recent_successful_prediction_resets_decay():
    """Two markets: dormant timestamp from m1, fresh timestamp from m2.
    The fresh win re-anchors the decay clock — full weight returns.
    """
    chain = []
    chain += make_market_chain(
        "m1", "creator",
        outcome="yes",
        predictions=[{"node_id": "alice", "side": "yes", "probability_at_bet": 30.0}],
        base_ts=1_000_000.0,
        participants=5, total_stake=10.0,
    )
    chain += make_market_chain(
        "m2", "creator",
        outcome="no",
        predictions=[{"node_id": "alice", "side": "no", "probability_at_bet": 40.0}],
        base_ts=1_000_000.0 + 200 * _DAY_S,  # m2 well past m1's decay
        participants=5, total_stake=10.0,
    )
    base = compute_oracle_rep("alice", chain)
    now = 1_000_000.0 + 200 * _DAY_S + 7200.0 + 5 * _DAY_S
    active = compute_oracle_rep_active("alice", chain, now=now)
    # Within m2's window → full weight.
    assert active == base
