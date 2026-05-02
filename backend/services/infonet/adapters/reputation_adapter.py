"""Adapter that projects chain history into the new reputation views.

Sprint 2: real implementation. Replaces the Sprint 1 ``NotImplementedError``
skeleton with the pure functions in ``services/infonet/reputation/``.

Why this exists rather than callers importing the pure functions
directly: the adapter is the single integration boundary that future
sprints will extend (Sprint 3 wraps anti-gaming penalties around the
common-rep view, Sprint 4 extends the oracle-rep balance with
resolution-stake redistribution, Sprint 5 layers in dispute reversal).
By keeping callers on this adapter, the producer code never has to
change as those layers ship.

The adapter takes a ``chain_provider`` callable rather than reaching
into ``mesh_hashchain`` itself. Two reasons:

1. Tests pass a list of synthetic events directly — no hashchain
   instance required, no fixture overhead.
2. Sprint 4 cutover decisions (parallel append surface vs unifying
   ``ACTIVE_APPEND_EVENT_TYPES``) won't ripple into reputation code.

Cross-cutting design rule: reputation reads are background work. They
must NEVER block a user-facing request. The adapter exposes only pure
synchronous functions because they ARE pure — caches at the adapter
layer (Sprint 3+) make repeat reads cheap. Callers that need real-time
freshness should call directly on each request; callers that can
tolerate staleness should poll a cached adapter instance.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Iterable

from services.infonet.reputation import (
    OracleRepBreakdown,
    compute_common_rep,
    compute_oracle_rep,
    compute_oracle_rep_active,
    compute_oracle_rep_lifetime,
    decay_factor_for_age,
    last_successful_prediction_ts,
)
from services.infonet.reputation.oracle_rep import compute_oracle_rep_breakdown
from services.infonet.time_validity import chain_majority_time


_ChainProvider = Callable[[], Iterable[dict[str, Any]]]


def _empty_chain() -> list[dict[str, Any]]:
    return []


class InfonetReputationAdapter:
    """Project chain state into oracle/common rep views.

    ``chain_provider`` is a zero-arg callable returning an iterable of
    chain events. Pass a closure that reads from
    ``mesh_hashchain.Infonet.events`` in production, or a literal list
    in tests.
    """

    def __init__(self, chain_provider: _ChainProvider | None = None) -> None:
        self._chain_provider: _ChainProvider = chain_provider or _empty_chain

    def _events(self) -> list[dict[str, Any]]:
        return [e for e in self._chain_provider() if isinstance(e, dict)]

    def oracle_rep(self, node_id: str) -> float:
        return compute_oracle_rep(node_id, self._events())

    def oracle_rep_breakdown(self, node_id: str) -> OracleRepBreakdown:
        return compute_oracle_rep_breakdown(node_id, self._events())

    def oracle_rep_lifetime(self, node_id: str) -> float:
        return compute_oracle_rep_lifetime(node_id, self._events())

    def oracle_rep_active(self, node_id: str, *, now: float | None = None) -> float:
        events = self._events()
        if now is None:
            chain_now = chain_majority_time(events)
            # Fall back to local clock only when the chain has no
            # distinct-node history yet (genesis / fresh mesh). This is
            # the only place a local clock leaks into governance —
            # acceptable because there are no oracles to penalize yet.
            now = chain_now if chain_now > 0 else time.time()
        return compute_oracle_rep_active(node_id, events, now=now)

    def common_rep(self, node_id: str) -> float:
        return compute_common_rep(node_id, self._events())

    def last_successful_prediction_ts(self, node_id: str) -> float | None:
        return last_successful_prediction_ts(node_id, self._events())

    def decay_factor(self, node_id: str, *, now: float | None = None) -> float:
        events = self._events()
        if now is None:
            now = chain_majority_time(events) or time.time()
        last_ts = last_successful_prediction_ts(node_id, events)
        if last_ts is None:
            return 0.0
        days = max(0.0, (float(now) - last_ts) / 86400.0)
        return decay_factor_for_age(days)


__all__ = ["InfonetReputationAdapter"]
