"""Gate locking — "constitutionalize-a-gate".

Source of truth: ``infonet-economy/RULES_SKELETON.md`` §5.3 step 4 +
``CONFIG['gate_lock_cost_per_member']`` / ``CONFIG['gate_lock_min_members']``.

Locking semantics:

- Each ``gate_lock`` event records one member contributing
  ``CONFIG['gate_lock_cost_per_member']`` (default 10) common rep.
- A gate is "locked" once ≥ ``CONFIG['gate_lock_min_members']``
  (default 5) distinct current members have each emitted a valid
  ``gate_lock`` event.
- Once locked, the gate's rules become immutable — no governance
  petition can modify them. Only an upgrade-hash governance event
  (out of scope for Sprint 6) can amend a locked gate's rules.

Validation rules for an incoming ``gate_lock`` event (callers in
production should run these *before* emitting):

- The gate exists.
- The locker is a current member.
- The locker hasn't already locked this gate (one lock per node).
- The locker has paid (the burn happens at emit time; this module
  asserts the schematic ``lock_cost`` matches CONFIG).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from services.infonet.config import CONFIG
from services.infonet.gates.sacrifice import compute_member_set
from services.infonet.gates.state import events_for_gate


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    p = event.get("payload")
    return p if isinstance(p, dict) else {}


def _lock_cost_per_member() -> int:
    return int(CONFIG["gate_lock_cost_per_member"])


def _lock_min_members() -> int:
    return int(CONFIG["gate_lock_min_members"])


@dataclass(frozen=True)
class LockedGateState:
    locked: bool
    locked_at: float | None
    locked_by: tuple[str, ...]


def _collect_lock_contributions(
    gate_id: str,
    chain: Iterable[dict[str, Any]],
) -> list[tuple[str, float]]:
    """Return ``[(node_id, timestamp)]`` for each accepted ``gate_lock``
    event in chain order. Subsequent locks from the same node are
    ignored (one lock per node)."""
    chain_list = list(chain)
    members = compute_member_set(gate_id, chain_list)
    seen: set[str] = set()
    out: list[tuple[str, float]] = []
    for ev in events_for_gate(gate_id, chain_list):
        if ev.get("event_type") != "gate_lock":
            continue
        node = ev.get("node_id")
        if not isinstance(node, str) or not node:
            continue
        if node in seen:
            continue
        if node not in members:
            # Non-member lock attempt — ignored. The producer-side
            # check should also refuse to emit, but resolver-side
            # enforcement is defense-in-depth.
            continue
        p = _payload(ev)
        try:
            paid = float(p.get("lock_cost") or 0.0)
        except (TypeError, ValueError):
            paid = 0.0
        if paid < float(_lock_cost_per_member()):
            continue
        seen.add(node)
        out.append((node, float(ev.get("timestamp") or 0.0)))
    return out


def _state(gate_id: str, chain: Iterable[dict[str, Any]]) -> LockedGateState:
    contributions = _collect_lock_contributions(gate_id, chain)
    if len(contributions) < _lock_min_members():
        return LockedGateState(locked=False, locked_at=None, locked_by=())
    contributions.sort(key=lambda c: c[1])
    threshold_ts = contributions[_lock_min_members() - 1][1]
    nodes = tuple(c[0] for c in contributions)
    return LockedGateState(locked=True, locked_at=threshold_ts, locked_by=nodes)


def is_locked(gate_id: str, chain: Iterable[dict[str, Any]]) -> bool:
    return _state(gate_id, chain).locked


def locked_at(gate_id: str, chain: Iterable[dict[str, Any]]) -> float | None:
    return _state(gate_id, chain).locked_at


def locked_by(gate_id: str, chain: Iterable[dict[str, Any]]) -> tuple[str, ...]:
    return _state(gate_id, chain).locked_by


@dataclass(frozen=True)
class LockValidation:
    accepted: bool
    reason: str
    cost: int


def validate_lock_request(
    node_id: str,
    gate_id: str,
    chain: Iterable[dict[str, Any]],
    *,
    lock_cost: int | None = None,
) -> LockValidation:
    """Pre-emit check for a ``gate_lock`` event from ``node_id``.

    Returns ``accepted=False`` with a structured ``reason`` when
    rejected — the UI surfaces these directly so the user knows what
    needs to change.
    """
    chain_list = list(chain)
    cost = int(_lock_cost_per_member() if lock_cost is None else lock_cost)
    if cost < _lock_cost_per_member():
        return LockValidation(False, "lock_cost_below_min", cost)
    if node_id not in compute_member_set(gate_id, chain_list):
        return LockValidation(False, "not_a_member", cost)
    if node_id in {n for n, _ in _collect_lock_contributions(gate_id, chain_list)}:
        return LockValidation(False, "already_locked_by_node", cost)
    return LockValidation(True, "ok", cost)


__all__ = [
    "LockedGateState",
    "LockValidation",
    "is_locked",
    "locked_at",
    "locked_by",
    "validate_lock_request",
]
