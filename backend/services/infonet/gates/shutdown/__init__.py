"""Gate shutdown lifecycle — Tier 1 suspend, Tier 2 shutdown, typed appeal.

Source of truth: ``infonet-economy/RULES_SKELETON.md`` §5.5.

Three modules with clean separation of concerns:

- ``suspend.py`` — Tier 1: 30-day reversible freeze. Filed via
  ``gate_suspend_file``, voted on, executed via
  ``gate_suspend_execute``, auto-unsuspends after 30 days unless a
  shutdown petition passes.
- ``shutdown.py`` — Tier 2: 7-day-delayed archive. PREREQUISITE: gate
  must currently be suspended.
- ``appeal.py`` — Typed shutdown appeal: pauses the 7-day execution
  timer, max one appeal per shutdown, 48h window after vote passage.
"""

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

__all__ = [
    "AppealValidation",
    "ShutdownState",
    "SuspensionState",
    "compute_shutdown_state",
    "compute_suspension_state",
    "paused_execution_remaining_sec",
    "validate_appeal_filing",
    "validate_shutdown_filing",
    "validate_suspend_filing",
]
