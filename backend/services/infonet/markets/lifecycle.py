"""Market lifecycle state machine.

Source of truth: ``infonet-economy/RULES_SKELETON.md`` §5.2 + §3.10.

Five logical statuses:

    PREDICTING — open for predictions; no snapshot yet.
    EVIDENCE   — snapshot frozen; evidence window open
                 (CONFIG['evidence_window_hours']).
    RESOLVING  — evidence window closed; resolution staking window open
                 (CONFIG['resolution_window_hours']).
    FINAL      — resolution_finalize event landed with a real outcome.
    INVALID    — resolution_finalize event landed with outcome="invalid".

Transitions are decided by ``chain_majority_time`` (per RULES §3.14
Rule 3) — no single node's local clock can unilaterally advance a
market. That rule keeps producers honest even when network partitions
shift local time.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Iterable

from services.infonet.config import CONFIG


class MarketStatus(str, Enum):
    PREDICTING = "predicting"
    EVIDENCE = "evidence"
    RESOLVING = "resolving"
    FINAL = "final"
    INVALID = "invalid"


_SECONDS_PER_HOUR = 3600.0


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    p = event.get("payload")
    return p if isinstance(p, dict) else {}


def _market_id(event: dict[str, Any]) -> str:
    return str(_payload(event).get("market_id") or "")


def _events_for_market(market_id: str, chain: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ev in chain:
        if not isinstance(ev, dict):
            continue
        if _market_id(ev) == market_id:
            out.append(ev)
    out.sort(key=lambda e: (float(e.get("timestamp") or 0.0), int(e.get("sequence") or 0)))
    return out


def compute_market_status(
    market_id: str,
    chain: Iterable[dict[str, Any]],
    *,
    now: float,
) -> MarketStatus:
    """Return the current status of ``market_id`` at chain time ``now``.

    Status is derived from the chain — it's never stored. The producer
    that emits ``market_snapshot`` and ``resolution_finalize`` events
    is responsible for using the same ``now`` value (typically
    ``chain_majority_time(chain)``) so every node converges on the same
    status.
    """
    events = _events_for_market(market_id, chain)
    if not events:
        return MarketStatus.PREDICTING  # treated as not-yet-existing

    create_event = next((e for e in events if e.get("event_type") == "prediction_create"), None)
    if create_event is None:
        return MarketStatus.PREDICTING

    finalize = next((e for e in events if e.get("event_type") == "resolution_finalize"), None)
    if finalize is not None:
        outcome = _payload(finalize).get("outcome")
        return MarketStatus.INVALID if outcome == "invalid" else MarketStatus.FINAL

    snapshot = next((e for e in events if e.get("event_type") == "market_snapshot"), None)
    if snapshot is None:
        return MarketStatus.PREDICTING

    snapshot_ts = float(snapshot.get("timestamp") or _payload(snapshot).get("frozen_at") or 0.0)
    evidence_close = snapshot_ts + float(CONFIG["evidence_window_hours"]) * _SECONDS_PER_HOUR
    if now < evidence_close:
        return MarketStatus.EVIDENCE
    return MarketStatus.RESOLVING


def should_advance_phase(
    market_id: str,
    chain: Iterable[dict[str, Any]],
    *,
    now: float,
) -> tuple[MarketStatus, MarketStatus] | None:
    """If a phase advance is due, return ``(current, next)``. Else ``None``.

    The producer should call this on a heartbeat and emit the
    appropriate event when a transition is ready:

    - PREDICTING → EVIDENCE: emit ``market_snapshot``.
    - EVIDENCE → RESOLVING: just a status change (no chain event).
    - RESOLVING → FINAL/INVALID: emit ``resolution_finalize``.
    """
    events = _events_for_market(market_id, chain)
    if not events:
        return None

    create_event = next((e for e in events if e.get("event_type") == "prediction_create"), None)
    if create_event is None:
        return None
    finalize = next((e for e in events if e.get("event_type") == "resolution_finalize"), None)
    if finalize is not None:
        return None  # already terminal

    create_payload = _payload(create_event)
    trigger_date = float(create_payload.get("trigger_date") or 0.0)
    snapshot = next((e for e in events if e.get("event_type") == "market_snapshot"), None)

    if snapshot is None:
        # PREDICTING — advance to EVIDENCE iff trigger_date has passed in
        # majority chain time.
        if now >= trigger_date:
            return (MarketStatus.PREDICTING, MarketStatus.EVIDENCE)
        return None

    snapshot_ts = float(snapshot.get("timestamp") or _payload(snapshot).get("frozen_at") or 0.0)
    evidence_close = snapshot_ts + float(CONFIG["evidence_window_hours"]) * _SECONDS_PER_HOUR
    resolution_close = evidence_close + float(CONFIG["resolution_window_hours"]) * _SECONDS_PER_HOUR

    if now < evidence_close:
        return None  # still EVIDENCE
    if now < resolution_close:
        return (MarketStatus.EVIDENCE, MarketStatus.RESOLVING)
    return (MarketStatus.RESOLVING, MarketStatus.FINAL)


__all__ = [
    "MarketStatus",
    "compute_market_status",
    "should_advance_phase",
]
