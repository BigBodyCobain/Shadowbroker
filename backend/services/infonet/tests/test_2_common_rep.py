"""Sprint 2 — common rep base formula (Sprint 3 layers anti-gaming).

The formula in Sprint 2 is just ``base_rep = oracle_rep(upreper) *
weight_factor``. VCS / clustering / temporal multipliers ship in Sprint 3.
"""

from __future__ import annotations

from services.infonet.reputation import compute_common_rep
from services.infonet.tests._chain_factory import make_event, make_market_chain


def test_no_uprep_means_no_common_rep():
    chain = make_market_chain(
        "m1", "creator", outcome="yes",
        predictions=[{"node_id": "alice", "side": "yes", "probability_at_bet": 30.0}],
    )
    assert compute_common_rep("alice", chain) == 0.0


def test_uprep_from_zero_oracle_rep_yields_zero_common_rep():
    """Plan §3.2: rep is oracle-weighted. A node with no oracle rep
    cannot mint common rep through upreps."""
    chain = [
        make_event("uprep", "newbie", {"target_node_id": "alice", "target_event_id": "post1"},
                   timestamp=1.0, sequence=1),
    ]
    assert compute_common_rep("alice", chain) == 0.0


def test_uprep_from_oracle_holder_mints_common_rep():
    base = 1_000_000.0
    chain = make_market_chain(
        "m1", "creator", outcome="yes",
        predictions=[
            {"node_id": "ora", "side": "yes", "stake_amount": 10.0},
            {"node_id": "loser", "side": "no", "stake_amount": 10.0},
        ],
        base_ts=base,
        participants=5, total_stake=20.0,
    )
    chain.append(make_event(
        "uprep", "ora", {"target_node_id": "alice", "target_event_id": "post1"},
        timestamp=base + 10_000, sequence=99,
    ))
    # ora has 20 oracle rep, weight factor 0.1 → 2.0 common rep for alice.
    assert compute_common_rep("alice", chain) == 2.0


def test_self_uprep_is_ignored():
    base = 1_000_000.0
    chain = make_market_chain(
        "m1", "creator", outcome="yes",
        predictions=[
            {"node_id": "alice", "side": "yes", "stake_amount": 10.0},
            {"node_id": "loser", "side": "no", "stake_amount": 10.0},
        ],
        base_ts=base,
        participants=5, total_stake=20.0,
    )
    chain.append(make_event(
        "uprep", "alice", {"target_node_id": "alice", "target_event_id": "post1"},
        timestamp=base + 10_000, sequence=99,
    ))
    # Self-uprep silently ignored.
    assert compute_common_rep("alice", chain) == 0.0


def test_multiple_upreps_accumulate():
    base = 1_000_000.0
    chain = make_market_chain(
        "m1", "creator", outcome="yes",
        predictions=[
            {"node_id": "ora", "side": "yes", "stake_amount": 10.0},
            {"node_id": "loser", "side": "no", "stake_amount": 10.0},
        ],
        base_ts=base,
        participants=5, total_stake=20.0,
    )
    for i in range(3):
        chain.append(make_event(
            "uprep", "ora",
            {"target_node_id": "alice", "target_event_id": f"post{i}"},
            timestamp=base + 10_000 + i, sequence=100 + i,
        ))
    # 3 upreps × 20 oracle rep × 0.1 = 6.0
    assert compute_common_rep("alice", chain) == 6.0


def test_weight_factor_override():
    base = 1_000_000.0
    chain = make_market_chain(
        "m1", "creator", outcome="yes",
        predictions=[
            {"node_id": "ora", "side": "yes", "stake_amount": 10.0},
            {"node_id": "loser", "side": "no", "stake_amount": 10.0},
        ],
        base_ts=base,
        participants=5, total_stake=20.0,
    )
    chain.append(make_event(
        "uprep", "ora", {"target_node_id": "alice", "target_event_id": "post1"},
        timestamp=base + 10_000, sequence=99,
    ))
    assert compute_common_rep("alice", chain, weight_factor=0.5) == 10.0
