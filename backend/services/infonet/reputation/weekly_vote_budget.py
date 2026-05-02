"""Weekly vote budget — RULES §3.7.

    weekly_budget = weekly_vote_base + floor(oracle_rep / weekly_vote_per_oracle)

Notes on placement: the budget is reputation-derived and gates how
many upreps a node can cast in a 7-day window. Anti-gaming penalties
shrink each uprep's *weight*, but the budget is what bounds *count*.
Both layers run together to defeat farming.

Enforcement is upstream of the chain (the producer must check budget
before signing a new ``uprep`` event); this module provides the
computation and a chain-side audit (``count_upreps_in_last_week``) so
verifiers can spot budget violations.
"""

from __future__ import annotations

import math
from typing import Any, Iterable

from services.infonet.config import CONFIG
from services.infonet.reputation.oracle_rep import compute_oracle_rep


_SECONDS_PER_DAY = 86400.0
_WEEK_S = 7 * _SECONDS_PER_DAY


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    p = event.get("payload")
    return p if isinstance(p, dict) else {}


def compute_weekly_vote_budget(
    node_id: str,
    chain: Iterable[dict[str, Any]],
) -> int:
    """Per-week uprep budget for ``node_id``."""
    base = int(CONFIG["weekly_vote_base"])
    per_oracle = int(CONFIG["weekly_vote_per_oracle"])
    if per_oracle <= 0:
        return base
    rep = compute_oracle_rep(node_id, chain)
    return base + math.floor(rep / per_oracle)


def count_upreps_in_last_week(
    node_id: str,
    chain: Iterable[dict[str, Any]],
    *,
    now: float,
) -> int:
    """Count of ``uprep`` events authored by ``node_id`` in the past 7 days
    relative to ``now``. Used by chain-side audits.
    """
    cutoff = float(now) - _WEEK_S
    count = 0
    for ev in chain:
        if not isinstance(ev, dict):
            continue
        if ev.get("event_type") != "uprep":
            continue
        if ev.get("node_id") != node_id:
            continue
        try:
            ts = float(ev.get("timestamp") or 0.0)
        except (TypeError, ValueError):
            continue
        if cutoff <= ts <= float(now):
            count += 1
    return count


def is_budget_exceeded(
    node_id: str,
    chain: Iterable[dict[str, Any]],
    *,
    now: float,
) -> bool:
    """``True`` if the node has cast more upreps in the past 7 days than
    its current weekly budget allows.

    Cross-cutting design rule: producers should call this in the
    background as a soft-fail check — the user's queued uprep is still
    accepted, but flagged for delayed processing rather than refused
    outright. Constitutional rejections are reserved for unsigned
    writes / replays / rotation-during-active-stakes.
    """
    return count_upreps_in_last_week(node_id, chain, now=now) > compute_weekly_vote_budget(node_id, chain)


__all__ = [
    "compute_weekly_vote_budget",
    "count_upreps_in_last_week",
    "is_budget_exceeded",
]
