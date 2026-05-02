"""Progressive penalty — whale deterrence.

Source of truth: ``infonet-economy/RULES_SKELETON.md`` §3.6.

    base_penalty   = correlation_score   # 0.0 to 1.0
    rep_multiplier = 1 + log2(max(oracle_rep, 1))
    rep_docked     = base_penalty * rep_multiplier

The point: a whale with 1024 oracle rep faces a multiplier of 11×, so
the same correlation score that would dock a small node 0.5 rep docks
a whale 5.5 rep. Coordination becomes more expensive as you accumulate
more rep — the protocol's "you can't simply outscale anti-gaming"
defense.

This module exposes the math. Sprint 3 does NOT yet wire it into a
running aggregate-correlation tracker — that requires per-node
correlation history which is a Sprint 4+ concern. The helpers here are
ready for that integration.
"""

from __future__ import annotations

import math


def compute_rep_multiplier(oracle_rep: float) -> float:
    """``1 + log2(max(oracle_rep, 1))``.

    - ``oracle_rep <= 1`` → multiplier 1.0
    - ``oracle_rep == 2`` → 2.0
    - ``oracle_rep == 1024`` → 11.0
    """
    rep = max(1.0, float(oracle_rep))
    return 1.0 + math.log2(rep)


def apply_progressive_penalty(base_penalty: float, oracle_rep: float) -> float:
    """``base_penalty * compute_rep_multiplier(oracle_rep)``.

    ``base_penalty`` is intended to be a non-negative correlation score
    in ``[0.0, 1.0]``; the function does not clamp.
    """
    return float(base_penalty) * compute_rep_multiplier(oracle_rep)


__all__ = [
    "apply_progressive_penalty",
    "compute_rep_multiplier",
]
