"""Test-only chain-builder helpers for gate scenarios."""

from __future__ import annotations

from typing import Any

from services.infonet.tests._chain_factory import make_event


def make_gate_create(
    gate_id: str,
    creator: str,
    *,
    ts: float,
    seq: int = 1,
    entry_sacrifice: int = 5,
    min_overall_rep: int = 0,
    min_gate_rep: dict[str, int] | None = None,
    display_name: str | None = None,
) -> dict[str, Any]:
    rules: dict[str, Any] = {
        "entry_sacrifice": entry_sacrifice,
        "min_overall_rep": min_overall_rep,
    }
    if min_gate_rep:
        rules["min_gate_rep"] = dict(min_gate_rep)
    return make_event(
        "gate_create", creator,
        {"gate_id": gate_id, "display_name": display_name or gate_id, "rules": rules},
        timestamp=ts, sequence=seq,
    )


def make_gate_enter(gate_id: str, node: str, *, ts: float, seq: int,
                    sacrifice: int = 5) -> dict[str, Any]:
    return make_event(
        "gate_enter", node,
        {"gate_id": gate_id, "sacrifice_amount": sacrifice},
        timestamp=ts, sequence=seq,
    )


def make_gate_exit(gate_id: str, node: str, *, ts: float, seq: int) -> dict[str, Any]:
    return make_event(
        "gate_exit", node,
        {"gate_id": gate_id},
        timestamp=ts, sequence=seq,
    )


def make_gate_lock(gate_id: str, node: str, *, ts: float, seq: int,
                   lock_cost: int = 10) -> dict[str, Any]:
    return make_event(
        "gate_lock", node,
        {"gate_id": gate_id, "lock_cost": lock_cost},
        timestamp=ts, sequence=seq,
    )


def make_suspend_file(gate_id: str, filer: str, petition_id: str, *,
                      ts: float, seq: int,
                      reason: str = "abuse",
                      evidence: list[str] | None = None) -> dict[str, Any]:
    return make_event(
        "gate_suspend_file", filer,
        {"petition_id": petition_id, "gate_id": gate_id,
         "reason": reason, "evidence_hashes": list(evidence or ["ev1"])},
        timestamp=ts, sequence=seq,
    )


def make_suspend_execute(gate_id: str, petition_id: str, *,
                         ts: float, seq: int,
                         executor: str = "creator") -> dict[str, Any]:
    return make_event(
        "gate_suspend_execute", executor,
        {"petition_id": petition_id, "gate_id": gate_id},
        timestamp=ts, sequence=seq,
    )


def make_unsuspend(gate_id: str, *, ts: float, seq: int,
                   executor: str = "creator") -> dict[str, Any]:
    return make_event(
        "gate_unsuspend", executor,
        {"gate_id": gate_id},
        timestamp=ts, sequence=seq,
    )


def make_shutdown_file(gate_id: str, filer: str, petition_id: str, *,
                       ts: float, seq: int,
                       reason: str = "still abusing",
                       evidence: list[str] | None = None) -> dict[str, Any]:
    return make_event(
        "gate_shutdown_file", filer,
        {"petition_id": petition_id, "gate_id": gate_id,
         "reason": reason, "evidence_hashes": list(evidence or ["ev1"])},
        timestamp=ts, sequence=seq,
    )


def make_shutdown_vote(gate_id: str, petition_id: str, vote: str, *,
                       ts: float, seq: int,
                       voter: str = "creator") -> dict[str, Any]:
    return make_event(
        "gate_shutdown_vote", voter,
        {"petition_id": petition_id, "vote": vote, "gate_id": gate_id},
        timestamp=ts, sequence=seq,
    )


def make_shutdown_execute(gate_id: str, petition_id: str, *,
                          ts: float, seq: int,
                          executor: str = "creator") -> dict[str, Any]:
    return make_event(
        "gate_shutdown_execute", executor,
        {"petition_id": petition_id, "gate_id": gate_id},
        timestamp=ts, sequence=seq,
    )


def make_appeal_file(gate_id: str, target_petition_id: str, filer: str,
                     petition_id: str, *,
                     ts: float, seq: int,
                     reason: str = "appeal",
                     evidence: list[str] | None = None) -> dict[str, Any]:
    return make_event(
        "gate_shutdown_appeal_file", filer,
        {"petition_id": petition_id, "gate_id": gate_id,
         "target_petition_id": target_petition_id,
         "reason": reason,
         "evidence_hashes": list(evidence or ["ev1"])},
        timestamp=ts, sequence=seq,
    )


def make_appeal_resolve(gate_id: str, petition_id: str, target_petition_id: str,
                        outcome: str, *, ts: float, seq: int,
                        resumed_execution_at: float | None = None,
                        resolver: str = "creator") -> dict[str, Any]:
    payload = {"petition_id": petition_id, "outcome": outcome,
               "target_petition_id": target_petition_id, "gate_id": gate_id}
    if resumed_execution_at is not None:
        payload["resumed_execution_at"] = resumed_execution_at
    return make_event("gate_shutdown_appeal_resolve", resolver, payload,
                      timestamp=ts, sequence=seq)
