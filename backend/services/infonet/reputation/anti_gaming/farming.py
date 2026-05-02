"""Easy-bet farming detection and enforcement.

Source of truth: ``infonet-economy/RULES_SKELETON.md`` §3.1.

A node's ``farming_pct`` is:

    farming_pct = count_easy_bets / total_predictions

where an "easy bet" is a prediction whose ``probability_at_bet``
exceeds ``farming_easy_bet_cutoff`` (default 0.80, expressed as 80.0
on the 0-100 scale used in payloads).

Penalty multiplier:

    farming_pct > farming_hard_threshold   →  oracle_rep_earned *= 0.10
    farming_pct > farming_soft_threshold   →  oracle_rep_earned *= 0.50
    otherwise                              →  oracle_rep_earned *= 1.00

The plan §1.2 calls out that the existing ``mesh_oracle.py`` *tracks*
``farming_pct`` but does NOT enforce the multiplier. Sprint 3 adds the
enforcement here, and Sprint 4's `oracle_rep` integration applies it
to mints. Until that wiring lands, this module is exposed as the
authoritative source of the math.

Note on sides: the spec's "easy bet" is a probability-of-the-PICKED-side
test. A free pick at 90% on yes is easy; a contrarian free pick at 10%
on yes (where the chain says yes is 10% likely) is hard. The
``probability_at_bet`` field stores the probability of the YES side at
the time the prediction is placed; we compute the predicted-side
probability accordingly.
"""

from __future__ import annotations

from typing import Any, Iterable

from services.infonet.config import CONFIG


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    p = event.get("payload")
    return p if isinstance(p, dict) else {}


def _picked_side_probability(payload: dict[str, Any]) -> float | None:
    """Translate ``probability_at_bet`` (always P(yes) on 0-100) into the
    probability of the side actually picked. Returns ``None`` if the
    payload is malformed.
    """
    side = payload.get("side")
    prob = payload.get("probability_at_bet")
    if side not in ("yes", "no"):
        return None
    if prob is None:
        return None
    try:
        p_yes = float(prob)
    except (TypeError, ValueError):
        return None
    if not (0.0 <= p_yes <= 100.0):
        return None
    return p_yes if side == "yes" else 100.0 - p_yes


def compute_farming_pct(
    node_id: str,
    chain: Iterable[dict[str, Any]],
) -> float:
    """Fraction of ``node_id``'s predictions whose picked-side probability
    exceeded ``farming_easy_bet_cutoff``.

    Returns ``0.0`` if the node has no predictions on chain. The cutoff
    is on the 0-1 scale in ``CONFIG``; predictions store probability on
    the 0-100 scale, so we scale the cutoff for comparison.
    """
    if not isinstance(node_id, str) or not node_id:
        return 0.0
    cutoff_pct = float(CONFIG["farming_easy_bet_cutoff"]) * 100.0

    total = 0
    easy = 0
    for ev in chain:
        if not isinstance(ev, dict):
            continue
        if ev.get("event_type") != "prediction_place":
            continue
        if ev.get("node_id") != node_id:
            continue
        picked_p = _picked_side_probability(_payload(ev))
        if picked_p is None:
            continue
        total += 1
        if picked_p > cutoff_pct:
            easy += 1
    if total == 0:
        return 0.0
    return easy / total


def farming_multiplier(farming_pct: float) -> float:
    """Spec multiplier for a node's mint earnings.

    - ``> farming_hard_threshold`` → 0.10
    - ``> farming_soft_threshold`` → 0.50
    - otherwise → 1.00
    """
    pct = float(farming_pct)
    if pct > float(CONFIG["farming_hard_threshold"]):
        return 0.10
    if pct > float(CONFIG["farming_soft_threshold"]):
        return 0.50
    return 1.00


__all__ = [
    "compute_farming_pct",
    "farming_multiplier",
]
