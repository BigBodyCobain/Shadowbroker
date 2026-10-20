"""Snap Map OSINT — feed, watch-zone management, analyst confirmation, media proxy."""
from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urlparse

import requests
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from auth import require_local_operator
from limiter import limiter
from services.fetchers._store import get_latest_data_subset_refs
from services.fetchers.snapmap_osint import (
    MAX_RADIUS_M,
    MAX_ZONES,
    MIN_RADIUS_M,
    confirm_alert,
    list_alerts,
    load_zones,
    save_zones,
    snap_media_host_allowed,
)
from services.network_utils import outbound_user_agent

logger = logging.getLogger(__name__)

router = APIRouter()

_EMPTY = {"zones": [], "alerts": [], "total_zones": 0, "anomalies": 0, "timestamp": None}


@router.get("/api/snapmap-feed")
@limiter.limit("30/minute")
async def snapmap_feed(request: Request) -> dict:
    snap = get_latest_data_subset_refs("snapmap_osint")
    payload = snap.get("snapmap_osint")
    if not isinstance(payload, dict) or payload.get("zones") is None:
        return dict(_EMPTY)
    return payload


@router.get("/api/snapmap/zones", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def snapmap_zones(request: Request) -> dict:
    return {
        "zones": load_zones(),
        "limits": {"min_radius_m": MIN_RADIUS_M, "max_radius_m": MAX_RADIUS_M, "max_zones": MAX_ZONES},
    }


@router.put("/api/snapmap/zones", dependencies=[Depends(require_local_operator)])
@limiter.limit("10/minute")
async def snapmap_zones_replace(request: Request, body: dict[str, Any] = Body(...)) -> dict:
    """Replace the watch-zone list. Guardrails (radius, count) are enforced server-side."""
    raw = body.get("zones")
    if not isinstance(raw, list):
        raise HTTPException(status_code=400, detail="Body must be {\"zones\": [...]}")
    zones = await asyncio.to_thread(save_zones, raw)
    return {"zones": zones, "accepted": len(zones), "submitted": len(raw)}


@router.get("/api/snapmap/alerts", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def snapmap_alerts(request: Request, limit: int = Query(default=50, ge=1, le=500)) -> dict:
    return {"alerts": await asyncio.to_thread(list_alerts, limit)}


@router.post("/api/snapmap/alerts/{alert_id}/confirm", dependencies=[Depends(require_local_operator)])
@limiter.limit("20/minute")
async def snapmap_alert_confirm(request: Request, alert_id: int, body: dict[str, Any] = Body(default={})) -> dict:
    """Analyst confirmation after manual verification — upgrades the alert to reliability A."""
    note = str((body or {}).get("note") or "").strip()
    if not note:
        raise HTTPException(status_code=400, detail="A verification note is required to rate an alert A")
    alert = await asyncio.to_thread(confirm_alert, alert_id, note)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    return alert


@router.get("/api/snapmap/media")
@limiter.limit("60/minute")
async def snapmap_media_proxy(request: Request, url: str = Query(...)) -> StreamingResponse:
    """Stream Snap CDN media for in-app viewing (host allowlist, no redirects)."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise HTTPException(status_code=400, detail="Invalid scheme")
    if not snap_media_host_allowed(parsed.hostname):
        raise HTTPException(status_code=403, detail="Host not allowed")

    headers = {
        "User-Agent": f"Mozilla/5.0 (compatible; {outbound_user_agent('snapmap-media')})",
        "Accept": "*/*",
    }
    if range_header := request.headers.get("range"):
        headers["Range"] = range_header
    try:
        resp = requests.get(url, stream=True, timeout=(3, 45), headers=headers, allow_redirects=False)
    except requests.RequestException as exc:
        logger.warning("Snap media upstream failure: %s", exc)
        raise HTTPException(status_code=502, detail="Upstream fetch failed") from exc
    if resp.status_code >= 300:
        resp.close()
        raise HTTPException(status_code=502, detail=f"Upstream returned {resp.status_code}")

    response_headers = {"Cache-Control": "private, max-age=300", "Accept-Ranges": resp.headers.get("Accept-Ranges", "bytes")}
    for key in ("Content-Length", "Content-Range"):
        if value := resp.headers.get(key):
            response_headers[key] = value
    return StreamingResponse(
        resp.iter_content(chunk_size=65536),
        status_code=resp.status_code,
        media_type=resp.headers.get("Content-Type", "application/octet-stream"),
        headers=response_headers,
        background=BackgroundTask(resp.close),
    )
