"""Sprint 3 — weekly vote budget (RULES §3.7)."""

from __future__ import annotations

import math

from services.infonet.config import CONFIG
from services.infonet.reputation import (
    compute_weekly_vote_budget,
    count_upreps_in_last_week,
    is_budget_exceeded,
)
from services.infonet.tests._chain_factory import make_event, make_market_chain


def _uprep(author: str, target: str, ts: float, seq: int) -> dict:
    return make_event(
        "uprep", author,
        {"target_node_id": target, "target_event_id": f"e-{seq}"},
        timestamp=ts, sequence=seq,
    )


def test_zero_oracle_rep_means_base_budget():
    base = int(CONFIG["weekly_vote_base"])
    assert compute_weekly_vote_budget("nobody", []) == base


def test_budget_grows_with_oracle_rep():
    base_ts = 1_000_000.0
    chain = make_market_chain(
        "m1", "creator", outcome="yes",
        predictions=[
            {"node_id": "alice", "side": "yes", "stake_amount": 100.0,
             "probability_at_bet": 50.0},
            {"node_id": "loser", "side": "no", "stake_amount": 100.0,
             "probability_at_bet": 50.0},
        ],
        base_ts=base_ts, participants=5, total_stake=200.0,
    )
    # alice oracle rep = 200 (stake 100 + 100 winnings).
    # budget = base + floor(200 / per_oracle).
    base = int(CONFIG["weekly_vote_base"])
    per_oracle = int(CONFIG["weekly_vote_per_oracle"])
    expected = base + math.floor(200.0 / per_oracle)
    assert compute_weekly_vote_budget("alice", chain) == expected


def test_count_in_last_week_within_window():
    now = 2_000_000.0
    chain = [
        _uprep("alice", "x", ts=now - 3600, seq=1),
        _uprep("alice", "y", ts=now - 86400 * 3, seq=2),
        _uprep("alice", "z", ts=now - 86400 * 5, seq=3),
    ]
    assert count_upreps_in_last_week("alice", chain, now=now) == 3


def test_count_in_last_week_excludes_old_events():
    now = 2_000_000.0
    chain = [
        _uprep("alice", "x", ts=now - 3600, seq=1),
        # 8 days old — outside the week
        _uprep("alice", "y", ts=now - 8 * 86400, seq=2),
    ]
    assert count_upreps_in_last_week("alice", chain, now=now) == 1


def test_count_in_last_week_excludes_other_authors():
    now = 2_000_000.0
    chain = [
        _uprep("alice", "x", ts=now - 3600, seq=1),
        _uprep("bob", "x", ts=now - 3600, seq=2),
    ]
    assert count_upreps_in_last_week("alice", chain, now=now) == 1


def test_is_budget_exceeded_within_budget_returns_false():
    base = int(CONFIG["weekly_vote_base"])
    now = 2_000_000.0
    chain = [_uprep("alice", f"t{i}", ts=now - i * 100, seq=i + 1) for i in range(base)]
    assert not is_budget_exceeded("alice", chain, now=now)


def test_is_budget_exceeded_over_budget_returns_true():
    base = int(CONFIG["weekly_vote_base"])
    now = 2_000_000.0
    chain = [
        _uprep("alice", f"t{i}", ts=now - i * 100, seq=i + 1)
        for i in range(base + 1)
    ]
    assert is_budget_exceeded("alice", chain, now=now)
