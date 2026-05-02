"""Gate ratification — cumulative oracle rep threshold.

Source of truth: ``infonet-economy/RULES_SKELETON.md`` §5.3 step 3.

A gate is "ratified" once the SUM of its members' oracle rep crosses
``CONFIG['gate_ratification_rep']`` (default 50). Ratification is a
recognition signal — it doesn't gate any functionality, but UI may
surface it as "this gate is established / legitimate".

Pure function over the chain. The threshold is governable via petition
(Sprint 7) by changing the CONFIG value.
"""

from __future__ import annotations

from typing import Any, Iterable

from services.infonet.config import CONFIG
from services.infonet.gates.sacrifice import compute_member_set
from services.infonet.reputation import compute_oracle_rep


def _ratification_threshold() -> int:
    return int(CONFIG["gate_ratification_rep"])


# Public alias for consumers who don't want to import CONFIG.
RATIFICATION_THRESHOLD = _ratification_threshold()


def cumulative_member_oracle_rep(
    gate_id: str,
    chain: Iterable[dict[str, Any]],
) -> float:
    """Sum of current members' oracle rep balances."""
    chain_list = list(chain)
    members = compute_member_set(gate_id, chain_list)
    return sum(compute_oracle_rep(m, chain_list) for m in members)


def is_ratified(
    gate_id: str,
    chain: Iterable[dict[str, Any]],
) -> bool:
    """``True`` once cumulative member oracle rep meets the threshold."""
    return cumulative_member_oracle_rep(gate_id, chain) >= float(_ratification_threshold())


__all__ = [
    "RATIFICATION_THRESHOLD",
    "cumulative_member_oracle_rep",
    "is_ratified",
]
