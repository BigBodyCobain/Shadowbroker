"""Sprint 3 — common_rep with VCS×clustering×temporal multipliers.

These are end-to-end tests of the full per-uprep formula (RULES §3.3):

    rep = upreper.oracle_rep × weight_factor × VCS × clustering × temporal

Verifies that adversarial chain shapes correctly reduce common rep,
and that legitimate single-uprep cases keep the Sprint 2 base value.
"""

from __future__ import annotations

from services.infonet.config import CONFIG
from services.infonet.reputation import compute_common_rep
from services.infonet.tests._chain_factory import make_event, make_market_chain


def _uprep(author: str, target: str, ts: float, seq: int) -> dict:
    return make_event(
        "uprep", author,
        {"target_node_id": target, "target_event_id": f"e-{author}-{target}-{seq}"},
        timestamp=ts, sequence=seq,
    )


def _seed_oracle_rep(node_id: str, base_ts: float, market_id: str) -> list[dict]:
    """Helper: build a chain that gives ``node_id`` 20.0 oracle rep via a
    won staked prediction. Deterministic so tests can assert exact mints."""
    return make_market_chain(
        market_id, "creator",
        outcome="yes",
        predictions=[
            {"node_id": node_id, "side": "yes", "stake_amount": 10.0,
             "probability_at_bet": 50.0},
            {"node_id": f"{node_id}-loser", "side": "no", "stake_amount": 10.0,
             "probability_at_bet": 50.0},
        ],
        base_ts=base_ts,
        participants=5, total_stake=20.0,
    )


def test_single_uprep_full_weight_matches_sprint2_base():
    """One legitimate upreper, no fans, no cluster, no burst → matches
    Sprint 2's untainted base formula."""
    base = 1_000_000.0
    chain = _seed_oracle_rep("ora", base, "m_seed")
    chain.append(_uprep("ora", "alice", ts=base + 10_000, seq=99))
    # ora has 20 oracle rep × 0.1 weight × 1 × 1 × 1 = 2.0
    assert compute_common_rep("alice", chain) == 2.0


def test_circle_jerk_collapses_common_rep_to_floor_band():
    """10 nodes circle-jerking each other and alice.

    The cabal first establishes its cross-network (every voter upreps
    every other voter), THEN each voter upreps alice — the upreps to
    alice are spaced apart by more than the 5-minute burst window so
    burst-multiplier does not apply (we want to assert the floor on
    VCS×clustering specifically, not a transient burst effect).

    Expected math:
      First alice-uprep: no other fans yet → VCS=1.0, clustering=0.0 →
        full mint = 2.0. This is correct protocol behavior — the
        cabal can't be detected from the very first uprep's POV.
      Subsequent 9 alice-upreps: cross-network is established, each
        face VCS floor 0.10 × clustering floor 0.20 → mint 2.0 × 0.02 = 0.04.

    Total = 2.0 + 9 × 0.04 = 2.36.

    The non-circle-jerk baseline (10 honest upreps with no cross-network)
    would mint 10 × 2.0 = 20.0. So the cabal extracts only ~12% of
    normal. That's the floor we assert against — not a hard 0 (the spec
    intentionally floors at vcs_min_weight × clustering_min_weight rather
    than zero, to keep "redemption_path_exists" working: a node who
    happens to be in a coincidentally-clustered network still earns
    some rep).
    """
    base = 1_000_000.0
    voters = [f"n{i}" for i in range(10)]
    chain: list[dict] = []
    seq = 0
    for v in voters:
        chain += _seed_oracle_rep(v, base + seq, f"m-{v}")
        seq += 100_000
    cross_start = base + seq + 1_000_000

    seq2 = 0
    # Phase 1: full cross-network. Every voter upreps every other voter.
    for v1 in voters:
        for v2 in voters:
            if v1 == v2:
                continue
            seq2 += 1
            chain.append(_uprep(v1, v2, ts=cross_start + seq2, seq=seq2 + 1000))

    # Phase 2: each voter upreps alice. Spaced > 5 min apart so the
    # burst penalty does not fire (300-sec window, half = 150 sec).
    alice_start = cross_start + seq2 + 10_000
    for i, v in enumerate(voters):
        chain.append(_uprep(v, "alice", ts=alice_start + i * 400, seq=10_000 + i))

    base_per_uprep = 20 * 0.1  # 2.0
    floor_v = float(CONFIG["vcs_min_weight"])
    floor_c = float(CONFIG["clustering_min_weight"])
    # 1 full-mint first uprep + 9 floored upreps.
    expected_max = base_per_uprep + 9 * base_per_uprep * floor_v * floor_c

    capped = compute_common_rep("alice", chain)
    assert capped <= expected_max + 1e-9, (
        f"circle-jerk produced {capped:.4f}, exceeds floor cap {expected_max:.4f}"
    )

    # And the cabal extracts ≤ ~12% of what 10 honest upreps would mint.
    honest_baseline = 10 * base_per_uprep
    assert capped < honest_baseline * 0.15
    assert capped > 0  # redemption_path_exists — never fully zeroed


def test_burst_alone_reduces_to_twenty_percent():
    """5 distinct upreps within 5 seconds of each other → burst → 0.2 multiplier
    AND each uprep also experiences clustering (n=5 voters who don't uprep
    each other → coefficient=0 → multiplier 1.0). VCS = 1.0 each because
    no upreper's targets overlap any other's fan set.

    Net: 5 × base × 1 × 1 × 0.2 = base.
    """
    base = 1_000_000.0
    chain: list[dict] = []
    voters = [f"v{i}" for i in range(5)]
    for i, v in enumerate(voters):
        chain += _seed_oracle_rep(v, base + i * 100_000, f"m-{v}")

    later = base + 5 * 100_000 + 1_000_000
    for i, v in enumerate(voters):
        chain.append(_uprep(v, "alice", ts=later + i, seq=1000 + i))

    # Each uprep: 20 × 0.1 = 2.0 base. Multipliers: VCS=1, clustering=1, burst=0.2.
    # Total = 5 × 2.0 × 0.2 = 2.0
    rep = compute_common_rep("alice", chain)
    assert abs(rep - 2.0) < 1e-9


def test_apply_anti_gaming_false_returns_base_formula():
    """Test escape hatch — turn off anti-gaming and the result is the
    raw Sprint 2 base (sum of upreper.oracle_rep × weight_factor)."""
    base = 1_000_000.0
    chain = []
    chain += _seed_oracle_rep("a", base, "m1")
    chain += _seed_oracle_rep("b", base + 100_000, "m2")
    later = base + 500_000
    chain.append(_uprep("a", "alice", ts=later, seq=200))
    chain.append(_uprep("b", "alice", ts=later + 1, seq=201))
    # Turn off all multipliers.
    raw = compute_common_rep("alice", chain, apply_anti_gaming=False)
    # 2 upreps × (20 oracle × 0.1) = 4.0
    assert raw == 4.0


def test_anti_gaming_layer_strictly_reduces_or_equals_base():
    """Property test: anti-gaming output ≤ base output for any chain."""
    base = 1_000_000.0
    chain: list[dict] = []
    voters = [f"v{i}" for i in range(6)]
    for i, v in enumerate(voters):
        chain += _seed_oracle_rep(v, base + i * 100_000, f"m-{v}")
    later = base + 6 * 100_000 + 1_000_000
    for i, v in enumerate(voters):
        chain.append(_uprep(v, "alice", ts=later + i, seq=2000 + i))
    raw = compute_common_rep("alice", chain, apply_anti_gaming=False)
    layered = compute_common_rep("alice", chain, apply_anti_gaming=True)
    assert layered <= raw + 1e-9
