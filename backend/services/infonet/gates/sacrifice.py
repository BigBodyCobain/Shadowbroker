"""Gate sacrifice mechanic — burn-on-entry, not threshold check.

Source of truth: ``infonet-economy/RULES_SKELETON.md`` §3.16, §5.3 step 2.

A node enters a gate by **burning** common rep equal to
``gate.entry_sacrifice``. The burn is permanent and non-refundable
(even on voluntary exit). This is the constitutional difference from
threshold-based access: you can't fake having enough rep — you have
to spend it.

The eligibility checks happen *before* the burn:

- Node's common rep ≥ ``min_overall_rep + entry_sacrifice``.
- Node's per-gate rep meets each ``min_gate_rep[required_gate]``.

If those pass, the entry is accepted, ``entry_sacrifice`` is burned
from the node's common rep, and the node is recorded as a member.

This module exposes pure functions:

- ``can_enter(node_id, gate_id, chain)`` — eligibility check + cost,
  returning a structured ``EntryDecision`` so the UI can render
  exactly *why* a node can't enter (cross-cutting non-hostile UX rule).
- ``compute_member_set(gate_id, chain)`` — current members from
  ``gate_enter`` − ``gate_exit`` events.
- ``is_member(node_id, gate_id, chain)`` — convenience.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from services.infonet.gates.state import events_for_gate, get_gate_meta
from services.infonet.reputation import compute_common_rep


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    p = event.get("payload")
    return p if isinstance(p, dict) else {}


def compute_member_set(
    gate_id: str,
    chain: Iterable[dict[str, Any]],
) -> set[str]:
    """Current member set: ``gate_enter`` − ``gate_exit`` − members
    booted by ``gate_shutdown_execute``. The shutdown case zeroes the
    set out — once a gate is shut down, there are no members.
    """
    chain_list = list(chain)
    events = events_for_gate(gate_id, chain_list)
    members: set[str] = set()
    shutdown_seen = False
    for ev in events:
        et = ev.get("event_type")
        if et == "gate_shutdown_execute":
            shutdown_seen = True
            members = set()
            continue
        node = ev.get("node_id")
        if not isinstance(node, str) or not node:
            continue
        if et == "gate_enter":
            if not shutdown_seen:
                members.add(node)
        elif et == "gate_exit":
            members.discard(node)
    return members


def is_member(
    node_id: str,
    gate_id: str,
    chain: Iterable[dict[str, Any]],
) -> bool:
    return node_id in compute_member_set(gate_id, list(chain))


@dataclass(frozen=True)
class EntryRefusal:
    """Structured "why a node can't enter" diagnostic.

    The cross-cutting non-hostile UX rule (BUILD_LOG.md design rules
    §1) requires the UI to show the user a path forward — not a
    blanket "denied". This dataclass carries enough info for the
    frontend to render "you need 5 more common rep" or "you need
    more rep in gate X".
    """
    kind: str
    detail: str


@dataclass(frozen=True)
class EntryDecision:
    accepted: bool
    cost: int
    refusals: tuple[EntryRefusal, ...]


def compute_gate_rep(
    node_id: str,
    gate_id: str,
    chain: Iterable[dict[str, Any]],
) -> float:
    """Per-gate reputation: common rep earned from upreps cast by
    members of ``gate_id``.

    Sprint 6 ships a simple variant: same formula as
    ``compute_common_rep`` but only upreps from current members of
    ``gate_id`` count. Anti-gaming penalties (Sprint 3) still apply
    via the underlying ``compute_common_rep`` call when called with
    the synthetic chain — but for Sprint 6 we filter at the chain
    level and pass the filtered chain to the global function.

    A more sophisticated per-gate formula (e.g. using only upreps
    that happened *while* the upreper was a member, or weighting by
    in-gate activity) is open for governance to specify later.
    """
    chain_list = [e for e in chain if isinstance(e, dict)]
    members = compute_member_set(gate_id, chain_list)
    if not members:
        return 0.0
    # Filter to upreps authored by current gate members targeting node_id.
    # Pass the WHOLE chain to compute_common_rep (it needs full event
    # history for oracle_rep computation of the upreper); but limit
    # which uprep events count by stripping non-member ones.
    filtered: list[dict[str, Any]] = []
    for ev in chain_list:
        if ev.get("event_type") == "uprep":
            author = ev.get("node_id")
            if author not in members:
                continue
        filtered.append(ev)
    return compute_common_rep(node_id, filtered)


def can_enter(
    node_id: str,
    gate_id: str,
    chain: Iterable[dict[str, Any]],
) -> EntryDecision:
    """RULES §3.16 — eligibility + cost.

    Returns a structured decision. ``accepted=True`` means: burning
    ``cost`` common rep from ``node_id`` satisfies all entry rules.
    ``accepted=False`` lists every reason refusal occurred so the UI
    can show all of them at once.
    """
    chain_list = list(chain)
    meta = get_gate_meta(gate_id, chain_list)
    if meta is None:
        return EntryDecision(
            accepted=False, cost=0,
            refusals=(EntryRefusal(kind="gate_not_found", detail=gate_id),),
        )
    if is_member(node_id, gate_id, chain_list):
        return EntryDecision(
            accepted=False, cost=0,
            refusals=(EntryRefusal(kind="already_member", detail=gate_id),),
        )

    refusals: list[EntryRefusal] = []
    common_rep = compute_common_rep(node_id, chain_list)
    needed = meta.min_overall_rep + meta.entry_sacrifice
    if common_rep < needed:
        refusals.append(EntryRefusal(
            kind="insufficient_common_rep",
            detail=f"have {common_rep:.4f}, need {needed} (min_overall_rep "
                   f"{meta.min_overall_rep} + entry_sacrifice {meta.entry_sacrifice})",
        ))
    for required_gate, min_rep in meta.min_gate_rep.items():
        gate_rep = compute_gate_rep(node_id, required_gate, chain_list)
        if gate_rep < min_rep:
            refusals.append(EntryRefusal(
                kind="insufficient_gate_rep",
                detail=f"gate {required_gate}: have {gate_rep:.4f}, need {min_rep}",
            ))
    return EntryDecision(
        accepted=not refusals, cost=meta.entry_sacrifice if not refusals else 0,
        refusals=tuple(refusals),
    )


__all__ = [
    "EntryDecision",
    "EntryRefusal",
    "can_enter",
    "compute_gate_rep",
    "compute_member_set",
    "is_member",
]
