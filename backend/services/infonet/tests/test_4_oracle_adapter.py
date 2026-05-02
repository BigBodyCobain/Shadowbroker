"""Sprint 4 — InfonetOracleAdapter end-to-end smoke."""

from __future__ import annotations

from services.infonet.adapters.oracle_adapter import InfonetOracleAdapter
from services.infonet.markets import MarketStatus
from services.infonet.tests._chain_factory import make_event


def _create(market_id: str, base_ts: float, trigger: float, seq: int = 1) -> dict:
    return make_event(
        "prediction_create", "creator",
        {"market_id": market_id, "market_type": "objective",
         "question": "?", "trigger_date": trigger, "creation_bond": 3},
        timestamp=base_ts, sequence=seq,
    )


def test_adapter_unknown_market_is_predicting():
    a = InfonetOracleAdapter(lambda: [])
    assert a.market_status("nope", now=100.0) == MarketStatus.PREDICTING
    assert a.find_snapshot("nope") is None
    assert a.collect_evidence("nope") == []
    assert a.excluded_predictor_ids("nope") == set()


def test_adapter_take_snapshot_is_pure():
    chain = [
        _create("m1", base_ts=0.0, trigger=200.0),
        make_event("prediction_place", "alice",
                   {"market_id": "m1", "side": "yes", "stake_amount": 10.0,
                    "probability_at_bet": 50.0},
                   timestamp=10.0, sequence=2),
    ]
    a = InfonetOracleAdapter(lambda: chain)
    snap = a.take_snapshot("m1", frozen_at=100.0)
    assert snap["frozen_participant_count"] == 1
    assert snap["frozen_total_stake"] == 10.0
    assert snap["frozen_predictor_ids"] == ["alice"]
    # Calling again returns same answer.
    assert a.take_snapshot("m1", frozen_at=100.0) == snap


def test_adapter_resolve_market_returns_invalid_for_no_evidence():
    chain = [
        _create("m1", base_ts=0.0, trigger=200.0),
        make_event("market_snapshot", "creator",
                   {"market_id": "m1", "frozen_participant_count": 0,
                    "frozen_total_stake": 0.0, "frozen_predictor_ids": [],
                    "frozen_probability_state": {"yes": 0.5, "no": 0.5},
                    "frozen_at": 100.0},
                   timestamp=100.0, sequence=2),
    ]
    a = InfonetOracleAdapter(lambda: chain)
    result = a.resolve_market("m1")
    assert result.outcome == "invalid"
    assert result.reason == "no_evidence"


def test_adapter_callable_chain_provider_invoked_per_call():
    """No caching — each adapter method re-walks the chain."""
    calls = {"n": 0}
    chain: list[dict] = []

    def provider():
        calls["n"] += 1
        return list(chain)

    a = InfonetOracleAdapter(provider)
    a.market_status("m1", now=0.0)
    a.find_snapshot("m1")
    a.collect_evidence("m1")
    assert calls["n"] == 3


def test_adapter_snapshot_event_hash_is_static_helper():
    """Hash helper is a staticmethod — doesn't need a chain provider."""
    h = InfonetOracleAdapter.snapshot_event_hash(
        {"market_id": "m1", "frozen_at": 100.0},
        market_id="m1", creator_node_id="creator", sequence=1,
    )
    assert isinstance(h, str) and len(h) == 64
