"""Regression coverage for malformed and non-finite dispute numerics."""

from services.infonet.markets.dispute import collect_disputes


def test_collect_disputes_normalizes_invalid_numeric_values():
    chain = [
        {
            "event_type": "dispute_open",
            "event_id": "dispute-1",
            "node_id": "challenger",
            "timestamp": "not-a-timestamp",
            "payload": {
                "market_id": "market-1",
                "challenger_stake": "nan",
            },
        },
        {
            "event_type": "dispute_stake",
            "node_id": "oracle-1",
            "timestamp": 1.0,
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
                "outcome": "upheld",
            },
        },
    ]

    disputes = collect_disputes("market-1", chain)

    assert len(disputes) == 1
    dispute = disputes[0]
    assert dispute.challenger_stake == 0.0
    assert dispute.opened_at == 0.0
    assert dispute.confirm_stakes == []
    assert dispute.resolved_outcome == "upheld"
    assert dispute.resolved_at == 0.0


def test_collect_disputes_preserves_finite_numeric_strings():
    chain = [
        {
            "event_type": "dispute_open",
            "event_id": "dispute-2",
            "node_id": "challenger",
            "timestamp": "12.5",
            "payload": {
                "market_id": "market-2",
                "challenger_stake": "3.5",
            },
        },
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
    ]

    dispute = collect_disputes("market-2", chain)[0]

    assert dispute.challenger_stake == 3.5
    assert dispute.opened_at == 12.5
    assert dispute.reverse_stakes[0]["amount"] == 2.25
