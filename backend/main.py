from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from services.data_fetcher import start_scheduler, stop_scheduler, get_latest_data
from services.ais_stream import start_ais_stream, stop_ais_stream
from services.carrier_tracker import start_carrier_tracker, stop_carrier_tracker
import uvicorn
import logging
import hashlib
import json as json_mod

logging.basicConfig(level=logging.INFO)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Start background data fetching, AIS stream, and carrier tracker
    start_carrier_tracker()
    start_ais_stream()
    start_scheduler()
    yield
    # Shutdown: Stop all background services
    stop_ais_stream()
    stop_scheduler()
    stop_carrier_tracker()

app = FastAPI(title="Live Risk Dashboard API", lifespan=lifespan)

from fastapi.middleware.gzip import GZipMiddleware
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # For prototyping, allow all
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from services.data_fetcher import update_all_data

@app.get("/api/refresh")
async def force_refresh():
    # Force an immediate synchronous update of the data payload
    import threading
    t = threading.Thread(target=update_all_data)
    t.start()
    return {"status": "refreshing in background"}

@app.get("/api/live-data")
async def live_data():
    return get_latest_data()

@app.get("/api/live-data/fast")
async def live_data_fast(request: Request):
    d = get_latest_data()
    payload = {
        "commercial_flights": d.get("commercial_flights", []),
        "military_flights": d.get("military_flights", []),
        "private_flights": d.get("private_flights", []),
        "private_jets": d.get("private_jets", []),
        "tracked_flights": d.get("tracked_flights", []),
        "ships": d.get("ships", []),
        "cctv": d.get("cctv", []),
        "uavs": d.get("uavs", []),
        "liveuamap": d.get("liveuamap", []),
        "gps_jamming": d.get("gps_jamming", []),
    }
    # ETag includes last_updated timestamp so it changes on every data refresh,
    # not just when item counts change (old bug: positions went stale)
    last_updated = d.get("last_updated", "")
    counts = "|".join(f"{k}:{len(v) if isinstance(v, list) else 0}" for k, v in payload.items())
    etag = hashlib.md5(f"{last_updated}|{counts}".encode()).hexdigest()[:16]
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "no-cache"})
    return Response(
        content=json_mod.dumps(payload),
        media_type="application/json",
        headers={"ETag": etag, "Cache-Control": "no-cache"}
    )

@app.get("/api/live-data/slow")
async def live_data_slow(request: Request):
    d = get_latest_data()
    payload = {
        "last_updated": d.get("last_updated"),
        "news": d.get("news", []),
        "stocks": d.get("stocks", {}),
        "oil": d.get("oil", {}),
        "weather": d.get("weather"),
        "traffic": d.get("traffic", []),
        "earthquakes": d.get("earthquakes", []),
        "frontlines": d.get("frontlines"),
        "gdelt": d.get("gdelt", []),
        "airports": d.get("airports", []),
        "satellites": d.get("satellites", [])
    }
    # ETag based on last_updated + item counts
    last_updated = d.get("last_updated", "")
    counts = "|".join(f"{k}:{len(v) if isinstance(v, list) else 0}" for k, v in payload.items())
    etag = hashlib.md5(f"slow|{last_updated}|{counts}".encode()).hexdigest()[:16]
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "no-cache"})
    return Response(
        content=json_mod.dumps(payload, default=str),
        media_type="application/json",
        headers={"ETag": etag, "Cache-Control": "no-cache"}
    )

@app.get("/api/debug-latest")
async def debug_latest_data():
    return list(get_latest_data().keys())


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}

from services.radio_intercept import get_top_broadcastify_feeds, get_openmhz_systems, get_recent_openmhz_calls, find_nearest_openmhz_system

@app.get("/api/radio/top")
async def get_top_radios():
    return get_top_broadcastify_feeds()

@app.get("/api/radio/openmhz/systems")
async def api_get_openmhz_systems():
    return get_openmhz_systems()

@app.get("/api/radio/openmhz/calls/{sys_name}")
async def api_get_openmhz_calls(sys_name: str):
    return get_recent_openmhz_calls(sys_name)

@app.get("/api/radio/nearest")
async def api_get_nearest_radio(lat: float, lng: float):
    return find_nearest_openmhz_system(lat, lng)

from services.radio_intercept import find_nearest_openmhz_systems_list

@app.get("/api/radio/nearest-list")
async def api_get_nearest_radios_list(lat: float, lng: float, limit: int = 5):
    return find_nearest_openmhz_systems_list(lat, lng, limit=limit)

from services.network_utils import fetch_with_curl

@app.get("/api/route/{callsign}")
async def get_flight_route(callsign: str):
    r = fetch_with_curl("https://api.adsb.lol/api/0/routeset", method="POST", json_data={"planes": [{"callsign": callsign}]}, timeout=10)
    if r.status_code == 200:
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
                return {
                    "orig_loc": [airports[0].get("lon", 0), airports[0].get("lat", 0)],
                    "dest_loc": [airports[-1].get("lon", 0), airports[-1].get("lat", 0)]
                }
    return {}

from services.region_dossier import get_region_dossier

@app.get("/api/region-dossier")
def api_region_dossier(lat: float, lng: float):
    """Sync def so FastAPI runs it in a threadpool — prevents blocking the event loop."""
    return get_region_dossier(lat, lng)

# ---------------------------------------------------------------------------
# API Settings — key registry & management
# ---------------------------------------------------------------------------
from services.api_settings import get_api_keys, update_api_key
from pydantic import BaseModel

class ApiKeyUpdate(BaseModel):
    env_key: str
    value: str

@app.get("/api/settings/api-keys")
async def api_get_keys():
    return get_api_keys()

@app.put("/api/settings/api-keys")
async def api_update_key(body: ApiKeyUpdate):
    ok = update_api_key(body.env_key, body.value)
    if ok:
        return {"status": "updated", "env_key": body.env_key}
    return {"status": "error", "message": "Failed to update .env file"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

# Application successfully initialized with background scraping tasks
