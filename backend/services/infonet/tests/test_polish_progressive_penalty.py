"""Polish — progressive penalty wiring + correlation aggregate.

Verifies that Sprint 3's progressive-penalty math is now wired into
the live ``compute_common_rep`` path via the aggregate correlation
score (Sprint 10 polish 2026-04-28).

The penalty is gated on ``CONFIG['progressive_penalty_threshold']``
which defaults to ``0.0`` (disabled). Tests exercise both the
disabled default behavior AND the post-threshold-bump behavior.
"""

from __future__ import annotations

from services.infonet.config import CONFIG
from services.infonet.reputation import compute_common_rep
from services.infonet.reputation.anti_gaming.correlation_score import (
    compute_node_correlation_score,
    progressive_penalty_multiplier_for,
)
from services.infonet.tests._chain_factory import make_event, make_market_chain


def _uprep(author: str, target: str, ts: float, seq: int) -> dict:
    return make_event(
        "uprep", author,
        {"target_node_id": target, "target_event_id": f"e-{author}-{target}-{seq}"},
        timestamp=ts, sequence=seq,
    )


def _seed_oracle_rep(node_id: str, base_ts: float, market_id: str) -> list[dict]:
    return make_market_chain(
        market_id, "creator",
        outcome="yes",
        predictions=[
            {"node_id": node_id, "side": "yes", "stake_amount": 10.0},
            {"node_id": f"{node_id}-loser", "side": "no", "stake_amount": 10.0},
        ],
        base_ts=base_ts, participants=5, total_stake=20.0,
    )


# ── Aggregate correlation score ────────────────────────────────────────

def test_correlation_score_zero_when_no_upreps():
    assert compute_node_correlation_score("alice", []) == 0.0


def test_correlation_score_zero_for_independent_uprepers():
    """Single uprep from a clean upreper → no correlation evidence."""
    base = 1_000_000.0
    chain = _seed_oracle_rep("ora", base, "m1")
    chain.append(_uprep("ora", "alice", ts=base + 10_000, seq=99))
    score = compute_node_correlation_score("alice", chain)
    # VCS = 1.0 (no overlap with empty B_fans) → 1 - 1 = 0.0.
    assert score == 0.0


def test_correlation_score_high_for_circle_jerk_target():
    """In a saturated circle-jerk, aggregate correlation approaches
    1 - vcs_min_weight (default 0.10) = 0.90."""
    base = 1_000_000.0
    voters = [f"n{i}" for i in range(10)]
    chain: list[dict] = []
    seq = 0
    for v in voters:
        chain += _seed_oracle_rep(v, base + seq, f"m-{v}")
        seq += 100_000
    cross_start = base + seq + 1_000_000
    seq2 = 0
    for v1 in voters:
        for v2 in voters:
            if v1 == v2:
                continue
            seq2 += 1
            chain.append(_uprep(v1, v2, ts=cross_start + seq2, seq=seq2 + 1000))
    alice_start = cross_start + seq2 + 10_000
    for i, v in enumerate(voters):
        chain.append(_uprep(v, "alice", ts=alice_start + i * 400, seq=10_000 + i))
    score = compute_node_correlation_score("alice", chain)
    # Most upreps face VCS floor of 0.10 → correlation evidence ≈ 0.90.
    assert score > 0.5


# ── Penalty disabled when threshold = 0 (default) ───────────────────────

def test_progressive_penalty_disabled_by_default():
    """CONFIG['progressive_penalty_threshold'] defaults to 0.0 → no
    penalty applied. Common-rep returns the same value as Sprint 3
    behavior."""
    assert float(CONFIG["progressive_penalty_threshold"]) == 0.0
    base = 1_000_000.0
    chain = _seed_oracle_rep("ora", base, "m1")
    chain.append(_uprep("ora", "alice", ts=base + 10_000, seq=99))
    rep = compute_common_rep("alice", chain)
    # ora has 20 oracle rep × 0.10 weight × 1 (single uprep, no penalty) = 2.0.
    assert rep == 2.0


def test_progressive_penalty_kicks_in_above_threshold():
    """When governance raises the threshold above 0, nodes with
    high aggregate correlation get reduced common-rep payouts."""
    base = 1_000_000.0
    # Build a circle-jerk targeting alice.
    voters = [f"n{i}" for i in range(10)]
    chain: list[dict] = []
    seq = 0
    for v in voters:
        chain += _seed_oracle_rep(v, base + seq, f"m-{v}")
        seq += 100_000
    cross_start = base + seq + 1_000_000
    seq2 = 0
    for v1 in voters:
        for v2 in voters:
            if v1 == v2:
                continue
            seq2 += 1
            chain.append(_uprep(v1, v2, ts=cross_start + seq2, seq=seq2 + 1000))
    alice_start = cross_start + seq2 + 10_000
    for i, v in enumerate(voters):
        chain.append(_uprep(v, "alice", ts=alice_start + i * 400, seq=10_000 + i))

    # Without penalty (threshold=0).
    rep_unpenalized = compute_common_rep("alice", chain)
    # Bump threshold via simulated governance petition.
    original = CONFIG["progressive_penalty_threshold"]
    try:
        CONFIG["progressive_penalty_threshold"] = 0.5
        rep_penalized = compute_common_rep("alice", chain)
        # Penalized rep is strictly less than unpenalized (the cabal's
        # extracted rep is reduced by the whale-deterrence multiplier).
        assert rep_penalized < rep_unpenalized
    finally:
        CONFIG["progressive_penalty_threshold"] = original


def test_progressive_penalty_helper_returns_one_when_disabled():
    """Sanity: the helper returns 1.0 when the threshold is the
    default 0.0 — preserving Sprint 3 behavior structurally."""
    assert progressive_penalty_multiplier_for(
        "alice", [], oracle_rep=1024.0,
    ) == 1.0


def test_progressive_penalty_helper_returns_one_below_threshold():
    """Even when the threshold is bumped, a node with score below it
    sees no penalty."""
    base = 1_000_000.0
    chain = _seed_oracle_rep("ora", base, "m1")
    chain.append(_uprep("ora", "alice", ts=base + 10_000, seq=99))
    original = CONFIG["progressive_penalty_threshold"]
    try:
        CONFIG["progressive_penalty_threshold"] = 0.5
        # Single clean uprep → score ≈ 0.0 → no penalty.
        m = progressive_penalty_multiplier_for(
            "alice", chain, oracle_rep=1024.0,
        )
        assert m == 1.0
    finally:
        CONFIG["progressive_penalty_threshold"] = original
