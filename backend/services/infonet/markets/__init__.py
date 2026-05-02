"""Market lifecycle, snapshot, evidence, and resolution.

Source of truth: ``infonet-economy/RULES_SKELETON.md`` §3.10, §5.2.

Pure-function design (same as Sprint 2/3): every entry point takes
``(market_id, chain, ...)`` and returns a deterministic value or a
structured result. The producer is responsible for emitting the
resulting events to the chain through the adapter layer.
"""

from services.infonet.markets.data_unavailable import (
    is_data_unavailable_triggered,
    resolve_data_unavailable_effects,
)
from services.infonet.markets.dispute import (
    DisputeView,
    collect_disputes,
    compute_dispute_outcome,
    dispute_settlement_effects,
    effective_outcome,
    market_was_reversed,
)
from services.infonet.markets.evidence import (
    EvidenceBundle,
    collect_evidence,
    evidence_content_hash,
    is_first_for_side,
    submission_hash,
)
from services.infonet.markets.lifecycle import (
    MarketStatus,
    compute_market_status,
    should_advance_phase,
)
from services.infonet.markets.resolution import (
    ResolutionResult,
    collect_resolution_stakes,
    excluded_predictor_ids,
    is_predictor_excluded,
    resolve_market,
)
from services.infonet.markets.snapshot import (
    build_snapshot,
    compute_snapshot_event_hash,
    find_snapshot,
)
from services.infonet.markets.stalemate_burn import (
    apply_to_stakes as apply_stalemate_burn,
    stalemate_burn_pct,
)

__all__ = [
    "DisputeView",
    "EvidenceBundle",
    "MarketStatus",
    "ResolutionResult",
    "apply_stalemate_burn",
    "build_snapshot",
    "collect_disputes",
    "collect_evidence",
    "collect_resolution_stakes",
    "compute_dispute_outcome",
    "compute_market_status",
    "compute_snapshot_event_hash",
    "dispute_settlement_effects",
    "effective_outcome",
    "evidence_content_hash",
    "excluded_predictor_ids",
    "find_snapshot",
    "is_data_unavailable_triggered",
    "is_first_for_side",
    "is_predictor_excluded",
    "market_was_reversed",
    "resolve_data_unavailable_effects",
    "resolve_market",
    "should_advance_phase",
    "stalemate_burn_pct",
    "submission_hash",
]
