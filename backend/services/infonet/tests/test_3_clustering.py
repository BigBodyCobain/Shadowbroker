"""Sprint 3 — clustering coefficient adversarial tests.

Maps to IMPLEMENTATION_PLAN.md §7.1 Sprint 3 row:
"Clustering catches sophisticated farming."
"""

from __future__ import annotations

from services.infonet.config import CONFIG
from services.infonet.reputation.anti_gaming import (
    clustering_penalty,
    compute_clustering_coefficient,
)
from services.infonet.tests._chain_factory import make_event


def _uprep(author: str, target: str, ts: float, seq: int = 1) -> dict:
    return make_event(
        "uprep", author,
        {"target_node_id": target, "target_event_id": f"e-{author}-{target}-{seq}"},
        timestamp=ts, sequence=seq,
    )


def test_clustering_zero_voters_is_zero():
    assert compute_clustering_coefficient("alice", []) == 0.0


def test_clustering_single_voter_is_zero():
    chain = [_uprep("a", "alice", ts=1000.0)]
    assert compute_clustering_coefficient("alice", chain) == 0.0


def test_clustering_two_strangers_is_zero():
    chain = [
        _uprep("a", "alice", ts=1000.0, seq=1),
        _uprep("b", "alice", ts=1010.0, seq=2),
    ]
    assert compute_clustering_coefficient("alice", chain) == 0.0


def test_clustering_two_voters_who_uprep_each_other_is_one():
    chain = [
        _uprep("a", "alice", ts=1000.0, seq=1),
        _uprep("b", "alice", ts=1010.0, seq=2),
        _uprep("a", "b", ts=1020.0, seq=3),
    ]
    # Single edge a–b out of 1 possible.
    assert compute_clustering_coefficient("alice", chain) == 1.0


def test_clustering_complete_four_node_cabal_is_one():
    """A 4-node cabal that all uprep alice AND all uprep each other →
    clustering coefficient = 1.0.
    """
    voters = ["a", "b", "c", "d"]
    chain = [_uprep(v, "alice", ts=1000.0 + i, seq=i + 1) for i, v in enumerate(voters)]
    seq = 100
    for v1 in voters:
        for v2 in voters:
            if v1 == v2:
                continue
            seq += 1
            chain.append(_uprep(v1, v2, ts=2000.0 + seq, seq=seq))
    assert compute_clustering_coefficient("alice", chain) == 1.0


def test_clustering_partial_two_of_three_pairs_is_two_thirds():
    """3 voters → 3 possible pairs. 2 pairs are connected → 2/3."""
    chain = [
        _uprep("a", "alice", ts=1000.0, seq=1),
        _uprep("b", "alice", ts=1010.0, seq=2),
        _uprep("c", "alice", ts=1020.0, seq=3),
        # Edges: a–b, a–c (b–c missing)
        _uprep("a", "b", ts=1030.0, seq=4),
        _uprep("a", "c", ts=1040.0, seq=5),
    ]
    coef = compute_clustering_coefficient("alice", chain)
    assert abs(coef - (2 / 3)) < 1e-9


def test_clustering_penalty_floors_at_min_weight():
    """Coefficient = 1.0 → penalty = floor (clustering_min_weight)."""
    floor = float(CONFIG["clustering_min_weight"])
    assert clustering_penalty(1.0) == floor
    assert clustering_penalty(0.95) == floor  # 0.05 < 0.20 floor


def test_clustering_penalty_full_weight_for_zero_coefficient():
    assert clustering_penalty(0.0) == 1.0


def test_clustering_penalty_linear_in_window():
    """Above the floor, penalty = 1 - coefficient."""
    floor = float(CONFIG["clustering_min_weight"])
    # 0.5 coefficient → 0.5 penalty (above 0.20 floor)
    assert clustering_penalty(0.5) == 0.5
    # 0.79 coefficient → 0.21 penalty (above 0.20 floor)
    assert abs(clustering_penalty(0.79) - 0.21) < 1e-9
    # 0.81 coefficient → 0.19 < floor → clamped
    assert clustering_penalty(0.81) == floor
