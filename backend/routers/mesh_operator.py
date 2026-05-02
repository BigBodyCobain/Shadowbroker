import time
import logging
from fastapi import APIRouter, Request, Response, Query, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from limiter import limiter
from auth import require_admin, require_local_operator

logger = logging.getLogger(__name__)

router = APIRouter()


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
    return {"ok": True, "count": len(records), "peers": [r.to_dict() for r in records]}


@router.post("/api/mesh/peers", dependencies=[Depends(require_local_operator)])
@limiter.limit("10/minute")
async def add_peer(request: Request):
    """Add a peer to the store. Body: {peer_url, transport?, label?, role?, buckets?[]}."""
    from services.mesh.mesh_crypto import normalize_peer_url
    from services.mesh.mesh_peer_store import (
        DEFAULT_PEER_STORE_PATH, PeerStore, PeerStoreError,
        make_push_peer_record, make_sync_peer_record,
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
    added: list = []
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
    removed: list = []
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
