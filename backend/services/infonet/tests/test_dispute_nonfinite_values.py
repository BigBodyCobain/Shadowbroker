"""Regression coverage for malformed and non-finite dispute numerics."""

from services.infonet.markets.dispute import collect_disputes


def _open_event(
    *, dispute_id: str, market_id: str, timestamp: object, challenger_stake: object
) -> dict:
    return {
        "event_type": "dispute_open",
        "event_id": dispute_id,
        "node_id": "challenger",
        "timestamp": timestamp,
        "payload": {
            "market_id": market_id,
            "challenger_stake": challenger_stake,
        },
    }


def test_malformed_authoritative_open_events_are_excluded() -> None:
    chain = [
        _open_event(
            dispute_id="bad-time",
            market_id="market-1",
            timestamp="not-a-timestamp",
            challenger_stake=3.0,
        ),
        _open_event(
            dispute_id="bad-stake",
            market_id="market-1",
            timestamp=10.0,
            challenger_stake=float("nan"),
        ),
    ]

    assert collect_disputes("market-1", chain) == []


def test_invalid_economic_and_resolution_values_fail_closed() -> None:
    chain = [
        _open_event(
            dispute_id="dispute-1",
            market_id="market-1",
            timestamp=10.0,
            challenger_stake=3.0,
        ),
        {
            "event_type": "dispute_stake",
            "node_id": "oracle-1",
            "timestamp": 11.0,
            "payload": {
                "dispute_id": "dispute-1",
                "side": "confirm",
                "rep_type": "oracle",
                "amount": float("nan"),
            },
        },
        {
            "event_type": "dispute_resolve",
            "timestamp": float("inf"),
            "payload": {
                "dispute_id": "dispute-1",
                "outcome": "reversed",
            },
        },
    ]

    dispute = collect_disputes("market-1", chain)[0]

    assert dispute.confirm_stakes == []
    assert dispute.resolved_outcome is None
    assert dispute.resolved_at is None


def test_collect_disputes_preserves_finite_numeric_strings() -> None:
    chain = [
        _open_event(
            dispute_id="dispute-2",
            market_id="market-2",
            timestamp="12.5",
            challenger_stake="3.5",
        ),
        {
            "event_type": "dispute_stake",
            "node_id": "oracle-2",
            "payload": {
                "dispute_id": "dispute-2",
                "side": "reverse",
                "rep_type": "oracle",
                "amount": "2.25",
            },
        },
        {
            "event_type": "dispute_resolve",
            "timestamp": "13.5",
            "payload": {
                "dispute_id": "dispute-2",
                "outcome": "reversed",
            },
        },
    ]

    dispute = collect_disputes("market-2", chain)[0]

    assert dispute.challenger_stake == 3.5
    assert dispute.opened_at == 12.5
    assert dispute.reverse_stakes[0]["amount"] == 2.25
    assert dispute.resolved_outcome == "reversed"
    assert dispute.resolved_at == 13.5
