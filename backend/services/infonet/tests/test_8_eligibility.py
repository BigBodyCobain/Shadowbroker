"""Sprint 8 — bootstrap eligibility (identity age + predictor exclusion).

Maps to IMPLEMENTATION_PLAN §7.1 Sprint 8 row:
"Identity age measured against `frozen_at`, not `now`."
"""

from __future__ import annotations

from services.infonet.bootstrap import (
    is_identity_age_eligible,
    validate_bootstrap_eligibility,
)
from services.infonet.config import CONFIG
from services.infonet.tests._chain_factory import make_event


_DAY_S = 86400.0


def _node_register(node_id: str, *, ts: float, seq: int) -> dict:
    return make_event(
        "node_register", node_id,
        {"public_key": f"pk-{node_id}", "public_key_algo": "ed25519",
         "node_class": "heavy"},
        timestamp=ts, sequence=seq,
    )


def _market_create(market_id: str, *, base_ts: float, bootstrap_index: int = 1) -> dict:
    return make_event(
        "prediction_create", "creator",
        {"market_id": market_id, "market_type": "objective",
         "question": "?", "trigger_date": base_ts + 100, "creation_bond": 3,
         "bootstrap_index": bootstrap_index},
        timestamp=base_ts, sequence=1,
    )


def _market_snapshot(market_id: str, *, frozen_at: float,
                     predictors: list[str] | None = None) -> dict:
    p = predictors or []
    return make_event(
        "market_snapshot", "creator",
        {"market_id": market_id, "frozen_participant_count": len(p),
         "frozen_total_stake": 0.0, "frozen_predictor_ids": list(p),
         "frozen_probability_state": {"yes": 0.5, "no": 0.5},
         "frozen_at": frozen_at},
        timestamp=frozen_at, sequence=2,
    )


def test_node_registered_long_before_frozen_at_is_eligible():
    min_age = float(CONFIG["bootstrap_min_identity_age_days"])
    chain = [
        _node_register("alice", ts=0.0, seq=1),
        _market_create("m1", base_ts=10 * _DAY_S),
        _market_snapshot("m1", frozen_at=(min_age + 5) * _DAY_S),
    ]
    assert is_identity_age_eligible("alice", "m1", chain)


def test_node_registered_too_recently_not_eligible():
    """Registered at frozen_at — 1 day. Min age 3 days. Fails."""
    chain = [
        _node_register("alice", ts=10 * _DAY_S, seq=1),
        _market_create("m1", base_ts=11 * _DAY_S),
        _market_snapshot("m1", frozen_at=11 * _DAY_S),
    ]
    assert not is_identity_age_eligible("alice", "m1", chain)


def test_eligibility_uses_frozen_at_not_now():
    """An attacker who waits to submit *after* identity age threshold
    elapses cannot retroactively become eligible — eligibility is
    measured against the snapshot's frozen_at, which is fixed."""
    min_age = float(CONFIG["bootstrap_min_identity_age_days"])
    # alice registered 1 day before frozen_at — too young.
    frozen_at = 100 * _DAY_S
    chain = [
        _node_register("alice", ts=frozen_at - 1 * _DAY_S, seq=1),
        _market_create("m1", base_ts=frozen_at - 1),
        _market_snapshot("m1", frozen_at=frozen_at),
    ]
    # Even if "now" is far in the future (where alice would technically
    # be old enough by today's clock), eligibility doesn't change.
    assert not is_identity_age_eligible("alice", "m1", chain)
    # Sanity check: if the snapshot were created later (later frozen_at),
    # alice WOULD be eligible. This proves the test isn't vacuously true.
    later_chain = [
        _node_register("alice", ts=frozen_at - 1 * _DAY_S, seq=1),
        _market_create("m1", base_ts=frozen_at + (min_age + 1) * _DAY_S - 1),
        _market_snapshot("m1", frozen_at=frozen_at + (min_age + 1) * _DAY_S),
    ]
    assert is_identity_age_eligible("alice", "m1", later_chain)


def test_eligibility_falls_back_to_earliest_event_without_register():
    """Spec says identity age is from node.created_at = first chain
    appearance. If no node_register event exists, fall back to the
    node's earliest event."""
    min_age = float(CONFIG["bootstrap_min_identity_age_days"])
    chain = [
        # alice's earliest chain event is a prediction_place at ts=0.
        make_event("prediction_place", "alice",
                   {"market_id": "m_old", "side": "yes", "probability_at_bet": 50.0},
                   timestamp=0.0, sequence=1),
        _market_create("m1", base_ts=10 * _DAY_S),
        _market_snapshot("m1", frozen_at=(min_age + 5) * _DAY_S),
    ]
    assert is_identity_age_eligible("alice", "m1", chain)


def test_validate_bootstrap_eligibility_rejects_predictor():
    """A node listed in frozen_predictor_ids cannot resolve their own
    market via bootstrap voting."""
    min_age = float(CONFIG["bootstrap_min_identity_age_days"])
    chain = [
        _node_register("alice", ts=0.0, seq=1),
        _market_create("m1", base_ts=10 * _DAY_S),
        _market_snapshot("m1", frozen_at=(min_age + 5) * _DAY_S,
                         predictors=["alice"]),
    ]
    decision = validate_bootstrap_eligibility("alice", "m1", chain)
    assert not decision.eligible
    assert decision.reason == "predictor_excluded"


def test_validate_bootstrap_eligibility_rejects_rotated_predictor():
    """rotation_descendants is included in the exclusion set per spec."""
    min_age = float(CONFIG["bootstrap_min_identity_age_days"])
    chain = [
        _node_register("alice", ts=0.0, seq=1),
        _node_register("alice2", ts=1.0, seq=2),
        _market_create("m1", base_ts=10 * _DAY_S),
        _market_snapshot("m1", frozen_at=(min_age + 5) * _DAY_S,
                         predictors=["alice"]),
        # alice rotates to alice2 AFTER snapshot.
        make_event("identity_rotate", "alice2",
                   {"old_node_id": "alice", "old_public_key": "pk",
                    "old_public_key_algo": "ed25519",
                    "new_public_key": "pk2", "new_public_key_algo": "ed25519",
                    "old_signature": "sig"},
                   timestamp=11 * _DAY_S, sequence=99),
    ]
    decision = validate_bootstrap_eligibility("alice2", "m1", chain)
    assert not decision.eligible
    assert decision.reason == "predictor_excluded"


def test_validate_bootstrap_eligibility_rejects_when_snapshot_missing():
    chain = [_node_register("alice", ts=0.0, seq=1)]
    decision = validate_bootstrap_eligibility("alice", "m1", chain)
    assert not decision.eligible
    assert decision.reason == "snapshot_missing"


def test_validate_bootstrap_eligibility_accepts_valid_node():
    min_age = float(CONFIG["bootstrap_min_identity_age_days"])
    chain = [
        _node_register("alice", ts=0.0, seq=1),
        _market_create("m1", base_ts=10 * _DAY_S),
        _market_snapshot("m1", frozen_at=(min_age + 5) * _DAY_S, predictors=[]),
    ]
    decision = validate_bootstrap_eligibility("alice", "m1", chain)
    assert decision.eligible
    assert decision.reason == "ok"
