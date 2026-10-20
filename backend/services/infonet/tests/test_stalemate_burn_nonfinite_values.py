"""Regression coverage for non-finite stalemate burn inputs."""

import math

import pytest

from services.infonet.markets.stalemate_burn import apply_to_stakes, split_burn_and_return


def test_split_rejects_nonfinite_amounts():
    assert split_burn_and_return(float("nan"), 0.1) == (0.0, 0.0)
    assert split_burn_and_return(float("inf"), 0.1) == (0.0, 0.0)


def test_apply_skips_nonfinite_stakes_without_poisoning_totals():
    returns, burned = apply_to_stakes(
        [
            {"node_id": "alice", "rep_type": "oracle", "amount": 10.0},
            {"node_id": "mallory", "rep_type": "oracle", "amount": float("nan")},
            {"node_id": "eve", "rep_type": "common", "amount": float("inf")},
        ],
        burn_pct=0.1,
    )

    assert returns == {("alice", "oracle"): 9.0}
    assert burned == 1.0
    assert math.isfinite(burned)


def test_nonfinite_burn_percentage_is_rejected():
    with pytest.raises(ValueError, match="burn_pct must be finite"):
        split_burn_and_return(10.0, float("nan"))

    with pytest.raises(ValueError, match="burn_pct must be finite"):
        apply_to_stakes([], burn_pct=float("inf"))
