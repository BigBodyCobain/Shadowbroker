"""Time validity primitives — chain_majority_time, drift tolerance,
phase boundaries.

Source of truth: ``infonet-economy/RULES_SKELETON.md`` §3.13, §3.14.

Three rules:

1. **Reject future events beyond drift tolerance** — an event whose
   ``timestamp`` exceeds ``chain_majority_time() + max_future_event_drift_sec``
   is rejected. Defends against clock skew or manipulation.

2. **Reject stale events past finalized phase boundaries** — an
   ``evidence_submit`` after the evidence window has closed, or a
   ``resolution_stake`` after the resolution window has closed, is
   rejected. (The phase-boundary check itself lives in Sprint 4 with
   the market lifecycle; this module exposes the building blocks.)

3. **Phase transitions use majority-accepted chain time** — no single
   node's local clock can unilaterally trigger or delay a transition.

Cross-cutting design rule (BUILD_LOG.md): time validity checks must
NEVER block a user's UI. The intended caller flow:

- Receiver-side ingest: events that fail drift tolerance are silently
  re-queued for retry. The user does not see a 4xx.
- Producer-side append: if the local clock is too far ahead, the
  producer adjusts its clock or back-pressures, but the user's queued
  action is NOT lost.

This module is pure logic — the queue / retry behavior is the caller's
responsibility.
"""

from __future__ import annotations

import statistics
from typing import Any, Iterable

from services.infonet.config import CONFIG


# Number of distinct nodes' last events used to compute the median.
# RULES §3.14 says "median timestamp of last N events from distinct
# nodes" without specifying N. 11 is a small odd number that survives
# Byzantine arithmetic with up to ~5 colluding nodes (median is robust).
# Configurable for tests.
_DEFAULT_MEDIAN_N = 11


def chain_majority_time(
    chain: Iterable[dict[str, Any]],
    *,
    n: int = _DEFAULT_MEDIAN_N,
) -> float:
    """Median timestamp of the last ``n`` events from distinct nodes.

    Returns ``0.0`` for an empty chain. Returns the single timestamp
    when fewer than ``n`` distinct nodes have appeared.

    The reduction is deterministic given the chain — every node
    computes the same value from the same chain history, which is the
    whole point. Phase transitions and drift checks can therefore be
    consensus-safe without trusting any node's local clock.
    """
    if n <= 0:
        raise ValueError("n must be positive")
    events = [e for e in chain if isinstance(e, dict)]
    events.sort(key=lambda e: float(e.get("timestamp") or 0.0), reverse=True)
    seen_nodes: set[str] = set()
    timestamps: list[float] = []
    for ev in events:
        node = ev.get("node_id")
        if not isinstance(node, str) or not node:
            continue
        if node in seen_nodes:
            continue
        seen_nodes.add(node)
        ts = ev.get("timestamp")
        try:
            timestamps.append(float(ts))
        except (TypeError, ValueError):
            continue
        if len(timestamps) >= n:
            break
    if not timestamps:
        return 0.0
    return float(statistics.median(timestamps))


def is_event_too_future(
    event: dict[str, Any],
    chain: Iterable[dict[str, Any]] | None = None,
    *,
    chain_time: float | None = None,
) -> bool:
    """Is ``event.timestamp`` more than ``max_future_event_drift_sec``
    ahead of ``chain_majority_time``?

    Pass ``chain_time`` when the caller has already computed it (e.g.
    bulk validation of a batch — avoids recomputing the median per
    event). Otherwise pass ``chain``.
    """
    if chain_time is None:
        if chain is None:
            raise ValueError("Pass chain or chain_time")
        chain_time = chain_majority_time(chain)
    try:
        ts = float(event.get("timestamp"))
    except (TypeError, ValueError):
        # Non-numeric timestamp is its own validation failure — let the
        # schema-level check catch that. Drift check itself returns
        # False here (we cannot meaningfully compare).
        return False
    drift = float(CONFIG["max_future_event_drift_sec"])
    return ts > chain_time + drift


def event_meets_phase_window(
    event_timestamp: float,
    phase_start: float,
    phase_window_seconds: float,
) -> bool:
    """Is ``event_timestamp`` within the ``[phase_start, phase_start +
    phase_window_seconds]`` window?

    Building block for the phase-boundary check; the actual phase
    lookup (mapping market_id → current phase) lives in Sprint 4 with
    the market lifecycle.
    """
    if phase_window_seconds < 0:
        raise ValueError("phase_window_seconds must be non-negative")
    return phase_start <= event_timestamp <= phase_start + phase_window_seconds


__all__ = [
    "chain_majority_time",
    "event_meets_phase_window",
    "is_event_too_future",
]
