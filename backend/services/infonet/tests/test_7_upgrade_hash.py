"""Sprint 7 — upgrade-hash governance.

Maps to RULES §3.15 + §5.6:
- 80% supermajority (vs 67% for param petitions)
- 40% quorum (vs 30%)
- 67% of Heavy Nodes signal ready before activation
"""

from __future__ import annotations

from services.infonet.config import CONFIG
from services.infonet.governance import compute_upgrade_state
from services.infonet.tests._chain_factory import make_event, make_market_chain


_DAY_S = 86400.0
_HOUR_S = 3600.0


def _propose(filer: str, proposal_id: str, *,
             ts: float, seq: int,
             release_hash: str = "abc123",
             target: str = "0.2.0") -> dict:
    return make_event(
        "upgrade_propose", filer,
        {"proposal_id": proposal_id, "release_hash": release_hash,
         "release_description": "feature x",
         "target_protocol_version": target},
        timestamp=ts, sequence=seq,
    )


def _sign(signer: str, proposal_id: str, *, ts: float, seq: int) -> dict:
    return make_event(
        "upgrade_sign", signer,
        {"proposal_id": proposal_id},
        timestamp=ts, sequence=seq,
    )


def _vote(voter: str, proposal_id: str, vote: str, *, ts: float, seq: int) -> dict:
    return make_event(
        "upgrade_vote", voter,
        {"proposal_id": proposal_id, "vote": vote},
        timestamp=ts, sequence=seq,
    )


def _signal_ready(node: str, proposal_id: str, release_hash: str, *,
                  ts: float, seq: int) -> dict:
    return make_event(
        "upgrade_signal_ready", node,
        {"proposal_id": proposal_id, "release_hash": release_hash},
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


def test_unknown_proposal_is_not_found():
    state = compute_upgrade_state("nope", [], now=1.0)
    assert state.status == "not_found"


def test_filed_proposal_in_signatures_phase():
    base = 1_000_000.0
    chain = [_propose("alice", "u1", ts=base, seq=1)]
    state = compute_upgrade_state("u1", chain, now=base + 1)
    assert state.status == "signatures"


def test_failed_signatures_after_window():
    base = 1_000_000.0
    chain = [_propose("alice", "u1", ts=base, seq=1)]
    sig_window = float(CONFIG["upgrade_signature_window_days"]) * _DAY_S
    state = compute_upgrade_state("u1", chain, now=base + sig_window + 1)
    assert state.status == "failed_signatures"


def test_supermajority_higher_than_param_petitions():
    """RULES §5.6: upgrade requires 80% (param petitions: 67%).

    A proposal with 70% support PASSES a param petition but FAILS an
    upgrade. We verify the threshold separation by reading CONFIG."""
    assert float(CONFIG["upgrade_supermajority"]) > float(CONFIG["petition_supermajority"])
    assert float(CONFIG["upgrade_supermajority"]) >= 0.80


def test_quorum_higher_than_param_petitions():
    assert float(CONFIG["upgrade_quorum"]) > float(CONFIG["petition_quorum"])
    assert float(CONFIG["upgrade_quorum"]) >= 0.40


def test_proposal_passes_to_challenge_with_supermajority():
    base = 1_000_000.0
    chain = []
    chain += _seed_oracle("alice", base, "m1", stake=1000.0)
    chain.append(_propose("alice", "u1", ts=base + 100_000, seq=200))
    chain.append(_sign("alice", "u1", ts=base + 100_100, seq=201))
    chain.append(_vote("alice", "u1", "for", ts=base + 100_500, seq=202))
    sig_ts = base + 100_100
    vote_window = float(CONFIG["upgrade_vote_window_days"]) * _DAY_S
    state = compute_upgrade_state("u1", chain, now=sig_ts + vote_window + 1)
    # alice has effectively 100% of the network's oracle rep → 100%
    # vote share, well above 80% threshold + 40% quorum.
    assert state.status == "challenge"


def test_proposal_advances_to_activation_after_challenge_window():
    base = 1_000_000.0
    chain = []
    chain += _seed_oracle("alice", base, "m1", stake=1000.0)
    chain.append(_propose("alice", "u1", ts=base + 100_000, seq=200))
    chain.append(_sign("alice", "u1", ts=base + 100_100, seq=201))
    chain.append(_vote("alice", "u1", "for", ts=base + 100_500, seq=202))

    sig_ts = base + 100_100
    vote_window = float(CONFIG["upgrade_vote_window_days"]) * _DAY_S
    challenge_window = float(CONFIG["upgrade_challenge_window_hours"]) * _HOUR_S
    after = sig_ts + vote_window + challenge_window + 1
    state = compute_upgrade_state("u1", chain, now=after)
    assert state.status == "activation"


def test_activation_threshold_67pct_of_heavy_nodes():
    """At ≥67% Heavy Node readiness, status reports threshold_met=True.

    7 of 10 = 0.70 clearly crosses the 0.67 threshold (6 of 9 = 0.666
    falls short — that boundary is tested separately below).
    """
    base = 1_000_000.0
    chain = []
    chain += _seed_oracle("alice", base, "m1", stake=1000.0)
    chain.append(_propose("alice", "u1", ts=base + 100_000, seq=200,
                          release_hash="rel-x"))
    chain.append(_sign("alice", "u1", ts=base + 100_100, seq=201))
    chain.append(_vote("alice", "u1", "for", ts=base + 100_500, seq=202))

    sig_ts = base + 100_100
    vote_window = float(CONFIG["upgrade_vote_window_days"]) * _DAY_S
    challenge_window = float(CONFIG["upgrade_challenge_window_hours"]) * _HOUR_S
    activation_start = sig_ts + vote_window + challenge_window + 1
    # 10 Heavy Nodes total, 7 signal ready → 70%.
    heavy_set = {f"h{i}" for i in range(10)}
    for i, h in enumerate(sorted(heavy_set)[:7]):
        chain.append(_signal_ready(h, "u1", "rel-x",
                                   ts=activation_start + i, seq=300 + i))

    state = compute_upgrade_state("u1", chain, now=activation_start + 100,
                                  heavy_node_ids=heavy_set)
    assert state.readiness.total_heavy_nodes == 10
    assert state.readiness.ready_count == 7
    assert state.readiness.threshold_met is True


def test_activation_at_2_3_falls_short_of_67pct():
    """6/9 = 0.6666 < 0.67 — boundary check confirms the threshold is
    a strict ≥ (not floating-point loose)."""
    base = 1_000_000.0
    chain = []
    chain += _seed_oracle("alice", base, "m1", stake=1000.0)
    chain.append(_propose("alice", "u1", ts=base + 100_000, seq=200,
                          release_hash="rel-x"))
    chain.append(_sign("alice", "u1", ts=base + 100_100, seq=201))
    chain.append(_vote("alice", "u1", "for", ts=base + 100_500, seq=202))

    sig_ts = base + 100_100
    vote_window = float(CONFIG["upgrade_vote_window_days"]) * _DAY_S
    challenge_window = float(CONFIG["upgrade_challenge_window_hours"]) * _HOUR_S
    activation_start = sig_ts + vote_window + challenge_window + 1
    heavy_set = {f"h{i}" for i in range(9)}
    for i, h in enumerate(sorted(heavy_set)[:6]):
        chain.append(_signal_ready(h, "u1", "rel-x",
                                   ts=activation_start + i, seq=300 + i))

    state = compute_upgrade_state("u1", chain, now=activation_start + 100,
                                  heavy_node_ids=heavy_set)
    # 6/9 = 0.6666... is strictly less than 0.67.
    assert not state.readiness.threshold_met


def test_activation_below_67pct_does_not_meet_threshold():
    base = 1_000_000.0
    chain = []
    chain += _seed_oracle("alice", base, "m1", stake=1000.0)
    chain.append(_propose("alice", "u1", ts=base + 100_000, seq=200,
                          release_hash="rel-x"))
    chain.append(_sign("alice", "u1", ts=base + 100_100, seq=201))
    chain.append(_vote("alice", "u1", "for", ts=base + 100_500, seq=202))

    sig_ts = base + 100_100
    vote_window = float(CONFIG["upgrade_vote_window_days"]) * _DAY_S
    challenge_window = float(CONFIG["upgrade_challenge_window_hours"]) * _HOUR_S
    activation_start = sig_ts + vote_window + challenge_window + 1
    heavy_set = {f"h{i}" for i in range(10)}
    # Only 6 of 10 = 60% (below 67%).
    for i, h in enumerate(sorted(heavy_set)[:6]):
        chain.append(_signal_ready(h, "u1", "rel-x",
                                   ts=activation_start + i, seq=300 + i))
    state = compute_upgrade_state("u1", chain, now=activation_start + 100,
                                  heavy_node_ids=heavy_set)
    assert state.readiness.threshold_met is False


def test_signal_ready_with_wrong_release_hash_ignored():
    """An attacker can't speed up activation by signaling readiness for
    a different release."""
    base = 1_000_000.0
    chain = []
    chain += _seed_oracle("alice", base, "m1", stake=1000.0)
    chain.append(_propose("alice", "u1", ts=base + 100_000, seq=200,
                          release_hash="rel-x"))
    chain.append(_sign("alice", "u1", ts=base + 100_100, seq=201))
    chain.append(_vote("alice", "u1", "for", ts=base + 100_500, seq=202))

    sig_ts = base + 100_100
    vote_window = float(CONFIG["upgrade_vote_window_days"]) * _DAY_S
    challenge_window = float(CONFIG["upgrade_challenge_window_hours"]) * _HOUR_S
    activation_start = sig_ts + vote_window + challenge_window + 1
    heavy_set = {f"h{i}" for i in range(3)}
    # All 3 heavies signal ready, but for a DIFFERENT release_hash.
    for i, h in enumerate(sorted(heavy_set)):
        chain.append(_signal_ready(h, "u1", "rel-FORGED",
                                   ts=activation_start + i, seq=300 + i))
    state = compute_upgrade_state("u1", chain, now=activation_start + 100,
                                  heavy_node_ids=heavy_set)
    assert state.readiness.ready_count == 0
    assert not state.readiness.threshold_met


def test_signal_ready_from_non_heavy_node_ignored():
    base = 1_000_000.0
    chain = []
    chain += _seed_oracle("alice", base, "m1", stake=1000.0)
    chain.append(_propose("alice", "u1", ts=base + 100_000, seq=200,
                          release_hash="rel-x"))
    chain.append(_sign("alice", "u1", ts=base + 100_100, seq=201))
    chain.append(_vote("alice", "u1", "for", ts=base + 100_500, seq=202))

    sig_ts = base + 100_100
    vote_window = float(CONFIG["upgrade_vote_window_days"]) * _DAY_S
    challenge_window = float(CONFIG["upgrade_challenge_window_hours"]) * _HOUR_S
    activation_start = sig_ts + vote_window + challenge_window + 1
    heavy_set = {"h1", "h2"}
    # "imposter" is NOT in heavy_set — readiness signal should be ignored.
    chain.append(_signal_ready("imposter", "u1", "rel-x",
                               ts=activation_start + 1, seq=300))
    state = compute_upgrade_state("u1", chain, now=activation_start + 100,
                                  heavy_node_ids=heavy_set)
    assert state.readiness.ready_count == 0


def test_failed_activation_after_window_expires():
    base = 1_000_000.0
    chain = []
    chain += _seed_oracle("alice", base, "m1", stake=1000.0)
    chain.append(_propose("alice", "u1", ts=base + 100_000, seq=200,
                          release_hash="rel-x"))
    chain.append(_sign("alice", "u1", ts=base + 100_100, seq=201))
    chain.append(_vote("alice", "u1", "for", ts=base + 100_500, seq=202))

    sig_ts = base + 100_100
    vote_window = float(CONFIG["upgrade_vote_window_days"]) * _DAY_S
    challenge_window = float(CONFIG["upgrade_challenge_window_hours"]) * _HOUR_S
    activation_window = float(CONFIG["upgrade_activation_window_days"]) * _DAY_S
    after = sig_ts + vote_window + challenge_window + activation_window + 1
    state = compute_upgrade_state("u1", chain, now=after,
                                  heavy_node_ids={"h1", "h2"})
    assert state.status == "failed_activation"
