"""DATA_UNAVAILABLE resolution path — Round 8 phantom-evidence defense.

Source of truth: ``infonet-economy/RULES_SKELETON.md`` §3.10 Step 1.5
+ the ``CONFIG['data_unavailable_threshold']`` comment block.

Threshold: when ``oracle_da / oracle_all >= data_unavailable_threshold``
(default 33% of oracle-rep stake), the market is INVALID and:

- ALL evidence-submitter bonds are SLASHED (burned, not returned).
  The premise: evidence existed but couldn't be verified — the
  submitters are at fault.
- DA voters' resolution stakes are returned in FULL (they acted
  correctly).
- yes/no resolution stakes get the stalemate burn applied (they
  participated despite bad evidence; small burn makes blind staking
  expensive).

This is distinct from the no-supermajority stalemate path: there, all
stakes (including DA) take the burn and bonds are returned in good
faith. Sprint 5 keeps the two paths separate to match the spec.
"""

from __future__ import annotations

from typing import Any

from services.infonet.config import CONFIG
from services.infonet.markets.evidence import EvidenceBundle
from services.infonet.markets.stalemate_burn import (
    apply_to_stakes,
    split_burn_and_return,
)


def is_data_unavailable_triggered(stakes: list[Any]) -> bool:
    """``True`` if oracle DA stakes meet or exceed the threshold."""
    oracle_all = sum(getattr(s, "amount", 0.0) for s in stakes
                     if getattr(s, "rep_type", None) == "oracle")
    if oracle_all <= 0:
        return False
    oracle_da = sum(getattr(s, "amount", 0.0) for s in stakes
                    if getattr(s, "side", None) == "data_unavailable"
                    and getattr(s, "rep_type", None) == "oracle")
    return oracle_da / oracle_all >= float(CONFIG["data_unavailable_threshold"])


def resolve_data_unavailable_effects(
    stakes: list[Any],
    bundles: list[EvidenceBundle],
) -> dict[str, Any]:
    """Compute the rep-transfer effects for a DA-triggered INVALID
    resolution. Returns a dict with the same keys ``ResolutionResult``
    expects, ready for the caller to fold in.

    Side effects layered:

    - DA voters get full return.
    - yes/no resolution stakers get the stalemate burn.
    - Evidence submitters: bonds slashed (forfeit).
    """
    out: dict[str, Any] = {
        "stake_returns": {},
        "bond_forfeits": {},
        "bond_returns": {},
        "burned": 0.0,
    }

    da_stakes = [s for s in stakes if getattr(s, "side", None) == "data_unavailable"]
    other_stakes = [s for s in stakes if getattr(s, "side", None) in ("yes", "no")]

    # DA voters: full return.
    for s in da_stakes:
        node_id = getattr(s, "node_id", None)
        rep_type = getattr(s, "rep_type", None)
        amount = float(getattr(s, "amount", 0.0))
        if not isinstance(node_id, str) or rep_type not in ("oracle", "common") or amount <= 0:
            continue
        key = (node_id, rep_type)
        out["stake_returns"][key] = out["stake_returns"].get(key, 0.0) + amount

    # yes/no stakers: stalemate burn.
    burn_returns, burn_total = apply_to_stakes(
        ({"node_id": s.node_id, "rep_type": s.rep_type, "amount": s.amount} for s in other_stakes),
    )
    for k, v in burn_returns.items():
        out["stake_returns"][k] = out["stake_returns"].get(k, 0.0) + v
    out["burned"] += burn_total

    # Evidence bonds: slashed (forfeited) — burned.
    for b in bundles:
        if b.bond > 0:
            out["bond_forfeits"][b.node_id] = (
                out["bond_forfeits"].get(b.node_id, 0.0) + b.bond
            )
            out["burned"] += b.bond
    return out


__all__ = [
    "is_data_unavailable_triggered",
    "resolve_data_unavailable_effects",
    "split_burn_and_return",  # re-exported for callers' convenience
]
