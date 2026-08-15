"""Regression coverage for malformed/non-finite market snapshot numerics."""

import math
from typing import Any

import pytest

from services.infonet.markets.snapshot import build_snapshot


def _prediction(
    node: str,
    side: str,
    stake: Any,
    *,
    timestamp: float,
    sequence: int,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"market_id": "m1", "side": side}
    if stake is not None:
        payload["stake_amount"] = stake
    return {
        "event_type": "prediction_place",
        "node_id": node,
        "timestamp": timestamp,
        "sequence": sequence,
        "payload": payload,
    }


@pytest.mark.parametrize("invalid_stake", [float("nan"), float("inf"), "not-a-number", -1.0, 0.0])
def test_invalid_paid_stake_does_not_poison_or_count_snapshot(invalid_stake: Any) -> None:
    chain = [
        _prediction("alice", "yes", None, timestamp=100.0, sequence=1),
        _prediction("mallory", "no", invalid_stake, timestamp=101.0, sequence=2),
    ]

    snapshot = build_snapshot("m1", chain, frozen_at=200.0)

    assert snapshot["frozen_participant_count"] == 1
    assert snapshot["frozen_predictor_ids"] == ["alice"]
    assert snapshot["frozen_total_stake"] == 0.0
    assert snapshot["frozen_probability_state"] == {"yes": 1.0, "no": 0.0}
    assert all(math.isfinite(v) for v in snapshot["frozen_probability_state"].values())


def test_finite_numeric_string_stake_is_preserved() -> None:
    chain = [
        _prediction("alice", "yes", "2.5", timestamp=100.0, sequence=1),
        _prediction("bob", "no", "7.5", timestamp=101.0, sequence=2),
    ]

    snapshot = build_snapshot("m1", chain, frozen_at="200.5")

    assert snapshot["frozen_participant_count"] == 2
    assert snapshot["frozen_total_stake"] == 10.0
    assert snapshot["frozen_probability_state"] == {"yes": 0.25, "no": 0.75}
    assert snapshot["frozen_at"] == 200.5


@pytest.mark.parametrize("invalid_frozen_at", [float("nan"), float("inf"), "not-a-time"])
def test_nonfinite_or_malformed_frozen_at_is_rejected(invalid_frozen_at: Any) -> None:
    with pytest.raises(ValueError, match="frozen_at must be finite"):
        build_snapshot("m1", [], frozen_at=invalid_frozen_at)
