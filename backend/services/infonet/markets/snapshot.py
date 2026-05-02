"""Market snapshot — frozen at PREDICTING → EVIDENCE transition.

Source of truth: ``infonet-economy/RULES_SKELETON.md`` §2.2 (snapshot
fields), §3.10 (snapshot_event_hash usage), §5.2 (when emitted).

The snapshot is the **commitment boundary** for all downstream
evaluation. Once frozen:

- Liquidity gates (``min_market_participants``,
  ``min_market_total_stake``) are evaluated against frozen values, not
  live state.
- Predictor exclusion is computed from ``frozen_predictor_ids``
  (UNION ``rotation_descendants`` at resolution time).
- Bootstrap PoW uses ``snapshot_event_hash`` as its salt so attackers
  can't pre-mine before the boundary.

The snapshot itself is **immutable** by spec — the producer emits it
once and never updates it. Sprint 4 enforces immutability by ignoring
any subsequent ``market_snapshot`` events with the same market_id
(``find_snapshot`` returns the FIRST one). Tests assert this invariant.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    p = event.get("payload")
    return p if isinstance(p, dict) else {}


def _events_for_market(market_id: str, chain: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ev in chain:
        if not isinstance(ev, dict):
            continue
        if _payload(ev).get("market_id") == market_id:
            out.append(ev)
    out.sort(key=lambda e: (float(e.get("timestamp") or 0.0), int(e.get("sequence") or 0)))
    return out


def build_snapshot(
    market_id: str,
    chain: Iterable[dict[str, Any]],
    *,
    frozen_at: float,
) -> dict[str, Any]:
    """Compute the snapshot payload deterministically from chain history.

    Walks ``prediction_place`` events for ``market_id``, in chain order,
    and produces the frozen counts / stake totals / predictor list /
    yes-no probability state. The resulting dict is ready to be written
    as the payload of a ``market_snapshot`` event.

    ``frozen_at`` is the canonical commitment timestamp — typically
    ``chain_majority_time(chain)`` at the moment the producer decides
    to advance to EVIDENCE. Pass it explicitly so the function stays
    pure and deterministic.
    """
    events = _events_for_market(market_id, chain)

    predictor_ids: list[str] = []
    seen_predictors: set[str] = set()
    yes_weight = 0.0
    no_weight = 0.0
    total_stake = 0.0

    for ev in events:
        if ev.get("event_type") != "prediction_place":
            continue
        node = ev.get("node_id")
        if not isinstance(node, str) or not node:
            continue
        p = _payload(ev)
        side = p.get("side")
        if side not in ("yes", "no"):
            continue
        if node not in seen_predictors:
            seen_predictors.add(node)
            predictor_ids.append(node)
        stake = p.get("stake_amount")
        if stake is not None:
            try:
                a = float(stake)
            except (TypeError, ValueError):
                a = 0.0
            if a > 0:
                total_stake += a
                if side == "yes":
                    yes_weight += a
                else:
                    no_weight += a
        else:
            # Free pick = 1.0 virtual stake (RULES §5.2).
            if side == "yes":
                yes_weight += 1.0
            else:
                no_weight += 1.0

    pool = yes_weight + no_weight
    if pool > 0:
        yes_p = yes_weight / pool
    else:
        yes_p = 0.5
    no_p = 1.0 - yes_p

    return {
        "market_id": market_id,
        "frozen_participant_count": len(predictor_ids),
        "frozen_total_stake": total_stake,
        "frozen_predictor_ids": predictor_ids,
        "frozen_probability_state": {"yes": yes_p, "no": no_p},
        "frozen_at": float(frozen_at),
    }


def compute_snapshot_event_hash(
    snapshot_payload: dict[str, Any],
    *,
    market_id: str,
    creator_node_id: str,
    sequence: int,
) -> str:
    """Canonical SHA-256 of the snapshot event.

    This hash is what bootstrap PoW uses as its salt (RULES §3.10 step
    0.5) — committing this value on-chain prevents pre-mining of
    bootstrap votes. The serialization is canonical (sorted keys,
    compact separators, UTF-8) so every node arrives at the same hex.

    The producer should append this value to the snapshot payload as
    ``snapshot_event_hash`` before emitting the event.
    """
    canonical = {
        "event_type": "market_snapshot",
        "market_id": market_id,
        "node_id": creator_node_id,
        "sequence": int(sequence),
        "payload": snapshot_payload,
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def find_snapshot(
    market_id: str,
    chain: Iterable[dict[str, Any]],
) -> dict[str, Any] | None:
    """Return the FIRST ``market_snapshot`` payload for ``market_id``.

    Subsequent ``market_snapshot`` events with the same market_id are
    ignored — snapshots are immutable per RULES §2.2. This is a
    structural enforcement, not just a convention; an attacker who
    forges a second snapshot cannot influence resolution.
    """
    events = _events_for_market(market_id, chain)
    for ev in events:
        if ev.get("event_type") == "market_snapshot":
            return _payload(ev)
    return None


__all__ = [
    "build_snapshot",
    "compute_snapshot_event_hash",
    "find_snapshot",
]
