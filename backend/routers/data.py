import asyncio
import logging
import math
import os
import threading
from typing import Any
from fastapi import APIRouter, Request, Response, Query, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from limiter import limiter
from auth import require_admin, require_local_operator
from services.data_fetcher import update_all_data
import orjson
import json as json_mod

logger = logging.getLogger(__name__)

router = APIRouter()

_refresh_lock = threading.Lock()


class ViewportUpdate(BaseModel):
    s: float
    w: float
    n: float
    e: float


class LayerUpdate(BaseModel):
    layers: dict[str, bool]


class LiveUamapOptInUpdate(BaseModel):
    opted_in: bool


class PredictionMarketsOptInUpdate(BaseModel):
    opted_in: bool


_LAST_VIEWPORT_UPDATE: tuple | None = None
_LAST_VIEWPORT_UPDATE_TS = 0.0
_VIEWPORT_UPDATE_LOCK = threading.Lock()
_VIEWPORT_DEDUPE_EPSILON = 1.0
_VIEWPORT_MIN_UPDATE_S = 10.0


def _normalize_longitude(value: float) -> float:
    normalized = ((value + 180.0) % 360.0 + 360.0) % 360.0 - 180.0
    if normalized == -180.0 and value > 0:
        return 180.0
    return normalized


def _normalize_viewport_bounds(s: float, w: float, n: float, e: float) -> tuple:
    south = max(-90.0, min(90.0, s))
    north = max(-90.0, min(90.0, n))
    raw_width = abs(e - w)
    if not math.isfinite(raw_width) or raw_width >= 360.0:
        return south, -180.0, north, 180.0
    west = _normalize_longitude(w)
    east = _normalize_longitude(e)
    if east < west:
        return south, -180.0, north, 180.0
    return south, west, north, east


def _viewport_changed_enough(bounds: tuple) -> bool:
    global _LAST_VIEWPORT_UPDATE, _LAST_VIEWPORT_UPDATE_TS
    import time
    now = time.monotonic()
    with _VIEWPORT_UPDATE_LOCK:
        if _LAST_VIEWPORT_UPDATE is None:
            _LAST_VIEWPORT_UPDATE = bounds
            _LAST_VIEWPORT_UPDATE_TS = now
            return True
        changed = any(
            abs(current - previous) > _VIEWPORT_DEDUPE_EPSILON
            for current, previous in zip(bounds, _LAST_VIEWPORT_UPDATE)
        )
        if not changed and (now - _LAST_VIEWPORT_UPDATE_TS) < _VIEWPORT_MIN_UPDATE_S:
            return False
        if (now - _LAST_VIEWPORT_UPDATE_TS) < _VIEWPORT_MIN_UPDATE_S:
            return False
        _LAST_VIEWPORT_UPDATE = bounds
        _LAST_VIEWPORT_UPDATE_TS = now
        return True


def _queue_viirs_change_refresh() -> None:
    from services.fetchers.earth_observation import fetch_viirs_change_nodes
    threading.Thread(target=fetch_viirs_change_nodes, daemon=True).start()


def _etag_response(request: Request, payload: dict, prefix: str = "", default=None):
    etag = _current_etag(prefix)
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "no-cache"})
    content = json_mod.dumps(_json_safe(payload), default=default, allow_nan=False)
    return Response(content=content, media_type="application/json",
        headers={"ETag": etag, "Cache-Control": "no-cache"})


def _current_etag(prefix: str = "") -> str:
    from services.fetchers._store import get_active_layers_version, get_data_version
    return f"{prefix}v{get_data_version()}-l{get_active_layers_version()}"


# ── Issue #288: viewport-aware payloads ─────────────────────────────────────
# Heavy, density-driven, time-sensitive layers that benefit from bbox
# filtering. Light reference layers (datacenters, military_bases,
# power_plants, satellites, weather, news, etc.) are intentionally NOT
# in these sets — they ship world-scale even when bounds are supplied so
# panning never reveals an "empty world" of static infrastructure.
#
# When the caller does NOT pass s/w/n/e, none of this runs and the response
# is byte-for-byte identical to the pre-#288 behavior.
_FAST_BBOX_HEAVY_KEYS: tuple[str, ...] = (
    "commercial_flights",
    "military_flights",
    "private_flights",
    "private_jets",
    "tracked_flights",
    "ships",
    "cctv",
    "uavs",
    "liveuamap",
    "gps_jamming",
    "sigint",
    "trains",
)
_SLOW_BBOX_HEAVY_KEYS: tuple[str, ...] = (
    "gdelt",
    "firms_fires",
    "kiwisdr",
    "scanners",
    "psk_reporter",
)


def _has_full_bbox(s, w, n, e) -> bool:
    return None not in (s, w, n, e)


def _bbox_etag_suffix(s, w, n, e) -> str:
    """Quantize bbox to 1° before mixing into the ETag.

    The 20% padding inside _bbox_filter already absorbs sub-degree pans;
    quantizing here means small mouse drags don't blow the ETag cache
    on the client. Full-world bounds collapse to a single suffix.
    """
    if not _has_full_bbox(s, w, n, e):
        return ""
    try:
        ss = math.floor(float(s))
        ww = math.floor(float(w))
        nn = math.ceil(float(n))
        ee = math.ceil(float(e))
    except (TypeError, ValueError):
        return ""
    # If the requested window covers basically the whole world, treat it as
    # "no bbox" for caching purposes so world-zoomed clients all hit the
    # same ETag and benefit from the existing 304 path.
    lat_span, lng_span = _bbox_spans(s, w, n, e)
    if lng_span >= 300 or lat_span >= 120:
        return ""
    return f"|bbox={ss},{ww},{nn},{ee}"


def _apply_bbox_to_payload(payload: dict, heavy_keys: tuple[str, ...],
                            s: float, w: float, n: float, e: float) -> dict:
    """In-place filter the heavy-key collections in *payload* to a viewport.

    Items without lat/lng are passed through (so e.g. summary blobs aren't
    accidentally dropped). The existing _bbox_filter helper applies a 20%
    pad and handles antimeridian crossings.
    """
    lat_span, lng_span = _bbox_spans(s, w, n, e)
    # World-scale request → skip filtering entirely. Spares the CPU and
    # guarantees the response matches the no-params shape.
    if lng_span >= 300 or lat_span >= 120:
        return payload
    for key in heavy_keys:
        items = payload.get(key)
        if not isinstance(items, list) or not items:
            continue
        payload[key] = _bbox_filter(items, s, w, n, e)
    return payload


def _json_safe(value):
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in list(value.items())}
    if isinstance(value, list):
        return [_json_safe(v) for v in list(value)]
    if isinstance(value, tuple):
        return [_json_safe(v) for v in list(value)]
    return value


def _sanitize_payload(value):
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _sanitize_payload(v) for k, v in list(value.items())}
    if isinstance(value, (list, tuple)):
        return list(value)
    return value


def _live_data_json_bytes(payload: dict) -> bytes:
    """Serialize dashboard payloads with the same defensive orjson options everywhere."""
    return orjson.dumps(
        _sanitize_payload(payload),
        default=str,
        option=orjson.OPT_NON_STR_KEYS,
    )


def _bbox_filter(items: list, s: float, w: float, n: float, e: float,
                 lat_key: str = "lat", lng_key: str = "lng") -> list:
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
            out.append(item)
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


def _bbox_filter_geojson_points(items: list, s: float, w: float, n: float, e: float) -> list:
    pad_lat = (n - s) * 0.2
    pad_lng = (e - w) * 0.2 if e > w else ((e + 360 - w) * 0.2)
    s2, n2 = s - pad_lat, n + pad_lat
    w2, e2 = w - pad_lng, e + pad_lng
    crosses_antimeridian = w2 > e2
    out = []
    for item in items:
        geometry = item.get("geometry") if isinstance(item, dict) else None
        coords = geometry.get("coordinates") if isinstance(geometry, dict) else None
        if not isinstance(coords, (list, tuple)) or len(coords) < 2:
            out.append(item)
            continue
        lng, lat = coords[0], coords[1]
        if lat is None or lng is None:
            out.append(item)
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


def _bbox_spans(s, w, n, e) -> tuple:
    if None in (s, w, n, e):
        return 180.0, 360.0
    lat_span = max(0.0, float(n) - float(s))
    lng_span = float(e) - float(w)
    if lng_span < 0:
        lng_span += 360.0
    if lng_span == 0 and w == -180 and e == 180:
        lng_span = 360.0
    return lat_span, max(0.0, lng_span)


def _cap_startup_items(items: list | None, max_items: int) -> list:
    if not items:
        return []
    if len(items) <= max_items:
        return items
    return items[:max_items]


def _cap_fast_startup_payload(payload: dict) -> dict:
    capped = dict(payload)
    capped["commercial_flights"] = _cap_startup_items(capped.get("commercial_flights"), 800)
    capped["private_flights"] = _cap_startup_items(capped.get("private_flights"), 300)
    capped["private_jets"] = _cap_startup_items(capped.get("private_jets"), 150)
    capped["ships"] = _cap_startup_items(capped.get("ships"), 1500)
    capped["cctv"] = []
    capped["sigint"] = _cap_startup_items(capped.get("sigint"), 500)
    capped["trains"] = _cap_startup_items(capped.get("trains"), 100)
    capped["startup_payload"] = True
    return capped


def _cap_fast_dashboard_payload(payload: dict) -> dict:
    return payload


def _world_and_continental_scale(has_bbox: bool, s, w, n, e) -> tuple:
    lat_span, lng_span = _bbox_spans(s, w, n, e)
    world_scale = (not has_bbox) or lng_span >= 300 or lat_span >= 120
    continental_scale = has_bbox and not world_scale and (lng_span >= 120 or lat_span >= 55)
    return world_scale, continental_scale


def _filter_sigint_by_layers(items: list, active_layers: dict) -> list:
    allow_aprs = bool(active_layers.get("sigint_aprs", True))
    allow_mesh = bool(active_layers.get("sigint_meshtastic", True))
    if allow_aprs and allow_mesh:
        return items
    allowed_sources: set = {"js8call"}
    if allow_aprs:
        allowed_sources.add("aprs")
    if allow_mesh:
        allowed_sources.update({"meshtastic", "meshtastic-map"})
    return [item for item in items if str(item.get("source") or "").lower() in allowed_sources]


def _sigint_totals_for_items(items: list) -> dict:
    totals = {"total": len(items), "meshtastic": 0, "meshtastic_live": 0, "meshtastic_map": 0,
              "aprs": 0, "js8call": 0}
    for item in items:
        source = str(item.get("source") or "").lower()
        if source == "meshtastic":
            totals["meshtastic"] += 1
            if bool(item.get("from_api")):
                totals["meshtastic_map"] += 1
            else:
                totals["meshtastic_live"] += 1
        elif source == "aprs":
            totals["aprs"] += 1
        elif source == "js8call":
            totals["js8call"] += 1
    return totals


@router.get("/api/refresh", dependencies=[Depends(require_admin)])
@limiter.limit("2/minute")
async def force_refresh(request: Request):
    from services.schemas import RefreshResponse
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


@router.post("/api/ais/feed", dependencies=[Depends(require_local_operator)])
@limiter.limit("60/minute")
async def ais_feed(request: Request):
    """Accept AIS-catcher HTTP JSON feed (POST decoded AIS messages)."""
    from services.ais_stream import ingest_ais_catcher
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=422, content={"ok": False, "detail": "invalid JSON body"})
    msgs = body.get("msgs", [])
    if not msgs:
        return {"status": "ok", "ingested": 0}
    count = ingest_ais_catcher(msgs)
    return {"status": "ok", "ingested": count}


@router.get("/api/trail/flight/{icao24}")
@limiter.limit("120/minute")
async def get_selected_flight_trail(icao24: str, request: Request):  # noqa: ARG001
    from services.fetchers.flights import get_flight_trail
    return {"id": icao24, "trail": get_flight_trail(icao24)}


@router.get("/api/trail/ship/{mmsi}")
@limiter.limit("120/minute")
async def get_selected_ship_trail(mmsi: int, request: Request):  # noqa: ARG001
    from services.ais_stream import get_vessel_trail
    return {"id": mmsi, "trail": get_vessel_trail(mmsi)}


@router.post("/api/viewport")
@limiter.limit("60/minute")
async def update_viewport(vp: ViewportUpdate, request: Request):  # noqa: ARG001
    """Receive frontend map bounds. AIS stream stays global so open-ocean
    vessels are never dropped — the frontend worker handles viewport culling."""
    return {"status": "ok"}


@router.get("/api/liveuamap/scraper-status", dependencies=[Depends(require_local_operator)])
async def api_liveuamap_scraper_status():
    """Whether LiveUAMap Playwright may run (Windows needs UI opt-in unless env forces)."""
    from services.liveuamap_settings import liveuamap_scraper_status

    return liveuamap_scraper_status()


@router.post("/api/liveuamap/scraper-opt-in", dependencies=[Depends(require_local_operator)])
@limiter.limit("10/minute")
async def api_liveuamap_scraper_opt_in(body: LiveUamapOptInUpdate, request: Request):
    """Persist operator consent for LiveUAMap scraper (#348)."""
    from services.liveuamap_settings import liveuamap_scraper_status, set_liveuamap_ui_opt_in

    set_liveuamap_ui_opt_in(body.opted_in)
    if body.opted_in:
        from services.fetchers._store import is_any_active

        if is_any_active("global_incidents"):
            threading.Thread(target=_run_liveuamap_refresh, daemon=True).start()
    return liveuamap_scraper_status()


def _run_liveuamap_refresh() -> None:
    try:
        from services.fetchers.geo import update_liveuamap

        update_liveuamap()
    except Exception as e:
        logger.warning("LiveUAMap refresh after opt-in failed: %s", e)


@router.get("/api/prediction-markets/status", dependencies=[Depends(require_local_operator)])
async def api_prediction_markets_status():
    """Whether Polymarket/Kalshi fetches and news market correlation are enabled."""
    from services.prediction_markets_settings import prediction_markets_status

    return prediction_markets_status()


@router.post("/api/prediction-markets/opt-in", dependencies=[Depends(require_local_operator)])
@limiter.limit("10/minute")
async def api_prediction_markets_opt_in(body: PredictionMarketsOptInUpdate, request: Request):
    """Enable or disable prediction market fetches + intercept story correlation."""
    from services.config import get_settings
    from services.prediction_markets_settings import (
        prediction_markets_status,
        set_prediction_markets_ui_opt_in,
    )
    from routers.ai_intel import _write_env_value

    set_prediction_markets_ui_opt_in(body.opted_in)
    _write_env_value("PREDICTION_MARKETS_ENABLED", "true" if body.opted_in else "false")
    os.environ["PREDICTION_MARKETS_ENABLED"] = "true" if body.opted_in else "false"
    get_settings.cache_clear()

    if body.opted_in:
        threading.Thread(target=_run_prediction_markets_refresh, daemon=True).start()
    else:
        threading.Thread(target=_run_prediction_markets_disable, daemon=True).start()

    return prediction_markets_status()


def _run_prediction_markets_refresh() -> None:
    try:
        from services.fetchers.prediction_markets import fetch_prediction_markets
        from services.fetchers.news import fetch_news

        fetch_prediction_markets()
        fetch_news()
    except Exception as e:
        logger.warning("Prediction markets refresh after opt-in failed: %s", e)


def _run_prediction_markets_disable() -> None:
    try:
        from services.fetchers._store import _data_lock, _mark_fresh, latest_data
        from services.fetchers.news import fetch_news

        with _data_lock:
            latest_data["prediction_markets"] = []
            latest_data["trending_markets"] = []
        _mark_fresh("prediction_markets")
        fetch_news()
    except Exception as e:
        logger.warning("Prediction markets disable cleanup failed: %s", e)


@router.post("/api/layers", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def update_layers(update: LayerUpdate, request: Request):
    """Receive frontend layer toggle state. Starts/stops streams accordingly."""
    from services.fetchers._store import active_layers, bump_active_layers_version, is_any_active
    old_ships = is_any_active("ships_military", "ships_cargo", "ships_civilian", "ships_passenger", "ships_tracked_yachts")
    old_mesh = is_any_active("sigint_meshtastic")
    old_aprs = is_any_active("sigint_aprs")
    old_viirs = is_any_active("viirs_nightlights")
    old_datacenters = is_any_active("datacenters")
    old_fishing = is_any_active("fishing_activity")
    changed = False
    for key, value in update.layers.items():
        if key in active_layers:
            if active_layers[key] != value:
                changed = True
            active_layers[key] = value
    if changed:
        bump_active_layers_version()
    new_ships = is_any_active("ships_military", "ships_cargo", "ships_civilian", "ships_passenger", "ships_tracked_yachts")
    new_mesh = is_any_active("sigint_meshtastic")
    new_aprs = is_any_active("sigint_aprs")
    new_viirs = is_any_active("viirs_nightlights")
    new_datacenters = is_any_active("datacenters")
    new_fishing = is_any_active("fishing_activity")
    if old_ships and not new_ships:
        from services.ais_stream import stop_ais_stream
        stop_ais_stream()
        logger.info("AIS stream stopped (all ship layers disabled)")
    elif not old_ships and new_ships:
        from services.ais_stream import start_ais_stream
        start_ais_stream()
        logger.info("AIS stream started (ship layer enabled)")
    from services.sigint_bridge import sigint_grid
    if old_mesh and not new_mesh:
        try:
            from services.meshtastic_mqtt_settings import mqtt_bridge_enabled
            keep_chat_running = mqtt_bridge_enabled()
        except Exception:
            keep_chat_running = False
        if keep_chat_running:
            logger.info("Meshtastic map layer disabled; MQTT bridge kept running for MeshChat")
        else:
            sigint_grid.mesh.stop()
            logger.info("Meshtastic MQTT bridge stopped (layer disabled)")
    elif not old_mesh and new_mesh:
        try:
            from services.meshtastic_mqtt_settings import mqtt_bridge_enabled
            mqtt_enabled = mqtt_bridge_enabled()
        except Exception:
            mqtt_enabled = False
        if mqtt_enabled:
            sigint_grid.mesh.start()
            logger.info("Meshtastic MQTT bridge started (layer enabled)")
        else:
            logger.info(
                "Meshtastic layer enabled; MQTT bridge remains disabled "
                "(set MESH_MQTT_ENABLED=true to participate in the public broker)"
            )
    if old_aprs and not new_aprs:
        sigint_grid.aprs.stop()
        logger.info("APRS bridge stopped (layer disabled)")
    elif not old_aprs and new_aprs:
        sigint_grid.aprs.start()
        logger.info("APRS bridge started (layer enabled)")
    if not old_viirs and new_viirs:
        _queue_viirs_change_refresh()
        logger.info("VIIRS change refresh queued (layer enabled)")
    if not old_datacenters and new_datacenters:
        from services.fetchers.infrastructure import fetch_datacenters

        fetch_datacenters()
        logger.info("Datacenters loaded (layer enabled)")
    if not old_fishing and new_fishing:
        from services.fetchers.geo import fetch_fishing_activity

        fetch_fishing_activity()
        logger.info("Fishing activity refresh queued (layer enabled)")
    return {"status": "ok"}


@router.get("/api/live-data")
@limiter.limit("120/minute")
async def live_data(request: Request):
    etag = _current_etag(prefix="live|full|")
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "no-cache"})
    from services.fetchers._store import get_latest_data_deepcopy_snapshot

    payload = get_latest_data_deepcopy_snapshot()
    return Response(
        content=_live_data_json_bytes(payload),
        media_type="application/json",
        headers={"ETag": etag, "Cache-Control": "no-cache"},
    )


@router.get("/api/bootstrap/critical")
@limiter.limit("180/minute")
async def bootstrap_critical(request: Request):
    """Cached first-paint payload for the dashboard.

    This endpoint is intentionally memory-only: no upstream calls, no refresh,
    and a bounded response. It exists so the map and threat feed can paint
    before slower panels and background enrichers finish warming up.
    """
    etag = _current_etag(prefix="bootstrap|critical|")
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "no-cache"})
    from services.fetchers._store import (
        active_layers,
        get_latest_data_subset_refs,
        get_source_timestamps_snapshot,
    )

    d = get_latest_data_subset_refs(
        "last_updated", "commercial_flights", "military_flights", "private_flights",
        "private_jets", "tracked_flights", "ships", "uavs", "liveuamap", "gps_jamming",
        "satellites", "satellite_source", "satellite_analysis", "sigint", "sigint_totals",
        "trains", "news", "gdelt", "airports", "threat_level", "trending_markets",
        "correlations", "fimi", "crowdthreat",
    )
    freshness = get_source_timestamps_snapshot()
    ships_enabled = any(active_layers.get(key, True) for key in (
        "ships_military", "ships_cargo", "ships_civilian", "ships_passenger", "ships_tracked_yachts"))
    sigint_items = _filter_sigint_by_layers(d.get("sigint") or [], active_layers)
    payload = {
        "last_updated": d.get("last_updated"),
        "commercial_flights": _cap_startup_items(
            (d.get("commercial_flights") or []) if active_layers.get("flights", True) else [],
            800,
        ),
        "military_flights": _cap_startup_items(
            (d.get("military_flights") or []) if active_layers.get("military", True) else [],
            300,
        ),
        "private_flights": _cap_startup_items(
            (d.get("private_flights") or []) if active_layers.get("private", True) else [],
            300,
        ),
        "private_jets": _cap_startup_items(
            (d.get("private_jets") or []) if active_layers.get("jets", True) else [],
            150,
        ),
        "tracked_flights": _cap_startup_items(
            (d.get("tracked_flights") or []) if active_layers.get("tracked", True) else [],
            250,
        ),
        "ships": _cap_startup_items((d.get("ships") or []) if ships_enabled else [], 1500),
        "uavs": _cap_startup_items((d.get("uavs") or []) if active_layers.get("military", True) else [], 100),
        "liveuamap": _cap_startup_items(
            (d.get("liveuamap") or []) if active_layers.get("global_incidents", True) else [],
            300,
        ),
        "gps_jamming": _cap_startup_items(
            (d.get("gps_jamming") or []) if active_layers.get("gps_jamming", True) else [],
            200,
        ),
        "satellites": _cap_startup_items(
            (d.get("satellites") or []) if active_layers.get("satellites", True) else [],
            250,
        ),
        "satellite_source": d.get("satellite_source", "none"),
        "satellite_analysis": (d.get("satellite_analysis") or {}) if active_layers.get("satellites", True) else {},
        "sigint": _cap_startup_items(
            sigint_items if (active_layers.get("sigint_meshtastic", True) or active_layers.get("sigint_aprs", True)) else [],
            500,
        ),
        "sigint_totals": _sigint_totals_for_items(sigint_items),
        "trains": _cap_startup_items((d.get("trains") or []) if active_layers.get("trains", True) else [], 100),
        "news": _cap_startup_items(d.get("news") or [], 30),
        "gdelt": _cap_startup_items((d.get("gdelt") or []) if active_layers.get("global_incidents", True) else [], 300),
        "airports": _cap_startup_items(d.get("airports") or [], 500),
        "threat_level": d.get("threat_level"),
        "trending_markets": _cap_startup_items(d.get("trending_markets") or [], 10),
        "correlations": _cap_startup_items(
            (d.get("correlations") or []) if active_layers.get("correlations", True) else [],
            50,
        ),
        "fimi": d.get("fimi"),
        "crowdthreat": _cap_startup_items(
            (d.get("crowdthreat") or []) if active_layers.get("crowdthreat", True) else [],
            150,
        ),
        "freshness": freshness,
        "bootstrap_ready": True,
        "bootstrap_payload": True,
    }
    return Response(
        content=_live_data_json_bytes(payload),
        media_type="application/json",
        headers={"ETag": etag, "Cache-Control": "no-cache"},
    )


@router.get("/api/live-data/fast")
@limiter.limit("120/minute")
async def live_data_fast(
    request: Request,
    s: float = Query(None, description="South bound — when all four bounds are supplied, heavy/dense layers (vessels, aircraft, sigint, CCTV, …) are filtered to this viewport with 20% padding. Static reference layers (satellites, etc.) always ship world-scale.", ge=-90, le=90),
    w: float = Query(None, description="West bound (see s)", ge=-180, le=180),
    n: float = Query(None, description="North bound (see s)", ge=-90, le=90),
    e: float = Query(None, description="East bound (see s)", ge=-180, le=180),
    initial: bool = Query(False, description="Return a capped startup payload for first paint"),
):
    bbox_suffix = _bbox_etag_suffix(s, w, n, e)
    etag = _current_etag(prefix=("fast|initial|" if initial else "fast|full|") + bbox_suffix.lstrip("|") + ("|" if bbox_suffix else ""))
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "no-cache"})
    from services.fetchers._store import (active_layers, get_latest_data_subset_refs, get_source_timestamps_snapshot)
    d = get_latest_data_subset_refs(
        "last_updated", "commercial_flights", "military_flights", "private_flights",
        "private_jets", "tracked_flights", "ships", "cctv", "uavs", "liveuamap",
        "gps_jamming", "satellites", "satellite_source", "satellite_analysis",
        "sigint", "sigint_totals", "trains",
    )
    freshness = get_source_timestamps_snapshot()
    ships_enabled = any(active_layers.get(key, True) for key in (
        "ships_military", "ships_cargo", "ships_civilian", "ships_passenger", "ships_tracked_yachts"))
    cctv_total = len(d.get("cctv") or [])
    sigint_items = _filter_sigint_by_layers(d.get("sigint") or [], active_layers)
    sigint_totals = _sigint_totals_for_items(sigint_items)
    payload = {
        "commercial_flights": (d.get("commercial_flights") or []) if active_layers.get("flights", True) else [],
        "military_flights": (d.get("military_flights") or []) if active_layers.get("military", True) else [],
        "private_flights": (d.get("private_flights") or []) if active_layers.get("private", True) else [],
        "private_jets": (d.get("private_jets") or []) if active_layers.get("jets", True) else [],
        "tracked_flights": (d.get("tracked_flights") or []) if active_layers.get("tracked", True) else [],
        "ships": (d.get("ships") or []) if ships_enabled else [],
        "cctv": (d.get("cctv") or []) if active_layers.get("cctv", True) else [],
        "uavs": (d.get("uavs") or []) if active_layers.get("military", True) else [],
        "liveuamap": (d.get("liveuamap") or []) if active_layers.get("global_incidents", True) else [],
        "gps_jamming": (d.get("gps_jamming") or []) if active_layers.get("gps_jamming", True) else [],
        "satellites": (d.get("satellites") or []) if active_layers.get("satellites", True) else [],
        "satellite_source": d.get("satellite_source", "none"),
        "satellite_analysis": (d.get("satellite_analysis") or {}) if active_layers.get("satellites", True) else {},
        "sigint": sigint_items if (active_layers.get("sigint_meshtastic", True) or active_layers.get("sigint_aprs", True)) else [],
        "sigint_totals": sigint_totals,
        "cctv_total": cctv_total,
        "trains": (d.get("trains") or []) if active_layers.get("trains", True) else [],
        "freshness": freshness,
    }
    if initial:
        payload = _cap_fast_startup_payload(payload)
    else:
        payload = _cap_fast_dashboard_payload(payload)
    # Issue #288: bbox filter heavy/dense layers only when all four bounds
    # are supplied. Without bounds, behaviour is byte-for-byte identical
    # to the pre-#288 implementation.
    if _has_full_bbox(s, w, n, e):
        payload = _apply_bbox_to_payload(payload, _FAST_BBOX_HEAVY_KEYS, s, w, n, e)
    return Response(
        content=_live_data_json_bytes(payload),
        media_type="application/json",
        headers={"ETag": etag, "Cache-Control": "no-cache"},
    )


@router.get("/api/live-data/slow")
@limiter.limit("60/minute")
async def live_data_slow(
    request: Request,
    s: float = Query(None, description="South bound — when all four bounds are supplied, heavy/dense layers (gdelt, firms_fires, kiwisdr, scanners, psk_reporter) are filtered to this viewport with 20% padding. Static reference layers (datacenters, military bases, power plants, weather, news, …) always ship world-scale.", ge=-90, le=90),
    w: float = Query(None, description="West bound (see s)", ge=-180, le=180),
    n: float = Query(None, description="North bound (see s)", ge=-90, le=90),
    e: float = Query(None, description="East bound (see s)", ge=-180, le=180),
):
    bbox_suffix = _bbox_etag_suffix(s, w, n, e)
    etag = _current_etag(prefix="slow|full|" + bbox_suffix.lstrip("|") + ("|" if bbox_suffix else ""))
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "no-cache"})
    from services.fetchers._store import (active_layers, get_latest_data_subset_refs, get_source_timestamps_snapshot)
    d = get_latest_data_subset_refs(
        "last_updated", "news", "stocks", "financial_source", "oil", "weather", "traffic",
        "earthquakes", "frontlines", "gdelt", "airports", "kiwisdr", "satnogs_stations",
        "satnogs_observations", "tinygs_satellites", "space_weather", "internet_outages",
        "firms_fires", "datacenters", "military_bases", "power_plants", "viirs_change_nodes",
        "scanners", "weather_alerts", "ukraine_alerts", "air_quality", "volcanoes",
        "fishing_activity", "psk_reporter", "correlations", "uap_sightings", "wastewater",
        "crowdthreat", "threat_level", "trending_markets", "road_corridor_trends",
        "malware_threats", "cyber_threats", "scm_suppliers", "telegram_osint", "gt_risk",
    )
    freshness = get_source_timestamps_snapshot()
    payload = {
        "last_updated": d.get("last_updated"),
        "threat_level": d.get("threat_level"),
        "trending_markets": d.get("trending_markets", []),
        "news": d.get("news", []),
        "stocks": d.get("stocks", {}),
        "financial_source": d.get("financial_source", ""),
        "oil": d.get("oil", {}),
        "weather": d.get("weather"),
        "traffic": d.get("traffic", []),
        "earthquakes": (d.get("earthquakes") or []) if active_layers.get("earthquakes", True) else [],
        "frontlines": d.get("frontlines") if active_layers.get("ukraine_frontline", True) else None,
        "gdelt": (d.get("gdelt") or []) if active_layers.get("global_incidents", True) else [],
        "airports": d.get("airports") or [],
        "kiwisdr": (d.get("kiwisdr") or []) if active_layers.get("kiwisdr", True) else [],
        "satnogs_stations": (d.get("satnogs_stations") or []) if active_layers.get("satnogs", True) else [],
        "satnogs_total": len(d.get("satnogs_stations") or []),
        "satnogs_observations": (d.get("satnogs_observations") or []) if active_layers.get("satnogs", True) else [],
        "tinygs_satellites": (d.get("tinygs_satellites") or []) if active_layers.get("tinygs", True) else [],
        "tinygs_total": len(d.get("tinygs_satellites") or []),
        "psk_reporter": (d.get("psk_reporter") or []) if active_layers.get("psk_reporter", True) else [],
        "space_weather": d.get("space_weather"),
        "internet_outages": (d.get("internet_outages") or []) if active_layers.get("internet_outages", True) else [],
        "firms_fires": (d.get("firms_fires") or []) if active_layers.get("firms", True) else [],
        "datacenters": (d.get("datacenters") or []) if active_layers.get("datacenters", True) else [],
        "military_bases": (d.get("military_bases") or []) if active_layers.get("military_bases", True) else [],
        "power_plants": (d.get("power_plants") or []) if active_layers.get("power_plants", True) else [],
        "viirs_change_nodes": (d.get("viirs_change_nodes") or []) if active_layers.get("viirs_nightlights", True) else [],
        "scanners": (d.get("scanners") or []) if active_layers.get("scanners", True) else [],
        "weather_alerts": d.get("weather_alerts", []) if active_layers.get("weather_alerts", True) else [],
        "ukraine_alerts": d.get("ukraine_alerts", []) if active_layers.get("ukraine_alerts", True) else [],
        "air_quality": (d.get("air_quality") or []) if active_layers.get("air_quality", True) else [],
        "volcanoes": (d.get("volcanoes") or []) if active_layers.get("volcanoes", True) else [],
        "fishing_activity": (d.get("fishing_activity") or []) if active_layers.get("fishing_activity", True) else [],
        "correlations": (d.get("correlations") or []) if active_layers.get("correlations", True) else [],
        "uap_sightings": (d.get("uap_sightings") or []) if active_layers.get("uap_sightings", True) else [],
        "wastewater": (d.get("wastewater") or []) if active_layers.get("wastewater", True) else [],
        "crowdthreat": (d.get("crowdthreat") or []) if active_layers.get("crowdthreat", True) else [],
        "road_corridor_trends": (
            d.get("road_corridor_trends") or {"updated_at": None, "corridors": []}
        )
        if active_layers.get("road_corridor_trends", False)
        else {"updated_at": None, "corridors": []},
        "malware_threats": (
            d.get("malware_threats") or {"threats": [], "total": 0}
        )
        if active_layers.get("malware_c2", False)
        else {"threats": [], "total": 0},
        "cyber_threats": (
            d.get("cyber_threats") or {"threats": [], "stats": {}}
        )
        if active_layers.get("cyber_threats", False)
        else {"threats": [], "stats": {}},
        "scm_suppliers": (
            d.get("scm_suppliers") or {"suppliers": [], "total": 0, "critical_count": 0}
        )
        if active_layers.get("scm_suppliers", False)
        else {"suppliers": [], "total": 0, "critical_count": 0},
        "telegram_osint": (
            d.get("telegram_osint") or {"posts": [], "total": 0, "geolocated": 0}
        )
        if active_layers.get("telegram_osint", True)
        else {"posts": [], "total": 0, "geolocated": 0},
        "gt_risk": (
            d.get("gt_risk")
            or {"enabled": False, "heatmap": {"type": "FeatureCollection", "features": []}, "clusters": []}
        )
        if active_layers.get("gt_risk", False)
        else {"enabled": False, "heatmap": {"type": "FeatureCollection", "features": []}, "clusters": []},
        "freshness": freshness,
    }
    # Issue #288: bbox filter heavy/dense layers only when all four bounds
    # are supplied. Static reference layers (datacenters, military bases,
    # power_plants, etc.) deliberately stay world-scale so panning never
    # hides the infrastructure overlay the operator already has on screen.
    if _has_full_bbox(s, w, n, e):
        payload = _apply_bbox_to_payload(payload, _SLOW_BBOX_HEAVY_KEYS, s, w, n, e)
    return Response(
        content=_live_data_json_bytes(payload),
        media_type="application/json",
        headers={"ETag": etag, "Cache-Control": "no-cache"},
    )


# ── Satellite Overflight Counting ───────────────────────────────────────────
# Counts unique satellites whose ground track entered a bounding box over 24h.
# Uses cached TLEs + SGP4 propagation — no extra network requests.

class OverflightRequest(BaseModel):
    s: float
    w: float
    n: float
    e: float
    hours: int = 24


# Issue #202: compute_overflights() is O(catalog_size × timesteps), where
# timesteps grows linearly with `hours`. An unbounded `hours` value is a
# trivial CPU-exhaustion vector. We clamp silently rather than raising 422 —
# the response shape is unchanged, callers asking for too many hours just
# get a shorter window, which is friendlier than a hostile error.
#
# Override via OVERFLIGHTS_MAX_HOURS env var if you legitimately need a
# longer window (e.g. a planning use case that wants a full week).
def _overflight_max_hours() -> int:
    import os as _os
    try:
        raw = int(str(_os.environ.get("OVERFLIGHTS_MAX_HOURS", "72")).strip())
    except (TypeError, ValueError):
        raw = 72
    return max(1, raw)


@router.post("/api/satellites/overflights")
@limiter.limit("10/minute")
async def satellite_overflights(request: Request, body: OverflightRequest):
    from services.fetchers.satellites import compute_overflights, _sat_gp_cache
    gp_data = _sat_gp_cache.get("data")
    if not gp_data:
        return JSONResponse({"total": 0, "by_mission": {}, "satellites": [], "error": "No GP data cached yet"})
    bbox = {"s": body.s, "w": body.w, "n": body.n, "e": body.e}

    # Silent clamp — see comment on _overflight_max_hours().
    requested_hours = max(1, int(body.hours or 0))
    effective_hours = min(requested_hours, _overflight_max_hours())

    result = compute_overflights(gp_data, bbox, hours=effective_hours)
    # If we clamped, surface the effective window in the response so the
    # caller can detect it if they care, without it being an error.
    if isinstance(result, dict) and effective_hours != requested_hours:
        result.setdefault("requested_hours", requested_hours)
        result.setdefault("effective_hours", effective_hours)
    return JSONResponse(result)
