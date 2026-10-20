"""Regression coverage for malformed market lifecycle ordering metadata."""

from typing import Any

import pytest

from services.infonet.config import CONFIG
from services.infonet.markets import MarketStatus, compute_market_status, should_advance_phase
from services.infonet.markets.event_selection import events_for_market
from services.infonet.markets.resolution import resolve_market
from services.infonet.markets.snapshot import InvalidAuthoritativeSnapshot, find_snapshot


def _create(trigger_date: Any = 200.0) -> dict[str, Any]:
    return {
        "event_type": "prediction_create",
        "node_id": "creator",
        "timestamp": 100.0,
        "sequence": 1,
        "payload": {"market_id": "m1", "trigger_date": trigger_date},
    }


def _snapshot(
    timestamp: Any = 200.0, frozen_at: Any = 200.0, sequence: Any = 2
) -> dict[str, Any]:
    return {
        "event_type": "market_snapshot",
        "node_id": "creator",
        "timestamp": timestamp,
        "sequence": sequence,
        "payload": {
            "market_id": "m1",
            "frozen_at": frozen_at,
            "frozen_predictor_ids": ["predictor"],
        },
    }


def _finalize(timestamp: Any = 300.0, sequence: Any = 3) -> dict[str, Any]:
    return {
        "event_type": "resolution_finalize",
        "node_id": "creator",
        "timestamp": timestamp,
        "sequence": sequence,
        "payload": {"market_id": "m1", "outcome": "yes"},
    }


def test_malformed_non_authoritative_metadata_does_not_break_projection() -> None:
    chain = [
        _create(),
        _snapshot(),
        {
            "event_type": "prediction_place",
            "node_id": "peer",
            "timestamp": "not-a-timestamp",
            "sequence": "not-a-sequence",
            "payload": {"market_id": "m1"},
        },
    ]

    assert compute_market_status("m1", chain, now=201.0) == MarketStatus.EVIDENCE


def test_market_events_preserve_canonical_hashchain_order() -> None:
    first = _snapshot(timestamp=300.0, sequence=5)
    second = _snapshot(timestamp=200.0, sequence=2)

    events = events_for_market("m1", [_create(), first, second])

    assert events[1:] == [first, second]


def test_lifecycle_and_find_snapshot_share_authoritative_append_order() -> None:
    evidence_window = float(CONFIG["evidence_window_hours"]) * 3600.0
    first_timestamp = 10.0 * evidence_window
    first = _snapshot(timestamp=first_timestamp, frozen_at=first_timestamp, sequence=5)
    second = _snapshot(timestamp=1.0, frozen_at=1.0, sequence=2)
    chain = [_create(), first, second]

    # Lifecycle must use the first appended snapshot. If snapshot.py re-sorted
    # by timestamp/sequence, the much older second event would be selected and
    # this same `now` would project RESOLVING instead of EVIDENCE.
    now = first_timestamp + evidence_window / 2.0
    assert compute_market_status("m1", chain, now=now) == MarketStatus.EVIDENCE
    assert find_snapshot("m1", chain) == first["payload"]


def test_invalid_first_snapshot_fails_closed_without_replacement() -> None:
    chain = [
        _create(),
        _snapshot(timestamp="bad", frozen_at=200.0, sequence="bad"),
        _snapshot(timestamp=200.0, frozen_at=200.0, sequence=3),
    ]

    assert compute_market_status("m1", chain, now=10_000.0) == MarketStatus.PREDICTING
    assert should_advance_phase("m1", chain, now=10_000.0) is None
    with pytest.raises(InvalidAuthoritativeSnapshot):
        find_snapshot("m1", chain)


def test_invalid_first_snapshot_halts_direct_resolution() -> None:
    chain = [
        _create(),
        _snapshot(timestamp="bad", frozen_at=200.0, sequence="bad"),
        _snapshot(timestamp=200.0, frozen_at=200.0, sequence=3),
        {
            "event_type": "resolution_stake",
            "node_id": "resolver",
            "timestamp": 400.0,
            "sequence": 4,
            "payload": {
                "market_id": "m1",
                "side": "yes",
                "amount": 10.0,
                "rep_type": "oracle",
            },
        },
    ]

    # A malformed authoritative commitment is distinct from no snapshot.
    # Resolution must halt instead of treating it as an empty exclusion set.
    with pytest.raises(InvalidAuthoritativeSnapshot):
        resolve_market("m1", chain)


def test_nonfinite_snapshot_timestamp_does_not_fall_back_to_frozen_at() -> None:
    chain = [_create(), _snapshot(timestamp=float("nan"), frozen_at=200.0)]

    assert compute_market_status("m1", chain, now=201.0) == MarketStatus.PREDICTING
    assert should_advance_phase("m1", chain, now=10_000.0) is None
    with pytest.raises(InvalidAuthoritativeSnapshot):
        find_snapshot("m1", chain)


def test_invalid_first_finalize_cannot_be_replaced_by_later_finalize() -> None:
    chain = [
        _create(),
        _snapshot(),
        _finalize(timestamp="bad", sequence="bad"),
        _finalize(timestamp=300.0, sequence=4),
    ]

    # The malformed finalize has no terminal authority, so projection stays
    # in the prior snapshot-backed phase. The later finalize cannot replace it.
    assert compute_market_status("m1", chain, now=201.0) == MarketStatus.EVIDENCE
    assert should_advance_phase("m1", chain, now=10_000.0) is None


def test_invalid_trigger_date_cannot_authorize_phase_advance() -> None:
    chain = [_create(trigger_date="not-a-date")]

    assert should_advance_phase("m1", chain, now=10_000.0) is None
