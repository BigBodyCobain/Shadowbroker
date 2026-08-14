"""Regression coverage for malformed chain timestamps."""

from services.infonet.time_validity import chain_majority_time, is_event_too_future


def _event(node_id: str, timestamp):
    return {"node_id": node_id, "timestamp": timestamp}


def test_chain_majority_time_ignores_malformed_and_nonfinite_timestamps():
    chain = [
        _event("valid-a", 10.0),
        _event("bad-text", "not-a-timestamp"),
        _event("bad-nan", float("nan")),
        _event("bad-inf", float("inf")),
        _event("valid-b", 20.0),
    ]

    assert chain_majority_time(chain) == 15.0


def test_chain_majority_time_accepts_finite_numeric_strings():
    chain = [_event("a", "10.5"), _event("b", "20.5")]

    assert chain_majority_time(chain) == 15.5


def test_future_check_does_not_treat_nonfinite_timestamp_as_valid():
    assert not is_event_too_future(_event("a", float("nan")), chain_time=100.0)
    assert not is_event_too_future(_event("a", float("inf")), chain_time=100.0)
