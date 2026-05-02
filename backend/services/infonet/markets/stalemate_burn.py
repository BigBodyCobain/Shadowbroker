"""Stalemate burn — Round 8 anti-griefing defense.

Source of truth: ``infonet-economy/RULES_SKELETON.md`` §3.10 Step 2
(no-supermajority branch) and the comment block above
``CONFIG['resolution_stalemate_burn_pct']``.

The problem: without a stalemate burn, a >25% cartel can stake the
contrarian side at zero cost to permanently force INVALID and halt
oracle rep minting. Burning a small percentage of every resolution
stake when consensus fails makes that strategy progressively expensive
— the cartel bleeds rep over time.

Critical constraint (RULES §3.10 step 2 comment): the stalemate burn
ONLY applies when:

- both sides staked (total ≥ min threshold), AND
- evidence exists, AND
- supermajority not reached.

It does NOT apply when:

- zero evidence (the market gave no signal at all — not griefing),
- below-minimum participation, OR
- below-minimum stake total (uninformative — not griefing).

That's why the helper here is *non-default* — it's invoked only by the
specific branches in ``resolution.py`` that match the spec's
"genuine disagreement" case.
"""

from __future__ import annotations

from typing import Iterable

from services.infonet.config import CONFIG


def stalemate_burn_pct() -> float:
    """Current burn percentage from CONFIG. Helper so callers don't
    need to remember the key name."""
    return float(CONFIG["resolution_stalemate_burn_pct"])


def split_burn_and_return(amount: float, burn_pct: float | None = None) -> tuple[float, float]:
    """Compute (burn_amount, returned_amount) for a single stake."""
    if amount <= 0:
        return 0.0, 0.0
    pct = float(stalemate_burn_pct() if burn_pct is None else burn_pct)
    if pct <= 0:
        return 0.0, float(amount)
    if pct >= 1:
        return float(amount), 0.0
    burn = float(amount) * pct
    returned = float(amount) - burn
    return burn, returned


def apply_to_stakes(
    stakes: Iterable[dict],
    *,
    burn_pct: float | None = None,
) -> tuple[dict[tuple[str, str], float], float]:
    """Apply the stalemate burn to ``stakes`` (iterable of dicts with
    ``node_id``, ``rep_type``, ``amount``).

    Returns ``(returns_by_(node, rep_type), total_burned)``. The caller
    folds these into the larger ``ResolutionResult`` rather than
    mutating any state directly.
    """
    pct = float(stalemate_burn_pct() if burn_pct is None else burn_pct)
    returns: dict[tuple[str, str], float] = {}
    total_burned = 0.0
    for s in stakes:
        node_id = s.get("node_id") if isinstance(s, dict) else getattr(s, "node_id", None)
        rep_type = s.get("rep_type") if isinstance(s, dict) else getattr(s, "rep_type", None)
        amount = s.get("amount") if isinstance(s, dict) else getattr(s, "amount", None)
        try:
            amt = float(amount) if amount is not None else 0.0
        except (TypeError, ValueError):
            amt = 0.0
        if amt <= 0 or not isinstance(node_id, str) or rep_type not in ("oracle", "common"):
            continue
        burn, ret = split_burn_and_return(amt, pct)
        if ret > 0:
            returns[(node_id, rep_type)] = returns.get((node_id, rep_type), 0.0) + ret
        total_burned += burn
    return returns, total_burned


__all__ = [
    "apply_to_stakes",
    "split_burn_and_return",
    "stalemate_burn_pct",
]
