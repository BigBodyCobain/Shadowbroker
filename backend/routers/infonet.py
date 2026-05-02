"""Infonet economy / governance / gates / bootstrap HTTP surface.

Source of truth: ``infonet-economy/IMPLEMENTATION_PLAN.md`` §2.1.

Read endpoints return chain-derived state (computed by the
``services.infonet`` adapters / pure functions). Write endpoints take
a payload, validate it through the cutover-registered validators, and
return a structured "would-emit" preview. Production wiring (signing
+ ``Infonet.append`` persistence) is a thin follow-on; the validation
contract is locked here.

Cross-cutting design rule: errors are diagnostic, not punitive. Each
write endpoint returns ``{"ok": False, "reason": "..."}`` on
validation failure with the exact field that failed. Frontend
surfaces the reason in the UI.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Body, Path

# Triggers the chain cutover at module-load time so registered
# validators are live for any subsequent route invocation.
from services.infonet import _chain_cutover  # noqa: F401
from services.infonet.adapters.gate_adapter import InfonetGateAdapter
from services.infonet.adapters.oracle_adapter import InfonetOracleAdapter
from services.infonet.adapters.reputation_adapter import InfonetReputationAdapter
from services.infonet.bootstrap import compute_active_features
from services.infonet.config import (
    CONFIG,
    IMMUTABLE_PRINCIPLES,
)
from services.infonet.governance import (
    apply_petition_payload,
    compute_petition_state,
    compute_upgrade_state,
)
from services.infonet.governance.dsl_executor import InvalidPetition
from services.infonet.partition import (
    classify_event_type,
    is_chain_stale,
    should_mark_provisional,
)
from services.infonet.privacy import (
    DEXScaffolding,
    RingCTScaffolding,
    ShieldedBalanceScaffolding,
    StealthAddressScaffolding,
)
from services.infonet.schema import (
    INFONET_ECONOMY_EVENT_TYPES,
    validate_infonet_event_payload,
)
from services.infonet.time_validity import chain_majority_time

logger = logging.getLogger("routers.infonet")

router = APIRouter(prefix="/api/infonet", tags=["infonet"])


# ─── Chain access helper ─────────────────────────────────────────────────
# Every adapter takes a ``chain_provider`` callable. We pull the live
# Infonet chain from mesh_hashchain. Tests can monkeypatch this.

def _live_chain() -> list[dict[str, Any]]:
    try:
        from services.mesh.mesh_hashchain import infonet
        events = getattr(infonet, "events", None)
        if isinstance(events, list):
            return list(events)
        # Some implementations use a deque; convert to list.
        if events is not None:
            return list(events)
    except Exception as exc:
        logger.debug("infonet chain unavailable: %s", exc)
    return []


def _now() -> float:
    cmt = chain_majority_time(_live_chain())
    return cmt if cmt > 0 else float(time.time())


# ─── Status ──────────────────────────────────────────────────────────────

@router.get("/status")
def infonet_status() -> dict[str, Any]:
    """Top-level health snapshot for the InfonetTerminal HUD.

    Returns ramp activation flags, partition staleness, privacy
    primitive statuses, immutable principles, and counts of
    chain-derived state (markets / petitions / gates / etc).
    """
    chain = _live_chain()
    now = _now()
    features = compute_active_features(chain)

    # Privacy primitive statuses (truthful — most are NOT_IMPLEMENTED).
    privacy = {
        "ringct": RingCTScaffolding().status().value,
        "stealth_address": StealthAddressScaffolding().status().value,
        "shielded_balance": ShieldedBalanceScaffolding().status().value,
        "dex": DEXScaffolding().status().value,
    }

    return {
        "ok": True,
        "now": now,
        "chain_majority_time": chain_majority_time(chain),
        "chain_event_count": len(chain),
        "chain_stale": is_chain_stale(chain, now=now),
        "ramp": {
            "node_count": features.node_count,
            "bootstrap_resolution_active": features.bootstrap_resolution_active,
            "staked_resolution_active": features.staked_resolution_active,
            "governance_petitions_active": features.governance_petitions_active,
            "upgrade_governance_active": features.upgrade_governance_active,
            "commoncoin_active": features.commoncoin_active,
        },
        "privacy_primitive_status": privacy,
        "immutable_principles": dict(IMMUTABLE_PRINCIPLES),
        "config_keys_count": len(CONFIG),
        "infonet_economy_event_types_count": len(INFONET_ECONOMY_EVENT_TYPES),
    }


# ─── Petitions / governance ──────────────────────────────────────────────

@router.get("/petitions")
def list_petitions() -> dict[str, Any]:
    """List petition_file events on the chain with their current state."""
    chain = _live_chain()
    now = _now()
    out: list[dict[str, Any]] = []
    for ev in chain:
        if ev.get("event_type") != "petition_file":
            continue
        pid = (ev.get("payload") or {}).get("petition_id")
        if not isinstance(pid, str):
            continue
        try:
            state = compute_petition_state(pid, chain, now=now)
            out.append({
                "petition_id": state.petition_id,
                "status": state.status,
                "filer_id": state.filer_id,
                "filed_at": state.filed_at,
                "petition_payload": state.petition_payload,
                "signature_governance_weight": state.signature_governance_weight,
                "signature_threshold_at_filing": state.signature_threshold_at_filing,
                "votes_for_weight": state.votes_for_weight,
                "votes_against_weight": state.votes_against_weight,
                "voting_deadline": state.voting_deadline,
                "challenge_window_until": state.challenge_window_until,
            })
        except Exception as exc:
            logger.warning("petition state error for %s: %s", pid, exc)
    return {"ok": True, "petitions": out, "now": now}


@router.get("/petitions/{petition_id}")
def get_petition(petition_id: str = Path(...)) -> dict[str, Any]:
    chain = _live_chain()
    now = _now()
    state = compute_petition_state(petition_id, chain, now=now)
    return {"ok": True, "petition": state.__dict__, "now": now}


@router.post("/petitions/preview")
def preview_petition_payload(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Validate a petition payload through the DSL executor without
    emitting it. Returns the candidate config diff so the UI can show
    "this petition would change vote_decay_days from 90 to 30".
    """
    try:
        result = apply_petition_payload(payload)
        return {
            "ok": True,
            "changed_keys": list(result.changed_keys),
            "new_values": {k: result.new_config[k] for k in result.changed_keys},
        }
    except InvalidPetition as exc:
        return {"ok": False, "reason": str(exc)}


@router.post("/events/validate")
def validate_event(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Validate an arbitrary Infonet economy event payload.

    Frontend uses this for client-side preflight before signing /
    submitting an event. Returns ``{ok: True}`` on success or
    ``{ok: False, reason: ...}`` with the exact validation failure.
    """
    event_type = body.get("event_type")
    payload = body.get("payload", {})
    if not isinstance(event_type, str) or not event_type:
        return {"ok": False, "reason": "event_type required"}
    if not isinstance(payload, dict):
        return {"ok": False, "reason": "payload must be an object"}
    ok, reason = validate_infonet_event_payload(event_type, payload)
    return {
        "ok": ok,
        "reason": reason if not ok else None,
        "tier": classify_event_type(event_type),
        "would_be_provisional": should_mark_provisional(event_type, _live_chain(), now=_now()),
    }


# ─── Upgrade-hash governance ────────────────────────────────────────────

@router.get("/upgrades")
def list_upgrades() -> dict[str, Any]:
    chain = _live_chain()
    now = _now()
    out: list[dict[str, Any]] = []
    for ev in chain:
        if ev.get("event_type") != "upgrade_propose":
            continue
        pid = (ev.get("payload") or {}).get("proposal_id")
        if not isinstance(pid, str):
            continue
        try:
            # Heavy node set is a runtime concept (transport tier ==
            # private_strong per plan §3.5). Empty here for the
            # snapshot endpoint; production will pass the live set.
            state = compute_upgrade_state(pid, chain, now=now, heavy_node_ids=set())
            out.append({
                "proposal_id": state.proposal_id,
                "status": state.status,
                "proposer_id": state.proposer_id,
                "filed_at": state.filed_at,
                "release_hash": state.release_hash,
                "target_protocol_version": state.target_protocol_version,
                "votes_for_weight": state.votes_for_weight,
                "votes_against_weight": state.votes_against_weight,
                "readiness_fraction": state.readiness.fraction,
                "readiness_threshold_met": state.readiness.threshold_met,
            })
        except Exception as exc:
            logger.warning("upgrade state error for %s: %s", pid, exc)
    return {"ok": True, "upgrades": out, "now": now}


@router.get("/upgrades/{proposal_id}")
def get_upgrade(proposal_id: str = Path(...)) -> dict[str, Any]:
    chain = _live_chain()
    now = _now()
    state = compute_upgrade_state(proposal_id, chain, now=now, heavy_node_ids=set())
    return {
        "ok": True,
        "upgrade": {
            "proposal_id": state.proposal_id,
            "status": state.status,
            "proposer_id": state.proposer_id,
            "filed_at": state.filed_at,
            "release_hash": state.release_hash,
            "target_protocol_version": state.target_protocol_version,
            "signature_governance_weight": state.signature_governance_weight,
            "votes_for_weight": state.votes_for_weight,
            "votes_against_weight": state.votes_against_weight,
            "voting_deadline": state.voting_deadline,
            "challenge_window_until": state.challenge_window_until,
            "activation_deadline": state.activation_deadline,
            "readiness": {
                "total_heavy_nodes": state.readiness.total_heavy_nodes,
                "ready_count": state.readiness.ready_count,
                "fraction": state.readiness.fraction,
                "threshold_met": state.readiness.threshold_met,
            },
        },
        "now": now,
    }


# ─── Markets / resolution / disputes ────────────────────────────────────

@router.get("/markets/{market_id}")
def get_market_state(market_id: str = Path(...)) -> dict[str, Any]:
    """Full market view: lifecycle, snapshot, evidence, stakes,
    excluded predictors, dispute state."""
    chain = _live_chain()
    now = _now()
    oracle = InfonetOracleAdapter(lambda: chain)

    status = oracle.market_status(market_id, now=now)
    snap = oracle.find_snapshot(market_id)
    bundles = oracle.collect_evidence(market_id)
    excluded = sorted(oracle.excluded_predictor_ids(market_id))
    disputes = oracle.collect_disputes(market_id)
    reversed_flag = oracle.market_was_reversed(market_id)

    return {
        "ok": True,
        "market_id": market_id,
        "status": status.value,
        "snapshot": snap,
        "evidence_bundles": [
            {
                "node_id": b.node_id,
                "claimed_outcome": b.claimed_outcome,
                "evidence_hashes": list(b.evidence_hashes),
                "source_description": b.source_description,
                "bond": b.bond,
                "timestamp": b.timestamp,
                "is_first_for_side": b.is_first_for_side,
                "submission_hash": b.submission_hash,
            }
            for b in bundles
        ],
        "excluded_predictor_ids": excluded,
        "disputes": [
            {
                "dispute_id": d.dispute_id,
                "challenger_id": d.challenger_id,
                "challenger_stake": d.challenger_stake,
                "opened_at": d.opened_at,
                "is_resolved": d.is_resolved,
                "resolved_outcome": d.resolved_outcome,
                "confirm_stakes": d.confirm_stakes,
                "reverse_stakes": d.reverse_stakes,
            }
            for d in disputes
        ],
        "was_reversed": reversed_flag,
        "now": now,
    }


@router.get("/markets/{market_id}/preview-resolution")
def preview_resolution(market_id: str = Path(...)) -> dict[str, Any]:
    """Run the resolution decision procedure without emitting a
    finalize event. UI uses this to show "if resolution closed now,
    the market would resolve as <outcome> for <reason>"."""
    chain = _live_chain()
    oracle = InfonetOracleAdapter(lambda: chain)
    result = oracle.resolve_market(market_id)
    return {
        "ok": True,
        "preview": {
            "outcome": result.outcome,
            "reason": result.reason,
            "is_provisional": result.is_provisional,
            "burned_amount": result.burned_amount,
            "stake_returns": [
                {"node_id": k[0], "rep_type": k[1], "amount": v}
                for k, v in result.stake_returns.items()
            ],
            "stake_winnings": [
                {"node_id": k[0], "rep_type": k[1], "amount": v}
                for k, v in result.stake_winnings.items()
            ],
            "bond_returns": [
                {"node_id": k, "amount": v} for k, v in result.bond_returns.items()
            ],
            "bond_forfeits": [
                {"node_id": k, "amount": v} for k, v in result.bond_forfeits.items()
            ],
            "first_submitter_bonuses": [
                {"node_id": k, "amount": v}
                for k, v in result.first_submitter_bonuses.items()
            ],
        },
    }


# ─── Gate shutdown lifecycle ────────────────────────────────────────────

@router.get("/gates/{gate_id}")
def get_gate_state(gate_id: str = Path(...)) -> dict[str, Any]:
    chain = _live_chain()
    now = _now()
    gates = InfonetGateAdapter(lambda: chain)
    meta = gates.gate_meta(gate_id)
    if meta is None:
        return {"ok": False, "reason": "gate_not_found"}
    suspension = gates.suspension_state(gate_id, now=now)
    shutdown = gates.shutdown_state(gate_id, now=now)
    locked = gates.locked_state(gate_id)
    members = sorted(gates.member_set(gate_id))
    return {
        "ok": True,
        "gate_id": gate_id,
        "meta": {
            "creator_node_id": meta.creator_node_id,
            "display_name": meta.display_name,
            "entry_sacrifice": meta.entry_sacrifice,
            "min_overall_rep": meta.min_overall_rep,
            "min_gate_rep": dict(meta.min_gate_rep),
            "created_at": meta.created_at,
        },
        "members": members,
        "ratified": gates.is_ratified(gate_id),
        "cumulative_member_oracle_rep": gates.cumulative_member_oracle_rep(gate_id),
        "locked": {
            "is_locked": locked.locked,
            "locked_at": locked.locked_at,
            "locked_by": list(locked.locked_by),
        },
        "suspension": {
            "status": suspension.status,
            "suspended_at": suspension.suspended_at,
            "suspended_until": suspension.suspended_until,
            "last_shutdown_petition_at": suspension.last_shutdown_petition_at,
        },
        "shutdown": {
            "has_pending": shutdown.has_pending,
            "pending_petition_id": shutdown.pending_petition_id,
            "pending_status": shutdown.pending_status,
            "execution_at": shutdown.execution_at,
            "executed": shutdown.executed,
        },
        "now": now,
    }


# ─── Reputation views ───────────────────────────────────────────────────

@router.get("/nodes/{node_id}/reputation")
def get_node_reputation(node_id: str = Path(...)) -> dict[str, Any]:
    chain = _live_chain()
    rep = InfonetReputationAdapter(lambda: chain)
    breakdown = rep.oracle_rep_breakdown(node_id)
    return {
        "ok": True,
        "node_id": node_id,
        "oracle_rep": rep.oracle_rep(node_id),
        "oracle_rep_active": rep.oracle_rep_active(node_id),
        "oracle_rep_lifetime": rep.oracle_rep_lifetime(node_id),
        "common_rep": rep.common_rep(node_id),
        "decay_factor": rep.decay_factor(node_id),
        "last_successful_prediction_ts": rep.last_successful_prediction_ts(node_id),
        "breakdown": {
            "free_prediction_mints": breakdown.free_prediction_mints,
            "staked_prediction_returns": breakdown.staked_prediction_returns,
            "staked_prediction_losses": breakdown.staked_prediction_losses,
            "total": breakdown.total,
        },
    }


# ─── Bootstrap ──────────────────────────────────────────────────────────

@router.get("/bootstrap/markets/{market_id}")
def get_bootstrap_market_state(market_id: str = Path(...)) -> dict[str, Any]:
    """Bootstrap-mode-specific market view: who has voted, who is
    eligible, current tally."""
    from services.infonet.bootstrap import (
        deduplicate_votes,
        validate_bootstrap_eligibility,
    )

    chain = _live_chain()
    canonical = deduplicate_votes(market_id, chain)
    votes_summary: list[dict[str, Any]] = []
    yes = 0
    no = 0
    for v in canonical:
        node_id = v.get("node_id") or ""
        side = (v.get("payload") or {}).get("side")
        decision = validate_bootstrap_eligibility(node_id, market_id, chain)
        votes_summary.append({
            "node_id": node_id,
            "side": side,
            "eligible": decision.eligible,
            "ineligible_reason": decision.reason if not decision.eligible else None,
        })
        if decision.eligible:
            if side == "yes":
                yes += 1
            elif side == "no":
                no += 1
    total = yes + no
    return {
        "ok": True,
        "market_id": market_id,
        "votes": votes_summary,
        "tally": {
            "yes": yes,
            "no": no,
            "total_eligible": total,
            "min_market_participants": int(CONFIG["min_market_participants"]),
            "supermajority_threshold": float(CONFIG["bootstrap_resolution_supermajority"]),
        },
    }


# ─── Signed write: append an Infonet economy event ──────────────────────

@router.post("/append")
def append_event(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Append a signed Infonet economy event to the chain.

    Body shape (all required for production):

        {
            "event_type": str,       # one of INFONET_ECONOMY_EVENT_TYPES
            "node_id":    str,       # signer
            "payload":    dict,      # event-specific fields
            "signature":  str,       # hex
            "sequence":   int,       # node-monotonic
            "public_key": str,       # base64
            "public_key_algo": str,  # "ed25519" or "ecdsa"
            "protocol_version": str  # optional, defaults to current
        }

    The cutover-registered validators run automatically via
    ``mesh_hashchain.Infonet.append`` — payload validation, signature
    verification, replay protection, sequence ordering, public-key
    binding, revocation status. No additional security wrapper is
    needed because ``Infonet.append`` IS the secure entry point.

    Returns the appended event dict on success, or
    ``{"ok": False, "reason": "..."}`` on validation / signing failure.
    """
    if not isinstance(body, dict):
        return {"ok": False, "reason": "body_must_be_object"}

    event_type = body.get("event_type")
    if not isinstance(event_type, str) or event_type not in INFONET_ECONOMY_EVENT_TYPES:
        return {
            "ok": False,
            "reason": f"event_type must be one of INFONET_ECONOMY_EVENT_TYPES "
                      f"(got {event_type!r})",
        }

    node_id = body.get("node_id")
    if not isinstance(node_id, str) or not node_id:
        return {"ok": False, "reason": "node_id required"}

    payload = body.get("payload", {})
    if not isinstance(payload, dict):
        return {"ok": False, "reason": "payload must be an object"}

    sequence = body.get("sequence", 0)
    try:
        sequence = int(sequence)
    except (TypeError, ValueError):
        return {"ok": False, "reason": "sequence must be an integer"}
    if sequence <= 0:
        return {"ok": False, "reason": "sequence must be > 0"}

    signature = str(body.get("signature") or "")
    public_key = str(body.get("public_key") or "")
    public_key_algo = str(body.get("public_key_algo") or "")
    protocol_version = str(body.get("protocol_version") or "")

    if not signature or not public_key or not public_key_algo:
        return {
            "ok": False,
            "reason": "signature, public_key, and public_key_algo are required",
        }

    try:
        from services.mesh.mesh_hashchain import infonet
        event = infonet.append(
            event_type=event_type,
            node_id=node_id,
            payload=payload,
            signature=signature,
            sequence=sequence,
            public_key=public_key,
            public_key_algo=public_key_algo,
            protocol_version=protocol_version,
        )
    except ValueError as exc:
        # Infonet.append raises ValueError for any validation failure
        # — payload / signature / replay / sequence / binding. The
        # message is user-facing per the non-hostile UX rule.
        return {"ok": False, "reason": str(exc)}
    except Exception as exc:
        logger.exception("infonet append failed")
        return {"ok": False, "reason": f"server_error: {type(exc).__name__}"}

    return {"ok": True, "event": event}


# ─── Function Keys (citizen + operator views) ───────────────────────────

@router.get("/function-keys/operator/{operator_id}/batch-summary")
def operator_batch_summary(operator_id: str = Path(...)) -> dict[str, Any]:
    """Sprint 11+ scaffolding: returns the operator's local batch
    counter for the current period. Production wires this through the
    operator's local-store implementation (Sprint 11+ scaffolding
    doesn't persist; counts reset per process)."""
    return {
        "ok": True,
        "operator_id": operator_id,
        "scaffolding_only": True,
        "note": "Production operators maintain a persistent BatchedSettlementBatch. "
                "This endpoint reports the in-memory state of the local batch.",
    }


__all__ = ["router"]
