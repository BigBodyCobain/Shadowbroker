"""Sprint 6 — gate ratification (cumulative oracle rep ≥ 50)."""

from __future__ import annotations

from services.infonet.config import CONFIG
from services.infonet.gates import cumulative_member_oracle_rep, is_ratified
from services.infonet.tests._chain_factory import make_market_chain
from services.infonet.tests._gate_factory import make_gate_create, make_gate_enter


def test_unknown_gate_not_ratified():
    assert not is_ratified("nope", [])
    assert cumulative_member_oracle_rep("nope", []) == 0.0


def test_gate_with_no_members_not_ratified():
    base = 1_000_000.0
    chain = [make_gate_create("g1", "creator", ts=base, seq=1)]
    assert not is_ratified("g1", chain)


def test_gate_ratifies_when_cumulative_oracle_rep_crosses_threshold():
    """Two members with combined oracle rep >= ratification threshold."""
    threshold = float(CONFIG["gate_ratification_rep"])
    base = 1_000_000.0
    chain = []

    # Earn alice and bob enough oracle rep.
    chain += make_market_chain(
        "m1", "creator", outcome="yes",
        predictions=[
            {"node_id": "alice", "side": "yes", "stake_amount": threshold / 2 + 5},
            {"node_id": "loser", "side": "no", "stake_amount": threshold / 2 + 5},
        ],
        base_ts=base, participants=5, total_stake=threshold + 10,
    )
    chain += make_market_chain(
        "m2", "creator", outcome="yes",
        predictions=[
            {"node_id": "bob", "side": "yes", "stake_amount": threshold / 2 + 5},
            {"node_id": "loser2", "side": "no", "stake_amount": threshold / 2 + 5},
        ],
        base_ts=base + 100_000, participants=5, total_stake=threshold + 10,
    )
    chain.append(make_gate_create("g1", "creator", ts=base + 200_000, seq=200))
    chain.append(make_gate_enter("g1", "alice", ts=base + 201_000, seq=201))
    chain.append(make_gate_enter("g1", "bob", ts=base + 202_000, seq=202))
    cumulative = cumulative_member_oracle_rep("g1", chain)
    assert cumulative >= threshold
    assert is_ratified("g1", chain)


def test_gate_below_threshold_not_ratified():
    """One member with low oracle rep — below threshold."""
    base = 1_000_000.0
    chain = []
    # alice earns a small amount of oracle rep.
    chain += make_market_chain(
        "m1", "creator", outcome="yes",
        predictions=[
            {"node_id": "alice", "side": "yes", "stake_amount": 5.0},
            {"node_id": "loser", "side": "no", "stake_amount": 5.0},
        ],
        base_ts=base, participants=5, total_stake=10.0,
    )
    chain.append(make_gate_create("g1", "creator", ts=base + 100_000, seq=200))
    chain.append(make_gate_enter("g1", "alice", ts=base + 101_000, seq=201))
    cumulative = cumulative_member_oracle_rep("g1", chain)
    threshold = float(CONFIG["gate_ratification_rep"])
    assert cumulative < threshold
    assert not is_ratified("g1", chain)
