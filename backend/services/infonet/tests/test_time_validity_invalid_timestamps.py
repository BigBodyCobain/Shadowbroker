"""Regression coverage for malformed chain timestamps."""

from typing import Any

from services.infonet.time_validity import chain_majority_time, is_event_too_future


def _event(node_id: str, timestamp: Any) -> dict[str, Any]:
    return {"node_id": node_id, "timestamp": timestamp}


def test_chain_majority_time_ignores_malformed_and_nonfinite_timestamps() -> None:
    chain = [
        _event("valid-a", 10.0),
        _event("bad-text", "not-a-timestamp"),
        _event("bad-nan", float("nan")),
        _event("bad-inf", float("inf")),
        _event("valid-b", 20.0),
    ]

    assert chain_majority_time(chain) == 15.0


def test_chain_majority_time_accepts_finite_numeric_strings() -> None:
    chain = [_event("a", "10.5"), _event("b", "20.5")]

    assert chain_majority_time(chain) == 15.5


def test_future_check_fails_closed_for_invalid_timestamps() -> None:
    assert is_event_too_future(_event("bad-text", "not-a-timestamp"), chain_time=100.0)
    assert is_event_too_future(_event("bad-nan", float("nan")), chain_time=100.0)
    assert is_event_too_future(_event("bad-inf", float("inf")), chain_time=100.0)


def test_future_check_preserves_valid_timestamp_behavior() -> None:
    assert not is_event_too_future(_event("near", 110.0), chain_time=100.0)
    assert is_event_too_future(_event("far", 10_000.0), chain_time=100.0)
