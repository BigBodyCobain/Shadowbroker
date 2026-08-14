"""Regression coverage for malformed/non-finite market snapshot inputs."""

import math

import pytest

from services.infonet.markets.snapshot import build_snapshot, find_snapshot


def _prediction(node, side, stake, *, timestamp, sequence):
    payload = {"market_id": "m1", "side": side}
    if stake is not None:
        payload["stake_amount"] = stake
    return {
        "event_type": "prediction_place",
        "node_id": node,
        "timestamp": timestamp,
        "sequence": sequence,
        "payload": payload,
    }


def test_nonfinite_paid_stake_does_not_poison_snapshot():
    chain = [
        _prediction("alice", "yes", None, timestamp=100.0, sequence=1),
        _prediction("mallory", "no", float("inf"), timestamp=101.0, sequence=2),
    ]

    snapshot = build_snapshot("m1", chain, frozen_at=200.0)

    assert snapshot["frozen_participant_count"] == 1
    assert snapshot["frozen_predictor_ids"] == ["alice"]
    assert snapshot["frozen_total_stake"] == 0.0
    assert snapshot["frozen_probability_state"] == {"yes": 1.0, "no": 0.0}
    assert all(math.isfinite(v) for v in snapshot["frozen_probability_state"].values())


def test_malformed_ordering_metadata_does_not_break_snapshot_build():
    chain = [
        _prediction("alice", "yes", 5.0, timestamp="bad", sequence="bad"),
        _prediction("bob", "no", 5.0, timestamp=100.0, sequence=1),
    ]

    snapshot = build_snapshot("m1", chain, frozen_at=200.0)

    assert snapshot["frozen_participant_count"] == 2
    assert snapshot["frozen_total_stake"] == 10.0
    assert snapshot["frozen_probability_state"] == {"yes": 0.5, "no": 0.5}


def test_invalid_snapshot_ordering_does_not_outrank_valid_snapshot():
    invalid = {
        "event_type": "market_snapshot",
        "timestamp": "bad",
        "sequence": "bad",
        "payload": {"market_id": "m1", "marker": "invalid"},
    }
    valid = {
        "event_type": "market_snapshot",
        "timestamp": 100.0,
        "sequence": 1,
        "payload": {"market_id": "m1", "marker": "valid"},
    }

    assert find_snapshot("m1", [invalid, valid])["marker"] == "valid"


def test_nonfinite_frozen_at_is_rejected():
    with pytest.raises(ValueError, match="frozen_at must be finite"):
        build_snapshot("m1", [], frozen_at=float("nan"))
