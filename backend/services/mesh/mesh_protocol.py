"""Mesh protocol helpers for canonical payloads and versioning."""

from __future__ import annotations

import hashlib
from typing import Any
PROTOCOL_VERSION = "infonet/2"
NETWORK_ID = "sb-testnet-0"
SIGNED_CONTEXT_PROTOCOL = "shadowbroker"
SIGNED_CONTEXT_VERSION = 1
SIGNED_CONTEXT_FIELD = "signed_context"


def _safe_int(val, default=0):
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _normalize_signed_context(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    normalized = {
        "protocol": str(value.get("protocol", "") or ""),
        "version": _safe_int(value.get("version", 0), 0),
        "event_type": str(value.get("event_type", "") or ""),
        "kind": str(value.get("kind", "") or ""),
        "endpoint": str(value.get("endpoint", "") or ""),
        "lane_floor": str(value.get("lane_floor", "") or "").strip().lower(),
        "sequence_domain": str(value.get("sequence_domain", "") or ""),
        "node_id": str(value.get("node_id", "") or ""),
        "sequence": _safe_int(value.get("sequence", 0), 0),
        "body_hash": str(value.get("body_hash", "") or "").strip().lower(),
    }
    gate_id = str(value.get("gate_id", "") or "").strip().lower()
    if gate_id:
        normalized["gate_id"] = gate_id
    recipient_id = str(value.get("recipient_id", "") or "").strip()
    if recipient_id:
        normalized["recipient_id"] = recipient_id
    target_id = str(value.get("target_id", "") or "").strip()
    if target_id:
        normalized["target_id"] = target_id
    return normalized


def _copy_signed_context(normalized: dict[str, Any], payload: dict[str, Any]) -> None:
    signed_context = _normalize_signed_context(payload.get(SIGNED_CONTEXT_FIELD))
    if signed_context:
        normalized[SIGNED_CONTEXT_FIELD] = signed_context


def _normalize_number(value: Any) -> int | float:
    try:
        num = float(value)
    except Exception:
        return 0
    if num.is_integer():
        return int(num)
    return num


def payload_body_hash(event_type: str, payload: dict[str, Any]) -> str:
    """Return a SHA-256 hash of the normalized payload without signed_context."""
    from services.mesh.mesh_crypto import canonical_json

    base_payload = dict(payload or {})
    base_payload.pop(SIGNED_CONTEXT_FIELD, None)
    normalized = normalize_payload(event_type, base_payload)
    normalized.pop(SIGNED_CONTEXT_FIELD, None)
    return hashlib.sha256(canonical_json(normalized).encode("utf-8")).hexdigest()


def build_signed_context(
    *,
    event_type: str,
    kind: str,
    endpoint: str,
    lane_floor: str,
    sequence_domain: str,
    node_id: str,
    sequence: int,
    payload: dict[str, Any],
    gate_id: str = "",
    recipient_id: str = "",
    target_id: str = "",
) -> dict[str, Any]:
    context = {
        "protocol": SIGNED_CONTEXT_PROTOCOL,
        "version": SIGNED_CONTEXT_VERSION,
        "event_type": str(event_type or ""),
        "kind": str(kind or ""),
        "endpoint": str(endpoint or ""),
        "lane_floor": str(lane_floor or "").strip().lower(),
        "sequence_domain": str(sequence_domain or ""),
        "node_id": str(node_id or ""),
        "sequence": _safe_int(sequence, 0),
        "body_hash": payload_body_hash(event_type, payload),
    }
    if gate_id:
        context["gate_id"] = str(gate_id).strip().lower()
    if recipient_id:
        context["recipient_id"] = str(recipient_id).strip()
    if target_id:
        context["target_id"] = str(target_id).strip()
    return context


def validate_signed_context(
    *,
    event_type: str,
    kind: str,
    endpoint: str,
    lane_floor: str,
    sequence_domain: str,
    node_id: str,
    sequence: int,
    payload: dict[str, Any],
    gate_id: str = "",
    recipient_id: str = "",
    target_id: str = "",
) -> tuple[bool, str]:
    supplied = _normalize_signed_context((payload or {}).get(SIGNED_CONTEXT_FIELD))
    if not supplied:
        return True, "signed_context_absent"
    expected = build_signed_context(
        event_type=event_type,
        kind=kind,
        endpoint=endpoint,
        lane_floor=lane_floor,
        sequence_domain=sequence_domain,
        node_id=node_id,
        sequence=sequence,
        payload=payload,
        gate_id=gate_id,
        recipient_id=recipient_id,
        target_id=target_id,
    )
    if supplied != expected:
        return False, "signed_context_mismatch"
    return True, "signed_context_ok"


def normalize_message_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        "message": str(payload.get("message", "")),
        "destination": str(payload.get("destination", "")),
        "channel": str(payload.get("channel", "LongFast")),
        "priority": str(payload.get("priority", "normal")),
        "ephemeral": bool(payload.get("ephemeral", False)),
    }
    transport_lock = str(payload.get("transport_lock", "") or "").strip().lower()
    if transport_lock:
        normalized["transport_lock"] = transport_lock
    _copy_signed_context(normalized, payload)
    return normalized


def normalize_gate_message_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        "gate": str(payload.get("gate", "")).strip().lower(),
        "ciphertext": str(payload.get("ciphertext", "")),
        "nonce": str(payload.get("nonce", payload.get("iv", ""))),
        "sender_ref": str(payload.get("sender_ref", "")),
        "format": str(payload.get("format", "mls1") or "mls1").strip().lower(),
    }
    epoch = _safe_int(payload.get("epoch", 0), 0)
    if epoch > 0:
        normalized["epoch"] = epoch
    # gate_envelope carries cross-node decryptable ciphertext — preserve it
    # on-chain so receiving nodes can decrypt without MLS key exchange.
    gate_envelope = str(payload.get("gate_envelope", "") or "").strip()
    if gate_envelope:
        normalized["gate_envelope"] = gate_envelope
    # envelope_hash binds gate_envelope to the signed payload (SHA-256 hex).
    envelope_hash = str(payload.get("envelope_hash", "") or "").strip()
    if envelope_hash:
        normalized["envelope_hash"] = envelope_hash
    # reply_to is a display-only parent message reference.
    reply_to = str(payload.get("reply_to", "") or "").strip()
    if reply_to:
        normalized["reply_to"] = reply_to
    transport_lock = str(payload.get("transport_lock", "") or "").strip().lower()
    if transport_lock:
        normalized["transport_lock"] = transport_lock
    _copy_signed_context(normalized, payload)
    return normalized


def normalize_vote_payload(payload: dict[str, Any]) -> dict[str, Any]:
    vote_val = _safe_int(payload.get("vote", 0), 0)
    normalized = {
        "target_id": str(payload.get("target_id", "")),
        "vote": vote_val,
        "gate": str(payload.get("gate", "")),
    }
    _copy_signed_context(normalized, payload)
    return normalized


def normalize_gate_create_payload(payload: dict[str, Any]) -> dict[str, Any]:
    rules = payload.get("rules", {})
    if not isinstance(rules, dict):
        rules = {}
    normalized = {
        "gate_id": str(payload.get("gate_id", "")).lower(),
        "display_name": str(payload.get("display_name", ""))[:64],
        "rules": rules,
    }
    _copy_signed_context(normalized, payload)
    return normalized


def normalize_prediction_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "market_title": str(payload.get("market_title", "")),
        "side": str(payload.get("side", "")),
        "stake_amount": _normalize_number(payload.get("stake_amount", 0.0)),
    }


def normalize_stake_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "message_id": str(payload.get("message_id", "")),
        "poster_id": str(payload.get("poster_id", "")),
        "side": str(payload.get("side", "")),
        "amount": _normalize_number(payload.get("amount", 0.0)),
        "duration_days": _safe_int(payload.get("duration_days", 0), 0),
    }


def normalize_dm_key_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        "dh_pub_key": str(payload.get("dh_pub_key", "")),
        "dh_algo": str(payload.get("dh_algo", "")),
        "timestamp": _safe_int(payload.get("timestamp", 0), 0),
    }
    transport_lock = str(payload.get("transport_lock", "") or "").strip().lower()
    if transport_lock:
        normalized["transport_lock"] = transport_lock
    _copy_signed_context(normalized, payload)
    return normalized


def normalize_dm_message_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        "recipient_id": str(payload.get("recipient_id", "")),
        "delivery_class": str(payload.get("delivery_class", "")).lower(),
        "recipient_token": str(payload.get("recipient_token", "")),
        "ciphertext": str(payload.get("ciphertext", "")),
        "msg_id": str(payload.get("msg_id", "")),
        "timestamp": _safe_int(payload.get("timestamp", 0), 0),
        "format": str(payload.get("format", "dm1") or "dm1").strip().lower(),
    }
    session_welcome = payload.get("session_welcome")
    if session_welcome:
        normalized["session_welcome"] = str(session_welcome)
    sender_seal = str(payload.get("sender_seal", "") or "")
    if sender_seal:
        normalized["sender_seal"] = sender_seal
    relay_salt = str(payload.get("relay_salt", "") or "").strip().lower()
    if relay_salt:
        normalized["relay_salt"] = relay_salt
    transport_lock = str(payload.get("transport_lock", "") or "").strip().lower()
    if transport_lock:
        normalized["transport_lock"] = transport_lock
    _copy_signed_context(normalized, payload)
    return normalized


def normalize_dm_message_payload_legacy(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "recipient_id": str(payload.get("recipient_id", "")),
        "delivery_class": str(payload.get("delivery_class", "")).lower(),
        "recipient_token": str(payload.get("recipient_token", "")),
        "ciphertext": str(payload.get("ciphertext", "")),
        "msg_id": str(payload.get("msg_id", "")),
        "timestamp": _safe_int(payload.get("timestamp", 0), 0),
    }


def normalize_mailbox_claims(payload: dict[str, Any]) -> list[dict[str, str]]:
    claims = payload.get("mailbox_claims", [])
    if not isinstance(claims, list):
        return []
    normalized: list[dict[str, str]] = []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        normalized.append(
            {
                "type": str(claim.get("type", "")).lower(),
                "token": str(claim.get("token", "")),
            }
        )
    return normalized


def normalize_dm_poll_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        "mailbox_claims": normalize_mailbox_claims(payload),
        "timestamp": _safe_int(payload.get("timestamp", 0), 0),
        "nonce": str(payload.get("nonce", "")),
    }
    transport_lock = str(payload.get("transport_lock", "") or "").strip().lower()
    if transport_lock:
        normalized["transport_lock"] = transport_lock
    _copy_signed_context(normalized, payload)
    return normalized


def normalize_dm_count_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return normalize_dm_poll_payload(payload)


def normalize_dm_block_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        "blocked_id": str(payload.get("blocked_id", "")),
        "action": str(payload.get("action", "block")).lower(),
    }
    transport_lock = str(payload.get("transport_lock", "") or "").strip().lower()
    if transport_lock:
        normalized["transport_lock"] = transport_lock
    _copy_signed_context(normalized, payload)
    return normalized


def normalize_dm_key_witness_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        "target_id": str(payload.get("target_id", "")),
        "dh_pub_key": str(payload.get("dh_pub_key", "")),
        "timestamp": _safe_int(payload.get("timestamp", 0), 0),
    }
    transport_lock = str(payload.get("transport_lock", "") or "").strip().lower()
    if transport_lock:
        normalized["transport_lock"] = transport_lock
    _copy_signed_context(normalized, payload)
    return normalized


def normalize_trust_vouch_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        "target_id": str(payload.get("target_id", "")),
        "note": str(payload.get("note", ""))[:140],
        "timestamp": _safe_int(payload.get("timestamp", 0), 0),
    }
    transport_lock = str(payload.get("transport_lock", "") or "").strip().lower()
    if transport_lock:
        normalized["transport_lock"] = transport_lock
    _copy_signed_context(normalized, payload)
    return normalized


def normalize_key_rotate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        "old_node_id": str(payload.get("old_node_id", "")),
        "old_public_key": str(payload.get("old_public_key", "")),
        "old_public_key_algo": str(payload.get("old_public_key_algo", "")),
        "new_public_key": str(payload.get("new_public_key", "")),
        "new_public_key_algo": str(payload.get("new_public_key_algo", "")),
        "timestamp": _safe_int(payload.get("timestamp", 0), 0),
        "old_signature": str(payload.get("old_signature", "")),
    }
    transport_lock = str(payload.get("transport_lock", "") or "").strip().lower()
    if transport_lock:
        normalized["transport_lock"] = transport_lock
    _copy_signed_context(normalized, payload)
    return normalized


def normalize_key_revoke_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        "revoked_public_key": str(payload.get("revoked_public_key", "")),
        "revoked_public_key_algo": str(payload.get("revoked_public_key_algo", "")),
        "revoked_at": _safe_int(payload.get("revoked_at", 0), 0),
        "grace_until": _safe_int(payload.get("grace_until", 0), 0),
        "reason": str(payload.get("reason", ""))[:140],
    }
    transport_lock = str(payload.get("transport_lock", "") or "").strip().lower()
    if transport_lock:
        normalized["transport_lock"] = transport_lock
    _copy_signed_context(normalized, payload)
    return normalized


def normalize_abuse_report_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "target_id": str(payload.get("target_id", "")),
        "reason": str(payload.get("reason", ""))[:280],
        "gate": str(payload.get("gate", "")),
        "evidence": str(payload.get("evidence", ""))[:256],
    }


def normalize_sar_anomaly_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Canonical wire shape for a signed SAR anomaly event.

    Mirrors ``services.sar.sar_signing.build_signed_payload`` exactly so the
    verifier sees the same fields the signer signed.  ``evidence_hash`` is
    the load-bearing binding — it is computed over the canonical anomaly
    JSON before signing and reproduced on the verifier side.
    """
    def _f(name: str, default: float = 0.0) -> float:
        try:
            return float(payload.get(name, default) or 0.0)
        except (TypeError, ValueError):
            return default

    def _i(name: str, default: int = 0) -> int:
        try:
            return int(payload.get(name, default) or 0)
        except (TypeError, ValueError):
            return default

    return {
        "anomaly_id": str(payload.get("anomaly_id", ""))[:128],
        "kind": str(payload.get("kind", ""))[:48],
        "lat": _f("lat"),
        "lon": _f("lon"),
        "magnitude": _f("magnitude"),
        "magnitude_unit": str(payload.get("magnitude_unit", ""))[:32],
        "confidence": _f("confidence"),
        "first_seen": str(payload.get("first_seen", ""))[:32],
        "last_seen": str(payload.get("last_seen", ""))[:32],
        "stack_id": str(payload.get("stack_id", ""))[:64],
        "scene_count": _i("scene_count"),
        "evidence_hash": str(payload.get("evidence_hash", ""))[:128],
        "solver": str(payload.get("solver", ""))[:64],
        "source_constellation": str(payload.get("source_constellation", ""))[:64],
    }


def normalize_payload(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    if event_type == "message":
        return normalize_message_payload(payload)
    if event_type == "gate_message":
        return normalize_gate_message_payload(payload)
    if event_type == "vote":
        return normalize_vote_payload(payload)
    if event_type == "gate_create":
        return normalize_gate_create_payload(payload)
    if event_type == "prediction":
        return normalize_prediction_payload(payload)
    if event_type == "stake":
        return normalize_stake_payload(payload)
    if event_type == "dm_key":
        return normalize_dm_key_payload(payload)
    if event_type == "dm_message":
        return normalize_dm_message_payload(payload)
    if event_type == "dm_poll":
        return normalize_dm_poll_payload(payload)
    if event_type == "dm_count":
        return normalize_dm_count_payload(payload)
    if event_type == "dm_block":
        return normalize_dm_block_payload(payload)
    if event_type == "dm_key_witness":
        return normalize_dm_key_witness_payload(payload)
    if event_type == "trust_vouch":
        return normalize_trust_vouch_payload(payload)
    if event_type == "key_rotate":
        return normalize_key_rotate_payload(payload)
    if event_type == "key_revoke":
        return normalize_key_revoke_payload(payload)
    if event_type == "abuse_report":
        return normalize_abuse_report_payload(payload)
    if event_type == "sar_anomaly":
        return normalize_sar_anomaly_payload(payload)
    return payload
