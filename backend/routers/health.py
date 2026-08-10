import time as _time_mod
from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from limiter import limiter
from auth import require_admin
from services.schemas import HealthResponse
import os

# Health/SLO probes only need counts + freshness — not a full dashboard deepcopy.
_HEALTH_DATA_KEYS: tuple[str, ...] = (
    "last_updated",
    "commercial_flights",
    "military_flights",
    "private_jets",
    "ships",
    "satellites",
    "earthquakes",
    "cctv",
    "news",
    "uavs",
    "firms_fires",
    "liveuamap",
    "gdelt",
    "uap_sightings",
    "wastewater",
    "fimi",
    "space_weather",
    "weather_alerts",
    "volcanoes",
    "prediction_markets",
)


def _health_data_snapshot() -> dict:
    from services.fetchers._store import get_latest_data_subset_refs
    from services.slo import SLO_REGISTRY

    keys = tuple(dict.fromkeys((*_HEALTH_DATA_KEYS, *SLO_REGISTRY.keys())))
    return get_latest_data_subset_refs(*keys)


def _health_row_count(value) -> int:
    if value is None:
        return 0
    try:
        return len(value)
    except TypeError:
        return 0

APP_VERSION = os.environ.get("_HEALTH_APP_VERSION", "0.9.82")

router = APIRouter()


def _get_app_version() -> str:
    # Import lazily to avoid circular import; main sets APP_VERSION before including routers
    try:
        import main as _main
        return _main.APP_VERSION
    except Exception:
        return APP_VERSION


_start_time_ref: dict = {"value": None}


def _get_start_time() -> float:
    if _start_time_ref["value"] is None:
        try:
            import main as _main
            _start_time_ref["value"] = _main._start_time
        except Exception:
            _start_time_ref["value"] = _time_mod.time()
    return _start_time_ref["value"]


@router.get("/api/health", response_model=HealthResponse)
@limiter.limit("30/minute")
async def health_check(request: Request):
    from services.fetchers._store import get_source_timestamps_snapshot
    from services.slo import compute_all_statuses, summarise_statuses

    d = _health_data_snapshot()
    last = d.get("last_updated")
    timestamps = get_source_timestamps_snapshot()
    slo_statuses = compute_all_statuses(d, timestamps)
    slo_summary = summarise_statuses(slo_statuses)
    # Top-level status reflects worst SLO result — "degraded" if any
    # yellow, "error" if any red, "ok" otherwise. This is the single
    # field an external probe / pager can watch.
    top_status = "ok"
    if slo_summary.get("red", 0) > 0:
        top_status = "error"
    elif slo_summary.get("yellow", 0) > 0:
        top_status = "degraded"

    # Issue #258: surface AIS proxy degraded TLS state so operators can see
    # when the SPKI-pinned fallback is in effect. The data plane keeps
    # flowing (this is by design — see ais_proxy.js comments) but observers
    # who care about MITM-protection posture deserve a visible signal.
    #
    # Plus connectivity health (added 2026-05-23 when stream.aisstream.io
    # went fully offline): ``connected`` tells the frontend whether ship
    # data is actually flowing. When false, a banner explains that ships
    # are unavailable due to an upstream outage — better than the user
    # silently seeing an empty ocean and assuming we broke something.
    ais_status: dict = {}
    try:
        from services.ais_stream import ais_proxy_status
        ais_status = ais_proxy_status() or {}
    except Exception:
        ais_status = {}
    try:
        from services.fetchers.aishub_fallback import aishub_fallback_enabled

        ais_status["aishub_configured"] = bool(aishub_fallback_enabled())
    except Exception:
        ais_status["aishub_configured"] = bool(str(os.environ.get("AISHUB_USERNAME", "") or "").strip())
    if ais_status.get("degraded_tls") and top_status == "ok":
        # Don't override a worse top-level status if SLOs already failed,
        # but escalate ok -> degraded so the field surfaces in dashboards.
        top_status = "degraded"
    # AIS_API_KEY not configured is "feature off", not "system broken" —
    # so we only escalate when the operator opted into AIS (key set) AND
    # the stream is currently offline.
    if (
        os.environ.get("AIS_API_KEY")
        and ais_status.get("connected") is False
        and top_status == "ok"
    ):
        top_status = "degraded"

    runtime: dict = {}
    try:
        from services.runtime_profile import get_runtime_profile
        from analytics.settings import gt_analytics_status

        runtime = {
            **get_runtime_profile(),
            "gt_analytics": gt_analytics_status(),
        }
    except Exception:
        runtime = {}

    return {
        "status": top_status,
        "version": _get_app_version(),
        "last_updated": last,
        "sources": {
            "flights": _health_row_count(d.get("commercial_flights")),
            "military": _health_row_count(d.get("military_flights")),
            "ships": _health_row_count(d.get("ships")),
            "satellites": _health_row_count(d.get("satellites")),
            "earthquakes": _health_row_count(d.get("earthquakes")),
            "cctv": _health_row_count(d.get("cctv")),
            "news": _health_row_count(d.get("news")),
            "uavs": _health_row_count(d.get("uavs")),
            "firms_fires": _health_row_count(d.get("firms_fires")),
            "liveuamap": _health_row_count(d.get("liveuamap")),
            "gdelt": _health_row_count(d.get("gdelt")),
            "uap_sightings": _health_row_count(d.get("uap_sightings")),
        },
        "freshness": timestamps,
        "uptime_seconds": round(_time_mod.time() - _get_start_time()),
        "slo": slo_statuses,
        "slo_summary": slo_summary,
        "ais_proxy": ais_status,
        "runtime": runtime or None,
    }


@router.get("/api/debug-latest", dependencies=[Depends(require_admin)])
@limiter.limit("30/minute")
async def debug_latest_data(request: Request):
    from services.fetchers._store import latest_data, _data_lock

    with _data_lock:
        return list(latest_data.keys())
