"""Sprint 3 — easy-bet farming detection + enforcement.

Maps to IMPLEMENTATION_PLAN.md §1.2: "Farming detection (`farming_pct`)
... NEEDS penalty enforcement (60%/80% thresholds)."
"""

from __future__ import annotations

from services.infonet.config import CONFIG
from services.infonet.reputation import compute_oracle_rep
from services.infonet.reputation.anti_gaming import (
    compute_farming_pct,
    farming_multiplier,
)
from services.infonet.tests._chain_factory import make_event, make_market_chain


def _free_pred(market_id: str, node_id: str, side: str, prob: float, ts: float, seq: int) -> dict:
    return make_event(
        "prediction_place", node_id,
        {"market_id": market_id, "side": side, "probability_at_bet": prob},
        timestamp=ts, sequence=seq,
    )


def test_no_predictions_means_zero_farming():
    assert compute_farming_pct("alice", []) == 0.0


def test_all_easy_bets_pct_is_one():
    """Every prediction at 90% on the picked side → farming_pct = 1.0."""
    chain = [
        _free_pred("m1", "alice", "yes", 90.0, ts=100.0, seq=1),
        _free_pred("m2", "alice", "yes", 95.0, ts=200.0, seq=2),
        _free_pred("m3", "alice", "yes", 88.0, ts=300.0, seq=3),
    ]
    assert compute_farming_pct("alice", chain) == 1.0


def test_no_easy_bets_pct_is_zero():
    """50/50 picks are not easy bets."""
    chain = [
        _free_pred("m1", "alice", "yes", 50.0, ts=100.0, seq=1),
        _free_pred("m2", "alice", "no", 50.0, ts=200.0, seq=2),
    ]
    assert compute_farming_pct("alice", chain) == 0.0


def test_picked_side_probability_handles_no_pick():
    """A no-pick at p_yes=10 means picked-side probability is 90 → easy bet."""
    chain = [
        _free_pred("m1", "alice", "no", 10.0, ts=100.0, seq=1),
    ]
    # picked side = no → P(no) = 100 - 10 = 90 > 80 cutoff → easy.
    assert compute_farming_pct("alice", chain) == 1.0


def test_contrarian_prediction_is_not_easy():
    """A 'yes' at p_yes=10 (going against the chain consensus) is the
    opposite of farming."""
    chain = [
        _free_pred("m1", "alice", "yes", 10.0, ts=100.0, seq=1),
    ]
    assert compute_farming_pct("alice", chain) == 0.0


def test_farming_multiplier_below_soft_threshold_is_full():
    soft = float(CONFIG["farming_soft_threshold"])
    assert farming_multiplier(soft - 0.01) == 1.0
    assert farming_multiplier(0.0) == 1.0


def test_farming_multiplier_in_soft_band_is_half():
    soft = float(CONFIG["farming_soft_threshold"])
    hard = float(CONFIG["farming_hard_threshold"])
    assert farming_multiplier((soft + hard) / 2.0) == 0.50


def test_farming_multiplier_above_hard_threshold_is_tenth():
    hard = float(CONFIG["farming_hard_threshold"])
    assert farming_multiplier(hard + 0.001) == 0.10
    assert farming_multiplier(1.0) == 0.10


def test_oracle_rep_with_high_farming_is_reduced_to_ten_percent():
    """Integration: a node whose ALL free picks are easy bets gets 10%
    of normal mint when those picks resolve correctly.
    """
    base = 1_000_000.0
    chain = []
    chain += make_market_chain(
        "m1", "creator", outcome="yes",
        predictions=[{"node_id": "alice", "side": "yes", "probability_at_bet": 90.0}],
        base_ts=base,
        participants=5, total_stake=10.0,
    )
    chain += make_market_chain(
        "m2", "creator", outcome="yes",
        predictions=[{"node_id": "alice", "side": "yes", "probability_at_bet": 92.0}],
        base_ts=base + 100_000,
        participants=5, total_stake=10.0,
    )
    # alice has 100% easy bets → 10% multiplier.
    # Each market mint without farming: max(0.01, 1 - 0.90) = 0.10 and 0.08
    # Both correct. Total without farming = 0.18. With 10% farming = 0.018.
    rep = compute_oracle_rep("alice", chain)
    assert abs(rep - 0.018) < 1e-9


def test_staked_predictions_NOT_farming_penalized():
    """Spec semantics: farming applies to free picks, not staked
    positions where the farmer is risking actual rep."""
    base = 1_000_000.0
    chain = make_market_chain(
        "m1", "creator", outcome="yes",
        predictions=[
            # alice's only prediction is a STAKED easy bet — picked-side prob 92%.
            {"node_id": "alice", "side": "yes", "stake_amount": 10.0,
             "probability_at_bet": 92.0},
            {"node_id": "loser", "side": "no", "stake_amount": 10.0,
             "probability_at_bet": 92.0},
        ],
        base_ts=base, participants=5, total_stake=20.0,
    )
    # alice has 1/1 easy bets → farming_pct = 1.0 → 10% multiplier on FREE picks only.
    # Her staked return is unmultiplied: 20.0 (stake 10 + 10 from loser pool).
    rep = compute_oracle_rep("alice", chain)
    assert rep == 20.0
