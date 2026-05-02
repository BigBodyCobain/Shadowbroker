"""Aggregate per-node correlation score — feeds progressive penalty.

Source of truth: ``infonet-economy/RULES_SKELETON.md`` §3.6.

Sprint 3 shipped the progressive-penalty math (whale deterrence
multiplier ``1 + log2(rep)``) but did not wire it into a running
aggregate. This module fills that gap.

Per-node aggregate score:

    score(node) = mean(1 - vcs(upreper, node)
                       for every uprep targeting node in the decay window)

Range: ``[0.0, 1.0]``. ``0.0`` means every uprep was orthogonal —
no correlation evidence. ``1.0`` means every uprep was from a fully
overlapping target set — saturated cabal.

When ``score(node) > CONFIG['progressive_penalty_threshold']`` (default
``0.0`` — disabled), the progressive penalty multiplier is applied to
the node's effective common-rep payouts. The threshold default is
``0.0`` so Sprint 3 behavior is preserved for any chain that doesn't
explicitly opt in via governance.
"""

from __future__ import annotations

from typing import Any, Iterable

from services.infonet.config import CONFIG
from services.infonet.reputation.anti_gaming.progressive_penalty import (
    apply_progressive_penalty,
)
from services.infonet.reputation.anti_gaming.vcs import compute_vcs


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    p = event.get("payload")
    return p if isinstance(p, dict) else {}


def compute_node_correlation_score(
    node_id: str,
    chain: Iterable[dict[str, Any]],
    *,
    now: float | None = None,
) -> float:
    """Average correlation evidence (``1 - VCS``) across upreps
    targeting ``node_id``.

    Returns ``0.0`` when no upreps target the node — no evidence to
    support a penalty.
    """
    chain_list = [e for e in chain if isinstance(e, dict)]
    if not chain_list:
        return 0.0
    if now is None:
        now = max(float(ev.get("timestamp") or 0.0) for ev in chain_list)

    correlations: list[float] = []
    for ev in chain_list:
        if ev.get("event_type") != "uprep":
            continue
        if _payload(ev).get("target_node_id") != node_id:
            continue
        upreper = ev.get("node_id")
        if not isinstance(upreper, str) or not upreper or upreper == node_id:
            continue
        try:
            ts = float(ev.get("timestamp") or 0.0)
        except (TypeError, ValueError):
            ts = float(now)
        vcs = compute_vcs(upreper, node_id, chain_list, now=ts)
        correlations.append(max(0.0, min(1.0, 1.0 - vcs)))
    if not correlations:
        return 0.0
    return sum(correlations) / len(correlations)


def progressive_penalty_multiplier_for(
    node_id: str,
    chain: Iterable[dict[str, Any]],
    *,
    oracle_rep: float,
    now: float | None = None,
) -> float:
    """Return the multiplier to apply to a node's common-rep payouts.

    Returns ``1.0`` when the aggregate correlation score is at or
    below ``CONFIG['progressive_penalty_threshold']`` (no penalty).
    Above the threshold, the penalty is computed via
    ``apply_progressive_penalty(score - threshold, oracle_rep)`` and
    *subtracted* from 1.0 (clamped to ``[0.0, 1.0]``).

    The threshold defaults to ``0.0`` (disabled). Governance can
    raise it via petition once aggregate-correlation history is
    well-calibrated against real chain data.
    """
    threshold = float(CONFIG["progressive_penalty_threshold"])
    if threshold <= 0.0:
        # Disabled — preserve Sprint 3 behavior.
        return 1.0
    score = compute_node_correlation_score(node_id, chain, now=now)
    if score <= threshold:
        return 1.0
    over = score - threshold
    docked = apply_progressive_penalty(over, oracle_rep)
    return max(0.0, 1.0 - docked)


__all__ = [
    "compute_node_correlation_score",
    "progressive_penalty_multiplier_for",
]
