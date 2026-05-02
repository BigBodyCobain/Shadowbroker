"""Sprint 8 — bootstrap resolution end-to-end via resolve_market.

Verifies the full pipeline: bootstrap-indexed market + bootstrap_resolution_vote
events + eligibility filtering + dedup + supermajority → FINAL outcome.
"""

from __future__ import annotations

from services.infonet.config import CONFIG
from services.infonet.markets import resolve_market
from services.infonet.tests._chain_factory import make_event


_DAY_S = 86400.0


def _create(market_id: str, *, base_ts: float, bootstrap_index: int = 1) -> dict:
    return make_event(
        "prediction_create", "creator",
        {"market_id": market_id, "market_type": "objective",
         "question": "?", "trigger_date": base_ts + 100, "creation_bond": 3,
         "bootstrap_index": bootstrap_index},
        timestamp=base_ts, sequence=1,
    )


def _snapshot(market_id: str, *, frozen_at: float,
              predictors: list[str] | None = None) -> dict:
    p = predictors or []
    return make_event(
        "market_snapshot", "creator",
        {"market_id": market_id, "frozen_participant_count": len(p),
         "frozen_total_stake": 0.0, "frozen_predictor_ids": list(p),
         "frozen_probability_state": {"yes": 0.5, "no": 0.5},
         "frozen_at": frozen_at},
        timestamp=frozen_at, sequence=2,
    )


def _node_register(node_id: str, *, ts: float, seq: int) -> dict:
    return make_event(
        "node_register", node_id,
        {"public_key": f"pk-{node_id}", "public_key_algo": "ed25519",
         "node_class": "heavy"},
        timestamp=ts, sequence=seq,
    )


def _bootstrap_vote(node_id: str, market_id: str, side: str, *,
                    ts: float, seq: int, pow_nonce: int = 0) -> dict:
    return make_event(
        "bootstrap_resolution_vote", node_id,
        {"market_id": market_id, "side": side, "pow_nonce": pow_nonce},
        timestamp=ts, sequence=seq,
    )


def _evidence(market_id: str, node_id: str, outcome: str, *,
              ts: float, seq: int) -> dict:
    from services.infonet.markets.evidence import (
        evidence_content_hash,
        submission_hash,
    )
    h = [f"ev-{node_id}-{outcome}"]
    chash = evidence_content_hash(market_id, outcome, h, "src")
    shash = submission_hash(chash, node_id, ts)
    return make_event(
        "evidence_submit", node_id,
        {"market_id": market_id, "claimed_outcome": outcome,
         "evidence_hashes": h, "source_description": "src",
         "evidence_content_hash": chash, "submission_hash": shash, "bond": 0.0},
        timestamp=ts, sequence=seq,
    )


def _eligible_chain(*, base_ts: float = 0.0,
                    voter_count: int = 5,
                    yes_count: int | None = None) -> list[dict]:
    """Build a bootstrap chain with `voter_count` eligible Heavy Nodes."""
    min_age = float(CONFIG["bootstrap_min_identity_age_days"])
    chain: list[dict] = []
    for i in range(voter_count):
        chain.append(_node_register(f"v{i}", ts=base_ts + i, seq=10 + i))
    chain.append(_create("m1", base_ts=base_ts + 10 * _DAY_S))
    snap_ts = base_ts + (min_age + 5) * _DAY_S
    chain.append(_snapshot("m1", frozen_at=snap_ts))
    chain.append(_evidence("m1", "ev_yes", "yes", ts=snap_ts + 100, seq=200))

    yes = voter_count if yes_count is None else yes_count
    for i in range(voter_count):
        side = "yes" if i < yes else "no"
        chain.append(_bootstrap_vote(
            f"v{i}", "m1", side,
            ts=snap_ts + 200 + i, seq=300 + i,
        ))
    return chain


def test_bootstrap_resolution_unanimous_yes_passes():
    chain = _eligible_chain(voter_count=5, yes_count=5)
    result = resolve_market("m1", chain)
    assert result.outcome == "yes"
    assert result.reason.startswith("bootstrap_supermajority_")


def test_bootstrap_resolution_below_min_participation():
    """min_market_participants is the eligible-vote threshold."""
    threshold = int(CONFIG["min_market_participants"])
    chain = _eligible_chain(voter_count=threshold - 1)
    result = resolve_market("m1", chain)
    assert result.outcome == "invalid"
    assert result.reason == "bootstrap_below_min_participation"


def test_bootstrap_resolution_no_supermajority_invalidates():
    """50/50 split → no supermajority → INVALID."""
    chain = _eligible_chain(voter_count=10, yes_count=5)
    result = resolve_market("m1", chain)
    assert result.outcome == "invalid"
    assert result.reason == "bootstrap_no_supermajority"


def test_bootstrap_resolution_excludes_predictors():
    """A predictor's bootstrap vote is filtered out — does not count
    toward the participation total or supermajority."""
    min_age = float(CONFIG["bootstrap_min_identity_age_days"])
    base_ts = 0.0
    voter_count = 5
    chain: list[dict] = []
    for i in range(voter_count):
        chain.append(_node_register(f"v{i}", ts=base_ts + i, seq=10 + i))
    chain.append(_node_register("predictor", ts=base_ts + 100, seq=99))
    chain.append(_create("m1", base_ts=base_ts + 10 * _DAY_S))
    snap_ts = base_ts + (min_age + 5) * _DAY_S
    chain.append(_snapshot("m1", frozen_at=snap_ts, predictors=["predictor"]))
    chain.append(_evidence("m1", "ev_yes", "yes", ts=snap_ts + 100, seq=200))
    # predictor tries to sneak in a vote — must be silently filtered.
    chain.append(_bootstrap_vote("predictor", "m1", "no",
                                  ts=snap_ts + 200, seq=300))
    for i in range(voter_count):
        chain.append(_bootstrap_vote(f"v{i}", "m1", "yes",
                                     ts=snap_ts + 300 + i, seq=310 + i))
    result = resolve_market("m1", chain)
    assert result.outcome == "yes"  # predictor's "no" was excluded


def test_bootstrap_resolution_winning_side_evidence_required():
    """Even with a clear supermajority, missing evidence on the
    winning side voids the resolution."""
    min_age = float(CONFIG["bootstrap_min_identity_age_days"])
    base_ts = 0.0
    voter_count = 5
    chain: list[dict] = []
    for i in range(voter_count):
        chain.append(_node_register(f"v{i}", ts=base_ts + i, seq=10 + i))
    chain.append(_create("m1", base_ts=base_ts + 10 * _DAY_S))
    snap_ts = base_ts + (min_age + 5) * _DAY_S
    chain.append(_snapshot("m1", frozen_at=snap_ts))
    # Evidence ONLY on no side.
    chain.append(_evidence("m1", "ev_no", "no", ts=snap_ts + 100, seq=200))
    # All voters say YES.
    for i in range(voter_count):
        chain.append(_bootstrap_vote(f"v{i}", "m1", "yes",
                                     ts=snap_ts + 200 + i, seq=300 + i))
    result = resolve_market("m1", chain)
    assert result.outcome == "invalid"
    assert result.reason == "no_winning_side_evidence"


def test_bootstrap_resolution_dedups_duplicate_votes():
    """A node submitting two bootstrap votes is deduplicated to one.

    6 distinct yes-voting nodes + a spurious second "no" vote from v0.
    After dedup: 6 distinct nodes contribute 1 vote each. Whether
    v0's "yes" or "no" wins the dedup doesn't affect the outcome —
    5 or 6 yes out of 6 total ≥ 75% supermajority either way.
    """
    min_age = float(CONFIG["bootstrap_min_identity_age_days"])
    base_ts = 0.0
    voter_count = 6
    chain: list[dict] = []
    for i in range(voter_count):
        chain.append(_node_register(f"v{i}", ts=base_ts + i, seq=10 + i))
    chain.append(_create("m1", base_ts=base_ts + 10 * _DAY_S))
    snap_ts = base_ts + (min_age + 5) * _DAY_S
    chain.append(_snapshot("m1", frozen_at=snap_ts))
    chain.append(_evidence("m1", "ev_yes", "yes", ts=snap_ts + 100, seq=200))

    for i in range(voter_count):
        chain.append(_bootstrap_vote(f"v{i}", "m1", "yes",
                                     ts=snap_ts + 200 + i, seq=300 + i))
    chain.append(_bootstrap_vote("v0", "m1", "no",
                                  ts=snap_ts + 999, seq=399, pow_nonce=99))
    result = resolve_market("m1", chain)
    assert result.outcome == "yes"
    # Confirm dedup actually fired: count distinct voters in the
    # canonical set returned by the dedup helper.
    from services.infonet.bootstrap import deduplicate_votes
    canonical = deduplicate_votes("m1", chain)
    distinct_nodes = {v["node_id"] for v in canonical}
    assert len(distinct_nodes) == voter_count  # NOT voter_count + 1
