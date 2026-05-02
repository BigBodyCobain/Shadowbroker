import asyncio
import base64
import hashlib as _hashlib_mod
import json as json_mod
import logging
import math
import secrets
import time
from typing import Any

from cachetools import TTLCache
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from auth import (
    _private_plane_access_denied_payload,
    _private_plane_refusal_response,
    _private_infonet_policy_snapshot,
    require_admin,
    require_local_operator,
)
from limiter import limiter


# ---------------------------------------------------------------------------
# Transition delegates: forward to main.py so test monkeypatches still work.
# These will move to a shared module once main.py routes are removed.
# ---------------------------------------------------------------------------
def _main_delegate(name):
    def _wrapper(*a, **kw):
        import main as _m
        return getattr(_m, name)(*a, **kw)
    _wrapper.__name__ = name
    return _wrapper


_check_scoped_auth = _main_delegate("_check_scoped_auth")
_current_private_lane_tier = _main_delegate("_current_private_lane_tier")
_is_debug_test_request = _main_delegate("_is_debug_test_request")
_scoped_view_authenticated = _main_delegate("_scoped_view_authenticated")
_node_runtime_snapshot = _main_delegate("_node_runtime_snapshot")
_verify_gate_access_main = _main_delegate("_verify_gate_access")
from services.config import get_settings
from services.data_fetcher import get_latest_data
from services.mesh.mesh_crypto import (
    derive_node_id,
    normalize_peer_url,
    parse_public_key_algo,
)
from services.mesh.mesh_protocol import (
    PROTOCOL_VERSION,
    normalize_payload,
)
from services.mesh.mesh_schema import validate_event_payload
from services.mesh.mesh_signed_events import (
    MeshWriteExemption,
    SignedWriteKind,
    get_prepared_signed_write,
    mesh_write_exempt,
    requires_signed_write,
    verify_key_rotation_claim_signature,
    verify_node_bound_signature,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _signed_body(request: Request) -> dict[str, Any]:
    prepared = get_prepared_signed_write(request)
    if prepared is None:
        return {}
    return dict(prepared.body)


# --- Public mesh log helpers ---

def _public_mesh_log_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
    tier_str = str((entry or {}).get("trust_tier", "public_degraded") or "public_degraded").strip().lower()
    if tier_str.startswith("private_"):
        return None
    return {
        "sender": str((entry or {}).get("sender", "") or ""),
        "destination": str((entry or {}).get("destination", "") or ""),
        "routed_via": str((entry or {}).get("routed_via", "") or ""),
        "priority": str((entry or {}).get("priority", "") or ""),
        "route_reason": str((entry or {}).get("route_reason", "") or ""),
        "timestamp": float((entry or {}).get("timestamp", 0) or 0),
    }


def _public_mesh_log_size(entries: list[dict[str, Any]]) -> int:
    return sum(1 for item in entries if _public_mesh_log_entry(item) is not None)

# --- Constants ---

_PRIVATE_LANE_CONTROL_FIELDS = {"private_lane_tier", "private_lane_policy"}
_PUBLIC_RNS_STATUS_FIELDS = {"enabled", "ready", "configured_peers", "active_peers"}

# --- Gate timestamp redaction ---

def _redacted_gate_timestamp(event: dict[str, Any]) -> float:
    raw_ts = float((event or {}).get("timestamp", 0) or 0.0)
    if raw_ts <= 0:
        return 0.0
    try:
        jitter_window = max(0, int(get_settings().MESH_GATE_TIMESTAMP_JITTER_S or 0))
    except Exception:
        jitter_window = 0
    if jitter_window <= 0:
        return raw_ts
    event_id = str((event or {}).get("event_id", "") or "")
    seed = _hashlib_mod.sha256(f"{event_id}|{int(raw_ts)}".encode("utf-8")).digest()
    fraction = int.from_bytes(seed[:8], "big") / float(2**64 - 1)
    return max(0.0, raw_ts - (fraction * float(jitter_window)))

# --- Status/lane redaction helpers ---

def _redact_private_lane_control_fields(
    payload: dict[str, Any],
    authenticated: bool,
) -> dict[str, Any]:
    redacted = dict(payload)
    if authenticated:
        return redacted
    for field in _PRIVATE_LANE_CONTROL_FIELDS:
        redacted.pop(field, None)
    return redacted


def _redact_public_rns_status(
    payload: dict[str, Any],
    authenticated: bool,
) -> dict[str, Any]:
    redacted = _redact_private_lane_control_fields(payload, authenticated=authenticated)
    if authenticated:
        return redacted
    return {
        key: redacted.get(key)
        for key in _PUBLIC_RNS_STATUS_FIELDS
        if key in redacted
    }


def _redact_public_mesh_status(
    payload: dict[str, Any],
    authenticated: bool,
) -> dict[str, Any]:
    if authenticated:
        return dict(payload)
    return {
        "message_log_size": int(payload.get("message_log_size", 0) or 0),
    }

# --- Node history redaction ---

def _redact_public_node_history(
    events: list[dict[str, Any]],
    authenticated: bool,
) -> list[dict[str, Any]]:
    if authenticated:
        return [dict(event) for event in events]
    return [
        {
            "event_id": str(event.get("event_id", "") or ""),
            "event_type": str(event.get("event_type", "") or ""),
            "timestamp": float(event.get("timestamp", 0) or 0),
        }
        for event in events
    ]

# --- Composed gate message redaction ---

def _redact_composed_gate_message(payload: dict[str, Any]) -> dict[str, Any]:
    safe = {
        "ok": bool(payload.get("ok")),
        "gate_id": str(payload.get("gate_id", "") or ""),
        "identity_scope": str(payload.get("identity_scope", "") or ""),
        "ciphertext": str(payload.get("ciphertext", "") or ""),
        "nonce": str(payload.get("nonce", "") or ""),
        "sender_ref": str(payload.get("sender_ref", "") or ""),
        "format": str(payload.get("format", "mls1") or "mls1"),
        "timestamp": float(payload.get("timestamp", 0) or 0),
    }
    epoch = payload.get("epoch", 0)
    if epoch:
        safe["epoch"] = int(epoch or 0)
    if payload.get("detail"):
        safe["detail"] = str(payload.get("detail", "") or "")
    if payload.get("key_commitment"):
        safe["key_commitment"] = str(payload.get("key_commitment", "") or "")
    return safe

# --- Gate validation and access helpers ---

_validate_gate_vote_context = _main_delegate("_validate_gate_vote_context")


_GATE_REDACT_FIELDS = ("sender_ref", "epoch", "nonce")
_KEY_ROTATE_REDACT_FIELDS = {
    "old_node_id",
    "old_public_key",
    "old_public_key_algo",
    "old_signature",
}


def _redact_gate_metadata(event: dict) -> dict:
    """Strip MLS-internal fields from gate_message events in public sync responses."""
    if not isinstance(event, dict):
        return event
    event_type = str(event.get("event_type", "") or "")
    if event_type != "gate_message":
        return event
    redacted = dict(event)
    for field in ("node_id", "sequence"):
        redacted.pop(field, None)
    if isinstance(redacted.get("payload"), dict):
        payload = dict(redacted.get("payload") or {})
        for field in _GATE_REDACT_FIELDS:
            payload.pop(field, None)
        redacted["payload"] = payload
        return redacted
    for field in _GATE_REDACT_FIELDS:
        redacted.pop(field, None)
    return redacted


def _redact_key_rotate_payload(event: dict) -> dict:
    """Strip identity-linking fields from key_rotate events in public responses."""
    if not isinstance(event, dict):
        return event
    if str(event.get("event_type", "") or "") != "key_rotate":
        return event
    redacted = dict(event)
    payload = redacted.get("payload")
    if isinstance(payload, dict):
        payload = dict(payload)
        for field in _KEY_ROTATE_REDACT_FIELDS:
            payload.pop(field, None)
        redacted["payload"] = payload
    return redacted


def _redact_vote_gate(event: dict) -> dict:
    """Strip gate label from vote events in public responses."""
    if not isinstance(event, dict):
        return event
    if str(event.get("event_type", "") or "") != "vote":
        return event
    redacted = dict(event)
    payload = redacted.get("payload")
    if isinstance(payload, dict):
        payload = dict(payload)
        payload.pop("gate", None)
        redacted["payload"] = payload
    return redacted


def _redact_public_event(event: dict) -> dict:
    """Apply all public-response redactions for public chain endpoints."""
    return _redact_vote_gate(_redact_key_rotate_payload(_redact_gate_metadata(event)))


def _trusted_gate_reply_to(event: dict) -> str:
    if not isinstance(event, dict):
        return ""
    payload = event.get("payload")
    if not isinstance(payload, dict):
        return ""
    reply_to = str(payload.get("reply_to", "") or "").strip()
    if not reply_to:
        return ""
    gate_id = str(payload.get("gate", "") or "").strip()
    node_id = str(event.get("node_id", "") or "").strip()
    public_key = str(event.get("public_key", "") or "").strip()
    public_key_algo = str(event.get("public_key_algo", "") or "").strip()
    if node_id and not public_key and gate_id:
        try:
            binding = _lookup_gate_member_binding(gate_id, node_id)
            if binding:
                public_key, public_key_algo = binding
        except Exception:
            return ""
    signature = str(event.get("signature", "") or "").strip()
    protocol_version = str(event.get("protocol_version", "") or "").strip()
    sequence = int(event.get("sequence", 0) or 0)
    if not (gate_id and node_id and public_key and public_key_algo and signature and protocol_version and sequence > 0):
        return ""
    verify_payload = {
        "gate": gate_id,
        "ciphertext": str(payload.get("ciphertext", "") or ""),
        "nonce": str(payload.get("nonce", "") or ""),
        "sender_ref": str(payload.get("sender_ref", "") or ""),
        "format": str(payload.get("format", "mls1") or "mls1"),
    }
    epoch = _safe_int(payload.get("epoch", 0) or 0)
    if epoch > 0:
        verify_payload["epoch"] = epoch
    envelope_hash = str(payload.get("envelope_hash", "") or "").strip()
    if envelope_hash:
        verify_payload["envelope_hash"] = envelope_hash
    return _recover_verified_gate_reply_to(
        node_id=node_id,
        sequence=sequence,
        public_key=public_key,
        public_key_algo=public_key_algo,
        signature=signature,
        payload=verify_payload,
        reply_to=reply_to,
        protocol_version=protocol_version,
    )


def _derive_anon_handle_router(node_id: str, gate_id: str) -> str:
    """HMAC(node_id, gate_id)[:4] — stable session handle, rotates with session."""
    import hmac as _hmac, hashlib as _hashlib
    node_key = str(node_id or "").strip()
    gate_key = str(gate_id or "").strip().lower()
    if not node_key:
        return "anon_????"
    tag = _hmac.new(
        node_key.encode("utf-8"),
        f"{gate_key}|sender-handle-v1".encode("utf-8"),
        _hashlib.sha256,
    ).hexdigest()[:4]
    return f"anon_{tag}"


def _strip_gate_identity_member(event: dict, *, envelope_policy: str = "envelope_disabled") -> dict:
    """Narrowed member view: strips signer identity fields.

    Includes ``sender_handle`` (stable per-session anonymized display label)
    and the ``gate_envelope`` / ``envelope_hash`` fields members need to
    decrypt durable history via the AES-GCM envelope under gate_secret.
    """
    if not isinstance(event, dict):
        event = {}
    payload = event.get("payload")
    if not isinstance(payload, dict):
        payload = {}
    gate_id = str(payload.get("gate", "") or "")
    sender_handle = _derive_anon_handle_router(str(event.get("node_id", "") or ""), gate_id)
    result_payload: dict = {
        "gate": gate_id,
        "ciphertext": str(payload.get("ciphertext", "") or ""),
        "format": str(payload.get("format", "") or ""),
        "nonce": str(payload.get("nonce", "") or ""),
        "sender_ref": str(payload.get("sender_ref", "") or ""),
        "sender_handle": sender_handle,
        "transport_lock": str(payload.get("transport_lock", "") or ""),
        "gate_envelope": str(payload.get("gate_envelope", "") or ""),
        "envelope_hash": str(payload.get("envelope_hash", "") or ""),
        "reply_to": _trusted_gate_reply_to(event),
    }
    return {
        "event_id": str(event.get("event_id", "") or ""),
        "event_type": "gate_message",
        "timestamp": _redacted_gate_timestamp(event),
        "protocol_version": str(event.get("protocol_version", "") or ""),
        "sender_handle": sender_handle,
        "payload": result_payload,
    }


def _strip_gate_identity_privileged(event: dict) -> dict:
    """Privileged/audit view: preserves full signer identity surface."""
    if not isinstance(event, dict):
        event = {}
    payload = event.get("payload")
    if not isinstance(payload, dict):
        payload = {}
    node_id = str(event.get("node_id", "") or "")
    public_key = str(event.get("public_key", "") or "")
    public_key_algo = str(event.get("public_key_algo", "") or "")
    if node_id and not public_key:
        gate_id = str(payload.get("gate", "") or "")
        if gate_id:
            try:
                binding = _lookup_gate_member_binding(gate_id, node_id)
                if binding:
                    public_key, public_key_algo = binding
            except Exception:
                pass
    return {
        "event_id": str(event.get("event_id", "") or ""),
        "event_type": "gate_message",
        "timestamp": _redacted_gate_timestamp(event),
        "node_id": node_id,
        "sequence": int(event.get("sequence", 0) or 0),
        "signature": str(event.get("signature", "") or ""),
        "public_key": public_key,
        "public_key_algo": public_key_algo,
        "protocol_version": str(event.get("protocol_version", "") or ""),
        "payload": {
            "gate": str(payload.get("gate", "") or ""),
            "ciphertext": str(payload.get("ciphertext", "") or ""),
            "format": str(payload.get("format", "") or ""),
            "nonce": str(payload.get("nonce", "") or ""),
            "sender_ref": str(payload.get("sender_ref", "") or ""),
            "transport_lock": str(payload.get("transport_lock", "") or ""),
            "gate_envelope": str(payload.get("gate_envelope", "") or ""),
            "envelope_hash": str(payload.get("envelope_hash", "") or ""),
            "reply_to": _trusted_gate_reply_to(event),
        },
    }


def _strip_gate_identity(event: dict) -> dict:
    """Legacy alias — defaults to member (narrowed) view."""
    return _strip_gate_identity_member(event)


def _resolve_envelope_policy(gate_id: str) -> str:
    """Look up envelope_policy for a gate. Per-gate policy is the source of
    truth; the global recovery-envelope runtime gate is intentionally NOT
    checked here — it silently downgrades working configurations to
    envelope_disabled without surfacing any error."""
    try:
        from services.mesh.mesh_reputation import gate_manager
        return str(gate_manager.get_envelope_policy(gate_id) or "envelope_disabled")
    except Exception:
        return "envelope_disabled"


def _strip_gate_for_access(event: dict, access: str) -> dict:
    """Select member or privileged strip based on access level."""
    if access == "privileged":
        return _strip_gate_identity_privileged(event)
    payload = event.get("payload") if isinstance(event, dict) else None
    gate_id = str((payload or {}).get("gate", "") or "")
    envelope_policy = _resolve_envelope_policy(gate_id) if gate_id else "envelope_disabled"
    return _strip_gate_identity_member(event, envelope_policy=envelope_policy)


def _lookup_gate_member_binding(gate_id: str, node_id: str) -> tuple[str, str] | None:
    gate_key = str(gate_id or "").strip().lower()
    candidate = str(node_id or "").strip()
    if not gate_key or not candidate:
        return None
    try:
        from services.mesh.mesh_wormhole_persona import (
            bootstrap_wormhole_persona_state,
            read_wormhole_persona_state,
        )

        bootstrap_wormhole_persona_state()
        state = read_wormhole_persona_state()
    except Exception:
        return None
    for persona in list(state.get("gate_personas", {}).get(gate_key) or []):
        if str(persona.get("node_id", "") or "").strip() != candidate:
            continue
        public_key = str(persona.get("public_key", "") or "").strip()
        public_key_algo = str(persona.get("public_key_algo", "Ed25519") or "Ed25519").strip()
        if public_key and public_key_algo:
            return public_key, public_key_algo
    session = dict(state.get("gate_sessions", {}).get(gate_key) or {})
    if str(session.get("node_id", "") or "").strip() == candidate:
        public_key = str(session.get("public_key", "") or "").strip()
        public_key_algo = str(session.get("public_key_algo", "Ed25519") or "Ed25519").strip()
        if public_key and public_key_algo:
            return public_key, public_key_algo
    return None


_resolve_gate_proof_identity = _main_delegate("_resolve_gate_proof_identity")


def _sign_gate_access_proof(gate_id: str) -> dict[str, Any]:
    gate_key = str(gate_id or "").strip().lower()
    if not gate_key:
        return {"ok": False, "detail": "gate_id required"}
    identity = _resolve_gate_proof_identity(gate_key)
    if not identity:
        return {"ok": False, "detail": "gate_access_proof_unavailable"}
    private_key_b64 = str(identity.get("private_key", "") or "").strip()
    node_id = str(identity.get("node_id", "") or "").strip()
    public_key = str(identity.get("public_key", "") or "").strip()
    public_key_algo = str(identity.get("public_key_algo", "Ed25519") or "Ed25519").strip()
    if not (private_key_b64 and node_id and public_key and public_key_algo):
        return {"ok": False, "detail": "gate_access_proof_unavailable"}
    try:
        from cryptography.hazmat.primitives.asymmetric import ec, ed25519

        ts = int(time.time())
        challenge = f"{gate_key}:{ts}"
        key_bytes = base64.b64decode(private_key_b64)
        algo = parse_public_key_algo(public_key_algo)
        if algo == "Ed25519":
            signing_key = ed25519.Ed25519PrivateKey.from_private_bytes(key_bytes)
            signature = signing_key.sign(challenge.encode("utf-8"))
        elif algo == "ECDSA_P256":
            from cryptography.hazmat.primitives import hashes

            signing_key = ec.derive_private_key(int.from_bytes(key_bytes, "big"), ec.SECP256R1())
            signature = signing_key.sign(challenge.encode("utf-8"), ec.ECDSA(hashes.SHA256()))
        else:
            return {"ok": False, "detail": "gate_access_proof_unsupported_algo"}
    except Exception as exc:
        logger.warning("Gate access proof signing failed: %s", type(exc).__name__)
        return {"ok": False, "detail": "gate_access_proof_failed"}
    return {
        "ok": True,
        "gate_id": gate_key,
        "node_id": node_id,
        "ts": ts,
        "proof": base64.b64encode(signature).decode("ascii"),
    }


def _verify_gate_access(request: Request, gate_id: str) -> str:
    """Delegate gate access policy to main.py so the runtime seam stays singular."""
    return str(_verify_gate_access_main(request, gate_id) or "")

# --- Throttle state ---


# ─── Per-Identity Throttle State ──────────────────────────────────────────
# In-memory: {node_id: {"last_send": timestamp, "daily_count": int, "daily_reset": timestamp}}
# Bounded to 10000 entries with 24hr TTL to prevent unbounded memory growth
_node_throttle: TTLCache = TTLCache(maxsize=10000, ttl=86400)
_gate_post_cooldown: TTLCache = TTLCache(maxsize=20000, ttl=86400)

# Byte limits per payload type
_BYTE_LIMITS = {"text": 200, "pin": 300, "emergency": 200, "command": 200}

# --- Throttle and signed event helpers ---

_check_throttle = _main_delegate("_check_throttle")


_check_gate_post_cooldown = _main_delegate("_check_gate_post_cooldown")
_record_gate_post_cooldown = _main_delegate("_record_gate_post_cooldown")


_recover_verified_gate_reply_to = _main_delegate("_recover_verified_gate_reply_to")
_verify_gate_message_signed_write = _main_delegate("_verify_gate_message_signed_write")
_verify_signed_write = _main_delegate("_verify_signed_write")



# --- Gate store hydration ---

def _hydrate_gate_store_from_chain(events: list[dict]) -> int:
    """Copy any gate_message chain events into the local gate_store for read/decrypt.

    Only events that are resident in the local infonet (accepted or already
    present) are hydrated.  The canonical infonet-resident event is used —
    never the raw batch event — so a forged batch entry carrying a valid
    event_id but attacker-chosen payload cannot pollute gate_store.
    """
    import copy

    from services.mesh.mesh_hashchain import gate_store, infonet

    count = 0
    for evt in events:
        if evt.get("event_type") != "gate_message":
            continue
        event_id = str(evt.get("event_id", "") or "").strip()
        if not event_id or event_id not in infonet.event_index:
            continue
        canonical = infonet.events[infonet.event_index[event_id]]
        payload = canonical.get("payload") or {}
        gate_id = str(payload.get("gate", "") or "").strip()
        if not gate_id:
            continue
        try:
            gate_store.append(gate_id, copy.deepcopy(canonical))
            count += 1
        except Exception:
            pass
    return count

# --- Safe type helpers ---

def _safe_int(val, default=0):
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _safe_float(val, default=0.0):
    try:
        parsed = float(val)
        if not math.isfinite(parsed):
            return default
        return parsed
    except (TypeError, ValueError):
        return default

# --- Route handlers ---

@router.post("/api/mesh/send")
@limiter.limit("10/minute")
@requires_signed_write(kind=SignedWriteKind.MESH_SEND)
async def mesh_send(request: Request):
    """Unified mesh message endpoint — auto-routes via optimal transport.

    Body: { destination, message, priority?, channel?, node_id?, credentials? }
    The router picks APRS, Meshtastic, or Internet based on gate logic.
    Enforces byte limits and per-identity rate limiting.
    """
    body = _signed_body(request)
    destination = body.get("destination", "")
    message = body.get("message", "")
    if not destination or not message:
        return {"ok": False, "detail": "Missing required fields: destination, message"}

    # ─── Byte limit enforcement ───────────────────────────────────
    payload_bytes = len(message.encode("utf-8"))
    payload_type = body.get("payload_type", "text")
    max_bytes = _BYTE_LIMITS.get(payload_type, 200)
    if payload_bytes > max_bytes:
        return {
            "ok": False,
            "detail": f"Message too long ({payload_bytes} bytes). Maximum: {max_bytes} bytes for {payload_type} messages.",
        }

    # ─── Signature verification & node registration ──────────────
    node_id = body.get("node_id", body.get("sender_id", "anonymous"))
    public_key = body.get("public_key", "")
    public_key_algo = body.get("public_key_algo", "")
    signature = body.get("signature", "")
    sequence = _safe_int(body.get("sequence", 0) or 0)
    protocol_version = body.get("protocol_version", "")
    signed_payload = {
        "message": message,
        "destination": destination,
        "channel": body.get("channel", "LongFast"),
        "priority": body.get("priority", "normal").lower(),
        "ephemeral": bool(body.get("ephemeral", False)),
    }
    if body.get("transport_lock"):
        signed_payload["transport_lock"] = str(body.get("transport_lock"))
    # Register node in reputation ledger (auto-creates if new)
    if node_id != "anonymous":
        try:
            from services.mesh.mesh_reputation import reputation_ledger

            reputation_ledger.register_node(node_id, public_key, public_key_algo)
        except Exception:
            pass  # Non-critical — don't block sends if reputation module fails

    # ─── Per-identity throttle ────────────────────────────────────
    priority_str = signed_payload["priority"]
    transport_lock = str(body.get("transport_lock", "") or "").lower()
    throttle_ok, throttle_reason = _check_throttle(node_id, priority_str, transport_lock)
    if not throttle_ok:
        return {"ok": False, "detail": throttle_reason}

    from services.mesh.mesh_router import (
        MeshEnvelope,
        MeshtasticTransport,
        Priority,
        TransportResult,
        mesh_router,
    )

    priority_map = {
        "emergency": Priority.EMERGENCY,
        "high": Priority.HIGH,
        "normal": Priority.NORMAL,
        "low": Priority.LOW,
    }
    priority = priority_map.get(priority_str, Priority.NORMAL)

    # ─── C-1 fix: compute trust_tier from Wormhole state ───────
    from services.wormhole_supervisor import get_transport_tier

    computed_tier = get_transport_tier()

    envelope = MeshEnvelope(
        sender_id=node_id,
        destination=destination,
        channel=body.get("channel", "LongFast"),
        priority=priority,
        payload=message,
        ephemeral=body.get("ephemeral", False),
        trust_tier=computed_tier,
    )

    credentials = body.get("credentials", {})
    # ─── C-2 fix: enforce tier before transport_lock dispatch ──
    private_tier = str(envelope.trust_tier or "").startswith("private_")
    if transport_lock == "meshtastic":
        if private_tier:
            results = [TransportResult(
                False, "meshtastic",
                "Private-tier content cannot be sent over Meshtastic"
            )]
        elif not mesh_router.meshtastic.can_reach(envelope):
            results = [TransportResult(False, "meshtastic", "Message exceeds Meshtastic payload limit")]
        else:
            cb_ok, cb_reason = mesh_router.breakers["meshtastic"].check_and_record(envelope.priority)
            if not cb_ok:
                results = [TransportResult(False, "meshtastic", cb_reason)]
            else:
                envelope.route_reason = (
                    "Transport locked to Meshtastic public path"
                    if MeshtasticTransport._parse_node_id(destination) is None
                    else "Transport locked to Meshtastic public node-targeted path"
                )
                result = mesh_router.meshtastic.send(envelope, credentials)
                if result.ok:
                    envelope.routed_via = mesh_router.meshtastic.NAME
                results = [result]
    elif transport_lock == "aprs":
        if private_tier:
            results = [TransportResult(
                False, "aprs",
                "Private-tier content cannot be sent over APRS"
            )]
        else:
            results = mesh_router.route(envelope, credentials)
    else:
        results = mesh_router.route(envelope, credentials)
    any_ok = any(r.ok for r in results)

    # ─── Mirror to Meshtastic bridge feed ────────────────────────
    # The MQTT broker won't echo our own publishes back to our subscriber,
    # so inject successfully-sent messages into the bridge's deque directly.
    if any_ok and envelope.routed_via == "meshtastic":
        try:
            from services.sigint_bridge import sigint_grid

            bridge = sigint_grid.mesh
            if bridge:
                from datetime import datetime

                bridge.messages.appendleft(
                    {
                        "from": MeshtasticTransport.mesh_address_for_sender(node_id),
                        "to": destination if MeshtasticTransport._parse_node_id(destination) is not None else "broadcast",
                        "text": message,
                        "region": credentials.get("mesh_region", "US"),
                        "channel": body.get("channel", "LongFast"),
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                    }
                )
        except Exception:
            pass  # Non-critical

    return {
        "ok": any_ok,
        "message_id": envelope.message_id,
        "event_id": "",
        "routed_via": envelope.routed_via,
        "route_reason": envelope.route_reason,
        "results": [r.to_dict() for r in results],
    }


@router.get("/api/mesh/log")
@limiter.limit("30/minute")
async def mesh_log(request: Request):
    """Get recent mesh message routing log (audit trail)."""
    from services.mesh.mesh_router import mesh_router

    mesh_router.prune_message_log()
    entries = list(mesh_router.message_log)
    ok, _detail = _check_scoped_auth(request, "mesh.audit")
    if ok:
        return {"log": entries}
    public_entries = [entry for entry in (_public_mesh_log_entry(item) for item in entries) if entry]
    return {"log": public_entries}


@router.get("/api/mesh/status")
@limiter.limit("30/minute")
async def mesh_status(request: Request):
    """Get mesh system status including circuit breaker state."""
    from services.env_check import get_security_posture_warnings
    from services.mesh.mesh_router import mesh_router
    from services.sigint_bridge import sigint_grid

    mesh_router.prune_message_log()
    entries = list(mesh_router.message_log)
    sigs = sigint_grid.get_all_signals()
    aprs = sum(1 for s in sigs if s.get("source") == "aprs")
    mesh = sum(1 for s in sigs if s.get("source") == "meshtastic")
    js8 = sum(1 for s in sigs if s.get("source") == "js8call")
    ok, _detail = _check_scoped_auth(request, "mesh.audit")
    authenticated = _scoped_view_authenticated(request, "mesh.audit")
    response = {
        "circuit_breakers": {
            name: breaker.get_status() for name, breaker in mesh_router.breakers.items()
        },
        "message_log_size": len(entries) if ok else _public_mesh_log_size(entries),
        "signal_counts": {
            "aprs": aprs,
            "meshtastic": mesh,
            "js8call": js8,
            "total": aprs + mesh + js8,
        },
    }
    if ok:
        response["public_message_log_size"] = _public_mesh_log_size(entries)
        response["private_log_retention_seconds"] = int(
            getattr(get_settings(), "MESH_PRIVATE_LOG_TTL_S", 900) or 0
        )
        response["security_warnings"] = get_security_posture_warnings(get_settings())

    return _redact_public_mesh_status(response, authenticated=authenticated)


@router.get("/api/mesh/signals")
@limiter.limit("30/minute")
async def mesh_signals(
    request: Request,
    source: str = "",
    region: str = "",
    root: str = "",
    limit: int = 50,
):
    """Get SIGINT signals with optional source/region/root filters."""
    from services.fetchers.sigint import build_sigint_snapshot

    sigs, _channel_stats, totals = build_sigint_snapshot()
    if source:
        sigs = [s for s in sigs if s.get("source") == source.lower()]
    if region:
        region_filter = region.upper()
        sigs = [
            s
            for s in sigs
            if s.get("region", "").upper() == region_filter
            or s.get("root", "").upper() == region_filter
        ]
    if root:
        root_filter = root.upper()
        sigs = [s for s in sigs if s.get("root", "").upper() == root_filter]
    return {
        "signals": sigs[: min(limit, 500)],
        "total": len(sigs),
        "source_totals": totals,
    }


@router.get("/api/mesh/messages")
@limiter.limit("30/minute")
async def mesh_messages(
    request: Request,
    region: str = "",
    root: str = "",
    channel: str = "",
    limit: int = 30,
):
    """Get recent Meshtastic text messages from the MQTT bridge."""
    from services.sigint_bridge import sigint_grid

    bridge = sigint_grid.mesh
    if not bridge:
        return []
    msgs = list(bridge.messages)
    if region:
        region_filter = region.upper()
        msgs = [
            m
            for m in msgs
            if m.get("region", "").upper() == region_filter
            or m.get("root", "").upper() == region_filter
        ]
    if root:
        root_filter = root.upper()
        msgs = [m for m in msgs if m.get("root", "").upper() == root_filter]
    if channel:
        msgs = [m for m in msgs if m.get("channel", "").lower() == channel.lower()]
    return msgs[: min(limit, 100)]


@router.get("/api/mesh/channels")
@limiter.limit("30/minute")
async def mesh_channels(request: Request):
    """Get Meshtastic channel population stats — nodes per region/channel."""
    stats = get_latest_data().get("mesh_channel_stats", {})
    return stats


# ─── Reputation Endpoints ─────────────────────────────────────────────────

# Cached root node_id — avoids 5 encrypted disk reads per vote.
_root_node_id_cache: dict[str, object] = {"value": None, "ts": 0.0}
_ROOT_NODE_ID_TTL = 30.0  # seconds


def _cached_root_node_id() -> str:
    import time as _time

    now = _time.time()
    if _root_node_id_cache["value"] is not None and (now - float(_root_node_id_cache["ts"])) < _ROOT_NODE_ID_TTL:
        return str(_root_node_id_cache["value"])
    try:
        from services.mesh.mesh_wormhole_persona import read_wormhole_persona_state

        ps = read_wormhole_persona_state()
        nid = str(ps.get("root_identity", {}).get("node_id", "") or "").strip()
        _root_node_id_cache["value"] = nid
        _root_node_id_cache["ts"] = now
        return nid
    except Exception:
        return ""


@router.post("/api/mesh/vote")
@limiter.limit("30/minute")
@requires_signed_write(kind=SignedWriteKind.MESH_VOTE)
async def mesh_vote(request: Request):
    """Cast a reputation vote on a node.

    Body: {voter_id, voter_pubkey?, voter_sig?, target_id, vote: 1|-1, gate?: string}
    """
    from services.mesh.mesh_reputation import reputation_ledger

    body = _signed_body(request)
    voter_id = body.get("voter_id", "")
    target_id = body.get("target_id", "")
    vote = body.get("vote", 0)
    gate = body.get("gate", "")
    public_key = body.get("voter_pubkey", "")
    public_key_algo = body.get("public_key_algo", "")
    signature = body.get("voter_sig", "")
    sequence = _safe_int(body.get("sequence", 0) or 0)
    protocol_version = body.get("protocol_version", "")

    if not voter_id or not target_id:
        return {"ok": False, "detail": "Missing voter_id or target_id"}
    if vote not in (1, -1):
        return {"ok": False, "detail": "Vote must be 1 or -1"}

    gate_ok, gate_detail = _validate_gate_vote_context(voter_id, gate)
    if not gate_ok:
        return {"ok": False, "detail": gate_detail}
    gate = gate_detail or ""

    vote_payload = {"target_id": target_id, "vote": vote, "gate": gate}

    # Resolve stable local operator ID for duplicate-vote prevention.
    # Personas generate unique keypairs, so voter_id alone is insufficient —
    # use the root identity's node_id as a stable anchor so switching personas
    # doesn't let the same operator vote multiple times on the same post.
    stable_voter_id = voter_id
    try:
        root_nid = _cached_root_node_id()
        if root_nid:
            stable_voter_id = root_nid
    except Exception:
        pass

    # Register node if not known
    reputation_ledger.register_node(voter_id, public_key, public_key_algo)

    ok, reason, vote_weight = reputation_ledger.cast_vote(stable_voter_id, target_id, vote, gate)

    # Record on Infonet
    if ok:
        try:
            from services.mesh.mesh_hashchain import infonet

            normalized_payload = normalize_payload("vote", vote_payload)
            infonet.append(
                event_type="vote",
                node_id=voter_id,
                payload=normalized_payload,
                signature=signature,
                sequence=sequence,
                public_key=public_key,
                public_key_algo=public_key_algo,
                protocol_version=protocol_version,
            )
        except Exception:
            pass

    return {"ok": ok, "detail": reason, "weight": round(vote_weight, 2)}


@router.post("/api/mesh/report")
@limiter.limit("10/minute")
@requires_signed_write(kind=SignedWriteKind.MESH_REPORT)
async def mesh_report(request: Request):
    """Report abusive or fraudulent behavior (signed, public, non-anonymous)."""
    body = _signed_body(request)
    reporter_id = body.get("reporter_id", "")
    target_id = body.get("target_id", "")
    reason = body.get("reason", "")
    gate = body.get("gate", "")
    evidence = body.get("evidence", "")
    public_key = body.get("public_key", "")
    public_key_algo = body.get("public_key_algo", "")
    signature = body.get("signature", "")
    sequence = _safe_int(body.get("sequence", 0) or 0)
    protocol_version = body.get("protocol_version", "")

    if not reporter_id or not target_id or not reason:
        return {"ok": False, "detail": "Missing reporter_id, target_id, or reason"}

    report_payload = {"target_id": target_id, "reason": reason, "gate": gate, "evidence": evidence}

    try:
        from services.mesh.mesh_reputation import reputation_ledger

        reputation_ledger.register_node(reporter_id, public_key, public_key_algo)
    except Exception:
        pass

    try:
        from services.mesh.mesh_hashchain import infonet

        normalized_payload = normalize_payload("abuse_report", report_payload)
        infonet.append(
            event_type="abuse_report",
            node_id=reporter_id,
            payload=normalized_payload,
            signature=signature,
            sequence=sequence,
            public_key=public_key,
            public_key_algo=public_key_algo,
            protocol_version=protocol_version,
        )
    except Exception:
        logger.exception("failed to record abuse report on infonet")
        return {"ok": False, "detail": "report_record_failed"}

    return {"ok": True, "detail": "Report recorded"}


@router.get("/api/mesh/reputation")
@limiter.limit("60/minute")
async def mesh_reputation(request: Request, node_id: str = ""):
    """Get reputation for a single node.

    Public callers receive a summary-only view; authenticated audit callers may
    access the richer breakdown.
    """
    from services.mesh.mesh_reputation import reputation_ledger

    if not node_id:
        return {"ok": False, "detail": "Provide ?node_id=xxx"}
    return reputation_ledger.get_reputation_log(
        node_id,
        detailed=_scoped_view_authenticated(request, "mesh.audit"),
    )


@router.get("/api/mesh/reputation/batch")
@limiter.limit("60/minute")
async def mesh_reputation_batch(request: Request, node_id: list[str] = Query(default=[])):
    """Get overall public reputation for multiple public node IDs."""
    from services.mesh.mesh_reputation import reputation_ledger

    normalized: list[str] = []
    seen: set[str] = set()
    for raw in list(node_id or []):
        candidate = str(raw or "").strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        normalized.append(candidate)
        if len(normalized) >= 100:
            break
    if not normalized:
        return {"ok": False, "detail": "Provide at least one node_id", "reputations": {}}
    return {
        "ok": True,
        "reputations": {
            candidate: reputation_ledger.get_reputation(candidate).get("overall", 0) or 0
            for candidate in normalized
        },
    }


@router.get("/api/mesh/reputation/all", dependencies=[Depends(require_admin)])
@limiter.limit("30/minute")
async def mesh_reputation_all(request: Request):
    """Get all known node reputations."""
    from services.mesh.mesh_reputation import reputation_ledger

    return {"reputations": reputation_ledger.get_all_reputations()}


@router.post("/api/mesh/identity/rotate")
@limiter.limit("5/minute")
@requires_signed_write(kind=SignedWriteKind.IDENTITY_ROTATE)
async def mesh_identity_rotate(request: Request):
    """Link a new node_id to an old one via dual-signature rotation."""
    body = _signed_body(request)
    old_node_id = body.get("old_node_id", "").strip()
    old_public_key = body.get("old_public_key", "").strip()
    old_public_key_algo = body.get("old_public_key_algo", "").strip()
    old_signature = body.get("old_signature", "").strip()
    new_node_id = body.get("new_node_id", "").strip()
    new_public_key = body.get("new_public_key", "").strip()
    new_public_key_algo = body.get("new_public_key_algo", "").strip()
    new_signature = body.get("new_signature", "").strip()
    timestamp = _safe_int(body.get("timestamp", 0) or 0)
    sequence = _safe_int(body.get("sequence", 0) or 0)
    protocol_version = body.get("protocol_version", "").strip()

    if not (
        old_node_id
        and old_public_key
        and old_public_key_algo
        and old_signature
        and new_node_id
        and new_public_key
        and new_public_key_algo
        and new_signature
        and timestamp
    ):
        return {"ok": False, "detail": "Missing rotation fields"}
    if old_node_id == new_node_id:
        return {"ok": False, "detail": "old_node_id must differ from new_node_id"}
    if abs(timestamp - int(time.time())) > 7 * 86400:
        return {"ok": False, "detail": "Rotation timestamp is too far from current time"}

    rotation_payload = {
        "old_node_id": old_node_id,
        "old_public_key": old_public_key,
        "old_public_key_algo": old_public_key_algo,
        "new_public_key": new_public_key,
        "new_public_key_algo": new_public_key_algo,
        "timestamp": timestamp,
        "old_signature": old_signature,
    }

    old_sig_ok, old_sig_reason = verify_key_rotation_claim_signature(
        old_node_id=old_node_id,
        old_public_key=old_public_key,
        old_public_key_algo=old_public_key_algo,
        old_signature=old_signature,
        new_public_key=new_public_key,
        new_public_key_algo=new_public_key_algo,
        timestamp=timestamp,
    )
    if not old_sig_ok:
        return {"ok": False, "detail": old_sig_reason}

    from services.mesh.mesh_reputation import reputation_ledger

    reputation_ledger.register_node(new_node_id, new_public_key, new_public_key_algo)
    ok, reason = reputation_ledger.link_identities(old_node_id, new_node_id)
    if not ok:
        return {"ok": False, "detail": reason}

    # Record on Infonet
    try:
        from services.mesh.mesh_hashchain import infonet

        normalized_payload = normalize_payload("key_rotate", rotation_payload)
        infonet.append(
            event_type="key_rotate",
            node_id=new_node_id,
            payload=normalized_payload,
            signature=new_signature,
            sequence=sequence,
            public_key=new_public_key,
            public_key_algo=new_public_key_algo,
            protocol_version=protocol_version,
        )
    except Exception:
        pass

    return {"ok": True, "detail": "Identity linked"}


@router.post("/api/mesh/identity/revoke")
@limiter.limit("5/minute")
@requires_signed_write(kind=SignedWriteKind.IDENTITY_REVOKE)
async def mesh_identity_revoke(request: Request):
    """Revoke a node's key with a grace window."""
    body = _signed_body(request)
    node_id = body.get("node_id", "").strip()
    public_key = body.get("public_key", "").strip()
    public_key_algo = body.get("public_key_algo", "").strip()
    signature = body.get("signature", "").strip()
    revoked_at = _safe_int(body.get("revoked_at", 0) or 0)
    grace_until = _safe_int(body.get("grace_until", 0) or 0)
    reason = body.get("reason", "").strip()
    sequence = _safe_int(body.get("sequence", 0) or 0)
    protocol_version = body.get("protocol_version", "").strip()

    if not (node_id and public_key and public_key_algo and signature and revoked_at and grace_until):
        return {"ok": False, "detail": "Missing revocation fields"}

    now = int(time.time())
    max_grace = 7 * 86400
    if grace_until < revoked_at:
        return {"ok": False, "detail": "grace_until must be >= revoked_at"}
    if grace_until - revoked_at > max_grace:
        return {"ok": False, "detail": "Grace window too large (max 7 days)"}
    if abs(revoked_at - now) > max_grace:
        return {"ok": False, "detail": "revoked_at is too far from current time"}

    payload = {
        "revoked_public_key": public_key,
        "revoked_public_key_algo": public_key_algo,
        "revoked_at": revoked_at,
        "grace_until": grace_until,
        "reason": reason,
    }

    if payload["revoked_public_key"] != public_key:
        return {"ok": False, "detail": "revoked_public_key must match public_key"}
    if payload["revoked_public_key_algo"] != public_key_algo:
        return {"ok": False, "detail": "revoked_public_key_algo must match public_key_algo"}

    try:
        from services.mesh.mesh_hashchain import infonet

        normalized_payload = normalize_payload("key_revoke", payload)
        infonet.append(
            event_type="key_revoke",
            node_id=node_id,
            payload=normalized_payload,
            signature=signature,
            sequence=sequence,
            public_key=public_key,
            public_key_algo=public_key_algo,
            protocol_version=protocol_version,
        )
    except Exception:
        logger.exception("failed to record key revocation on infonet")
        return {"ok": False, "detail": "revocation_record_failed"}

    return {"ok": True, "detail": "Identity revoked"}


# ─── Gate Endpoints ───────────────────────────────────────────────────────


@router.post("/api/mesh/gate/create")
@limiter.limit("5/hour")
@requires_signed_write(kind=SignedWriteKind.GATE_CREATE)
async def gate_create(request: Request):
    """Create a new reputation-gated community.

    Body: {creator_id, creator_pubkey?, creator_sig?, gate_id, display_name, rules?: {min_overall_rep, min_gate_rep}}
    """
    from services.mesh.mesh_reputation import (
        ALLOW_DYNAMIC_GATES,
        reputation_ledger,
        gate_manager,
    )

    if not ALLOW_DYNAMIC_GATES:
        return {"ok": False, "detail": "Gate creation is disabled for the fixed private launch catalog"}

    body = _signed_body(request)
    creator_id = body.get("creator_id", "")
    gate_id = body.get("gate_id", "")
    display_name = body.get("display_name", gate_id)
    rules = body.get("rules", {})
    public_key = body.get("creator_pubkey", "")
    public_key_algo = body.get("public_key_algo", "")
    signature = body.get("creator_sig", "")
    sequence = _safe_int(body.get("sequence", 0) or 0)
    protocol_version = body.get("protocol_version", "")

    if not creator_id or not gate_id:
        return {"ok": False, "detail": "Missing creator_id or gate_id"}

    gate_payload = {"gate_id": gate_id, "display_name": display_name, "rules": rules}

    reputation_ledger.register_node(creator_id, public_key, public_key_algo)

    ok, reason = gate_manager.create_gate(
        creator_id,
        gate_id,
        display_name,
        min_overall_rep=rules.get("min_overall_rep", 0),
        min_gate_rep=rules.get("min_gate_rep"),
    )

    # Record on Infonet
    if ok:
        try:
            from services.mesh.mesh_hashchain import infonet

            normalized_payload = normalize_payload("gate_create", gate_payload)
            infonet.append(
                event_type="gate_create",
                node_id=creator_id,
                payload=normalized_payload,
                signature=signature,
                sequence=sequence,
                public_key=public_key,
                public_key_algo=public_key_algo,
                protocol_version=protocol_version,
            )
        except Exception:
            pass

    return {"ok": ok, "detail": reason}


@router.get("/api/mesh/gate/list")
@limiter.limit("30/minute")
async def gate_list(request: Request):
    """List all known gates (public catalog — secrets are never included)."""
    from services.mesh.mesh_reputation import gate_manager

    return {"gates": gate_manager.list_gates()}


@router.get("/api/mesh/gate/{gate_id}")
@limiter.limit("30/minute")
async def gate_detail(request: Request, gate_id: str):
    """Get gate details including ratification status."""
    from services.mesh.mesh_reputation import gate_manager

    gate = gate_manager.get_gate(gate_id)
    if not gate:
        return {"ok": False, "detail": f"Gate '{gate_id}' not found"}
    gate["ratification"] = gate_manager.get_ratification_status(gate_id)
    return gate


@router.post("/api/mesh/gate/{gate_id}/message")
@limiter.limit("10/minute")
@requires_signed_write(kind=SignedWriteKind.GATE_MESSAGE)
async def gate_message(request: Request, gate_id: str):
    """Post a message to a gate. Checks entry rules against sender's reputation.

    Body: {sender_id, ciphertext, nonce, sender_ref, signature?}
    """
    body = _signed_body(request)
    return _submit_gate_message_envelope(request, gate_id, body)


def _submit_gate_message_envelope(request: Request, gate_id: str, body: dict[str, Any]) -> dict[str, Any]:
    import main as _m

    return _m._submit_gate_message_envelope(request, gate_id, body)


# ─── Infonet Endpoints ───────────────────────────────────────────────────


@router.get("/api/mesh/infonet/status")
@limiter.limit("30/minute")
async def infonet_status(request: Request, verify_signatures: bool = False):
    """Get Infonet metadata — event counts, head hash, chain size."""
    from services.mesh.mesh_hashchain import infonet
    from services.wormhole_supervisor import get_wormhole_state

    info = infonet.get_info()
    valid, reason = infonet.validate_chain(verify_signatures=verify_signatures)
    try:
        wormhole = get_wormhole_state()
    except Exception:
        wormhole = {"configured": False, "ready": False, "rns_ready": False}
    info["valid"] = valid
    info["validation"] = reason
    info["verify_signatures"] = verify_signatures
    info["private_lane_tier"] = _current_private_lane_tier(wormhole)
    info["private_lane_policy"] = _private_infonet_policy_snapshot()
    info.update(_node_runtime_snapshot())
    return _redact_private_lane_control_fields(
        info,
        authenticated=_scoped_view_authenticated(request, "mesh.audit"),
    )


@router.get("/api/mesh/infonet/merkle")
@limiter.limit("30/minute")
async def infonet_merkle(request: Request):
    """Merkle root for sync comparison."""
    from services.mesh.mesh_hashchain import infonet

    return {
        "merkle_root": infonet.get_merkle_root(),
        "head_hash": infonet.head_hash,
        "count": len(infonet.events),
        "network_id": infonet.get_info().get("network_id"),
    }


@router.get("/api/mesh/infonet/locator")
@limiter.limit("30/minute")
async def infonet_locator(request: Request, limit: int = Query(32, ge=4, le=128)):
    """Block locator for fork-aware sync."""
    from services.mesh.mesh_hashchain import infonet

    locator = infonet.get_locator(max_entries=limit)
    return {
        "locator": locator,
        "head_hash": infonet.head_hash,
        "count": len(infonet.events),
        "network_id": infonet.get_info().get("network_id"),
    }


@router.post("/api/mesh/infonet/sync")
@limiter.limit("30/minute")
@mesh_write_exempt(MeshWriteExemption.PEER_GOSSIP)
async def infonet_sync_post(
    request: Request,
    limit: int = Query(100, ge=1, le=500),
):
    """Fork-aware sync using a block locator."""
    from services.mesh.mesh_hashchain import infonet, GENESIS_HASH

    body = await request.json()
    req_proto = str(body.get("protocol_version", "") or "")
    if req_proto and req_proto != PROTOCOL_VERSION:
        return Response(
            content=json_mod.dumps(
                {
                    "ok": False,
                    "detail": "Unsupported protocol_version",
                    "protocol_version": PROTOCOL_VERSION,
                }
            ),
            status_code=426,
            media_type="application/json",
        )
    locator = body.get("locator", [])
    if not isinstance(locator, list):
        return {"ok": False, "detail": "locator must be a list"}
    expected_head = str(body.get("expected_head", "") or "")
    if expected_head and expected_head != infonet.head_hash:
        return Response(
            content=json_mod.dumps(
                {
                    "ok": False,
                    "detail": "head_hash mismatch",
                    "head_hash": infonet.head_hash,
                    "expected_head": expected_head,
                }
            ),
            status_code=409,
            media_type="application/json",
        )
    if "limit" in body:
        try:
            limit = max(1, min(500, _safe_int(body["limit"], 0)))
        except Exception:
            pass

    matched_hash, start_index, events = infonet.get_events_after_locator(locator, limit=limit)
    forked = False
    if not matched_hash:
        forked = True
    elif matched_hash == GENESIS_HASH and len(locator) > 1:
        forked = True

    # Filter out legacy gate_message events — not part of the public sync surface.
    events = [_redact_public_event(e) for e in events if e.get("event_type") != "gate_message"]

    response = {
        "events": events,
        "matched_hash": matched_hash,
        "forked": forked,
        "head_hash": infonet.head_hash,
        "count": len(events),
        "protocol_version": PROTOCOL_VERSION,
    }
    if body.get("include_proofs"):
        proofs = infonet.get_merkle_proofs(start_index, len(events)) if start_index >= 0 else {}
        response.update(
            {
                "merkle_root": proofs.get("root", infonet.get_merkle_root()),
                "merkle_total": proofs.get("total", len(infonet.events)),
                "merkle_start": proofs.get("start", 0),
                "merkle_proofs": proofs.get("proofs", []),
            }
        )
    return response


@router.get("/api/mesh/metrics")
@limiter.limit("30/minute")
async def mesh_metrics(request: Request):
    """Mesh protocol health counters."""
    from services.mesh.mesh_metrics import snapshot

    ok, detail = _check_scoped_auth(request, "mesh.audit")
    if not ok:
        if detail == "insufficient scope":
            raise HTTPException(status_code=403, detail="Forbidden — insufficient scope")
        raise HTTPException(status_code=403, detail=detail)
    return snapshot()


@router.get("/api/mesh/rns/status")
@limiter.limit("30/minute")
async def mesh_rns_status(request: Request):
    from services.wormhole_supervisor import get_wormhole_state

    try:
        from services.mesh.mesh_rns import rns_bridge

        status = await asyncio.to_thread(rns_bridge.status)
    except Exception:
        status = {"enabled": False, "ready": False, "configured_peers": 0, "active_peers": 0}
    try:
        wormhole = get_wormhole_state()
    except Exception:
        wormhole = {"configured": False, "ready": False, "rns_ready": False}
    status["private_lane_tier"] = _current_private_lane_tier(wormhole)
    status["private_lane_policy"] = _private_infonet_policy_snapshot()
    return _redact_public_rns_status(
        status,
        authenticated=_scoped_view_authenticated(request, "mesh.audit"),
    )


@router.get("/api/mesh/infonet/sync")
@limiter.limit("30/minute")
async def infonet_sync(
    request: Request,
    after_hash: str = "",
    limit: int = Query(100, ge=1, le=500),
    expected_head: str = "",
    protocol_version: str = "",
):
    """Return events after a given hash (delta sync)."""
    from services.mesh.mesh_hashchain import infonet, GENESIS_HASH

    if protocol_version and protocol_version != PROTOCOL_VERSION:
        return Response(
            content=json_mod.dumps(
                {
                    "ok": False,
                    "detail": "Unsupported protocol_version",
                    "protocol_version": PROTOCOL_VERSION,
                }
            ),
            status_code=426,
            media_type="application/json",
        )
    if expected_head and expected_head != infonet.head_hash:
        return Response(
            content=json_mod.dumps(
                {
                    "ok": False,
                    "detail": "head_hash mismatch",
                    "head_hash": infonet.head_hash,
                    "expected_head": expected_head,
                }
            ),
            status_code=409,
            media_type="application/json",
        )
    base = after_hash or GENESIS_HASH
    events = infonet.get_events_after(base, limit=limit)
    # Filter out legacy gate_message events — not part of the public sync surface.
    events = [_redact_public_event(e) for e in events if e.get("event_type") != "gate_message"]
    return {
        "events": events,
        "after_hash": base,
        "count": len(events),
        "protocol_version": PROTOCOL_VERSION,
    }


@router.post("/api/mesh/infonet/ingest", dependencies=[Depends(require_admin)])
@limiter.limit("10/minute")
@mesh_write_exempt(MeshWriteExemption.ADMIN_CONTROL)
async def infonet_ingest(request: Request):
    """Ingest externally sourced Infonet events (strict verification)."""
    from services.mesh.mesh_hashchain import infonet

    body = await request.json()
    events = body.get("events", [])
    expected_head = str(body.get("expected_head", "") or "")
    if expected_head and expected_head != infonet.head_hash:
        return Response(
            content=json_mod.dumps(
                {
                    "ok": False,
                    "detail": "head_hash mismatch",
                    "head_hash": infonet.head_hash,
                    "expected_head": expected_head,
                }
            ),
            status_code=409,
            media_type="application/json",
        )
    if not isinstance(events, list):
        return {"ok": False, "detail": "events must be a list"}
    if len(events) > 200:
        return {"ok": False, "detail": "Too many events in one ingest batch"}

    result = infonet.ingest_events(events)
    _hydrate_gate_store_from_chain(events)
    return {"ok": True, **result}



# ---------------------------------------------------------------------------
# Peer Management API — operator endpoints for adding / removing / listing
# peers without editing peer_store.json by hand.
# ---------------------------------------------------------------------------


@router.get("/api/mesh/peers", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def list_peers(request: Request, bucket: str = Query(None)):
    """List all peers (or filter by bucket: sync, push, bootstrap)."""
    from services.mesh.mesh_peer_store import DEFAULT_PEER_STORE_PATH, PeerStore

    store = PeerStore(DEFAULT_PEER_STORE_PATH)
    try:
        store.load()
    except Exception as exc:
        return {"ok": False, "detail": f"Failed to load peer store: {exc}"}

    if bucket:
        records = store.records_for_bucket(bucket)
    else:
        records = store.records()

    return {
        "ok": True,
        "count": len(records),
        "peers": [r.to_dict() for r in records],
    }


@router.post("/api/mesh/peers", dependencies=[Depends(require_local_operator)])
@limiter.limit("10/minute")
@mesh_write_exempt(MeshWriteExemption.LOCAL_OPERATOR_ONLY)
async def add_peer(request: Request):
    """Add a peer to the store. Body: {peer_url, transport?, label?, role?, buckets?[]}."""
    from services.mesh.mesh_crypto import normalize_peer_url
    from services.mesh.mesh_peer_store import (
        DEFAULT_PEER_STORE_PATH,
        PeerStore,
        PeerStoreError,
        make_push_peer_record,
        make_sync_peer_record,
    )
    from services.mesh.mesh_router import peer_transport_kind

    body = await request.json()
    peer_url_raw = str(body.get("peer_url", "") or "").strip()
    if not peer_url_raw:
        return {"ok": False, "detail": "peer_url is required"}

    peer_url = normalize_peer_url(peer_url_raw)
    if not peer_url:
        return {"ok": False, "detail": "Invalid peer_url"}

    transport = str(body.get("transport", "") or "").strip().lower()
    if not transport:
        transport = peer_transport_kind(peer_url)
    if not transport:
        return {"ok": False, "detail": "Cannot determine transport for peer_url — provide transport explicitly"}

    label = str(body.get("label", "") or "").strip()
    role = str(body.get("role", "") or "").strip().lower() or "relay"
    buckets = body.get("buckets", ["sync", "push"])
    if isinstance(buckets, str):
        buckets = [buckets]
    if not isinstance(buckets, list):
        buckets = ["sync", "push"]

    store = PeerStore(DEFAULT_PEER_STORE_PATH)
    try:
        store.load()
    except Exception:
        store = PeerStore(DEFAULT_PEER_STORE_PATH)

    added: list[str] = []
    try:
        for b in buckets:
            b = str(b).strip().lower()
            if b == "sync":
                store.upsert(make_sync_peer_record(peer_url=peer_url, transport=transport, role=role, label=label))
                added.append("sync")
            elif b == "push":
                store.upsert(make_push_peer_record(peer_url=peer_url, transport=transport, role=role, label=label))
                added.append("push")
        store.save()
    except PeerStoreError as exc:
        return {"ok": False, "detail": str(exc)}

    return {"ok": True, "peer_url": peer_url, "buckets": added}


@router.delete("/api/mesh/peers", dependencies=[Depends(require_local_operator)])
@limiter.limit("10/minute")
@mesh_write_exempt(MeshWriteExemption.LOCAL_OPERATOR_ONLY)
async def remove_peer(request: Request):
    """Remove a peer. Body: {peer_url, bucket?}. If bucket omitted, removes from all buckets."""
    from services.mesh.mesh_crypto import normalize_peer_url
    from services.mesh.mesh_peer_store import DEFAULT_PEER_STORE_PATH, PeerStore

    body = await request.json()
    peer_url_raw = str(body.get("peer_url", "") or "").strip()
    if not peer_url_raw:
        return {"ok": False, "detail": "peer_url is required"}

    peer_url = normalize_peer_url(peer_url_raw)
    if not peer_url:
        return {"ok": False, "detail": "Invalid peer_url"}

    bucket_filter = str(body.get("bucket", "") or "").strip().lower()

    store = PeerStore(DEFAULT_PEER_STORE_PATH)
    try:
        store.load()
    except Exception:
        return {"ok": False, "detail": "Failed to load peer store"}

    removed: list[str] = []
    for b in ["bootstrap", "sync", "push"]:
        if bucket_filter and b != bucket_filter:
            continue
        key = f"{b}:{peer_url}"
        if key in store._records:
            del store._records[key]
            removed.append(b)

    if not removed:
        return {"ok": False, "detail": "Peer not found in any bucket"}

    store.save()
    return {"ok": True, "peer_url": peer_url, "removed_from": removed}


@router.patch("/api/mesh/peers", dependencies=[Depends(require_local_operator)])
@limiter.limit("10/minute")
@mesh_write_exempt(MeshWriteExemption.LOCAL_OPERATOR_ONLY)
async def toggle_peer(request: Request):
    """Enable or disable a peer. Body: {peer_url, bucket, enabled: bool}."""
    from services.mesh.mesh_crypto import normalize_peer_url
    from services.mesh.mesh_peer_store import DEFAULT_PEER_STORE_PATH, PeerRecord, PeerStore

    body = await request.json()
    peer_url_raw = str(body.get("peer_url", "") or "").strip()
    bucket = str(body.get("bucket", "") or "").strip().lower()
    enabled = body.get("enabled")

    if not peer_url_raw:
        return {"ok": False, "detail": "peer_url is required"}
    if not bucket:
        return {"ok": False, "detail": "bucket is required"}
    if enabled is None:
        return {"ok": False, "detail": "enabled (true/false) is required"}

    peer_url = normalize_peer_url(peer_url_raw)
    if not peer_url:
        return {"ok": False, "detail": "Invalid peer_url"}

    store = PeerStore(DEFAULT_PEER_STORE_PATH)
    try:
        store.load()
    except Exception:
        return {"ok": False, "detail": "Failed to load peer store"}

    key = f"{bucket}:{peer_url}"
    record = store._records.get(key)
    if not record:
        return {"ok": False, "detail": f"Peer not found in {bucket} bucket"}

    updated = PeerRecord(**{**record.to_dict(), "enabled": bool(enabled), "updated_at": int(time.time())})
    store._records[key] = updated
    store.save()

    return {"ok": True, "peer_url": peer_url, "bucket": bucket, "enabled": bool(enabled)}


@router.put("/api/mesh/gate/{gate_id}/envelope_policy")
@limiter.limit("10/minute")
@mesh_write_exempt(MeshWriteExemption.ADMIN_CONTROL)
async def set_gate_envelope_policy(request: Request, gate_id: str):
    """Set the envelope_policy for a gate. Requires gate admin scope."""
    ok, detail = _check_scoped_auth(request, "gate")
    if not ok:
        return Response(
            content='{"ok":false,"detail":"Gate admin scope required"}',
            status_code=403,
            media_type="application/json",
        )
    try:
        body = await request.json()
    except Exception:
        return {"ok": False, "detail": "Invalid JSON body"}
    policy = str(body.get("envelope_policy", "") or "").strip()
    acknowledge_recovery_risk = bool(body.get("acknowledge_recovery_risk", False))
    from services.mesh.mesh_reputation import gate_manager, VALID_ENVELOPE_POLICIES
    if policy not in VALID_ENVELOPE_POLICIES:
        return {"ok": False, "detail": f"Invalid policy: must be one of {VALID_ENVELOPE_POLICIES}"}
    success, msg = gate_manager.set_envelope_policy(
        gate_id,
        policy,
        acknowledge_recovery_risk=acknowledge_recovery_risk,
    )
    return {"ok": success, "detail": msg}


@router.put("/api/mesh/gate/{gate_id}/legacy_envelope_fallback")
@limiter.limit("10/minute")
@mesh_write_exempt(MeshWriteExemption.ADMIN_CONTROL)
async def set_gate_legacy_envelope_fallback(request: Request, gate_id: str):
    """Set legacy_envelope_fallback for a gate. Requires gate admin scope."""
    ok, detail = _check_scoped_auth(request, "gate")
    if not ok:
        return Response(
            content='{"ok":false,"detail":"Gate admin scope required"}',
            status_code=403,
            media_type="application/json",
        )
    try:
        body = await request.json()
    except Exception:
        return {"ok": False, "detail": "Invalid JSON body"}
    raw = body.get("legacy_envelope_fallback")
    acknowledge_legacy_risk = body.get("acknowledge_legacy_risk", False)
    if raw is None or not isinstance(raw, bool):
        return {"ok": False, "detail": "legacy_envelope_fallback must be a boolean"}
    if acknowledge_legacy_risk is not None and not isinstance(acknowledge_legacy_risk, bool):
        return {"ok": False, "detail": "acknowledge_legacy_risk must be a boolean"}
    from services.mesh.mesh_reputation import gate_manager
    success, msg = gate_manager.set_legacy_envelope_fallback(
        gate_id,
        raw,
        acknowledge_legacy_risk=bool(acknowledge_legacy_risk),
    )
    return {"ok": success, "detail": msg}


@router.get("/api/mesh/gate/{gate_id}/messages")
@limiter.limit("60/minute")
async def gate_messages(
    request: Request,
    gate_id: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """Get encrypted gate messages from private store (newest first). Requires gate membership."""
    access = _verify_gate_access(request, gate_id)
    if not access:
        return await _private_plane_refusal_response(
            request,
            status_code=403,
            payload=_private_plane_access_denied_payload(),
        )
    return _build_gate_message_response(gate_id, access, limit=limit, offset=offset)


def _build_gate_message_response(
    gate_id: str,
    access: str,
    *,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    from services.mesh.mesh_hashchain import gate_store
    from services.mesh.mesh_reputation import gate_manager

    raw_messages, cursor = gate_store.get_messages_with_cursor(gate_id, limit=limit, offset=offset)
    safe_messages = [_strip_gate_for_access(m, access) for m in raw_messages]
    if gate_id and not safe_messages:
        gate_meta = gate_manager.get_gate(gate_id)
        if gate_meta:
            welcome_text = str(gate_meta.get("welcome") or gate_meta.get("description") or "").strip()
            if welcome_text:
                safe_messages = [
                    {
                        "event_id": f"seed_{gate_id}_welcome",
                        "event_type": "gate_notice",
                        "node_id": "!sb_gate",
                        "message": welcome_text,
                        "gate": gate_id,
                        "timestamp": int(gate_meta.get("created_at") or time.time()),
                        "sequence": 0,
                        "ephemeral": False,
                        "system_seed": True,
                        "fixed_gate": bool(gate_meta.get("fixed", False)),
                    }
                ]
    return {"messages": safe_messages, "count": len(safe_messages), "gate": gate_id, "cursor": cursor}


def _gate_session_stream_enabled() -> bool:
    try:
        return bool(get_settings().MESH_GATE_SESSION_STREAM_ENABLED)
    except Exception:
        return False


def _gate_session_stream_heartbeat_s() -> int:
    try:
        return max(1, int(get_settings().MESH_GATE_SESSION_STREAM_HEARTBEAT_S or 20))
    except Exception:
        return 20


def _gate_session_stream_batch_ms() -> int:
    try:
        return max(250, int(get_settings().MESH_GATE_SESSION_STREAM_BATCH_MS or 1500))
    except Exception:
        return 1500


def _gate_session_stream_max_gates() -> int:
    try:
        return max(1, int(get_settings().MESH_GATE_SESSION_STREAM_MAX_GATES or 16))
    except Exception:
        return 16


def _normalize_gate_session_stream_gates(raw: str, limit: int) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for gate_id in str(raw or "").split(","):
        candidate = str(gate_id or "").strip().lower()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        normalized.append(candidate)
        if len(normalized) >= limit:
            break
    return normalized


def _format_gate_session_stream_event(event: str, data: dict[str, Any]) -> str:
    payload = json_mod.dumps(data, default=str)
    return f"event: {event}\ndata: {payload}\n\n"


def _build_gate_session_stream_gate_access(gate_id: str) -> dict[str, Any] | None:
    proof = _sign_gate_access_proof(gate_id)
    if not proof.get("ok"):
        return None
    node_id = str(proof.get("node_id") or "").strip()
    gate_proof = str(proof.get("proof") or "").strip()
    gate_ts = str(proof.get("ts") or "").strip()
    if not node_id or not gate_proof or not gate_ts:
        return None
    return {
        "node_id": node_id,
        "proof": gate_proof,
        "ts": gate_ts,
    }


def _build_gate_session_stream_gate_key_status(gate_id: str) -> dict[str, Any]:
    from services.mesh.mesh_gate_mls import get_local_gate_key_status

    status = get_local_gate_key_status(gate_id)
    if not isinstance(status, dict):
        return {"ok": False, "gate_id": gate_id, "detail": "gate_key_status_unavailable"}
    return dict(status)


@router.get("/api/mesh/infonet/messages")
@limiter.limit("60/minute")
async def infonet_messages(
    request: Request,
    gate: str = "",
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """Browse messages on the Infonet (newest first). Optional gate filter."""
    from services.mesh.mesh_hashchain import infonet

    if gate:
        access = _verify_gate_access(request, gate)
        if not access:
            return await _private_plane_refusal_response(
                request,
                status_code=403,
                payload=_private_plane_access_denied_payload(),
            )
        return _build_gate_message_response(gate, access, limit=limit, offset=offset)
    else:
        messages = infonet.get_messages(gate_id="", limit=limit, offset=offset)
        messages = [m for m in messages if m.get("event_type") != "gate_message"]
        messages = [_redact_public_event(m) for m in messages]
    return {"messages": messages, "count": len(messages), "gate": gate or "all", "cursor": 0}


@router.get("/api/mesh/infonet/messages/wait")
@limiter.limit("60/minute")
async def infonet_messages_wait(
    request: Request,
    gate: str = "",
    after: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    timeout_ms: int = Query(25_000, ge=1_000, le=90_000),
):
    """Wait for gate message changes, then return the latest gate view."""
    gate_id = str(gate or "").strip().lower()
    if not gate_id:
        return Response(
            content='{"ok":false,"detail":"gate required"}',
            status_code=400,
            media_type="application/json",
        )
    access = _verify_gate_access(request, gate_id)
    if not access:
        return await _private_plane_refusal_response(
            request,
            status_code=403,
            payload=_private_plane_access_denied_payload(),
        )
    from services.mesh.mesh_hashchain import gate_store

    changed, _cursor = await asyncio.to_thread(
        gate_store.wait_for_gate_change,
        gate_id,
        after,
        timeout_ms / 1000.0,
    )
    payload = _build_gate_message_response(gate_id, access, limit=limit, offset=0)
    payload["changed"] = bool(changed)
    return payload


@router.get("/api/mesh/infonet/session-stream", dependencies=[Depends(require_admin)])
@limiter.limit("30/minute")
async def infonet_session_stream(
    request: Request,
    gates: str = Query(""),
):
    """Feature-flagged session-level gate stream for multiplexed room updates.

    Current behavior:
    - admin-gated control-plane access
    - immediate hello event with normalized subscriptions and gate bootstrap context
    - gate_update events for subscribed rooms
    - coarse heartbeats and reconnect-friendly session state
    """
    if not _gate_session_stream_enabled():
        return JSONResponse(
            status_code=404,
            content={"ok": False, "detail": "gate_session_stream_disabled"},
        )

    heartbeat_s = _gate_session_stream_heartbeat_s()
    batch_ms = _gate_session_stream_batch_ms()
    max_gates = _gate_session_stream_max_gates()
    subscriptions = _normalize_gate_session_stream_gates(gates, max_gates)
    session_id = secrets.token_hex(8)
    from services.mesh.mesh_hashchain import gate_store

    cursors = {
        gate_id: gate_store.gate_cursor(gate_id)
        for gate_id in subscriptions
    }
    gate_access = {
        gate_id: access
        for gate_id in subscriptions
        for access in [_build_gate_session_stream_gate_access(gate_id)]
        if access
    }
    gate_key_status = {
        gate_id: _build_gate_session_stream_gate_key_status(gate_id)
        for gate_id in subscriptions
    }

    async def event_stream():
        try:
            yield _format_gate_session_stream_event(
                "hello",
                {
                    "ok": True,
                    "mode": "skeleton",
                    "transport": "sse",
                    "session_id": session_id,
                    "subscriptions": subscriptions,
                    "cursors": cursors,
                    "gate_access": gate_access,
                    "gate_key_status": gate_key_status,
                    "heartbeat_s": heartbeat_s,
                    "batch_ms": batch_ms,
                },
            )
            last_heartbeat = time.monotonic()
            while True:
                if await request.is_disconnected():
                    break
                updates = await asyncio.to_thread(
                    gate_store.wait_for_any_gate_change,
                    cursors,
                    batch_ms / 1000.0,
                )
                if await request.is_disconnected():
                    break
                if updates:
                    update_list = [
                        {"gate_id": gate_id, "cursor": cursor}
                        for gate_id, cursor in sorted(updates.items())
                    ]
                    cursors.update({gate_id: cursor for gate_id, cursor in updates.items()})
                    yield _format_gate_session_stream_event(
                        "gate_update",
                        {
                            "session_id": session_id,
                            "updates": update_list,
                            "ts": int(time.time()),
                        },
                    )
                now = time.monotonic()
                if now - last_heartbeat >= heartbeat_s:
                    yield _format_gate_session_stream_event(
                        "heartbeat",
                        {
                            "session_id": session_id,
                            "ts": int(time.time()),
                        },
                    )
                    last_heartbeat = now
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/mesh/infonet/event/{event_id}")
@limiter.limit("60/minute")
async def infonet_event(request: Request, event_id: str):
    """Look up a single Infonet event by ID."""
    from services.mesh.mesh_hashchain import gate_store, infonet

    evt = infonet.get_event(event_id)
    if not evt:
        evt = gate_store.get_event(event_id)
        if evt:
            gate_id = str(evt.get("payload", {}).get("gate", "") or evt.get("gate", "") or "").strip()
            access = _verify_gate_access(request, gate_id) if gate_id else ""
            if not gate_id or not access:
                return await _private_plane_refusal_response(
                    request,
                    status_code=403,
                    payload=_private_plane_access_denied_payload(),
                )
            return _strip_gate_for_access(evt, access)
        return {"ok": False, "detail": "Event not found"}
    if evt.get("event_type") == "gate_message":
        gate_id = str(evt.get("payload", {}).get("gate", "") or evt.get("gate", "") or "").strip()
        access = _verify_gate_access(request, gate_id) if gate_id else ""
        if not gate_id or not access:
            return await _private_plane_refusal_response(
                request,
                status_code=403,
                payload=_private_plane_access_denied_payload(),
            )
        return _strip_gate_for_access(evt, access)
    return _redact_public_event(infonet.decorate_event(evt))


@router.get("/api/mesh/infonet/node/{node_id}")
@limiter.limit("30/minute")
async def infonet_node_events(
    request: Request,
    node_id: str,
    limit: int = Query(20, ge=1, le=100),
):
    """Get recent Infonet events by a specific node."""
    from services.mesh.mesh_hashchain import infonet

    events = infonet.get_events_by_node(node_id, limit=limit)
    events = [e for e in events if e.get("event_type") != "gate_message"]
    events = [_redact_public_event(e) for e in infonet.decorate_events(events)]
    events = _redact_public_node_history(
        events,
        authenticated=_scoped_view_authenticated(request, "mesh.audit"),
    )
    return {"events": events, "count": len(events), "node_id": node_id}


@router.get("/api/mesh/infonet/events")
@limiter.limit("30/minute")
async def infonet_events_by_type(
    request: Request,
    event_type: str = "",
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """Get recent Infonet events, optionally filtered by type."""
    from services.mesh.mesh_hashchain import infonet

    if event_type:
        events = infonet.get_events_by_type(event_type, limit=limit, offset=offset)
    else:
        events = list(reversed(infonet.events))
        events = events[offset : offset + limit]
    events = [e for e in events if e.get("event_type") != "gate_message"]
    events = [_redact_public_event(e) for e in infonet.decorate_events(events)]
    return {
        "events": events,
        "count": len(events),
        "event_type": event_type or "all",
    }

