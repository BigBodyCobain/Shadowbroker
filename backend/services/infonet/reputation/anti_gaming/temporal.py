"""Temporal burst detection — flags suspicious uprep storms.

Source of truth: ``infonet-economy/RULES_SKELETON.md`` §3.3 (the
``rep_after_burst`` step).

Definition: a target B is "in a burst" relative to an uprep at time
``t`` if there are at least ``temporal_burst_min_upreps`` upreps to B
within a ``temporal_burst_window_sec`` window centered on ``t`` (the
window includes the uprep being evaluated).

When in burst: per-uprep weight is multiplied by 0.2 (80% reduction).
Otherwise 1.0.

Why a centered window: bursts can be detected on either side of the
suspect uprep. Sliding-forward-only would let an attacker pre-warm the
counter.
"""

from __future__ import annotations

from typing import Any, Iterable

from services.infonet.config import CONFIG


_BURST_REDUCTION_FACTOR = 0.2


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    p = event.get("payload")
    return p if isinstance(p, dict) else {}


def is_in_burst(
    target_id: str,
    uprep_timestamp: float,
    chain: Iterable[dict[str, Any]],
) -> bool:
    """Are there ``temporal_burst_min_upreps`` upreps to ``target_id``
    within ``temporal_burst_window_sec`` of ``uprep_timestamp``?
    """
    if not isinstance(target_id, str) or not target_id:
        return False
    try:
        ts = float(uprep_timestamp)
    except (TypeError, ValueError):
        return False
    window_s = float(CONFIG["temporal_burst_window_sec"])
    half = window_s / 2.0
    threshold = int(CONFIG["temporal_burst_min_upreps"])

    count = 0
    for ev in chain:
        if not isinstance(ev, dict):
            continue
        if ev.get("event_type") != "uprep":
            continue
        p = _payload(ev)
        if p.get("target_node_id") != target_id:
            continue
        try:
            ets = float(ev.get("timestamp") or 0.0)
        except (TypeError, ValueError):
            continue
        if ts - half <= ets <= ts + half:
            count += 1
            if count >= threshold:
                return True
    return False


def temporal_multiplier(in_burst: bool) -> float:
    """1.0 if not in burst; ``_BURST_REDUCTION_FACTOR`` (0.2) if in burst."""
    return _BURST_REDUCTION_FACTOR if in_burst else 1.0


__all__ = [
    "is_in_burst",
    "temporal_multiplier",
]
