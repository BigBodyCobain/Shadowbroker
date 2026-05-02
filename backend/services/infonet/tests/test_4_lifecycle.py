"""Sprint 4 — market lifecycle state machine.

Maps to RULES §5.2 + IMPLEMENTATION_PLAN §7.1 Sprint 4 row covering
state-machine correctness.
"""

from __future__ import annotations

from services.infonet.config import CONFIG
from services.infonet.markets import (
    MarketStatus,
    compute_market_status,
    should_advance_phase,
)
from services.infonet.tests._chain_factory import make_event


_EVIDENCE_S = float(CONFIG["evidence_window_hours"]) * 3600.0
_RESOLUTION_S = float(CONFIG["resolution_window_hours"]) * 3600.0


def _create(market_id: str, base_ts: float, trigger_date: float, seq: int = 1) -> dict:
    return make_event(
        "prediction_create", "creator",
        {"market_id": market_id, "market_type": "objective",
         "question": "?", "trigger_date": trigger_date, "creation_bond": 3},
        timestamp=base_ts, sequence=seq,
    )


def _snapshot(market_id: str, frozen_at: float, seq: int = 2) -> dict:
    return make_event(
        "market_snapshot", "creator",
        {"market_id": market_id, "frozen_participant_count": 5,
         "frozen_total_stake": 10.0, "frozen_predictor_ids": ["p1", "p2"],
         "frozen_probability_state": {"yes": 0.5, "no": 0.5},
         "frozen_at": frozen_at},
        timestamp=frozen_at, sequence=seq,
    )


def _finalize(market_id: str, ts: float, outcome: str, seq: int = 99) -> dict:
    return make_event(
        "resolution_finalize", "creator",
        {"market_id": market_id, "outcome": outcome,
         "is_provisional": False, "snapshot_event_hash": "h"},
        timestamp=ts, sequence=seq,
    )


def test_unknown_market_is_predicting():
    assert compute_market_status("nope", [], now=1.0) == MarketStatus.PREDICTING


def test_just_created_market_is_predicting():
    chain = [_create("m1", base_ts=100.0, trigger_date=200.0)]
    assert compute_market_status("m1", chain, now=150.0) == MarketStatus.PREDICTING


def test_after_snapshot_within_window_is_evidence():
    base = 100.0
    chain = [
        _create("m1", base_ts=base, trigger_date=200.0),
        _snapshot("m1", frozen_at=200.0),
    ]
    # 1 hour into evidence window.
    assert compute_market_status("m1", chain, now=200.0 + 3600) == MarketStatus.EVIDENCE


def test_after_evidence_window_is_resolving():
    chain = [
        _create("m1", base_ts=100.0, trigger_date=200.0),
        _snapshot("m1", frozen_at=200.0),
    ]
    now = 200.0 + _EVIDENCE_S + 1.0
    assert compute_market_status("m1", chain, now=now) == MarketStatus.RESOLVING


def test_finalize_yes_is_final():
    chain = [
        _create("m1", base_ts=100.0, trigger_date=200.0),
        _snapshot("m1", frozen_at=200.0),
        _finalize("m1", ts=300.0, outcome="yes"),
    ]
    assert compute_market_status("m1", chain, now=400.0) == MarketStatus.FINAL


def test_finalize_invalid_is_invalid():
    chain = [
        _create("m1", base_ts=100.0, trigger_date=200.0),
        _snapshot("m1", frozen_at=200.0),
        _finalize("m1", ts=300.0, outcome="invalid"),
    ]
    assert compute_market_status("m1", chain, now=400.0) == MarketStatus.INVALID


def test_should_advance_predicting_to_evidence_at_trigger_date():
    chain = [_create("m1", base_ts=100.0, trigger_date=200.0)]
    assert should_advance_phase("m1", chain, now=199.99) is None
    assert should_advance_phase("m1", chain, now=200.0) == (
        MarketStatus.PREDICTING, MarketStatus.EVIDENCE,
    )


def test_should_advance_evidence_to_resolving_at_window_close():
    chain = [
        _create("m1", base_ts=100.0, trigger_date=200.0),
        _snapshot("m1", frozen_at=200.0),
    ]
    inside = 200.0 + _EVIDENCE_S - 1.0
    boundary = 200.0 + _EVIDENCE_S
    assert should_advance_phase("m1", chain, now=inside) is None
    assert should_advance_phase("m1", chain, now=boundary) == (
        MarketStatus.EVIDENCE, MarketStatus.RESOLVING,
    )


def test_should_advance_resolving_to_final_at_window_close():
    chain = [
        _create("m1", base_ts=100.0, trigger_date=200.0),
        _snapshot("m1", frozen_at=200.0),
    ]
    boundary = 200.0 + _EVIDENCE_S + _RESOLUTION_S
    assert should_advance_phase("m1", chain, now=boundary) == (
        MarketStatus.RESOLVING, MarketStatus.FINAL,
    )


def test_terminal_market_does_not_advance():
    chain = [
        _create("m1", base_ts=100.0, trigger_date=200.0),
        _snapshot("m1", frozen_at=200.0),
        _finalize("m1", ts=300.0, outcome="yes"),
    ]
    assert should_advance_phase("m1", chain, now=10_000_000.0) is None
