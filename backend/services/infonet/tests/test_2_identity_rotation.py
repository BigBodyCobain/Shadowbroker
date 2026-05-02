"""Sprint 2 — identity rotation gates and descendant tracking.

Maps to IMPLEMENTATION_PLAN.md §7.1 Sprint 2 row:
"Identity rotation during active stakes is rejected."

The non-hostile UX rule (BUILD_LOG.md cross-cutting design rule #1)
also applies: rejection MUST come back as structured ``RotationBlocker``
data so the UI can offer the user a path forward, not a 4xx wall.
"""

from __future__ import annotations

import pytest

from services.infonet.identity_rotation import (
    RotationBlocker,
    RotationDecision,
    rotation_descendants,
    validate_rotation,
)
from services.infonet.tests._chain_factory import make_event, make_market_chain


def _rotation_event(old: str, new: str, *, ts: float = 2_000_000.0) -> dict:
    return make_event(
        "identity_rotate",
        new,  # signed by the new identity
        {
            "old_node_id": old,
            "old_public_key": "old-pk",
            "old_public_key_algo": "ed25519",
            "new_public_key": "new-pk",
            "new_public_key_algo": "ed25519",
            "old_signature": "sig",
        },
        timestamp=ts,
        sequence=1,
    )


def test_rotation_with_no_active_stakes_accepted():
    chain: list[dict] = []
    decision = validate_rotation(_rotation_event("alice", "alice2"), chain, now=2_000_000.0)
    assert decision.accepted
    assert decision.blockers == ()


def test_rotation_blocked_by_active_resolution_stake():
    """resolution_stake exists for an unfinalized market → reject."""
    base = 1_700_000_000.0
    # Set up a market in the resolution phase but NOT finalized.
    chain = [
        make_event("prediction_create", "creator",
                   {"market_id": "m1", "market_type": "objective",
                    "question": "?", "trigger_date": base + 1, "creation_bond": 3},
                   timestamp=base, sequence=1),
        make_event("market_snapshot", "creator",
                   {"market_id": "m1", "frozen_participant_count": 5,
                    "frozen_total_stake": 10.0, "frozen_predictor_ids": [],
                    "frozen_probability_state": {"yes": 0.5, "no": 0.5},
                    "frozen_at": base + 100},
                   timestamp=base + 100, sequence=2),
        make_event("resolution_stake", "alice",
                   {"market_id": "m1", "side": "yes", "amount": 5.0, "rep_type": "oracle"},
                   timestamp=base + 200, sequence=3),
    ]
    decision = validate_rotation(_rotation_event("alice", "alice2"), chain, now=base + 300)
    assert not decision.accepted
    assert any(b.kind == "resolution_stake" for b in decision.blockers)
    res_blocker = next(b for b in decision.blockers if b.kind == "resolution_stake")
    assert res_blocker.count == 1
    assert "m1" in res_blocker.sample_ids


def test_rotation_unblocked_after_market_finalizes():
    base = 1_700_000_000.0
    chain = make_market_chain(
        "m1", "creator",
        outcome="yes",
        predictions=[{"node_id": "alice", "side": "yes", "probability_at_bet": 30.0}],
        base_ts=base,
    )
    # Plus a resolution_stake from alice that the chain factory does NOT add.
    chain.append(make_event(
        "resolution_stake", "alice",
        {"market_id": "m1", "side": "yes", "amount": 5.0, "rep_type": "oracle"},
        timestamp=base + 5000, sequence=99,
    ))
    # Market finalized in make_market_chain → status is "final" → not blocking.
    decision = validate_rotation(_rotation_event("alice", "alice2"), chain, now=base + 8000)
    assert decision.accepted


def test_rotation_blocked_by_active_dispute_stake():
    base = 1_700_000_000.0
    chain = [
        make_event("dispute_open", "alice",
                   {"market_id": "m1", "challenger_stake": 5.0, "reason": "wrong"},
                   timestamp=base, sequence=1),
        make_event("dispute_stake", "alice",
                   {"dispute_id": "d1", "side": "confirm", "amount": 5.0, "rep_type": "oracle"},
                   timestamp=base + 100, sequence=2),
    ]
    decision = validate_rotation(_rotation_event("alice", "alice2"), chain, now=base + 200)
    assert not decision.accepted
    assert any(b.kind == "dispute_stake" for b in decision.blockers)


def test_rotation_blocked_by_active_truth_stake():
    base = 1_700_000_000.0
    chain = [
        make_event("truth_stake_place", "alice",
                   {"message_id": "msg1", "poster_id": "bob", "side": "truth",
                    "amount": 5.0, "duration_days": 3},
                   timestamp=base, sequence=1),
    ]
    # Within the 3-day window — still active.
    decision = validate_rotation(_rotation_event("alice", "alice2"), chain, now=base + 86400)
    assert not decision.accepted
    truth_blockers = [b for b in decision.blockers if b.kind == "truth_stake"]
    assert truth_blockers and truth_blockers[0].count == 1


def test_rotation_unblocked_after_truth_stake_resolves():
    base = 1_700_000_000.0
    chain = [
        make_event("truth_stake_place", "alice",
                   {"message_id": "msg1", "poster_id": "bob", "side": "truth",
                    "amount": 5.0, "duration_days": 3},
                   timestamp=base, sequence=1),
        make_event("truth_stake_resolve", "creator",
                   {"message_id": "msg1", "outcome": "truth"},
                   timestamp=base + 100, sequence=2),
    ]
    decision = validate_rotation(_rotation_event("alice", "alice2"), chain, now=base + 86400)
    assert decision.accepted


def test_rotation_unblocked_after_truth_stake_window_expires():
    base = 1_700_000_000.0
    chain = [
        make_event("truth_stake_place", "alice",
                   {"message_id": "msg1", "poster_id": "bob", "side": "truth",
                    "amount": 5.0, "duration_days": 3},
                   timestamp=base, sequence=1),
    ]
    # > 3 days past → window closed even without resolve event.
    decision = validate_rotation(_rotation_event("alice", "alice2"), chain, now=base + 4 * 86400)
    assert decision.accepted


def test_rotation_blockers_include_structured_diagnostic():
    """UX contract: every blocker carries kind + count + sample_ids
    so the UI can offer a non-hostile retry path."""
    base = 1_700_000_000.0
    chain = [
        make_event("resolution_stake", "alice",
                   {"market_id": "m1", "side": "yes", "amount": 5.0, "rep_type": "oracle"},
                   timestamp=base, sequence=1),
        make_event("resolution_stake", "alice",
                   {"market_id": "m2", "side": "no", "amount": 5.0, "rep_type": "oracle"},
                   timestamp=base + 1, sequence=2),
    ]
    decision = validate_rotation(_rotation_event("alice", "alice2"), chain, now=base + 100)
    assert isinstance(decision, RotationDecision)
    assert not decision.accepted
    res_blocker = next(b for b in decision.blockers if b.kind == "resolution_stake")
    assert isinstance(res_blocker, RotationBlocker)
    assert res_blocker.count == 2
    assert set(res_blocker.sample_ids) == {"m1", "m2"}


def test_rotation_descendants_simple_chain():
    base = 2_000_000.0
    chain = [
        _rotation_event("alice", "alice2", ts=base),
        _rotation_event("alice2", "alice3", ts=base + 100),
        _rotation_event("alice3", "alice4", ts=base + 200),
    ]
    desc = rotation_descendants("alice", chain)
    assert desc == {"alice2", "alice3", "alice4"}


def test_rotation_descendants_handles_branching():
    """Pathological case: a single old_node_id appears in two
    rotations (key compromise scenario). Both branches are followed."""
    base = 2_000_000.0
    chain = [
        _rotation_event("alice", "alice2", ts=base),
        _rotation_event("alice", "alice_alt", ts=base + 50),
        _rotation_event("alice2", "alice3", ts=base + 100),
    ]
    desc = rotation_descendants("alice", chain)
    assert desc == {"alice2", "alice3", "alice_alt"}


def test_rotation_descendants_excludes_self():
    base = 2_000_000.0
    chain = [_rotation_event("alice", "alice2", ts=base)]
    desc = rotation_descendants("alice", chain)
    assert "alice" not in desc


def test_rotation_descendants_terminates_on_cycle():
    """Defense against malicious self-cycle: must not infinite-loop."""
    base = 2_000_000.0
    chain = [
        _rotation_event("alice", "alice2", ts=base),
        _rotation_event("alice2", "alice", ts=base + 100),  # forbidden in production but defensive
    ]
    desc = rotation_descendants("alice", chain)
    # The cycle bridges alice → alice2 → alice. Self-rotations to the
    # same id are filtered earlier; cross-cycles are clamped by the
    # "already seen" check.
    assert "alice2" in desc


def test_validate_rotation_rejects_non_rotation_event():
    with pytest.raises(ValueError):
        validate_rotation(make_event("uprep", "x", {"target_node_id": "y", "target_event_id": "e"},
                                     timestamp=1, sequence=1), [], now=2.0)


def test_validate_rotation_rejects_missing_old_node_id():
    base = 2_000_000.0
    bad = _rotation_event("alice", "alice2", ts=base)
    bad["payload"].pop("old_node_id")
    with pytest.raises(ValueError):
        validate_rotation(bad, [], now=base + 1)
