"""Common rep computation with anti-gaming multipliers (Sprint 3).

Source of truth: ``infonet-economy/RULES_SKELETON.md`` §3.3.

Per-uprep formula:

    base_rep            = upreper.oracle_rep * weight_factor
    rep_after_vcs       = base_rep * compute_vcs(upreper, target)
    rep_after_clustering = rep_after_vcs * clustering_penalty(coefficient(target))
    rep_after_burst     = rep_after_clustering * temporal_multiplier(in_burst)

    common_rep_earned   = rep_after_burst   (per uprep; sum across all upreps)

VCS / clustering use the upreps-within-decay-window helper. Temporal
burst uses a centered window (see ``anti_gaming/temporal.py``).

Sprint 3 caches per-uprep evaluations in-process: a single call to
``compute_common_rep`` walks the chain at most three times (once per
multiplier family). Caching across calls is a Sprint 3+ adapter
concern.

Cross-cutting design rule: this is background work. The UI should call
through ``InfonetReputationAdapter.common_rep`` and treat the result
as eventually-consistent — never block a user-visible action waiting
for it.
"""

from __future__ import annotations

from typing import Any, Iterable

from services.infonet.config import CONFIG
from services.infonet.reputation.anti_gaming.clustering import (
    clustering_penalty,
    compute_clustering_coefficient,
)
from services.infonet.reputation.anti_gaming.correlation_score import (
    progressive_penalty_multiplier_for,
)
from services.infonet.reputation.anti_gaming.temporal import (
    is_in_burst,
    temporal_multiplier,
)
from services.infonet.reputation.anti_gaming.vcs import compute_vcs
from services.infonet.reputation.oracle_rep import compute_oracle_rep


def _default_weight_factor() -> float:
    """RULES §3.3 weight factor — promoted from Sprint 2 module
    constant to ``CONFIG['common_rep_weight_factor']`` 2026-04-28 so
    governance can tune it via petition.

    Tests pass an explicit value to ``compute_common_rep`` to override.
    """
    return float(CONFIG["common_rep_weight_factor"])


def compute_common_rep(
    node_id: str,
    chain: Iterable[dict[str, Any]],
    *,
    weight_factor: float | None = None,
    apply_anti_gaming: bool = True,
) -> float:
    """Common rep balance for ``node_id``.

    ``apply_anti_gaming=False`` returns the Sprint 2 base formula —
    useful for tests that want to isolate the multiplier layer. Default
    in production is ``True``.
    """
    factor = float(_default_weight_factor() if weight_factor is None else weight_factor)
    events = [e for e in chain if isinstance(e, dict)]
    rep = 0.0
    # Oracle-rep cache keyed by upreper only — oracle_rep is computed
    # over the full chain (no time bound) and doesn't change per-uprep.
    upreper_cache: dict[str, float] = {}
    # NB: do NOT cache the clustering coefficient by node_id alone — it
    # is a function of (target, evaluation timestamp). Caching by target
    # only would freeze the first uprep's view (often coefficient 0
    # before other voters arrive) and skip the penalty for subsequent
    # upreps.

    for ev in events:
        if ev.get("event_type") != "uprep":
            continue
        payload = ev.get("payload") or {}
        if payload.get("target_node_id") != node_id:
            continue
        upreper = ev.get("node_id")
        if not isinstance(upreper, str) or not upreper:
            continue
        if upreper == node_id:
            continue

        if upreper not in upreper_cache:
            upreper_cache[upreper] = compute_oracle_rep(upreper, events)
        base = upreper_cache[upreper] * factor

        if apply_anti_gaming:
            try:
                ts = float(ev.get("timestamp") or 0.0)
            except (TypeError, ValueError):
                ts = 0.0
            vcs = compute_vcs(upreper, node_id, events, now=ts)
            coefficient = compute_clustering_coefficient(node_id, events, now=ts)
            cluster_mult = clustering_penalty(coefficient)
            burst_mult = temporal_multiplier(is_in_burst(node_id, ts, events))
            rep += base * vcs * cluster_mult * burst_mult
        else:
            rep += base

    if apply_anti_gaming and rep > 0:
        # Progressive-penalty wiring (Sprint 3 polish 2026-04-28).
        # Disabled when CONFIG['progressive_penalty_threshold'] == 0,
        # so this preserves Sprint 3 behavior by default. Once
        # governance raises the threshold via petition, the whale-
        # deterrence multiplier kicks in for nodes whose aggregate
        # correlation score crosses it. Oracle-rep input is the
        # TARGET's rep (not the upreper's) — bigger oracles bear
        # bigger penalties for cabal-shaped uprep patterns.
        target_oracle_rep = compute_oracle_rep(node_id, events)
        rep *= progressive_penalty_multiplier_for(
            node_id, events, oracle_rep=target_oracle_rep,
        )
    return rep


__all__ = ["compute_common_rep"]
