"""Regression coverage for non-finite gate lock contributions."""

from services.infonet.config import CONFIG
from services.infonet.gates import is_locked, validate_lock_request
from services.infonet.tests._gate_factory import (
    make_gate_create,
    make_gate_enter,
    make_gate_lock,
)


def _gate_with_members() -> tuple[list[dict], list[str]]:
    base = 1_000_000.0
    threshold = int(CONFIG["gate_lock_min_members"])
    members = [f"m{i}" for i in range(threshold)]
    chain = [make_gate_create("g1", "creator", ts=base, seq=1)]
    for i, member in enumerate(members):
        chain.append(make_gate_enter("g1", member, ts=base + 100 + i, seq=2 + i))
    return chain, members


def _append_valid_locks(chain: list[dict], members: list[str]) -> None:
    cost = int(CONFIG["gate_lock_cost_per_member"])
    for i, member in enumerate(members):
        chain.append(
            make_gate_lock(
                "g1",
                member,
                ts=1_001_000.0 + i,
                seq=200 + i,
                lock_cost=cost,
            )
        )


def test_infinite_lock_cost_does_not_count_toward_threshold():
    chain, members = _gate_with_members()
    _append_valid_locks(chain, members[:-1])
    bad = make_gate_lock("g1", members[-1], ts=1_002_000.0, seq=999)
    bad["payload"]["lock_cost"] = float("inf")
    chain.append(bad)

    assert not is_locked("g1", chain)


def test_nonfinite_lock_timestamp_does_not_count_toward_threshold():
    chain, members = _gate_with_members()
    _append_valid_locks(chain, members[:-1])
    bad = make_gate_lock("g1", members[-1], ts=float("nan"), seq=999)
    chain.append(bad)

    assert not is_locked("g1", chain)


def test_validate_lock_request_rejects_nonfinite_cost():
    chain, members = _gate_with_members()

    decision = validate_lock_request(
        members[0],
        "g1",
        chain,
        lock_cost=float("inf"),  # type: ignore[arg-type]
    )

    assert not decision.accepted
    assert decision.reason == "invalid_lock_cost"
