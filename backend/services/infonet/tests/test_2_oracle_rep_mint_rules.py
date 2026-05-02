"""Sprint 2 — oracle rep mint rules per ``IMMUTABLE_PRINCIPLES['oracle_rep_source']``.

Constitutional anchor: oracle rep may ONLY be minted from correct
predictions in markets that:

1. Reach FINAL (non-INVALID) status.
2. Are non-provisional.
3. Pass frozen liquidity thresholds (min participants + min total stake).
4. Are NOT bootstrap-mode (Sprint 8 will add that path).
5. Are objective. Subjective markets mint Common Rep only.

Sprint 2 invariant: the chain analysis returns 0 oracle rep for any
node that does not satisfy ALL of the above.
"""

from __future__ import annotations

from services.infonet.config import CONFIG
from services.infonet.reputation import (
    compute_oracle_rep,
    compute_oracle_rep_lifetime,
    last_successful_prediction_ts,
)
from services.infonet.tests._chain_factory import make_market_chain


def test_correct_free_pick_in_final_market_mints_oracle_rep():
    chain = make_market_chain(
        "m1", "creator",
        outcome="yes",
        predictions=[{"node_id": "alice", "side": "yes", "probability_at_bet": 30.0}],
        participants=5,
        total_stake=10.0,
    )
    assert compute_oracle_rep("alice", chain) > 0


def test_wrong_free_pick_mints_zero():
    chain = make_market_chain(
        "m1", "creator",
        outcome="yes",
        predictions=[{"node_id": "alice", "side": "no", "probability_at_bet": 50.0}],
        participants=5,
        total_stake=10.0,
    )
    assert compute_oracle_rep("alice", chain) == 0


def test_invalid_market_mints_zero_for_correct_predictor():
    """RULES §3.10 step 0 — invalid markets mint nothing."""
    chain = make_market_chain(
        "m1", "creator",
        outcome="invalid",
        predictions=[{"node_id": "alice", "side": "yes", "probability_at_bet": 30.0}],
        participants=5,
        total_stake=10.0,
    )
    assert compute_oracle_rep("alice", chain) == 0


def test_provisional_market_mints_zero():
    """RULES §3.14 Rule 4 — provisional outcomes do not mint."""
    chain = make_market_chain(
        "m1", "creator",
        outcome="yes",
        is_provisional=True,
        predictions=[{"node_id": "alice", "side": "yes", "probability_at_bet": 30.0}],
        participants=5,
        total_stake=10.0,
    )
    assert compute_oracle_rep("alice", chain) == 0


def test_below_participant_threshold_mints_zero():
    """RULES §3.1 — frozen_participant_count < min_market_participants → zero."""
    threshold = int(CONFIG["min_market_participants"])
    chain = make_market_chain(
        "m1", "creator",
        outcome="yes",
        predictions=[{"node_id": "alice", "side": "yes", "probability_at_bet": 30.0}],
        participants=threshold - 1,
        total_stake=100.0,
    )
    assert compute_oracle_rep("alice", chain) == 0


def test_below_stake_threshold_mints_zero():
    """RULES §3.1 — frozen_total_stake < min_market_total_stake → zero."""
    threshold = float(CONFIG["min_market_total_stake"])
    chain = make_market_chain(
        "m1", "creator",
        outcome="yes",
        predictions=[{"node_id": "alice", "side": "yes", "probability_at_bet": 30.0}],
        participants=5,
        total_stake=threshold - 0.01,
    )
    assert compute_oracle_rep("alice", chain) == 0


def test_subjective_market_mints_zero_oracle_rep():
    """RULES §3.1 (Round 8) — subjective markets feed common rep only."""
    chain = make_market_chain(
        "m1", "creator",
        market_type="subjective",
        outcome="yes",
        predictions=[{"node_id": "alice", "side": "yes", "probability_at_bet": 30.0}],
        participants=5,
        total_stake=10.0,
    )
    assert compute_oracle_rep("alice", chain) == 0


def test_bootstrap_market_mints_when_resolution_finalize_present():
    """Sprint 8 enables bootstrap minting.

    A bootstrap-indexed market that reaches FINAL (via the eligible-
    node-one-vote path or a synthetic resolution_finalize event) mints
    oracle rep for correct predictors, same as a normal market.
    Constitutional anchor: "Oracle rep minted normally from correct
    predictions" — RULES §3.10 step 0.5.
    """
    chain = make_market_chain(
        "m1", "creator",
        bootstrap_index=1,
        outcome="yes",
        predictions=[{"node_id": "alice", "side": "yes", "probability_at_bet": 30.0}],
        participants=5,
        total_stake=10.0,
    )
    # alice picked yes at p=30 → mint = max(0.01, 1 - 0.3) = 0.7.
    assert compute_oracle_rep("alice", chain) > 0


def test_winning_staked_pred_returns_principal_plus_loser_pool_share():
    """RULES §3.2 — staked winner gets stake + share of loser pool."""
    chain = make_market_chain(
        "m1", "creator",
        outcome="yes",
        predictions=[
            {"node_id": "alice", "side": "yes", "stake_amount": 10.0},
            {"node_id": "bob",   "side": "no",  "stake_amount": 10.0},
        ],
        participants=5,
        total_stake=20.0,
    )
    # alice: stake 10 + 100% share of 10 loser pool = 20.0 net
    # but free_pick path also fires for any free predictions — there are none here
    assert compute_oracle_rep("alice", chain) == 20.0


def test_losing_staked_pred_loses_stake():
    chain = make_market_chain(
        "m1", "creator",
        outcome="yes",
        predictions=[
            {"node_id": "alice", "side": "yes", "stake_amount": 10.0},
            {"node_id": "bob",   "side": "no",  "stake_amount": 10.0},
        ],
        participants=5,
        total_stake=20.0,
    )
    # bob lost — clamped to 0 in node-only view
    assert compute_oracle_rep("bob", chain) == 0


def test_oracle_rep_lifetime_excludes_losses():
    """Lifetime is monotonic — loss-clamping does not reduce it."""
    # Two markets: alice wins one, loses one.
    chain = []
    chain += make_market_chain(
        "m1", "creator",
        outcome="yes",
        predictions=[
            {"node_id": "alice", "side": "yes", "stake_amount": 10.0},
            {"node_id": "bob",   "side": "no",  "stake_amount": 10.0},
        ],
        base_ts=1_700_000_000.0,
        participants=5, total_stake=20.0,
    )
    chain += make_market_chain(
        "m2", "creator",
        outcome="no",
        predictions=[
            {"node_id": "alice", "side": "yes", "stake_amount": 5.0},
            {"node_id": "bob",   "side": "no",  "stake_amount": 5.0},
        ],
        base_ts=1_700_100_000.0,
        participants=5, total_stake=10.0,
    )
    lifetime = compute_oracle_rep_lifetime("alice", chain)
    assert lifetime == 20.0  # 20 from the win, no debit for the loss


def test_last_successful_prediction_ts_finds_most_recent_winning_market():
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
        base_ts=2_000_000.0,
        participants=5, total_stake=10.0,
    )
    ts = last_successful_prediction_ts("alice", chain)
    # Should be the m2 finalize timestamp, not m1.
    assert ts is not None
    assert ts >= 2_000_000.0


def test_invalid_market_does_NOT_set_last_successful_ts():
    """RULES §3.11 — INVALID markets do not reset the governance decay clock."""
    chain = make_market_chain(
        "m1", "creator",
        outcome="invalid",
        predictions=[{"node_id": "alice", "side": "yes", "probability_at_bet": 30.0}],
        participants=5, total_stake=10.0,
    )
    assert last_successful_prediction_ts("alice", chain) is None


def test_no_oracle_rep_from_uprep_or_governance_or_coin():
    """Constitutional: oracle rep source is predictions-only.

    A chain with upreps + petitions + coin transfers but no
    resolution_finalize must mint zero oracle rep.
    """
    from services.infonet.tests._chain_factory import make_event
    base = 1_700_000_000.0
    chain = [
        make_event("uprep", "alice", {"target_node_id": "bob", "target_event_id": "e1"},
                   timestamp=base, sequence=1),
        make_event("petition_file", "alice",
                   {"petition_id": "p1", "petition_payload":
                    {"type": "UPDATE_PARAM", "key": "vote_decay_days", "value": 30}},
                   timestamp=base + 1, sequence=2),
        make_event("petition_execute", "alice", {"petition_id": "p1"},
                   timestamp=base + 2, sequence=3),
        make_event("coin_transfer", "alice", {"to_node_id": "bob", "amount": 5},
                   timestamp=base + 3, sequence=4),
    ]
    assert compute_oracle_rep("alice", chain) == 0
    assert compute_oracle_rep("bob", chain) == 0
    assert compute_oracle_rep_lifetime("alice", chain) == 0
