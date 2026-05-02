"""SAR (Synthetic Aperture Radar) layer endpoints.

Exposes:
  - GET  /api/sar/status            — feature gates + signup links for the UI
  - GET  /api/sar/anomalies         — Mode B pre-processed anomalies
  - GET  /api/sar/scenes            — Mode A scene catalog
  - GET  /api/sar/coverage          — per-AOI coverage and next-pass hints
  - GET  /api/sar/aois              — operator-defined AOIs
  - POST /api/sar/aois              — create or replace an AOI
  - DELETE /api/sar/aois/{aoi_id}   — remove an AOI
  - GET  /api/sar/near              — anomalies within radius_km of (lat, lon)

The /status endpoint is the load-bearing UX: when Mode B is disabled it
returns the structured help payload from sar_config.products_fetch_status()
so the frontend can render in-app links to the free signup pages instead of
making the user hunt around.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from auth import require_local_operator
from limiter import limiter
from services.fetchers._store import get_latest_data_subset_refs
from services.sar.sar_aoi import (
    SarAoi,
    add_aoi,
    haversine_km,
    load_aois,
    remove_aoi,
)
from services.sar.sar_config import (
    catalog_enabled,
    clear_runtime_credentials,
    openclaw_enabled,
    products_fetch_enabled,
    products_fetch_status,
    require_private_tier_for_publish,
    set_runtime_credentials,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Status — the in-app onboarding hook
# ---------------------------------------------------------------------------
@router.get("/api/sar/status")
@limiter.limit("60/minute")
async def sar_status(request: Request) -> dict:
    """Layer status + signup links.

    The frontend calls this whenever the SAR panel is opened.  When Mode B
    is off, the response includes a step-by-step ``help`` block with the
    free signup URLs so the user can enable everything without leaving the
    app.
    """
    products_status = products_fetch_status()
    return {
        "ok": True,
        "catalog": {
            "mode": "A",
            "enabled": catalog_enabled(),
            "needs_account": False,
            "description": "Free Sentinel-1 scene catalog from ASF Search.",
        },
        "products": {
            "mode": "B",
            **products_status,
        },
        "openclaw_enabled": openclaw_enabled(),
        "require_private_tier": require_private_tier_for_publish(),
    }


# ---------------------------------------------------------------------------
# Data feeds
# ---------------------------------------------------------------------------
@router.get("/api/sar/anomalies")
@limiter.limit("60/minute")
async def sar_anomalies(
    request: Request,
    kind: str = Query("", description="Optional anomaly kind filter"),
    aoi_id: str = Query("", description="Optional AOI id filter"),
    limit: int = Query(200, ge=1, le=1000),
) -> dict:
    """Return the latest cached SAR anomalies (Mode B)."""
    snap = get_latest_data_subset_refs("sar_anomalies")
    items = list(snap.get("sar_anomalies") or [])
    if kind:
        items = [a for a in items if a.get("kind") == kind]
    if aoi_id:
        aoi_id = aoi_id.strip().lower()
        items = [a for a in items if (a.get("stack_id") or "").lower() == aoi_id]
    items = items[:limit]
    return {
        "ok": True,
        "count": len(items),
        "anomalies": items,
        "products_enabled": products_fetch_enabled(),
    }


@router.get("/api/sar/scenes")
@limiter.limit("60/minute")
async def sar_scenes(
    request: Request,
    aoi_id: str = Query(""),
    limit: int = Query(200, ge=1, le=1000),
) -> dict:
    """Return the latest cached scene catalog (Mode A)."""
    snap = get_latest_data_subset_refs("sar_scenes")
    items = list(snap.get("sar_scenes") or [])
    if aoi_id:
        aoi_id = aoi_id.strip().lower()
        items = [s for s in items if (s.get("aoi_id") or "").lower() == aoi_id]
    items = items[:limit]
    return {
        "ok": True,
        "count": len(items),
        "scenes": items,
        "catalog_enabled": catalog_enabled(),
    }


@router.get("/api/sar/coverage")
@limiter.limit("60/minute")
async def sar_coverage(request: Request) -> dict:
    """Per-AOI coverage and rough next-pass estimate."""
    snap = get_latest_data_subset_refs("sar_aoi_coverage")
    return {
        "ok": True,
        "coverage": list(snap.get("sar_aoi_coverage") or []),
    }


@router.get("/api/sar/near")
@limiter.limit("60/minute")
async def sar_near(
    request: Request,
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(50, ge=1, le=2000),
    kind: str = Query(""),
    limit: int = Query(50, ge=1, le=500),
) -> dict:
    """Return anomalies whose center sits within ``radius_km`` of (lat, lon)."""
    snap = get_latest_data_subset_refs("sar_anomalies")
    items = list(snap.get("sar_anomalies") or [])
    matches = []
    for a in items:
        try:
            a_lat = float(a.get("lat", 0.0))
            a_lon = float(a.get("lon", 0.0))
        except (TypeError, ValueError):
            continue
        d = haversine_km(lat, lon, a_lat, a_lon)
        if d > radius_km:
            continue
        if kind and a.get("kind") != kind:
            continue
        a = dict(a)
        a["distance_km"] = round(d, 2)
        matches.append(a)
    matches.sort(key=lambda x: x.get("distance_km", 0))
    return {
        "ok": True,
        "count": len(matches[:limit]),
        "anomalies": matches[:limit],
    }


# ---------------------------------------------------------------------------
# AOI CRUD
# ---------------------------------------------------------------------------
@router.get("/api/sar/aois")
@limiter.limit("60/minute")
async def sar_aoi_list(request: Request) -> dict:
    return {
        "ok": True,
        "aois": [a.to_dict() for a in load_aois(force=True)],
    }


class AoiPayload(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=120)
    description: str = Field("", max_length=400)
    center_lat: float = Field(..., ge=-90, le=90)
    center_lon: float = Field(..., ge=-180, le=180)
    radius_km: float = Field(25.0, ge=1.0, le=500.0)
    category: str = Field("watchlist", max_length=40)
    polygon: list[list[float]] | None = None


@router.post("/api/sar/aois", dependencies=[Depends(require_local_operator)])
@limiter.limit("20/minute")
async def sar_aoi_upsert(request: Request, payload: AoiPayload) -> dict:
    aoi = SarAoi(
        id=payload.id.strip().lower(),
        name=payload.name.strip(),
        description=payload.description.strip(),
        center_lat=payload.center_lat,
        center_lon=payload.center_lon,
        radius_km=payload.radius_km,
        polygon=payload.polygon,
        category=(payload.category or "watchlist").strip().lower(),
    )
    add_aoi(aoi)
    return {"ok": True, "aoi": aoi.to_dict()}


@router.delete("/api/sar/aois/{aoi_id}", dependencies=[Depends(require_local_operator)])
@limiter.limit("20/minute")
async def sar_aoi_delete(request: Request, aoi_id: str) -> dict:
    removed = remove_aoi(aoi_id)
    if not removed:
        raise HTTPException(status_code=404, detail="AOI not found")
    return {"ok": True, "removed": aoi_id}


# ---------------------------------------------------------------------------
# Mode B enable / disable — one-click setup from the frontend
# ---------------------------------------------------------------------------
class ModeBEnablePayload(BaseModel):
    earthdata_user: str = Field("", max_length=120)
    earthdata_token: str = Field(..., min_length=8, max_length=2048)
    copernicus_user: str = Field("", max_length=120)
    copernicus_token: str = Field("", max_length=2048)


@router.post("/api/sar/mode-b/enable", dependencies=[Depends(require_local_operator)])
@limiter.limit("10/minute")
async def sar_mode_b_enable(request: Request, payload: ModeBEnablePayload) -> dict:
    """Store Earthdata (and optional Copernicus) credentials and flip both
    two-step opt-in flags.  Returns the fresh status payload so the UI can
    immediately reflect the change.
    """
    set_runtime_credentials(
        earthdata_user=payload.earthdata_user,
        earthdata_token=payload.earthdata_token,
        copernicus_user=payload.copernicus_user,
        copernicus_token=payload.copernicus_token,
        mode_b_opt_in=True,
    )
    return {
        "ok": True,
        "products": products_fetch_status(),
    }


@router.post("/api/sar/mode-b/disable", dependencies=[Depends(require_local_operator)])
@limiter.limit("10/minute")
async def sar_mode_b_disable(request: Request) -> dict:
    """Wipe runtime credentials and revert to Mode A only."""
    clear_runtime_credentials()
    return {
        "ok": True,
        "products": products_fetch_status(),
    }
