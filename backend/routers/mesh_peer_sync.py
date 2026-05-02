import json as json_mod
import logging
from typing import Any
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from limiter import limiter
from auth import require_admin, require_local_operator, _verify_peer_push_hmac
from services.config import get_settings
from services.mesh.mesh_crypto import normalize_peer_url
from services.mesh.mesh_router import peer_transport_kind
from auth import _peer_hmac_url_from_request

logger = logging.getLogger(__name__)

router = APIRouter()

_PEER_PUSH_BATCH_SIZE = 50


def _safe_int(val, default=0):
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _hydrate_gate_store_from_chain(events: list) -> int:
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


@router.post("/api/mesh/infonet/peer-push")
@limiter.limit("30/minute")
async def infonet_peer_push(request: Request):
    """Accept pushed Infonet events from relay peers (HMAC-authenticated)."""
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > 524_288:
                return Response(content='{"ok":false,"detail":"Request body too large (max 512KB)"}',
                    status_code=413, media_type="application/json")
        except (ValueError, TypeError):
            pass
    from services.mesh.mesh_hashchain import infonet
    body_bytes = await request.body()
    if not _verify_peer_push_hmac(request, body_bytes):
        return Response(content='{"ok":false,"detail":"Invalid or missing peer HMAC"}',
            status_code=403, media_type="application/json")
    body = json_mod.loads(body_bytes or b"{}")
    events = body.get("events", [])
    if not isinstance(events, list):
        return {"ok": False, "detail": "events must be a list"}
    if len(events) > 50:
        return {"ok": False, "detail": "Too many events in one push (max 50)"}
    if not events:
        return {"ok": True, "accepted": 0, "duplicates": 0, "rejected": []}
    result = infonet.ingest_events(events)
    _hydrate_gate_store_from_chain(events)
    return {"ok": True, **result}


@router.post("/api/mesh/gate/peer-push")
@limiter.limit("30/minute")
async def gate_peer_push(request: Request):
    """Accept pushed gate events from relay peers (private plane)."""
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > 524_288:
                return Response(content='{"ok":false,"detail":"Request body too large"}',
                    status_code=413, media_type="application/json")
        except (ValueError, TypeError):
            pass
    from services.mesh.mesh_hashchain import gate_store
    body_bytes = await request.body()
    if not _verify_peer_push_hmac(request, body_bytes):
        return Response(content='{"ok":false,"detail":"Invalid or missing peer HMAC"}',
            status_code=403, media_type="application/json")
    body = json_mod.loads(body_bytes or b"{}")
    events = body.get("events", [])
    if not isinstance(events, list):
        return {"ok": False, "detail": "events must be a list"}
    if len(events) > 50:
        return {"ok": False, "detail": "Too many events (max 50)"}
    if not events:
        return {"ok": True, "accepted": 0, "duplicates": 0}
    from services.mesh.mesh_hashchain import resolve_gate_wire_ref
    # Sprint 3 / Rec #4: the gate_ref is HMACed with a key bound to the
    # receiver's peer URL (the URL the push was delivered to). This is
    # the same URL _verify_peer_push_hmac validated the X-Peer-HMAC
    # header against, so we can trust it for ref resolution.
    hop_peer_url = _peer_hmac_url_from_request(request)
    grouped_events: dict[str, list] = {}
    for evt in events:
        evt_dict = evt if isinstance(evt, dict) else {}
        payload = evt_dict.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        clean_event = {
            "event_id": str(evt_dict.get("event_id", "") or ""),
            "event_type": "gate_message",
            "timestamp": evt_dict.get("timestamp", 0),
            "node_id": str(evt_dict.get("node_id", "") or evt_dict.get("sender_id", "") or ""),
            "sequence": evt_dict.get("sequence", 0),
            "signature": str(evt_dict.get("signature", "") or ""),
            "public_key": str(evt_dict.get("public_key", "") or ""),
            "public_key_algo": str(evt_dict.get("public_key_algo", "") or ""),
            "protocol_version": str(evt_dict.get("protocol_version", "") or ""),
            "payload": {
                "ciphertext": str(payload.get("ciphertext", "") or ""),
                "format": str(payload.get("format", "") or ""),
                "nonce": str(payload.get("nonce", "") or ""),
                "sender_ref": str(payload.get("sender_ref", "") or ""),
            },
        }
        epoch = _safe_int(payload.get("epoch", 0) or 0)
        if epoch > 0:
            clean_event["payload"]["epoch"] = epoch
        envelope_hash_val = str(payload.get("envelope_hash", "") or "").strip()
        gate_envelope_val = str(payload.get("gate_envelope", "") or "").strip()
        reply_to_val = str(payload.get("reply_to", "") or "").strip()
        if envelope_hash_val:
            clean_event["payload"]["envelope_hash"] = envelope_hash_val
        if gate_envelope_val:
            clean_event["payload"]["gate_envelope"] = gate_envelope_val
        if reply_to_val:
            clean_event["payload"]["reply_to"] = reply_to_val
        event_gate_id = str(payload.get("gate", "") or evt_dict.get("gate", "") or "").strip().lower()
        if not event_gate_id:
            event_gate_id = resolve_gate_wire_ref(
                str(payload.get("gate_ref", "") or evt_dict.get("gate_ref", "") or ""),
                clean_event,
                peer_url=hop_peer_url,
            )
        if not event_gate_id:
            return {"ok": False, "detail": "gate resolution failed"}
        final_payload: dict[str, Any] = {
            "gate": event_gate_id,
            "ciphertext": clean_event["payload"]["ciphertext"],
            "format": clean_event["payload"]["format"],
            "nonce": clean_event["payload"]["nonce"],
            "sender_ref": clean_event["payload"]["sender_ref"],
        }
        if epoch > 0:
            final_payload["epoch"] = epoch
        if clean_event["payload"].get("envelope_hash"):
            final_payload["envelope_hash"] = clean_event["payload"]["envelope_hash"]
        if clean_event["payload"].get("gate_envelope"):
            final_payload["gate_envelope"] = clean_event["payload"]["gate_envelope"]
        if clean_event["payload"].get("reply_to"):
            final_payload["reply_to"] = clean_event["payload"]["reply_to"]
        grouped_events.setdefault(event_gate_id, []).append({
            "event_id": clean_event["event_id"],
            "event_type": "gate_message",
            "timestamp": clean_event["timestamp"],
            "node_id": clean_event["node_id"],
            "sequence": clean_event["sequence"],
            "signature": clean_event["signature"],
            "public_key": clean_event["public_key"],
            "public_key_algo": clean_event["public_key_algo"],
            "protocol_version": clean_event["protocol_version"],
            "payload": final_payload,
        })
    accepted = 0
    duplicates = 0
    rejected = 0
    for event_gate_id, items in grouped_events.items():
        result = gate_store.ingest_peer_events(event_gate_id, items)
        a = int(result.get("accepted", 0) or 0)
        accepted += a
        duplicates += int(result.get("duplicates", 0) or 0)
        rejected += int(result.get("rejected", 0) or 0)
    return {"ok": True, "accepted": accepted, "duplicates": duplicates, "rejected": rejected}


@router.post("/api/mesh/gate/peer-pull")
@limiter.limit("30/minute")
async def gate_peer_pull(request: Request):
    """Return gate events a peer is missing (HMAC-authenticated pull sync)."""
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > 65_536:
                return Response(content='{"ok":false,"detail":"Request body too large"}',
                    status_code=413, media_type="application/json")
        except (ValueError, TypeError):
            pass
    from services.mesh.mesh_hashchain import gate_store
    body_bytes = await request.body()
    if not _verify_peer_push_hmac(request, body_bytes):
        return Response(content='{"ok":false,"detail":"Invalid or missing peer HMAC"}',
            status_code=403, media_type="application/json")
    body = json_mod.loads(body_bytes or b"{}")
    gate_id = str(body.get("gate_id", "") or "").strip().lower()
    after_count = _safe_int(body.get("after_count", 0) or 0)
    if not gate_id:
        gate_ids = gate_store.known_gate_ids()
        gate_counts: dict[str, int] = {}
        for gid in gate_ids:
            with gate_store._lock:
                gate_counts[gid] = len(gate_store._gates.get(gid, []))
        return {"ok": True, "gates": gate_counts}
    with gate_store._lock:
        all_events = list(gate_store._gates.get(gate_id, []))
    total = len(all_events)
    if after_count >= total:
        return {"ok": True, "events": [], "total": total, "gate_id": gate_id}
    batch = all_events[after_count : after_count + _PEER_PUSH_BATCH_SIZE]
    return {"ok": True, "events": batch, "total": total, "gate_id": gate_id}
