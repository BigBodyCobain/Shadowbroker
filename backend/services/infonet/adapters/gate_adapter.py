"""Gate adapter — Sprint 6 implementation.

Bridges chain history to the gate sacrifice / locking / shutdown
lifecycle. Same ``chain_provider`` pattern as the other adapters.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Iterable

from services.infonet.gates import (
    AppealValidation,
    EntryDecision,
    GateMeta,
    LockedGateState,
    ShutdownState,
    SuspensionState,
    can_enter,
    compute_member_set,
    compute_shutdown_state,
    compute_suspension_state,
    cumulative_member_oracle_rep,
    get_gate_meta,
    is_locked,
    is_member,
    is_ratified,
    locked_at,
    locked_by,
    paused_execution_remaining_sec,
    validate_appeal_filing,
    validate_lock_request,
    validate_shutdown_filing,
    validate_suspend_filing,
)
from services.infonet.gates.locking import LockValidation
from services.infonet.gates.shutdown.suspend import FilingValidation
from services.infonet.time_validity import chain_majority_time


_ChainProvider = Callable[[], Iterable[dict[str, Any]]]


def _empty_chain() -> list[dict[str, Any]]:
    return []


class InfonetGateAdapter:
    """Project chain state into gate views."""

    def __init__(self, chain_provider: _ChainProvider | None = None) -> None:
        self._chain_provider: _ChainProvider = chain_provider or _empty_chain

    def _events(self) -> list[dict[str, Any]]:
        return [e for e in self._chain_provider() if isinstance(e, dict)]

    def _now(self, override: float | None) -> float:
        if override is not None:
            return float(override)
        events = self._events()
        chain_now = chain_majority_time(events)
        return chain_now if chain_now > 0 else float(time.time())

    # ── Metadata + membership ────────────────────────────────────────
    def gate_meta(self, gate_id: str) -> GateMeta | None:
        return get_gate_meta(gate_id, self._events())

    def member_set(self, gate_id: str) -> set[str]:
        return compute_member_set(gate_id, self._events())

    def is_member(self, node_id: str, gate_id: str) -> bool:
        return is_member(node_id, gate_id, self._events())

    def can_enter(self, node_id: str, gate_id: str) -> EntryDecision:
        return can_enter(node_id, gate_id, self._events())

    # ── Ratification ─────────────────────────────────────────────────
    def is_ratified(self, gate_id: str) -> bool:
        return is_ratified(gate_id, self._events())

    def cumulative_member_oracle_rep(self, gate_id: str) -> float:
        return cumulative_member_oracle_rep(gate_id, self._events())

    # ── Locking ──────────────────────────────────────────────────────
    def is_locked(self, gate_id: str) -> bool:
        return is_locked(gate_id, self._events())

    def locked_state(self, gate_id: str) -> LockedGateState:
        events = self._events()
        return LockedGateState(
            locked=is_locked(gate_id, events),
            locked_at=locked_at(gate_id, events),
            locked_by=locked_by(gate_id, events),
        )

    def validate_lock_request(
        self, node_id: str, gate_id: str, *, lock_cost: int | None = None,
    ) -> LockValidation:
        return validate_lock_request(node_id, gate_id, self._events(), lock_cost=lock_cost)

    # ── Suspension ───────────────────────────────────────────────────
    def suspension_state(
        self, gate_id: str, *, now: float | None = None,
    ) -> SuspensionState:
        return compute_suspension_state(gate_id, self._events(), now=self._now(now))

    def validate_suspend_filing(
        self,
        gate_id: str,
        filer_id: str,
        *,
        reason: str,
        evidence_hashes: list[str],
        now: float | None = None,
        filer_cooldown_until: float | None = None,
    ) -> FilingValidation:
        return validate_suspend_filing(
            gate_id, filer_id,
            reason=reason, evidence_hashes=evidence_hashes,
            chain=self._events(), now=self._now(now),
            filer_cooldown_until=filer_cooldown_until,
        )

    # ── Shutdown ─────────────────────────────────────────────────────
    def shutdown_state(
        self, gate_id: str, *, now: float | None = None,
    ) -> ShutdownState:
        return compute_shutdown_state(gate_id, self._events(), now=self._now(now))

    def validate_shutdown_filing(
        self,
        gate_id: str,
        filer_id: str,
        *,
        reason: str,
        evidence_hashes: list[str],
        now: float | None = None,
        filer_cooldown_until: float | None = None,
    ) -> FilingValidation:
        return validate_shutdown_filing(
            gate_id, filer_id,
            reason=reason, evidence_hashes=evidence_hashes,
            chain=self._events(), now=self._now(now),
            filer_cooldown_until=filer_cooldown_until,
        )

    # ── Appeal ───────────────────────────────────────────────────────
    def validate_appeal_filing(
        self,
        gate_id: str,
        target_petition_id: str,
        filer_id: str,
        *,
        reason: str,
        evidence_hashes: list[str],
        now: float | None = None,
        filer_cooldown_until: float | None = None,
    ) -> AppealValidation:
        return validate_appeal_filing(
            gate_id, target_petition_id, filer_id,
            reason=reason, evidence_hashes=evidence_hashes,
            chain=self._events(), now=self._now(now),
            filer_cooldown_until=filer_cooldown_until,
        )

    def paused_execution_remaining_sec(
        self,
        target_petition_id: str,
        *,
        appeal_filed_at: float,
    ) -> float:
        return paused_execution_remaining_sec(
            target_petition_id, self._events(),
            appeal_filed_at=appeal_filed_at,
        )


__all__ = ["InfonetGateAdapter"]
