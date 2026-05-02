"""Sprint 5 — bounded-reversal disputes.

Maps to IMPLEMENTATION_PLAN §7.1 Sprint 5 row:
"Bounded reversal does not cascade."
"""

from __future__ import annotations

from services.infonet.markets import (
    DisputeView,
    collect_disputes,
    compute_dispute_outcome,
    dispute_settlement_effects,
    effective_outcome,
    market_was_reversed,
)
from services.infonet.reputation import (
    compute_oracle_rep,
    last_successful_prediction_ts,
)
from services.infonet.tests._chain_factory import make_event, make_market_chain


def _open(market_id: str, challenger: str, stake: float, *, ts: float, seq: int,
          dispute_id: str | None = None) -> dict:
    payload = {"market_id": market_id, "challenger_stake": stake, "reason": "wrong"}
    if dispute_id is not None:
        payload["dispute_id"] = dispute_id
    return make_event("dispute_open", challenger, payload, timestamp=ts, sequence=seq)


def _stake(dispute_id: str, node_id: str, side: str, amount: float,
           *, ts: float, seq: int, rep_type: str = "oracle") -> dict:
    return make_event(
        "dispute_stake", node_id,
        {"dispute_id": dispute_id, "side": side, "amount": amount, "rep_type": rep_type},
        timestamp=ts, sequence=seq,
    )


def _resolve(dispute_id: str, outcome: str, *, ts: float, seq: int) -> dict:
    return make_event(
        "dispute_resolve", "creator",
        {"dispute_id": dispute_id, "outcome": outcome},
        timestamp=ts, sequence=seq,
    )


# ── Dispute view ────────────────────────────────────────────────────────

def test_collect_disputes_pulls_open_stake_resolve():
    chain = [
        _open("m1", "alice", 5.0, ts=100, seq=1, dispute_id="d1"),
        _stake("d1", "bob", "confirm", 10.0, ts=110, seq=2),
        _stake("d1", "carol", "reverse", 5.0, ts=111, seq=3),
        _resolve("d1", "upheld", ts=200, seq=4),
    ]
    disputes = collect_disputes("m1", chain)
    assert len(disputes) == 1
    d = disputes[0]
    assert d.dispute_id == "d1"
    assert d.challenger_id == "alice"
    assert d.challenger_stake == 5.0
    assert len(d.confirm_stakes) == 1
    assert len(d.reverse_stakes) == 1
    assert d.is_resolved
    assert d.resolved_outcome == "upheld"


def test_compute_dispute_outcome_majority_oracle():
    d = DisputeView(
        dispute_id="d1", market_id="m1", challenger_id="x",
        challenger_stake=0.0, opened_at=0.0,
        confirm_stakes=[{"node_id": "a", "amount": 10.0, "rep_type": "oracle"}],
        reverse_stakes=[{"node_id": "b", "amount": 5.0, "rep_type": "oracle"}],
    )
    assert compute_dispute_outcome(d) == "upheld"


def test_compute_dispute_outcome_reverses_when_majority_reverse():
    d = DisputeView(
        dispute_id="d1", market_id="m1", challenger_id="x",
        challenger_stake=0.0, opened_at=0.0,
        confirm_stakes=[{"node_id": "a", "amount": 5.0, "rep_type": "oracle"}],
        reverse_stakes=[{"node_id": "b", "amount": 10.0, "rep_type": "oracle"}],
    )
    assert compute_dispute_outcome(d) == "reversed"


def test_compute_dispute_outcome_tie_returns_tie():
    d = DisputeView(
        dispute_id="d1", market_id="m1", challenger_id="x",
        challenger_stake=0.0, opened_at=0.0,
        confirm_stakes=[{"node_id": "a", "amount": 10.0, "rep_type": "oracle"}],
        reverse_stakes=[{"node_id": "b", "amount": 10.0, "rep_type": "oracle"}],
    )
    assert compute_dispute_outcome(d) == "tie"


def test_dispute_outcome_uses_oracle_only():
    """Common rep stakes participate but don't decide the outcome."""
    d = DisputeView(
        dispute_id="d1", market_id="m1", challenger_id="x",
        challenger_stake=0.0, opened_at=0.0,
        confirm_stakes=[{"node_id": "a", "amount": 5.0, "rep_type": "oracle"}],
        reverse_stakes=[
            {"node_id": "b", "amount": 100.0, "rep_type": "common"},
            {"node_id": "c", "amount": 1.0, "rep_type": "oracle"},
        ],
    )
    # oracle: confirm 5 vs reverse 1 → upheld.
    assert compute_dispute_outcome(d) == "upheld"


# ── Bounded reversal flips effective outcome ─────────────────────────────

def test_effective_outcome_unmodified_if_no_dispute():
    assert effective_outcome("yes", "m1", []) == "yes"


def test_effective_outcome_unmodified_if_dispute_upheld():
    chain = [
        _open("m1", "alice", 5.0, ts=100, seq=1, dispute_id="d1"),
        _resolve("d1", "upheld", ts=200, seq=2),
    ]
    assert effective_outcome("yes", "m1", chain) == "yes"


def test_effective_outcome_flips_if_dispute_reversed():
    chain = [
        _open("m1", "alice", 5.0, ts=100, seq=1, dispute_id="d1"),
        _resolve("d1", "reversed", ts=200, seq=2),
    ]
    assert effective_outcome("yes", "m1", chain) == "no"
    assert effective_outcome("no", "m1", chain) == "yes"


def test_market_was_reversed_returns_true_after_reverse():
    chain = [
        _open("m1", "alice", 5.0, ts=100, seq=1, dispute_id="d1"),
        _resolve("d1", "reversed", ts=200, seq=2),
    ]
    assert market_was_reversed("m1", chain)


def test_unresolved_dispute_does_not_flip_outcome():
    """A dispute with stakes but no dispute_resolve event hasn't
    reversed anything yet."""
    chain = [
        _open("m1", "alice", 5.0, ts=100, seq=1, dispute_id="d1"),
        _stake("d1", "bob", "reverse", 10.0, ts=110, seq=2),
        # No dispute_resolve event yet.
    ]
    assert effective_outcome("yes", "m1", chain) == "yes"
    assert not market_was_reversed("m1", chain)


# ── Bounded: reversal of one market doesn't cascade to others ────────────

def test_reversal_in_market_a_does_not_affect_market_b_mint():
    """Bounded reversal: m1's outcome flip recalculates ONLY m1's
    oracle rep; m2's separate outcome is untouched.

    Concretely: alice has +20 from m1 (won) and +20 from m2 (won) →
    40 before. After m1 reverses (effective outcome flips to no),
    alice's m1 stake (yes) is now a losing stake → forfeited (-10).
    m2 untouched. Net = -10 + 20 = 10.

    The "bounded" part: even though m1 is reversed, m2's resolution
    is NOT recomputed. If cascading were enabled, oracle rep that
    *originated* in m1 might be clawed back from m2 stakes too.
    Bounded reversal blocks that. Tests assert m2's contribution
    stays +20 across the reversal.
    """
    base = 1_000_000.0
    chain = []
    chain += make_market_chain(
        "m1", "creator", outcome="yes",
        predictions=[{"node_id": "alice", "side": "yes", "stake_amount": 10.0},
                     {"node_id": "loser1", "side": "no", "stake_amount": 10.0}],
        base_ts=base, participants=5, total_stake=20.0,
    )
    chain += make_market_chain(
        "m2", "creator", outcome="no",
        predictions=[{"node_id": "alice", "side": "no", "stake_amount": 10.0},
                     {"node_id": "loser2", "side": "yes", "stake_amount": 10.0}],
        base_ts=base + 100_000, participants=5, total_stake=20.0,
    )
    assert compute_oracle_rep("alice", chain) == 40.0

    # m1 is disputed and reversed. m2 untouched.
    chain.append(_open("m1", "challenger", 5.0, ts=base + 200_000, seq=900,
                       dispute_id="d1"))
    chain.append(_stake("d1", "majority", "reverse", 100.0,
                        ts=base + 200_500, seq=901))
    chain.append(_resolve("d1", "reversed", ts=base + 201_000, seq=902))

    # m1 contribution: alice (yes) is now on the losing side after
    #   the flip → -10 forfeited.
    # m2 contribution: untouched (outcome stays "no", alice picked
    #   "no") → +20.
    # Net: 10. The non-cascade property: m2's +20 is NOT reduced.
    rep = compute_oracle_rep("alice", chain)
    assert rep == 10.0
    # The non-cascade invariant: loser2 (m2 loser) is unaffected by
    # m1's reversal. They lost 10 in m2; m1's reversal does not
    # restore that.
    assert compute_oracle_rep("loser2", chain) == 0  # net negative, clamped to 0


def test_reversal_recalculates_only_affected_market_for_timestamp():
    """If alice's most recent winning prediction was in the reversed
    market, last_successful_prediction_ts falls back to the older,
    still-valid market (RULES §3.12 requirement)."""
    base = 1_000_000.0
    chain = []
    chain += make_market_chain(
        "m_old", "creator", outcome="yes",
        predictions=[{"node_id": "alice", "side": "yes", "probability_at_bet": 30.0}],
        base_ts=base, participants=5, total_stake=10.0,
    )
    chain += make_market_chain(
        "m_recent", "creator", outcome="yes",
        predictions=[{"node_id": "alice", "side": "yes", "probability_at_bet": 30.0}],
        base_ts=base + 1_000_000, participants=5, total_stake=10.0,
    )
    # Before reversal: most recent ts is from m_recent.
    before_ts = last_successful_prediction_ts("alice", chain)
    assert before_ts is not None and before_ts >= base + 1_000_000

    # m_recent is reversed.
    chain.append(_open("m_recent", "challenger", 5.0,
                       ts=base + 2_000_000, seq=900, dispute_id="d1"))
    chain.append(_resolve("d1", "reversed", ts=base + 2_001_000, seq=901))

    # After reversal: alice's m_recent prediction (yes) is now on the
    # LOSING side (effective outcome flipped to no). Her last
    # qualifying ts must fall back to m_old.
    after_ts = last_successful_prediction_ts("alice", chain)
    assert after_ts is not None
    assert after_ts < base + 1_000_000  # not from m_recent


def test_reversed_market_predictor_on_new_winning_side_now_qualifies():
    """If alice predicted "no" on m1 and the reversal flipped the
    outcome to no, alice now correctly predicted — she gets rep."""
    base = 1_000_000.0
    chain = []
    chain += make_market_chain(
        "m1", "creator", outcome="yes",
        predictions=[
            {"node_id": "alice", "side": "no", "probability_at_bet": 50.0},
            {"node_id": "bob", "side": "yes", "stake_amount": 10.0,
             "probability_at_bet": 50.0},
            {"node_id": "loser", "side": "no", "stake_amount": 10.0,
             "probability_at_bet": 50.0},
        ],
        base_ts=base, participants=5, total_stake=20.0,
    )
    # Before reversal: alice picked no, market said yes → alice mints 0.
    assert compute_oracle_rep("alice", chain) == 0

    chain.append(_open("m1", "challenger", 5.0,
                       ts=base + 100_000, seq=900, dispute_id="d1"))
    chain.append(_stake("d1", "majority", "reverse", 100.0,
                        ts=base + 100_500, seq=901))
    chain.append(_resolve("d1", "reversed", ts=base + 101_000, seq=902))

    # After reversal: effective outcome is no. alice picked no → free
    # mint applies (alice's prediction had no stake_amount in factory →
    # default factory uses stake_amount=None? let me check)
    # The factory only adds stake_amount if "stake_amount" key in pred dict.
    # Above, alice has no stake_amount — free pick.
    rep = compute_oracle_rep("alice", chain)
    # Free mint at p=50 on the now-winning side: max(0.01, 1 - 50/100) = 0.5
    assert rep == 0.5


# ── Settlement effects ──────────────────────────────────────────────────

def test_dispute_settlement_upheld_distributes_winnings_to_confirmers():
    d = DisputeView(
        dispute_id="d1", market_id="m1", challenger_id="x",
        challenger_stake=0.0, opened_at=0.0,
        confirm_stakes=[{"node_id": "a", "amount": 10.0, "rep_type": "oracle"}],
        reverse_stakes=[{"node_id": "b", "amount": 10.0, "rep_type": "oracle"}],
        resolved_outcome="upheld", resolved_at=1.0,
    )
    eff = dispute_settlement_effects(d)
    # winner pool = 10, loser pool = 10. 2% burn = 0.2. Distributable = 9.8.
    # a: returns 10, winnings 9.8.
    assert eff["stake_returns"][("a", "oracle")] == 10.0
    assert abs(eff["stake_winnings"][("a", "oracle")] - 9.8) < 1e-9
    assert abs(eff["burned"] - 0.2) < 1e-9
    # b loses entirely.
    assert ("b", "oracle") not in eff["stake_returns"]


def test_dispute_settlement_tie_returns_all_stakes():
    d = DisputeView(
        dispute_id="d1", market_id="m1", challenger_id="x",
        challenger_stake=0.0, opened_at=0.0,
        confirm_stakes=[{"node_id": "a", "amount": 10.0, "rep_type": "oracle"}],
        reverse_stakes=[{"node_id": "b", "amount": 10.0, "rep_type": "oracle"}],
        resolved_outcome="tie", resolved_at=1.0,
    )
    eff = dispute_settlement_effects(d)
    assert eff["stake_returns"][("a", "oracle")] == 10.0
    assert eff["stake_returns"][("b", "oracle")] == 10.0
    assert not eff["stake_winnings"]
    assert eff["burned"] == 0.0


def test_dispute_settlement_unresolved_returns_empty():
    d = DisputeView(
        dispute_id="d1", market_id="m1", challenger_id="x",
        challenger_stake=0.0, opened_at=0.0,
    )
    eff = dispute_settlement_effects(d)
    assert not eff["stake_returns"]
    assert not eff["stake_winnings"]
    assert eff["burned"] == 0.0
