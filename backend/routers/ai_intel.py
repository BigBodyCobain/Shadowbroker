"""AI Intel API — endpoints for OpenClaw and the AI co-pilot.

All endpoints require local operator access (loopback or X-Admin-Key).
Provides: pin management, satellite imagery, news-near, data injection.
"""

import asyncio
import logging
import math
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from auth import require_local_operator, require_openclaw_or_local
from limiter import limiter

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Agent Actions Queue — agent pushes display commands to the frontend
# ---------------------------------------------------------------------------
# When the agent wants to show something to the user (satellite image,
# fly-to location, etc.), it pushes an action here. The frontend polls
# this lightweight endpoint and executes the action in the UI.
#
# Actions are consumed on read (destructive poll) so they don't pile up.
# ---------------------------------------------------------------------------

import threading as _actions_threading
import collections as _collections

_agent_actions_lock = _actions_threading.Lock()
_agent_actions: _collections.deque = _collections.deque(maxlen=20)


def push_agent_action(action: dict[str, Any]) -> None:
    """Push an action for the frontend to pick up."""
    action.setdefault("ts", time.time())
    with _agent_actions_lock:
        _agent_actions.append(action)


def pop_agent_actions() -> list[dict[str, Any]]:
    """Pop all pending actions (destructive read)."""
    with _agent_actions_lock:
        actions = list(_agent_actions)
        _agent_actions.clear()
    return actions


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class EntityAttachment(BaseModel):
    entity_type: str = ""   # "ship", "flight", "satellite", etc.
    entity_id: str = ""
    entity_label: str = ""


class PinCreate(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    label: str = Field(..., max_length=200)
    category: str = "custom"
    layer_id: str = ""
    color: str = ""
    description: str = ""
    source: str = "user"
    source_url: str = ""
    confidence: float = 1.0
    ttl_hours: float = 0
    metadata: dict = Field(default_factory=dict)
    entity_attachment: EntityAttachment | None = None


class PinBatchCreate(BaseModel):
    pins: list[dict[str, Any]] = Field(..., max_length=200)
    layer_id: str = ""


class PinUpdate(BaseModel):
    label: str | None = Field(None, max_length=200)
    description: str | None = Field(None, max_length=2000)
    category: str | None = None
    color: str | None = None


class PinCommentCreate(BaseModel):
    text: str = Field(..., max_length=4000)
    author: str = "user"           # "user" | "agent" | "openclaw"
    author_label: str = ""
    reply_to: str = ""             # parent comment id (optional)


class LayerCreate(BaseModel):
    name: str = Field(..., max_length=100)
    description: str = ""
    source: str = "user"
    color: str = ""
    feed_url: str = ""
    feed_interval: int = 300


class LayerUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    visible: bool | None = None
    color: str | None = None
    feed_url: str | None = None
    feed_interval: int | None = None


class InjectRequest(BaseModel):
    layer: str
    items: list[dict[str, Any]] = Field(..., max_length=200)
    mode: str = "append"  # "append" or "replace"


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

@router.get("/api/ai/status", dependencies=[Depends(require_openclaw_or_local)])
@limiter.limit("60/minute")
async def ai_status(request: Request):
    """Health check and capability overview for the AI Intel subsystem."""
    from services.ai_pin_store import pin_count

    counts = pin_count()
    return {
        "ok": True,
        "service": "ShadowBroker AI Intel",
        "version": "1.0.0",
        "pin_count": sum(counts.values()),
        "pin_categories": counts,
        "capabilities": [
            "pin_placement", "pin_batch", "satellite_imagery",
            "news_near", "data_injection", "geojson_export",
        ],
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Pin CRUD
# ---------------------------------------------------------------------------

@router.post("/api/ai/pins", dependencies=[Depends(require_openclaw_or_local)])
@limiter.limit("60/minute")
async def create_pin(request: Request, body: PinCreate):
    """Place a single AI Intel pin on the map."""
    from services.ai_pin_store import create_pin as _create_pin

    ea = body.entity_attachment.model_dump() if body.entity_attachment else None
    pin = _create_pin(
        lat=body.lat,
        lng=body.lng,
        label=body.label,
        category=body.category,
        layer_id=body.layer_id,
        color=body.color,
        description=body.description,
        source=body.source,
        source_url=body.source_url,
        confidence=body.confidence,
        ttl_hours=body.ttl_hours,
        metadata=body.metadata,
        entity_attachment=ea,
    )
    return {"ok": True, "pin": pin}


@router.post("/api/ai/pins/batch", dependencies=[Depends(require_openclaw_or_local)])
@limiter.limit("20/minute")
async def create_pins_batch(request: Request, body: PinBatchCreate):
    """Place multiple AI Intel pins at once (max 100)."""
    from services.ai_pin_store import create_pins_batch as _create_batch

    pins = _create_batch(body.pins, default_layer_id=body.layer_id)
    return {"ok": True, "created": len(pins), "pins": pins}


@router.get("/api/ai/pins", dependencies=[Depends(require_openclaw_or_local)])
@limiter.limit("60/minute")
async def list_pins(
    request: Request,
    category: str = "",
    source: str = "",
    layer_id: str = "",
    limit: int = Query(500, ge=1, le=2000),
):
    """List AI Intel pins with optional filters."""
    from services.ai_pin_store import get_pins

    pins = get_pins(category=category, source=source, layer_id=layer_id, limit=limit)
    return {"ok": True, "count": len(pins), "pins": pins}


@router.get("/api/ai/pins/geojson", dependencies=[Depends(require_openclaw_or_local)])
@limiter.limit("60/minute")
async def pins_geojson(request: Request, layer_id: str = ""):
    """Export all active AI Intel pins as GeoJSON for the map layer."""
    from services.ai_pin_store import pins_as_geojson

    return pins_as_geojson(layer_id=layer_id)


@router.get("/api/ai/pins/{pin_id}", dependencies=[Depends(require_openclaw_or_local)])
@limiter.limit("120/minute")
async def get_pin_detail(request: Request, pin_id: str):
    """Return a single pin with its full comment thread."""
    from services.ai_pin_store import get_pin

    pin = get_pin(pin_id)
    if not pin:
        raise HTTPException(404, f"Pin '{pin_id}' not found")
    return {"ok": True, "pin": pin}


@router.patch("/api/ai/pins/{pin_id}", dependencies=[Depends(require_openclaw_or_local)])
@limiter.limit("60/minute")
async def patch_pin(request: Request, pin_id: str, body: PinUpdate):
    """Edit a pin's label, description, category, or color."""
    from services.ai_pin_store import update_pin

    updated = update_pin(
        pin_id,
        label=body.label,
        description=body.description,
        category=body.category,
        color=body.color,
    )
    if not updated:
        raise HTTPException(404, f"Pin '{pin_id}' not found")
    return {"ok": True, "pin": updated}


@router.post("/api/ai/pins/{pin_id}/comments", dependencies=[Depends(require_openclaw_or_local)])
@limiter.limit("60/minute")
async def post_pin_comment(request: Request, pin_id: str, body: PinCommentCreate):
    """Append a comment (or reply) to a pin's thread."""
    from services.ai_pin_store import add_pin_comment

    pin = add_pin_comment(
        pin_id,
        text=body.text,
        author=body.author,
        author_label=body.author_label,
        reply_to=body.reply_to,
    )
    if not pin:
        raise HTTPException(404, f"Pin '{pin_id}' not found or empty comment")
    return {"ok": True, "pin": pin}


@router.delete(
    "/api/ai/pins/{pin_id}/comments/{comment_id}",
    dependencies=[Depends(require_openclaw_or_local)],
)
@limiter.limit("60/minute")
async def delete_pin_comment_route(request: Request, pin_id: str, comment_id: str):
    """Delete a single comment from a pin's thread."""
    from services.ai_pin_store import delete_pin_comment

    if delete_pin_comment(pin_id, comment_id):
        return {"ok": True, "deleted": comment_id}
    raise HTTPException(404, "Comment not found")


@router.delete("/api/ai/pins/{pin_id}", dependencies=[Depends(require_openclaw_or_local)])
@limiter.limit("60/minute")
async def delete_pin(request: Request, pin_id: str):
    """Delete a single pin by ID."""
    from services.ai_pin_store import delete_pin as _delete

    if _delete(pin_id):
        return {"ok": True, "deleted": pin_id}
    raise HTTPException(404, f"Pin '{pin_id}' not found")


@router.delete("/api/ai/pins", dependencies=[Depends(require_openclaw_or_local)])
@limiter.limit("10/minute")
async def clear_pins(
    request: Request,
    category: str = "",
    source: str = "",
):
    """Clear pins — all, or filtered by category/source."""
    from services.ai_pin_store import clear_pins as _clear

    removed = _clear(category=category, source=source)
    return {"ok": True, "removed": removed}


# ---------------------------------------------------------------------------
# Pin Layers
# ---------------------------------------------------------------------------

@router.post("/api/ai/layers", dependencies=[Depends(require_openclaw_or_local)])
@limiter.limit("30/minute")
async def api_create_layer(request: Request, body: LayerCreate):
    """Create a new pin layer."""
    from services.ai_pin_store import create_layer as _create_layer

    layer = _create_layer(
        name=body.name,
        description=body.description,
        source=body.source,
        color=body.color,
        feed_url=body.feed_url,
        feed_interval=body.feed_interval,
    )
    return {"ok": True, "layer": layer}


@router.get("/api/ai/layers", dependencies=[Depends(require_openclaw_or_local)])
@limiter.limit("60/minute")
async def api_list_layers(request: Request):
    """List all pin layers with pin counts."""
    from services.ai_pin_store import get_layers as _get_layers

    layers = _get_layers()
    return {"ok": True, "count": len(layers), "layers": layers}


@router.patch("/api/ai/layers/{layer_id}", dependencies=[Depends(require_openclaw_or_local)])
@limiter.limit("30/minute")
async def api_update_layer(request: Request, layer_id: str, body: LayerUpdate):
    """Update a pin layer (name, visibility, color, etc.)."""
    from services.ai_pin_store import update_layer as _update_layer

    updates = body.model_dump(exclude_none=True)
    result = _update_layer(layer_id, **updates)
    if result is None:
        raise HTTPException(404, f"Layer '{layer_id}' not found")
    return {"ok": True, "layer": result}


@router.delete("/api/ai/layers/{layer_id}", dependencies=[Depends(require_openclaw_or_local)])
@limiter.limit("10/minute")
async def api_delete_layer(request: Request, layer_id: str):
    """Delete a layer and all its pins."""
    from services.ai_pin_store import delete_layer as _delete_layer

    removed = _delete_layer(layer_id)
    return {"ok": True, "layer_id": layer_id, "pins_removed": removed}


@router.post("/api/ai/layers/{layer_id}/refresh", dependencies=[Depends(require_openclaw_or_local)])
@limiter.limit("10/minute")
async def api_refresh_layer_feed(request: Request, layer_id: str):
    """Manually trigger a feed refresh for a layer."""
    from services.ai_pin_store import get_layers as _get_layers

    layers = _get_layers()
    target = next((l for l in layers if l["id"] == layer_id), None)
    if target is None:
        raise HTTPException(404, f"Layer '{layer_id}' not found")
    if not target.get("feed_url"):
        raise HTTPException(400, "Layer has no feed URL")

    from services.feed_ingester import _fetch_layer_feed
    _fetch_layer_feed(target)

    # Re-fetch to get updated pin count
    updated_layers = _get_layers()
    updated = next((l for l in updated_layers if l["id"] == layer_id), target)
    return {"ok": True, "layer": updated}


# ---------------------------------------------------------------------------
# Agent Actions endpoint — frontend polls this for UI commands from the agent
# ---------------------------------------------------------------------------

@router.get("/api/ai/agent-actions")
@limiter.limit("120/minute")
async def get_agent_actions(request: Request):
    """Frontend polls for pending agent display actions (destructive read).

    No auth required — this only contains display directives (show image,
    fly to location), not sensitive data. The agent authenticates when
    pushing actions through the command channel.
    """
    actions = pop_agent_actions()
    return {"ok": True, "actions": actions}


# ---------------------------------------------------------------------------
# Satellite Imagery
# ---------------------------------------------------------------------------

@router.get("/api/ai/satellite-images", dependencies=[Depends(require_openclaw_or_local)])
@limiter.limit("20/minute")
async def ai_satellite_images(
    request: Request,
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    count: int = Query(3, ge=1, le=5),
):
    """Fetch latest Sentinel-2 satellite imagery for a coordinate.
    Uses Microsoft Planetary Computer STAC API (free, no key needed).
    Falls back to Esri World Imagery if Planetary Computer is unavailable."""
    import requests as req
    from datetime import datetime, timedelta

    results = []
    end = datetime.utcnow()
    start = end - timedelta(days=60)

    search_payload = {
        "collections": ["sentinel-2-l2a"],
        "intersects": {"type": "Point", "coordinates": [lng, lat]},
        "datetime": f"{start.isoformat()}Z/{end.isoformat()}Z",
        "sortby": [{"field": "datetime", "direction": "desc"}],
        "limit": count,
        "query": {"eo:cloud_cover": {"lt": 30}},
    }

    def _do_stac_search() -> list[dict]:
        """Run STAC search + SAS signing in a single worker thread."""

        def _sign_href(href: str) -> str:
            """Sign a Planetary Computer asset URL with a short-lived SAS token."""
            if not href or "blob.core.windows.net" not in href:
                return href
            try:
                # Extract storage account name for token request
                account = href.split(".blob.core.windows.net")[0].split("//")[-1]
                token_resp = req.get(
                    f"https://planetarycomputer.microsoft.com/api/sas/v1/token/{account}",
                    timeout=5,
                )
                token_resp.raise_for_status()
                token = token_resp.json().get("token", "")
                sep = "&" if "?" in href else "?"
                return f"{href}{sep}{token}" if token else href
            except Exception:
                return href

        resp = req.post(
            "https://planetarycomputer.microsoft.com/api/stac/v1/search",
            json=search_payload,
            timeout=10,
            headers={"User-Agent": "ShadowBroker-OSINT/1.0 (ai-intel)"},
        )
        resp.raise_for_status()
        features = resp.json().get("features", [])

        out: list[dict] = []
        for item in features[:count]:
            assets = item.get("assets", {})
            rendered = assets.get("rendered_preview", {})
            thumbnail = assets.get("thumbnail", {})
            props = item.get("properties", {})

            thumb_href = _sign_href(thumbnail.get("href", "") or rendered.get("href", ""))
            full_href = _sign_href(rendered.get("href", "") or thumbnail.get("href", ""))

            out.append({
                "scene_id": item.get("id"),
                "datetime": props.get("datetime"),
                "cloud_cover": props.get("eo:cloud_cover"),
                "platform": props.get("platform", "Sentinel-2"),
                "thumbnail_url": thumb_href,
                "fullres_url": full_href,
                "bbox": item.get("bbox"),
            })
        return out

    try:
        results = await asyncio.to_thread(_do_stac_search)
    except Exception as e:
        logger.warning(f"Sentinel-2 STAC search failed: {e}")
        # Fallback to Esri World Imagery
        from services.sentinel_search import _esri_imagery_fallback
        fallback = _esri_imagery_fallback(lat, lng)
        results = [fallback]

    return {
        "ok": True,
        "lat": lat,
        "lng": lng,
        "scenes": results,
        "count": len(results),
        "source": "Microsoft Planetary Computer / Sentinel-2 L2A",
    }


# ---------------------------------------------------------------------------
# News Near (GDELT + news by proximity)
# ---------------------------------------------------------------------------

def _haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in miles using the Haversine formula."""
    R = 3958.8  # Earth radius in miles
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(dlng / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


@router.get("/api/ai/news-near", dependencies=[Depends(require_openclaw_or_local)])
@limiter.limit("30/minute")
async def ai_news_near(
    request: Request,
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    radius: float = Query(500, ge=10, le=5000),
):
    """Get GDELT incidents and news articles near a coordinate.
    Returns headlines with source URLs, filtered by proximity."""
    from services.fetchers._store import latest_data

    # Filter GDELT incidents
    gdelt_results = []
    for incident in (latest_data.get("gdelt") or []):
        coords = incident.get("geometry", {}).get("coordinates", [])
        if len(coords) >= 2:
            try:
                dist = _haversine_miles(lat, lng, coords[1], coords[0])
            except (ValueError, TypeError):
                continue
            if dist <= radius:
                props = incident.get("properties", {})
                gdelt_results.append({
                    "name": props.get("name", "Unknown"),
                    "count": props.get("count", 1),
                    "urls": props.get("_urls_list", []),
                    "headlines": props.get("_headlines_list", []),
                    "lat": coords[1],
                    "lng": coords[0],
                    "distance_miles": round(dist, 1),
                })
    gdelt_results.sort(key=lambda x: -x["count"])

    # Filter news articles
    news_results = []
    for article in (latest_data.get("news") or []):
        a_lat = article.get("lat")
        a_lng = article.get("lng")
        if a_lat is not None and a_lng is not None:
            try:
                dist = _haversine_miles(lat, lng, float(a_lat), float(a_lng))
            except (ValueError, TypeError):
                continue
            if dist <= radius:
                news_results.append({
                    "title": article.get("title", ""),
                    "summary": article.get("summary", ""),
                    "source": article.get("source", ""),
                    "link": article.get("link", ""),
                    "risk_score": article.get("risk_score", 0),
                    "lat": float(a_lat),
                    "lng": float(a_lng),
                    "distance_miles": round(dist, 1),
                })
    news_results.sort(key=lambda x: -(x.get("risk_score") or 0))

    return {
        "ok": True,
        "center": {"lat": lat, "lng": lng},
        "radius_miles": radius,
        "gdelt": gdelt_results[:20],
        "gdelt_count": len(gdelt_results),
        "news": news_results[:10],
        "news_count": len(news_results),
    }


# ---------------------------------------------------------------------------
# Native Layer Data Injection
# ---------------------------------------------------------------------------

INJECTABLE_LAYERS = {
    "cctv", "ships", "sigint", "kiwisdr",
    "military_bases", "datacenters", "power_plants",
    "satnogs_stations", "volcanoes", "earthquakes",
    "news", "viirs_change_nodes", "air_quality",
}


@router.post("/api/ai/inject", dependencies=[Depends(require_openclaw_or_local)])
@limiter.limit("30/minute")
async def inject_data(request: Request, body: InjectRequest):
    """Inject custom data into ANY native ShadowBroker layer.
    Items appear as real telemetry alongside automated feeds.
    Tagged with _source='user:openclaw' so they can be filtered/removed."""
    from services.fetchers._store import latest_data, _data_lock, bump_data_version

    if body.layer not in INJECTABLE_LAYERS:
        raise HTTPException(400, f"Layer '{body.layer}' is not injectable. "
                            f"Valid layers: {sorted(INJECTABLE_LAYERS)}")

    now = time.time()
    items = body.items[:200]  # cap at 200

    # Tag every injected item
    for item in items:
        item["_injected"] = True
        item["_source"] = "user:openclaw"
        item["_injected_at"] = now

    with _data_lock:
        existing = list(latest_data.get(body.layer) or [])
        if body.mode == "replace":
            existing = [x for x in existing if not x.get("_injected")]
        existing.extend(items)
        latest_data[body.layer] = existing
        bump_data_version()

    total = len(latest_data.get(body.layer, []))
    return {
        "ok": True,
        "layer": body.layer,
        "injected": len(items),
        "total": total,
    }


@router.delete("/api/ai/inject", dependencies=[Depends(require_openclaw_or_local)])
@limiter.limit("10/minute")
async def remove_injected(
    request: Request,
    layer: str = "",
):
    """Remove user-injected data from native layers."""
    from services.fetchers._store import latest_data, _data_lock, bump_data_version

    removed = 0
    with _data_lock:
        if layer:
            if layer not in INJECTABLE_LAYERS:
                raise HTTPException(400, f"Layer '{layer}' is not injectable")
            existing = list(latest_data.get(layer) or [])
            cleaned = [x for x in existing if not x.get("_injected")]
            removed = len(existing) - len(cleaned)
            latest_data[layer] = cleaned
        else:
            for key in INJECTABLE_LAYERS:
                existing = list(latest_data.get(key) or [])
                cleaned = [x for x in existing if not x.get("_injected")]
                removed += len(existing) - len(cleaned)
                latest_data[key] = cleaned
        if removed:
            bump_data_version()

    return {"ok": True, "removed": removed, "layer": layer or "all"}


# ---------------------------------------------------------------------------
# Intelligence Report Generation
# ---------------------------------------------------------------------------

@router.get("/api/ai/report", dependencies=[Depends(require_openclaw_or_local)])
@limiter.limit("10/minute")
async def generate_report(request: Request):
    """Generate a full intelligence report from current telemetry.
    Returns a structured markdown-style report suitable for export."""
    from services.fetchers._store import latest_data
    from services.ai_pin_store import pin_count, get_pins
    from datetime import datetime

    now = datetime.utcnow()
    pins = get_pins(limit=500)
    counts = pin_count()

    # Gather stats
    mil_flights = latest_data.get("military_flights", [])
    ships = latest_data.get("ships", [])
    tracked = latest_data.get("tracked_flights", [])
    earthquakes = latest_data.get("earthquakes", [])
    gdelt = latest_data.get("gdelt", [])
    correlations = latest_data.get("correlations", [])
    sigint_totals = latest_data.get("sigint_totals", {})

    report = {
        "ok": True,
        "generated_at": now.isoformat() + "Z",
        "title": f"ShadowBroker Intelligence Report — {now.strftime('%Y-%m-%d %H:%M')} UTC",
        "summary": {
            "military_flights": len(mil_flights),
            "tracked_aircraft": len(tracked),
            "ships": len(ships),
            "earthquakes": len(earthquakes),
            "gdelt_events": len(gdelt),
            "correlations": len(correlations),
            "ai_pins": sum(counts.values()),
            "sigint": sigint_totals,
        },
        "top_military": [
            {
                "callsign": f.get("callsign"),
                "type": f.get("type"),
                "lat": f.get("lat"),
                "lon": f.get("lon"),
                "altitude": f.get("altitude"),
            }
            for f in mil_flights[:10]
        ],
        "top_correlations": [
            {
                "type": c.get("type"),
                "description": c.get("description"),
                "severity": c.get("severity"),
            }
            for c in correlations[:5]
        ],
        "recent_earthquakes": [
            {
                "magnitude": q.get("magnitude"),
                "place": q.get("place"),
                "lat": q.get("lat"),
                "lng": q.get("lng"),
            }
            for q in sorted(
                earthquakes, key=lambda x: -(x.get("magnitude") or 0),
            )[:5]
        ],
        "ai_pin_summary": counts,
    }

    return report


# ---------------------------------------------------------------------------
# Telemetry summary (lightweight — for AI to quickly assess the state)
# ---------------------------------------------------------------------------

@router.get("/api/ai/summary", dependencies=[Depends(require_openclaw_or_local)])
@limiter.limit("60/minute")
async def ai_telemetry_summary(request: Request):
    """Lightweight telemetry summary — counts and top entities.
    Designed for OpenClaw to quickly assess the state without fetching full data."""
    from services.fetchers._store import latest_data
    from services.telemetry import get_telemetry_summary

    summary = get_telemetry_summary()
    return {
        "ok": True,
        "timestamp": time.time(),
        "counts": summary.get("counts", {}),
        "available_layers": summary.get("available_layers", []),
        "non_empty_layers": summary.get("non_empty_layers", []),
        "layer_aliases": summary.get("layer_aliases", {}),
        "sigint_totals": latest_data.get("sigint_totals", {}),
        "version": summary.get("version"),
        "last_updated": summary.get("last_updated"),
    }


# ---------------------------------------------------------------------------
# Time Machine — Telemetry Snapshots (Hybrid: full + compressed_v1)
# ---------------------------------------------------------------------------

import copy
import gzip
import json
import os
from datetime import datetime
from pathlib import Path
from threading import Lock as TMLock

# Snapshot storage
_snapshots: list[dict] = []
_snapshots_lock = TMLock()
_snapshot_max = 1000  # max retained snapshots

# Configuration
_timemachine_config: dict = {
    "profiles": {
        "high_freq": {
            "interval_minutes": 15,
            "layers": [
                "military_flights", "ships", "satellites",
                "tracked_flights", "private_jets",
            ],
            "max_snapshots": 672,
        },
        "standard": {
            "interval_minutes": 120,
            "layers": [
                "gdelt", "news", "earthquakes", "weather_alerts",
                "sigint", "gps_jamming", "correlations",
                "liveuamap", "firms_fires",
            ],
            "max_snapshots": 84,
        },
    },
    "preset": "active",
    "presets": {
        "paranoid":  {"high_freq": 5,   "standard": 30},
        "active":    {"high_freq": 15,  "standard": 120},
        "casual":    {"high_freq": 60,  "standard": 360},
        "minimal":   {"high_freq": 360, "standard": 0},
    },
}

# Persistence path
_TM_DIR = Path(os.environ.get("SB_DATA_DIR", ".")) / "timemachine"

# ---------------------------------------------------------------------------
# Layer compressors — keep only positional + identity data per entity type.
# Reduces snapshot size ~80-90% vs full deep-copy while retaining enough
# to render entities on the map.
# ---------------------------------------------------------------------------

def _round(v, n=3):
    """Safely round a numeric value.  Default 3 decimal places (~111 m)."""
    try:
        return round(float(v), n) if v is not None else None
    except (TypeError, ValueError):
        return None


def _strip_none(d: dict) -> dict:
    """Return a copy of *d* with all None-valued keys removed."""
    return {k: v for k, v in d.items() if v is not None}


LAYER_COMPRESSORS: dict[str, callable] = {
    "military_flights": lambda e: _strip_none({
        "cs": e.get("callsign"), "lat": _round(e.get("lat")),
        "lng": _round(e.get("lng")), "alt": e.get("alt"),
        "hdg": e.get("heading"), "t": e.get("type"), "ic": e.get("icao24"),
    }),
    "tracked_flights": lambda e: _strip_none({
        "cs": e.get("callsign"), "lat": _round(e.get("lat")),
        "lng": _round(e.get("lng")), "alt": e.get("alt"),
        "hdg": e.get("heading"), "ic": e.get("icao24"),
        "reg": e.get("registration"),
    }),
    "private_jets": lambda e: _strip_none({
        "cs": e.get("callsign"), "lat": _round(e.get("lat")),
        "lng": _round(e.get("lng")), "alt": e.get("alt"),
        "hdg": e.get("heading"), "ic": e.get("icao24"),
        "owner": (e.get("owner") or "")[:60] or None,
    }),
    "commercial_flights": lambda e: _strip_none({
        "cs": e.get("callsign"), "lat": _round(e.get("lat")),
        "lng": _round(e.get("lng")), "alt": e.get("alt"),
        "hdg": e.get("heading"),
    }),
    "ships": lambda e: _strip_none({
        "mmsi": e.get("mmsi"), "nm": (e.get("name") or "")[:40] or None,
        "lat": _round(e.get("lat")), "lng": _round(e.get("lng")),
        "hdg": e.get("heading"), "st": e.get("ship_type"),
    }),
    "satellites": lambda e: _strip_none({
        "id": e.get("id") or e.get("norad_id"), "nm": (e.get("name") or "")[:40] or None,
        "lat": _round(e.get("lat")), "lng": _round(e.get("lng")),
        "alt": _round(e.get("alt"), 1),
    }),
    "news": lambda e: _strip_none({
        "t": (e.get("title") or "")[:80] or None, "lat": _round(e.get("lat")),
        "lng": _round(e.get("lng")), "rs": e.get("risk_score"),
        "pd": e.get("pub_date"), "src": (e.get("source") or "")[:30] or None,
    }),
    "earthquakes": lambda e: _strip_none({
        "id": e.get("id"), "lat": _round(e.get("lat")),
        "lng": _round(e.get("lng")), "mag": e.get("magnitude"),
        "t": (e.get("title") or "")[:60] or None,
    }),
    "weather_alerts": lambda e: _strip_none({
        "id": e.get("id"), "lat": _round(e.get("lat")),
        "lng": _round(e.get("lng")), "sev": e.get("severity"),
        "ev": (e.get("event") or "")[:40] or None,
    }),
    "firms_fires": lambda e: _strip_none({
        "lat": _round(e.get("lat")), "lng": _round(e.get("lng")),
        "frp": e.get("frp"), "conf": e.get("confidence"),
    }),
    "crowdthreat": lambda e: _strip_none({
        "id": e.get("id"), "lat": _round(e.get("lat")),
        "lng": _round(e.get("lng")), "t": (e.get("title") or "")[:60] or None,
        "cat": e.get("category"),
    }),
    "sigint": lambda e: {
        # sigint is a dict of sub-arrays; pass through keys
        k: [_strip_none({"lat": _round(i.get("lat")), "lng": _round(i.get("lng")),
             "cs": i.get("callsign") or i.get("call") or i.get("id")})
            for i in (v if isinstance(v, list) else [])]
        for k, v in (e.items() if isinstance(e, dict) else [])
    },
}


def _compress_entity(layer: str, entity) -> dict | None:
    """Compress a single entity using the layer's compressor, or a generic fallback."""
    if not isinstance(entity, dict):
        return None
    compressor = LAYER_COMPRESSORS.get(layer)
    if compressor:
        return compressor(entity)
    # Generic fallback: keep lat/lng + id/name
    return _strip_none({
        "id": entity.get("id"),
        "lat": _round(entity.get("lat")),
        "lng": _round(entity.get("lng")),
        "nm": (entity.get("name") or entity.get("title") or "")[:60] or None,
    })


def _compress_layer_data(layer: str, data) -> list | dict:
    """Compress an entire layer's data."""
    # sigint is a dict of sub-arrays, handle specially
    if layer == "sigint" and isinstance(data, dict):
        compressor = LAYER_COMPRESSORS.get("sigint")
        if compressor:
            return compressor(data)
        return data
    if isinstance(data, list):
        compressed = []
        for entity in data:
            c = _compress_entity(layer, entity)
            if c is not None:
                compressed.append(c)
        return compressed
    # Scalar or unknown shape — return as-is
    return data


def _load_snapshots():
    """Load snapshots from disk on startup.

    Reads gzipped format first (``snapshots.json.gz``).  Falls back to the
    legacy uncompressed ``snapshots.json`` if the gzip file doesn't exist,
    then migrates the data to gzip on next save.
    """
    global _snapshots
    gz_file = _TM_DIR / "snapshots.json.gz"
    legacy_file = _TM_DIR / "snapshots.json"

    if gz_file.exists():
        try:
            with gzip.open(gz_file, "rt", encoding="utf-8") as f:
                _snapshots = json.load(f)
            logger.info("Time Machine: loaded %d snapshots from %s", len(_snapshots), gz_file)
            return
        except Exception as e:
            logger.warning("Time Machine: failed to load gzip snapshots: %s", e)

    if legacy_file.exists():
        try:
            with open(legacy_file, "r") as f:
                _snapshots = json.load(f)
            logger.info(
                "Time Machine: loaded %d snapshots from legacy %s (will migrate to gzip on next save)",
                len(_snapshots), legacy_file,
            )
        except Exception as e:
            logger.warning("Time Machine: failed to load legacy snapshots: %s", e)


def _save_snapshots_to_disk():
    """Persist snapshots to disk as gzip-compressed JSON.

    JSON compresses ~90% with gzip, cutting ~68 MB/day to ~5-8 MB/day.
    Also removes the legacy uncompressed file if it exists.
    """
    try:
        _TM_DIR.mkdir(parents=True, exist_ok=True)
        gz_file = _TM_DIR / "snapshots.json.gz"
        data = json.dumps(_snapshots[-_snapshot_max:], separators=(",", ":")).encode("utf-8")
        with gzip.open(gz_file, "wb", compresslevel=6) as f:
            f.write(data)
        # Remove legacy uncompressed file after successful gzip write
        legacy_file = _TM_DIR / "snapshots.json"
        if legacy_file.exists():
            try:
                legacy_file.unlink()
                logger.info("Time Machine: migrated to gzip, removed legacy snapshots.json")
            except Exception:
                pass  # not critical
    except Exception as e:
        logger.warning("Time Machine: failed to save snapshots: %s", e)


# Load on import
_load_snapshots()


# ---------------------------------------------------------------------------
# Core snapshot logic (callable from API, scheduler, and OpenClaw)
# ---------------------------------------------------------------------------

def _take_snapshot_internal(
    layers: list[str] | None = None,
    profile: str = "manual",
    compress: bool = False,
) -> dict:
    """Take a snapshot of current telemetry data.

    Args:
        layers: Specific layers to capture. None = all configured layers.
        profile: Label for the snapshot (manual, auto_high_freq, auto_standard, openclaw).
        compress: If True, use compressed_v1 format (positions + IDs only).

    Returns:
        Snapshot metadata dict (without the full data payload).
    """
    from services.fetchers._store import latest_data, _data_lock

    requested_layers = list(layers) if layers else []
    if not requested_layers:
        for prof in _timemachine_config["profiles"].values():
            requested_layers.extend(prof["layers"])
        requested_layers = list(set(requested_layers))

    now = datetime.utcnow()
    snapshot_data = {}
    with _data_lock:
        for layer in requested_layers:
            val = latest_data.get(layer)
            if val is not None:
                if compress:
                    snapshot_data[layer] = _compress_layer_data(layer, val)
                elif isinstance(val, (list, dict)):
                    snapshot_data[layer] = copy.deepcopy(val)
                else:
                    snapshot_data[layer] = val

    snapshot_id = f"snap-{now.strftime('%Y%m%d-%H%M%S')}-{len(_snapshots)}"
    snapshot = {
        "id": snapshot_id,
        "timestamp": now.isoformat() + "Z",
        "unix_ts": now.timestamp(),
        "format": "compressed_v1" if compress else "full",
        "layers": list(snapshot_data.keys()),
        "layer_counts": {k: len(v) if isinstance(v, list) else 1 for k, v in snapshot_data.items()},
        "profile": profile,
        "data": snapshot_data,
    }

    with _snapshots_lock:
        _snapshots.append(snapshot)
        if len(_snapshots) > _snapshot_max:
            _snapshots[:] = _snapshots[-_snapshot_max:]

    _save_snapshots_to_disk()

    return {
        "ok": True,
        "snapshot_id": snapshot_id,
        "timestamp": snapshot["timestamp"],
        "format": snapshot["format"],
        "layers": snapshot["layers"],
        "layer_counts": snapshot["layer_counts"],
    }


@router.post("/api/ai/timemachine/snapshot", dependencies=[Depends(require_openclaw_or_local)])
@limiter.limit("30/minute")
async def take_snapshot(request: Request, body: dict = None):
    """Take a snapshot of current telemetry.
    Optional body: {"layers": [...], "profile": "...", "compress": true}"""
    body = body or {}
    result = await asyncio.to_thread(
        _take_snapshot_internal,
        layers=body.get("layers"),
        profile=body.get("profile", "manual"),
        compress=body.get("compress", False),
    )
    return result


@router.get("/api/ai/timemachine/snapshots", dependencies=[Depends(require_openclaw_or_local)])
@limiter.limit("60/minute")
async def list_snapshots(
    request: Request,
    layer: str = "",
    since: float = 0,
    until: float = 0,
    limit: int = Query(20, ge=1, le=100),
):
    """List available snapshots, optionally filtered by layer and time range.
    Returns metadata only (no full data) for fast listing."""
    results = []
    with _snapshots_lock:
        for snap in reversed(_snapshots):
            # Time filters
            ts = snap.get("unix_ts", 0)
            if since and ts < since:
                continue
            if until and ts > until:
                continue
            # Layer filter
            if layer and layer not in snap.get("layers", []):
                continue

            results.append({
                "id": snap["id"],
                "timestamp": snap["timestamp"],
                "unix_ts": snap.get("unix_ts"),
                "format": snap.get("format", "full"),
                "layers": snap["layers"],
                "layer_counts": snap["layer_counts"],
                "profile": snap.get("profile"),
            })
            if len(results) >= limit:
                break

    return {"ok": True, "count": len(results), "snapshots": results}


@router.get("/api/ai/timemachine/snapshot/{snapshot_id}", dependencies=[Depends(require_openclaw_or_local)])
@limiter.limit("30/minute")
async def get_snapshot(
    request: Request,
    snapshot_id: str,
    layer: str = "",
):
    """Retrieve a specific snapshot's full data.
    Optional layer filter returns only that layer's data."""
    with _snapshots_lock:
        for snap in _snapshots:
            if snap["id"] == snapshot_id:
                if layer:
                    data = snap.get("data", {}).get(layer)
                    if data is None:
                        raise HTTPException(404, f"Layer '{layer}' not in snapshot")
                    return {
                        "ok": True,
                        "snapshot_id": snapshot_id,
                        "timestamp": snap["timestamp"],
                        "layer": layer,
                        "count": len(data) if isinstance(data, list) else 1,
                        "data": data,
                    }
                return {
                    "ok": True,
                    "snapshot_id": snapshot_id,
                    "timestamp": snap["timestamp"],
                    "layers": snap["layers"],
                    "layer_counts": snap["layer_counts"],
                    "data": snap.get("data", {}),
                }
    raise HTTPException(404, f"Snapshot '{snapshot_id}' not found")


@router.get("/api/ai/timemachine/hourly-index", dependencies=[Depends(require_openclaw_or_local)])
@limiter.limit("60/minute")
async def timemachine_hourly_index(request: Request):
    """Return snapshot availability per hour for the last 24h.
    Used by the TimelineScrubber to show which bins are clickable."""
    now = datetime.utcnow()
    cutoff = now.timestamp() - 24 * 3600

    hours: dict[int, dict] = {}
    with _snapshots_lock:
        for snap in reversed(_snapshots):
            ts = snap.get("unix_ts", 0)
            if ts < cutoff:
                continue
            snap_dt = datetime.utcfromtimestamp(ts)
            h = snap_dt.hour
            if h not in hours:
                hours[h] = {
                    "count": 0,
                    "latest_id": snap["id"],
                    "latest_ts": snap["timestamp"],
                    "snapshot_ids": [],
                }
            hours[h]["count"] += 1
            hours[h]["snapshot_ids"].append(snap["id"])

    return {"ok": True, "hours": hours}


@router.get("/api/ai/timemachine/playback/{snapshot_id}", dependencies=[Depends(require_openclaw_or_local)])
@limiter.limit("30/minute")
async def timemachine_playback(request: Request, snapshot_id: str):
    """Load a snapshot's data in the same shape as /api/live-data/* for map rendering.
    Compressed snapshots are expanded with sensible defaults so map components
    can render them without modification."""
    with _snapshots_lock:
        target = None
        for snap in _snapshots:
            if snap["id"] == snapshot_id:
                target = snap
                break
    if target is None:
        raise HTTPException(404, f"Snapshot '{snapshot_id}' not found")

    snap_format = target.get("format", "full")
    data = target.get("data", {})

    # For compressed snapshots, expand shortened keys back to full field names
    if snap_format == "compressed_v1":
        expanded = {}
        for layer, items in data.items():
            if isinstance(items, list):
                expanded[layer] = [_expand_compressed_entity(layer, e) for e in items]
            else:
                expanded[layer] = items
        data = expanded

    return {
        "ok": True,
        "snapshot_id": target["id"],
        "timestamp": target["timestamp"],
        "unix_ts": target.get("unix_ts"),
        "format": snap_format,
        "mode": "playback",
        "layers": target["layers"],
        "layer_counts": target["layer_counts"],
        "data": data,
    }


# Expansion maps: compressed short keys → full field names expected by frontend
_EXPAND_MAPS: dict[str, dict[str, str]] = {
    "military_flights": {"cs": "callsign", "lng": "lng", "lat": "lat", "alt": "alt", "hdg": "heading", "t": "type", "ic": "icao24"},
    "tracked_flights": {"cs": "callsign", "lng": "lng", "lat": "lat", "alt": "alt", "hdg": "heading", "ic": "icao24", "reg": "registration"},
    "private_jets": {"cs": "callsign", "lng": "lng", "lat": "lat", "alt": "alt", "hdg": "heading", "ic": "icao24", "owner": "owner"},
    "commercial_flights": {"cs": "callsign", "lng": "lng", "lat": "lat", "alt": "alt", "hdg": "heading"},
    "ships": {"mmsi": "mmsi", "nm": "name", "lng": "lng", "lat": "lat", "hdg": "heading", "st": "ship_type"},
    "satellites": {"id": "id", "nm": "name", "lng": "lng", "lat": "lat", "alt": "alt"},
    "news": {"t": "title", "lng": "lng", "lat": "lat", "rs": "risk_score", "pd": "pub_date", "src": "source"},
    "earthquakes": {"id": "id", "lng": "lng", "lat": "lat", "mag": "magnitude", "t": "title"},
    "weather_alerts": {"id": "id", "lng": "lng", "lat": "lat", "sev": "severity", "ev": "event"},
    "firms_fires": {"lng": "lng", "lat": "lat", "frp": "frp", "conf": "confidence"},
    "crowdthreat": {"id": "id", "lng": "lng", "lat": "lat", "t": "title", "cat": "category"},
}


def _expand_compressed_entity(layer: str, entity: dict) -> dict:
    """Expand a compressed entity back to full field names."""
    expand_map = _EXPAND_MAPS.get(layer)
    if not expand_map:
        return entity
    expanded = {}
    for short_key, val in entity.items():
        full_key = expand_map.get(short_key, short_key)
        expanded[full_key] = val
    return expanded


@router.delete("/api/ai/timemachine/snapshots", dependencies=[Depends(require_openclaw_or_local)])
@limiter.limit("10/minute")
async def clear_snapshots(
    request: Request,
    before: float = 0,
):
    """Clear snapshots. If 'before' unix timestamp provided, only clears older ones."""
    with _snapshots_lock:
        if before:
            original = len(_snapshots)
            _snapshots[:] = [s for s in _snapshots if s.get("unix_ts", 0) >= before]
            removed = original - len(_snapshots)
        else:
            removed = len(_snapshots)
            _snapshots.clear()

    await asyncio.to_thread(_save_snapshots_to_disk)
    return {"ok": True, "removed": removed, "remaining": len(_snapshots)}


@router.get("/api/ai/timemachine/config", dependencies=[Depends(require_openclaw_or_local)])
@limiter.limit("60/minute")
async def get_timemachine_config(request: Request):
    """Get current Time Machine configuration."""
    return {"ok": True, "config": _timemachine_config}


@router.put("/api/ai/timemachine/config", dependencies=[Depends(require_openclaw_or_local)])
@limiter.limit("10/minute")
async def update_timemachine_config(request: Request, body: dict):
    """Update Time Machine configuration.
    Can set a preset ("paranoid", "active", "casual", "minimal")
    or customize individual profile intervals and layers."""
    preset = body.get("preset")
    if preset and preset in _timemachine_config["presets"]:
        intervals = _timemachine_config["presets"][preset]
        _timemachine_config["profiles"]["high_freq"]["interval_minutes"] = intervals["high_freq"]
        _timemachine_config["profiles"]["standard"]["interval_minutes"] = intervals["standard"]
        _timemachine_config["preset"] = preset

    # Custom profile overrides
    if "high_freq" in body:
        for k, v in body["high_freq"].items():
            if k in _timemachine_config["profiles"]["high_freq"]:
                _timemachine_config["profiles"]["high_freq"][k] = v
    if "standard" in body:
        for k, v in body["standard"].items():
            if k in _timemachine_config["profiles"]["standard"]:
                _timemachine_config["profiles"]["standard"][k] = v

    return {"ok": True, "config": _timemachine_config}


@router.get("/api/ai/timemachine/diff", dependencies=[Depends(require_openclaw_or_local)])
@limiter.limit("30/minute")
async def diff_snapshots(
    request: Request,
    snapshot_a: str = Query(..., description="Earlier snapshot ID"),
    snapshot_b: str = Query(..., description="Later snapshot ID"),
    layer: str = Query(..., description="Layer to compare"),
):
    """Compare two snapshots and return what changed in a specific layer.
    Returns added, removed, and count changes."""
    snap_a_data = None
    snap_b_data = None

    with _snapshots_lock:
        for snap in _snapshots:
            if snap["id"] == snapshot_a:
                snap_a_data = snap.get("data", {}).get(layer, [])
            if snap["id"] == snapshot_b:
                snap_b_data = snap.get("data", {}).get(layer, [])

    if snap_a_data is None:
        raise HTTPException(404, f"Snapshot '{snapshot_a}' not found or missing layer '{layer}'")
    if snap_b_data is None:
        raise HTTPException(404, f"Snapshot '{snapshot_b}' not found or missing layer '{layer}'")

    # Simple count diff
    count_a = len(snap_a_data) if isinstance(snap_a_data, list) else 0
    count_b = len(snap_b_data) if isinstance(snap_b_data, list) else 0

    return {
        "ok": True,
        "snapshot_a": snapshot_a,
        "snapshot_b": snapshot_b,
        "layer": layer,
        "count_a": count_a,
        "count_b": count_b,
        "delta": count_b - count_a,
        "summary": f"{layer}: {count_a} → {count_b} ({'+' if count_b >= count_a else ''}{count_b - count_a})",
    }


# ───────────────────────── AI NEWS SUMMARY ────────────────────────
@router.get("/ai/news/summary")
@limiter.limit("10/minute")
async def ai_news_summary(request: Request):
    """Return a structured AI-generated summary of current news articles.
    Works without an LLM — extracts top stories, regional breakdown,
    threat distribution, and trending keywords from the raw feed."""
    from collections import Counter

    news = _latest_data.get("news", [])
    if not news:
        return {
            "ok": True,
            "article_count": 0,
            "summary": "No news articles currently available.",
            "top_stories": [],
            "regions": {},
            "threat_distribution": {},
            "keywords": [],
        }

    # Top stories (highest risk score)
    sorted_news = sorted(news, key=lambda a: a.get("risk_score", 0), reverse=True)
    top_stories = []
    for article in sorted_news[:8]:
        top_stories.append({
            "title": article.get("title", "Untitled"),
            "source": article.get("source", "Unknown"),
            "risk_score": article.get("risk_score", 0),
            "sentiment": article.get("sentiment"),
            "link": article.get("link", ""),
            "published": article.get("published", ""),
        })

    # Regional breakdown
    region_counter: Counter = Counter()
    for article in news:
        src = str(article.get("source", "Unknown")).strip()
        if src:
            region_counter[src] += 1

    # Threat distribution
    threat_dist: dict = {"CRITICAL": 0, "HIGH": 0, "ELEVATED": 0, "MODERATE": 0, "LOW": 0}
    for article in news:
        score = article.get("risk_score", 0)
        if score >= 9:
            threat_dist["CRITICAL"] += 1
        elif score >= 7:
            threat_dist["HIGH"] += 1
        elif score >= 5:
            threat_dist["ELEVATED"] += 1
        elif score >= 3:
            threat_dist["MODERATE"] += 1
        else:
            threat_dist["LOW"] += 1

    # Keyword extraction (simple word frequency from titles)
    stop_words = {
        "the", "a", "an", "in", "on", "at", "to", "for", "of", "and",
        "is", "are", "was", "were", "be", "been", "has", "had", "have",
        "with", "by", "from", "as", "it", "its", "this", "that", "or",
        "but", "not", "no", "will", "can", "may", "would", "could",
        "should", "do", "does", "did", "he", "she", "they", "we", "you",
        "i", "me", "my", "our", "your", "their", "his", "her", "us",
        "up", "out", "if", "about", "into", "over", "after", "new",
        "says", "said", "also", "more", "than", "just", "been", "being",
    }
    word_counter: Counter = Counter()
    for article in news:
        title = str(article.get("title", ""))
        words = title.lower().split()
        for word in words:
            clean = word.strip(".,!?:;\"'()[]{}–—-")
            if len(clean) > 2 and clean not in stop_words:
                word_counter[clean] += 1

    trending = [{"word": w, "count": c} for w, c in word_counter.most_common(15)]

    # Build plain-text summary
    breaking_count = sum(1 for a in news if a.get("breaking"))
    avg_risk = sum(a.get("risk_score", 0) for a in news) / len(news) if news else 0
    summary_lines = [
        f"📊 {len(news)} articles tracked across {len(region_counter)} sources.",
        f"⚡ {breaking_count} BREAKING articles." if breaking_count else "",
        f"🎯 Average threat score: {avg_risk:.1f}/10.",
        f"🔴 {threat_dist['CRITICAL']} critical, {threat_dist['HIGH']} high-threat articles.",
    ]
    summary = " ".join(line for line in summary_lines if line)

    return {
        "ok": True,
        "article_count": len(news),
        "breaking_count": breaking_count,
        "avg_risk_score": round(avg_risk, 2),
        "summary": summary,
        "top_stories": top_stories,
        "regions": dict(region_counter.most_common(20)),
        "threat_distribution": threat_dist,
        "keywords": trending,
    }


# ───────────────────────── CORRELATION EXPLANATIONS ────────────────────────
_CORR_TYPE_LABELS = {
    "rf_anomaly": "RF ANOMALY — Electromagnetic Interference Detected",
    "military_buildup": "MILITARY BUILDUP — Force Concentration Alert",
    "infra_cascade": "INFRASTRUCTURE CASCADE — Multi-System Failure",
}

_CORR_TYPE_IMPLICATIONS = {
    "rf_anomaly": [
        "Active GPS/GNSS jamming or spoofing is occurring in this zone.",
        "Civilian aviation may be affected — pilots should cross-check inertial navigation.",
        "Electronic warfare (EW) operations may be underway.",
        "Simultaneous internet outages suggest coordinated infrastructure targeting.",
    ],
    "military_buildup": [
        "Concentration of military assets indicates potential operational staging.",
        "GDELT conflict events corroborate elevated tensions in this zone.",
        "Naval and air assets co-located suggests multi-domain readiness posture.",
        "Monitor for NOTAM closures or TFRs that may confirm military activity.",
    ],
    "infra_cascade": [
        "Internet outages are disrupting SIGINT-grade radio monitoring (KiwiSDR).",
        "Loss of KiwiSDR receivers reduces ally HF intelligence collection capability.",
        "May indicate power grid failure, cable cuts, or deliberate network isolation.",
        "Correlate with regional news for civil unrest or natural disaster reports.",
    ],
}


@router.get("/ai/correlations/explain")
@limiter.limit("10/minute")
async def ai_correlation_explanations(request: Request):
    """Return structured intelligence explanations for each active correlation alert.
    Works without an LLM — generates explanations from pre-built templates and data."""

    correlations = _latest_data.get("correlations", [])
    if not correlations:
        return {
            "ok": True,
            "count": 0,
            "explanations": [],
            "summary": "No cross-layer correlations are currently active.",
        }

    explanations = []
    for i, corr in enumerate(correlations):
        ctype = corr.get("type", "unknown")
        sev = corr.get("severity", "low")
        score = corr.get("score", 0)
        drivers = corr.get("drivers", [])
        lat = corr.get("lat", 0)
        lng = corr.get("lng", 0)

        label = _CORR_TYPE_LABELS.get(ctype, f"UNKNOWN CORRELATION — {ctype}")
        implications = _CORR_TYPE_IMPLICATIONS.get(ctype, [
            "Unknown correlation type — manual analysis recommended.",
        ])

        # Generate driver analysis
        driver_text = " | ".join(drivers) if drivers else "No driver data"

        # Severity assessment
        if sev == "high":
            sev_text = "⚠️ HIGH — Immediate attention required"
            action = "Deploy monitoring assets and establish continuous watch."
        elif sev == "medium":
            sev_text = "🟡 MEDIUM — Elevated concern"
            action = "Increase polling frequency and flag for analyst review."
        else:
            sev_text = "🟢 LOW — Awareness level"
            action = "Log for trend analysis and continue standard monitoring."

        explanations.append({
            "index": i,
            "type": ctype,
            "label": label,
            "lat": lat,
            "lng": lng,
            "severity": sev,
            "severity_text": sev_text,
            "score": score,
            "drivers": drivers,
            "driver_summary": driver_text,
            "implications": implications[:3],
            "recommended_action": action,
            "explanation": (
                f"{label}\n"
                f"Location: {lat:.2f}°, {lng:.2f}°\n"
                f"Severity: {sev_text}\n"
                f"Indicators: {driver_text}\n"
                f"Assessment: {implications[0]}\n"
                f"Action: {action}"
            ),
        })

    # Build overall summary
    by_type: dict = {}
    for e in explanations:
        by_type.setdefault(e["type"], []).append(e)

    type_summaries = []
    for ctype, items in by_type.items():
        high = sum(1 for x in items if x["severity"] == "high")
        med = sum(1 for x in items if x["severity"] == "medium")
        label = _CORR_TYPE_LABELS.get(ctype, ctype).split("—")[0].strip()
        type_summaries.append(f"{label}: {len(items)} alerts ({high} high, {med} medium)")

    summary = (
        f"🌍📡 CORRELATION ANALYSIS: {len(correlations)} active cross-layer alerts. "
        + " | ".join(type_summaries)
    )

    return {
        "ok": True,
        "count": len(explanations),
        "explanations": explanations,
        "by_type": {k: len(v) for k, v in by_type.items()},
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# Agent Tool Manifest — machine-readable tool definitions for LLM agents
# ---------------------------------------------------------------------------
# Any LLM agent (OpenClaw, custom, etc.) hits this endpoint once on connect
# and loads the result as its tool definitions. No manual reading required.

@router.get("/api/ai/tools", dependencies=[Depends(require_openclaw_or_local)])
@limiter.limit("30/minute")
async def agent_tool_manifest(request: Request):
    """Return structured tool definitions that an LLM agent can load directly.

    This is the machine-readable equivalent of /api/ai/capabilities.
    An agent loads these as its available tools on first connect.
    Each tool has: name, description, parameters (with types), and examples.
    """
    from services.openclaw_channel import READ_COMMANDS, WRITE_COMMANDS
    from services.config import get_settings

    access_tier = str(get_settings().OPENCLAW_ACCESS_TIER or "restricted").strip().lower()
    available_commands = sorted(READ_COMMANDS | WRITE_COMMANDS) if access_tier == "full" else sorted(READ_COMMANDS)

    return {
        "ok": True,
        "version": "0.9.7",
        "access_tier": access_tier,
        "available_commands": available_commands,
        "transport": {
            "commands": "POST /api/ai/channel/command  body: {\"cmd\": \"<tool_name>\", \"args\": {<params>}}",
            "batch": "POST /api/ai/channel/batch  body: {\"commands\": [{\"cmd\": \"...\", \"args\": {...}}, ...]}  (max 20, concurrent execution, one HTTP round-trip)",
            "realtime_stream": "GET /api/ai/channel/sse  (Server-Sent Events — keeps Tor circuit warm, receives push events)",
            "auth": "HMAC-SHA256 headers: X-SB-Timestamp, X-SB-Nonce, X-SB-Signature. Sign: HMAC(key, METHOD|path|ts|nonce|sha256(body))",
        },
        "tools": [
            # ── Read Tools ────────────────────────────────────
            {
                "name": "get_summary",
                "type": "read",
                "description": "Get counts of all live fast-tier and slow-tier telemetry layers, plus available layer names and common aliases. Use this first for layer discovery before pulling datasets.",
                "parameters": {},
                "returns": "{counts: {...}, available_layers: [...], non_empty_layers: [...], layer_aliases: {...}, last_updated, version}",
            },
            {
                "name": "get_layer_slice",
                "type": "read",
                "description": "Get only specific top-level telemetry layers, with optional version gating so unchanged reads return empty. Accepts friendly aliases like gfw/global_fishing_watch → fishing_activity and uap/ufo → uap_sightings. Layer slices are uncapped unless you pass a positive limit_per_layer.",
                "parameters": {
                    "layers": {"type": "array", "required": True, "description": "Requested top-level layer names, e.g. ['tracked_flights', 'ships', 'news']"},
                    "limit_per_layer": {"type": "integer", "required": False, "description": "Optional positive cap per layer. Omit or pass 0/negative for the full layer."},
                    "since_version": {"type": "integer", "required": False, "description": "If equal to current server version, response returns changed=false with empty layers"},
                    "compact": {"type": "boolean", "required": False, "description": "If true, layers are returned in compressed_v1 schema (short keys, 3-decimal lat/lng, None-stripped). Response includes format: 'compressed_v1'."},
                },
                "returns": "{version: int, changed: bool, layers: {...}, requested_layers: [...], missing_layers: [...], available_layers: [...], truncated: {...}}",
            },
            {
                "name": "find_flights",
                "type": "read",
                "description": "Search flights server-side by callsign, registration, ICAO24, owner/operator, or free-text query. Returns a compact result set instead of the full flight snapshot.",
                "parameters": {
                    "query": {"type": "string", "required": False, "description": "Free-text match across callsign, registration, owner, operator, type"},
                    "callsign": {"type": "string", "required": False, "description": "Exact/partial callsign filter"},
                    "registration": {"type": "string", "required": False, "description": "Tail number filter"},
                    "icao24": {"type": "string", "required": False, "description": "ICAO24 hex id filter"},
                    "owner": {"type": "string", "required": False, "description": "Owner/operator/person filter"},
                    "categories": {"type": "array", "required": False, "description": "Flight layers to search: tracked, military, jets, private, commercial"},
                    "limit": {"type": "integer", "required": False, "description": "Max results (default 25, max 100)"},
                    "compact": {"type": "boolean", "required": False, "description": "If true, strips empty/None fields from each result and rounds lat/lng to 3 decimals. Response includes format: 'compressed_v1'."},
                },
                "returns": "{results: [{source_layer, callsign, registration, icao24, owner, type, lat, lng, ...}], version: int, truncated: bool}",
            },
            {
                "name": "find_ships",
                "type": "read",
                "description": "Search ships server-side by MMSI, IMO, name, yacht-owner enrichment, or free-text query. Returns only compact ship matches.",
                "parameters": {
                    "query": {"type": "string", "required": False, "description": "Free-text match across ship name, MMSI, IMO, callsign, type, yacht owner, tracked yacht name"},
                    "mmsi": {"type": "string", "required": False, "description": "Exact MMSI filter"},
                    "imo": {"type": "string", "required": False, "description": "Exact IMO filter"},
                    "name": {"type": "string", "required": False, "description": "Ship name filter"},
                    "limit": {"type": "integer", "required": False, "description": "Max results (default 25, max 100)"},
                    "compact": {"type": "boolean", "required": False, "description": "If true, strips empty/None fields from each result and rounds lat/lng to 3 decimals. Response includes format: 'compressed_v1'."},
                },
                "returns": "{results: [{mmsi, imo, name, owner, tracked_name, tracked_category, callsign, type, lat, lng, ...}], version: int, truncated: bool}",
            },
            {
                "name": "find_entity",
                "type": "read",
                "description": "Resolve a plane, ship, person, operator, callsign, registration, MMSI, IMO, ICAO24, or named entity with exact aircraft/ship matching first and universal telemetry search second. Use this before tracking a named entity.",
                "parameters": {
                    "query": {"type": "string", "required": False, "description": "Natural-language name, operator, owner, callsign, vessel name, or entity label"},
                    "entity_type": {"type": "string", "required": False, "description": "Optional type hint: aircraft, plane, ship, vessel, maritime, person, infrastructure, event"},
                    "callsign": {"type": "string", "required": False, "description": "Aircraft or vessel callsign"},
                    "registration": {"type": "string", "required": False, "description": "Aircraft tail number / registration"},
                    "icao24": {"type": "string", "required": False, "description": "Aircraft ICAO24 hex identifier"},
                    "mmsi": {"type": "string", "required": False, "description": "Ship MMSI"},
                    "imo": {"type": "string", "required": False, "description": "Ship IMO number"},
                    "name": {"type": "string", "required": False, "description": "Known aircraft/vessel/entity name"},
                    "owner": {"type": "string", "required": False, "description": "Owner, operator, yacht owner, or alert_operator"},
                    "layers": {"type": "array", "required": False, "description": "Optional telemetry layer subset for universal fallback search"},
                    "limit": {"type": "integer", "required": False, "description": "Max results (default 10, max 50)"},
                },
                "returns": "{best_match: {...}|null, results: [{source_layer, entity_type, label, id, callsign, registration, icao24, mmsi, imo, owner, lat, lng, score, confidence}], searched_layers: [...], strategy: [...]}",
                "example": {"cmd": "find_entity", "args": {"entity_type": "aircraft", "callsign": "AF1", "owner": "USAF"}},
            },
            {
                "name": "correlate_entity",
                "type": "read",
                "description": "Resolve an entity exactly, then build a compact evidence pack around its current position: nearby tracked entities, active correlations, SAR anomalies, outages, weather/RF hazards, and nearby reporting. This is a lead generator, not a causation verdict.",
                "parameters": {
                    "query": {"type": "string", "required": False, "description": "Natural-language name, operator, owner, callsign, vessel name, or entity label"},
                    "entity_type": {"type": "string", "required": False, "description": "Optional type hint: aircraft, ship, person, event, infrastructure"},
                    "callsign": {"type": "string", "required": False, "description": "Aircraft or vessel callsign"},
                    "registration": {"type": "string", "required": False, "description": "Aircraft tail number / registration"},
                    "icao24": {"type": "string", "required": False, "description": "Aircraft ICAO24 hex identifier"},
                    "mmsi": {"type": "string", "required": False, "description": "Ship MMSI"},
                    "imo": {"type": "string", "required": False, "description": "Ship IMO number"},
                    "name": {"type": "string", "required": False, "description": "Known aircraft/vessel/entity name"},
                    "owner": {"type": "string", "required": False, "description": "Owner, operator, yacht owner, or alert_operator"},
                    "radius_km": {"type": "float", "required": False, "description": "Context radius in km (default 100, max 1000)"},
                    "limit": {"type": "integer", "required": False, "description": "Max records per evidence group (default 10, max 50)"},
                },
                "returns": "{status, claim_level, entity, center, radius_km, signals, evidence: {proximate_entities, context_layers}, recommended_next}",
                "example": {"cmd": "correlate_entity", "args": {"entity_type": "aircraft", "callsign": "AF1", "radius_km": 150}},
            },
            {
                "name": "search_telemetry",
                "type": "read",
                "description": "Universal compact search across telemetry layers. Use this when you know what you are looking for but not which layer holds it.",
                "parameters": {
                    "query": {"type": "string", "required": True, "description": "Keyword, person, vessel, place, protest topic, owner, callsign, etc."},
                    "layers": {"type": "array", "required": False, "description": "Optional layer subset to constrain search. Omit to search the full universal index across telemetry."},
                    "limit": {"type": "integer", "required": False, "description": "Max results (default 25, max 100)"},
                    "compact": {"type": "boolean", "required": False, "description": "If true, strips empty/None fields from each result and rounds lat/lng to 3 decimals. Response includes format: 'compressed_v1'."},
                },
                "returns": "{results: [{source_layer, label, summary, type, id, lat, lng, time, score}], version: int, truncated: bool, searched_layers: [...]}",
            },
            {
                "name": "search_news",
                "type": "read",
                "description": "Search news and event layers server-side by keyword. Includes news, GDELT, CrowdThreat, and major incident/event feeds without pulling the full slow telemetry feed.",
                "parameters": {
                    "query": {"type": "string", "required": True, "description": "Keyword or phrase to search for"},
                    "limit": {"type": "integer", "required": False, "description": "Max results (default 10, max 50)"},
                    "include_gdelt": {"type": "boolean", "required": False, "description": "Include GDELT matches (default true)"},
                    "compact": {"type": "boolean", "required": False, "description": "If true, strips empty/None fields from each result and rounds lat/lng to 3 decimals. Response includes format: 'compressed_v1'."},
                },
                "returns": "{results: [{source_layer, title, summary, source, link, lat, lng, risk_score}], version: int, truncated: bool}",
            },
            {
                "name": "entities_near",
                "type": "read",
                "description": "Run a proximity search around a coordinate across selected telemetry layers. Useful for 'what is near here?' without pulling whole datasets.",
                "parameters": {
                    "lat": {"type": "float", "required": True, "description": "Center latitude"},
                    "lng": {"type": "float", "required": True, "description": "Center longitude"},
                    "radius_km": {"type": "float", "required": False, "description": "Search radius in km (default 50)"},
                    "entity_types": {"type": "array", "required": False, "description": "Layers to search: tracked, military, jets, private, commercial, ships, uavs, satellites, earthquakes, news"},
                    "limit": {"type": "integer", "required": False, "description": "Max results (default 25, max 100)"},
                    "compact": {"type": "boolean", "required": False, "description": "If true, strips empty/None fields from each result and rounds lat/lng to 3 decimals. Response includes format: 'compressed_v1'."},
                },
                "returns": "{results: [{source_layer, label, lat, lng, distance_km, type, id}], version: int, truncated: bool}",
            },
            {
                "name": "brief_area",
                "type": "read",
                "description": "Compact area briefing around a coordinate: nearby entities, optional topic news, and selected context layers. Use instead of pulling full fast+slow telemetry for a location question.",
                "parameters": {
                    "lat": {"type": "float", "required": True, "description": "Center latitude"},
                    "lng": {"type": "float", "required": True, "description": "Center longitude"},
                    "radius_km": {"type": "float", "required": False, "description": "Search radius in km (default 50)"},
                    "entity_types": {"type": "array", "required": False, "description": "Nearby entity layers/types to include, default aircraft and ships"},
                    "query": {"type": "string", "required": False, "description": "Optional topic/news keyword for the area brief"},
                    "limit": {"type": "integer", "required": False, "description": "Max nearby entities (default 25)"},
                    "context_limit": {"type": "integer", "required": False, "description": "Max records from each context layer (default 10)"},
                },
                "returns": "{center, radius_km, nearby, topic_news, context_layers}",
            },
            {
                "name": "what_changed",
                "type": "read",
                "description": "Incremental change helper. Without layers, returns summary/version metadata. With layers, returns only requested layer slices with since_version or since_layer_versions gating.",
                "parameters": {
                    "layers": {"type": "array", "required": False, "description": "Optional top-level layers to check"},
                    "since_version": {"type": "integer", "required": False, "description": "Global version previously seen by the agent"},
                    "since_layer_versions": {"type": "object", "required": False, "description": "Per-layer versions previously seen by the agent"},
                    "limit_per_layer": {"type": "integer", "required": False, "description": "Optional cap per changed layer"},
                    "compact": {"type": "boolean", "required": False, "description": "Return compact layer payloads when true"},
                },
                "returns": "{version, changed, layers, layer_versions, requested_layers, truncated} or summary metadata",
            },
            {
                "name": "get_telemetry",
                "type": "read",
                "description": "Get all fast-refresh telemetry data: flights (commercial, military, private, tracked/VIP), ships, satellites, sigint, CCTV, trains, GPS jamming, conflict zones. "
                               "The 'tracked_flights' array contains enriched VIP aircraft with alert_operator (person name), alert_category, alert_socials, alert_color. "
                               "This is the 'Tracked Aircraft — People' layer — it includes billionaires, politicians, military, etc. "
                               "Pass compact=true for a smaller compressed_v1 payload (~60-90% reduction) — parses faster for agents.",
                "parameters": {
                    "compact": {"type": "boolean", "required": False, "description": "If true, emit compressed_v1 schema (short keys like cs/ic/hdg/t, 3-decimal lat/lng, None-stripped). Same information, ~60-90% smaller. Response includes format: 'compressed_v1'."},
                },
                "returns": "Object with arrays: commercial_flights, military_flights, private_flights, private_jets, tracked_flights, ships, satellites, sigint, cctv, uavs, liveuamap, gps_jamming, trains",
            },
            {
                "name": "get_slow_telemetry",
                "type": "read",
                "description": "Get slow-refresh data: news headlines, GDELT conflict events, prediction markets, earthquakes, weather, internet outages, military bases, power plants, volcanoes, fire hotspots, correlations, air quality. "
                               "Pass compact=true for a smaller compressed_v1 payload — parses faster for agents.",
                "parameters": {
                    "compact": {"type": "boolean", "required": False, "description": "If true, emit compressed_v1 schema (short keys, 3-decimal lat/lng, None-stripped). Same information, ~60-90% smaller. Response includes format: 'compressed_v1'."},
                },
                "returns": "Object with arrays/objects for each slow data source",
            },
            {
                "name": "get_report",
                "type": "read",
                "description": "Get combined fast + slow telemetry in one call. Large response — use get_summary first, then targeted get_telemetry or get_slow_telemetry. "
                               "Pass compact=true to shrink both halves to compressed_v1 schema.",
                "parameters": {
                    "compact": {"type": "boolean", "required": False, "description": "If true, both fast and slow halves emit compressed_v1 schema (short keys, 3-decimal lat/lng, None-stripped). Response includes format: 'compressed_v1'."},
                },
                "returns": "{fast: <telemetry>, slow: <slow_telemetry>}",
            },
            {
                "name": "get_sigint_totals",
                "type": "read",
                "description": "Get signal intelligence counts: Meshtastic mesh nodes, APRS ham radio, JS8Call digital mode.",
                "parameters": {},
                "returns": "{meshtastic: N, aprs: N, js8call: N}",
            },
            {
                "name": "get_prediction_markets",
                "type": "read",
                "description": "Get live prediction market data from Polymarket and Kalshi. Includes probabilities, volume, and event descriptions.",
                "parameters": {},
                "returns": "Array of market objects with title, probability, volume, source",
            },
            {
                "name": "get_ai_pins",
                "type": "read",
                "description": "Get all intel pins currently placed on the map (by agents or operators).",
                "parameters": {},
                "returns": "Array of pin objects with id, lat, lng, label, category, description, source, created_at",
            },
            {
                "name": "get_layers",
                "type": "read",
                "description": "Get all custom pin layers (groupings of pins).",
                "parameters": {},
                "returns": "Array of layer objects with id, name, color, pin_count",
            },
            {
                "name": "get_correlations",
                "type": "read",
                "description": "Get cross-domain correlation alerts: infrastructure cascades, possible contradictions (official denials near outages), anomaly clusters.",
                "parameters": {},
                "returns": "Array of correlation alert objects with type, confidence, location, drivers, alternatives",
            },
            {
                "name": "list_watches",
                "type": "read",
                "description": "List all active watchdog watches (aircraft tracking, geofences, keyword monitors, etc.).",
                "parameters": {},
                "returns": "Array of watch objects with id, type, params, created_at",
            },
            {
                "name": "sar_status",
                "type": "read",
                "description": "Get SAR/OpenClaw integration status, catalog readiness, product fetch status, and private-tier publish requirement.",
                "parameters": {},
                "returns": "{catalog_enabled, products, require_private_tier}",
            },
            {
                "name": "sar_anomalies_recent",
                "type": "read",
                "description": "List recent SAR anomalies, optionally filtered by anomaly kind.",
                "parameters": {
                    "kind": {"type": "string", "required": False, "description": "Optional anomaly kind filter"},
                    "limit": {"type": "integer", "required": False, "description": "Max anomalies (default 25)"},
                },
            },
            {
                "name": "sar_anomalies_near",
                "type": "read",
                "description": "Find SAR anomalies near a coordinate.",
                "parameters": {
                    "lat": {"type": "float", "required": True, "description": "Center latitude"},
                    "lng": {"type": "float", "required": True, "description": "Center longitude"},
                    "radius_km": {"type": "float", "required": False, "description": "Search radius in km (default 50)"},
                    "limit": {"type": "integer", "required": False, "description": "Max anomalies (default 25)"},
                },
            },
            {
                "name": "sar_scene_search",
                "type": "read",
                "description": "Search cached SAR scenes, optionally scoped to an AOI.",
                "parameters": {
                    "aoi_id": {"type": "string", "required": False, "description": "AOI id to filter scenes"},
                    "limit": {"type": "integer", "required": False, "description": "Max scenes (default 25)"},
                },
            },
            {
                "name": "sar_coverage_for_aoi",
                "type": "read",
                "description": "Return SAR coverage records for one AOI or all AOIs.",
                "parameters": {
                    "aoi_id": {"type": "string", "required": False, "description": "AOI id to filter coverage"},
                },
            },
            {
                "name": "sar_aoi_list",
                "type": "read",
                "description": "List configured SAR areas of interest.",
                "parameters": {},
            },
            {
                "name": "sar_pin_click",
                "type": "read",
                "description": "Return full detail for a SAR anomaly pin without screen scraping the UI popup.",
                "parameters": {
                    "anomaly_id": {"type": "string", "required": True, "description": "SAR anomaly id"},
                },
            },
            {
                "name": "list_analysis_zones",
                "type": "read",
                "description": "List OpenClaw analysis zones currently shown on the map.",
                "parameters": {},
                "returns": "{zones: [...]}",
            },
            {
                "name": "timemachine_list",
                "type": "read",
                "description": "List recent Time Machine snapshots available for playback.",
                "parameters": {},
                "returns": "{enabled: bool, count: int, snapshots: [{id, timestamp, format, layers, layer_counts}]}",
            },
            {
                "name": "timemachine_config",
                "type": "read",
                "description": "Get Time Machine settings, enabled state, cadence, and storage notice.",
                "parameters": {},
                "returns": "{enabled: bool, interval_minutes: int, storage_notice: str, ...}",
            },
            {
                "name": "channel_status",
                "type": "read",
                "description": "Get command channel health: queue sizes, access tier, uptime stats.",
                "parameters": {},
                "returns": "Object with channel health metrics",
            },
            # ── Write Tools ───────────────────────────────────
            {
                "name": "place_pin",
                "type": "write",
                "description": "Place an intel pin on the map. The pin is visible to the operator in the UI immediately.",
                "parameters": {
                    "lat": {"type": "float", "required": True, "description": "Latitude"},
                    "lng": {"type": "float", "required": True, "description": "Longitude"},
                    "label": {"type": "string", "required": True, "description": "Pin label (short title)"},
                    "category": {"type": "string", "required": True, "description": "Pin category",
                                 "enum": ["threat", "news", "geolocation", "custom", "anomaly", "military",
                                          "maritime", "flight", "infrastructure", "weather", "sigint",
                                          "prediction", "research"]},
                    "description": {"type": "string", "required": False, "description": "Detailed description"},
                    "source": {"type": "string", "required": False, "description": "Attribution (default: 'openclaw')"},
                    "layer_id": {"type": "string", "required": False, "description": "Assign to a specific layer"},
                    "color": {"type": "string", "required": False, "description": "Hex color override"},
                },
                "example": {"cmd": "place_pin", "args": {"lat": 35.6892, "lng": 51.389, "label": "Tehran Activity", "category": "research", "description": "Unusual satellite passes detected"}},
            },
            {
                "name": "delete_pin",
                "type": "write",
                "description": "Remove a pin from the map by its ID.",
                "parameters": {
                    "id": {"type": "string", "required": True, "description": "Pin ID to delete"},
                },
            },
            {
                "name": "create_layer",
                "type": "write",
                "description": "Create a new pin layer (group of pins with shared color/category).",
                "parameters": {
                    "name": {"type": "string", "required": True, "description": "Layer name"},
                    "color": {"type": "string", "required": False, "description": "Layer color (hex)"},
                    "feed_url": {"type": "string", "required": False, "description": "RSS/Atom feed URL to auto-ingest pins from"},
                },
            },
            {
                "name": "delete_layer",
                "type": "write",
                "description": "Delete a layer and all its pins.",
                "parameters": {
                    "id": {"type": "string", "required": True, "description": "Layer ID to delete"},
                },
            },
            {
                "name": "inject_data",
                "type": "write",
                "description": "Push custom data items into a layer. Items appear as pins on the map.",
                "parameters": {
                    "layer": {"type": "string", "required": True, "description": "Layer ID to inject into"},
                    "items": {"type": "array", "required": True, "description": "Array of {lat, lng, label, description} objects"},
                },
            },
            {
                "name": "show_satellite",
                "type": "write",
                "description": "Display satellite imagery of a location fullscreen on the operator's map. Uses free Sentinel-2 data from Microsoft Planetary Computer. The image pops up centered on screen — same viewer as right-clicking the map.",
                "parameters": {
                    "lat": {"type": "float", "required": True, "description": "Latitude of target location"},
                    "lng": {"type": "float", "required": True, "description": "Longitude of target location"},
                    "caption": {"type": "string", "required": False, "description": "Caption to display with the image"},
                },
                "example": {"cmd": "show_satellite", "args": {"lat": 35.6892, "lng": 51.389, "caption": "Tehran — latest Sentinel-2 pass"}},
            },
            {
                "name": "show_sentinel",
                "type": "write",
                "description": "Display Sentinel Hub imagery with a specific analysis preset. Requires Copernicus CDSE credentials configured on the server. Falls back to free Sentinel-2 if not available.",
                "parameters": {
                    "lat": {"type": "float", "required": True, "description": "Latitude of target location"},
                    "lng": {"type": "float", "required": True, "description": "Longitude of target location"},
                    "preset": {"type": "string", "required": False, "description": "Imagery preset (default: TRUE-COLOR)",
                               "enum": ["TRUE-COLOR", "FALSE-COLOR", "NDVI", "MOISTURE-INDEX"]},
                    "caption": {"type": "string", "required": False, "description": "Caption to display with the image"},
                },
                "example": {"cmd": "show_sentinel", "args": {"lat": 35.6892, "lng": 51.389, "preset": "NDVI", "caption": "Tehran vegetation index"}},
            },
            {
                "name": "add_watch",
                "type": "write",
                "description": "Set up a watchdog alert. When triggered, alerts push instantly via SSE stream. Debounced: same watch won't re-fire within 60 seconds.",
                "parameters": {
                    "type": {"type": "string", "required": True, "description": "Watch type",
                             "enum": ["track_aircraft", "track_callsign", "track_registration", "track_ship", "track_entity", "geofence", "keyword", "prediction_market"]},
                    "params": {"type": "object", "required": True, "description": "Type-specific parameters (see subtypes)"},
                },
                "subtypes": {
                    "track_aircraft": {"params": {"callsign": "string (optional)", "registration": "string (optional)", "icao24": "string (optional)", "owner": "string (optional)", "query": "string (optional)"}, "description": "Alert when a matching aircraft appears across split flight layers"},
                    "track_callsign": {"params": {"callsign": "string"}, "description": "Alert when aircraft with this callsign appears"},
                    "track_registration": {"params": {"registration": "string"}, "description": "Alert when aircraft with this tail number appears"},
                    "track_ship": {"params": {"mmsi": "string (optional)", "imo": "string (optional)", "name": "string (optional)", "owner": "string (optional)", "callsign": "string (optional)"}, "description": "Alert when ship appears by MMSI, IMO, name, owner, or callsign"},
                    "track_entity": {"params": {"query": "string", "entity_type": "string (optional)", "layers": "list (optional)"}, "description": "Generic exact-first entity tracker when aircraft/ship fields are not known yet"},
                    "geofence": {"params": {"lat": "float", "lng": "float", "radius_km": "float (default 50)", "entity_types": "list (default ['flights','ships'])"}, "description": "Alert when any entity enters a geographic zone"},
                    "keyword": {"params": {"keyword": "string"}, "description": "Alert when keyword appears in news/GDELT headlines"},
                    "prediction_market": {"params": {"query": "string", "threshold": "float 0-1 (optional)"}, "description": "Alert on prediction market movements matching query"},
                },
                "example": {"cmd": "add_watch", "args": {"type": "track_registration", "params": {"registration": "N3880"}}},
            },
            {
                "name": "track_entity",
                "type": "write",
                "description": "Create the most precise non-hostile tracking watch for an entity. It resolves identifiers first, then installs track_aircraft, track_ship, or generic track_entity. If the entity is not visible now, it still creates a pending generic watch from the query.",
                "parameters": {
                    "query": {"type": "string", "required": False, "description": "Name, owner, operator, callsign, vessel name, or entity label"},
                    "entity_type": {"type": "string", "required": False, "description": "Optional type hint: aircraft, ship, person, event, infrastructure"},
                    "callsign": {"type": "string", "required": False, "description": "Aircraft or vessel callsign"},
                    "registration": {"type": "string", "required": False, "description": "Aircraft registration / tail number"},
                    "icao24": {"type": "string", "required": False, "description": "Aircraft ICAO24 hex identifier"},
                    "mmsi": {"type": "string", "required": False, "description": "Ship MMSI"},
                    "imo": {"type": "string", "required": False, "description": "Ship IMO number"},
                    "name": {"type": "string", "required": False, "description": "Known vessel/entity name"},
                    "owner": {"type": "string", "required": False, "description": "Owner/operator/person"},
                    "layers": {"type": "array", "required": False, "description": "Optional fallback layers for generic tracking"},
                },
                "returns": "{watch, watch_type, initial_lookup}",
                "example": {"cmd": "track_entity", "args": {"entity_type": "ship", "name": "BRAVO EUGENIA", "owner": "Jerry Jones"}},
            },
            {
                "name": "watch_area",
                "type": "write",
                "description": "Create a geofence watch around a coordinate using sensible defaults for moving entities. Alerts arrive over SSE and poll fallback.",
                "parameters": {
                    "lat": {"type": "float", "required": True, "description": "Center latitude"},
                    "lng": {"type": "float", "required": True, "description": "Center longitude"},
                    "radius_km": {"type": "float", "required": False, "description": "Geofence radius in km (default 50)"},
                    "entity_types": {"type": "array", "required": False, "description": "Entity types to watch, default ['aircraft', 'ships']"},
                },
                "returns": "Watch object",
            },
            {
                "name": "remove_watch",
                "type": "write",
                "description": "Remove a watchdog watch by ID.",
                "parameters": {
                    "id": {"type": "string", "required": True, "description": "Watch ID to remove"},
                },
            },
            {
                "name": "clear_watches",
                "type": "write",
                "description": "Remove all active watches.",
                "parameters": {},
            },
            {
                "name": "take_snapshot",
                "type": "write",
                "description": "Take a time-machine snapshot of current data state for later playback.",
                "parameters": {
                    "layers": {"type": "array", "required": False, "description": "Specific layers to snapshot (default: all)"},
                    "compress": {"type": "boolean", "required": False, "description": "Compress snapshot (default: true)"},
                },
            },
            {
                "name": "timemachine_playback",
                "type": "write",
                "description": "Load a saved Time Machine snapshot for playback or offline analysis.",
                "parameters": {
                    "snapshot_id": {"type": "string", "required": True, "description": "Snapshot ID to load"},
                },
            },
            {
                "name": "update_layer",
                "type": "write",
                "description": "Update an existing pin layer's metadata or visibility.",
                "parameters": {
                    "layer_id": {"type": "string", "required": True, "description": "Layer ID to update"},
                    "name": {"type": "string", "required": False, "description": "New layer name"},
                    "description": {"type": "string", "required": False, "description": "Updated description"},
                    "visible": {"type": "boolean", "required": False, "description": "Set layer visibility"},
                    "color": {"type": "string", "required": False, "description": "Hex color"},
                    "feed_url": {"type": "string", "required": False, "description": "RSS/Atom feed URL"},
                    "feed_interval": {"type": "integer", "required": False, "description": "Feed poll interval in seconds"},
                },
            },
            {
                "name": "refresh_feed",
                "type": "write",
                "description": "Re-fetch a layer's RSS/Atom feed and update its pins.",
                "parameters": {
                    "id": {"type": "string", "required": True, "description": "Layer ID with a feed_url configured"},
                },
            },
            {
                "name": "sar_aoi_add",
                "type": "write",
                "description": "Add a SAR area of interest for catalog/coverage/anomaly workflows.",
                "parameters": {
                    "id": {"type": "string", "required": True, "description": "Stable AOI id"},
                    "name": {"type": "string", "required": False, "description": "Human-readable AOI name"},
                    "center_lat": {"type": "float", "required": True, "description": "AOI center latitude"},
                    "center_lon": {"type": "float", "required": True, "description": "AOI center longitude"},
                    "radius_km": {"type": "float", "required": False, "description": "AOI radius in km"},
                    "priority": {"type": "integer", "required": False, "description": "AOI priority"},
                },
            },
            {
                "name": "sar_aoi_remove",
                "type": "write",
                "description": "Remove a SAR area of interest.",
                "parameters": {
                    "aoi_id": {"type": "string", "required": True, "description": "AOI id to remove"},
                },
            },
            {
                "name": "sar_pin_from_anomaly",
                "type": "write",
                "description": "Create an intel pin from a SAR anomaly id.",
                "parameters": {
                    "anomaly_id": {"type": "string", "required": True, "description": "SAR anomaly id"},
                },
            },
            {
                "name": "sar_watch_anomaly",
                "type": "write",
                "description": "Create a watchdog alert for SAR anomalies, optionally scoped by AOI/kind/magnitude.",
                "parameters": {
                    "aoi_id": {"type": "string", "required": False, "description": "AOI id to watch"},
                    "kind": {"type": "string", "required": False, "description": "Anomaly kind"},
                    "min_magnitude": {"type": "float", "required": False, "description": "Minimum anomaly magnitude"},
                },
            },
            {
                "name": "sar_focus_aoi",
                "type": "write",
                "description": "Move the operator map to a SAR AOI center and optionally open its details.",
                "parameters": {
                    "aoi_id": {"type": "string", "required": True, "description": "AOI id"},
                    "zoom": {"type": "float", "required": False, "description": "Map zoom level"},
                },
            },
            {
                "name": "place_analysis_zone",
                "type": "write",
                "description": "Place an OpenClaw analysis zone overlay on the map.",
                "parameters": {
                    "lat": {"type": "float", "required": True, "description": "Zone center latitude"},
                    "lng": {"type": "float", "required": True, "description": "Zone center longitude"},
                    "radius_km": {"type": "float", "required": False, "description": "Zone radius in km"},
                    "label": {"type": "string", "required": False, "description": "Zone label"},
                    "description": {"type": "string", "required": False, "description": "Zone notes"},
                    "color": {"type": "string", "required": False, "description": "Zone color"},
                },
            },
            {
                "name": "delete_analysis_zone",
                "type": "write",
                "description": "Delete an OpenClaw analysis zone.",
                "parameters": {
                    "zone_id": {"type": "string", "required": True, "description": "Zone id"},
                },
            },
            {
                "name": "clear_analysis_zones",
                "type": "write",
                "description": "Clear OpenClaw-created analysis zones from the map.",
                "parameters": {},
            },
        ],
        "sse_events": {
            "description": "Events pushed via GET /api/ai/channel/sse — keep connection open to receive these in real-time.",
            "events": {
                "connected": "Sent on connect. Contains access_tier.",
                "task": "Operator-pushed tasks (instructions, sync requests).",
                "alert": "Watchdog alert fired (aircraft spotted, geofence breach, keyword hit, market move).",
                "heartbeat": "Every 15s — keeps Tor circuit alive. Contains timestamp.",
            },
        },
        "tips": [
            "COMPACT MODE: Pass compact=true on ANY read command to get compressed_v1 responses — ~60-90% smaller payloads, faster parse, fewer tokens. Short keys (cs/ic/hdg/t), 3-decimal lat/lng, null-stripped. Use this by default unless you need verbose field names.",
            "BATCH for speed: POST /api/ai/channel/batch with {\"commands\": [{cmd, args}, ...]} runs up to 20 commands concurrently in ONE HTTP round-trip. Use this whenever you need 2+ lookups — it eliminates round-trip latency.",
            "BATCH + COMPACT: Combine both — {\"commands\": [{\"cmd\": \"find_flights\", \"args\": {\"query\": \"N189AM\", \"compact\": true}}, ...]} — for maximum speed.",
            "INCREMENTAL polling: get_layer_slice accepts since_layer_versions (preferred) or since_version. Pass {layer: version} from the previous response's layer_versions field — only layers that actually changed are serialized. Combined with SSE layer_changed events, the agent knows exactly which layers to fetch.",
            "Start with get_summary to understand data volume before pulling full datasets.",
            "Prefer compact lookups first: search_telemetry, find_flights, find_ships, search_news, entities_near, get_layer_slice. Use get_telemetry/get_slow_telemetry/get_report only when focused commands are insufficient.",
            "ShadowBroker does expose UAP sightings, wastewater, and tracked_flights/VIP aircraft when those layers are populated. Verify with get_summary or get_layer_slice before claiming a layer is absent.",
            "ShadowBroker also exposes fishing_activity, which is the fishing-vessel activity layer backed by Global Fishing Watch data when GFW_API_TOKEN is configured. Do not confuse it with the AIS ships layer.",
            "Use search_telemetry as the Google-style entry point whenever the user gives you a person, place, company, topic, owner, nickname, or natural-language phrase and you do not already know the source layer.",
            "Example: for 'Where is Jerry Jones yacht?' search 'Jerry Jones' across all telemetry first, identify the ship match, then refine with find_ships or raw layer context only if needed.",
            "For fuzzy natural-language lookups like 'Patriots jet' or 'Jerry Jones yacht', use search_telemetry first and inspect the ranked candidate list before making a hard claim.",
            "search_telemetry returns ranked candidates grouped by entity type, so use the group list to narrow aircraft vs ships vs events before answering.",
            "Example: for protests, facilities, or incident topics, search the phrase across telemetry first instead of guessing one layer and returning null.",
            "For AF1/AF2 and other VIP aircraft, use find_flights first when the domain is obvious, then inspect tracked_flights via get_layer_slice if you need raw layer context.",
            "If one domain-specific command returns no match, do not conclude the entity is absent. Fall back to search_telemetry before any broad layer pull.",
            "If search_telemetry returns multiple plausible candidates, summarize the top matches instead of pretending one uncertain match is definitive.",
            "tracked_flights contains VIP aircraft with person names, social links, and categories — this is the 'People' layer.",
            "Use show_satellite to display imagery to the operator — it pops up fullscreen, no need for them to search manually.",
            "Set up watches for persistent monitoring — alerts push instantly via SSE, no polling needed.",
            "Single commands: POST /api/ai/channel/command with body {\"cmd\": \"name\", \"args\": {}}.",
            "Multi-command: POST /api/ai/channel/batch with body {\"commands\": [...]} — faster than sequential single calls.",
            "Open GET /api/ai/channel/sse once and keep it open — all alerts/tasks stream to you in real-time.",
        ],
    }


# ---------------------------------------------------------------------------
# API Discovery — lets the agent learn all available endpoints on first connect
# ---------------------------------------------------------------------------

@router.get("/api/ai/capabilities", dependencies=[Depends(require_openclaw_or_local)])
@limiter.limit("30/minute")
async def api_capabilities(request: Request):
    """Return full API manifest so the agent knows every available endpoint."""
    from services.openclaw_channel import READ_COMMANDS, WRITE_COMMANDS, detect_tier
    from services.config import get_settings
    tier = detect_tier()
    access_tier = str(get_settings().OPENCLAW_ACCESS_TIER or "restricted").strip().lower()
    return {
        "ok": True,
        "version": "0.9.7",
        "auth": {
            "method": "HMAC-SHA256",
            "headers": ["X-SB-Timestamp", "X-SB-Nonce", "X-SB-Signature"],
            "signature_format": "HMAC-SHA256(secret, METHOD|path|timestamp|nonce|sha256(body))",
            "remote_agent_http_auth_identity": "shared_hmac_secret",
            "agent_ed25519_identity_used_for_http_auth": False,
            "agent_ed25519_identity_used_for_mesh_signing": True,
            "notes": [
                "The live OpenClaw HTTP channel authenticates possession of the shared HMAC secret, not a specific Ed25519 agent keypair.",
                "If multiple callers know the HMAC secret, the backend treats them as the same remote OpenClaw trust principal.",
                "The OpenClaw Ed25519/X25519 identity is used for mesh signing and future private-lane upgrades, not current HTTP command authentication.",
            ],
        },
        "trust_boundary": {
            "remote_api_principal": "holder_of_openclaw_hmac_secret",
            "operator_principal": "local_operator_or_admin_key_holder",
            "access_tier": access_tier,
            "transport_tier": tier,
            "remote_route_surface": {
                "auth_dependency": "require_openclaw_or_local",
                "family": "/api/ai/*",
                "notes": [
                    "Remote OpenClaw access is broader than /api/ai/channel/* and includes other AI Intel routes protected by require_openclaw_or_local.",
                    "The command allowlist still gates what the remote agent can invoke through /api/ai/channel/command and /api/ai/channel/batch.",
                ],
            },
            "durability": {
                "command_queue": "memory_only",
                "task_queue": "memory_only",
                "watch_registry": "memory_only",
                "notes": [
                    "Restarting the backend drops in-memory channel state, pending tasks, and watchdog watches.",
                    "This channel is currently a singleton process-local integration, not a multi-agent durable broker.",
                ],
            },
        },
        "sse_channel": {
            "description": "PREFERRED for Tor agents: Server-Sent Events stream. One long-lived HTTP GET "
                           "connection for real-time push. Works perfectly over Tor SOCKS5 (unlike WebSocket).",
            "stream_endpoint": "GET /api/ai/channel/sse  (long-lived, returns text/event-stream)",
            "command_endpoint": "POST /api/ai/channel/command  (send commands, same as HTTP channel)",
            "auth": "Same HMAC auth as all other endpoints (X-SB-Timestamp, X-SB-Nonce, X-SB-Signature)",
            "protocol": {
                "events_from_server": {
                    "connected": 'event: connected\\ndata: {"access_tier": "...", "layer_versions": {"ships": 42, ...}}',
                    "layer_changed": 'event: layer_changed\\ndata: {"layers": {"ships": {"layer": "ships", "version": 43, "count": 1287}, ...}}  (pushed on every data refresh — agent fetches only changed layers)',
                    "task": 'event: task\\ndata: {"task_type": "...", "payload": {...}}',
                    "alert": 'event: alert\\ndata: {"alert_type": "...", ...}',
                    "heartbeat": 'event: heartbeat\\ndata: {"ts": 1234567890, "layer_versions": {...}}  (every 15s, full version snapshot)',
                },
                "commands_from_agent": "POST /api/ai/channel/command with {\"cmd\": \"get_summary\", \"args\": {}}",
            },
            "usage": [
                "1. Open GET /api/ai/channel/sse FIRST — keep connection open for the session",
                "2. On 'connected' event: receive full layer_versions snapshot (current state)",
                "3. On 'layer_changed' event: know exactly which layers updated — fetch only those via get_layer_slice with since_layer_versions",
                "4. On 'alert' event: receive watchdog hits instantly (geofence, callsign, keyword)",
                "5. On 'task' event: receive operator-pushed tasks instantly",
                "6. Send commands via POST /api/ai/channel/command as needed",
                "7. Heartbeats every 15s include full layer_versions for drift recovery",
            ],
            "benefits": [
                "Works over Tor SOCKS5 — plain HTTP, no WebSocket upgrade needed",
                "Single connection — Tor circuit stays warm, no 10-20s reconnect",
                "Layer changes pushed instantly — fetch only what changed, not everything",
                "Tasks and alerts pushed instantly — no polling delay",
                "HMAC authenticated once at connect — no per-event signing overhead",
                "Heartbeat keeps connection alive through proxies and Tor",
            ],
            "python_example": (
                "from sb_query import ShadowBrokerClient\n"
                "sb = ShadowBrokerClient()\n"
                "async for event in sb.stream_updates():\n"
                "    if event['event'] == 'layer_changed':\n"
                "        changed = list(event['data']['layers'].keys())\n"
                "        data = await sb.get_layer_slice(changed)  # only changed layers"
            ),
        },
        "websocket_channel": {
            "description": "Alternative for LOCAL agents only. WebSocket does NOT work over Tor SOCKS5. "
                           "Use SSE channel instead for remote/Tor connections.",
            "endpoint": "ws://{host}/api/ai/channel/ws?ts={timestamp}&nonce={nonce}&sig={hmac_signature}",
            "auth": "HMAC signature in query params. Sign: GET|/api/ai/channel/ws|ts|nonce|sha256('')",
            "note": "WebSocket upgrade hangs over Tor SOCKS5. Use GET /api/ai/channel/sse instead.",
        },
        "command_channel_http": {
            "description": "HTTP commands — use with SSE stream for real-time, or standalone for simple requests.",
            "send": "POST /api/ai/channel/command  body: {cmd, args}",
            "batch": "POST /api/ai/channel/batch  body: {commands: [{cmd, args}, ...]}  (max 20, concurrent execution, one round-trip)",
            "poll": "POST /api/ai/channel/poll  body: {}  (returns completed results + pending tasks)",
            "authorization_model": "coarse_access_tier",
            "authorization_notes": [
                "restricted = read commands only",
                "full = read + write commands",
                "This is a coarse operator-selected policy, not a per-command scoped capability token model.",
            ],
            "read_commands": sorted(READ_COMMANDS),
            "write_commands": sorted(WRITE_COMMANDS),
            "command_reference": {
                "get_telemetry": {"args": {}, "description": "All live fast-refresh data (flights, ships, sigint, earthquakes, weather, CCTV, etc)"},
                "get_slow_telemetry": {"args": {}, "description": "Slow-refresh data (prediction markets, news, military bases, power plants, volcanoes, etc)"},
                "get_summary": {"args": {}, "description": "Counts and discovery metadata for all live telemetry layers, including available layer names and common aliases."},
                "get_layer_slice": {
                    "args": {"layers": "list[str]", "limit_per_layer": "int (optional, omit or <=0 for full layer)", "since_version": "int (optional)"},
                    "description": "Fetch only selected top-level layers. Accepts aliases such as gfw/global_fishing_watch → fishing_activity. If since_version matches current version, returns changed=false and no layer payload.",
                },
                "find_flights": {
                    "args": {"query": "str (optional)", "callsign": "str (optional)", "registration": "str (optional)", "icao24": "str (optional)", "owner": "str (optional)", "categories": "list[str] (optional)", "limit": "int (default 25)"},
                    "description": "Compact server-side flight search across tracked/military/private/commercial layers.",
                },
                "find_ships": {
                    "args": {"query": "str (optional)", "mmsi": "str (optional)", "imo": "str (optional)", "name": "str (optional)", "limit": "int (default 25)"},
                    "description": "Compact server-side ship search by MMSI/IMO/name/query, including yacht-owner enrichment.",
                },
                "find_entity": {
                    "args": {"query": "str (optional)", "entity_type": "aircraft|ship|person|event|infrastructure (optional)", "callsign": "str (optional)", "registration": "str (optional)", "icao24": "str (optional)", "mmsi": "str (optional)", "imo": "str (optional)", "name": "str (optional)", "owner": "str (optional)", "layers": "list[str] (optional)", "limit": "int (default 10)"},
                    "description": "Exact-first resolver for planes, ships, operators, callsigns, registrations, MMSI/IMO, and named entities. Use before tracking to avoid fuzzy prompt matching.",
                },
                "correlate_entity": {
                    "args": {"query": "str (optional)", "entity_type": "str (optional)", "callsign": "str (optional)", "registration": "str (optional)", "icao24": "str (optional)", "mmsi": "str (optional)", "imo": "str (optional)", "name": "str (optional)", "owner": "str (optional)", "radius_km": "float (default 100)", "limit": "int (default 10)"},
                    "description": "Resolve an entity and return nearby context/correlation evidence. Co-location is reported as a lead, not proof.",
                },
                "search_telemetry": {
                    "args": {"query": "str", "layers": "list[str] (optional)", "limit": "int (default 25)"},
                    "description": "Universal compact search across telemetry when the entity type or source layer is not obvious.",
                },
                "search_news": {
                    "args": {"query": "str", "limit": "int (default 10)", "include_gdelt": "bool (default true)"},
                    "description": "Search news and event layers by keyword without pulling the whole slow feed.",
                },
                "entities_near": {
                    "args": {"lat": "float", "lng": "float", "radius_km": "float (default 50)", "entity_types": "list[str] (optional)", "limit": "int (default 25)"},
                    "description": "Compact proximity search around a point across selected layers.",
                },
                "brief_area": {
                    "args": {"lat": "float", "lng": "float", "radius_km": "float (default 50)", "entity_types": "list[str] (optional)", "query": "str (optional)", "limit": "int (default 25)", "context_limit": "int (default 10)"},
                    "description": "One compact area brief: nearby aircraft/ships/entities, optional topic news, and selected context layers.",
                },
                "what_changed": {
                    "args": {"layers": "list[str] (optional)", "since_version": "int (optional)", "since_layer_versions": "dict[str,int] (optional)", "limit_per_layer": "int (optional)", "compact": "bool (optional)"},
                    "description": "Incremental polling helper. Use with SSE layer_versions to fetch only changed layer slices.",
                },
                "get_report": {"args": {}, "description": "Combined fast + slow telemetry"},
                "get_sigint_totals": {"args": {}, "description": "Meshtastic/APRS/JS8Call signal counts"},
                "get_prediction_markets": {"args": {}, "description": "Polymarket + Kalshi prediction markets"},
                "get_ai_pins": {"args": {}, "description": "All intel pins placed on the map"},
                "get_layers": {"args": {}, "description": "All pin layers"},
                "get_correlations": {"args": {}, "description": "Cross-domain correlation alerts"},
                "channel_status": {"args": {}, "description": "Command channel health + stats"},
                "sar_status": {"args": {}, "description": "SAR/OpenClaw catalog readiness and product fetch status"},
                "sar_anomalies_recent": {"args": {"kind": "str (optional)", "limit": "int (default 25)"}, "description": "Recent SAR anomaly list"},
                "sar_anomalies_near": {"args": {"lat": "float", "lng": "float", "radius_km": "float (default 50)", "limit": "int (default 25)"}, "description": "SAR anomalies near a coordinate"},
                "sar_scene_search": {"args": {"aoi_id": "str (optional)", "limit": "int (default 25)"}, "description": "Search cached SAR scenes"},
                "sar_coverage_for_aoi": {"args": {"aoi_id": "str (optional)"}, "description": "SAR coverage records by AOI"},
                "sar_aoi_list": {"args": {}, "description": "List SAR areas of interest"},
                "sar_pin_click": {"args": {"anomaly_id": "str"}, "description": "Inspect SAR anomaly pin details"},
                "list_analysis_zones": {"args": {}, "description": "List OpenClaw analysis zones on the map"},
                "place_pin": {
                    "args": {"lat": "float", "lng": "float", "label": "str",
                             "category": "threat|news|geolocation|custom|anomaly|military|maritime|flight|infrastructure|weather|sigint|prediction|research",
                             "description": "str (optional)", "source": "str (default: openclaw)",
                             "layer_id": "str (optional)", "color": "str (optional)",
                             "confidence": "float 0-1 (default: 1.0)",
                             "entity_attachment": {"entity_type": "str", "entity_id": "str", "entity_label": "str"}},
                    "description": "Place an intel pin on the map (full access only)",
                },
                "delete_pin": {"args": {"id": "str"}, "description": "Remove a pin (full access only)"},
                "create_layer": {"args": {"name": "str", "description": "str (optional)", "color": "str (optional)"}, "description": "Create a pin layer"},
                "update_layer": {"args": {"layer_id": "str", "name": "str (optional)", "visible": "bool (optional)"}, "description": "Update layer properties"},
                "delete_layer": {"args": {"layer_id": "str"}, "description": "Delete layer and all its pins"},
                "inject_data": {"args": {"layer": "str", "items": "list"}, "description": "Inject data into a layer"},
                "refresh_feed": {"args": {"layer_id": "str"}, "description": "Refresh a layer's RSS/feed source"},
                "take_snapshot": {"args": {"layers": "list (optional)", "compress": "bool (default: true)"}, "description": "Take a Time Machine snapshot"},
                "timemachine_list": {"args": {}, "description": "List recent Time Machine snapshots"},
                "timemachine_playback": {"args": {"snapshot_id": "str"}, "description": "Load a snapshot for playback"},
                "timemachine_config": {"args": {}, "description": "Get Time Machine config (enabled, interval)"},
                "track_entity": {
                    "args": {"query": "str (optional)", "entity_type": "str (optional)", "callsign": "str (optional)", "registration": "str (optional)", "icao24": "str (optional)", "mmsi": "str (optional)", "imo": "str (optional)", "name": "str (optional)", "owner": "str (optional)", "layers": "list[str] (optional)"},
                    "description": "Resolve then install the most precise aircraft/ship/generic watch. If unresolved now, keeps a generic watch instead of failing the user flow.",
                },
                "watch_area": {"args": {"lat": "float", "lng": "float", "radius_km": "float (default 50)", "entity_types": "list[str] (default aircraft+ships)"}, "description": "Create a geofence watch around a coordinate"},
                "sar_aoi_add": {"args": {"id": "str", "name": "str (optional)", "center_lat": "float", "center_lon": "float", "radius_km": "float (optional)", "priority": "int (optional)"}, "description": "Add a SAR area of interest"},
                "sar_aoi_remove": {"args": {"aoi_id": "str"}, "description": "Remove a SAR area of interest"},
                "sar_pin_from_anomaly": {"args": {"anomaly_id": "str"}, "description": "Create an intel pin from a SAR anomaly"},
                "sar_watch_anomaly": {"args": {"aoi_id": "str (optional)", "kind": "str (optional)", "min_magnitude": "float (optional)"}, "description": "Create SAR anomaly watch"},
                "sar_focus_aoi": {"args": {"aoi_id": "str", "zoom": "float (optional)"}, "description": "Move the operator map to a SAR AOI"},
                "place_analysis_zone": {"args": {"lat": "float", "lng": "float", "radius_km": "float (optional)", "label": "str (optional)", "description": "str (optional)", "color": "str (optional)"}, "description": "Place an OpenClaw analysis zone"},
                "delete_analysis_zone": {"args": {"zone_id": "str"}, "description": "Delete an analysis zone"},
                "clear_analysis_zones": {"args": {}, "description": "Clear OpenClaw-created analysis zones"},
                "show_satellite": {
                    "args": {"lat": "float", "lng": "float", "caption": "str (optional)"},
                    "description": "Show Sentinel-2 satellite imagery to user in full-screen viewer. "
                                   "Same display as right-click on the map. Image appears centered on screen.",
                },
                "show_sentinel": {
                    "args": {"lat": "float", "lng": "float",
                             "preset": "TRUE-COLOR|FALSE-COLOR|NDVI|MOISTURE-INDEX (default: TRUE-COLOR)",
                             "caption": "str (optional)"},
                    "description": "Show Copernicus Sentinel Hub imagery (requires user's CDSE credentials). "
                                   "Falls back to free Sentinel-2 STAC. Presets: TRUE-COLOR (visible), "
                                   "FALSE-COLOR (vegetation), NDVI (plant health), MOISTURE-INDEX (water stress).",
                },
            },
        },
        "rest_endpoints": {
            "pins": {
                "POST /api/ai/pins": "Create a pin (body: {lat, lng, label, category, ...})",
                "GET /api/ai/pins": "List pins (?limit=500&category=threat&layer_id=...)",
                "GET /api/ai/pins/{id}": "Get single pin",
                "PATCH /api/ai/pins/{id}": "Update pin (body: {label, description, category, color})",
                "DELETE /api/ai/pins/{id}": "Delete pin",
                "POST /api/ai/pins/batch": "Create up to 200 pins at once (body: {pins: [...]})",
                "GET /api/ai/pins/geojson": "Pins as GeoJSON FeatureCollection",
            },
            "layers": {
                "POST /api/ai/layers": "Create layer (body: {name, description, color, feed_url, feed_interval})",
                "GET /api/ai/layers": "List all layers",
                "PATCH /api/ai/layers/{id}": "Update layer",
                "DELETE /api/ai/layers/{id}": "Delete layer + all pins",
                "POST /api/ai/layers/{id}/refresh": "Refresh layer feed",
            },
            "telemetry": {
                "GET /api/live-data/fast": "Fast-refresh data (flights, ships, sigint, earthquakes ~10s)",
                "GET /api/live-data/slow": "Slow-refresh data (markets, news, bases ~60s)",
                "GET /api/ai/summary": "Lightweight summary with counts",
                "GET /api/ai/report": "Full combined report",
            },
            "intelligence": {
                "GET /api/ai/news-near": "News near coordinates (?lat=&lng=&radius_km=100)",
                "GET /api/ai/satellite-images": "Satellite imagery (?lat=&lng=&days=7)",
                "GET /api/region-dossier": "Region dossier (?lat=&lng=)",
                "GET /api/ai/status": "AI Intel system status",
            },
            "timemachine": {
                "POST /api/ai/timemachine/snapshot": "Take snapshot",
                "GET /api/ai/timemachine/snapshots": "List snapshots",
                "GET /api/ai/timemachine/snapshot/{id}": "Get snapshot data",
                "GET /api/ai/timemachine/playback/{id}": "Playback snapshot",
                "GET /api/ai/timemachine/diff": "Diff two snapshots (?from=&to=)",
                "GET /api/ai/timemachine/config": "Get TM config",
                "PUT /api/ai/timemachine/config": "Update TM config",
            },
        },
        "watchdog": {
            "description": "Set up alert triggers so you get pushed notifications instead of polling. "
                           "Alerts are delivered as tasks via the poll endpoint.",
            "commands": {
                "add_watch": {
                    "description": "Register an alert trigger. Alerts push to you via channel poll.",
                    "types": {
                        "track_aircraft": {"params": {"callsign": "str (optional)", "registration": "str (optional)", "icao24": "str (optional)", "owner": "str (optional)", "query": "str (optional)"}, "description": "Alert when a matching aircraft appears across flight layers"},
                        "track_callsign": {"params": {"callsign": "str (e.g. 'KAL076')"}, "description": "Alert when aircraft with this callsign appears"},
                        "track_registration": {"params": {"registration": "str (e.g. 'N189AM')"}, "description": "Alert when aircraft with this tail number appears"},
                        "track_ship": {"params": {"mmsi": "str (optional)", "imo": "str (optional)", "name": "str (optional)", "owner": "str (optional)", "callsign": "str (optional)"}, "description": "Alert when ship appears by MMSI, IMO, name, owner, or callsign"},
                        "track_entity": {"params": {"query": "str", "entity_type": "str (optional)", "layers": "list[str] (optional)"}, "description": "Generic exact-first entity watch"},
                        "geofence": {"params": {"lat": "float", "lng": "float", "radius_km": "float (default 50)", "entity_types": "list (default ['flights','ships'])"}, "description": "Alert when any entity enters a geographic zone"},
                        "keyword": {"params": {"keyword": "str"}, "description": "Alert when keyword appears in news/GDELT"},
                        "prediction_market": {"params": {"query": "str", "threshold": "float 0-1 (optional)"}, "description": "Alert on prediction market movements"},
                    },
                },
                "remove_watch": {"args": {"id": "str"}, "description": "Remove a watch by ID"},
                "list_watches": {"args": {}, "description": "List all active watches (read command)"},
                "clear_watches": {"args": {}, "description": "Remove all watches"},
            },
            "how_it_works": "Watchdog checks telemetry every 15s. When a watch matches, an alert is pushed "
                            "instantly over SSE stream (event: alert) AND queued as a task for HTTP poll fallback. "
                            "Same watch won't re-fire within 60s (debounce).",
            "example": "command: add_watch, args: {type: 'track_callsign', params: {callsign: 'N189AM'}} — "
                       "over SSE you'll get an instant alert push. Over HTTP poll, check /api/ai/channel/poll.",
        },
        "tips": {
            "connection": "PREFERRED: Open GET /api/ai/channel/sse FIRST and keep it open. The server pushes "
                          "layer_changed events whenever data refreshes — you know exactly which layers to fetch "
                          "instead of blind-polling. Also delivers watchdog alerts and operator tasks instantly. "
                          "Send commands via POST /api/ai/channel/command alongside the stream. Works over Tor.",
            "performance": "1) Open SSE stream for layer_changed push notifications. "
                          "2) Use get_layer_slice with per-layer incremental (since_layer_versions) — only changed "
                          "layers are serialized, unchanged layers transfer zero bytes. The client tracks versions "
                          "automatically from SSE events and previous responses. "
                          "3) Pass compact=true on every read command for compressed_v1 responses (~60-90% smaller). "
                          "4) Use targeted commands first (find_flights, search_telemetry, entities_near). "
                          "Reserve get_telemetry/get_slow_telemetry for rare full-context pulls.",
            "pins": "Pins are server-side, NOT localStorage. Use place_pin command or POST /api/ai/pins. The agent can place and delete pins.",
            "tracking": "To track a specific aircraft without polling: use add_watch with track_callsign or track_registration. Over SSE, you'll get instant push alerts.",
            "agency": "You can: place pins, set geofences, track entities, monitor keywords, get pushed alerts — all without user intervention. SSE stream makes all of this real-time.",
        },
        "transport": tier,
    }


# ---------------------------------------------------------------------------
# OpenClaw Connection Management (local-operator only — NOT via HMAC)
# These endpoints manage the HMAC secret itself, so they MUST require
# local operator access to prevent privilege escalation.
# ---------------------------------------------------------------------------

@router.get("/api/ai/connect-info", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def get_connect_info(request: Request, reveal: bool = False):
    """Return connection details for the OpenClaw Connect modal.

    The HMAC secret is masked by default. Pass ?reveal=true to see the full key.
    Private keys are NEVER returned.
    """
    import os
    import secrets
    from services.config import get_settings

    settings = get_settings()
    hmac_secret = str(settings.OPENCLAW_HMAC_SECRET or "").strip()
    access_tier = str(settings.OPENCLAW_ACCESS_TIER or "restricted").strip().lower()

    # Auto-generate if not set
    if not hmac_secret:
        hmac_secret = secrets.token_hex(24)  # 48 chars
        _write_env_value("OPENCLAW_HMAC_SECRET", hmac_secret)
        # Clear settings cache so next read picks up the new value
        get_settings.cache_clear()

    masked = hmac_secret[:6] + "••••••••" + hmac_secret[-4:] if len(hmac_secret) > 10 else "••••••••"

    return {
        "ok": True,
        "hmac_secret": hmac_secret if reveal else masked,
        "hmac_secret_set": bool(hmac_secret),
        "bootstrap_behavior": {
            "auto_generates_when_missing": True,
            "auto_generated_this_call": not bool(settings.OPENCLAW_HMAC_SECRET or ""),
            "notes": [
                "If no HMAC secret exists yet, this endpoint bootstraps one and persists it to .env.",
                "Regenerating the HMAC secret revokes all existing direct-mode OpenClaw callers at once.",
            ],
        },
        "access_tier": access_tier,
        "trust_model": {
            "remote_http_principal": "holder_of_openclaw_hmac_secret",
            "agent_ed25519_identity_bound_to_http_session": False,
            "agent_ed25519_identity_purpose": [
                "mesh signing",
                "future private-lane upgrade",
            ],
            "authorization_model": {
                "type": "coarse_access_tier",
                "restricted": "read commands only",
                "full": "read and write commands",
            },
            "durability": {
                "command_queue": "memory_only",
                "task_queue": "memory_only",
                "watch_registry": "memory_only",
            },
        },
        "connection_modes": {
            "direct": {
                "enabled": True,
                "description": "HMAC-signed HTTP requests for local/VPN/Tor connections",
            },
            "wormhole": {
                "enabled": False,
                "description": "Planned — E2EE via Wormhole DM (not yet implemented for this channel)",
            },
        },
        "access_tiers": {
            "restricted": {
                "description": "Read-only telemetry, pins, satellite, news queries",
                "risk": "Low — agent can observe but cannot modify data or post to mesh",
                "capabilities": [
                    "get_telemetry", "get_pins", "satellite_images",
                    "news_near", "ai_summary", "ai_report",
                    "timemachine_list", "timemachine_view",
                ],
            },
            "full": {
                "description": "Full access — read, write, inject, post, snapshot",
                "risk": "High — agent can place pins, inject data into layers, take snapshots, and interact with the mesh network on your behalf. You are responsible for its actions.",
                "capabilities": [
                    "get_telemetry", "get_pins", "create_pin", "delete_pin",
                    "satellite_images", "news_near", "data_injection",
                    "ai_summary", "ai_report", "timemachine_snapshot",
                    "timemachine_list", "timemachine_view", "timemachine_diff",
                ],
            },
        },
    }


@router.post("/api/ai/connect-info/regenerate", dependencies=[Depends(require_local_operator)])
@limiter.limit("5/minute")
async def regenerate_hmac_secret(request: Request):
    """Generate a new HMAC secret. Old secret immediately stops working."""
    import secrets
    from services.config import get_settings

    new_secret = secrets.token_hex(24)  # 48 chars
    _write_env_value("OPENCLAW_HMAC_SECRET", new_secret)
    get_settings.cache_clear()

    return {
        "ok": True,
        "hmac_secret": new_secret,
        "detail": "HMAC secret regenerated. Update your OpenClaw agent configuration.",
    }


@router.put("/api/ai/connect-info/access-tier", dependencies=[Depends(require_local_operator)])
@limiter.limit("10/minute")
async def set_access_tier(request: Request, body: dict):
    """Set the access tier for remote OpenClaw agents."""
    from services.config import get_settings

    tier = str(body.get("tier", "") or "").strip().lower()
    if tier not in ("full", "restricted"):
        raise HTTPException(400, "Invalid tier. Must be 'full' or 'restricted'.")

    _write_env_value("OPENCLAW_ACCESS_TIER", tier)
    get_settings.cache_clear()

    return {"ok": True, "access_tier": tier}


def _write_env_value(key: str, value: str) -> None:
    """Write or update a key=value pair in the .env file.

    Uses atomic write-to-temp-then-rename to prevent corruption from
    concurrent access.  Does NOT log the value to avoid leaking secrets.
    """
    import os
    import tempfile
    from pathlib import Path

    env_path = Path(__file__).resolve().parent.parent / ".env"
    lines: list[str] = []
    found = False

    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith(f"{key}=") or stripped.startswith(f"# {key}="):
                    lines.append(f"{key}={value}\n")
                    found = True
                else:
                    lines.append(line)

    if not found:
        lines.append(f"\n# -- OpenClaw Agent --\n{key}={value}\n")

    # Atomic write: write to temp file in same directory, then rename
    fd, tmp_path = tempfile.mkstemp(
        dir=str(env_path.parent), prefix=".env.tmp.", suffix=""
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.writelines(lines)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(env_path))
    except BaseException:
        # Clean up temp file on any failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    # Also set in current process env so Settings picks it up
    os.environ[key] = value


# ---------------------------------------------------------------------------
# Agent Identity Management (Ed25519 keypair — used for mesh signing;
# Wormhole DM E2EE upgrade is planned but not yet wired into this channel)
# ---------------------------------------------------------------------------

@router.get("/api/ai/agent-identity", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def get_agent_identity(request: Request):
    """Get the OpenClaw agent's public identity info.

    Returns the agent's node_id and public key — never the private key.
    """
    from services.openclaw_bridge import get_agent_public_info
    return get_agent_public_info()


@router.post("/api/ai/agent-identity/bootstrap", dependencies=[Depends(require_local_operator)])
@limiter.limit("5/minute")
async def bootstrap_agent_identity(request: Request):
    """Generate (or regenerate) the agent's Ed25519 keypair.

    Pass ?force=true to regenerate. The old identity is permanently lost.
    """
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    force = bool(body.get("force", False))
    from services.openclaw_bridge import generate_agent_keypair
    return generate_agent_keypair(force=force)


@router.delete("/api/ai/agent-identity", dependencies=[Depends(require_local_operator)])
@limiter.limit("3/minute")
async def revoke_agent_identity(request: Request):
    """Permanently revoke the agent's identity.

    The keypair is destroyed. A new one must be bootstrapped.
    """
    from services.openclaw_bridge import revoke_agent_identity
    return revoke_agent_identity()


# ---------------------------------------------------------------------------
# Command Channel — Bidirectional Agent ↔ SB communication
# ---------------------------------------------------------------------------

class ChannelCommand(BaseModel):
    cmd: str = Field(..., min_length=1, max_length=64)
    args: dict[str, Any] = Field(default_factory=dict)


class ChannelBatchRequest(BaseModel):
    """Batch of commands submitted in a single HTTP round-trip."""
    commands: list[ChannelCommand] = Field(..., min_length=1, max_length=20)


class ChannelTask(BaseModel):
    task_type: str = Field(default="custom", min_length=1, max_length=32)
    payload: dict[str, Any] = Field(default_factory=dict)


@router.post("/api/ai/channel/command", dependencies=[Depends(require_openclaw_or_local)])
@limiter.limit("60/minute")
async def channel_submit_command(request: Request, body: ChannelCommand):
    """Agent submits a command through the channel.

    The command is executed immediately and the result is returned.
    Allowed commands depend on the current access tier.
    """
    from services.config import get_settings
    from services.openclaw_channel import channel

    access_tier = str(get_settings().OPENCLAW_ACCESS_TIER or "restricted").strip().lower()
    result = channel.submit_command(body.cmd, body.args, access_tier)

    if not result.get("ok"):
        raise HTTPException(status_code=403 if "requires full" in str(result.get("detail", "")) else 400,
                            detail=result.get("detail", "command failed"))
    return result


@router.post("/api/ai/channel/batch", dependencies=[Depends(require_openclaw_or_local)])
@limiter.limit("30/minute")
async def channel_submit_batch(request: Request, body: ChannelBatchRequest):
    """Submit multiple commands in a single HTTP round-trip.

    Commands execute concurrently — independent queries (find_flights +
    search_news + entities_near) overlap instead of serialising behind
    N separate HTTP calls.  Max 20 commands per batch.

    Returns {"ok": true, "results": [...], "tier": int, "count": int}.
    """
    from services.config import get_settings
    from services.openclaw_channel import channel

    access_tier = str(get_settings().OPENCLAW_ACCESS_TIER or "restricted").strip().lower()
    batch = [{"cmd": c.cmd, "args": c.args} for c in body.commands]
    result = channel.submit_batch(batch, access_tier)

    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("detail", "batch failed"))
    return result


@router.post("/api/ai/channel/poll", dependencies=[Depends(require_openclaw_or_local)])
@limiter.limit("120/minute")
async def channel_poll(request: Request):
    """Agent polls for command results and pending tasks.

    Returns any completed command results (destructive read) plus
    any tasks pushed by the operator that haven't been picked up yet.
    """
    from services.openclaw_channel import channel

    completed = channel.get_completed_commands()
    tasks = channel.poll_tasks()
    return {
        "ok": True,
        "commands": completed,
        "tasks": tasks,
        "commands_count": len(completed),
        "tasks_count": len(tasks),
    }


@router.post("/api/ai/channel/task", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def channel_push_task(request: Request, body: ChannelTask):
    """Operator pushes a task to the agent.

    Task types: alert, request, sync, custom.
    The agent picks up tasks on its next poll.
    """
    from services.openclaw_channel import channel

    result = channel.push_task(body.task_type, body.payload)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("detail", "task push failed"))
    return result


@router.get("/api/ai/channel/status", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def channel_status(request: Request):
    """Get command channel status: tier, queue sizes, stats."""
    from services.openclaw_channel import channel
    return channel.status()


# ---------------------------------------------------------------------------
# SSE Channel — Server-Sent Events for real-time push over plain HTTP
# ---------------------------------------------------------------------------
# Works perfectly over Tor SOCKS5 (unlike WebSocket which hangs on upgrade).
# Agent keeps one long-lived GET connection open → server pushes events.
# Commands still go via POST /api/ai/channel/command (existing endpoint).
#
# Protocol:
#   event: connected      data: {"access_tier": "...", "layer_versions": {...}}
#   event: layer_changed  data: {"layers": {"ships": {"layer": "ships", "version": 42, "count": 1287}, ...}}
#   event: task           data: {"task_type": "...", "payload": {...}}
#   event: alert          data: {"alert_type": "...", ...}
#   event: heartbeat      data: {"ts": 1234567890, "layer_versions": {...}}
# ---------------------------------------------------------------------------

from starlette.responses import StreamingResponse

# Track SSE clients for broadcast (parallel to WS clients)
_sse_queues: list[asyncio.Queue] = []
_sse_queues_lock = asyncio.Lock()


async def broadcast_to_sse_clients(event_type: str, data: dict[str, Any]):
    """Push an event to all connected SSE clients."""
    async with _sse_queues_lock:
        queues = list(_sse_queues)
    for q in queues:
        try:
            q.put_nowait({"event": event_type, "data": data})
        except asyncio.QueueFull:
            pass  # Drop if client is too slow — they'll catch up


@router.get("/api/ai/channel/sse", dependencies=[Depends(require_openclaw_or_local)])
async def channel_sse(request: Request):
    """Server-Sent Events stream for real-time push to agents.

    Keeps one HTTP connection open. Tor-friendly — no WebSocket upgrade.
    Tasks, alerts, and watchdog hits are pushed instantly.
    Layer changes are pushed as they happen — agent fetches only what changed.
    Agent sends commands via POST /api/ai/channel/command.

    Events pushed:
      layer_changed  — {layers: {layer_name: {version, count}, ...}}
      task           — operator-pushed task
      alert          — watchdog alert
      heartbeat      — keep-alive with current layer versions
      connected      — initial handshake with access tier + all layer versions
    """
    from services.config import get_settings
    from services.openclaw_channel import channel
    from services.fetchers._store import (
        get_layer_versions,
        register_layer_change_callback,
        unregister_layer_change_callback,
    )

    access_tier = str(get_settings().OPENCLAW_ACCESS_TIER or "restricted").strip().lower()

    queue: asyncio.Queue = asyncio.Queue(maxsize=512)

    # Bridge thread-based layer change notifications into the async queue.
    # _mark_fresh() fires from fetcher threads; we use call_soon_threadsafe
    # to safely enqueue into the asyncio.Queue from a non-async context.
    loop = asyncio.get_event_loop()

    def _on_layer_change(layer: str, version: int, count: int):
        try:
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"event": "layer_changed", "data": {"layer": layer, "version": version, "count": count}},
            )
        except (RuntimeError, asyncio.QueueFull):
            pass  # Loop closed or queue full — drop, agent will catch up

    register_layer_change_callback(_on_layer_change)

    async with _sse_queues_lock:
        _sse_queues.append(queue)

    async def event_stream():
        try:
            # Send connected event with full layer version snapshot so the
            # agent knows the current state before any deltas arrive.
            yield _sse_format("connected", {
                "access_tier": access_tier,
                "layer_versions": get_layer_versions(),
                "message": "SSE channel active. Send commands via POST /api/ai/channel/command.",
            })

            heartbeat_interval = 15  # seconds — keeps Tor circuit alive
            last_heartbeat = time.time()

            while True:
                # Drain all pending events and deduplicate layer_changed
                # notifications (keep only latest version per layer).
                events: list[dict] = []
                try:
                    # Wait up to 1s for the first event
                    ev = await asyncio.wait_for(queue.get(), timeout=1.0)
                    events.append(ev)
                    # Drain any more that queued while we waited
                    while not queue.empty():
                        try:
                            events.append(queue.get_nowait())
                        except asyncio.QueueEmpty:
                            break
                except asyncio.TimeoutError:
                    pass

                # Separate layer_changed events (dedup) from other events
                layer_latest: dict[str, dict] = {}
                for ev in events:
                    if ev.get("event") == "layer_changed":
                        layer_latest[ev["data"]["layer"]] = ev["data"]
                    else:
                        yield _sse_format(ev["event"], ev["data"])

                # Emit one batched layer_changed event per cycle
                if layer_latest:
                    yield _sse_format("layer_changed", {"layers": layer_latest})

                # Poll channel for tasks (same as WS push loop)
                tasks = channel.poll_tasks()
                for task in tasks:
                    yield _sse_format("task", task)

                # Heartbeat to keep connection alive through Tor/proxies
                now = time.time()
                if now - last_heartbeat >= heartbeat_interval:
                    yield _sse_format("heartbeat", {
                        "ts": now,
                        "layer_versions": get_layer_versions(),
                    })
                    last_heartbeat = now

                # Check if client disconnected
                if await request.is_disconnected():
                    break

        except asyncio.CancelledError:
            pass
        finally:
            unregister_layer_change_callback(_on_layer_change)
            async with _sse_queues_lock:
                if queue in _sse_queues:
                    _sse_queues.remove(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering if proxied
        },
    )


def _sse_format(event: str, data: Any) -> str:
    """Format a single SSE event."""
    import json as _j
    payload = _j.dumps(data, default=str)
    return f"event: {event}\ndata: {payload}\n\n"


# ---------------------------------------------------------------------------
# WebSocket Channel — persistent bidirectional connection
# ---------------------------------------------------------------------------
# Replaces polling: one Tor circuit, always warm, instant push.
#
# Auth: HMAC signature passed as query params on the upgrade request:
#   ws://host/api/ai/channel/ws?ts=...&nonce=...&sig=...
#
# Protocol (JSON messages over WS):
#   Agent → SB:  {"type": "command", "cmd": "get_summary", "args": {}}
#   SB → Agent:  {"type": "result",  "command_id": "...", "result": {...}}
#   SB → Agent:  {"type": "task",    "task": {...}}     (pushed instantly)
#   SB → Agent:  {"type": "alert",   "alert": {...}}    (watchdog hits)
#   Agent → SB:  {"type": "ping"}
#   SB → Agent:  {"type": "pong"}
# ---------------------------------------------------------------------------

from fastapi import WebSocket, WebSocketDisconnect
import json as _json_mod

# Track connected WebSocket clients for push delivery
_ws_clients: list[WebSocket] = []
_ws_clients_lock = asyncio.Lock()


async def _verify_ws_hmac(ws: WebSocket) -> bool:
    """Verify HMAC signature from WebSocket query params.

    The agent signs: METHOD|path|ts|nonce|body_digest
    For WS upgrade: GET|/api/ai/channel/ws|ts|nonce|sha256("")
    """
    import hashlib as _hl
    import hmac as _hm

    params = ws.query_params
    ts_str = params.get("ts", "")
    nonce = params.get("nonce", "")
    sig = params.get("sig", "")

    if not ts_str or not nonce or not sig:
        return False

    try:
        ts = int(ts_str)
    except ValueError:
        return False

    # Timestamp within 60 seconds
    if abs(time.time() - ts) > 60:
        return False

    from services.config import get_settings
    secret = str(get_settings().OPENCLAW_HMAC_SECRET or "").strip()
    if not secret:
        return False

    # Same signature format as HTTP HMAC: GET|path|ts|nonce|sha256("")
    body_digest = _hl.sha256(b"").hexdigest()
    message = f"GET|/api/ai/channel/ws|{ts_str}|{nonce}|{body_digest}"
    expected = _hm.new(
        secret.encode("utf-8"),
        message.encode("utf-8"),
        _hl.sha256,
    ).hexdigest()

    return _hm.compare_digest(sig, expected)


async def _ws_push_loop(ws: WebSocket):
    """Background coroutine that checks for tasks/alerts and pushes them."""
    from services.openclaw_channel import channel

    while True:
        try:
            await asyncio.sleep(1)  # Check every second (near-instant delivery)

            # Poll for tasks (watchdog alerts, operator tasks)
            tasks = channel.poll_tasks()
            for task in tasks:
                try:
                    await ws.send_json({"type": "task", "task": task})
                except Exception:
                    return  # Connection closed

        except asyncio.CancelledError:
            return
        except Exception:
            await asyncio.sleep(3)


@router.websocket("/api/ai/channel/ws")
async def channel_websocket(ws: WebSocket):
    """Persistent bidirectional WebSocket channel for OpenClaw agents.

    One connection = one Tor circuit kept warm. No polling overhead.
    Commands execute immediately, tasks/alerts are pushed in real-time.
    """
    # Auth: check HMAC on upgrade, or allow local connections
    host = (ws.client.host or "").lower() if ws.client else ""
    is_local = host in ("127.0.0.1", "::1", "localhost")

    if not is_local and not await _verify_ws_hmac(ws):
        # Must accept before sending close with custom code
        await ws.accept()
        await ws.close(code=4001, reason="HMAC authentication failed")
        return

    await ws.accept()

    # Register this client for push delivery
    async with _ws_clients_lock:
        _ws_clients.append(ws)

    # Start background push loop
    push_task = asyncio.create_task(_ws_push_loop(ws))

    from services.openclaw_channel import channel
    from services.config import get_settings

    access_tier = str(get_settings().OPENCLAW_ACCESS_TIER or "restricted").strip().lower()

    # Send welcome message
    try:
        await ws.send_json({
            "type": "connected",
            "access_tier": access_tier,
            "message": "WebSocket channel active. Send commands as JSON.",
        })
    except Exception:
        push_task.cancel()
        return

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = _json_mod.loads(raw)
            except _json_mod.JSONDecodeError:
                await ws.send_json({"type": "error", "detail": "invalid JSON"})
                continue

            msg_type = str(msg.get("type", "")).strip().lower()

            if msg_type == "ping":
                await ws.send_json({"type": "pong", "ts": time.time()})
                continue

            if msg_type == "command":
                cmd = str(msg.get("cmd", "")).strip().lower()
                args = msg.get("args") or {}
                if not cmd:
                    await ws.send_json({"type": "error", "detail": "empty command"})
                    continue

                # Execute command (same as HTTP channel)
                result = channel.submit_command(cmd, args, access_tier)
                await ws.send_json({
                    "type": "result",
                    "cmd": cmd,
                    "command_id": result.get("command_id"),
                    **result,
                })
                continue

            await ws.send_json({
                "type": "error",
                "detail": f"unknown message type: {msg_type}. Use 'command' or 'ping'.",
            })

    except WebSocketDisconnect:
        logger.info("OpenClaw WebSocket client disconnected")
    except Exception as e:
        logger.warning("OpenClaw WebSocket error: %s", e)
    finally:
        push_task.cancel()
        async with _ws_clients_lock:
            if ws in _ws_clients:
                _ws_clients.remove(ws)


async def broadcast_to_agents(msg: dict[str, Any]):
    """Push a message to all connected WebSocket AND SSE agents.

    Called by watchdog, correlation engine, or operator actions.
    """
    # Push to WebSocket clients
    async with _ws_clients_lock:
        clients = list(_ws_clients)

    dead: list[WebSocket] = []
    for ws in clients:
        try:
            await ws.send_json(msg)
        except Exception:
            dead.append(ws)

    if dead:
        async with _ws_clients_lock:
            for ws in dead:
                if ws in _ws_clients:
                    _ws_clients.remove(ws)

    # Push to SSE clients
    event_type = msg.get("type", "alert")
    await broadcast_to_sse_clients(event_type, msg)


# ---------------------------------------------------------------------------
# Analysis Zones — OpenClaw-placed map overlays (delete from frontend)
# ---------------------------------------------------------------------------

@router.delete(
    "/api/ai/analysis-zones/{zone_id}",
    dependencies=[Depends(require_local_operator)],
)
@limiter.limit("30/minute")
async def delete_analysis_zone(request: Request, zone_id: str) -> dict:
    """Delete an analysis zone by ID (called from the map popup delete button)."""
    from services.analysis_zone_store import delete_zone

    removed = delete_zone(zone_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Zone not found")
    return {"ok": True, "removed": zone_id}


@router.get(
    "/api/ai/analysis-zones",
    dependencies=[Depends(require_openclaw_or_local)],
)
@limiter.limit("60/minute")
async def list_analysis_zones(request: Request) -> dict:
    """List all live analysis zones."""
    from services.analysis_zone_store import list_zones

    return {"ok": True, "zones": list_zones()}

