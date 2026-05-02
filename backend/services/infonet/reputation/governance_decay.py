"""Governance weight decay — oracle_rep → oracle_rep_active.

Source of truth: ``infonet-economy/RULES_SKELETON.md`` §3.11.

``oracle_rep_active`` is **only** used for governance weight (petition
signatures, voting, quorum). Resolution staking, dispute staking, and
truth staking continue to use ``oracle_rep`` directly — dormant oracles
can still verify reality even if they aren't governing.

A successful prediction (``last_successful_prediction_ts`` is non-None)
within the decay window keeps a node at full governance weight. Beyond
the window, weight halves (default factor 0.5) per period.

Implemented as a pure function over the chain so every node computes
the same value from the same chain history.
"""

from __future__ import annotations

import math
from typing import Any, Iterable

from services.infonet.config import CONFIG
from services.infonet.reputation.oracle_rep import (
    compute_oracle_rep,
    last_successful_prediction_ts,
)


_SECONDS_PER_DAY = 86400.0


def decay_factor_for_age(days_since_success: float | None) -> float:
    """Return the multiplier for ``oracle_rep`` → ``oracle_rep_active``.

    - ``None``: node has no qualifying success → factor of 0 (no
      governance weight; new nodes earn it by predicting correctly in a
      mintable market).
    - within the decay window (``governance_decay_days``): 1.0.
    - beyond: ``governance_decay_factor ** decay_periods``.
    """
    if days_since_success is None:
        return 0.0
    decay_days = float(CONFIG["governance_decay_days"])
    factor = float(CONFIG["governance_decay_factor"])
    if not (0.0 < factor < 1.0):
        # Guard: schema bounds should prevent this, but if a malformed
        # config slips through, treat as no-decay.
        return 1.0 if days_since_success <= decay_days else 0.0
    if days_since_success <= decay_days:
        return 1.0
    decay_periods = math.floor(days_since_success / decay_days)
    return factor ** decay_periods


def compute_oracle_rep_active(
    node_id: str,
    chain: Iterable[dict[str, Any]],
    now: float,
) -> float:
    """Governance-weighted oracle rep at chain time ``now``.

    ``now`` is passed in (rather than read from ``time.time()``) so the
    function stays pure and so tests / replay always produce
    deterministic answers. Production callers pass
    ``time_validity.chain_majority_time(chain)``.
    """
    events = list(chain)
    balance = compute_oracle_rep(node_id, events)
    if balance <= 0:
        return 0.0
    last_ts = last_successful_prediction_ts(node_id, events)
    if last_ts is None:
        return 0.0
    days = max(0.0, (float(now) - last_ts) / _SECONDS_PER_DAY)
    return balance * decay_factor_for_age(days)


__all__ = [
    "compute_oracle_rep_active",
    "decay_factor_for_age",
]
