"""Governance — petitions, declarative DSL executor, constitutional
challenge, and upgrade-hash governance (Sprint 7).

Source of truth: ``infonet-economy/RULES_SKELETON.md`` §3.15, §5.4, §5.6.

The DSL executor is the centerpiece of Sprint 7. It is intentionally
**not a sandbox**: it cannot run arbitrary code, period. The four
allowed payload types (UPDATE_PARAM / BATCH_UPDATE_PARAMS /
ENABLE_FEATURE / DISABLE_FEATURE) are dispatched as plain Python
switch cases. There is NO ``eval``, ``exec``, ``compile``, or
dynamic attribute access anywhere in the executor. The whole class
of code-injection attacks goes away by design.

Protocol upgrades that need new logic use upgrade-hash governance —
nodes vote on a software release hash, not on-chain code.
"""

from services.infonet.governance.challenge import (
    ChallengeState,
    compute_challenge_state,
    validate_challenge_filing,
)
from services.infonet.governance.dsl_executor import (
    DSLExecutionResult,
    apply_petition_payload,
    forbidden_attributes_check,
)
from services.infonet.governance.petition import (
    PetitionState,
    compute_petition_state,
    network_governance_weight,
    validate_petition_filing,
)
from services.infonet.governance.upgrade_hash import (
    HeavyNodeReadinessState,
    UpgradeProposalState,
    compute_upgrade_state,
    validate_upgrade_proposal,
)

__all__ = [
    "ChallengeState",
    "DSLExecutionResult",
    "HeavyNodeReadinessState",
    "PetitionState",
    "UpgradeProposalState",
    "apply_petition_payload",
    "compute_challenge_state",
    "compute_petition_state",
    "compute_upgrade_state",
    "forbidden_attributes_check",
    "network_governance_weight",
    "validate_challenge_filing",
    "validate_petition_filing",
    "validate_upgrade_proposal",
]
