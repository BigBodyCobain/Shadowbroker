import time as _time_mod
from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from limiter import limiter
from auth import require_admin
from services.data_fetcher import get_latest_data
from services.schemas import HealthResponse
import os

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
        "ais_proxy": ais_status,
        "runtime": runtime or None,
    }


@router.get("/api/debug-latest", dependencies=[Depends(require_admin)])
@limiter.limit("30/minute")
async def debug_latest_data(request: Request):
    return list(get_latest_data().keys())
