"""Sprint 7 — DSL executor adversarial tests.

Maps to IMPLEMENTATION_PLAN §7.1 Sprint 7 row:
"DSL executor rejects unknown payload types, missing keys, type
mismatches, out-of-bounds values, cross-field invariant violations,
immutable key writes. No `eval` / `exec` reachable."
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from services.infonet.config import CONFIG, IMMUTABLE_PRINCIPLES, InvalidPetition
from services.infonet.governance import (
    apply_petition_payload,
    forbidden_attributes_check,
)
import services.infonet.governance.dsl_executor as _dsl_module


# ── Forbidden-execution surface ─────────────────────────────────────────

def test_executor_source_contains_no_eval_or_exec():
    """The DSL executor must NOT reference any code-execution primitive
    in its own source. This test reads the file as bytes and scans
    for the curated forbidden tokens."""
    path = Path(_dsl_module.__file__)
    source = path.read_text(encoding="utf-8")
    # Strip the line that defines the forbidden-tokens set itself —
    # that line *names* the tokens but doesn't *use* them. Same for
    # the docstring reference.
    cleaned_lines = []
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith('"'):
            continue
        if 'forbidden' in stripped.lower() or '_FORBIDDEN' in stripped:
            continue
        cleaned_lines.append(line)
    cleaned = "\n".join(cleaned_lines)
    for tok in forbidden_attributes_check():
        assert tok not in cleaned, (
            f"forbidden token {tok!r} reachable in dsl_executor.py — "
            f"this is a constitutional violation"
        )


def test_no_dynamic_attribute_access_with_runtime_keys():
    """Sanity check: ``getattr`` calls in the executor module use
    static attribute names only. We can't easily prove this without
    AST analysis, but we can confirm there's no ``getattr(`` followed
    by an obvious payload-derived expression."""
    path = Path(_dsl_module.__file__)
    source = path.read_text(encoding="utf-8")
    # No "getattr(" appears in the executor — we use direct dict
    # access (CONFIG_SCHEMA[key]) throughout.
    assert "getattr(" not in source


# ── Type / payload rejection ────────────────────────────────────────────

def test_rejects_unknown_payload_type():
    with pytest.raises(InvalidPetition, match="unknown petition_payload type"):
        apply_petition_payload({"type": "DELETE_EVERYTHING"})


def test_rejects_non_dict_payload():
    with pytest.raises(InvalidPetition, match="must be an object"):
        apply_petition_payload("UPDATE_PARAM")  # type: ignore[arg-type]


def test_rejects_missing_type_field():
    with pytest.raises(InvalidPetition):
        apply_petition_payload({"key": "vote_decay_days", "value": 30})


def test_rejects_missing_key_in_update_param():
    with pytest.raises(InvalidPetition, match="UPDATE_PARAM requires"):
        apply_petition_payload({"type": "UPDATE_PARAM", "value": 30})


def test_rejects_missing_value_in_update_param():
    with pytest.raises(InvalidPetition, match="UPDATE_PARAM requires"):
        apply_petition_payload({"type": "UPDATE_PARAM", "key": "vote_decay_days"})


def test_rejects_unknown_config_key():
    with pytest.raises(InvalidPetition, match="unknown CONFIG key"):
        apply_petition_payload({
            "type": "UPDATE_PARAM",
            "key": "totally_made_up_param",
            "value": 42,
        })


def test_rejects_immutable_principles_key():
    """Constitutional: IMMUTABLE_PRINCIPLES keys cannot be mutated."""
    for key in IMMUTABLE_PRINCIPLES:
        with pytest.raises(InvalidPetition, match="IMMUTABLE_PRINCIPLES"):
            apply_petition_payload({
                "type": "UPDATE_PARAM",
                "key": key,
                "value": "wat",
            })


def test_rejects_type_mismatch():
    with pytest.raises(InvalidPetition, match="Type mismatch"):
        apply_petition_payload({
            "type": "UPDATE_PARAM",
            "key": "vote_decay_days",  # int field
            "value": "thirty",
        })


def test_rejects_below_min():
    with pytest.raises(InvalidPetition, match="below minimum"):
        apply_petition_payload({
            "type": "UPDATE_PARAM",
            "key": "vote_decay_days",
            "value": 1,  # min is 7
        })


def test_rejects_above_max():
    with pytest.raises(InvalidPetition, match="above maximum"):
        apply_petition_payload({
            "type": "UPDATE_PARAM",
            "key": "vote_decay_days",
            "value": 9999,  # max is 365
        })


def test_rejects_enum_violation():
    with pytest.raises(InvalidPetition):
        apply_petition_payload({
            "type": "UPDATE_PARAM",
            "key": "bootstrap_pow_algorithm",
            "value": "scrypt",  # only "argon2id" allowed
        })


# ── Cross-field invariants ──────────────────────────────────────────────

def test_rejects_supermajority_below_quorum_after_batch():
    """RULES §1.3 invariant: petition_supermajority > petition_quorum."""
    with pytest.raises(InvalidPetition, match="Cross-field invariant"):
        apply_petition_payload({
            "type": "BATCH_UPDATE_PARAMS",
            "updates": [
                {"key": "petition_supermajority", "value": 0.55},
                {"key": "petition_quorum", "value": 0.60},
            ],
        })


def test_batch_rejects_duplicate_keys():
    with pytest.raises(InvalidPetition, match="duplicate key"):
        apply_petition_payload({
            "type": "BATCH_UPDATE_PARAMS",
            "updates": [
                {"key": "vote_decay_days", "value": 30},
                {"key": "vote_decay_days", "value": 60},
            ],
        })


def test_batch_rejects_empty_list():
    with pytest.raises(InvalidPetition, match="non-empty"):
        apply_petition_payload({"type": "BATCH_UPDATE_PARAMS", "updates": []})


# ── Feature toggles ─────────────────────────────────────────────────────

def test_enable_feature_sets_bool_true():
    result = apply_petition_payload({
        "type": "ENABLE_FEATURE",
        "feature": "subjective_oracle_rep_mint",
    })
    assert result.new_config["subjective_oracle_rep_mint"] is True
    assert result.changed_keys == ("subjective_oracle_rep_mint",)


def test_disable_feature_sets_bool_false():
    result = apply_petition_payload({
        "type": "DISABLE_FEATURE",
        "feature": "phase_boundary_stale_reject",
    })
    assert result.new_config["phase_boundary_stale_reject"] is False


def test_feature_toggle_rejects_non_bool_key():
    with pytest.raises(InvalidPetition, match="not a boolean"):
        apply_petition_payload({
            "type": "ENABLE_FEATURE",
            "feature": "vote_decay_days",  # int, not bool
        })


def test_feature_toggle_rejects_unknown_feature():
    with pytest.raises(InvalidPetition, match="unknown CONFIG key"):
        apply_petition_payload({
            "type": "ENABLE_FEATURE",
            "feature": "make_me_dictator",
        })


# ── Transactional behavior ──────────────────────────────────────────────

def test_failed_batch_does_not_mutate_live_config():
    """If any update in a batch fails, NONE of them apply to the
    live CONFIG. The candidate config is discarded."""
    snapshot = deepcopy(CONFIG)
    with pytest.raises(InvalidPetition):
        apply_petition_payload({
            "type": "BATCH_UPDATE_PARAMS",
            "updates": [
                {"key": "vote_decay_days", "value": 30},  # valid
                {"key": "vote_decay_days_BAD", "value": 999},  # invalid key
            ],
        })
    assert CONFIG == snapshot


def test_successful_apply_returns_new_config_does_not_mutate_live():
    """The executor returns a candidate; the caller decides whether
    to swap. Live CONFIG remains unchanged until the caller acts."""
    before = CONFIG["vote_decay_days"]
    result = apply_petition_payload({
        "type": "UPDATE_PARAM",
        "key": "vote_decay_days",
        "value": 60,
    })
    assert result.new_config["vote_decay_days"] == 60
    # Live CONFIG unchanged.
    assert CONFIG["vote_decay_days"] == before


def test_apply_preserves_unrelated_keys():
    other_keys_before = {
        k: v for k, v in CONFIG.items() if k != "vote_decay_days"
    }
    result = apply_petition_payload({
        "type": "UPDATE_PARAM",
        "key": "vote_decay_days",
        "value": 30,
    })
    other_keys_after = {
        k: v for k, v in result.new_config.items() if k != "vote_decay_days"
    }
    assert other_keys_before == other_keys_after
