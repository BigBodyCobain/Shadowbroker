"""Sprint 4 — resolution + predictor exclusion + first-submitter bonus.

Maps to IMPLEMENTATION_PLAN §7.1 Sprint 4 row:
- "Predictor cannot stake in resolution."
- "Snapshot is immutable." (covered in test_4_snapshot.py)
- "First evidence per side gets bonus."
- "Zero evidence → INVALID."
- "Winning-side evidence required for FINAL."
"""

from __future__ import annotations

from services.infonet.markets import (
    collect_resolution_stakes,
    evidence_content_hash,
    excluded_predictor_ids,
    is_predictor_excluded,
    resolve_market,
    submission_hash,
)
from services.infonet.tests._chain_factory import make_event


def _create(market_id: str, base_ts: float, *, market_type: str = "objective",
            bootstrap_index: int | None = None) -> dict:
    payload = {"market_id": market_id, "market_type": market_type,
               "question": "?", "trigger_date": base_ts + 100, "creation_bond": 3}
    if bootstrap_index is not None:
        payload["bootstrap_index"] = bootstrap_index
    return make_event("prediction_create", "creator", payload, timestamp=base_ts, sequence=1)


def _place(market_id: str, node_id: str, side: str, *, ts: float, seq: int,
           stake: float | None = None, prob: float = 50.0) -> dict:
    payload = {"market_id": market_id, "side": side, "probability_at_bet": prob}
    if stake is not None:
        payload["stake_amount"] = stake
    return make_event("prediction_place", node_id, payload, timestamp=ts, sequence=seq)


def _snapshot(market_id: str, frozen_at: float, *, predictors: list[str], seq: int = 50) -> dict:
    return make_event(
        "market_snapshot", "creator",
        {"market_id": market_id, "frozen_participant_count": len(predictors),
         "frozen_total_stake": 20.0, "frozen_predictor_ids": list(predictors),
         "frozen_probability_state": {"yes": 0.5, "no": 0.5},
         "frozen_at": frozen_at},
        timestamp=frozen_at, sequence=seq,
    )


def _evidence(market_id: str, node_id: str, outcome: str, *,
              ts: float, seq: int, bond: float = 2.0,
              hashes: list[str] | None = None, desc: str = "src") -> dict:
    h = hashes if hashes is not None else [f"ev-{node_id}-{outcome}"]
    chash = evidence_content_hash(market_id, outcome, h, desc)
    shash = submission_hash(chash, node_id, ts)
    return make_event(
        "evidence_submit", node_id,
        {"market_id": market_id, "claimed_outcome": outcome,
         "evidence_hashes": h, "source_description": desc,
         "evidence_content_hash": chash, "submission_hash": shash, "bond": bond},
        timestamp=ts, sequence=seq,
    )


def _stake(market_id: str, node_id: str, side: str, amount: float, *,
           ts: float, seq: int, rep_type: str = "oracle") -> dict:
    return make_event(
        "resolution_stake", node_id,
        {"market_id": market_id, "side": side, "amount": amount, "rep_type": rep_type},
        timestamp=ts, sequence=seq,
    )


# ── Predictor exclusion ─────────────────────────────────────────────────

def test_predictor_in_snapshot_is_excluded():
    chain = [
        _create("m1", 0.0),
        _place("m1", "alice", "yes", ts=10, seq=2, stake=10.0),
        _snapshot("m1", frozen_at=100.0, predictors=["alice"]),
    ]
    assert is_predictor_excluded("alice", "m1", chain)
    assert not is_predictor_excluded("bob", "m1", chain)


def test_rotation_descendant_inherits_exclusion():
    chain = [
        _create("m1", 0.0),
        _place("m1", "alice", "yes", ts=10, seq=2, stake=10.0),
        _snapshot("m1", frozen_at=100.0, predictors=["alice"]),
        # alice rotates to alice2 AFTER snapshot. The rotation is signed
        # by the new identity per spec.
        make_event("identity_rotate", "alice2",
                   {"old_node_id": "alice", "old_public_key": "pk",
                    "old_public_key_algo": "ed25519",
                    "new_public_key": "pk2", "new_public_key_algo": "ed25519",
                    "old_signature": "sig"},
                   timestamp=200.0, sequence=99),
    ]
    excluded = excluded_predictor_ids("m1", chain)
    assert "alice" in excluded
    assert "alice2" in excluded
    assert is_predictor_excluded("alice2", "m1", chain)


def test_resolution_stake_from_excluded_predictor_dropped():
    base = 0.0
    chain = [
        _create("m1", base),
        _place("m1", "alice", "yes", ts=10, seq=2, stake=10.0),
        _snapshot("m1", frozen_at=100.0, predictors=["alice"]),
        # alice tries to stake on her own market.
        _stake("m1", "alice", "yes", 5.0, ts=200, seq=3),
        # bob is a clean external resolver.
        _stake("m1", "bob", "yes", 15.0, ts=201, seq=4),
    ]
    stakes = collect_resolution_stakes("m1", chain, exclude_predictors=True)
    nodes = {s.node_id for s in stakes}
    assert "alice" not in nodes
    assert "bob" in nodes


# ── Zero-evidence INVALID ────────────────────────────────────────────────

def test_zero_evidence_resolves_to_invalid():
    chain = [
        _create("m1", 0.0),
        _place("m1", "alice", "yes", ts=10, seq=2, stake=10.0),
        _snapshot("m1", frozen_at=100.0, predictors=["alice"]),
    ]
    result = resolve_market("m1", chain)
    assert result.outcome == "invalid"
    assert result.reason == "no_evidence"


def test_zero_evidence_returns_resolution_stakes():
    chain = [
        _create("m1", 0.0),
        _snapshot("m1", frozen_at=100.0, predictors=[]),
        _stake("m1", "bob", "yes", 5.0, ts=200, seq=3),
        _stake("m1", "carol", "no", 5.0, ts=201, seq=4),
    ]
    result = resolve_market("m1", chain)
    assert result.outcome == "invalid"
    assert result.stake_returns[("bob", "oracle")] == 5.0
    assert result.stake_returns[("carol", "oracle")] == 5.0


# ── Winning-side evidence required ───────────────────────────────────────

def test_no_winning_side_evidence_resolves_to_invalid():
    """Resolution stakers reach 100% yes, but only "no" evidence exists."""
    chain = [
        _create("m1", 0.0),
        _snapshot("m1", frozen_at=100.0, predictors=[]),
        _evidence("m1", "ev1", "no", ts=110, seq=10),
        _stake("m1", "bob", "yes", 25.0, ts=200, seq=20),
    ]
    result = resolve_market("m1", chain)
    assert result.outcome == "invalid"
    assert result.reason == "no_winning_side_evidence"


def test_winning_side_evidence_present_resolves_final():
    chain = [
        _create("m1", 0.0),
        _snapshot("m1", frozen_at=100.0, predictors=[]),
        _evidence("m1", "ev1", "yes", ts=110, seq=10),
        _stake("m1", "bob", "yes", 25.0, ts=200, seq=20),
    ]
    result = resolve_market("m1", chain)
    assert result.outcome == "yes"
    assert result.reason.startswith("supermajority_")


# ── Below min resolution stake ───────────────────────────────────────────

def test_below_min_resolution_stake_is_invalid():
    chain = [
        _create("m1", 0.0),
        _snapshot("m1", frozen_at=100.0, predictors=[]),
        _evidence("m1", "ev1", "yes", ts=110, seq=10),
        # Only 5.0 oracle staked — below default min 20.0.
        _stake("m1", "bob", "yes", 5.0, ts=200, seq=20),
    ]
    result = resolve_market("m1", chain)
    assert result.outcome == "invalid"
    assert result.reason == "below_min_resolution_stake"


def test_no_supermajority_is_invalid():
    chain = [
        _create("m1", 0.0),
        _snapshot("m1", frozen_at=100.0, predictors=[]),
        _evidence("m1", "ev1", "yes", ts=110, seq=10),
        _evidence("m1", "ev2", "no", ts=120, seq=11),
        _stake("m1", "bob", "yes", 12.0, ts=200, seq=20),
        _stake("m1", "carol", "no", 12.0, ts=201, seq=21),
    ]
    result = resolve_market("m1", chain)
    assert result.outcome == "invalid"
    assert result.reason == "no_supermajority"


# ── First-submitter bonus ────────────────────────────────────────────────

def test_first_submitter_gets_bonus_capped_at_losing_pool():
    chain = [
        _create("m1", 0.0),
        _snapshot("m1", frozen_at=100.0, predictors=[]),
        # Two yes-side evidences, alice first.
        _evidence("m1", "alice", "yes", ts=110, seq=10, bond=2.0),
        _evidence("m1", "bob", "yes", ts=111, seq=11, bond=2.0),
        # One losing-side evidence (no) — bond becomes the bonus pool.
        _evidence("m1", "carol", "no", ts=112, seq=12, bond=2.0),
        # Heavy yes resolution stakes.
        _stake("m1", "dan", "yes", 25.0, ts=200, seq=20),
    ]
    result = resolve_market("m1", chain)
    assert result.outcome == "yes"
    # alice is the first yes-evidence submitter — eligible for bonus
    # capped by losing pool (2.0) and CONFIG['evidence_first_bonus'] (0.5).
    assert "alice" in result.first_submitter_bonuses
    assert result.first_submitter_bonuses["alice"] == 0.5
    # bob is NOT first.
    assert "bob" not in result.first_submitter_bonuses
    # carol's losing bond is forfeited.
    assert result.bond_forfeits.get("carol") == 2.0


def test_first_submitter_bonus_capped_when_losing_pool_empty():
    """If no losing-side evidence exists, the bonus pool is empty and
    the first submitter receives 0 bonus (NOT minted)."""
    chain = [
        _create("m1", 0.0),
        _snapshot("m1", frozen_at=100.0, predictors=[]),
        _evidence("m1", "alice", "yes", ts=110, seq=10, bond=2.0),
        _stake("m1", "bob", "yes", 25.0, ts=200, seq=20),
    ]
    result = resolve_market("m1", chain)
    assert result.outcome == "yes"
    # alice's bond is returned but no bonus paid.
    assert result.bond_returns.get("alice") == 2.0
    assert "alice" not in result.first_submitter_bonuses


# ── Stake distribution + 2% loser burn ───────────────────────────────────

def test_winning_stakes_split_loser_pool_with_2pct_burn():
    chain = [
        _create("m1", 0.0),
        _snapshot("m1", frozen_at=100.0, predictors=[]),
        _evidence("m1", "ev1", "yes", ts=110, seq=10),
        # 30 yes vs 8 no → 30/38 ≈ 0.789 > 0.75 supermajority.
        _stake("m1", "alice", "yes", 30.0, ts=200, seq=20),
        _stake("m1", "loser", "no", 8.0, ts=201, seq=21),
    ]
    result = resolve_market("m1", chain)
    assert result.outcome == "yes"
    # Loser pool 8. Burn 2% = 0.16. Distributable 7.84. alice has 100%
    # of winner pool (30/30) → alice winnings = 7.84.
    assert abs(result.stake_winnings.get(("alice", "oracle"), 0.0) - 7.84) < 1e-9
    assert result.stake_returns.get(("alice", "oracle"), 0.0) == 30.0
    # loser doesn't get returns.
    assert ("loser", "oracle") not in result.stake_returns
    assert abs(result.burned_amount - 0.16) < 1e-9


# ── Subjective markets resolve but mint no oracle rep ────────────────────

def test_subjective_market_resolves_but_oracle_rep_gates_zero():
    """resolve_market returns the outcome for subjective markets, but
    oracle_rep._market_is_mintable should still return False (Sprint 2
    invariant). Cross-check: the reputation view stays at zero."""
    from services.infonet.reputation import compute_oracle_rep
    chain = [
        _create("m1", 0.0, market_type="subjective"),
        _place("m1", "alice", "yes", ts=10, seq=2),
        _snapshot("m1", frozen_at=100.0, predictors=["alice"]),
        _evidence("m1", "ev1", "yes", ts=110, seq=10),
        _stake("m1", "bob", "yes", 25.0, ts=200, seq=20),
        # Producer would emit resolution_finalize here based on result.
        make_event("resolution_finalize", "creator",
                   {"market_id": "m1", "outcome": "yes",
                    "is_provisional": False, "snapshot_event_hash": "h"},
                   timestamp=300.0, sequence=99),
    ]
    result = resolve_market("m1", chain)
    assert result.outcome == "yes"  # subjective still resolves
    assert compute_oracle_rep("alice", chain) == 0  # but mints zero


# ── Bootstrap markets defer to Sprint 8 ──────────────────────────────────

def test_bootstrap_market_without_votes_is_below_min_participation():
    """Sprint 8: bootstrap markets resolve via eligible-node-one-vote.
    A bootstrap market with no votes fails the min_market_participants
    gate → INVALID with reason='bootstrap_below_min_participation'.
    """
    chain = [
        _create("m1", 0.0, bootstrap_index=1),
        _snapshot("m1", frozen_at=100.0, predictors=[]),
        _evidence("m1", "ev1", "yes", ts=110, seq=10),
    ]
    result = resolve_market("m1", chain)
    assert result.outcome == "invalid"
    assert result.reason == "bootstrap_below_min_participation"


# ── DA threshold detection ───────────────────────────────────────────────

def test_data_unavailable_threshold_invalidates():
    chain = [
        _create("m1", 0.0),
        _snapshot("m1", frozen_at=100.0, predictors=[]),
        _evidence("m1", "ev1", "yes", ts=110, seq=10),
        # 35% DA in oracle stake — above default 33% threshold.
        _stake("m1", "da1", "data_unavailable", 10.0, ts=200, seq=20),
        _stake("m1", "yes1", "yes", 19.0, ts=201, seq=21),
    ]
    result = resolve_market("m1", chain)
    assert result.outcome == "invalid"
    assert result.reason == "data_unavailable"
