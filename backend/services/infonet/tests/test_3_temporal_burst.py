"""Sprint 3 — temporal burst adversarial tests.

Maps to IMPLEMENTATION_PLAN.md §7.1 Sprint 3 row:
"Temporal burst flags 5+ upreps within 5 min."
"""

from __future__ import annotations

from services.infonet.config import CONFIG
from services.infonet.reputation.anti_gaming import is_in_burst, temporal_multiplier
from services.infonet.tests._chain_factory import make_event


_BURST_WINDOW = float(CONFIG["temporal_burst_window_sec"])
_BURST_THRESHOLD = int(CONFIG["temporal_burst_min_upreps"])


def _uprep(author: str, target: str, ts: float, seq: int = 1) -> dict:
    return make_event(
        "uprep", author,
        {"target_node_id": target, "target_event_id": f"e-{author}-{target}-{seq}"},
        timestamp=ts, sequence=seq,
    )


def test_no_upreps_is_not_burst():
    assert not is_in_burst("alice", 1000.0, [])


def test_below_threshold_is_not_burst():
    chain = [
        _uprep(f"n{i}", "alice", ts=1000.0 + i, seq=i + 1)
        for i in range(_BURST_THRESHOLD - 1)
    ]
    assert not is_in_burst("alice", 1000.0, chain)


def test_at_threshold_within_window_is_burst():
    chain = [
        _uprep(f"n{i}", "alice", ts=1000.0 + i, seq=i + 1)
        for i in range(_BURST_THRESHOLD)
    ]
    # All within ~5 seconds of each other → well inside the 5-min window.
    assert is_in_burst("alice", 1000.0, chain)


def test_burst_window_is_centered_not_forward_only():
    """An attacker pre-warming events BEFORE the suspect uprep should
    still trigger the burst — window is centered on the evaluated ts.
    """
    pre = _BURST_THRESHOLD - 1
    chain = [
        _uprep(f"n{i}", "alice", ts=1000.0 - i * 10, seq=i + 1)
        for i in range(pre)
    ]
    chain.append(_uprep("nlast", "alice", ts=1000.0, seq=99))
    assert is_in_burst("alice", 1000.0, chain)


def test_outside_window_is_not_burst():
    """Upreps spread across more than the burst window — none of any
    sub-group of 5 fits inside a 5-min slice."""
    spacing = _BURST_WINDOW  # one full window apart
    chain = [
        _uprep(f"n{i}", "alice", ts=1_000_000.0 + i * spacing, seq=i + 1)
        for i in range(_BURST_THRESHOLD)
    ]
    # Evaluate around the middle entry — only that one falls inside its window
    middle_ts = 1_000_000.0 + (_BURST_THRESHOLD // 2) * spacing
    assert not is_in_burst("alice", middle_ts, chain)


def test_other_targets_do_not_count_toward_burst():
    """Upreps to a different target don't contribute."""
    chain = [
        _uprep(f"n{i}", "bob", ts=1000.0 + i, seq=i + 1)
        for i in range(_BURST_THRESHOLD)
    ]
    assert not is_in_burst("alice", 1000.0, chain)


def test_temporal_multiplier_in_burst_is_low():
    assert temporal_multiplier(True) == 0.2


def test_temporal_multiplier_outside_burst_is_full():
    assert temporal_multiplier(False) == 1.0
