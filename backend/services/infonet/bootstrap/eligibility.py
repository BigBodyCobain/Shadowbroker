"""Bootstrap eligibility — identity age + predictor exclusion.

Source of truth: ``infonet-economy/RULES_SKELETON.md`` §3.10 step 0.5
(``is_bootstrap_eligible``).

Two gates:

1. **Identity age vs ``frozen_at`` (NOT ``now``).** Spec is explicit:

       node.created_at + (bootstrap_min_identity_age_days * 86400)
                                                    <= market.snapshot.frozen_at

   Measuring against the frozen snapshot timestamp keeps eligibility
   deterministic — every node computes the same set from the same
   chain state. Measuring against ``now`` would make eligibility
   depend on local clock, which is a clock-manipulation attack
   surface.

2. **Predictor exclusion.** Same as normal resolution:
   ``frozen_predictor_ids ∪ rotation_descendants(frozen_predictor_ids)``.
   Reuses ``services.infonet.markets.resolution.excluded_predictor_ids``
   (Sprint 4) — single source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from services.infonet.config import CONFIG
from services.infonet.markets.resolution import excluded_predictor_ids
from services.infonet.markets.snapshot import find_snapshot


_SECONDS_PER_DAY = 86400.0


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    p = event.get("payload")
    return p if isinstance(p, dict) else {}


def _node_created_at(node_id: str, chain: Iterable[dict[str, Any]]) -> float | None:
    """First chain appearance of ``node_id`` — used as a proxy for
    ``node.created_at``. Per RULES §2.1: "Timestamp of first appearance
    on chain". A ``node_register`` event is preferred when present;
    otherwise the earliest event signed by ``node_id``.
    """
    earliest_register: float | None = None
    earliest_any: float | None = None
    for ev in chain:
        if not isinstance(ev, dict):
            continue
        author = ev.get("node_id")
        if author != node_id:
            continue
        try:
            ts = float(ev.get("timestamp") or 0.0)
        except (TypeError, ValueError):
            continue
        if ev.get("event_type") == "node_register":
            if earliest_register is None or ts < earliest_register:
                earliest_register = ts
        if earliest_any is None or ts < earliest_any:
            earliest_any = ts
    return earliest_register if earliest_register is not None else earliest_any


def is_identity_age_eligible(
    node_id: str,
    market_id: str,
    chain: Iterable[dict[str, Any]],
    *,
    min_age_days: float | None = None,
) -> bool:
    """``True`` iff
    ``node.created_at + min_age_days * 86400 <= market.snapshot.frozen_at``.

    Returns ``False`` if the snapshot doesn't exist yet, the node has
    no chain history, or the timing condition fails.
    """
    chain_list = list(chain)
    snapshot = find_snapshot(market_id, chain_list)
    if snapshot is None:
        return False
    try:
        frozen_at = float(snapshot.get("frozen_at") or 0.0)
    except (TypeError, ValueError):
        return False
    created_at = _node_created_at(node_id, chain_list)
    if created_at is None:
        return False
    age_days = float(min_age_days if min_age_days is not None
                     else CONFIG["bootstrap_min_identity_age_days"])
    threshold_ts = created_at + age_days * _SECONDS_PER_DAY
    return threshold_ts <= frozen_at


@dataclass(frozen=True)
class EligibilityDecision:
    eligible: bool
    reason: str


def validate_bootstrap_eligibility(
    node_id: str,
    market_id: str,
    chain: Iterable[dict[str, Any]],
) -> EligibilityDecision:
    """Combine identity-age + predictor-exclusion checks.

    Used by the Sprint 8 anti-DoS funnel and by the bootstrap
    resolution path itself.
    """
    chain_list = list(chain)
    if find_snapshot(market_id, chain_list) is None:
        return EligibilityDecision(False, "snapshot_missing")
    if not is_identity_age_eligible(node_id, market_id, chain_list):
        return EligibilityDecision(False, "identity_age_too_young")
    if node_id in excluded_predictor_ids(market_id, chain_list):
        return EligibilityDecision(False, "predictor_excluded")
    return EligibilityDecision(True, "ok")


__all__ = [
    "EligibilityDecision",
    "is_identity_age_eligible",
    "validate_bootstrap_eligibility",
]
