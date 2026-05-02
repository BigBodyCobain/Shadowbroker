"""Reputation views — oracle_rep, oracle_rep_active, oracle_rep_lifetime, common_rep.

These are **pure functions** over the chain. No stored state. See
``infonet-economy/IMPLEMENTATION_PLAN.md`` §3.2 for the rationale.

Sprint 2 ships the base formulas (RULES §3.1, §3.2, §3.3, §3.11) without
the anti-gaming penalties. Sprint 3 layers VCS / clustering / temporal /
progressive penalties on top.
"""

from services.infonet.reputation.anti_gaming import (
    apply_progressive_penalty,
    clustering_penalty,
    compute_clustering_coefficient,
    compute_farming_pct,
    compute_rep_multiplier,
    compute_vcs,
    farming_multiplier,
    is_in_burst,
    temporal_multiplier,
)
from services.infonet.reputation.common_rep import compute_common_rep
from services.infonet.reputation.governance_decay import (
    compute_oracle_rep_active,
    decay_factor_for_age,
)
from services.infonet.reputation.oracle_rep import (
    OracleRepBreakdown,
    compute_oracle_rep,
    compute_oracle_rep_lifetime,
    last_successful_prediction_ts,
)
from services.infonet.reputation.weekly_vote_budget import (
    compute_weekly_vote_budget,
    count_upreps_in_last_week,
    is_budget_exceeded,
)

__all__ = [
    "OracleRepBreakdown",
    "apply_progressive_penalty",
    "clustering_penalty",
    "compute_clustering_coefficient",
    "compute_common_rep",
    "compute_farming_pct",
    "compute_oracle_rep",
    "compute_oracle_rep_active",
    "compute_oracle_rep_lifetime",
    "compute_rep_multiplier",
    "compute_vcs",
    "compute_weekly_vote_budget",
    "count_upreps_in_last_week",
    "decay_factor_for_age",
    "farming_multiplier",
    "is_budget_exceeded",
    "is_in_burst",
    "last_successful_prediction_ts",
    "temporal_multiplier",
]
