"""Common chain helpers shared across the gates package.

The legacy ``gate_create`` event is owned by mesh_schema (it predates
the economy layer). Sprint 6 reads those events and extracts the
structured fields it needs from the ``rules`` payload, with sensible
defaults when a key is missing — same pattern the rest of the
protocol uses for forward compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    p = event.get("payload")
    return p if isinstance(p, dict) else {}


def _gate_id(event: dict[str, Any]) -> str:
    p = _payload(event)
    gid = p.get("gate_id") or p.get("gate")
    return str(gid) if isinstance(gid, str) else ""


def events_for_gate(
    gate_id: str,
    chain: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """All events that reference ``gate_id``, sorted by chain order."""
    out: list[dict[str, Any]] = []
    for ev in chain:
        if not isinstance(ev, dict):
            continue
        if _gate_id(ev) == gate_id:
            out.append(ev)
    out.sort(key=lambda e: (float(e.get("timestamp") or 0.0), int(e.get("sequence") or 0)))
    return out


@dataclass(frozen=True)
class GateMeta:
    """Static metadata extracted from the original ``gate_create`` event."""
    gate_id: str
    creator_node_id: str
    display_name: str
    entry_sacrifice: int
    min_overall_rep: int
    min_gate_rep: dict[str, int]
    created_at: float
    raw_rules: dict[str, Any]


def _safe_int(val: Any, default: int = 0) -> int:
    try:
        if isinstance(val, bool):
            return default
        return int(val)
    except (TypeError, ValueError):
        return default


def get_gate_meta(
    gate_id: str,
    chain: Iterable[dict[str, Any]],
) -> GateMeta | None:
    """Return the gate's static metadata, or ``None`` if no
    ``gate_create`` event exists for it on the chain.

    Multiple ``gate_create`` events with the same gate_id are unusual
    but possible at peer-gossip ingestion time; the FIRST one wins
    (same first-write-wins pattern as ``find_snapshot``). Subsequent
    forgeries are ignored.
    """
    for ev in chain:
        if not isinstance(ev, dict):
            continue
        if ev.get("event_type") != "gate_create":
            continue
        if _gate_id(ev) != gate_id:
            continue
        p = _payload(ev)
        rules = p.get("rules")
        if not isinstance(rules, dict):
            rules = {}
        cross_gate = rules.get("min_gate_rep")
        if not isinstance(cross_gate, dict):
            cross_gate = {}
        return GateMeta(
            gate_id=gate_id,
            creator_node_id=str(ev.get("node_id") or ""),
            display_name=str(p.get("display_name") or ""),
            entry_sacrifice=_safe_int(rules.get("entry_sacrifice"), 0),
            min_overall_rep=_safe_int(rules.get("min_overall_rep"), 0),
            min_gate_rep={
                str(k): _safe_int(v, 0)
                for k, v in cross_gate.items()
                if isinstance(k, str) and k
            },
            created_at=float(ev.get("timestamp") or 0.0),
            raw_rules=dict(rules),
        )
    return None


__all__ = [
    "GateMeta",
    "events_for_gate",
    "get_gate_meta",
]
