import os
import time
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
_start_time = time.time()

# ---------------------------------------------------------------------------
# Docker Swarm Secrets support
# For each VAR below, if VAR_FILE is set (e.g. AIS_API_KEY_FILE=/run/secrets/AIS_API_KEY),
# the file is read and its trimmed content is placed into VAR.
# This MUST run before service imports — modules read os.environ at import time.
# ---------------------------------------------------------------------------
_SECRET_VARS = [
    "AIS_API_KEY",
    "OPENSKY_CLIENT_ID",
    "OPENSKY_CLIENT_SECRET",
    "LTA_ACCOUNT_KEY",
    "CORS_ORIGINS",
    "ADMIN_KEY",
]

for _var in _SECRET_VARS:
    _file_var = f"{_var}_FILE"
    _file_path = os.environ.get(_file_var)
    if _file_path:
        try:
            with open(_file_path, "r") as _f:
                _value = _f.read().strip()
            if _value:
                os.environ[_var] = _value
                logger.info(f"Loaded secret {_var} from {_file_path}")
            else:
                logger.warning(f"Secret file {_file_path} for {_var} is empty")
        except FileNotFoundError:
            logger.error(f"Secret file {_file_path} for {_var} not found")
        except Exception as _e:
            logger.error(f"Failed to read secret file {_file_path} for {_var}: {_e}")

from fastapi import FastAPI, Request, Response, Query, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from services.data_fetcher import start_scheduler, stop_scheduler, get_latest_data, source_timestamps
from services.ais_stream import start_ais_stream, stop_ais_stream
from services.carrier_tracker import start_carrier_tracker, stop_carrier_tracker
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from services.schemas import HealthResponse, RefreshResponse
import uvicorn
import hashlib
import json as json_mod
import socket
import threading

limiter = Limiter(key_func=get_remote_address)

# ---------------------------------------------------------------------------
# Admin authentication — protects settings & system endpoints
# Set ADMIN_KEY in .env or Docker secrets. If unset, endpoints remain open
# for local-dev convenience but will log a startup warning.
# ---------------------------------------------------------------------------
_ADMIN_KEY = os.environ.get("ADMIN_KEY", "")
if not _ADMIN_KEY:
    logger.warning("ADMIN_KEY is not set — sensitive endpoints are UNPROTECTED. "
                   "Set ADMIN_KEY in .env or Docker secrets for production.")

def require_admin(request: Request):
    """FastAPI dependency that rejects requests without a valid X-Admin-Key header."""
    if not _ADMIN_KEY:
        return  # No key configured — allow all (local dev)
    if request.headers.get("X-Admin-Key") != _ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Forbidden — invalid or missing admin key")


def _build_cors_origins():
    """Build a CORS origins whitelist: localhost + LAN IPs + env overrides.
    Falls back to wildcard only if auto-detection fails entirely."""
    origins = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]
    # Add this machine's LAN IPs (covers common home/office setups)
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ("127.0.0.1", "0.0.0.0"):
                origins.append(f"http://{ip}:3000")
                origins.append(f"http://{ip}:8000")
    except Exception:
        pass
    # Allow user override via CORS_ORIGINS env var (comma-separated)
    extra = os.environ.get("CORS_ORIGINS", "")
    if extra:
        origins.extend([o.strip() for o in extra.split(",") if o.strip()])
    return list(set(origins))  # deduplicate

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Validate environment variables before starting anything
    from services.env_check import validate_env
    validate_env(strict=True)

    # Start AIS stream first — it loads the disk cache (instant ships) then
    # begins accumulating live vessel data via WebSocket in the background.
    start_ais_stream()

    # Carrier tracker runs its own initial update_carrier_positions() internally
    # in _scheduler_loop, so we do NOT call it again in the preload thread.
    start_carrier_tracker()

    # Start the recurring scheduler (fast=60s, slow=30min).
    start_scheduler()

    # Kick off the full data preload in a background thread so the server
    # is listening on port 8000 instantly.  The frontend's adaptive polling
    # (retries every 3s) will pick up data piecemeal as each fetcher finishes.
    def _background_preload():
        logger.info("=== PRELOADING DATA (background — server already accepting requests) ===")
        try:
            update_all_data()
            logger.info("=== PRELOAD COMPLETE ===")
        except Exception as e:
            logger.error(f"Data preload failed (non-fatal): {e}")

    threading.Thread(target=_background_preload, daemon=True).start()

    yield
    # Shutdown: Stop all background services
    stop_ais_stream()
    stop_scheduler()
    stop_carrier_tracker()

app = FastAPI(title="Live Risk Dashboard API", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

from fastapi.middleware.gzip import GZipMiddleware
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_build_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from services.data_fetcher import update_all_data

_refresh_lock = threading.Lock()

@app.get("/api/refresh", response_model=RefreshResponse)
@limiter.limit("2/minute")
async def force_refresh(request: Request):
    if not _refresh_lock.acquire(blocking=False):
        return {"status": "refresh already in progress"}
    def _do_refresh():
        try:
            update_all_data()
        finally:
            _refresh_lock.release()
    t = threading.Thread(target=_do_refresh)
    t.start()
    return {"status": "refreshing in background"}

@app.post("/api/ais/feed")
@limiter.limit("60/minute")
async def ais_feed(request: Request):
    """Accept AIS-catcher HTTP JSON feed (POST decoded AIS messages)."""
    from services.ais_stream import ingest_ais_catcher
    try:
        body = await request.json()
    except Exception:
        return Response(content='{"error":"invalid JSON"}', status_code=400, media_type="application/json")

    msgs = body.get("msgs", [])
    if not msgs:
        return {"status": "ok", "ingested": 0}

    count = ingest_ais_catcher(msgs)
    return {"status": "ok", "ingested": count}

from pydantic import BaseModel
class ViewportUpdate(BaseModel):
    s: float
    w: float
    n: float
    e: float

@app.post("/api/viewport")
@limiter.limit("60/minute")
async def update_viewport(vp: ViewportUpdate, request: Request):
    """Receive frontend map bounds to dynamically choke the AIS stream."""
    from services.ais_stream import update_ais_bbox
    # Add a gentle 10% padding so ships don't pop-in right at the edge
    pad_lat = (vp.n - vp.s) * 0.1
    # handle antimeridian bounding box padding later if needed, simple for now:
    pad_lng = (vp.e - vp.w) * 0.1 if vp.e > vp.w else 0 
    
    update_ais_bbox(
        south=max(-90, vp.s - pad_lat),
        west=max(-180, vp.w - pad_lng) if pad_lng else vp.w,
        north=min(90, vp.n + pad_lat),
        east=min(180, vp.e + pad_lng) if pad_lng else vp.e
    )
    return {"status": "ok"}

@app.get("/api/live-data")
@limiter.limit("120/minute")
async def live_data(request: Request):
    return get_latest_data()

def _etag_response(request: Request, payload: dict, prefix: str = "", default=None):
    """Serialize once, hash the bytes for ETag, return 304 or full response."""
    content = json_mod.dumps(payload, default=default)
    etag = hashlib.md5(f"{prefix}{content}".encode()).hexdigest()[:16]
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "no-cache"})
    return Response(content=content, media_type="application/json",
                    headers={"ETag": etag, "Cache-Control": "no-cache"})

def _bbox_filter(items: list, s: float, w: float, n: float, e: float,
                 lat_key: str = "lat", lng_key: str = "lng") -> list:
    """Filter a list of dicts to those within the bounding box (with 20% padding).
    Handles antimeridian crossing (e.g. w=170, e=-170)."""
    pad_lat = (n - s) * 0.2
    pad_lng = (e - w) * 0.2 if e > w else ((e + 360 - w) * 0.2)
    s2, n2 = s - pad_lat, n + pad_lat
    w2, e2 = w - pad_lng, e + pad_lng
    crosses_antimeridian = w2 > e2
    out = []
    for item in items:
        lat = item.get(lat_key)
        lng = item.get(lng_key)
        if lat is None or lng is None:
            out.append(item)  # Keep items without coords (don't filter them out)
            continue
        if not (s2 <= lat <= n2):
            continue
        if crosses_antimeridian:
            if lng >= w2 or lng <= e2:
                out.append(item)
        else:
            if w2 <= lng <= e2:
                out.append(item)
    return out

@app.get("/api/live-data/fast")
@limiter.limit("120/minute")
async def live_data_fast(request: Request,
                         s: float = Query(None, description="South bound"),
                         w: float = Query(None, description="West bound"),
                         n: float = Query(None, description="North bound"),
                         e: float = Query(None, description="East bound")):
    d = get_latest_data()
    has_bbox = all(v is not None for v in (s, w, n, e))
    def _f(items, lat_key="lat", lng_key="lng"):
        return _bbox_filter(items, s, w, n, e, lat_key, lng_key) if has_bbox else items
    payload = {
        "commercial_flights": _f(d.get("commercial_flights", [])),
        "military_flights": _f(d.get("military_flights", [])),
        "private_flights": _f(d.get("private_flights", [])),
        "private_jets": _f(d.get("private_jets", [])),
        "tracked_flights": d.get("tracked_flights", []),  # Always send tracked (small set)
        "ships": _f(d.get("ships", [])),
        "cctv": _f(d.get("cctv", []), lat_key="lat", lng_key="lon"),
        "uavs": _f(d.get("uavs", [])),
        "liveuamap": _f(d.get("liveuamap", [])),
        "gps_jamming": _f(d.get("gps_jamming", [])),
        "satellites": _f(d.get("satellites", [])),
        "satellite_source": d.get("satellite_source", "none"),
        "freshness": dict(source_timestamps),
    }
    bbox_tag = f"{s},{w},{n},{e}" if has_bbox else "full"
    return _etag_response(request, payload, prefix=f"fast|{bbox_tag}|")

@app.get("/api/live-data/slow")
@limiter.limit("60/minute")
async def live_data_slow(request: Request,
                         s: float = Query(None, description="South bound"),
                         w: float = Query(None, description="West bound"),
                         n: float = Query(None, description="North bound"),
                         e: float = Query(None, description="East bound")):
    d = get_latest_data()
    has_bbox = all(v is not None for v in (s, w, n, e))
    def _f(items, lat_key="lat", lng_key="lng"):
        return _bbox_filter(items, s, w, n, e, lat_key, lng_key) if has_bbox else items
    payload = {
        "last_updated": d.get("last_updated"),
        "news": d.get("news", []),  # News has coords but we always send it (small set, important)
        "stocks": d.get("stocks", {}),
        "oil": d.get("oil", {}),
        "weather": d.get("weather"),
        "traffic": d.get("traffic", []),
        "earthquakes": _f(d.get("earthquakes", [])),
        "frontlines": d.get("frontlines"),  # Always send (GeoJSON polygon, not point-filterable)
        "gdelt": d.get("gdelt", []),  # GeoJSON features — filtered client-side
        "airports": d.get("airports", []),  # Always send (reference data)
        "kiwisdr": _f(d.get("kiwisdr", []), lat_key="lat", lng_key="lon"),
        "space_weather": d.get("space_weather"),
        "internet_outages": _f(d.get("internet_outages", [])),
        "firms_fires": _f(d.get("firms_fires", [])),
        "datacenters": _f(d.get("datacenters", [])),
        "military_bases": _f(d.get("military_bases", [])),
        "power_plants": _f(d.get("power_plants", [])),
        "freshness": dict(source_timestamps),
    }
    bbox_tag = f"{s},{w},{n},{e}" if has_bbox else "full"
    return _etag_response(request, payload, prefix=f"slow|{bbox_tag}|", default=str)

@app.get("/api/debug-latest")
@limiter.limit("30/minute")
async def debug_latest_data(request: Request):
    return list(get_latest_data().keys())


@app.get("/api/health", response_model=HealthResponse)
@limiter.limit("30/minute")
async def health_check(request: Request):
    import time
    d = get_latest_data()
    last = d.get("last_updated")
    return {
        "status": "ok",
        "last_updated": last,
        "sources": {
            "flights": len(d.get("commercial_flights", [])),
            "military": len(d.get("military_flights", [])),
            "ships": len(d.get("ships", [])),
            "satellites": len(d.get("satellites", [])),
            "earthquakes": len(d.get("earthquakes", [])),
            "cctv": len(d.get("cctv", [])),
            "news": len(d.get("news", [])),
            "uavs": len(d.get("uavs", [])),
            "firms_fires": len(d.get("firms_fires", [])),
            "liveuamap": len(d.get("liveuamap", [])),
            "gdelt": len(d.get("gdelt", [])),
        },
        "freshness": dict(source_timestamps),
        "uptime_seconds": round(time.time() - _start_time),
    }



from services.radio_intercept import get_top_broadcastify_feeds, get_openmhz_systems, get_recent_openmhz_calls, find_nearest_openmhz_system

@app.get("/api/radio/top")
@limiter.limit("30/minute")
async def get_top_radios(request: Request):
    return get_top_broadcastify_feeds()

@app.get("/api/radio/openmhz/systems")
@limiter.limit("30/minute")
async def api_get_openmhz_systems(request: Request):
    return get_openmhz_systems()

@app.get("/api/radio/openmhz/calls/{sys_name}")
@limiter.limit("60/minute")
async def api_get_openmhz_calls(request: Request, sys_name: str):
    return get_recent_openmhz_calls(sys_name)

@app.get("/api/radio/nearest")
@limiter.limit("60/minute")
async def api_get_nearest_radio(
    request: Request,
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
):
    return find_nearest_openmhz_system(lat, lng)

from services.radio_intercept import find_nearest_openmhz_systems_list

@app.get("/api/radio/nearest-list")
@limiter.limit("60/minute")
async def api_get_nearest_radios_list(
    request: Request,
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    limit: int = Query(5, ge=1, le=20),
):
    return find_nearest_openmhz_systems_list(lat, lng, limit=limit)

from services.network_utils import fetch_with_curl

@app.get("/api/route/{callsign}")
@limiter.limit("60/minute")
async def get_flight_route(request: Request, callsign: str, lat: float = 0.0, lng: float = 0.0):
    r = fetch_with_curl("https://api.adsb.lol/api/0/routeset", method="POST", json_data={"planes": [{"callsign": callsign, "lat": lat, "lng": lng}]}, timeout=10)
    if r and r.status_code == 200:
        data = r.json()
        route_list = []
        if isinstance(data, dict):
            route_list = data.get("value", [])
        elif isinstance(data, list):
            route_list = data
        
        if route_list and len(route_list) > 0:
            route = route_list[0]
            airports = route.get("_airports", [])
            if len(airports) >= 2:
                orig = airports[0]
                dest = airports[-1]
                return {
                    "orig_loc": [orig.get("lon", 0), orig.get("lat", 0)],
                    "dest_loc": [dest.get("lon", 0), dest.get("lat", 0)],
                    "origin_name": f"{orig.get('iata', '') or orig.get('icao', '')}: {orig.get('name', 'Unknown')}",
                    "dest_name": f"{dest.get('iata', '') or dest.get('icao', '')}: {dest.get('name', 'Unknown')}",
                }
    return {}

from services.region_dossier import get_region_dossier

@app.get("/api/region-dossier")
@limiter.limit("30/minute")
def api_region_dossier(
    request: Request,
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
):
    """Sync def so FastAPI runs it in a threadpool — prevents blocking the event loop."""
    return get_region_dossier(lat, lng)

from services.sentinel_search import search_sentinel2_scene

@app.get("/api/sentinel2/search")
@limiter.limit("30/minute")
def api_sentinel2_search(
    request: Request,
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
):
    """Search for latest Sentinel-2 imagery at a point. Sync for threadpool execution."""
    return search_sentinel2_scene(lat, lng)

# ---------------------------------------------------------------------------
# API Settings — key registry & management
# ---------------------------------------------------------------------------
from services.api_settings import get_api_keys, update_api_key
from pydantic import BaseModel

class ApiKeyUpdate(BaseModel):
    env_key: str
    value: str

@app.get("/api/settings/api-keys", dependencies=[Depends(require_admin)])
@limiter.limit("30/minute")
async def api_get_keys(request: Request):
    return get_api_keys()

@app.put("/api/settings/api-keys", dependencies=[Depends(require_admin)])
@limiter.limit("10/minute")
async def api_update_key(request: Request, body: ApiKeyUpdate):
    ok = update_api_key(body.env_key, body.value)
    if ok:
        return {"status": "updated", "env_key": body.env_key}
    return {"status": "error", "message": "Failed to update .env file"}

# ---------------------------------------------------------------------------
# News Feed Configuration
# ---------------------------------------------------------------------------
from services.news_feed_config import get_feeds, save_feeds, reset_feeds

@app.get("/api/settings/news-feeds")
@limiter.limit("30/minute")
async def api_get_news_feeds(request: Request):
    return get_feeds()

@app.put("/api/settings/news-feeds", dependencies=[Depends(require_admin)])
@limiter.limit("10/minute")
async def api_save_news_feeds(request: Request):
    body = await request.json()
    ok = save_feeds(body)
    if ok:
        return {"status": "updated", "count": len(body)}
    return Response(
        content=json_mod.dumps({"status": "error", "message": "Validation failed (max 20 feeds, each needs name/url/weight 1-5)"}),
        status_code=400,
        media_type="application/json",
    )

@app.post("/api/settings/news-feeds/reset", dependencies=[Depends(require_admin)])
@limiter.limit("10/minute")
async def api_reset_news_feeds(request: Request):
    ok = reset_feeds()
    if ok:
        return {"status": "reset", "feeds": get_feeds()}
    return {"status": "error", "message": "Failed to reset feeds"}

# ---------------------------------------------------------------------------
# System — self-update
# ---------------------------------------------------------------------------
from pathlib import Path
from services.updater import perform_update, schedule_restart

@app.post("/api/system/update", dependencies=[Depends(require_admin)])
@limiter.limit("1/minute")
async def system_update(request: Request):
    """Download latest release, backup current files, extract update, and restart."""
    # In Docker, __file__ is /app/main.py so .parent.parent resolves to /
    # which causes PermissionError. Use cwd as fallback when parent.parent
    # doesn't contain frontend/ or backend/ (i.e. we're already at project root).
    candidate = Path(__file__).resolve().parent.parent
    if (candidate / "frontend").is_dir() or (candidate / "backend").is_dir():
        project_root = str(candidate)
    else:
        project_root = os.getcwd()
    result = perform_update(project_root)
    if result.get("status") == "error":
        return Response(
            content=json_mod.dumps(result),
            status_code=500,
            media_type="application/json",
        )
    # Schedule restart AFTER response flushes (2s delay)
    threading.Timer(2.0, schedule_restart, args=[project_root]).start()
    return result

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
