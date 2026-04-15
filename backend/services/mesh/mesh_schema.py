"""Central schema registry for mesh protocol events."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from services.mesh.mesh_protocol import normalize_payload, PROTOCOL_VERSION, NETWORK_ID


def _safe_int(val, default=0):
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class EventSchema:
    event_type: str
    required_fields: tuple[str, ...]
    optional_fields: tuple[str, ...]
    validate: Callable[[dict[str, Any]], tuple[bool, str]]

    def validate_payload(self, payload: dict[str, Any]) -> tuple[bool, str]:
        return self.validate(payload)


def _require_fields(payload: dict[str, Any], fields: tuple[str, ...]) -> tuple[bool, str]:
    for key in fields:
        if key not in payload:
            return False, f"Missing field: {key}"
    return True, "ok"


def _validate_message(payload: dict[str, Any]) -> tuple[bool, str]:
    ok, reason = _require_fields(
        payload, ("message", "destination", "channel", "priority", "ephemeral")
    )
    if not ok:
        return ok, reason
    if payload.get("priority") not in ("normal", "high", "emergency", "low"):
        return False, "Invalid priority"
    if not isinstance(payload.get("ephemeral"), bool):
        return False, "ephemeral must be boolean"
    return True, "ok"


def _validate_gate_message(payload: dict[str, Any]) -> tuple[bool, str]:
    ok, reason = _require_fields(payload, ("gate", "ciphertext", "nonce", "sender_ref"))
    if not ok:
        return ok, reason
    if "message" in payload:
        return False, "plaintext gate message field is not allowed"
    gate = str(payload.get("gate", "")).strip().lower()
    if not gate:
        return False, "gate cannot be empty"
    if "epoch" in payload:
        epoch = _safe_int(payload.get("epoch", 0) or 0, 0)
        if epoch <= 0:
            return False, "epoch must be a positive integer"
    elif (
        not str(payload.get("ciphertext", "")).strip()
        and not str(payload.get("nonce", "")).strip()
        and not str(payload.get("sender_ref", "")).strip()
    ):
        return False, "epoch must be a positive integer"
    if not str(payload.get("ciphertext", "")).strip():
        return False, "ciphertext cannot be empty"
    if not str(payload.get("nonce", "")).strip():
        return False, "nonce cannot be empty"
    if not str(payload.get("sender_ref", "")).strip():
        return False, "sender_ref cannot be empty"
    payload_format = str(payload.get("format", "mls1") or "mls1").strip().lower()
    if payload_format != "mls1":
        return False, "Unsupported gate message format"
    return True, "ok"


def _validate_vote(payload: dict[str, Any]) -> tuple[bool, str]:
    ok, reason = _require_fields(payload, ("target_id", "vote", "gate"))
    if not ok:
        return ok, reason
    if payload.get("vote") not in (-1, 1):
        return False, "Invalid vote"
    return True, "ok"


def _validate_gate_create(payload: dict[str, Any]) -> tuple[bool, str]:
    ok, reason = _require_fields(payload, ("gate_id", "display_name", "rules"))
    if not ok:
        return ok, reason
    if not isinstance(payload.get("rules"), dict):
        return False, "rules must be an object"
    return True, "ok"


def _validate_prediction(payload: dict[str, Any]) -> tuple[bool, str]:
    return _require_fields(payload, ("market_title", "side", "stake_amount"))


def _validate_stake(payload: dict[str, Any]) -> tuple[bool, str]:
    return _require_fields(payload, ("message_id", "poster_id", "side", "amount", "duration_days"))


def _validate_dm_block(payload: dict[str, Any]) -> tuple[bool, str]:
    ok, reason = _require_fields(payload, ("blocked_id", "action"))
    if not ok:
        return ok, reason
    if payload.get("action") not in ("block", "unblock"):
        return False, "Invalid action"
    return True, "ok"


def _validate_dm_key(payload: dict[str, Any]) -> tuple[bool, str]:
    ok, reason = _require_fields(payload, ("dh_pub_key", "dh_algo", "timestamp"))
    if not ok:
        return ok, reason
    if payload.get("dh_algo") not in ("X25519", "ECDH", "ECDH_P256"):
        return False, "Invalid dh_algo"
    return True, "ok"


def _validate_dm_message(payload: dict[str, Any]) -> tuple[bool, str]:
    ok, reason = _require_fields(
        payload, ("recipient_id", "delivery_class", "recipient_token", "ciphertext", "msg_id", "timestamp")
    )
    if not ok:
        return ok, reason
    delivery_class = str(payload.get("delivery_class", "")).lower()
    if delivery_class not in ("request", "shared"):
        return False, "Invalid delivery_class"
    if delivery_class == "shared" and not str(payload.get("recipient_token", "")).strip():
        return False, "recipient_token required for shared delivery"
    dm_format = str(payload.get("format", "mls1") or "mls1").strip().lower()
    if dm_format not in ("mls1", "dm1"):
        return False, f"Unknown DM format: {dm_format}"
    return True, "ok"


def _validate_mailbox_claims(claims: Any) -> tuple[bool, str]:
    if not isinstance(claims, list) or not claims:
        return False, "mailbox_claims must be a non-empty list"
    for claim in claims:
        if not isinstance(claim, dict):
            return False, "mailbox_claims entries must be objects"
        claim_type = str(claim.get("type", "")).lower()
        if claim_type not in ("self", "requests", "shared"):
            return False, "Invalid mailbox claim type"
        if not str(claim.get("token", "")).strip():
            return False, f"{claim_type} mailbox claims require token"
    return True, "ok"


def _validate_dm_poll(payload: dict[str, Any]) -> tuple[bool, str]:
    ok, reason = _require_fields(payload, ("mailbox_claims", "timestamp", "nonce"))
    if not ok:
        return ok, reason
    return _validate_mailbox_claims(payload.get("mailbox_claims"))


def _validate_dm_count(payload: dict[str, Any]) -> tuple[bool, str]:
    return _validate_dm_poll(payload)


def _validate_key_rotate(payload: dict[str, Any]) -> tuple[bool, str]:
    ok, reason = _require_fields(
        payload,
        (
            "old_node_id",
            "old_public_key",
            "old_public_key_algo",
            "new_public_key",
            "new_public_key_algo",
            "timestamp",
            "old_signature",
        ),
    )
    if not ok:
        return ok, reason
    return True, "ok"


def _validate_key_revoke(payload: dict[str, Any]) -> tuple[bool, str]:
    ok, reason = _require_fields(
        payload,
        (
            "revoked_public_key",
            "revoked_public_key_algo",
            "revoked_at",
            "grace_until",
            "reason",
        ),
    )
    if not ok:
        return ok, reason
    revoked_at = _safe_int(payload.get("revoked_at", 0) or 0, 0)
    grace_until = _safe_int(payload.get("grace_until", 0) or 0, 0)
    if revoked_at <= 0:
        return False, "revoked_at must be a positive timestamp"
    if grace_until < revoked_at:
        return False, "grace_until must be >= revoked_at"
    return True, "ok"


def _validate_abuse_report(payload: dict[str, Any]) -> tuple[bool, str]:
    ok, reason = _require_fields(payload, ("target_id", "reason"))
    if not ok:
        return ok, reason
    if not str(payload.get("reason", "")).strip():
        return False, "reason cannot be empty"
    return True, "ok"


SCHEMA_REGISTRY: dict[str, EventSchema] = {
    "message": EventSchema(
        event_type="message",
        required_fields=("message", "destination", "channel", "priority", "ephemeral"),
        optional_fields=(),
        validate=_validate_message,
    ),
    "gate_message": EventSchema(
        event_type="gate_message",
        required_fields=("gate", "ciphertext", "nonce", "sender_ref"),
        optional_fields=("format",),
        validate=_validate_gate_message,
    ),
    "vote": EventSchema(
        event_type="vote",
        required_fields=("target_id", "vote", "gate"),
        optional_fields=(),
        validate=_validate_vote,
    ),
    "gate_create": EventSchema(
        event_type="gate_create",
        required_fields=("gate_id", "display_name", "rules"),
        optional_fields=(),
        validate=_validate_gate_create,
    ),
    "prediction": EventSchema(
        event_type="prediction",
        required_fields=("market_title", "side", "stake_amount"),
        optional_fields=(),
        validate=_validate_prediction,
    ),
    "stake": EventSchema(
        event_type="stake",
        required_fields=("message_id", "poster_id", "side", "amount", "duration_days"),
        optional_fields=(),
        validate=_validate_stake,
    ),
    "dm_block": EventSchema(
        event_type="dm_block",
        required_fields=("blocked_id", "action"),
        optional_fields=(),
        validate=_validate_dm_block,
    ),
    "dm_key": EventSchema(
        event_type="dm_key",
        required_fields=("dh_pub_key", "dh_algo", "timestamp"),
        optional_fields=(),
        validate=_validate_dm_key,
    ),
    "dm_message": EventSchema(
        event_type="dm_message",
        required_fields=("recipient_id", "delivery_class", "recipient_token", "ciphertext", "msg_id", "timestamp"),
        optional_fields=(),
        validate=_validate_dm_message,
    ),
    "dm_poll": EventSchema(
        event_type="dm_poll",
        required_fields=("mailbox_claims", "timestamp", "nonce"),
        optional_fields=(),
        validate=_validate_dm_poll,
    ),
    "dm_count": EventSchema(
        event_type="dm_count",
        required_fields=("mailbox_claims", "timestamp", "nonce"),
        optional_fields=(),
        validate=_validate_dm_count,
    ),
    "key_rotate": EventSchema(
        event_type="key_rotate",
        required_fields=(
            "old_node_id",
            "old_public_key",
            "old_public_key_algo",
            "new_public_key",
            "new_public_key_algo",
            "timestamp",
            "old_signature",
        ),
        optional_fields=(),
        validate=_validate_key_rotate,
    ),
    "key_revoke": EventSchema(
        event_type="key_revoke",
        required_fields=(
            "revoked_public_key",
            "revoked_public_key_algo",
            "revoked_at",
            "grace_until",
            "reason",
        ),
        optional_fields=(),
        validate=_validate_key_revoke,
    ),
    "abuse_report": EventSchema(
        event_type="abuse_report",
        required_fields=("target_id", "reason"),
        optional_fields=("gate", "evidence"),
        validate=_validate_abuse_report,
    ),
}


PUBLIC_LEDGER_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "message",
        "vote",
        "gate_create",
        "gate_message",
        "prediction",
        "stake",
        "key_rotate",
        "key_revoke",
        "abuse_report",
    }
)

_PUBLIC_LEDGER_FORBIDDEN_FIELDS: frozenset[str] = frozenset(
    {
        "ip",
        "ip_address",
        "origin_ip",
        "source_ip",
        "client_ip",
        "host",
        "hostname",
        "origin",
        "originator",
        "originator_hint",
        "routing_hint",
        "route",
        "route_hint",
        "route_reason",
        "routed_via",
        "transport",
        "transport_handle",
        "transport_lock",
        "recipient_id",
        "recipient_token",
        "delivery_class",
        "mailbox_claims",
        "dh_pub_key",
        "sender_token",
    }
)


def get_schema(event_type: str) -> EventSchema | None:
    return SCHEMA_REGISTRY.get(event_type)


def validate_event_payload(event_type: str, payload: dict[str, Any]) -> tuple[bool, str]:
    schema = get_schema(event_type)
    if not schema:
        return False, "Unknown event_type"
    normalized = normalize_payload(event_type, payload)
    if normalized != payload:
        return False, "Payload is not normalized"
    if event_type not in ("message", "gate_message") and "ephemeral" in payload:
        return False, "ephemeral not allowed for this event type"
    return schema.validate_payload(payload)


def validate_public_ledger_payload(event_type: str, payload: dict[str, Any]) -> tuple[bool, str]:
    if event_type not in PUBLIC_LEDGER_EVENT_TYPES:
        return False, f"{event_type} is not allowed on the public ledger"
    forbidden = sorted(
        key
        for key in payload.keys()
        if str(key or "").strip().lower() in _PUBLIC_LEDGER_FORBIDDEN_FIELDS
    )
    if forbidden:
        return False, f"public ledger payload contains forbidden fields: {', '.join(forbidden)}"
    if event_type == "message":
        destination = str(payload.get("destination", "") or "").strip().lower()
        if destination and destination != "broadcast":
            return False, "public ledger message destination must be broadcast"
    return True, "ok"


def validate_protocol_fields(protocol_version: str, network_id: str) -> tuple[bool, str]:
    if protocol_version != PROTOCOL_VERSION:
        return False, "Unsupported protocol_version"
    if network_id != NETWORK_ID:
        return False, "network_id mismatch"
    return True, "ok"
