"""Sprint 6 — sacrifice burn-on-entry mechanic.

Maps to IMPLEMENTATION_PLAN §7.1 Sprint 6 row:
"Sacrifice burns rep on entry (not refundable)."
"""

from __future__ import annotations

from services.infonet.gates import can_enter, compute_member_set, is_member
from services.infonet.tests._chain_factory import make_market_chain
from services.infonet.tests._gate_factory import (
    make_gate_create,
    make_gate_enter,
    make_gate_exit,
)


def test_unknown_gate_cannot_be_entered():
    decision = can_enter("alice", "no-such-gate", [])
    assert not decision.accepted
    assert decision.refusals[0].kind == "gate_not_found"


def test_can_enter_with_sufficient_rep():
    base = 1_000_000.0
    chain = []
    # Give alice enough common rep through an uprep from an oracle holder.
    chain += make_market_chain(
        "m1", "creator", outcome="yes",
        predictions=[
            {"node_id": "ora", "side": "yes", "stake_amount": 50.0},
            {"node_id": "loser", "side": "no", "stake_amount": 50.0},
        ],
        base_ts=base, participants=5, total_stake=100.0,
    )
    # Many upreps from ora to alice → alice has substantial common rep.
    from services.infonet.tests._chain_factory import make_event
    for i in range(3):
        chain.append(make_event(
            "uprep", "ora",
            {"target_node_id": "alice", "target_event_id": f"e{i}"},
            timestamp=base + 10_000 + i * 1000, sequence=100 + i,
        ))
    chain.append(make_gate_create("g1", "creator", ts=base + 20_000, seq=200,
                                  entry_sacrifice=5, min_overall_rep=0))
    decision = can_enter("alice", "g1", chain)
    assert decision.accepted
    assert decision.cost == 5


def test_insufficient_rep_refused_with_diagnostic():
    base = 1_000_000.0
    chain = [make_gate_create("g1", "creator", ts=base, seq=1,
                              entry_sacrifice=10, min_overall_rep=0)]
    decision = can_enter("alice", "g1", chain)
    assert not decision.accepted
    refusal_kinds = {r.kind for r in decision.refusals}
    assert "insufficient_common_rep" in refusal_kinds


def test_member_set_after_enter_and_exit():
    base = 1_000_000.0
    chain = [
        make_gate_create("g1", "creator", ts=base, seq=1),
        make_gate_enter("g1", "alice", ts=base + 100, seq=2),
        make_gate_enter("g1", "bob", ts=base + 200, seq=3),
        make_gate_exit("g1", "alice", ts=base + 300, seq=4),
    ]
    members = compute_member_set("g1", chain)
    assert members == {"bob"}


def test_already_member_cannot_re_enter():
    base = 1_000_000.0
    chain = [
        make_gate_create("g1", "creator", ts=base, seq=1, entry_sacrifice=0),
        make_gate_enter("g1", "alice", ts=base + 100, seq=2),
    ]
    decision = can_enter("alice", "g1", chain)
    assert not decision.accepted
    assert decision.refusals[0].kind == "already_member"


def test_voluntary_exit_does_not_refund_sacrifice():
    """Sacrifice is BURNED on entry. Voluntary exit removes member
    status but does NOT credit sacrifice back. The chain has no
    refund event — that's the structural enforcement.
    """
    base = 1_000_000.0
    chain = [
        make_gate_create("g1", "creator", ts=base, seq=1, entry_sacrifice=10),
        make_gate_enter("g1", "alice", ts=base + 100, seq=2, sacrifice=10),
        make_gate_exit("g1", "alice", ts=base + 200, seq=3),
    ]
    # alice is no longer a member.
    assert not is_member("alice", "g1", chain)
    # No "gate_refund" event exists in the schema. The sacrifice is
    # gone from the system permanently — common_rep view never gets
    # it back. (This is a structural / definitional invariant: the
    # protocol doesn't have an event type that could refund a
    # sacrifice. Asserting that here as a marker for future AIs.)
    from services.infonet.schema import INFONET_ECONOMY_EVENT_TYPES
    refund_event_types = {t for t in INFONET_ECONOMY_EVENT_TYPES if "refund" in t}
    assert refund_event_types == set()


def test_shutdown_voids_member_set():
    """When a gate is shutdown, the member set zeroes out — members
    are released but lose access. (Sprint 6: sacrifice is already
    burned by then.)"""
    base = 1_000_000.0
    chain = [
        make_gate_create("g1", "creator", ts=base, seq=1),
        make_gate_enter("g1", "alice", ts=base + 100, seq=2),
        make_gate_enter("g1", "bob", ts=base + 200, seq=3),
        # Synthesize a shutdown_execute event.
        {"event_type": "gate_shutdown_execute",
         "node_id": "creator", "timestamp": base + 1000, "sequence": 99,
         "payload": {"petition_id": "p1", "gate_id": "g1"}},
    ]
    assert compute_member_set("g1", chain) == set()
