"""Test-only helpers for synthesizing chain events.

Mirrors the dict shape that ``InfonetHashchainAdapter.dry_run_append``
emits, which in turn mirrors the legacy ``mesh_hashchain.Infonet.append``
output. Tests call these helpers to build synthetic chains; production
code is unaffected.
"""

from __future__ import annotations

from typing import Any


def make_event(
    event_type: str,
    node_id: str,
    payload: dict[str, Any],
    *,
    timestamp: float,
    sequence: int = 1,
) -> dict[str, Any]:
    return {
        "event_type": event_type,
        "node_id": node_id,
        "timestamp": float(timestamp),
        "sequence": int(sequence),
        "payload": dict(payload),
    }


def make_market_chain(
    market_id: str,
    creator_id: str,
    *,
    market_type: str = "objective",
    bootstrap_index: int | None = None,
    base_ts: float = 1_700_000_000.0,
    participants: int = 5,
    total_stake: float = 10.0,
    outcome: str | None = "yes",
    is_provisional: bool = False,
    predictions: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build a coherent set of events for one market.

    Returns events in chain order: prediction_create → prediction_place
    (per ``predictions``) → market_snapshot → resolution_finalize (if
    ``outcome`` is not None). Use this to set up "did the mint rule
    fire correctly" tests.
    """
    chain: list[dict[str, Any]] = []
    seq = 0

    def _next_seq() -> int:
        nonlocal seq
        seq += 1
        return seq

    chain.append(make_event(
        "prediction_create",
        creator_id,
        {
            "market_id": market_id,
            "market_type": market_type,
            "question": f"Q for {market_id}",
            "trigger_date": base_ts + 86400.0,
            "creation_bond": 3,
            **({"bootstrap_index": bootstrap_index} if bootstrap_index is not None else {}),
        },
        timestamp=base_ts,
        sequence=_next_seq(),
    ))

    predictor_ids: list[str] = []
    for i, pred in enumerate(predictions or []):
        chain.append(make_event(
            "prediction_place",
            pred["node_id"],
            {
                "market_id": market_id,
                "side": pred["side"],
                "probability_at_bet": pred.get("probability_at_bet", 50.0),
                **({"stake_amount": pred["stake_amount"]} if pred.get("stake_amount") is not None else {}),
            },
            timestamp=base_ts + 60.0 + i,
            sequence=_next_seq(),
        ))
        predictor_ids.append(pred["node_id"])

    snapshot_ts = base_ts + 3600.0
    chain.append(make_event(
        "market_snapshot",
        creator_id,
        {
            "market_id": market_id,
            "frozen_participant_count": participants,
            "frozen_total_stake": float(total_stake),
            "frozen_predictor_ids": list(dict.fromkeys(predictor_ids)),
            "frozen_probability_state": {"yes": 0.5, "no": 0.5},
            "frozen_at": snapshot_ts,
        },
        timestamp=snapshot_ts,
        sequence=_next_seq(),
    ))

    if outcome is not None:
        finalize_ts = base_ts + 7200.0
        chain.append(make_event(
            "resolution_finalize",
            creator_id,
            {
                "market_id": market_id,
                "outcome": outcome,
                "is_provisional": bool(is_provisional),
                "snapshot_event_hash": f"snap-{market_id}",
            },
            timestamp=finalize_ts,
            sequence=_next_seq(),
        ))

    return chain
