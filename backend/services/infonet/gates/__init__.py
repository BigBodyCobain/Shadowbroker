"""Gate sacrifice + locking + shutdown lifecycle (Sprint 6).

Pure-function design: every entry point reads the chain and returns a
deterministic value. State (member set / suspended_until / shutdown
status / appeal status) is derived, never stored.

Source of truth: ``infonet-economy/RULES_SKELETON.md`` §3.16, §5.3,
§5.5.
"""

from services.infonet.gates.locking import (
    LockedGateState,
    is_locked,
    locked_at,
    locked_by,
    validate_lock_request,
)
from services.infonet.gates.ratification import (
    RATIFICATION_THRESHOLD,
    cumulative_member_oracle_rep,
    is_ratified,
)
from services.infonet.gates.sacrifice import (
    EntryDecision,
    EntryRefusal,
    can_enter,
    compute_member_set,
    is_member,
)
from services.infonet.gates.shutdown.appeal import (
    AppealValidation,
    paused_execution_remaining_sec,
    validate_appeal_filing,
)
from services.infonet.gates.shutdown.shutdown import (
    ShutdownState,
    compute_shutdown_state,
    validate_shutdown_filing,
)
from services.infonet.gates.shutdown.suspend import (
    SuspensionState,
    compute_suspension_state,
    validate_suspend_filing,
)
from services.infonet.gates.state import (
    GateMeta,
    events_for_gate,
    get_gate_meta,
)

__all__ = [
    "AppealValidation",
    "EntryDecision",
    "EntryRefusal",
    "GateMeta",
    "LockedGateState",
    "RATIFICATION_THRESHOLD",
    "ShutdownState",
    "SuspensionState",
    "can_enter",
    "compute_member_set",
    "compute_shutdown_state",
    "compute_suspension_state",
    "cumulative_member_oracle_rep",
    "events_for_gate",
    "get_gate_meta",
    "is_locked",
    "is_member",
    "is_ratified",
    "locked_at",
    "locked_by",
    "paused_execution_remaining_sec",
    "validate_appeal_filing",
    "validate_lock_request",
    "validate_shutdown_filing",
    "validate_suspend_filing",
]
