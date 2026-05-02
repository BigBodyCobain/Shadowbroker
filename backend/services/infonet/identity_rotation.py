"""Identity rotation gates and obligation inheritance.

Source of truth: ``infonet-economy/RULES_SKELETON.md`` §3.13.

Pure functions over the chain. Two sets of responsibilities:

1. **Gating (``validate_rotation``):** reject a rotation if the old
   identity holds active resolution stakes, dispute stakes, or truth
   stakes. Predictor exclusion + governance decay + rep transfer are
   inherited automatically by ``rotation_descendants`` — they are NOT
   gates, they are computations downstream resolvers run.

2. **Descendant tracking (``rotation_descendants``):** given a node,
   return the full transitive closure of identities it has rotated
   into. Used by Sprint 4's predictor-exclusion logic to compute
   ``frozen_predictor_ids ∪ rotation_descendants(frozen_predictor_ids)``
   from the snapshot at resolution time.

Cross-cutting design rule (BUILD_LOG.md): a user attempting to rotate
while holding active stakes must NOT see a hostile UI message. The
caller is expected to:

- Show the user which stakes are blocking rotation.
- Offer to wait for those stakes to settle, or cancel pending
  unresolved stakes (where the protocol allows).
- Queue the rotation for retry after settlement.

This module returns structured rejection reasons (a tuple of
``(blocker_kind, count, sample_ids)``) so the UI can render exactly
that. It never returns "rejected" without the diagnostic shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class RotationBlocker:
    """One reason the rotation is currently rejected.

    ``kind`` is one of:
      - ``"resolution_stake"``  — open resolution stakes on a market
        that has not yet finalized.
      - ``"dispute_stake"``     — open dispute stakes that have not yet
        resolved.
      - ``"truth_stake"``       — truth stakes still inside their
        ``duration_days`` window without a resolve event.

    ``count`` is the number of blocking obligations of that kind.
    ``sample_ids`` is up to 5 string identifiers (market_id /
    dispute_id / message_id) so the UI can show "3 markets and 1
    dispute are still pending" with deep links.
    """
    kind: str
    count: int
    sample_ids: tuple[str, ...]


@dataclass(frozen=True)
class RotationDecision:
    accepted: bool
    blockers: tuple[RotationBlocker, ...]


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    p = event.get("payload")
    return p if isinstance(p, dict) else {}


def _market_status_lookup(events: list[dict[str, Any]]) -> dict[str, str]:
    """Last-write-wins map of market_id → terminal status.

    Sprint 2 only knows two terminal statuses (FINAL, INVALID) — the
    full lifecycle is Sprint 4. Markets without a ``resolution_finalize``
    are treated as still open (active stakes).
    """
    status: dict[str, str] = {}
    for ev in events:
        if ev.get("event_type") != "resolution_finalize":
            continue
        p = _payload(ev)
        mid = p.get("market_id")
        if isinstance(mid, str) and mid:
            outcome = p.get("outcome")
            status[mid] = "invalid" if outcome == "invalid" else "final"
    return status


def _dispute_status_lookup(events: list[dict[str, Any]]) -> dict[str, str]:
    status: dict[str, str] = {}
    for ev in events:
        if ev.get("event_type") != "dispute_resolve":
            continue
        p = _payload(ev)
        did = p.get("dispute_id")
        if isinstance(did, str) and did:
            status[did] = "resolved"
    return status


def _truth_stake_resolved_messages(events: list[dict[str, Any]]) -> set[str]:
    resolved: set[str] = set()
    for ev in events:
        if ev.get("event_type") != "truth_stake_resolve":
            continue
        p = _payload(ev)
        mid = p.get("message_id")
        if isinstance(mid, str) and mid:
            resolved.add(mid)
    return resolved


def _active_resolution_stakes(node_id: str, events: list[dict[str, Any]]) -> list[str]:
    market_status = _market_status_lookup(events)
    out: list[str] = []
    for ev in events:
        if ev.get("event_type") != "resolution_stake":
            continue
        if ev.get("node_id") != node_id:
            continue
        p = _payload(ev)
        mid = p.get("market_id")
        if not isinstance(mid, str) or not mid:
            continue
        if market_status.get(mid) is None:
            out.append(mid)
    return out


def _active_dispute_stakes(node_id: str, events: list[dict[str, Any]]) -> list[str]:
    dispute_status = _dispute_status_lookup(events)
    out: list[str] = []
    for ev in events:
        if ev.get("event_type") != "dispute_stake":
            continue
        if ev.get("node_id") != node_id:
            continue
        p = _payload(ev)
        did = p.get("dispute_id")
        if not isinstance(did, str) or not did:
            continue
        if dispute_status.get(did) is None:
            out.append(did)
    return out


def _active_truth_stakes(
    node_id: str,
    events: list[dict[str, Any]],
    *,
    now: float,
) -> list[str]:
    """A truth stake is active if its (placed_at + duration_days * 86400)
    is in the future relative to ``now`` AND no ``truth_stake_resolve``
    has landed for its message.
    """
    resolved = _truth_stake_resolved_messages(events)
    out: list[str] = []
    for ev in events:
        if ev.get("event_type") != "truth_stake_place":
            continue
        if ev.get("node_id") != node_id:
            continue
        p = _payload(ev)
        mid = p.get("message_id")
        if not isinstance(mid, str) or not mid:
            continue
        if mid in resolved:
            continue
        try:
            placed_at = float(ev.get("timestamp") or 0.0)
            duration_days = int(p.get("duration_days") or 0)
        except (TypeError, ValueError):
            continue
        expires_at = placed_at + duration_days * 86400.0
        if expires_at > now:
            out.append(mid)
    return out


def validate_rotation(
    rotation_event: dict[str, Any],
    chain: Iterable[dict[str, Any]],
    *,
    now: float,
) -> RotationDecision:
    """Decide whether ``rotation_event`` is permitted right now.

    Sprint 2 enforces RULES §3.13 Gate 1 only. Gate 2 (obligation
    inheritance) is computation, not gating, and is handled by the
    Sprint 4 predictor-exclusion logic that consults
    ``rotation_descendants``.

    The returned ``RotationDecision`` includes structured blockers so
    the UI can offer a non-hostile retry path (see module docstring).
    """
    if rotation_event.get("event_type") != "identity_rotate":
        raise ValueError("validate_rotation requires an identity_rotate event")
    payload = _payload(rotation_event)
    old_node_id = payload.get("old_node_id")
    if not isinstance(old_node_id, str) or not old_node_id:
        raise ValueError("identity_rotate payload missing old_node_id")

    events = [e for e in chain if isinstance(e, dict)]

    blockers: list[RotationBlocker] = []
    res = _active_resolution_stakes(old_node_id, events)
    if res:
        blockers.append(RotationBlocker(
            kind="resolution_stake",
            count=len(res),
            sample_ids=tuple(res[:5]),
        ))
    dis = _active_dispute_stakes(old_node_id, events)
    if dis:
        blockers.append(RotationBlocker(
            kind="dispute_stake",
            count=len(dis),
            sample_ids=tuple(dis[:5]),
        ))
    tru = _active_truth_stakes(old_node_id, events, now=now)
    if tru:
        blockers.append(RotationBlocker(
            kind="truth_stake",
            count=len(tru),
            sample_ids=tuple(tru[:5]),
        ))

    return RotationDecision(accepted=not blockers, blockers=tuple(blockers))


def rotation_descendants(
    node_id: str,
    chain: Iterable[dict[str, Any]],
) -> set[str]:
    """All identities that descend from ``node_id`` via ``identity_rotate``.

    Excludes ``node_id`` itself. Used by Sprint 4 predictor exclusion.
    """
    events = [e for e in chain if isinstance(e, dict)]
    # Build a forward map: old_node_id -> {new_node_id, new_node_id, ...}.
    # New node_id of an identity_rotate is the event's signer (per spec).
    forward: dict[str, set[str]] = {}
    for ev in events:
        if ev.get("event_type") != "identity_rotate":
            continue
        p = _payload(ev)
        old = p.get("old_node_id")
        new = ev.get("node_id")
        if not isinstance(old, str) or not isinstance(new, str):
            continue
        if not old or not new or old == new:
            continue
        forward.setdefault(old, set()).add(new)

    out: set[str] = set()
    stack = list(forward.get(node_id, set()))
    while stack:
        cur = stack.pop()
        if cur in out:
            continue
        out.add(cur)
        for nxt in forward.get(cur, ()):
            if nxt not in out:
                stack.append(nxt)
    return out


__all__ = [
    "RotationBlocker",
    "RotationDecision",
    "rotation_descendants",
    "validate_rotation",
]
