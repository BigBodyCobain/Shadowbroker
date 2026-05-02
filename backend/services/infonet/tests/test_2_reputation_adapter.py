"""Sprint 2 — InfonetReputationAdapter end-to-end coverage.

The adapter is the integration boundary every later sprint will extend.
Sprint 2 wires it to the pure functions in ``services/infonet/reputation/``.
"""

from __future__ import annotations

from services.infonet.adapters.reputation_adapter import InfonetReputationAdapter
from services.infonet.tests._chain_factory import make_event, make_market_chain


def test_adapter_zero_rep_for_unknown_node():
    a = InfonetReputationAdapter(lambda: [])
    assert a.oracle_rep("nobody") == 0.0
    assert a.common_rep("nobody") == 0.0
    assert a.oracle_rep_lifetime("nobody") == 0.0


def test_adapter_oracle_rep_breakdown_components():
    base = 1_000_000.0
    chain = make_market_chain(
        "m1", "creator", outcome="yes",
        predictions=[
            {"node_id": "alice", "side": "yes", "stake_amount": 10.0},
            {"node_id": "bob",   "side": "no",  "stake_amount": 10.0},
        ],
        base_ts=base,
        participants=5, total_stake=20.0,
    )
    a = InfonetReputationAdapter(lambda: chain)
    bd = a.oracle_rep_breakdown("alice")
    assert bd.staked_prediction_returns == 20.0
    assert bd.staked_prediction_losses == 0.0
    assert bd.total == 20.0


def test_adapter_uses_chain_majority_time_for_decay():
    base = 1_000_000.0
    chain = make_market_chain(
        "m1", "creator", outcome="yes",
        predictions=[{"node_id": "alice", "side": "yes", "probability_at_bet": 30.0}],
        base_ts=base,
        participants=5, total_stake=10.0,
    )
    # Add many recent events from distinct nodes to drive chain_majority_time
    # well beyond the decay window.
    later = base + 86400.0 * 200  # 200 days past finalize
    for i in range(11):
        chain.append(make_event(
            "uprep", f"chatter{i}",
            {"target_node_id": "alice", "target_event_id": f"e{i}"},
            timestamp=later + i, sequence=1,
        ))
    a = InfonetReputationAdapter(lambda: chain)
    base_balance = a.oracle_rep("alice")
    active = a.oracle_rep_active("alice")
    # Within 0–90 days: full weight. After 90: factor 0.5. After 180: 0.25.
    # 200 days → 2 periods → 0.25.
    assert active < base_balance


def test_adapter_decay_factor_helper_exposes_zero_for_unknown_node():
    a = InfonetReputationAdapter(lambda: [])
    assert a.decay_factor("nobody") == 0.0


def test_adapter_last_successful_prediction_ts():
    base = 1_000_000.0
    chain = make_market_chain(
        "m1", "creator", outcome="yes",
        predictions=[{"node_id": "alice", "side": "yes", "probability_at_bet": 30.0}],
        base_ts=base,
        participants=5, total_stake=10.0,
    )
    a = InfonetReputationAdapter(lambda: chain)
    ts = a.last_successful_prediction_ts("alice")
    assert ts is not None and ts >= base


def test_adapter_callable_chain_provider_is_invoked_per_call():
    """Adapter must NOT cache the chain — fresh evaluation each call so
    new events show up. Caching at the adapter is a Sprint 3+ concern."""
    snapshot_calls = {"n": 0}
    chain: list[dict] = []

    def provider():
        snapshot_calls["n"] += 1
        return list(chain)

    a = InfonetReputationAdapter(provider)
    a.oracle_rep("x")
    a.common_rep("x")
    a.oracle_rep_lifetime("x")
    assert snapshot_calls["n"] == 3
