import time as _time_mod
from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from limiter import limiter
from auth import require_admin
from services.data_fetcher import get_latest_data
from services.schemas import HealthResponse
import os

APP_VERSION = os.environ.get("_HEALTH_APP_VERSION", "0.9.7")

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

    d = get_latest_data()
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
    return {
        "status": top_status,
        "version": _get_app_version(),
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
            "uap_sightings": len(d.get("uap_sightings", [])),
        },
        "freshness": timestamps,
        "uptime_seconds": round(_time_mod.time() - _get_start_time()),
        "slo": slo_statuses,
        "slo_summary": slo_summary,
    }


@router.get("/api/debug-latest", dependencies=[Depends(require_admin)])
@limiter.limit("30/minute")
async def debug_latest_data(request: Request):
    return list(get_latest_data().keys())
