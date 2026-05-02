"""Provisional-flag heuristic — chain-staleness detection.

Source of truth: ``infonet-economy/IMPLEMENTATION_PLAN.md`` §3.7
("initial implementation can gate economic events with
``is_provisional=True`` whenever the local chain head's
``chain_majority_time`` is older than X seconds").

Sprint 10 ships the placeholder for full epoch finality. Producers
emitting Tier 2 events consult ``should_mark_provisional`` to decide
whether to set ``is_provisional=True``. Once the formal epoch
checkpoint protocol is shipped (IMPLEMENTATION_PLAN §6.5), this
heuristic gets replaced with a check against the latest confirmed
checkpoint.

Until then, the heuristic is: if local chain time hasn't advanced in
``DEFAULT_MAX_CHAIN_LAG_S`` seconds, the network is partitioned (or
dramatically slow); Tier 2 events emitted now are provisional.

Cross-cutting design rule: a partitioned node must NOT block the
user from emitting actions. Tier 1 actions are always live; Tier 2
actions are accepted but marked provisional. Reconnection promotes
provisional events to final once the checkpoint clears.
"""

from __future__ import annotations

from typing import Any, Iterable

from services.infonet.partition.two_tier_state import classify_event_type
from services.infonet.time_validity import chain_majority_time


# Default: 60 seconds. After 1 minute without a chain advance from a
# distinct node, Tier 2 events get marked provisional. This is a
# conservative default — production deployments will likely tune
# higher (5-10 minutes) once the network is large and partitions
# are rare. Currently NOT in CONFIG_SCHEMA — see Sprint 10 hand-off
# notes for the open governance question.
DEFAULT_MAX_CHAIN_LAG_S: float = 60.0


def chain_lag_seconds(
    chain: Iterable[dict[str, Any]],
    *,
    now: float,
) -> float:
    """Seconds elapsed between ``chain_majority_time(chain)`` and ``now``.

    Returns ``0.0`` if ``now`` is at or before chain time (clock skew
    or the chain genuinely caught up just now). Always non-negative.
    """
    cmt = chain_majority_time(chain)
    if cmt <= 0:
        # Empty chain — no events from distinct nodes yet. Treat as
        # "infinite lag" so Tier 2 emissions are provisional.
        return float("inf")
    return max(0.0, float(now) - cmt)


def is_chain_stale(
    chain: Iterable[dict[str, Any]],
    *,
    now: float,
    max_lag_seconds: float = DEFAULT_MAX_CHAIN_LAG_S,
) -> bool:
    """``True`` iff the chain hasn't advanced in ``max_lag_seconds``."""
    return chain_lag_seconds(chain, now=now) > float(max_lag_seconds)


def should_mark_provisional(
    event_type: str,
    chain: Iterable[dict[str, Any]],
    *,
    now: float,
    max_lag_seconds: float = DEFAULT_MAX_CHAIN_LAG_S,
) -> bool:
    """Should ``event_type`` carry ``is_provisional=True`` if emitted now?

    Tier 1 events: always ``False`` (they're CRDT-friendly).
    Tier 2 events: ``True`` iff chain is stale.
    Infrastructure / unknown: ``False`` (no economic finality at stake).
    """
    tier = classify_event_type(event_type)
    if tier != "tier2":
        return False
    return is_chain_stale(chain, now=now, max_lag_seconds=max_lag_seconds)


__all__ = [
    "DEFAULT_MAX_CHAIN_LAG_S",
    "chain_lag_seconds",
    "is_chain_stale",
    "should_mark_provisional",
]
