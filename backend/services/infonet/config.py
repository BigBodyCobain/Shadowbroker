"""Constitutional + governable parameters for the Infonet economy.

Source of truth: ``infonet-economy/RULES_SKELETON.md`` §1.

- ``IMMUTABLE_PRINCIPLES`` — constitutional, exposed as a ``MappingProxyType``.
  Mutation attempts raise ``TypeError`` at the language level. New keys can
  only be added through upgrade-hash governance (Sprint 7) which is itself
  governed by these principles — i.e. a hard fork.

- ``CONFIG`` — amendable parameters. Live (mutable) dict; all writes go
  through ``validate_petition_value`` first. The dict itself is a
  module-level singleton — the governance DSL executor (Sprint 7) is the
  only intended writer in production. Tests must use
  ``reset_config_for_tests`` to restore baseline.

- ``CONFIG_SCHEMA`` — per-key bounds and types. Itself an immutable
  ``MappingProxyType``. New schema entries require a hard fork (same flow
  as ``IMMUTABLE_PRINCIPLES``).

- ``CROSS_FIELD_INVARIANTS`` — ordered-pair invariants checked AFTER all
  updates in a ``BATCH_UPDATE_PARAMS``. Spec note: supermajority must
  always exceed quorum, etc.

This file is read by every subsequent sprint. Adding a CONFIG key without
adding a matching CONFIG_SCHEMA entry is a Sprint 1 invariant violation
and is asserted by the tests.
"""

from __future__ import annotations

from copy import deepcopy
from types import MappingProxyType
from typing import Any


class InvalidPetition(ValueError):
    """Raised by ``validate_petition_value`` and the governance DSL executor.

    Signals that a proposed CONFIG mutation is rejected by the schema or by
    a cross-field invariant. The DSL executor (Sprint 7) catches this and
    rolls back the petition — never partially applies.
    """


# ─── Constitutional principles ───────────────────────────────────────────
# Immutable. Mutation attempts raise TypeError at the language level
# because MappingProxyType is read-only.
#
# RULES_SKELETON.md §1.1 — adding a key here is a hard fork.

IMMUTABLE_PRINCIPLES: MappingProxyType = MappingProxyType({
    "oracle_rep_source":        "predictions_only",
    "hashchain_append_only":    True,
    "audit_public":             True,
    "identity_permissionless":  True,
    "signature_required":       True,
    "redemption_path_exists":   True,
    "coin_governance_firewall": True,
    "protocol_version":         "0.1.0",
})


# ─── Amendable parameters ────────────────────────────────────────────────
# RULES_SKELETON.md §1.2.
# Mutable dict. Production writes only via the Sprint 7 governance DSL
# executor which calls validate_petition_value first.

_BASELINE_CONFIG: dict[str, Any] = {
    # ── Reputation ──
    "vote_decay_days":              90,
    "min_rep_to_vote":              3,
    "min_rep_to_create_gate":       10,
    "bootstrap_threshold":          1000,
    "weekly_vote_base":             5,
    "weekly_vote_per_oracle":       10,
    "daily_vote_limit_per_target":  1,

    # ── Oracle Rep ──
    "oracle_min_earned":            0.01,
    "farming_soft_threshold":       0.60,
    "farming_hard_threshold":       0.80,
    "farming_easy_bet_cutoff":      0.80,
    "subjective_oracle_rep_mint":   False,

    # ── Market Liquidity ──
    "min_market_participants":      5,
    "min_market_total_stake":       10.0,

    # ── Resolution Phase ──
    "evidence_window_hours":        48,
    "resolution_window_hours":      72,
    "evidence_bond_cost":           2.0,
    "evidence_first_bonus":         0.5,
    "resolution_supermajority":     0.75,
    "min_resolution_stake_total":   20.0,
    "resolution_loser_burn_pct":    0.02,
    "data_unavailable_threshold":   0.33,
    "resolution_stalemate_burn_pct": 0.02,

    # ── Governance Decay ──
    "governance_decay_days":        90,
    "governance_decay_factor":      0.50,

    # ── Time Validity ──
    "max_future_event_drift_sec":   300,
    "phase_boundary_stale_reject":  True,

    # ── Identity Rotation ──
    "rotation_blocked_during_stakes": True,

    # ── Anti-Gaming ──
    "vcs_min_weight":               0.10,
    "clustering_min_weight":        0.20,
    "temporal_burst_window_sec":    300,
    "temporal_burst_min_upreps":    5,
    "progressive_penalty_base":     1.0,
    # Common-rep base formula multiplier (RULES §3.3). Promoted from
    # Sprint 2's module-private constant 2026-04-28 so governance can
    # tune the default common-rep payout per uprep.
    "common_rep_weight_factor":     0.10,
    # Progressive-penalty trigger threshold — average correlation
    # score above which the whale-deterrence multiplier kicks in
    # (Sprint 3 polish 2026-04-28). 0.0 = disabled (Sprint 3 default
    # behavior preserved).
    "progressive_penalty_threshold": 0.0,

    # ── Gates ──
    "gate_ratification_rep":        50,
    "gate_lock_cost_per_member":    10,
    "gate_lock_min_members":        5,
    "gate_creation_rate_limit":     5,

    # ── Truth Stakes ──
    "truth_stake_min_days":         1,
    "truth_stake_max_days":         7,
    "truth_stake_grace_hours":      24,
    "truth_stake_max_extensions":   3,
    "truth_stake_tie_burn_pct":     0.20,
    "truth_stake_self_stake":       False,

    # ── Dispute Resolution ──
    "dispute_window_days":          7,
    "dispute_common_rep_stakeable": True,

    # ── CommonCoin ──
    "monthly_mint_amount":          100000,
    "ubi_share_pct":                0.50,
    "oracle_dividend_pct":          0.50,
    "citizenship_sacrifice_cost":   10,
    "year1_max_coins_per_node":     10000,

    # ── Governance ──
    "petition_filing_cost":         15,
    "petition_signature_threshold": 0.25,
    "petition_signature_window_days": 14,
    "petition_vote_window_days":    7,
    "petition_supermajority":       0.67,
    "petition_quorum":              0.30,
    "challenge_filing_cost":        25,
    "challenge_window_hours":       48,

    # ── Upgrade-Hash Governance ──
    "upgrade_filing_cost":          25,
    "upgrade_signature_threshold":  0.25,
    "upgrade_signature_window_days": 14,
    "upgrade_vote_window_days":     14,
    "upgrade_supermajority":        0.80,
    "upgrade_quorum":               0.40,
    "upgrade_activation_threshold": 0.67,
    "upgrade_activation_window_days": 30,
    "upgrade_challenge_window_hours": 48,

    # ── Gate Shutdown ──
    "gate_suspend_filing_cost":     15,
    "gate_shutdown_filing_cost":    25,
    "gate_suspend_supermajority":   0.67,
    "gate_suspend_locked_supermajority": 0.75,
    "gate_shutdown_supermajority":  0.75,
    "gate_shutdown_locked_supermajority": 0.80,
    "gate_shutdown_quorum":         0.30,
    "gate_suspend_duration_days":   30,
    "gate_shutdown_execution_delay_days": 7,
    "gate_shutdown_cooldown_days":  90,
    "gate_shutdown_fail_penalty_days": 30,
    "gate_shutdown_appeal_filing_cost": 20,
    "gate_shutdown_appeal_window_hours": 48,
    "gate_shutdown_appeal_vote_window_days": 7,
    "gate_shutdown_appeal_supermajority": 0.67,
    "gate_shutdown_appeal_locked_supermajority": 0.75,
    "gate_shutdown_appeal_quorum": 0.30,

    # ── Market Creation ──
    "market_creation_bond":         3,
    "market_creation_bond_return_threshold": 5,

    # ── Bootstrap ──
    "bootstrap_market_count":       100,
    "bootstrap_evidence_bond_cost": 0,
    "bootstrap_resolution_mode":    "eligible_node_one_vote",
    "bootstrap_resolution_supermajority": 0.75,
    "bootstrap_min_identity_age_days": 3,
    "bootstrap_pow_algorithm":      "argon2id",
    "bootstrap_pow_argon2id_version": 0x13,
    "bootstrap_pow_argon2id_m":     65536,
    "bootstrap_pow_argon2id_t":     3,
    "bootstrap_pow_argon2id_p":     1,
    "bootstrap_pow_argon2id_output_len": 32,
    "bootstrap_pow_difficulty":     16,

    # ── Ramp milestones (Sprint 8 polish 2026-04-28) ──
    # Network-size thresholds at which features activate. Promoted
    # from Sprint 8 hardcoded constants so governance can tune them.
    # Values denote the minimum distinct-node count required.
    "ramp_staked_resolution_threshold":  1000,
    "ramp_petitions_threshold":          2000,
    "ramp_upgrade_threshold":            5000,
    "ramp_commoncoin_threshold":        10000,
}


CONFIG: dict[str, Any] = deepcopy(_BASELINE_CONFIG)


def reset_config_for_tests() -> None:
    """Restore CONFIG to the pre-petition baseline. Tests only.

    Used by the autouse fixture in ``services/infonet/tests/conftest.py`` so
    that one test mutating CONFIG (via a simulated petition execution)
    cannot leak state into the next test.
    """
    CONFIG.clear()
    CONFIG.update(deepcopy(_BASELINE_CONFIG))


# ─── CONFIG schema (per-key bounds) ──────────────────────────────────────
# RULES_SKELETON.md §1.3.
# Itself an immutable structure — new keys require upgrade-hash governance
# (a hard fork). validate_petition_value rejects any key not present here.

_SCHEMA_TYPES = {
    "int":   (int,),
    "float": (int, float),
    "bool":  (bool,),
    "str":   (str,),
}

_CONFIG_SCHEMA_BACKING: dict[str, MappingProxyType] = {
    # ── Reputation ──
    "vote_decay_days":              MappingProxyType({"type": "int",   "min": 7,    "max": 365}),
    "min_rep_to_vote":              MappingProxyType({"type": "int",   "min": 0,    "max": 100}),
    "min_rep_to_create_gate":       MappingProxyType({"type": "int",   "min": 1,    "max": 1000}),
    "bootstrap_threshold":          MappingProxyType({"type": "int",   "min": 100,  "max": 100000}),
    "weekly_vote_base":             MappingProxyType({"type": "int",   "min": 1,    "max": 100}),
    "weekly_vote_per_oracle":       MappingProxyType({"type": "int",   "min": 1,    "max": 1000}),
    "daily_vote_limit_per_target":  MappingProxyType({"type": "int",   "min": 1,    "max": 10}),

    # ── Oracle Rep ──
    "oracle_min_earned":            MappingProxyType({"type": "float", "min": 0.001, "max": 1.0}),
    "farming_soft_threshold":       MappingProxyType({"type": "float", "min": 0.10,  "max": 0.95}),
    "farming_hard_threshold":       MappingProxyType({"type": "float", "min": 0.20,  "max": 0.99}),
    "farming_easy_bet_cutoff":      MappingProxyType({"type": "float", "min": 0.50,  "max": 0.99}),
    "subjective_oracle_rep_mint":   MappingProxyType({"type": "bool"}),

    # ── Market Liquidity ──
    "min_market_participants":      MappingProxyType({"type": "int",   "min": 2,    "max": 100}),
    "min_market_total_stake":       MappingProxyType({"type": "float", "min": 1.0,  "max": 1000.0}),

    # ── Resolution ──
    "evidence_window_hours":        MappingProxyType({"type": "int",   "min": 12,   "max": 168}),
    "resolution_window_hours":      MappingProxyType({"type": "int",   "min": 24,   "max": 336}),
    "evidence_bond_cost":           MappingProxyType({"type": "float", "min": 0.5,  "max": 50.0}),
    "evidence_first_bonus":         MappingProxyType({"type": "float", "min": 0.0,  "max": 10.0}),
    "resolution_supermajority":     MappingProxyType({"type": "float", "min": 0.51, "max": 0.95}),
    "min_resolution_stake_total":   MappingProxyType({"type": "float", "min": 5.0,  "max": 500.0}),
    "resolution_loser_burn_pct":    MappingProxyType({"type": "float", "min": 0.0,  "max": 0.10}),
    "data_unavailable_threshold":   MappingProxyType({"type": "float", "min": 0.10, "max": 0.50}),
    "resolution_stalemate_burn_pct": MappingProxyType({"type": "float", "min": 0.0, "max": 0.10}),

    # ── Governance Decay ──
    "governance_decay_days":        MappingProxyType({"type": "int",   "min": 7,    "max": 365}),
    "governance_decay_factor":      MappingProxyType({"type": "float", "min": 0.10, "max": 0.99}),

    # ── Time Validity ──
    "max_future_event_drift_sec":   MappingProxyType({"type": "int",   "min": 30,   "max": 3600}),
    "phase_boundary_stale_reject":  MappingProxyType({"type": "bool"}),

    # ── Identity Rotation ──
    "rotation_blocked_during_stakes": MappingProxyType({"type": "bool"}),

    # ── Anti-Gaming ──
    "vcs_min_weight":               MappingProxyType({"type": "float", "min": 0.0,  "max": 1.0}),
    "clustering_min_weight":        MappingProxyType({"type": "float", "min": 0.0,  "max": 1.0}),
    "temporal_burst_window_sec":    MappingProxyType({"type": "int",   "min": 30,   "max": 3600}),
    "temporal_burst_min_upreps":    MappingProxyType({"type": "int",   "min": 2,    "max": 100}),
    "progressive_penalty_base":     MappingProxyType({"type": "float", "min": 0.1,  "max": 100.0}),
    "common_rep_weight_factor":     MappingProxyType({"type": "float", "min": 0.0,  "max": 1.0}),
    "progressive_penalty_threshold": MappingProxyType({"type": "float", "min": 0.0, "max": 1.0}),

    # ── Gates ──
    "gate_ratification_rep":        MappingProxyType({"type": "int",   "min": 1,    "max": 10000}),
    "gate_lock_cost_per_member":    MappingProxyType({"type": "int",   "min": 1,    "max": 1000}),
    "gate_lock_min_members":        MappingProxyType({"type": "int",   "min": 2,    "max": 1000}),
    "gate_creation_rate_limit":     MappingProxyType({"type": "int",   "min": 1,    "max": 100}),

    # ── Truth Stakes ──
    "truth_stake_min_days":         MappingProxyType({"type": "int",   "min": 1,    "max": 30}),
    "truth_stake_max_days":         MappingProxyType({"type": "int",   "min": 1,    "max": 90}),
    "truth_stake_grace_hours":      MappingProxyType({"type": "int",   "min": 1,    "max": 168}),
    "truth_stake_max_extensions":   MappingProxyType({"type": "int",   "min": 0,    "max": 10}),
    "truth_stake_tie_burn_pct":     MappingProxyType({"type": "float", "min": 0.0,  "max": 0.50}),
    "truth_stake_self_stake":       MappingProxyType({"type": "bool"}),

    # ── Dispute Resolution ──
    "dispute_window_days":          MappingProxyType({"type": "int",   "min": 1,    "max": 30}),
    "dispute_common_rep_stakeable": MappingProxyType({"type": "bool"}),

    # ── CommonCoin ──
    "monthly_mint_amount":          MappingProxyType({"type": "int",   "min": 1,    "max": 1_000_000_000}),
    "ubi_share_pct":                MappingProxyType({"type": "float", "min": 0.0,  "max": 1.0}),
    "oracle_dividend_pct":          MappingProxyType({"type": "float", "min": 0.0,  "max": 1.0}),
    "citizenship_sacrifice_cost":   MappingProxyType({"type": "int",   "min": 1,    "max": 1000}),
    "year1_max_coins_per_node":     MappingProxyType({"type": "int",   "min": 1,    "max": 1_000_000_000}),

    # ── Governance ──
    "petition_filing_cost":         MappingProxyType({"type": "int",   "min": 1,    "max": 100}),
    "petition_signature_threshold": MappingProxyType({"type": "float", "min": 0.05, "max": 0.50}),
    "petition_signature_window_days": MappingProxyType({"type": "int", "min": 1,    "max": 60}),
    "petition_vote_window_days":    MappingProxyType({"type": "int",   "min": 1,    "max": 30}),
    "petition_supermajority":       MappingProxyType({"type": "float", "min": 0.51, "max": 0.95}),
    "petition_quorum":              MappingProxyType({"type": "float", "min": 0.10, "max": 0.80}),
    "challenge_filing_cost":        MappingProxyType({"type": "int",   "min": 1,    "max": 200}),
    "challenge_window_hours":       MappingProxyType({"type": "int",   "min": 12,   "max": 168}),

    # ── Upgrade-Hash Governance ──
    "upgrade_filing_cost":          MappingProxyType({"type": "int",   "min": 1,    "max": 200}),
    "upgrade_signature_threshold":  MappingProxyType({"type": "float", "min": 0.05, "max": 0.50}),
    "upgrade_signature_window_days": MappingProxyType({"type": "int", "min": 1,    "max": 60}),
    "upgrade_vote_window_days":     MappingProxyType({"type": "int",   "min": 1,    "max": 60}),
    "upgrade_supermajority":        MappingProxyType({"type": "float", "min": 0.51, "max": 0.99}),
    "upgrade_quorum":               MappingProxyType({"type": "float", "min": 0.10, "max": 0.95}),
    "upgrade_activation_threshold": MappingProxyType({"type": "float", "min": 0.51, "max": 0.99}),
    "upgrade_activation_window_days": MappingProxyType({"type": "int", "min": 1,   "max": 90}),
    "upgrade_challenge_window_hours": MappingProxyType({"type": "int", "min": 12,  "max": 168}),

    # ── Gate Shutdown ──
    "gate_suspend_filing_cost":     MappingProxyType({"type": "int",   "min": 1,    "max": 200}),
    "gate_shutdown_filing_cost":    MappingProxyType({"type": "int",   "min": 1,    "max": 200}),
    "gate_suspend_supermajority":   MappingProxyType({"type": "float", "min": 0.51, "max": 0.95}),
    "gate_suspend_locked_supermajority": MappingProxyType({"type": "float", "min": 0.51, "max": 0.95}),
    "gate_shutdown_supermajority":  MappingProxyType({"type": "float", "min": 0.51, "max": 0.99}),
    "gate_shutdown_locked_supermajority": MappingProxyType({"type": "float", "min": 0.51, "max": 0.99}),
    "gate_shutdown_quorum":         MappingProxyType({"type": "float", "min": 0.10, "max": 0.80}),
    "gate_suspend_duration_days":   MappingProxyType({"type": "int",   "min": 1,    "max": 365}),
    "gate_shutdown_execution_delay_days": MappingProxyType({"type": "int", "min": 1, "max": 90}),
    "gate_shutdown_cooldown_days":  MappingProxyType({"type": "int",   "min": 7,    "max": 365}),
    "gate_shutdown_fail_penalty_days": MappingProxyType({"type": "int", "min": 0,   "max": 365}),
    "gate_shutdown_appeal_filing_cost": MappingProxyType({"type": "int", "min": 1, "max": 200}),
    "gate_shutdown_appeal_window_hours": MappingProxyType({"type": "int", "min": 12, "max": 168}),
    "gate_shutdown_appeal_vote_window_days": MappingProxyType({"type": "int", "min": 1, "max": 30}),
    "gate_shutdown_appeal_supermajority": MappingProxyType({"type": "float", "min": 0.51, "max": 0.95}),
    "gate_shutdown_appeal_locked_supermajority": MappingProxyType({"type": "float", "min": 0.51, "max": 0.95}),
    "gate_shutdown_appeal_quorum": MappingProxyType({"type": "float", "min": 0.10, "max": 0.80}),

    # ── Market Creation ──
    "market_creation_bond":         MappingProxyType({"type": "int",   "min": 0,    "max": 1000}),
    "market_creation_bond_return_threshold": MappingProxyType({"type": "int", "min": 1, "max": 1000}),

    # ── Bootstrap ──
    "bootstrap_market_count":       MappingProxyType({"type": "int",   "min": 0,    "max": 100000}),
    "bootstrap_evidence_bond_cost": MappingProxyType({"type": "float", "min": 0.0,  "max": 50.0}),
    "bootstrap_resolution_mode":    MappingProxyType({"type": "str", "enum": ("eligible_node_one_vote",)}),
    "bootstrap_resolution_supermajority": MappingProxyType({"type": "float", "min": 0.51, "max": 0.95}),
    "bootstrap_min_identity_age_days": MappingProxyType({"type": "int", "min": 0, "max": 365}),
    "bootstrap_pow_algorithm":      MappingProxyType({"type": "str", "enum": ("argon2id",)}),
    "bootstrap_pow_argon2id_version": MappingProxyType({"type": "int", "enum": (0x13,)}),
    "bootstrap_pow_argon2id_m":     MappingProxyType({"type": "int",   "min": 8192, "max": 1_048_576}),
    "bootstrap_pow_argon2id_t":     MappingProxyType({"type": "int",   "min": 1,    "max": 100}),
    "bootstrap_pow_argon2id_p":     MappingProxyType({"type": "int",   "min": 1,    "max": 16}),
    "bootstrap_pow_argon2id_output_len": MappingProxyType({"type": "int", "enum": (32,)}),
    "bootstrap_pow_difficulty":     MappingProxyType({"type": "int",   "min": 1,    "max": 64}),

    # ── Ramp milestones ──
    "ramp_staked_resolution_threshold": MappingProxyType({"type": "int", "min": 1, "max": 10_000_000}),
    "ramp_petitions_threshold":         MappingProxyType({"type": "int", "min": 1, "max": 10_000_000}),
    "ramp_upgrade_threshold":           MappingProxyType({"type": "int", "min": 1, "max": 10_000_000}),
    "ramp_commoncoin_threshold":        MappingProxyType({"type": "int", "min": 1, "max": 10_000_000}),
}

CONFIG_SCHEMA: MappingProxyType = MappingProxyType(_CONFIG_SCHEMA_BACKING)


# ─── Cross-field invariants ──────────────────────────────────────────────
# RULES_SKELETON.md §1.3.
# Each tuple is (left_key, op, right_key). Only ">" supported today —
# extend the dispatch in validate_cross_field_invariants when new ops
# appear in the spec.

CROSS_FIELD_INVARIANTS: tuple[tuple[str, str, str], ...] = (
    ("petition_supermajority",          ">", "petition_quorum"),
    ("resolution_supermajority",        ">", "data_unavailable_threshold"),
    ("upgrade_supermajority",           ">", "upgrade_quorum"),
    ("gate_shutdown_supermajority",     ">", "gate_shutdown_quorum"),
    ("gate_suspend_supermajority",      ">", "gate_shutdown_quorum"),
    ("farming_hard_threshold",          ">", "farming_soft_threshold"),
    ("truth_stake_max_days",            ">", "truth_stake_min_days"),
    ("upgrade_filing_cost",             ">", "petition_filing_cost"),
    # Ramp milestones must be in strict ascending order so each tier
    # genuinely activates additional capability (Sprint 8 polish
    # 2026-04-28).
    ("ramp_petitions_threshold",        ">", "ramp_staked_resolution_threshold"),
    ("ramp_upgrade_threshold",          ">", "ramp_petitions_threshold"),
    ("ramp_commoncoin_threshold",       ">", "ramp_upgrade_threshold"),
)


# ─── Validators (used by the Sprint 7 governance DSL executor) ───────────

def validate_petition_value(
    key: str,
    value: Any,
    current_config: dict[str, Any] | None = None,
) -> None:
    """Validate one (key, value) pair against ``CONFIG_SCHEMA``.

    Raises ``InvalidPetition`` on any failure. Returns ``None`` on success.

    ``current_config`` is accepted for API symmetry with the spec snippet
    in RULES §1.3 — current Sprint 1 logic doesn't need it. Future
    cross-field-aware updates may consult it.
    """
    del current_config  # deliberately unused — see docstring
    schema = CONFIG_SCHEMA.get(key)
    if schema is None:
        raise InvalidPetition(f"No schema for key: {key}")

    type_name = schema["type"]
    expected = _SCHEMA_TYPES.get(type_name)
    if expected is None:
        raise InvalidPetition(f"Schema for {key} has unknown type: {type_name}")

    if type_name == "bool":
        if not isinstance(value, bool):
            raise InvalidPetition(
                f"Type mismatch for {key}: expected bool, got {type(value).__name__}"
            )
    elif type_name == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise InvalidPetition(
                f"Type mismatch for {key}: expected int, got {type(value).__name__}"
            )
    elif type_name == "float":
        if isinstance(value, bool) or not isinstance(value, expected):
            raise InvalidPetition(
                f"Type mismatch for {key}: expected float, got {type(value).__name__}"
            )
    else:  # str
        if not isinstance(value, expected):
            raise InvalidPetition(
                f"Type mismatch for {key}: expected {type_name}, got {type(value).__name__}"
            )

    if "min" in schema and value < schema["min"]:
        raise InvalidPetition(f"{key}={value} below minimum {schema['min']}")
    if "max" in schema and value > schema["max"]:
        raise InvalidPetition(f"{key}={value} above maximum {schema['max']}")
    if "enum" in schema and value not in schema["enum"]:
        raise InvalidPetition(f"{key}={value} not in allowed values {tuple(schema['enum'])}")


def validate_cross_field_invariants(config: dict[str, Any]) -> None:
    """Check every entry of ``CROSS_FIELD_INVARIANTS`` against ``config``.

    Called by the DSL executor AFTER all updates from a single petition
    payload have been applied to a candidate config dict. Raises
    ``InvalidPetition`` on the first violation. The candidate config is
    discarded by the executor when this raises.
    """
    for left_key, op, right_key in CROSS_FIELD_INVARIANTS:
        if left_key not in config:
            raise InvalidPetition(f"Cross-field invariant references missing key: {left_key}")
        if right_key not in config:
            raise InvalidPetition(f"Cross-field invariant references missing key: {right_key}")
        left_val = config[left_key]
        right_val = config[right_key]
        if op == ">":
            if not (left_val > right_val):
                raise InvalidPetition(
                    f"Cross-field invariant violated: {left_key}={left_val} must be > "
                    f"{right_key}={right_val}"
                )
        else:
            raise InvalidPetition(f"Unknown cross-field operator: {op}")


def validate_config_schema_completeness() -> None:
    """Sprint 1 invariant: every CONFIG key has a matching CONFIG_SCHEMA entry.

    Raises ``InvalidPetition`` listing missing keys. Called both from the
    Sprint 1 adversarial test and from the DSL executor on startup.
    """
    missing = sorted(set(CONFIG.keys()) - set(CONFIG_SCHEMA.keys()))
    extra = sorted(set(CONFIG_SCHEMA.keys()) - set(CONFIG.keys()))
    if missing:
        raise InvalidPetition(f"CONFIG keys without CONFIG_SCHEMA entry: {missing}")
    if extra:
        raise InvalidPetition(f"CONFIG_SCHEMA keys without CONFIG entry: {extra}")


__all__ = [
    "CONFIG",
    "CONFIG_SCHEMA",
    "CROSS_FIELD_INVARIANTS",
    "IMMUTABLE_PRINCIPLES",
    "InvalidPetition",
    "reset_config_for_tests",
    "validate_config_schema_completeness",
    "validate_cross_field_invariants",
    "validate_petition_value",
]
