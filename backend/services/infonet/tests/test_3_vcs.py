"""Sprint 3 — Vote Correlation Score adversarial tests.

Maps to IMPLEMENTATION_PLAN.md §7.1 Sprint 3 row:
"VCS detects 10-account circle-jerk (overlap → 0.11 effective weight)."

The spec floor is ``vcs_min_weight = 0.10``. The plan calls out 0.11
("11% effective weight") as the visible result of a saturated
circle-jerk; we assert the strict mathematical floor (0.10) plus the
practical "as-many-as-needed-to-saturate" property.
"""

from __future__ import annotations

from services.infonet.config import CONFIG
from services.infonet.reputation.anti_gaming import compute_vcs
from services.infonet.tests._chain_factory import make_event


def _uprep(author: str, target: str, ts: float, seq: int = 1) -> dict:
    return make_event(
        "uprep", author,
        {"target_node_id": target, "target_event_id": f"e-{author}-{target}-{seq}"},
        timestamp=ts, sequence=seq,
    )


def test_vcs_no_other_voters_returns_full_weight():
    """B has no other fans → overlap=0 → multiplier=1.0."""
    chain = [_uprep("ora", "alice", ts=1000.0)]
    assert compute_vcs("ora", "alice", chain) == 1.0


def test_vcs_unique_authors_with_disjoint_targets_returns_full_weight():
    """A and B's fans uprep totally different sets → overlap=0."""
    chain = [
        _uprep("a", "alice", ts=1000.0, seq=1),
        _uprep("a", "x", ts=1010.0, seq=2),
        _uprep("a", "y", ts=1020.0, seq=3),
        _uprep("b", "alice", ts=1030.0, seq=4),
        _uprep("c", "alice", ts=1040.0, seq=5),
        # b and c uprep someone NOT in a's target set
        _uprep("b", "z", ts=1050.0, seq=6),
        _uprep("c", "w", ts=1060.0, seq=7),
    ]
    assert compute_vcs("a", "alice", chain) == 1.0


def test_vcs_full_overlap_returns_floor():
    """B's fans = A's targets exactly → overlap=1.0 → floor."""
    chain = [
        _uprep("a", "alice", ts=1000.0, seq=1),
        # a upreps everyone who upreps alice (besides a herself)
        _uprep("a", "b", ts=1010.0, seq=2),
        _uprep("a", "c", ts=1020.0, seq=3),
        _uprep("a", "d", ts=1030.0, seq=4),
        # b, c, d all uprep alice
        _uprep("b", "alice", ts=1040.0, seq=5),
        _uprep("c", "alice", ts=1050.0, seq=6),
        _uprep("d", "alice", ts=1060.0, seq=7),
    ]
    assert compute_vcs("a", "alice", chain) == float(CONFIG["vcs_min_weight"])


def test_vcs_ten_account_circle_jerk_falls_to_floor():
    """The 'circle-jerk' adversarial scenario from the plan: 10 accounts
    that all uprep each other, plus alice. From any one upreper's POV,
    every other voter is also one of their targets → overlap → 1.0 →
    weight floor.
    """
    nodes = [f"n{i}" for i in range(10)]
    chain: list[dict] = []
    seq = 0
    base = 1000.0
    # Each node upreps every other node (and alice).
    for i, author in enumerate(nodes):
        for j, target in enumerate(nodes):
            if i == j:
                continue
            seq += 1
            chain.append(_uprep(author, target, ts=base + seq, seq=seq))
        seq += 1
        chain.append(_uprep(author, "alice", ts=base + seq, seq=seq))
    # Pick any node's uprep to alice — the multiplier must be the floor.
    assert compute_vcs("n0", "alice", chain) == float(CONFIG["vcs_min_weight"])
    assert compute_vcs("n5", "alice", chain) == float(CONFIG["vcs_min_weight"])


def test_vcs_partial_overlap_scales_linearly():
    """Half of B's fans are in A's targets → overlap=0.5 → multiplier=0.5."""
    chain = [
        # a's targets: x, y (ignore alice — VCS excludes target itself)
        _uprep("a", "alice", ts=1000.0, seq=1),
        _uprep("a", "x", ts=1010.0, seq=2),
        _uprep("a", "y", ts=1020.0, seq=3),
        # alice's other fans: x (in a's set), z (not)
        _uprep("x", "alice", ts=1030.0, seq=4),
        _uprep("z", "alice", ts=1040.0, seq=5),
    ]
    # B_fans (excluding a) = {x, z}. A_targets = {alice, x, y}.
    # overlap = |{x}| / |{x,z}| = 0.5 → multiplier 0.5.
    assert compute_vcs("a", "alice", chain) == 0.5


def test_vcs_outside_decay_window_excluded():
    """Old upreps drop out of the window."""
    decay_days = float(CONFIG["vote_decay_days"])
    base = 1_000_000.0
    chain = [
        # a's old uprep to b, far outside the window relative to "now=base"
        _uprep("a", "b", ts=base - (decay_days + 5) * 86400.0, seq=1),
        # b's recent uprep to alice
        _uprep("b", "alice", ts=base - 100, seq=2),
        # a's recent uprep to alice
        _uprep("a", "alice", ts=base, seq=3),
    ]
    # a's old uprep to b is OUT of window → A_targets excludes b at now=base.
    # B_fans = {b}. overlap = 0 → full weight.
    assert compute_vcs("a", "alice", chain, now=base) == 1.0


def test_vcs_self_uprep_returns_full_weight():
    chain = [_uprep("a", "a", ts=1000.0)]
    # Self-uprep is filtered upstream; VCS no-ops to 1.0.
    assert compute_vcs("a", "a", chain) == 1.0


def test_vcs_empty_inputs_safe():
    assert compute_vcs("", "alice", []) == float(CONFIG["vcs_min_weight"])
    assert compute_vcs("a", "", []) == float(CONFIG["vcs_min_weight"])
    assert compute_vcs("a", "alice", []) == 1.0
