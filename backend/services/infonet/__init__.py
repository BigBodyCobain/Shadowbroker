"""Infonet economy & governance layer.

Layered ON TOP OF the existing mesh primitives in ``services/mesh/``.
The chain-write cutover (2026-04-28) registers Infonet event types
with ``mesh_schema`` and ``mesh_hashchain`` so production writes flow
through the legacy chain. The cutover is performed at import time by
``services.infonet._chain_cutover``.

The only legacy file modified by the cutover is ``mesh_schema.py``,
which gained a generic extension hook (``register_extension_validator``).
``mesh_hashchain.py`` is byte-identical to its Sprint 1 baseline; the
cutover mutates its module-level ``ACTIVE_APPEND_EVENT_TYPES`` set
(which is a mutable ``set``, not a frozenset, by design).

See ``infonet-economy/IMPLEMENTATION_PLAN.md`` and ``infonet-economy/BUILD_LOG.md``
in the repository root for the build order, sprint scope, and integration
principles. ``infonet-economy/RULES_SKELETON.md`` is the source of truth
for any formula / value / state machine implemented here.
"""

# Trigger the chain-write cutover at import time. Idempotent — see
# ``_chain_cutover.perform_cutover``. This must happen before any
# adapter or producer uses mesh_schema.validate_event_payload on a
# new event type.
from services.infonet import _chain_cutover as _chain_cutover_module
_chain_cutover_module.perform_cutover()
del _chain_cutover_module

from services.infonet.config import (
    CONFIG,
    CONFIG_SCHEMA,
    CROSS_FIELD_INVARIANTS,
    IMMUTABLE_PRINCIPLES,
    InvalidPetition,
    reset_config_for_tests,
    validate_config_schema_completeness,
    validate_cross_field_invariants,
    validate_petition_value,
)
from services.infonet.identity_rotation import (
    RotationBlocker,
    RotationDecision,
    rotation_descendants,
    validate_rotation,
)
from services.infonet.markets import (
    EvidenceBundle,
    MarketStatus,
    ResolutionResult,
    build_snapshot,
    collect_evidence,
    collect_resolution_stakes,
    compute_market_status,
    compute_snapshot_event_hash,
    evidence_content_hash,
    excluded_predictor_ids,
    find_snapshot,
    is_first_for_side,
    is_predictor_excluded,
    resolve_market,
    should_advance_phase,
    submission_hash,
)
from services.infonet.reputation import (
    OracleRepBreakdown,
    compute_common_rep,
    compute_oracle_rep,
    compute_oracle_rep_active,
    compute_oracle_rep_lifetime,
    decay_factor_for_age,
    last_successful_prediction_ts,
)
from services.infonet.schema import (
    INFONET_ECONOMY_EVENT_TYPES,
    InfonetEventSchema,
    get_infonet_schema,
    validate_infonet_event_payload,
)
from services.infonet.time_validity import (
    chain_majority_time,
    event_meets_phase_window,
    is_event_too_future,
)

__all__ = [
    "CONFIG",
    "CONFIG_SCHEMA",
    "CROSS_FIELD_INVARIANTS",
    "IMMUTABLE_PRINCIPLES",
    "INFONET_ECONOMY_EVENT_TYPES",
    "EvidenceBundle",
    "InfonetEventSchema",
    "InvalidPetition",
    "MarketStatus",
    "OracleRepBreakdown",
    "ResolutionResult",
    "RotationBlocker",
    "RotationDecision",
    "build_snapshot",
    "chain_majority_time",
    "collect_evidence",
    "collect_resolution_stakes",
    "compute_common_rep",
    "compute_market_status",
    "compute_oracle_rep",
    "compute_oracle_rep_active",
    "compute_oracle_rep_lifetime",
    "compute_snapshot_event_hash",
    "decay_factor_for_age",
    "event_meets_phase_window",
    "evidence_content_hash",
    "excluded_predictor_ids",
    "find_snapshot",
    "get_infonet_schema",
    "is_event_too_future",
    "is_first_for_side",
    "is_predictor_excluded",
    "last_successful_prediction_ts",
    "reset_config_for_tests",
    "resolve_market",
    "rotation_descendants",
    "should_advance_phase",
    "submission_hash",
    "validate_config_schema_completeness",
    "validate_cross_field_invariants",
    "validate_infonet_event_payload",
    "validate_petition_value",
    "validate_rotation",
]
