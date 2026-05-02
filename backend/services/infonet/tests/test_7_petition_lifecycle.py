"""Sprint 7 — petition state machine + constitutional challenge.

Maps to IMPLEMENTATION_PLAN §7.1 Sprint 7 row:
"Constitutional challenge can void passed petition."
"""

from __future__ import annotations

from services.infonet.config import CONFIG
from services.infonet.governance import (
    compute_challenge_state,
    compute_petition_state,
)
from services.infonet.tests._chain_factory import make_event, make_market_chain


_DAY_S = 86400.0
_HOUR_S = 3600.0


def _file_petition(filer: str, petition_id: str, *, ts: float, seq: int,
                   payload: dict | None = None) -> dict:
    return make_event(
        "petition_file", filer,
        {"petition_id": petition_id,
         "petition_payload": payload or {
             "type": "UPDATE_PARAM",
             "key": "vote_decay_days",
             "value": 60,
         }},
        timestamp=ts, sequence=seq,
    )


def _sign(signer: str, petition_id: str, *, ts: float, seq: int) -> dict:
    return make_event(
        "petition_sign", signer,
        {"petition_id": petition_id},
        timestamp=ts, sequence=seq,
    )


def _vote(voter: str, petition_id: str, vote: str, *, ts: float, seq: int) -> dict:
    return make_event(
        "petition_vote", voter,
        {"petition_id": petition_id, "vote": vote},
        timestamp=ts, sequence=seq,
    )


def _challenge_file(filer: str, petition_id: str, *, ts: float, seq: int) -> dict:
    return make_event(
        "challenge_file", filer,
        {"petition_id": petition_id, "reason": "constitutional violation"},
        timestamp=ts, sequence=seq,
    )


def _challenge_vote(voter: str, petition_id: str, vote: str, *,
                    ts: float, seq: int) -> dict:
    return make_event(
        "challenge_vote", voter,
        {"petition_id": petition_id, "vote": vote},
        timestamp=ts, sequence=seq,
    )


def _seed_oracle(node_id: str, base_ts: float, market_id: str,
                 stake: float = 100.0) -> list[dict]:
    return make_market_chain(
        market_id, "creator", outcome="yes",
        predictions=[
            {"node_id": node_id, "side": "yes", "stake_amount": stake},
            {"node_id": f"{node_id}-loser", "side": "no", "stake_amount": stake},
        ],
        base_ts=base_ts, participants=5, total_stake=stake * 2,
    )


def test_unknown_petition_is_not_found():
    state = compute_petition_state("nope", [], now=1.0)
    assert state.status == "not_found"


def test_just_filed_is_in_signatures_phase():
    base = 1_000_000.0
    chain = [_file_petition("alice", "p1", ts=base, seq=1)]
    state = compute_petition_state("p1", chain, now=base + 1)
    assert state.status == "signatures"


def test_signatures_below_threshold_failed_after_window():
    base = 1_000_000.0
    chain = [_file_petition("alice", "p1", ts=base, seq=1)]
    sig_window = float(CONFIG["petition_signature_window_days"]) * _DAY_S
    state = compute_petition_state("p1", chain, now=base + sig_window + 1)
    assert state.status == "failed_signatures"


def test_petition_advances_to_voting_when_signatures_meet_threshold():
    """Build enough oracle rep into a single signer that 25% threshold
    is satisfied."""
    base = 1_000_000.0
    chain = []
    chain += _seed_oracle("alice", base, "m1", stake=500.0)
    chain.append(_file_petition("alice", "p1", ts=base + 100_000, seq=200))
    chain.append(_sign("alice", "p1", ts=base + 100_100, seq=201))
    state = compute_petition_state("p1", chain, now=base + 100_500)
    # alice has nearly all the network's oracle rep → her single
    # signature satisfies the 25% threshold.
    assert state.status == "voting"


def test_petition_fails_vote_when_quorum_not_met():
    base = 1_000_000.0
    chain = []
    chain += _seed_oracle("alice", base, "m1", stake=500.0)
    chain.append(_file_petition("alice", "p1", ts=base + 100_000, seq=200))
    chain.append(_sign("alice", "p1", ts=base + 100_100, seq=201))
    # No votes cast.
    sig_ts = base + 100_100
    vote_window = float(CONFIG["petition_vote_window_days"]) * _DAY_S
    after = sig_ts + vote_window + 1
    state = compute_petition_state("p1", chain, now=after)
    assert state.status == "failed_vote"


def test_petition_passes_vote_with_supermajority_and_quorum():
    base = 1_000_000.0
    chain = []
    chain += _seed_oracle("alice", base, "m1", stake=500.0)
    chain.append(_file_petition("alice", "p1", ts=base + 100_000, seq=200))
    chain.append(_sign("alice", "p1", ts=base + 100_100, seq=201))
    chain.append(_vote("alice", "p1", "for", ts=base + 100_500, seq=202))
    sig_ts = base + 100_100
    vote_window = float(CONFIG["petition_vote_window_days"]) * _DAY_S
    after = sig_ts + vote_window + 1
    state = compute_petition_state("p1", chain, now=after)
    # Vote passed → enters challenge phase.
    assert state.status == "challenge"


def test_constitutional_challenge_can_void_passed_petition():
    """The Sprint 7 marquee adversarial test."""
    base = 1_000_000.0
    chain = []
    chain += _seed_oracle("alice", base, "m1", stake=500.0)
    chain += _seed_oracle("bob", base + 50_000, "m2", stake=10.0)
    chain.append(_file_petition("alice", "p1", ts=base + 100_000, seq=200))
    chain.append(_sign("alice", "p1", ts=base + 100_100, seq=201))
    chain.append(_vote("alice", "p1", "for", ts=base + 100_500, seq=202))

    sig_ts = base + 100_100
    vote_window = float(CONFIG["petition_vote_window_days"]) * _DAY_S
    challenge_filed_at = sig_ts + vote_window + 60.0
    chain.append(_challenge_file("bob", "p1", ts=challenge_filed_at, seq=300))
    # alice (high oracle rep) votes UPHOLD the challenge.
    chain.append(_challenge_vote("alice", "p1", "uphold",
                                 ts=challenge_filed_at + 60, seq=301))

    challenge_window = float(CONFIG["challenge_window_hours"]) * _HOUR_S
    after = challenge_filed_at + challenge_window + 1
    cstate = compute_challenge_state("p1", chain, now=after)
    assert cstate.outcome == "voided"
    pstate = compute_petition_state("p1", chain, now=after)
    assert pstate.status == "voided_challenge"


def test_unupheld_challenge_does_not_void_petition():
    base = 1_000_000.0
    chain = []
    chain += _seed_oracle("alice", base, "m1", stake=500.0)
    chain += _seed_oracle("bob", base + 50_000, "m2", stake=10.0)
    chain.append(_file_petition("alice", "p1", ts=base + 100_000, seq=200))
    chain.append(_sign("alice", "p1", ts=base + 100_100, seq=201))
    chain.append(_vote("alice", "p1", "for", ts=base + 100_500, seq=202))

    sig_ts = base + 100_100
    vote_window = float(CONFIG["petition_vote_window_days"]) * _DAY_S
    challenge_filed_at = sig_ts + vote_window + 60.0
    chain.append(_challenge_file("bob", "p1", ts=challenge_filed_at, seq=300))
    # alice (high oracle rep) votes VOID the challenge → petition stands.
    chain.append(_challenge_vote("alice", "p1", "void",
                                 ts=challenge_filed_at + 60, seq=301))

    challenge_window = float(CONFIG["challenge_window_hours"]) * _HOUR_S
    after = challenge_filed_at + challenge_window + 1
    pstate = compute_petition_state("p1", chain, now=after)
    assert pstate.status == "passed"


def test_petition_executed_after_petition_execute_event():
    base = 1_000_000.0
    chain = []
    chain += _seed_oracle("alice", base, "m1", stake=500.0)
    chain.append(_file_petition("alice", "p1", ts=base + 100_000, seq=200))
    chain.append(_sign("alice", "p1", ts=base + 100_100, seq=201))
    chain.append(_vote("alice", "p1", "for", ts=base + 100_500, seq=202))

    sig_ts = base + 100_100
    vote_window = float(CONFIG["petition_vote_window_days"]) * _DAY_S
    challenge_window = float(CONFIG["challenge_window_hours"]) * _HOUR_S
    execute_at = sig_ts + vote_window + challenge_window + 100.0
    chain.append(make_event(
        "petition_execute", "alice",
        {"petition_id": "p1"},
        timestamp=execute_at, sequence=400,
    ))
    state = compute_petition_state("p1", chain, now=execute_at + 1)
    assert state.status == "executed"
