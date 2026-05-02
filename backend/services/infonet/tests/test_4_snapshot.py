"""Sprint 4 — market snapshot freeze + immutability + canonical hash."""

from __future__ import annotations

from services.infonet.markets import (
    build_snapshot,
    compute_snapshot_event_hash,
    find_snapshot,
)
from services.infonet.tests._chain_factory import make_event


def _create(market_id: str, base_ts: float, seq: int = 1) -> dict:
    return make_event(
        "prediction_create", "creator",
        {"market_id": market_id, "market_type": "objective",
         "question": "?", "trigger_date": base_ts + 100, "creation_bond": 3},
        timestamp=base_ts, sequence=seq,
    )


def _place(market_id: str, node_id: str, side: str, *, ts: float, seq: int,
           stake: float | None = None, prob: float = 50.0) -> dict:
    payload = {"market_id": market_id, "side": side, "probability_at_bet": prob}
    if stake is not None:
        payload["stake_amount"] = stake
    return make_event("prediction_place", node_id, payload, timestamp=ts, sequence=seq)


def test_build_snapshot_counts_distinct_predictors():
    chain = [
        _create("m1", base_ts=0),
        _place("m1", "alice", "yes", ts=10, seq=2, stake=10.0),
        _place("m1", "bob", "no", ts=20, seq=3, stake=10.0),
        _place("m1", "carol", "yes", ts=30, seq=4),  # free pick
    ]
    snap = build_snapshot("m1", chain, frozen_at=100.0)
    assert snap["frozen_participant_count"] == 3
    assert set(snap["frozen_predictor_ids"]) == {"alice", "bob", "carol"}


def test_build_snapshot_total_stake_excludes_free_picks():
    chain = [
        _create("m1", base_ts=0),
        _place("m1", "alice", "yes", ts=10, seq=2, stake=10.0),
        _place("m1", "bob", "no", ts=20, seq=3, stake=15.0),
        _place("m1", "carol", "yes", ts=30, seq=4),  # free pick — virtual stake only
    ]
    snap = build_snapshot("m1", chain, frozen_at=100.0)
    # Free picks count as 1.0 *virtual* stake for probability math; do
    # NOT contribute to frozen_total_stake (which is real oracle rep).
    assert snap["frozen_total_stake"] == 25.0


def test_build_snapshot_probability_state_uses_virtual_free_picks():
    chain = [
        _create("m1", base_ts=0),
        _place("m1", "alice", "yes", ts=10, seq=2, stake=10.0),
        _place("m1", "bob", "no", ts=20, seq=3, stake=10.0),
        _place("m1", "carol", "yes", ts=30, seq=4),  # +1 virtual yes
    ]
    snap = build_snapshot("m1", chain, frozen_at=100.0)
    # yes pool = 10 + 1 = 11, no pool = 10. P(yes) = 11/21
    state = snap["frozen_probability_state"]
    assert abs(state["yes"] - 11 / 21) < 1e-9
    assert abs(state["no"] - 10 / 21) < 1e-9


def test_build_snapshot_first_predictor_p_is_50_50():
    chain = [_create("m1", base_ts=0)]
    snap = build_snapshot("m1", chain, frozen_at=100.0)
    assert snap["frozen_probability_state"] == {"yes": 0.5, "no": 0.5}


def test_snapshot_event_hash_deterministic():
    snap = {"market_id": "m1", "frozen_at": 100.0,
            "frozen_predictor_ids": ["a", "b"]}
    h1 = compute_snapshot_event_hash(snap, market_id="m1", creator_node_id="creator", sequence=5)
    h2 = compute_snapshot_event_hash(snap, market_id="m1", creator_node_id="creator", sequence=5)
    assert h1 == h2
    assert len(h1) == 64


def test_snapshot_event_hash_changes_on_payload_change():
    snap_a = {"market_id": "m1", "frozen_at": 100.0, "frozen_predictor_ids": ["a"]}
    snap_b = {"market_id": "m1", "frozen_at": 100.0, "frozen_predictor_ids": ["a", "b"]}
    h1 = compute_snapshot_event_hash(snap_a, market_id="m1", creator_node_id="c", sequence=1)
    h2 = compute_snapshot_event_hash(snap_b, market_id="m1", creator_node_id="c", sequence=1)
    assert h1 != h2


def test_snapshot_immutable_subsequent_event_ignored():
    """Critical Sprint 4 invariant: if a malicious node forges a second
    market_snapshot event, find_snapshot must return the FIRST one and
    ignore the forgery."""
    base = 0
    chain = [
        _create("m1", base_ts=base),
        make_event("market_snapshot", "creator",
                   {"market_id": "m1", "frozen_participant_count": 5,
                    "frozen_total_stake": 100.0, "frozen_predictor_ids": ["a"],
                    "frozen_probability_state": {"yes": 0.5, "no": 0.5},
                    "frozen_at": 100.0},
                   timestamp=100.0, sequence=2),
        # Attacker pushes a "corrected" snapshot later.
        make_event("market_snapshot", "attacker",
                   {"market_id": "m1", "frozen_participant_count": 999,
                    "frozen_total_stake": 99999.0, "frozen_predictor_ids": [],
                    "frozen_probability_state": {"yes": 0.99, "no": 0.01},
                    "frozen_at": 200.0},
                   timestamp=200.0, sequence=3),
    ]
    snap = find_snapshot("m1", chain)
    assert snap is not None
    assert snap["frozen_participant_count"] == 5
    assert snap["frozen_total_stake"] == 100.0
    assert snap["frozen_predictor_ids"] == ["a"]


def test_snapshot_only_uses_target_market_events():
    """Predictions for other markets must not pollute m1's snapshot."""
    chain = [
        _create("m1", base_ts=0),
        _create("m2", base_ts=1, seq=2),
        _place("m1", "alice", "yes", ts=10, seq=3, stake=5.0),
        _place("m2", "bob", "yes", ts=20, seq=4, stake=999.0),
    ]
    snap = build_snapshot("m1", chain, frozen_at=100.0)
    assert snap["frozen_participant_count"] == 1
    assert snap["frozen_predictor_ids"] == ["alice"]
    assert snap["frozen_total_stake"] == 5.0
