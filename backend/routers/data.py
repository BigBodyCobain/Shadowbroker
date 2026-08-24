import asyncio
import logging
import math
import os
import threading
from collections import OrderedDict
from collections.abc import Callable
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

# ETag → serialized live-data body. Natural invalidation via etag change.
_LIVE_DATA_BYTES_CACHE_MAX = 32
_LIVE_DATA_BYTES_CACHE: OrderedDict[str, bytes] = OrderedDict()
_LIVE_DATA_BYTES_CACHE_LOCK = threading.Lock()


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
    """Bbox no longer scopes payloads — keep a single world ETag cache key."""
    return ""


def _apply_bbox_to_payload(payload: dict, heavy_keys: tuple[str, ...],
                            s: float, w: float, n: float, e: float) -> dict:
    """No-op: live telemetry is never viewport-truncated.

    Bounds may still be accepted on the wire for client hints / future use,
    but we do not drop ships, aircraft, or other dense layers by map window.
    """
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


def _cached_live_data_bytes(etag: str, build_payload_fn: Callable[[], dict]) -> bytes:
    """Return orjson bytes for etag, building+serializing only on cache miss.

    Cache key is the full ETag string (includes version/bbox/prefix), so a
    store version bump naturally misses without explicit invalidation.
    """
    with _LIVE_DATA_BYTES_CACHE_LOCK:
        cached = _LIVE_DATA_BYTES_CACHE.get(etag)
        if cached is not None:
            _LIVE_DATA_BYTES_CACHE.move_to_end(etag)
            return cached

    body = _live_data_json_bytes(build_payload_fn())

    with _LIVE_DATA_BYTES_CACHE_LOCK:
        _LIVE_DATA_BYTES_CACHE[etag] = body
        _LIVE_DATA_BYTES_CACHE.move_to_end(etag)
        while len(_LIVE_DATA_BYTES_CACHE) > _LIVE_DATA_BYTES_CACHE_MAX:
            _LIVE_DATA_BYTES_CACHE.popitem(last=False)
    return body


def _item_lng(item: dict, lng_key: str = "lng"):
    """Prefer ``lng``; fall back to ``lon`` (CCTV / KiwiSDR / PSK use lon)."""
    lng = item.get(lng_key)
    if lng is not None:
        return lng
    if lng_key != "lon":
        return item.get("lon")
    return item.get("lng")


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
        lng = _item_lng(item, lng_key)
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


def _sample_items(items: list | None, max_items: int) -> list:
    """Evenly spaced sample — stable across polls for the same store order."""
    if not items:
        return []
    n = len(items)
    if n <= max_items:
        return items
    # Deterministic stride so ETag byte cache stays coherent for a given version.
    step = n / max_items
    return [items[int(i * step)] for i in range(max_items)]


def _cap_fast_startup_payload(payload: dict) -> dict:
    """Mark first-paint payloads. Do not defer or sample live telemetry."""
    capped = dict(payload)
    capped["startup_payload"] = True
    return capped


def _world_and_continental_scale(has_bbox: bool, s, w, n, e) -> tuple:
    lat_span, lng_span = _bbox_spans(s, w, n, e)
    world_scale = (not has_bbox) or lng_span >= 300 or lat_span >= 120
    continental_scale = has_bbox and not world_scale and (lng_span >= 120 or lat_span >= 55)
    return world_scale, continental_scale


def _cap_fast_dashboard_payload(payload: dict, *, s=None, w=None, n=None, e=None) -> dict:
    """Annotate zoom scale only — never sample/drop live telemetry rows.

    Regional density comes from #288 bbox filtering (what's in view), not from
    picking a random subset of the planet.
    """
    has_bbox = _has_full_bbox(s, w, n, e)
    world_scale, continental_scale = _world_and_continental_scale(has_bbox, s, w, n, e)
    if world_scale:
        payload["payload_scale"] = "world"
    elif continental_scale:
        payload["payload_scale"] = "continental"
    else:
        payload["payload_scale"] = "regional"
    return payload


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


@router.get("/api/aviation/datalink/status")
@limiter.limit("60/minute")
async def aviation_datalink_status(request: Request):  # noqa: ARG001
    from services.fetchers.airframes import get_datalink_status

    return get_datalink_status()


@router.get("/api/aviation/datalink/messages")
@limiter.limit("240/minute")
async def aviation_datalink_messages(
    request: Request,  # noqa: ARG001
    icao24: str = Query("", description="ICAO24 hex for the aircraft"),
    registration: str = Query("", description="Tail / registration number"),
    callsign: str = Query("", description="Optional callsign filter"),
    live: bool = Query(
        False,
        description="When true, fetch from Airframes if cache has no messages (slower)",
    ),
):
    from services.fetchers.airframes import lookup_datalink_messages

    return lookup_datalink_messages(
        icao24=icao24,
        registration=registration,
        callsign=callsign,
        allow_live=live,
    )


@router.get("/api/sigint/meshtastic/status")
@limiter.limit("120/minute")
async def meshtastic_map_status(request: Request):  # noqa: ARG001
    from services.fetchers.meshtastic_map import get_meshtastic_map_status

    return get_meshtastic_map_status()


@router.post("/api/sigint/meshtastic/scan", dependencies=[Depends(require_local_operator)])
@limiter.limit("3/hour")
async def meshtastic_planet_scan(request: Request):  # noqa: ARG001
    from services.fetchers.meshtastic_map import start_meshtastic_planet_scan

    return start_meshtastic_planet_scan()


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


@router.get("/api/layers", dependencies=[Depends(require_local_operator)])
async def get_layers(request: Request):
    """Report operator layer state plus any live overrides.

    The UI polls this so the DATA LAYERS toggles can show an overlay that an
    agent switched on. ``layers`` is the operator's own state and is what the
    browser persists; ``overrides`` is transient and must not be saved.
    """
    from services.fetchers._store import active_layers, get_layer_overrides
    return {"layers": dict(active_layers), "overrides": get_layer_overrides()}


@router.post("/api/layers", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def update_layers(update: LayerUpdate, request: Request):
    """Receive frontend layer toggle state. Starts/stops streams accordingly."""
    from services.fetchers._store import active_layers, bump_active_layers_version, is_any_active
    from services.layer_enable_refresh import refresh_newly_enabled_layers, snapshot_active_layers

    layers_before = snapshot_active_layers()
    old_ships = is_any_active("ships_military", "ships_cargo", "ships_civilian", "ships_passenger", "ships_tracked_yachts")
    old_mesh = is_any_active("sigint_meshtastic")
    old_aprs = is_any_active("sigint_aprs")
    old_viirs = is_any_active("viirs_nightlights")
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
    if old_ships and not new_ships:
        from services.ais_stream import stop_ais_stream
        stop_ais_stream()
        logger.info("AIS stream stopped (all ship layers disabled)")
    elif not old_ships and new_ships:
        from services.ais_stream import start_ais_stream
        start_ais_stream()
        logger.info("AIS stream started (ship layer enabled)")
    from services.sigint_bridge import sigint_grid
    from services.aprs_is_bridge import aprs_is_bridge
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
        # #533/#534: never start or stop the legacy SIGINTGrid APRS client.
        # It used an unbounded public APRS-IS filter. The replacement bridge
        # validates bounded operator configuration and fails closed.
        aprs_is_bridge.reconcile(False)
        logger.info("Bounded APRS-IS bridge stopped (layer disabled)")
    elif not old_aprs and new_aprs:
        aprs_is_bridge.reconcile(True)
        logger.info("Bounded APRS-IS bridge reconciled (layer enabled)")
    if not old_viirs and new_viirs:
        _queue_viirs_change_refresh()
        logger.info("VIIRS change refresh queued (layer enabled)")
    if old_mesh != new_mesh or old_aprs != new_aprs:
        # Publish a single merged snapshot immediately so enabling both radio
        # layers behaves like one "scan all" action while the bridges continue
        # receiving independently in their own bounded lifecycles.
        from services.fetchers.sigint import fetch_sigint

        threading.Thread(target=fetch_sigint, daemon=True, name="sigint-layer-refresh").start()
    refresh_newly_enabled_layers(layers_before)
    return {"status": "ok"}


@router.get("/api/live-data")
@limiter.limit("120/minute")
async def live_data(request: Request):
    etag = _current_etag(prefix="live|full|")
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "no-cache"})
    from services.fetchers._store import get_latest_data_refs_snapshot

    def _build() -> dict:
        return get_latest_data_refs_snapshot()

    return Response(
        content=_cached_live_data_bytes(etag, _build),
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
        effective_layers,
        get_latest_data_subset_refs,
        get_source_timestamps_snapshot,
    )

    # Rebind the local name to the override-merged map. Every layer filter
    # below reads this name, so one merge here covers all of them.
    active_layers = effective_layers()

    def _build() -> dict:
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
        return {
            "last_updated": d.get("last_updated"),
            "commercial_flights": (d.get("commercial_flights") or []) if active_layers.get("flights", True) else [],
            "military_flights": (d.get("military_flights") or []) if active_layers.get("military", True) else [],
            "private_flights": (d.get("private_flights") or []) if active_layers.get("private", True) else [],
            "private_jets": (d.get("private_jets") or []) if active_layers.get("jets", True) else [],
            "tracked_flights": (d.get("tracked_flights") or []) if active_layers.get("tracked", True) else [],
            "ships": (d.get("ships") or []) if ships_enabled else [],
            "uavs": (d.get("uavs") or []) if active_layers.get("military", True) else [],
            "liveuamap": (d.get("liveuamap") or []) if active_layers.get("global_incidents", True) else [],
            "gps_jamming": (d.get("gps_jamming") or []) if active_layers.get("gps_jamming", True) else [],
            "satellites": (d.get("satellites") or []) if active_layers.get("satellites", True) else [],
            "satellite_source": d.get("satellite_source", "none"),
            "satellite_analysis": (d.get("satellite_analysis") or {}) if active_layers.get("satellites", True) else {},
            "sigint": sigint_items if (active_layers.get("sigint_meshtastic", True) or active_layers.get("sigint_aprs", True)) else [],
            "sigint_totals": _sigint_totals_for_items(sigint_items),
            "trains": (d.get("trains") or []) if active_layers.get("trains", True) else [],
            "news": d.get("news") or [],
            "gdelt": (d.get("gdelt") or []) if active_layers.get("global_incidents", True) else [],
            "airports": d.get("airports") or [],
            "threat_level": d.get("threat_level"),
            "trending_markets": d.get("trending_markets") or [],
            "correlations": (d.get("correlations") or []) if active_layers.get("correlations", True) else [],
            "fimi": d.get("fimi"),
            "crowdthreat": (d.get("crowdthreat") or []) if active_layers.get("crowdthreat", True) else [],
            "freshness": freshness,
            "bootstrap_ready": True,
            "bootstrap_payload": True,
        }

    return Response(
        content=_cached_live_data_bytes(etag, _build),
        media_type="application/json",
        headers={"ETag": etag, "Cache-Control": "no-cache"},
    )


_DELTA_FAST_KEYS: tuple[str, ...] = (
    "ships",
    "commercial_flights",
    "military_flights",
    "tracked_flights",
    "private_flights",
    "private_jets",
)


def _parse_layer_versions(raw: str | None) -> dict[str, int] | None:
    """Parse ``ships:3,commercial_flights:5`` into a dict. Empty/invalid → None."""
    if not raw or not str(raw).strip():
        return None
    out: dict[str, int] = {}
    for part in str(raw).split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        key, _, ver = part.partition(":")
        key = key.strip()
        try:
            out[key] = int(ver.strip())
        except (TypeError, ValueError):
            continue
    return out or None


def _attach_version_meta(payload: dict) -> dict:
    from services.fetchers._store import get_data_version, get_layer_versions

    payload["mode"] = payload.get("mode") or "snapshot"
    payload["store_version"] = get_data_version()
    payload["layer_versions"] = get_layer_versions()
    return payload


def _try_build_fast_delta(
    client_lv: dict[str, int],
    *,
    s=None,
    w=None,
    n=None,
    e=None,
) -> dict | None:
    """Return a delta payload, or None to fall back to a full snapshot."""
    from services.fetchers._store import (
        compute_layer_row_delta,
        effective_layers,
        get_data_version,
        get_layer_versions,
        get_latest_data_subset_refs,
        get_source_timestamps_snapshot,
    )

    # Rebind the local name to the override-merged map (see bootstrap_critical).
    active_layers = effective_layers()

    server_lv = get_layer_versions()
    deltas: dict[str, Any] = {}
    for key in _DELTA_FAST_KEYS:
        since = client_lv.get(key)
        if since is None:
            # Client never saw this layer — force full snapshot recovery.
            return None
        patch = compute_layer_row_delta(key, since)
        if patch is None:
            return None
        if not patch.get("unchanged"):
            deltas[key] = {
                "upsert": list(patch.get("upsert") or []),
                "delete": list(patch.get("delete") or []),
                "version": patch.get("version", server_lv.get(key, 0)),
            }

    # Non-delta fast keys: include full array only when the layer version advanced.
    non_delta_keys = (
        "cctv",
        "uavs",
        "liveuamap",
        "gps_jamming",
        "satellites",
        "satellite_analysis",
        "sigint",
        "trains",
    )
    d = get_latest_data_subset_refs(*non_delta_keys, "satellite_source", "sigint_totals")
    full_layers: dict[str, Any] = {}
    for key in non_delta_keys:
        client_ver = client_lv.get(key)
        server_ver = int(server_lv.get(key, 0) or 0)
        if client_ver is not None and int(client_ver) >= server_ver:
            continue
        if key == "cctv":
            full_layers[key] = (d.get("cctv") or []) if active_layers.get("cctv", True) else []
        elif key == "uavs":
            full_layers[key] = (d.get("uavs") or []) if active_layers.get("military", True) else []
        elif key == "liveuamap":
            full_layers[key] = (d.get("liveuamap") or []) if active_layers.get("global_incidents", True) else []
        elif key == "gps_jamming":
            full_layers[key] = (d.get("gps_jamming") or []) if active_layers.get("gps_jamming", True) else []
        elif key == "satellites":
            full_layers[key] = (d.get("satellites") or []) if active_layers.get("satellites", True) else []
            full_layers["satellite_source"] = d.get("satellite_source", "none")
            full_layers["satellite_analysis"] = (
                (d.get("satellite_analysis") or {}) if active_layers.get("satellites", True) else {}
            )
        elif key == "sigint":
            items = _filter_sigint_by_layers(d.get("sigint") or [], active_layers)
            full_layers[key] = (
                items
                if (active_layers.get("sigint_meshtastic", True) or active_layers.get("sigint_aprs", True))
                else []
            )
            full_layers["sigint_totals"] = _sigint_totals_for_items(items)
        elif key == "trains":
            full_layers[key] = (d.get("trains") or []) if active_layers.get("trains", True) else []

    if full_layers and _has_full_bbox(s, w, n, e):
        _apply_bbox_to_payload(full_layers, _FAST_BBOX_HEAVY_KEYS, s, w, n, e)

    return {
        "mode": "delta",
        "store_version": get_data_version(),
        "layer_versions": server_lv,
        "deltas": deltas,
        "layers": full_layers,
        "freshness": get_source_timestamps_snapshot(),
        "cctv_total": len((d.get("cctv") or [])),
    }


@router.get("/api/live-data/fast")
@limiter.limit("120/minute")
async def live_data_fast(
    request: Request,
    s: float = Query(None, description="South bound — when all four bounds are supplied, heavy/dense layers (vessels, aircraft, sigint, CCTV, …) are filtered to this viewport with 20% padding. Static reference layers (satellites, etc.) always ship world-scale.", ge=-90, le=90),
    w: float = Query(None, description="West bound (see s)", ge=-180, le=180),
    n: float = Query(None, description="North bound (see s)", ge=-90, le=90),
    e: float = Query(None, description="East bound (see s)", ge=-180, le=180),
    initial: bool = Query(False, description="Return a capped startup payload for first paint"),
    lv: str = Query(
        None,
        description="Optional per-layer versions for delta mode, e.g. ships:3,commercial_flights:5. "
        "When provided and recoverable, response is mode=delta (upsert/delete). "
        "On skew/miss, falls back to a full snapshot.",
    ),
):
    bbox_suffix = _bbox_etag_suffix(s, w, n, e)
    client_lv = None if initial else _parse_layer_versions(lv)
    want_delta = client_lv is not None

    if want_delta:
        delta_payload = _try_build_fast_delta(client_lv, s=s, w=w, n=n, e=e)
        if delta_payload is not None:
            # Tiny unchanged delta → 304 when ETag matches store version alone.
            etag = _current_etag(
                prefix="fast|delta|" + bbox_suffix.lstrip("|") + ("|" if bbox_suffix else "")
            )
            if (
                not delta_payload.get("deltas")
                and not delta_payload.get("layers")
                and request.headers.get("if-none-match") == etag
            ):
                return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "no-cache"})
            body = _live_data_json_bytes(delta_payload)
            return Response(
                content=body,
                media_type="application/json",
                headers={"ETag": etag, "Cache-Control": "no-cache", "X-SB-Mode": "delta"},
            )

    etag = _current_etag(prefix=("fast|initial|" if initial else "fast|full|") + bbox_suffix.lstrip("|") + ("|" if bbox_suffix else ""))
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "no-cache"})
    from services.fetchers._store import (effective_layers, get_latest_data_subset_refs, get_source_timestamps_snapshot)

    # Rebind the local name to the override-merged map (see bootstrap_critical).
    active_layers = effective_layers()

    def _build() -> dict:
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
            # Issue #288: bbox densify first so world/continental caps sample
            # the *visible* set, not a random world subset then clip.
            if _has_full_bbox(s, w, n, e):
                payload = _apply_bbox_to_payload(payload, _FAST_BBOX_HEAVY_KEYS, s, w, n, e)
            payload = _cap_fast_dashboard_payload(payload, s=s, w=w, n=n, e=e)
        return _attach_version_meta(payload)

    return Response(
        content=_cached_live_data_bytes(etag, _build),
        media_type="application/json",
        headers={"ETag": etag, "Cache-Control": "no-cache", "X-SB-Mode": "snapshot"},
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
    from services.fetchers._store import (effective_layers, get_latest_data_subset_refs, get_source_timestamps_snapshot)

    # Rebind the local name to the override-merged map (see bootstrap_critical).
    active_layers = effective_layers()

    def _build() -> dict:
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
        return payload

    return Response(
        content=_cached_live_data_bytes(etag, _build),
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
