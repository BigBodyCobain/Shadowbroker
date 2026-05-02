"""Sprint 6 — gate locking.

Maps to IMPLEMENTATION_PLAN §7.1 Sprint 6 row:
"Gate locking requires 5 members × 10 rep. Locked gate rules immutable."
"""

from __future__ import annotations

from services.infonet.config import CONFIG
from services.infonet.gates import (
    is_locked,
    locked_at,
    locked_by,
    validate_lock_request,
)
from services.infonet.tests._gate_factory import (
    make_gate_create,
    make_gate_enter,
    make_gate_lock,
)


def _setup_gate_with_n_members(n: int) -> tuple[list, list[str]]:
    """Returns (chain, member_ids). Members are named m0, m1, ..."""
    base = 1_000_000.0
    chain = [make_gate_create("g1", "creator", ts=base, seq=1)]
    members = [f"m{i}" for i in range(n)]
    for i, m in enumerate(members):
        chain.append(make_gate_enter("g1", m, ts=base + 100 + i, seq=2 + i))
    return chain, members


def test_unlocked_when_zero_locks():
    chain, _ = _setup_gate_with_n_members(5)
    assert not is_locked("g1", chain)


def test_locks_below_threshold_do_not_lock():
    chain, members = _setup_gate_with_n_members(5)
    base = 1_001_000.0
    threshold = int(CONFIG["gate_lock_min_members"])
    # threshold - 1 locks.
    for i, m in enumerate(members[:threshold - 1]):
        chain.append(make_gate_lock("g1", m, ts=base + i, seq=200 + i))
    assert not is_locked("g1", chain)


def test_locks_at_exact_threshold_lock_the_gate():
    chain, members = _setup_gate_with_n_members(5)
    base = 1_001_000.0
    threshold = int(CONFIG["gate_lock_min_members"])
    for i, m in enumerate(members[:threshold]):
        chain.append(make_gate_lock("g1", m, ts=base + i, seq=200 + i))
    assert is_locked("g1", chain)
    # locked_at is the timestamp of the LAST contributing lock.
    assert locked_at("g1", chain) == base + threshold - 1
    assert set(locked_by("g1", chain)) == set(members[:threshold])


def test_below_min_lock_cost_rejected():
    """A gate_lock event with lock_cost below CONFIG is ignored —
    cannot count toward the threshold."""
    chain, members = _setup_gate_with_n_members(5)
    base = 1_001_000.0
    cost_per = int(CONFIG["gate_lock_cost_per_member"])
    for i, m in enumerate(members):
        chain.append(make_gate_lock("g1", m, ts=base + i, seq=200 + i,
                                    lock_cost=cost_per - 1))
    assert not is_locked("g1", chain)


def test_lock_from_non_member_ignored():
    chain, members = _setup_gate_with_n_members(4)  # only 4 members
    base = 1_001_000.0
    # Add 5 locks but include a non-member (no entry event for "ghost").
    for i, m in enumerate(members + ["ghost"]):
        chain.append(make_gate_lock("g1", m, ts=base + i, seq=200 + i))
    # Only 4 valid locks — below threshold of 5.
    assert not is_locked("g1", chain)


def test_duplicate_locks_from_same_node_count_once():
    chain, members = _setup_gate_with_n_members(5)
    base = 1_001_000.0
    # 4 distinct members + 1 duplicate from m0 = 5 events but 4 distinct nodes.
    for i, m in enumerate(members[:4] + [members[0]]):
        chain.append(make_gate_lock("g1", m, ts=base + i, seq=200 + i))
    assert not is_locked("g1", chain)


def test_validate_lock_request_accepts_member():
    chain, members = _setup_gate_with_n_members(3)
    decision = validate_lock_request(members[0], "g1", chain)
    assert decision.accepted
    assert decision.cost == int(CONFIG["gate_lock_cost_per_member"])


def test_validate_lock_request_rejects_non_member():
    chain, _ = _setup_gate_with_n_members(3)
    decision = validate_lock_request("ghost", "g1", chain)
    assert not decision.accepted
    assert decision.reason == "not_a_member"


def test_validate_lock_request_rejects_below_min_cost():
    chain, members = _setup_gate_with_n_members(3)
    decision = validate_lock_request(
        members[0], "g1", chain,
        lock_cost=int(CONFIG["gate_lock_cost_per_member"]) - 1,
    )
    assert not decision.accepted
    assert decision.reason == "lock_cost_below_min"


def test_validate_lock_request_rejects_double_lock():
    chain, members = _setup_gate_with_n_members(5)
    base = 1_001_000.0
    chain.append(make_gate_lock("g1", members[0], ts=base, seq=200))
    decision = validate_lock_request(members[0], "g1", chain)
    assert not decision.accepted
    assert decision.reason == "already_locked_by_node"


def test_locked_gate_rules_unchanged_in_chain():
    """Once locked, the gate's static metadata (entry_sacrifice etc.)
    in get_gate_meta is unchanged. There is no on-chain event type
    that could mutate gate_create's rules — the immutability is
    structural."""
    chain, members = _setup_gate_with_n_members(5)
    base = 1_001_000.0
    threshold = int(CONFIG["gate_lock_min_members"])
    for i, m in enumerate(members[:threshold]):
        chain.append(make_gate_lock("g1", m, ts=base + i, seq=200 + i))
    assert is_locked("g1", chain)

    # The gate's metadata is read from its FIRST gate_create event.
    # find_snapshot-style first-write-wins: any forged subsequent
    # gate_create with a different gate_id is ignored. We verify by
    # appending a forged "amend" gate_create with conflicting rules.
    from services.infonet.gates import get_gate_meta
    from services.infonet.tests._gate_factory import make_gate_create
    chain.append(make_gate_create("g1", "attacker", ts=base + 99999, seq=99999,
                                  entry_sacrifice=0, min_overall_rep=0))
    meta = get_gate_meta("g1", chain)
    assert meta is not None
    assert meta.entry_sacrifice == 5  # original value, unchanged
    assert meta.creator_node_id == "creator"
