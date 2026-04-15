"""Mesh protocol helpers for canonical payloads and versioning."""

from __future__ import annotations

from typing import Any
PROTOCOL_VERSION = "infonet/2"
NETWORK_ID = "sb-testnet-0"


def _safe_int(val, default=0):
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _normalize_number(value: Any) -> int | float:
    try:
        num = float(value)
    except Exception:
        return 0
    if num.is_integer():
        return int(num)
    return num


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
    # reply_to is a display-only parent message reference.
    reply_to = str(payload.get("reply_to", "") or "").strip()
    if reply_to:
        normalized["reply_to"] = reply_to
    return normalized


def normalize_vote_payload(payload: dict[str, Any]) -> dict[str, Any]:
    vote_val = _safe_int(payload.get("vote", 0), 0)
    return {
        "target_id": str(payload.get("target_id", "")),
        "vote": vote_val,
        "gate": str(payload.get("gate", "")),
    }


def normalize_gate_create_payload(payload: dict[str, Any]) -> dict[str, Any]:
    rules = payload.get("rules", {})
    if not isinstance(rules, dict):
        rules = {}
    return {
        "gate_id": str(payload.get("gate_id", "")).lower(),
        "display_name": str(payload.get("display_name", ""))[:64],
        "rules": rules,
    }


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
    return {
        "dh_pub_key": str(payload.get("dh_pub_key", "")),
        "dh_algo": str(payload.get("dh_algo", "")),
        "timestamp": _safe_int(payload.get("timestamp", 0), 0),
    }


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
    return {
        "mailbox_claims": normalize_mailbox_claims(payload),
        "timestamp": _safe_int(payload.get("timestamp", 0), 0),
        "nonce": str(payload.get("nonce", "")),
    }


def normalize_dm_count_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return normalize_dm_poll_payload(payload)


def normalize_dm_block_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "blocked_id": str(payload.get("blocked_id", "")),
        "action": str(payload.get("action", "block")).lower(),
    }


def normalize_dm_key_witness_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "target_id": str(payload.get("target_id", "")),
        "dh_pub_key": str(payload.get("dh_pub_key", "")),
        "timestamp": _safe_int(payload.get("timestamp", 0), 0),
    }


def normalize_trust_vouch_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "target_id": str(payload.get("target_id", "")),
        "note": str(payload.get("note", ""))[:140],
        "timestamp": _safe_int(payload.get("timestamp", 0), 0),
    }


def normalize_key_rotate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "old_node_id": str(payload.get("old_node_id", "")),
        "old_public_key": str(payload.get("old_public_key", "")),
        "old_public_key_algo": str(payload.get("old_public_key_algo", "")),
        "new_public_key": str(payload.get("new_public_key", "")),
        "new_public_key_algo": str(payload.get("new_public_key_algo", "")),
        "timestamp": _safe_int(payload.get("timestamp", 0), 0),
        "old_signature": str(payload.get("old_signature", "")),
    }


def normalize_key_revoke_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "revoked_public_key": str(payload.get("revoked_public_key", "")),
        "revoked_public_key_algo": str(payload.get("revoked_public_key_algo", "")),
        "revoked_at": _safe_int(payload.get("revoked_at", 0), 0),
        "grace_until": _safe_int(payload.get("grace_until", 0), 0),
        "reason": str(payload.get("reason", ""))[:140],
    }


def normalize_abuse_report_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "target_id": str(payload.get("target_id", "")),
        "reason": str(payload.get("reason", ""))[:280],
        "gate": str(payload.get("gate", "")),
        "evidence": str(payload.get("evidence", ""))[:256],
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
    return payload
