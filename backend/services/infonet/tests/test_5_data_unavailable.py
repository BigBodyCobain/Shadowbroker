"""Sprint 5 — DATA_UNAVAILABLE phantom-evidence slashing.

Maps to IMPLEMENTATION_PLAN §7.1 Sprint 5 row:
"DATA_UNAVAILABLE ≥33% triggers INVALID + bond slashing."
"""

from __future__ import annotations

from services.infonet.config import CONFIG
from services.infonet.markets import resolve_market
from services.infonet.markets.stalemate_burn import stalemate_burn_pct
from services.infonet.tests._chain_factory import make_event


def _create(market_id: str, base_ts: float) -> dict:
    return make_event(
        "prediction_create", "creator",
        {"market_id": market_id, "market_type": "objective",
         "question": "?", "trigger_date": base_ts + 100, "creation_bond": 3},
        timestamp=base_ts, sequence=1,
    )


def _snapshot(market_id: str, frozen_at: float, *, predictors: list[str] | None = None,
              seq: int = 50) -> dict:
    p = predictors or []
    return make_event(
        "market_snapshot", "creator",
        {"market_id": market_id, "frozen_participant_count": len(p),
         "frozen_total_stake": 20.0, "frozen_predictor_ids": list(p),
         "frozen_probability_state": {"yes": 0.5, "no": 0.5},
         "frozen_at": frozen_at},
        timestamp=frozen_at, sequence=seq,
    )


def _evidence(market_id: str, node_id: str, outcome: str, *,
              ts: float, seq: int, bond: float = 2.0) -> dict:
    from services.infonet.markets.evidence import evidence_content_hash, submission_hash
    h = [f"ev-{node_id}-{outcome}"]
    chash = evidence_content_hash(market_id, outcome, h, "src")
    shash = submission_hash(chash, node_id, ts)
    return make_event(
        "evidence_submit", node_id,
        {"market_id": market_id, "claimed_outcome": outcome,
         "evidence_hashes": h, "source_description": "src",
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


def test_da_above_threshold_invalidates_market():
    threshold = float(CONFIG["data_unavailable_threshold"])
    chain = [
        _create("m1", 0.0),
        _snapshot("m1", frozen_at=100.0),
        _evidence("m1", "ev1", "yes", ts=110, seq=10),
        _stake("m1", "da1", "data_unavailable", 10.0, ts=200, seq=20),
        _stake("m1", "yes1", "yes", 19.0, ts=201, seq=21),
    ]
    # 10/(10+19) ≈ 0.345 > threshold 0.33.
    result = resolve_market("m1", chain)
    assert result.outcome == "invalid"
    assert result.reason == "data_unavailable"
    assert (10.0 / 29.0) >= threshold  # sanity check on the test setup


def test_da_below_threshold_does_not_trigger():
    chain = [
        _create("m1", 0.0),
        _snapshot("m1", frozen_at=100.0),
        _evidence("m1", "ev1", "yes", ts=110, seq=10),
        # Only 5/35 = 14% DA — below 33%.
        _stake("m1", "da1", "data_unavailable", 5.0, ts=200, seq=20),
        _stake("m1", "yes1", "yes", 30.0, ts=201, seq=21),
    ]
    result = resolve_market("m1", chain)
    # DA is below threshold; market resolves on supermajority. yes_oracle=30, no_oracle=0
    # → 30/30 = 100% supermajority for yes → outcome=yes.
    assert result.outcome == "yes"


def test_da_triggers_evidence_bond_slashing():
    """Per RULES §3.10 step 1.5: ALL evidence submitter bonds are
    slashed when DA fires — not returned, burned."""
    chain = [
        _create("m1", 0.0),
        _snapshot("m1", frozen_at=100.0),
        _evidence("m1", "ev_yes", "yes", ts=110, seq=10, bond=2.0),
        _evidence("m1", "ev_no", "no", ts=111, seq=11, bond=2.0),
        _stake("m1", "da1", "data_unavailable", 15.0, ts=200, seq=20),
        _stake("m1", "yes1", "yes", 15.0, ts=201, seq=21),
    ]
    # 15/30 = 50% DA — well above 33%.
    result = resolve_market("m1", chain)
    assert result.outcome == "invalid"
    # Both evidence bonds forfeited.
    assert result.bond_forfeits.get("ev_yes") == 2.0
    assert result.bond_forfeits.get("ev_no") == 2.0
    # No bonds returned.
    assert "ev_yes" not in result.bond_returns
    assert "ev_no" not in result.bond_returns
    # Burn includes both bonds (4.0) plus stalemate burn on yes/no stake (15 * 0.02 = 0.30).
    expected_burn = 4.0 + 15.0 * stalemate_burn_pct()
    assert abs(result.burned_amount - expected_burn) < 1e-9


def test_da_voters_get_full_return():
    """DA voters acted correctly — full stake return."""
    chain = [
        _create("m1", 0.0),
        _snapshot("m1", frozen_at=100.0),
        _evidence("m1", "ev_yes", "yes", ts=110, seq=10),
        _stake("m1", "da1", "data_unavailable", 10.0, ts=200, seq=20),
        _stake("m1", "da2", "data_unavailable", 5.0, ts=201, seq=21),
        _stake("m1", "yes1", "yes", 14.0, ts=202, seq=22),
    ]
    # 15/29 ≈ 51% DA — above 33%.
    result = resolve_market("m1", chain)
    assert result.outcome == "invalid"
    assert result.reason == "data_unavailable"
    assert result.stake_returns.get(("da1", "oracle")) == 10.0
    assert result.stake_returns.get(("da2", "oracle")) == 5.0


def test_da_yes_no_stakers_take_stalemate_burn():
    """Yes/no stakers in DA-triggered INVALID get stalemate burn."""
    chain = [
        _create("m1", 0.0),
        _snapshot("m1", frozen_at=100.0),
        _evidence("m1", "ev_yes", "yes", ts=110, seq=10),
        _stake("m1", "da1", "data_unavailable", 15.0, ts=200, seq=20),
        _stake("m1", "yes1", "yes", 10.0, ts=201, seq=21),
        _stake("m1", "no1", "no", 5.0, ts=202, seq=22),
    ]
    # 15/30 = 50% DA — fires.
    result = resolve_market("m1", chain)
    burn_pct = stalemate_burn_pct()
    expected_yes_return = 10.0 * (1.0 - burn_pct)
    expected_no_return = 5.0 * (1.0 - burn_pct)
    assert abs(result.stake_returns.get(("yes1", "oracle"), 0.0) - expected_yes_return) < 1e-9
    assert abs(result.stake_returns.get(("no1", "oracle"), 0.0) - expected_no_return) < 1e-9


def test_da_at_exact_threshold_triggers():
    """Threshold check is `>=` not strict `>`."""
    threshold = float(CONFIG["data_unavailable_threshold"])
    # Choose stakes so DA is exactly threshold of total.
    da_amount = threshold * 100
    other_amount = 100 - da_amount
    chain = [
        _create("m1", 0.0),
        _snapshot("m1", frozen_at=100.0),
        _evidence("m1", "ev1", "yes", ts=110, seq=10),
        _stake("m1", "da1", "data_unavailable", da_amount, ts=200, seq=20),
        _stake("m1", "yes1", "yes", other_amount, ts=201, seq=21),
    ]
    result = resolve_market("m1", chain)
    assert result.outcome == "invalid"
    assert result.reason == "data_unavailable"
