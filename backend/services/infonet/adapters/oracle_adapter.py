"""Adapter from chain history to the market lifecycle / resolution view.

Sprint 4: real implementation (replaces the Sprint 1 ``NotImplementedError``
skeleton). Wires the pure functions in ``services/infonet/markets/`` to
the same chain-provider pattern used by ``InfonetReputationAdapter``.

Sprint 5 will extend this with dispute open / dispute_stake / dispute
resolve methods. Sprint 8 will extend the resolution path with
bootstrap-mode handling.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable

from services.infonet.markets import (
    DisputeView,
    EvidenceBundle,
    MarketStatus,
    ResolutionResult,
    build_snapshot,
    collect_disputes,
    collect_evidence,
    collect_resolution_stakes,
    compute_dispute_outcome,
    compute_market_status,
    compute_snapshot_event_hash,
    dispute_settlement_effects,
    effective_outcome,
    excluded_predictor_ids,
    find_snapshot,
    is_predictor_excluded,
    market_was_reversed,
    resolve_market,
    should_advance_phase,
)


_ChainProvider = Callable[[], Iterable[dict[str, Any]]]


def _empty_chain() -> list[dict[str, Any]]:
    return []


class InfonetOracleAdapter:
    """Project chain state into market lifecycle + resolution views."""

    def __init__(self, chain_provider: _ChainProvider | None = None) -> None:
        self._chain_provider: _ChainProvider = chain_provider or _empty_chain

    def _events(self) -> list[dict[str, Any]]:
        return [e for e in self._chain_provider() if isinstance(e, dict)]

    # ── Lifecycle ────────────────────────────────────────────────────
    def market_status(self, market_id: str, *, now: float) -> MarketStatus:
        return compute_market_status(market_id, self._events(), now=now)

    def should_advance_phase(
        self, market_id: str, *, now: float,
    ) -> tuple[MarketStatus, MarketStatus] | None:
        return should_advance_phase(market_id, self._events(), now=now)

    # ── Snapshot ─────────────────────────────────────────────────────
    def take_snapshot(self, market_id: str, *, frozen_at: float) -> dict[str, Any]:
        return build_snapshot(market_id, self._events(), frozen_at=frozen_at)

    def find_snapshot(self, market_id: str) -> dict[str, Any] | None:
        return find_snapshot(market_id, self._events())

    @staticmethod
    def snapshot_event_hash(
        snapshot_payload: dict[str, Any],
        *,
        market_id: str,
        creator_node_id: str,
        sequence: int,
    ) -> str:
        return compute_snapshot_event_hash(
            snapshot_payload,
            market_id=market_id,
            creator_node_id=creator_node_id,
            sequence=sequence,
        )

    # ── Evidence ─────────────────────────────────────────────────────
    def collect_evidence(self, market_id: str) -> list[EvidenceBundle]:
        return collect_evidence(market_id, self._events())

    # ── Resolution ───────────────────────────────────────────────────
    def excluded_predictor_ids(self, market_id: str) -> set[str]:
        return excluded_predictor_ids(market_id, self._events())

    def is_predictor_excluded(self, node_id: str, market_id: str) -> bool:
        return is_predictor_excluded(node_id, market_id, self._events())

    def collect_resolution_stakes(self, market_id: str):
        return collect_resolution_stakes(market_id, self._events())

    def resolve_market(
        self, market_id: str, *, is_provisional: bool = False,
    ) -> ResolutionResult:
        return resolve_market(market_id, self._events(), is_provisional=is_provisional)

    # ── Disputes (Sprint 5) ──────────────────────────────────────────
    def collect_disputes(self, market_id: str) -> list[DisputeView]:
        return collect_disputes(market_id, self._events())

    @staticmethod
    def compute_dispute_outcome(dispute: DisputeView) -> str:
        return compute_dispute_outcome(dispute)

    @staticmethod
    def dispute_settlement_effects(dispute: DisputeView) -> dict:
        return dispute_settlement_effects(dispute)

    def market_was_reversed(self, market_id: str) -> bool:
        return market_was_reversed(market_id, self._events())

    def effective_outcome(self, market_id: str, original_outcome: str) -> str:
        return effective_outcome(original_outcome, market_id, self._events())


__all__ = ["InfonetOracleAdapter"]
