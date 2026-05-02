"""Sprint 1 — CONFIG_SCHEMA bounds + cross-field invariants are enforced.

Maps to BUILD_LOG.md Sprint 1 invariants #2, #3, #4, plus the spec's
``validate_petition_value`` and ``validate_cross_field_invariants``
contract in RULES §1.3.
"""

from __future__ import annotations

import copy

import pytest

from services.infonet.config import (
    CONFIG,
    CONFIG_SCHEMA,
    CROSS_FIELD_INVARIANTS,
    InvalidPetition,
    validate_config_schema_completeness,
    validate_cross_field_invariants,
    validate_petition_value,
)


def test_every_config_key_has_schema_entry():
    """Sprint 1 invariant #2."""
    validate_config_schema_completeness()


def test_baseline_config_passes_cross_field_invariants():
    validate_cross_field_invariants(CONFIG)


def test_unknown_key_rejected():
    with pytest.raises(InvalidPetition):
        validate_petition_value("not_a_real_key", 42)


def test_int_below_min_rejected():
    with pytest.raises(InvalidPetition):
        validate_petition_value("vote_decay_days", 1)


def test_int_above_max_rejected():
    with pytest.raises(InvalidPetition):
        validate_petition_value("vote_decay_days", 9999)


def test_int_at_min_accepted():
    validate_petition_value("vote_decay_days", 7)


def test_int_at_max_accepted():
    validate_petition_value("vote_decay_days", 365)


def test_float_below_min_rejected():
    with pytest.raises(InvalidPetition):
        validate_petition_value("petition_supermajority", 0.40)


def test_float_above_max_rejected():
    with pytest.raises(InvalidPetition):
        validate_petition_value("petition_supermajority", 0.999)


def test_type_mismatch_int_for_float_field():
    """Floats accept ints, but only when value passes bounds."""
    validate_petition_value("petition_supermajority", 0.67)


def test_type_mismatch_string_for_int_field():
    with pytest.raises(InvalidPetition):
        validate_petition_value("vote_decay_days", "seven")  # type: ignore[arg-type]


def test_type_mismatch_int_for_bool_field():
    """bool fields must be actual bool — int 1 is not bool."""
    with pytest.raises(InvalidPetition):
        validate_petition_value("phase_boundary_stale_reject", 1)  # type: ignore[arg-type]


def test_type_mismatch_bool_for_int_field():
    """bool 1/0 must NOT be accepted as int — historic Python footgun."""
    with pytest.raises(InvalidPetition):
        validate_petition_value("vote_decay_days", True)  # type: ignore[arg-type]


def test_enum_violation_rejected():
    with pytest.raises(InvalidPetition):
        validate_petition_value("bootstrap_pow_algorithm", "scrypt")


def test_enum_value_accepted():
    validate_petition_value("bootstrap_pow_algorithm", "argon2id")


@pytest.mark.parametrize("left, op, right", CROSS_FIELD_INVARIANTS)
def test_cross_field_invariant_violation_rejected(left, op, right):
    """Mutating one side of a > invariant to break ordering must fail."""
    bad = copy.deepcopy(CONFIG)
    if op == ">":
        # Force left == right so the strict inequality fails.
        bad[left] = bad[right]
        with pytest.raises(InvalidPetition):
            validate_cross_field_invariants(bad)


def test_supermajority_below_quorum_rejected():
    """Plan §9 / RULES §1.3 — governance is incoherent if quorum can pass without majority."""
    bad = copy.deepcopy(CONFIG)
    bad["petition_supermajority"] = 0.55
    bad["petition_quorum"] = 0.60
    with pytest.raises(InvalidPetition):
        validate_cross_field_invariants(bad)


def test_resolution_supermajority_must_exceed_da_threshold():
    bad = copy.deepcopy(CONFIG)
    bad["resolution_supermajority"] = 0.55
    bad["data_unavailable_threshold"] = 0.55
    with pytest.raises(InvalidPetition):
        validate_cross_field_invariants(bad)


def test_farming_thresholds_must_be_ordered():
    bad = copy.deepcopy(CONFIG)
    bad["farming_soft_threshold"] = 0.85
    bad["farming_hard_threshold"] = 0.80
    with pytest.raises(InvalidPetition):
        validate_cross_field_invariants(bad)


def test_truth_stake_max_must_exceed_min():
    bad = copy.deepcopy(CONFIG)
    bad["truth_stake_min_days"] = 7
    bad["truth_stake_max_days"] = 7
    with pytest.raises(InvalidPetition):
        validate_cross_field_invariants(bad)


def test_config_schema_is_immutable():
    from types import MappingProxyType
    assert isinstance(CONFIG_SCHEMA, MappingProxyType)
    with pytest.raises(TypeError):
        CONFIG_SCHEMA["new_key"] = {"type": "int"}  # type: ignore[index]
