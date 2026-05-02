"""Event construction helpers for the Infonet economy.

A thin layer over ``services/infonet/schema.py``: each public function
builds a payload dict for one event type, validates it, and returns it.
The caller is responsible for signing the event and routing it through
``services/infonet/adapters/hashchain_adapter.py`` for actual append.

Sprint 1 scope: payload builders + validation. No chain writes. The
hashchain adapter's ``append_infonet_event`` is the eventual integration
point — see ``adapters/hashchain_adapter.py``.

Why a builder layer and not free-form dicts:
- Centralizes the canonical field set per event_type so callers can't
  drift from the schema.
- Allows future sprints to attach deterministic computation (e.g.
  ``probability_at_bet`` reconstruction in Sprint 4) without changing
  callers.
- Matches the "events extend, never replace" rule from the plan §3.1 —
  the legacy event constructors in ``mesh_schema.py`` keep working
  unchanged; new event types live here.
"""

from __future__ import annotations

from typing import Any

from services.infonet.schema import (
    INFONET_ECONOMY_EVENT_TYPES,
    validate_infonet_event_payload,
)


class EventConstructionError(ValueError):
    """Raised when a payload fails validation at build time.

    Distinct from chain-level errors (signature, replay, sequence) —
    those originate in the hashchain adapter, not here.
    """


def build_event(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Validate and return a payload for ``event_type``.

    The returned dict is a shallow copy — callers can attach signature,
    sequence, public_key, etc. before passing it to the hashchain
    adapter for append.
    """
    if event_type not in INFONET_ECONOMY_EVENT_TYPES:
        raise EventConstructionError(
            f"event_type {event_type!r} is not in INFONET_ECONOMY_EVENT_TYPES"
        )
    payload = dict(payload or {})
    ok, reason = validate_infonet_event_payload(event_type, payload)
    if not ok:
        raise EventConstructionError(f"{event_type}: {reason}")
    return payload


# ─── Convenience builders ────────────────────────────────────────────────
# Sprint 1 ships only a representative slice. Full per-type builders for
# the producing modules (markets/, gates/, governance/, ...) live in
# their respective sprints — they will all funnel through ``build_event``
# so this module stays the single validation choke point.

def build_uprep(target_node_id: str, target_event_id: str) -> dict[str, Any]:
    return build_event("uprep", {
        "target_node_id": target_node_id,
        "target_event_id": target_event_id,
    })


def build_citizenship_claim(sacrifice_amount: int) -> dict[str, Any]:
    return build_event("citizenship_claim", {"sacrifice_amount": sacrifice_amount})


def build_petition_file(
    petition_id: str,
    petition_payload: dict[str, Any],
) -> dict[str, Any]:
    return build_event("petition_file", {
        "petition_id": petition_id,
        "petition_payload": petition_payload,
    })


def build_petition_vote(petition_id: str, vote: str) -> dict[str, Any]:
    return build_event("petition_vote", {"petition_id": petition_id, "vote": vote})


def build_node_register(public_key: str, public_key_algo: str, node_class: str) -> dict[str, Any]:
    return build_event("node_register", {
        "public_key": public_key,
        "public_key_algo": public_key_algo,
        "node_class": node_class,
    })


__all__ = [
    "EventConstructionError",
    "build_citizenship_claim",
    "build_event",
    "build_node_register",
    "build_petition_file",
    "build_petition_vote",
    "build_uprep",
]
