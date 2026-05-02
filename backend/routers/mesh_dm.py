import asyncio
import hashlib
import hmac
import logging
import secrets
import time
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from auth import (
    _is_debug_test_request,
    _scoped_view_authenticated,
    _verify_peer_push_hmac,
    require_admin,
)
from limiter import limiter
from services.config import get_settings
from services.mesh.mesh_compatibility import (
    LEGACY_AGENT_ID_LOOKUP_TARGET,
    legacy_agent_id_lookup_blocked,
    record_legacy_agent_id_lookup,
    sunset_target_label,
)
from services.mesh.mesh_signed_events import (
    MeshWriteExemption,
    SignedWriteKind,
    get_prepared_signed_write,
    mesh_write_exempt,
    requires_signed_write,
)

logger = logging.getLogger(__name__)
_WARNED_LEGACY_DM_PUBKEY_LOOKUPS: set[str] = set()

router = APIRouter()


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------

def _safe_int(val, default=0):
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _warn_legacy_dm_pubkey_lookup(agent_id: str) -> None:
    peer_id = str(agent_id or "").strip().lower()
    if not peer_id or peer_id in _WARNED_LEGACY_DM_PUBKEY_LOOKUPS:
        return
    _WARNED_LEGACY_DM_PUBKEY_LOOKUPS.add(peer_id)
    logger.warning(
        "mesh legacy DH pubkey lookup used for %s via direct agent_id; prefer invite-scoped lookup handles before removal in %s",
        peer_id,
        sunset_target_label(LEGACY_AGENT_ID_LOOKUP_TARGET),
    )


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


_verify_signed_write = _main_delegate("_verify_signed_write")
_secure_dm_enabled = _main_delegate("_secure_dm_enabled")
_legacy_dm_get_allowed = _main_delegate("_legacy_dm_get_allowed")
_rns_private_dm_ready = _main_delegate("_rns_private_dm_ready")
_anonymous_dm_hidden_transport_enforced = _main_delegate("_anonymous_dm_hidden_transport_enforced")
_high_privacy_profile_enabled = _main_delegate("_high_privacy_profile_enabled")
_dm_send_from_signed_request = _main_delegate("_dm_send_from_signed_request")
_dm_poll_secure_from_signed_request = _main_delegate("_dm_poll_secure_from_signed_request")
_dm_count_secure_from_signed_request = _main_delegate("_dm_count_secure_from_signed_request")
_validate_private_signed_sequence = _main_delegate("_validate_private_signed_sequence")


def _signed_body(request: Request) -> dict[str, Any]:
    prepared = get_prepared_signed_write(request)
    if prepared is None:
        return {}
    return dict(prepared.body)


async def _maybe_apply_dm_relay_jitter() -> None:
    if not _high_privacy_profile_enabled():
        return
    await asyncio.sleep((50 + secrets.randbelow(451)) / 1000.0)


_REQUEST_V2_REDUCED_VERSION = "request-v2-reduced-v3"
_REQUEST_V2_RECOVERY_STATES = {"pending", "verified", "failed"}


def _is_canonical_reduced_request_message(message: dict[str, Any]) -> bool:
    item = dict(message or {})
    return (
        str(item.get("delivery_class", "") or "").strip().lower() == "request"
        and str(item.get("request_contract_version", "") or "").strip()
        == _REQUEST_V2_REDUCED_VERSION
        and item.get("sender_recovery_required") is True
    )


def _annotate_request_recovery_message(message: dict[str, Any]) -> dict[str, Any]:
    item = dict(message or {})
    delivery_class = str(item.get("delivery_class", "") or "").strip().lower()
    sender_id = str(item.get("sender_id", "") or "").strip()
    sender_seal = str(item.get("sender_seal", "") or "").strip()
    sender_is_blinded = sender_id.startswith("sealed:") or sender_id.startswith("sender_token:")
    if delivery_class != "request" or not sender_is_blinded or not sender_seal.startswith("v3:"):
        return item
    if not str(item.get("request_contract_version", "") or "").strip():
        item["request_contract_version"] = _REQUEST_V2_REDUCED_VERSION
    item["sender_recovery_required"] = True
    state = str(item.get("sender_recovery_state", "") or "").strip().lower()
    if state not in _REQUEST_V2_RECOVERY_STATES:
        state = "pending"
    item["sender_recovery_state"] = state
    return item


def _annotate_request_recovery_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_annotate_request_recovery_message(message) for message in (messages or [])]


def _request_duplicate_authority_rank(message: dict[str, Any]) -> int:
    item = dict(message or {})
    if str(item.get("delivery_class", "") or "").strip().lower() != "request":
        return 0
    if _is_canonical_reduced_request_message(item):
        return 3
    sender_id = str(item.get("sender_id", "") or "").strip()
    if sender_id.startswith("sealed:") or sender_id.startswith("sender_token:"):
        return 1
    if sender_id:
        return 2
    return 0


def _request_duplicate_recovery_rank(message: dict[str, Any]) -> int:
    if not _is_canonical_reduced_request_message(message):
        return 0
    state = str(dict(message or {}).get("sender_recovery_state", "") or "").strip().lower()
    if state == "verified":
        return 2
    if state == "pending":
        return 1
    return 0


def _poll_duplicate_source_rank(source: str) -> int:
    normalized = str(source or "").strip().lower()
    if normalized == "relay":
        return 2
    if normalized == "reticulum":
        return 1
    return 0


def _should_replace_dm_poll_duplicate(
    existing: dict[str, Any],
    existing_source: str,
    candidate: dict[str, Any],
    candidate_source: str,
) -> bool:
    candidate_authority = _request_duplicate_authority_rank(candidate)
    existing_authority = _request_duplicate_authority_rank(existing)
    if candidate_authority != existing_authority:
        return candidate_authority > existing_authority

    candidate_recovery = _request_duplicate_recovery_rank(candidate)
    existing_recovery = _request_duplicate_recovery_rank(existing)
    if candidate_recovery != existing_recovery:
        return candidate_recovery > existing_recovery

    candidate_source_rank = _poll_duplicate_source_rank(candidate_source)
    existing_source_rank = _poll_duplicate_source_rank(existing_source)
    if candidate_source_rank != existing_source_rank:
        return candidate_source_rank > existing_source_rank

    try:
        candidate_ts = float(candidate.get("timestamp", 0) or 0)
    except Exception:
        candidate_ts = 0.0
    try:
        existing_ts = float(existing.get("timestamp", 0) or 0)
    except Exception:
        existing_ts = 0.0
    return candidate_ts > existing_ts


def _merge_dm_poll_messages(
    relay_messages: list[dict[str, Any]],
    direct_messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    index_by_msg_id: dict[str, tuple[int, str]] = {}

    def add_messages(items: list[dict[str, Any]], source: str) -> None:
        for original in items or []:
            item = dict(original or {})
            msg_id = str(item.get("msg_id", "") or "").strip()
            if not msg_id:
                merged.append(item)
                continue
            existing = index_by_msg_id.get(msg_id)
            if existing is None:
                index_by_msg_id[msg_id] = (len(merged), source)
                merged.append(item)
                continue
            index, existing_source = existing
            if _should_replace_dm_poll_duplicate(merged[index], existing_source, item, source):
                merged[index] = item
                index_by_msg_id[msg_id] = (index, source)

    add_messages(relay_messages, "relay")
    add_messages(direct_messages, "reticulum")
    return sorted(merged, key=lambda item: float(item.get("timestamp", 0) or 0))


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------

@router.post("/api/mesh/dm/register")
@limiter.limit("10/minute")
@requires_signed_write(kind=SignedWriteKind.DM_REGISTER)
async def dm_register_key(request: Request):
    """Register a DH public key for encrypted DM key exchange."""
    body = _signed_body(request)
    agent_id = body.get("agent_id", "").strip()
    dh_pub_key = body.get("dh_pub_key", "").strip()
    dh_algo = body.get("dh_algo", "").strip()
    timestamp = _safe_int(body.get("timestamp", 0) or 0)
    public_key = body.get("public_key", "").strip()
    public_key_algo = body.get("public_key_algo", "").strip()
    signature = body.get("signature", "").strip()
    sequence = _safe_int(body.get("sequence", 0) or 0)
    protocol_version = body.get("protocol_version", "").strip()
    if not agent_id or not dh_pub_key or not dh_algo or not timestamp:
        return {"ok": False, "detail": "Missing agent_id, dh_pub_key, dh_algo, or timestamp"}
    if dh_algo.upper() not in ("X25519", "ECDH_P256", "ECDH"):
        return {"ok": False, "detail": "Unsupported dh_algo"}
    now_ts = int(time.time())
    if abs(timestamp - now_ts) > 7 * 86400:
        return {"ok": False, "detail": "DH key timestamp is too far from current time"}
    from services.mesh.mesh_dm_relay import dm_relay

    try:
        from services.mesh.mesh_reputation import reputation_ledger

        reputation_ledger.register_node(agent_id, public_key, public_key_algo)
    except Exception:
        pass

    accepted, detail, metadata = dm_relay.register_dh_key(
        agent_id,
        dh_pub_key,
        dh_algo,
        timestamp,
        signature,
        public_key,
        public_key_algo,
        protocol_version,
        sequence,
    )
    if not accepted:
        return {"ok": False, "detail": detail}

    return {"ok": True, **(metadata or {})}


@router.get("/api/mesh/dm/pubkey")
@limiter.limit("30/minute")
async def dm_get_pubkey(request: Request, agent_id: str = "", lookup_token: str = ""):
    import main as _m

    return await _m.dm_get_pubkey(request, agent_id=agent_id, lookup_token=lookup_token)


@router.get("/api/mesh/dm/prekey-bundle")
@limiter.limit("30/minute")
async def dm_get_prekey_bundle(request: Request, agent_id: str = "", lookup_token: str = ""):
    import main as _m

    return await _m.dm_get_prekey_bundle(request, agent_id=agent_id, lookup_token=lookup_token)


@router.post("/api/mesh/dm/prekey-peer-lookup")
@limiter.limit("60/minute")
@mesh_write_exempt(MeshWriteExemption.PEER_GOSSIP)
async def dm_prekey_peer_lookup(request: Request):
    """Peer-authenticated invite lookup handle resolution.

    This endpoint exists for private/bootstrap peers to import signed invites
    without exposing a stable agent_id on the ordinary lookup surface. It only
    accepts HMAC-authenticated peer calls and only resolves lookup_token.
    """
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > 4096:
                return JSONResponse(
                    status_code=413,
                    content={"ok": False, "detail": "Request body too large"},
                )
        except (TypeError, ValueError):
            pass
    body_bytes = await request.body()
    if not _verify_peer_push_hmac(request, body_bytes):
        return JSONResponse(
            status_code=403,
            content={"ok": False, "detail": "Invalid or missing peer HMAC"},
        )
    try:
        import json

        body = json.loads(body_bytes or b"{}")
    except Exception:
        return {"ok": False, "detail": "invalid json"}
    lookup_token = str(dict(body or {}).get("lookup_token", "") or "").strip()
    if not lookup_token:
        return {"ok": False, "detail": "lookup_token required"}
    from services.mesh.mesh_wormhole_prekey import fetch_dm_prekey_bundle

    result = fetch_dm_prekey_bundle(
        agent_id="",
        lookup_token=lookup_token,
        allow_peer_lookup=False,
    )
    if not result.get("ok"):
        return {"ok": False, "detail": str(result.get("detail", "") or "Prekey bundle not found")}
    safe = dict(result)
    safe.pop("resolved_agent_id", None)
    safe["lookup_mode"] = "invite_lookup_handle"
    return safe


@router.post("/api/mesh/dm/send")
@limiter.limit("20/minute")
@requires_signed_write(kind=SignedWriteKind.DM_SEND)
async def dm_send(request: Request):
    return await _dm_send_from_signed_request(request)


@router.post("/api/mesh/dm/poll")
@limiter.limit("30/minute")
@requires_signed_write(kind=SignedWriteKind.DM_POLL)
async def dm_poll_secure(request: Request):
    return await _dm_poll_secure_from_signed_request(request)


@router.get("/api/mesh/dm/poll")
@limiter.limit("30/minute")
async def dm_poll(
    request: Request,
    agent_id: str = "",
    agent_token: str = "",
    agent_token_prev: str = "",
    agent_tokens: str = "",
):
    import main as _m

    return await _m.dm_poll(
        request,
        agent_id=agent_id,
        agent_token=agent_token,
        agent_token_prev=agent_token_prev,
        agent_tokens=agent_tokens,
    )


@router.post("/api/mesh/dm/count")
@limiter.limit("60/minute")
@requires_signed_write(kind=SignedWriteKind.DM_COUNT)
async def dm_count_secure(request: Request):
    return await _dm_count_secure_from_signed_request(request)


@router.get("/api/mesh/dm/count")
@limiter.limit("60/minute")
async def dm_count(
    request: Request,
    agent_id: str = "",
    agent_token: str = "",
    agent_token_prev: str = "",
    agent_tokens: str = "",
):
    import main as _m

    return await _m.dm_count(
        request,
        agent_id=agent_id,
        agent_token=agent_token,
        agent_token_prev=agent_token_prev,
        agent_tokens=agent_tokens,
    )


@router.post("/api/mesh/dm/block")
@limiter.limit("10/minute")
@requires_signed_write(kind=SignedWriteKind.DM_BLOCK)
async def dm_block(request: Request):
    """Block or unblock a sender from DMing you."""
    body = _signed_body(request)
    agent_id = body.get("agent_id", "").strip()
    blocked_id = body.get("blocked_id", "").strip()
    action = body.get("action", "block").strip().lower()
    public_key = body.get("public_key", "").strip()
    public_key_algo = body.get("public_key_algo", "").strip()
    signature = body.get("signature", "").strip()
    sequence = _safe_int(body.get("sequence", 0) or 0)
    protocol_version = body.get("protocol_version", "").strip()
    if not agent_id or not blocked_id:
        return {"ok": False, "detail": "Missing agent_id or blocked_id"}
    from services.mesh.mesh_dm_relay import dm_relay

    try:
        from services.mesh.mesh_hashchain import infonet

        ok_seq, seq_reason = _validate_private_signed_sequence(
            infonet,
            agent_id,
            sequence,
            domain=f"dm_block:{action}",
        )
        if not ok_seq:
            return {"ok": False, "detail": seq_reason}
    except Exception:
        pass

    if action == "unblock":
        dm_relay.unblock(agent_id, blocked_id)
    else:
        dm_relay.block(agent_id, blocked_id)
    return {"ok": True, "action": action, "blocked_id": blocked_id}


@router.post("/api/mesh/dm/witness")
@limiter.limit("20/minute")
@requires_signed_write(kind=SignedWriteKind.DM_WITNESS)
async def dm_key_witness(request: Request):
    """Record a lightweight witness for a DM key (dual-path spot-check)."""
    body = _signed_body(request)
    witness_id = body.get("witness_id", "").strip()
    target_id = body.get("target_id", "").strip()
    dh_pub_key = body.get("dh_pub_key", "").strip()
    timestamp = _safe_int(body.get("timestamp", 0) or 0)
    public_key = body.get("public_key", "").strip()
    public_key_algo = body.get("public_key_algo", "").strip()
    signature = body.get("signature", "").strip()
    sequence = _safe_int(body.get("sequence", 0) or 0)
    protocol_version = body.get("protocol_version", "").strip()
    if not witness_id or not target_id or not dh_pub_key or not timestamp:
        return {"ok": False, "detail": "Missing witness_id, target_id, dh_pub_key, or timestamp"}
    now_ts = int(time.time())
    if abs(timestamp - now_ts) > 7 * 86400:
        return {"ok": False, "detail": "Witness timestamp is too far from current time"}
    try:
        from services.mesh.mesh_reputation import reputation_ledger

        reputation_ledger.register_node(witness_id, public_key, public_key_algo)
    except Exception:
        pass
    try:
        from services.mesh.mesh_hashchain import infonet

        ok_seq, seq_reason = _validate_private_signed_sequence(
            infonet,
            witness_id,
            sequence,
            domain="dm_witness",
        )
        if not ok_seq:
            return {"ok": False, "detail": seq_reason}
    except Exception:
        pass
    from services.mesh.mesh_dm_relay import dm_relay

    ok, reason = dm_relay.record_witness(witness_id, target_id, dh_pub_key, timestamp)
    return {"ok": ok, "detail": reason}


@router.get("/api/mesh/dm/witness")
@limiter.limit("60/minute")
async def dm_key_witness_get(request: Request, target_id: str = "", dh_pub_key: str = ""):
    """Get witness counts for a target's DH key."""
    if not target_id:
        return {"ok": False, "detail": "Missing target_id"}
    from services.mesh.mesh_dm_relay import dm_relay

    witnesses = dm_relay.get_witnesses(target_id, dh_pub_key if dh_pub_key else None, limit=5)
    response = {
        "ok": True,
        "count": len(witnesses),
    }
    if _scoped_view_authenticated(request, "mesh.audit"):
        response["target_id"] = target_id
        response["dh_pub_key"] = dh_pub_key or ""
        response["witnesses"] = witnesses
    return response


@router.post("/api/mesh/trust/vouch")
@limiter.limit("20/minute")
@requires_signed_write(kind=SignedWriteKind.TRUST_VOUCH)
async def trust_vouch(request: Request):
    """Record a trust vouch for a node (web-of-trust signal)."""
    body = _signed_body(request)
    voucher_id = body.get("voucher_id", "").strip()
    target_id = body.get("target_id", "").strip()
    note = body.get("note", "").strip()
    timestamp = _safe_int(body.get("timestamp", 0) or 0)
    public_key = body.get("public_key", "").strip()
    public_key_algo = body.get("public_key_algo", "").strip()
    signature = body.get("signature", "").strip()
    sequence = _safe_int(body.get("sequence", 0) or 0)
    protocol_version = body.get("protocol_version", "").strip()
    if not voucher_id or not target_id or not timestamp:
        return {"ok": False, "detail": "Missing voucher_id, target_id, or timestamp"}
    now_ts = int(time.time())
    if abs(timestamp - now_ts) > 7 * 86400:
        return {"ok": False, "detail": "Vouch timestamp is too far from current time"}
    try:
        from services.mesh.mesh_reputation import reputation_ledger
        from services.mesh.mesh_hashchain import infonet

        reputation_ledger.register_node(voucher_id, public_key, public_key_algo)
        ok_seq, seq_reason = _validate_private_signed_sequence(
            infonet,
            voucher_id,
            sequence,
            domain="trust_vouch",
        )
        if not ok_seq:
            return {"ok": False, "detail": seq_reason}
        ok, reason = reputation_ledger.add_vouch(voucher_id, target_id, note, timestamp)
        return {"ok": ok, "detail": reason}
    except Exception:
        return {"ok": False, "detail": "Failed to record vouch"}


@router.get("/api/mesh/trust/vouches", dependencies=[Depends(require_admin)])
@limiter.limit("60/minute")
async def trust_vouches(request: Request, node_id: str = "", limit: int = 20):
    """Fetch latest vouches for a node."""
    if not node_id:
        return {"ok": False, "detail": "Missing node_id"}
    try:
        from services.mesh.mesh_reputation import reputation_ledger

        vouches = reputation_ledger.get_vouches(node_id, limit=limit)
        return {"ok": True, "node_id": node_id, "vouches": vouches, "count": len(vouches)}
    except Exception:
        return {"ok": False, "detail": "Failed to fetch vouches"}
