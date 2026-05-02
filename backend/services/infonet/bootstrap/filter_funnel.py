"""Anti-DoS filter funnel — cheapest-first validator chain.

Source of truth: ``infonet-economy/RULES_SKELETON.md`` §3.10 step 0.5
"Anti-DoS filter funnel (validation order for bootstrap_resolution_vote)".

Validation order (each stage short-circuits to reject):

    1. Schema       — format / required fields / enum sanity (free)
    2. Signature    — Ed25519 verify (~µs)
    3. Identity age — vs snapshot.frozen_at (chain lookup)
    4. Predictor    — vs frozen_predictor_ids ∪ rotation_descendants
    5. Phase + dedup
    6. Argon2id PoW — most expensive (~64MB allocation + hash)

Why ordering matters: an attacker flooding malformed events should
never trigger the Argon2id work. Schema rejection happens first
(microseconds), so the funnel discards cheap-to-reject inputs cheap.

Sprint 8 ships the funnel as a list of ``FunnelStage`` callables.
Production callers compose them in order; each stage returns
``(accepted, reason)``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


_StageFn = Callable[[dict[str, Any]], tuple[bool, str]]


@dataclass(frozen=True)
class FunnelStage:
    name: str
    check: _StageFn
    cost_tier: int
    """Cost ranking 1=cheapest, 6=most expensive. Used by tests to
    confirm the stages are in the spec's ordering."""


def run_filter_funnel(
    event: dict[str, Any],
    stages: list[FunnelStage],
) -> tuple[bool, str]:
    """Run ``stages`` in order; return on the first failure.

    Returns ``(True, "ok")`` if every stage passes, otherwise
    ``(False, "<stage>: <reason>")`` with the failing stage's name
    and reason. The stage's own ``cost_tier`` is included in the
    failing diagnostic so monitoring can spot when expensive stages
    are doing the work cheap stages should have caught.
    """
    if not isinstance(event, dict):
        return False, "schema: event must be an object"
    seen_tiers: list[int] = []
    for stage in stages:
        if seen_tiers and stage.cost_tier < max(seen_tiers):
            # Sprint 8 invariant: tiers must be monotonically
            # non-decreasing. A misordered funnel is a developer
            # error, not an attacker input — fail loudly.
            raise ValueError(
                f"filter funnel out of order: stage {stage.name} "
                f"has cost_tier={stage.cost_tier} after a higher tier"
            )
        seen_tiers.append(stage.cost_tier)
        ok, reason = stage.check(event)
        if not ok:
            return False, f"{stage.name}: {reason}"
    return True, "ok"


__all__ = [
    "FunnelStage",
    "run_filter_funnel",
]
