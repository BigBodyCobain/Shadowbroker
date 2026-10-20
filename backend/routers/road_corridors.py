"""Road corridor Sentinel-2 freight trend endpoints (opt-in slow layer)."""

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from limiter import limiter
from services.road_corridor_sat.config import optional_deps_available, road_corridor_sat_enabled
from services.road_corridor_sat.credentials import sentinel_credentials_configured
from services.road_corridor_sat.jobs import enqueue_analyze, get_job, get_latest_job, job_to_dict
from services.road_corridor_sat.presets import CORRIDOR_PRESETS, get_preset
from services.road_corridor_sat.storage import build_trends_payload, preset_metadata

router = APIRouter()


def _status_payload() -> dict:
    latest = get_latest_job()
    return {
        "enabled": road_corridor_sat_enabled(),
        "deps_installed": optional_deps_available(),
        "credentials_configured": sentinel_credentials_configured(),
        "preset_count": len(CORRIDOR_PRESETS),
        "attribution": "backend/third_party/drishx/NOTICE.md",
        "active_job": job_to_dict(latest) if latest and latest.status in {"queued", "running"} else None,
    }


def _require_analyze_ready() -> None:
    if not optional_deps_available():
        raise HTTPException(
            status_code=503,
            detail="Install optional road-corridor dependencies (uv sync --extra road-corridor)",
        )
    if not sentinel_credentials_configured():
        raise HTTPException(
            status_code=503,
            detail="Set SENTINEL_CLIENT_ID and SENTINEL_CLIENT_SECRET in Imagery settings",
        )


class AnalyzeRequest(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    label: str | None = Field(default=None, max_length=120)


@router.get("/api/road-corridors/status")
@limiter.limit("60/minute")
async def road_corridors_status(request: Request) -> dict:
    return {"ok": True, **_status_payload()}


@router.get("/api/road-corridors")
@limiter.limit("60/minute")
async def list_road_corridors(request: Request) -> dict:
    return {
        "ok": True,
        "status": _status_payload(),
        "presets": CORRIDOR_PRESETS,
        "trends": build_trends_payload(),
    }


@router.post("/api/road-corridors/analyze")
@limiter.limit("6/minute")
async def analyze_road_corridor_here(request: Request, payload: AnalyzeRequest) -> dict:
    """Start an on-demand Sentinel-2 corridor analysis at map center."""
    _require_analyze_ready()
    try:
        job = enqueue_analyze(payload.lat, payload.lon, payload.label)
    except RuntimeError as exc:
        if str(exc) == "analysis_already_running":
            active = get_latest_job()
            raise HTTPException(
                status_code=409,
                detail="Analysis already in progress",
                headers={"X-Job-Id": active.job_id if active else ""},
            ) from exc
        raise
    return {"ok": True, **job_to_dict(job)}


@router.get("/api/road-corridors/analyze/status")
@limiter.limit("120/minute")
async def analyze_road_corridor_status(
    request: Request,
    job_id: str | None = Query(default=None),
) -> dict:
    job = get_job(job_id) if job_id else get_latest_job()
    if job is None:
        return {"ok": True, "job": None}
    return {"ok": True, "job": job_to_dict(job)}


@router.get("/api/road-corridors/{preset_id}")
@limiter.limit("60/minute")
async def get_road_corridor(preset_id: str, request: Request) -> dict:
    meta = preset_metadata(preset_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Unknown corridor preset")
    preset = get_preset(preset_id)
    if preset is None:
        # Ad-hoc viewport runs are stored on disk but not in CORRIDOR_PRESETS.
        return {"ok": True, "preset": None, "result": meta, "status": _status_payload()}
    return {"ok": True, "preset": preset, "result": meta, "status": _status_payload()}
