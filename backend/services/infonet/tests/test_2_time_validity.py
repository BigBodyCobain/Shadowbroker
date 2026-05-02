"""Sprint 2 — time validity primitives.

Maps to RULES §3.13/§3.14 and the cross-cutting design rules (drift
checks must NEVER block the user — see BUILD_LOG.md).
"""

from __future__ import annotations

import pytest

from services.infonet.config import CONFIG
from services.infonet.tests._chain_factory import make_event
from services.infonet.time_validity import (
    chain_majority_time,
    event_meets_phase_window,
    is_event_too_future,
)


def test_empty_chain_majority_time_is_zero():
    assert chain_majority_time([]) == 0.0


def test_chain_majority_time_is_median_of_distinct_node_timestamps():
    chain = [
        make_event("uprep", "n1", {"target_node_id": "x", "target_event_id": "e"},
                   timestamp=1000.0, sequence=1),
        make_event("uprep", "n2", {"target_node_id": "x", "target_event_id": "e"},
                   timestamp=2000.0, sequence=1),
        make_event("uprep", "n3", {"target_node_id": "x", "target_event_id": "e"},
                   timestamp=3000.0, sequence=1),
        make_event("uprep", "n4", {"target_node_id": "x", "target_event_id": "e"},
                   timestamp=4000.0, sequence=1),
        make_event("uprep", "n5", {"target_node_id": "x", "target_event_id": "e"},
                   timestamp=5000.0, sequence=1),
    ]
    assert chain_majority_time(chain) == 3000.0


def test_chain_majority_time_excludes_repeat_authors():
    """Repeated events from the same node_id MUST collapse to one
    contribution (otherwise a single misbehaving node can shift the
    median)."""
    chain = [
        make_event("uprep", "n1", {"target_node_id": "x", "target_event_id": "e"},
                   timestamp=t, sequence=i)
        for i, t in enumerate([100.0, 200.0, 300.0, 400.0, 500.0], start=1)
    ]
    chain.append(make_event(
        "uprep", "n2", {"target_node_id": "x", "target_event_id": "e"},
        timestamp=10_000.0, sequence=1,
    ))
    # Only n1's most-recent (500) and n2's 10000 contribute → median = 5250.
    assert chain_majority_time(chain) == (500.0 + 10_000.0) / 2.0


def test_chain_majority_time_uses_last_n_distinct_nodes():
    """When N is smaller than the chain, only the latest N distinct
    nodes' last events feed the median."""
    chain = [
        make_event("uprep", f"n{i}", {"target_node_id": "x", "target_event_id": "e"},
                   timestamp=float(i * 100), sequence=1)
        for i in range(1, 21)
    ]
    # n=3 → last 3 distinct nodes are n20, n19, n18 (timestamps 2000/1900/1800)
    # median is 1900.
    assert chain_majority_time(chain, n=3) == 1900.0


def test_event_too_future_rejected():
    chain_now = 1_700_000_000.0
    drift = float(CONFIG["max_future_event_drift_sec"])
    bad_event = make_event(
        "uprep", "n1", {"target_node_id": "x", "target_event_id": "e"},
        timestamp=chain_now + drift + 1.0, sequence=1,
    )
    assert is_event_too_future(bad_event, chain_time=chain_now)


def test_event_at_drift_boundary_accepted():
    chain_now = 1_700_000_000.0
    drift = float(CONFIG["max_future_event_drift_sec"])
    boundary = make_event(
        "uprep", "n1", {"target_node_id": "x", "target_event_id": "e"},
        timestamp=chain_now + drift, sequence=1,
    )
    assert not is_event_too_future(boundary, chain_time=chain_now)


def test_event_in_past_not_rejected_by_drift_check():
    chain_now = 1_700_000_000.0
    past = make_event(
        "uprep", "n1", {"target_node_id": "x", "target_event_id": "e"},
        timestamp=chain_now - 100.0, sequence=1,
    )
    assert not is_event_too_future(past, chain_time=chain_now)


def test_drift_check_with_chain_provided():
    """Convenience: caller passes the full chain; we recompute median internally."""
    chain = [
        make_event("uprep", "n1", {"target_node_id": "x", "target_event_id": "e"},
                   timestamp=1_700_000_000.0, sequence=1),
    ]
    drift = float(CONFIG["max_future_event_drift_sec"])
    bad = make_event(
        "uprep", "n2", {"target_node_id": "x", "target_event_id": "e"},
        timestamp=1_700_000_000.0 + drift + 100, sequence=1,
    )
    assert is_event_too_future(bad, chain=chain)


def test_drift_check_requires_chain_or_chain_time():
    with pytest.raises(ValueError):
        is_event_too_future({"timestamp": 1.0})


def test_phase_window_inside():
    assert event_meets_phase_window(150.0, phase_start=100.0, phase_window_seconds=100.0)


def test_phase_window_at_boundaries():
    assert event_meets_phase_window(100.0, phase_start=100.0, phase_window_seconds=100.0)
    assert event_meets_phase_window(200.0, phase_start=100.0, phase_window_seconds=100.0)


def test_phase_window_outside():
    assert not event_meets_phase_window(99.0, phase_start=100.0, phase_window_seconds=100.0)
    assert not event_meets_phase_window(201.0, phase_start=100.0, phase_window_seconds=100.0)


def test_phase_window_negative_window_rejected():
    with pytest.raises(ValueError):
        event_meets_phase_window(150.0, phase_start=100.0, phase_window_seconds=-1.0)


def test_chain_majority_time_n_must_be_positive():
    with pytest.raises(ValueError):
        chain_majority_time([], n=0)
