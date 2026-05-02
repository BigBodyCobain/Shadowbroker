"""Event-type registry and per-event payload validators for the Infonet
economy layer.

Source of truth: ``infonet-economy/RULES_SKELETON.md`` §4.1.

The legacy ``services/mesh/mesh_schema.py`` ships
``ACTIVE_PUBLIC_LEDGER_EVENT_TYPES`` for the existing mesh / DM / oracle
events. This module ships ``INFONET_ECONOMY_EVENT_TYPES`` — a disjoint
set of 40+ NEW event types added by the economy layer. Sprint 1's
adversarial test asserts the disjointness invariant.

Sprint 1 implements *structural* validators only — they assert payload
shape (required fields, basic types, enum membership). Deep semantic
validation (e.g. that ``probability_at_bet`` was actually computed from
the live chain state, that ``evidence_content_hash`` is canonical) lives
in later sprints alongside the modules that produce those values.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

# ─── Event-type set ──────────────────────────────────────────────────────
# RULES_SKELETON.md §4.1.
# Disjoint from mesh_schema.ACTIVE_PUBLIC_LEDGER_EVENT_TYPES — the union
# is the full public ledger surface once the adapter is wired in.

INFONET_ECONOMY_EVENT_TYPES: frozenset[str] = frozenset({
    # Reputation
    "uprep",
    "downrep",  # held off the active set in Sprint 2 — see BRAINDUMP §11
    # Markets / resolution-as-prediction
    "prediction_create",
    "prediction_place",
    "truth_stake_place",
    "truth_stake_resolve",
    "market_snapshot",
    "evidence_submit",
    "resolution_stake",
    "bootstrap_resolution_vote",
    "resolution_finalize",
    # Disputes
    "dispute_open",
    "dispute_stake",
    "dispute_resolve",
    # Gates (extend the existing legacy gate_create)
    "gate_enter",
    "gate_exit",
    "gate_lock",
    # Gate shutdown lifecycle
    "gate_suspend_file",
    "gate_suspend_vote",
    "gate_suspend_execute",
    "gate_shutdown_file",
    "gate_shutdown_vote",
    "gate_shutdown_execute",
    "gate_unsuspend",
    "gate_shutdown_appeal_file",
    "gate_shutdown_appeal_vote",
    "gate_shutdown_appeal_resolve",
    # Governance
    "petition_file",
    "petition_sign",
    "petition_vote",
    "challenge_file",
    "challenge_vote",
    "petition_execute",
    # Upgrade-hash governance
    "upgrade_propose",
    "upgrade_sign",
    "upgrade_vote",
    "upgrade_challenge",
    "upgrade_challenge_vote",
    "upgrade_signal_ready",
    "upgrade_activate",
    # Identity
    "node_register",
    "identity_rotate",
    "citizenship_claim",
    # Economy
    "coin_transfer",
    "coin_mint",
    "bounty_create",
    "bounty_claim",
    # Content
    "post_create",
    "post_reply",
})


# ─── Validator dataclass + helpers ───────────────────────────────────────

@dataclass(frozen=True)
class InfonetEventSchema:
    event_type: str
    required_fields: tuple[str, ...]
    optional_fields: tuple[str, ...]
    validate: Callable[[dict[str, Any]], tuple[bool, str]]

    def validate_payload(self, payload: dict[str, Any]) -> tuple[bool, str]:
        return self.validate(payload)


def _require(payload: dict[str, Any], fields: tuple[str, ...]) -> tuple[bool, str]:
    if not isinstance(payload, dict):
        return False, "payload must be an object"
    for key in fields:
        if key not in payload:
            return False, f"Missing field: {key}"
    return True, "ok"


def _is_nonempty_str(val: Any) -> bool:
    return isinstance(val, str) and bool(val.strip())


def _is_positive_number(val: Any) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool) and val > 0


def _is_nonnegative_number(val: Any) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool) and val >= 0


# ─── Per-event validators ───────────────────────────────────────────────
# Sprint 1 scope: structural (required fields, type sanity, enum guards).
# Deeper semantic checks (cross-event references, hash canonicalization,
# probability_at_bet reconstruction) ship in the sprint that owns the
# producing module.

def _validate_uprep(p: dict[str, Any]) -> tuple[bool, str]:
    ok, why = _require(p, ("target_node_id", "target_event_id"))
    if not ok:
        return ok, why
    if not _is_nonempty_str(p["target_node_id"]):
        return False, "target_node_id must be non-empty"
    if not _is_nonempty_str(p["target_event_id"]):
        return False, "target_event_id must be non-empty"
    return True, "ok"


def _validate_downrep(p: dict[str, Any]) -> tuple[bool, str]:
    return _validate_uprep(p)


def _validate_prediction_create(p: dict[str, Any]) -> tuple[bool, str]:
    ok, why = _require(p, ("market_id", "market_type", "question", "trigger_date", "creation_bond"))
    if not ok:
        return ok, why
    if not _is_nonempty_str(p["market_id"]):
        return False, "market_id must be non-empty"
    if p["market_type"] not in ("objective", "subjective"):
        return False, "market_type must be 'objective' or 'subjective'"
    if not _is_nonempty_str(p["question"]):
        return False, "question must be non-empty"
    if not _is_positive_number(p["trigger_date"]):
        return False, "trigger_date must be a positive timestamp"
    if not _is_nonnegative_number(p["creation_bond"]):
        return False, "creation_bond must be a non-negative number"
    return True, "ok"


def _validate_prediction_place(p: dict[str, Any]) -> tuple[bool, str]:
    ok, why = _require(p, ("market_id", "side", "probability_at_bet"))
    if not ok:
        return ok, why
    if not _is_nonempty_str(p["market_id"]):
        return False, "market_id must be non-empty"
    if p["side"] not in ("yes", "no"):
        return False, "side must be 'yes' or 'no'"
    prob = p["probability_at_bet"]
    if not isinstance(prob, (int, float)) or isinstance(prob, bool):
        return False, "probability_at_bet must be numeric"
    if not (0 <= prob <= 100):
        return False, "probability_at_bet must be in [0, 100]"
    if "stake_amount" in p:
        if p["stake_amount"] is not None and not _is_positive_number(p["stake_amount"]):
            return False, "stake_amount must be positive when present"
    return True, "ok"


def _validate_truth_stake_place(p: dict[str, Any]) -> tuple[bool, str]:
    ok, why = _require(p, ("message_id", "poster_id", "side", "amount", "duration_days"))
    if not ok:
        return ok, why
    if not _is_nonempty_str(p["message_id"]):
        return False, "message_id must be non-empty"
    if not _is_nonempty_str(p["poster_id"]):
        return False, "poster_id must be non-empty"
    if p["side"] not in ("truth", "false"):
        return False, "side must be 'truth' or 'false'"
    if not _is_positive_number(p["amount"]):
        return False, "amount must be positive"
    duration = p["duration_days"]
    if not isinstance(duration, int) or isinstance(duration, bool) or duration <= 0:
        return False, "duration_days must be a positive integer"
    return True, "ok"


def _validate_truth_stake_resolve(p: dict[str, Any]) -> tuple[bool, str]:
    ok, why = _require(p, ("message_id", "outcome"))
    if not ok:
        return ok, why
    if p["outcome"] not in ("truth", "false", "tie"):
        return False, "outcome must be 'truth', 'false', or 'tie'"
    return True, "ok"


def _validate_market_snapshot(p: dict[str, Any]) -> tuple[bool, str]:
    ok, why = _require(
        p,
        (
            "market_id",
            "frozen_participant_count",
            "frozen_total_stake",
            "frozen_predictor_ids",
            "frozen_probability_state",
            "frozen_at",
        ),
    )
    if not ok:
        return ok, why
    if not isinstance(p["frozen_participant_count"], int) or isinstance(p["frozen_participant_count"], bool):
        return False, "frozen_participant_count must be int"
    if p["frozen_participant_count"] < 0:
        return False, "frozen_participant_count must be >= 0"
    if not _is_nonnegative_number(p["frozen_total_stake"]):
        return False, "frozen_total_stake must be a non-negative number"
    if not isinstance(p["frozen_predictor_ids"], list):
        return False, "frozen_predictor_ids must be a list"
    if not all(_is_nonempty_str(x) for x in p["frozen_predictor_ids"]):
        return False, "frozen_predictor_ids entries must be non-empty strings"
    state = p["frozen_probability_state"]
    if not isinstance(state, dict) or "yes" not in state or "no" not in state:
        return False, "frozen_probability_state must be {yes, no}"
    if not _is_positive_number(p["frozen_at"]):
        return False, "frozen_at must be a positive timestamp"
    return True, "ok"


def _validate_evidence_submit(p: dict[str, Any]) -> tuple[bool, str]:
    ok, why = _require(
        p,
        (
            "market_id",
            "claimed_outcome",
            "evidence_hashes",
            "source_description",
            "evidence_content_hash",
            "submission_hash",
            "bond",
        ),
    )
    if not ok:
        return ok, why
    if p["claimed_outcome"] not in ("yes", "no"):
        return False, "claimed_outcome must be 'yes' or 'no'"
    if not isinstance(p["evidence_hashes"], list) or not p["evidence_hashes"]:
        return False, "evidence_hashes must be a non-empty list"
    if not all(_is_nonempty_str(h) for h in p["evidence_hashes"]):
        return False, "evidence_hashes entries must be non-empty strings"
    if not isinstance(p["source_description"], str):
        return False, "source_description must be a string"
    if not _is_nonempty_str(p["evidence_content_hash"]):
        return False, "evidence_content_hash must be non-empty"
    if not _is_nonempty_str(p["submission_hash"]):
        return False, "submission_hash must be non-empty"
    if not _is_nonnegative_number(p["bond"]):
        return False, "bond must be a non-negative number"
    return True, "ok"


def _validate_resolution_stake(p: dict[str, Any]) -> tuple[bool, str]:
    ok, why = _require(p, ("market_id", "side", "amount", "rep_type"))
    if not ok:
        return ok, why
    if p["side"] not in ("yes", "no", "data_unavailable"):
        return False, "side must be 'yes' | 'no' | 'data_unavailable'"
    if not _is_positive_number(p["amount"]):
        return False, "amount must be positive"
    if p["rep_type"] not in ("oracle", "common"):
        return False, "rep_type must be 'oracle' or 'common'"
    return True, "ok"


def _validate_bootstrap_resolution_vote(p: dict[str, Any]) -> tuple[bool, str]:
    ok, why = _require(p, ("market_id", "side", "pow_nonce"))
    if not ok:
        return ok, why
    if p["side"] not in ("yes", "no"):
        return False, "side must be 'yes' or 'no'"
    if not isinstance(p["pow_nonce"], int) or isinstance(p["pow_nonce"], bool) or p["pow_nonce"] < 0:
        return False, "pow_nonce must be a non-negative integer"
    return True, "ok"


def _validate_resolution_finalize(p: dict[str, Any]) -> tuple[bool, str]:
    ok, why = _require(p, ("market_id", "outcome", "is_provisional", "snapshot_event_hash"))
    if not ok:
        return ok, why
    if p["outcome"] not in ("yes", "no", "invalid"):
        return False, "outcome must be 'yes' | 'no' | 'invalid'"
    if not isinstance(p["is_provisional"], bool):
        return False, "is_provisional must be a boolean"
    if not _is_nonempty_str(p["snapshot_event_hash"]):
        return False, "snapshot_event_hash must be non-empty"
    return True, "ok"


def _validate_dispute_open(p: dict[str, Any]) -> tuple[bool, str]:
    ok, why = _require(p, ("market_id", "challenger_stake", "reason"))
    if not ok:
        return ok, why
    if not _is_positive_number(p["challenger_stake"]):
        return False, "challenger_stake must be positive"
    if not _is_nonempty_str(p["reason"]):
        return False, "reason must be non-empty"
    return True, "ok"


def _validate_dispute_stake(p: dict[str, Any]) -> tuple[bool, str]:
    ok, why = _require(p, ("dispute_id", "side", "amount", "rep_type"))
    if not ok:
        return ok, why
    if p["side"] not in ("confirm", "reverse"):
        return False, "side must be 'confirm' or 'reverse'"
    if not _is_positive_number(p["amount"]):
        return False, "amount must be positive"
    if p["rep_type"] not in ("oracle", "common"):
        return False, "rep_type must be 'oracle' or 'common'"
    return True, "ok"


def _validate_dispute_resolve(p: dict[str, Any]) -> tuple[bool, str]:
    ok, why = _require(p, ("dispute_id", "outcome"))
    if not ok:
        return ok, why
    if p["outcome"] not in ("upheld", "reversed", "tie"):
        return False, "outcome must be 'upheld' | 'reversed' | 'tie'"
    return True, "ok"


def _validate_gate_enter(p: dict[str, Any]) -> tuple[bool, str]:
    ok, why = _require(p, ("gate_id", "sacrifice_amount"))
    if not ok:
        return ok, why
    if not _is_nonempty_str(p["gate_id"]):
        return False, "gate_id must be non-empty"
    if not _is_positive_number(p["sacrifice_amount"]):
        return False, "sacrifice_amount must be positive"
    return True, "ok"


def _validate_gate_exit(p: dict[str, Any]) -> tuple[bool, str]:
    ok, why = _require(p, ("gate_id",))
    if not ok:
        return ok, why
    if not _is_nonempty_str(p["gate_id"]):
        return False, "gate_id must be non-empty"
    return True, "ok"


def _validate_gate_lock(p: dict[str, Any]) -> tuple[bool, str]:
    ok, why = _require(p, ("gate_id", "lock_cost"))
    if not ok:
        return ok, why
    if not _is_nonempty_str(p["gate_id"]):
        return False, "gate_id must be non-empty"
    if not _is_positive_number(p["lock_cost"]):
        return False, "lock_cost must be positive"
    return True, "ok"


def _validate_gate_action_petition_file(p: dict[str, Any]) -> tuple[bool, str]:
    ok, why = _require(p, ("petition_id", "gate_id", "reason", "evidence_hashes"))
    if not ok:
        return ok, why
    if not _is_nonempty_str(p["petition_id"]):
        return False, "petition_id must be non-empty"
    if not _is_nonempty_str(p["gate_id"]):
        return False, "gate_id must be non-empty"
    if not isinstance(p["reason"], str) or len(p["reason"]) > 2000:
        return False, "reason must be a string up to 2000 chars"
    if not isinstance(p["evidence_hashes"], list) or not p["evidence_hashes"]:
        return False, "evidence_hashes must be non-empty"
    if not all(_is_nonempty_str(h) for h in p["evidence_hashes"]):
        return False, "evidence_hashes entries must be non-empty strings"
    return True, "ok"


def _validate_gate_action_vote(p: dict[str, Any]) -> tuple[bool, str]:
    ok, why = _require(p, ("petition_id", "vote"))
    if not ok:
        return ok, why
    if p["vote"] not in ("for", "against"):
        return False, "vote must be 'for' or 'against'"
    return True, "ok"


def _validate_gate_action_execute(p: dict[str, Any]) -> tuple[bool, str]:
    ok, why = _require(p, ("petition_id", "gate_id"))
    if not ok:
        return ok, why
    if not _is_nonempty_str(p["petition_id"]):
        return False, "petition_id must be non-empty"
    if not _is_nonempty_str(p["gate_id"]):
        return False, "gate_id must be non-empty"
    return True, "ok"


def _validate_gate_unsuspend(p: dict[str, Any]) -> tuple[bool, str]:
    ok, why = _require(p, ("gate_id",))
    if not ok:
        return ok, why
    if not _is_nonempty_str(p["gate_id"]):
        return False, "gate_id must be non-empty"
    return True, "ok"


def _validate_gate_shutdown_appeal_file(p: dict[str, Any]) -> tuple[bool, str]:
    ok, why = _require(p, ("petition_id", "gate_id", "target_petition_id", "reason", "evidence_hashes"))
    if not ok:
        return ok, why
    if not _is_nonempty_str(p["target_petition_id"]):
        return False, "target_petition_id must be non-empty"
    if not isinstance(p["reason"], str) or len(p["reason"]) > 2000:
        return False, "reason must be a string up to 2000 chars"
    if not isinstance(p["evidence_hashes"], list) or not p["evidence_hashes"]:
        return False, "evidence_hashes must be non-empty"
    return True, "ok"


def _validate_gate_shutdown_appeal_resolve(p: dict[str, Any]) -> tuple[bool, str]:
    ok, why = _require(p, ("petition_id", "outcome"))
    if not ok:
        return ok, why
    if p["outcome"] not in ("voided_shutdown", "resumed"):
        return False, "outcome must be 'voided_shutdown' or 'resumed'"
    return True, "ok"


_VALID_PETITION_PAYLOAD_TYPES = frozenset({
    "UPDATE_PARAM",
    "BATCH_UPDATE_PARAMS",
    "ENABLE_FEATURE",
    "DISABLE_FEATURE",
})


def _validate_petition_file(p: dict[str, Any]) -> tuple[bool, str]:
    ok, why = _require(p, ("petition_id", "petition_payload"))
    if not ok:
        return ok, why
    if not _is_nonempty_str(p["petition_id"]):
        return False, "petition_id must be non-empty"
    payload = p["petition_payload"]
    if not isinstance(payload, dict) or "type" not in payload:
        return False, "petition_payload must be an object with a 'type' field"
    if payload["type"] not in _VALID_PETITION_PAYLOAD_TYPES:
        return False, f"petition_payload type must be one of {sorted(_VALID_PETITION_PAYLOAD_TYPES)}"
    # Structural shape per type. Semantic checks (key existence, bounds)
    # happen in the Sprint 7 DSL executor.
    t = payload["type"]
    if t == "UPDATE_PARAM":
        if "key" not in payload or "value" not in payload:
            return False, "UPDATE_PARAM requires key + value"
        if not _is_nonempty_str(payload["key"]):
            return False, "UPDATE_PARAM.key must be non-empty"
    elif t == "BATCH_UPDATE_PARAMS":
        if "updates" not in payload or not isinstance(payload["updates"], list) or not payload["updates"]:
            return False, "BATCH_UPDATE_PARAMS.updates must be a non-empty list"
        for u in payload["updates"]:
            if not isinstance(u, dict) or "key" not in u or "value" not in u:
                return False, "BATCH_UPDATE_PARAMS entries must be {key, value}"
            if not _is_nonempty_str(u["key"]):
                return False, "BATCH_UPDATE_PARAMS entry key must be non-empty"
    elif t in ("ENABLE_FEATURE", "DISABLE_FEATURE"):
        if "feature" not in payload or not _is_nonempty_str(payload["feature"]):
            return False, f"{t}.feature must be non-empty"
    return True, "ok"


def _validate_petition_sign(p: dict[str, Any]) -> tuple[bool, str]:
    ok, why = _require(p, ("petition_id",))
    if not ok:
        return ok, why
    if not _is_nonempty_str(p["petition_id"]):
        return False, "petition_id must be non-empty"
    return True, "ok"


def _validate_petition_vote(p: dict[str, Any]) -> tuple[bool, str]:
    ok, why = _require(p, ("petition_id", "vote"))
    if not ok:
        return ok, why
    if p["vote"] not in ("for", "against"):
        return False, "vote must be 'for' or 'against'"
    return True, "ok"


def _validate_challenge_file(p: dict[str, Any]) -> tuple[bool, str]:
    ok, why = _require(p, ("petition_id", "reason"))
    if not ok:
        return ok, why
    if not _is_nonempty_str(p["petition_id"]):
        return False, "petition_id must be non-empty"
    if not _is_nonempty_str(p["reason"]):
        return False, "reason must be non-empty"
    return True, "ok"


def _validate_challenge_vote(p: dict[str, Any]) -> tuple[bool, str]:
    ok, why = _require(p, ("petition_id", "vote"))
    if not ok:
        return ok, why
    if p["vote"] not in ("uphold", "void"):
        return False, "vote must be 'uphold' or 'void'"
    return True, "ok"


def _validate_petition_execute(p: dict[str, Any]) -> tuple[bool, str]:
    ok, why = _require(p, ("petition_id",))
    if not ok:
        return ok, why
    if not _is_nonempty_str(p["petition_id"]):
        return False, "petition_id must be non-empty"
    return True, "ok"


def _validate_upgrade_propose(p: dict[str, Any]) -> tuple[bool, str]:
    ok, why = _require(
        p,
        (
            "proposal_id",
            "release_hash",
            "release_description",
            "target_protocol_version",
        ),
    )
    if not ok:
        return ok, why
    if not _is_nonempty_str(p["proposal_id"]):
        return False, "proposal_id must be non-empty"
    if not _is_nonempty_str(p["release_hash"]):
        return False, "release_hash must be non-empty"
    if not isinstance(p["release_description"], str) or len(p["release_description"]) > 4000:
        return False, "release_description must be a string up to 4000 chars"
    if not _is_nonempty_str(p["target_protocol_version"]):
        return False, "target_protocol_version must be non-empty"
    return True, "ok"


def _validate_upgrade_sign(p: dict[str, Any]) -> tuple[bool, str]:
    ok, why = _require(p, ("proposal_id",))
    if not ok:
        return ok, why
    if not _is_nonempty_str(p["proposal_id"]):
        return False, "proposal_id must be non-empty"
    return True, "ok"


def _validate_upgrade_vote(p: dict[str, Any]) -> tuple[bool, str]:
    ok, why = _require(p, ("proposal_id", "vote"))
    if not ok:
        return ok, why
    if p["vote"] not in ("for", "against"):
        return False, "vote must be 'for' or 'against'"
    return True, "ok"


def _validate_upgrade_challenge(p: dict[str, Any]) -> tuple[bool, str]:
    return _validate_challenge_file({"petition_id": p.get("proposal_id", ""), "reason": p.get("reason", "")})


def _validate_upgrade_challenge_vote(p: dict[str, Any]) -> tuple[bool, str]:
    ok, why = _require(p, ("proposal_id", "vote"))
    if not ok:
        return ok, why
    if p["vote"] not in ("uphold", "void"):
        return False, "vote must be 'uphold' or 'void'"
    return True, "ok"


def _validate_upgrade_signal_ready(p: dict[str, Any]) -> tuple[bool, str]:
    ok, why = _require(p, ("proposal_id", "release_hash"))
    if not ok:
        return ok, why
    if not _is_nonempty_str(p["proposal_id"]):
        return False, "proposal_id must be non-empty"
    if not _is_nonempty_str(p["release_hash"]):
        return False, "release_hash must be non-empty"
    return True, "ok"


def _validate_upgrade_activate(p: dict[str, Any]) -> tuple[bool, str]:
    ok, why = _require(p, ("proposal_id", "new_protocol_version"))
    if not ok:
        return ok, why
    if not _is_nonempty_str(p["proposal_id"]):
        return False, "proposal_id must be non-empty"
    if not _is_nonempty_str(p["new_protocol_version"]):
        return False, "new_protocol_version must be non-empty"
    return True, "ok"


def _validate_node_register(p: dict[str, Any]) -> tuple[bool, str]:
    ok, why = _require(p, ("public_key", "public_key_algo", "node_class"))
    if not ok:
        return ok, why
    if not _is_nonempty_str(p["public_key"]):
        return False, "public_key must be non-empty"
    if p["public_key_algo"] not in ("ed25519", "ecdsa"):
        return False, "public_key_algo must be 'ed25519' or 'ecdsa'"
    if p["node_class"] not in ("heavy", "light"):
        return False, "node_class must be 'heavy' or 'light'"
    return True, "ok"


def _validate_identity_rotate(p: dict[str, Any]) -> tuple[bool, str]:
    ok, why = _require(
        p,
        (
            "old_node_id",
            "old_public_key",
            "old_public_key_algo",
            "new_public_key",
            "new_public_key_algo",
            "old_signature",
        ),
    )
    if not ok:
        return ok, why
    return True, "ok"


def _validate_citizenship_claim(p: dict[str, Any]) -> tuple[bool, str]:
    ok, why = _require(p, ("sacrifice_amount",))
    if not ok:
        return ok, why
    if not _is_positive_number(p["sacrifice_amount"]):
        return False, "sacrifice_amount must be positive"
    return True, "ok"


def _validate_coin_transfer(p: dict[str, Any]) -> tuple[bool, str]:
    # Sprint 1 logical-only — privacy primitives (RingCT) replace this in
    # Sprint 11+. Until then, enforce a simple {to, amount} shape.
    ok, why = _require(p, ("to_node_id", "amount"))
    if not ok:
        return ok, why
    if not _is_nonempty_str(p["to_node_id"]):
        return False, "to_node_id must be non-empty"
    if not _is_positive_number(p["amount"]):
        return False, "amount must be positive"
    return True, "ok"


def _validate_coin_mint(p: dict[str, Any]) -> tuple[bool, str]:
    ok, why = _require(p, ("month", "total_minted", "ubi_pool", "dividend_pool"))
    if not ok:
        return ok, why
    if not _is_nonempty_str(p["month"]):
        return False, "month must be non-empty (e.g. '2026-04')"
    for k in ("total_minted", "ubi_pool", "dividend_pool"):
        if not _is_nonnegative_number(p[k]):
            return False, f"{k} must be non-negative"
    return True, "ok"


def _validate_bounty_create(p: dict[str, Any]) -> tuple[bool, str]:
    ok, why = _require(p, ("bounty_id", "amount", "description"))
    if not ok:
        return ok, why
    if not _is_nonempty_str(p["bounty_id"]):
        return False, "bounty_id must be non-empty"
    if not _is_positive_number(p["amount"]):
        return False, "amount must be positive"
    if not _is_nonempty_str(p["description"]):
        return False, "description must be non-empty"
    return True, "ok"


def _validate_bounty_claim(p: dict[str, Any]) -> tuple[bool, str]:
    ok, why = _require(p, ("bounty_id",))
    if not ok:
        return ok, why
    if not _is_nonempty_str(p["bounty_id"]):
        return False, "bounty_id must be non-empty"
    return True, "ok"


def _validate_post_create(p: dict[str, Any]) -> tuple[bool, str]:
    ok, why = _require(p, ("post_id", "body"))
    if not ok:
        return ok, why
    if not _is_nonempty_str(p["post_id"]):
        return False, "post_id must be non-empty"
    if not isinstance(p["body"], str):
        return False, "body must be a string"
    return True, "ok"


def _validate_post_reply(p: dict[str, Any]) -> tuple[bool, str]:
    ok, why = _require(p, ("post_id", "parent_post_id", "body"))
    if not ok:
        return ok, why
    if not _is_nonempty_str(p["post_id"]):
        return False, "post_id must be non-empty"
    if not _is_nonempty_str(p["parent_post_id"]):
        return False, "parent_post_id must be non-empty"
    if not isinstance(p["body"], str):
        return False, "body must be a string"
    return True, "ok"


# ─── Schema registry ─────────────────────────────────────────────────────

_SCHEMA_REGISTRY: dict[str, InfonetEventSchema] = {}


def _reg(event_type: str, required: tuple[str, ...], optional: tuple[str, ...], fn) -> None:
    _SCHEMA_REGISTRY[event_type] = InfonetEventSchema(
        event_type=event_type,
        required_fields=required,
        optional_fields=optional,
        validate=fn,
    )


_reg("uprep", ("target_node_id", "target_event_id"), (), _validate_uprep)
_reg("downrep", ("target_node_id", "target_event_id"), (), _validate_downrep)

_reg("prediction_create",
     ("market_id", "market_type", "question", "trigger_date", "creation_bond"),
     (), _validate_prediction_create)
_reg("prediction_place",
     ("market_id", "side", "probability_at_bet"),
     ("stake_amount",), _validate_prediction_place)
_reg("truth_stake_place",
     ("message_id", "poster_id", "side", "amount", "duration_days"),
     (), _validate_truth_stake_place)
_reg("truth_stake_resolve",
     ("message_id", "outcome"),
     (), _validate_truth_stake_resolve)
_reg("market_snapshot",
     ("market_id", "frozen_participant_count", "frozen_total_stake",
      "frozen_predictor_ids", "frozen_probability_state", "frozen_at"),
     ("snapshot_event_hash",), _validate_market_snapshot)
_reg("evidence_submit",
     ("market_id", "claimed_outcome", "evidence_hashes", "source_description",
      "evidence_content_hash", "submission_hash", "bond"),
     (), _validate_evidence_submit)
_reg("resolution_stake",
     ("market_id", "side", "amount", "rep_type"),
     (), _validate_resolution_stake)
_reg("bootstrap_resolution_vote",
     ("market_id", "side", "pow_nonce"),
     (), _validate_bootstrap_resolution_vote)
_reg("resolution_finalize",
     ("market_id", "outcome", "is_provisional", "snapshot_event_hash"),
     (), _validate_resolution_finalize)

_reg("dispute_open", ("market_id", "challenger_stake", "reason"), (), _validate_dispute_open)
_reg("dispute_stake", ("dispute_id", "side", "amount", "rep_type"), (), _validate_dispute_stake)
_reg("dispute_resolve", ("dispute_id", "outcome"), (), _validate_dispute_resolve)

_reg("gate_enter", ("gate_id", "sacrifice_amount"), (), _validate_gate_enter)
_reg("gate_exit", ("gate_id",), (), _validate_gate_exit)
_reg("gate_lock", ("gate_id", "lock_cost"), (), _validate_gate_lock)

_reg("gate_suspend_file",
     ("petition_id", "gate_id", "reason", "evidence_hashes"), (),
     _validate_gate_action_petition_file)
_reg("gate_suspend_vote", ("petition_id", "vote"), (), _validate_gate_action_vote)
_reg("gate_suspend_execute", ("petition_id", "gate_id"), (), _validate_gate_action_execute)
_reg("gate_shutdown_file",
     ("petition_id", "gate_id", "reason", "evidence_hashes"), (),
     _validate_gate_action_petition_file)
_reg("gate_shutdown_vote", ("petition_id", "vote"), (), _validate_gate_action_vote)
_reg("gate_shutdown_execute", ("petition_id", "gate_id"), (), _validate_gate_action_execute)
_reg("gate_unsuspend", ("gate_id",), (), _validate_gate_unsuspend)
_reg("gate_shutdown_appeal_file",
     ("petition_id", "gate_id", "target_petition_id", "reason", "evidence_hashes"),
     (), _validate_gate_shutdown_appeal_file)
_reg("gate_shutdown_appeal_vote", ("petition_id", "vote"), (), _validate_gate_action_vote)
_reg("gate_shutdown_appeal_resolve", ("petition_id", "outcome"), (), _validate_gate_shutdown_appeal_resolve)

_reg("petition_file", ("petition_id", "petition_payload"), (), _validate_petition_file)
_reg("petition_sign", ("petition_id",), (), _validate_petition_sign)
_reg("petition_vote", ("petition_id", "vote"), (), _validate_petition_vote)
_reg("challenge_file", ("petition_id", "reason"), (), _validate_challenge_file)
_reg("challenge_vote", ("petition_id", "vote"), (), _validate_challenge_vote)
_reg("petition_execute", ("petition_id",), (), _validate_petition_execute)

_reg("upgrade_propose",
     ("proposal_id", "release_hash", "release_description", "target_protocol_version"),
     ("release_url", "compatibility_notes"),
     _validate_upgrade_propose)
_reg("upgrade_sign", ("proposal_id",), (), _validate_upgrade_sign)
_reg("upgrade_vote", ("proposal_id", "vote"), (), _validate_upgrade_vote)
_reg("upgrade_challenge", ("proposal_id", "reason"), (), _validate_upgrade_challenge)
_reg("upgrade_challenge_vote", ("proposal_id", "vote"), (), _validate_upgrade_challenge_vote)
_reg("upgrade_signal_ready", ("proposal_id", "release_hash"), (), _validate_upgrade_signal_ready)
_reg("upgrade_activate", ("proposal_id", "new_protocol_version"), (), _validate_upgrade_activate)

_reg("node_register", ("public_key", "public_key_algo", "node_class"), (), _validate_node_register)
_reg("identity_rotate",
     ("old_node_id", "old_public_key", "old_public_key_algo",
      "new_public_key", "new_public_key_algo", "old_signature"),
     (), _validate_identity_rotate)
_reg("citizenship_claim", ("sacrifice_amount",), (), _validate_citizenship_claim)

_reg("coin_transfer", ("to_node_id", "amount"), (), _validate_coin_transfer)
_reg("coin_mint", ("month", "total_minted", "ubi_pool", "dividend_pool"), (), _validate_coin_mint)
_reg("bounty_create", ("bounty_id", "amount", "description"), (), _validate_bounty_create)
_reg("bounty_claim", ("bounty_id",), (), _validate_bounty_claim)

_reg("post_create", ("post_id", "body"), (), _validate_post_create)
_reg("post_reply", ("post_id", "parent_post_id", "body"), (), _validate_post_reply)


def get_infonet_schema(event_type: str) -> InfonetEventSchema | None:
    return _SCHEMA_REGISTRY.get(event_type)


def validate_infonet_event_payload(
    event_type: str,
    payload: dict[str, Any],
) -> tuple[bool, str]:
    """Validate ``payload`` against the schema for ``event_type``.

    Sprint 1 contract:
    - Event types not in ``INFONET_ECONOMY_EVENT_TYPES`` are rejected.
    - Every type in ``INFONET_ECONOMY_EVENT_TYPES`` MUST have a registered
      validator (asserted by ``assert_registry_complete``).
    """
    if event_type not in INFONET_ECONOMY_EVENT_TYPES:
        return False, f"Unknown event_type for infonet economy: {event_type}"
    schema = _SCHEMA_REGISTRY.get(event_type)
    if schema is None:
        return False, f"No validator registered for: {event_type}"
    return schema.validate_payload(payload)


def assert_registry_complete() -> None:
    """Sprint 1 invariant: every event type has a validator."""
    missing = sorted(INFONET_ECONOMY_EVENT_TYPES - set(_SCHEMA_REGISTRY.keys()))
    if missing:
        raise AssertionError(f"INFONET_ECONOMY_EVENT_TYPES without validators: {missing}")


__all__ = [
    "INFONET_ECONOMY_EVENT_TYPES",
    "InfonetEventSchema",
    "assert_registry_complete",
    "get_infonet_schema",
    "validate_infonet_event_payload",
]
