"""Canonical selection helpers for market events.

The Infonet hashchain is already an append-only ordered sequence. Market
application code must preserve that iteration order instead of deriving a
second history from partially trusted ``timestamp`` or ``sequence`` fields.

Authoritative event selection therefore always chooses the first matching
event in hashchain order. Callers validate that event separately and fail
closed; they must not skip a malformed first authoritative event in favour of
a later replacement.
"""

from __future__ import annotations

import math
from typing import Any, Iterable


def payload(event: dict[str, Any]) -> dict[str, Any]:
    value = event.get("payload")
    return value if isinstance(value, dict) else {}


def market_id(event: dict[str, Any]) -> str:
    return str(payload(event).get("market_id") or "")


def finite_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def has_valid_ordering(event: dict[str, Any]) -> bool:
    """Whether an event carries usable ordering metadata."""
    return finite_float(event.get("timestamp")) is not None and safe_int(
        event.get("sequence")
    ) is not None


def events_for_market(
    market_id_value: str,
    chain: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Filter one market while preserving canonical hashchain iteration order."""
    return [
        event
        for event in chain
        if isinstance(event, dict) and market_id(event) == market_id_value
    ]


def first_authoritative_event(
    events: Iterable[dict[str, Any]],
    event_type: str,
) -> dict[str, Any] | None:
    """Return the first matching event without skipping malformed metadata."""
    return next(
        (event for event in events if event.get("event_type") == event_type),
        None,
    )


__all__ = [
    "events_for_market",
    "finite_float",
    "first_authoritative_event",
    "has_valid_ordering",
    "market_id",
    "payload",
    "safe_int",
]
