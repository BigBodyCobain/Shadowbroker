from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from auth import require_local_operator
from limiter import limiter
from services.business_intel import BUSINESS_INTEL_KEYS, business_dashboard, score_business_intel
from services.fetchers._store import get_latest_data_subset_refs, get_source_timestamps_snapshot

router = APIRouter(dependencies=[Depends(require_local_operator)])


class BusinessIntelScoreRequest(BaseModel):
    text: str = Field(default="", max_length=24_000)
    events: list[dict[str, Any]] = Field(default_factory=list, max_length=250)
    market: str = Field(default="local_services", max_length=64)
    objective: str = Field(default="demand", max_length=64)
    source_label: str = Field(default="authorized_notes", max_length=80)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    radius_km: float = Field(default=150.0, ge=5, le=1000)
    persist: bool = True
    fuse_local: bool = True
    limit: int = Field(default=40, ge=1, le=100)


def _latest_business_data() -> tuple[dict[str, Any], dict[str, str]]:
    keys = set(BUSINESS_INTEL_KEYS)
    # Include the Local Intel categories that Market Intel can fuse directly.
    keys.update(
        {
            "earthquakes",
            "firms_fires",
            "air_quality",
            "volcanoes",
            "datacenters",
            "power_plants",
            "military_bases",
            "cctv",
            "kiwisdr",
            "psk_reporter",
            "satnogs_stations",
            "tinygs_satellites",
            "scanners",
            "satellites",
            "liveuamap",
            "uap_sightings",
        }
    )
    return get_latest_data_subset_refs(*sorted(keys)), get_source_timestamps_snapshot()


@router.post("/api/business-intel/score")
@limiter.limit("30/minute")
async def score_business_intel_route(request: Request, body: BusinessIntelScoreRequest) -> dict[str, Any]:
    data, freshness = _latest_business_data()
    return score_business_intel(
        text=body.text,
        events=body.events,
        market=body.market,
        objective=body.objective,
        source_label=body.source_label,
        lat=body.lat,
        lng=body.lng,
        radius_km=body.radius_km,
        persist=body.persist,
        fuse_local=body.fuse_local,
        data=data,
        freshness=freshness,
        limit=body.limit,
    )


@router.get("/api/business-intel/dashboard")
@limiter.limit("60/minute")
async def business_intel_dashboard_route(
    request: Request,
    market: str = Query(default="local_services", max_length=64),
    objective: str = Query(default="demand", max_length=64),
    limit: int = Query(default=30, ge=1, le=100),
) -> dict[str, Any]:
    data, freshness = _latest_business_data()
    return business_dashboard(data=data, freshness=freshness, market=market, objective=objective, limit=limit)


@router.get("/api/business-intel/graph")
@limiter.limit("60/minute")
async def business_intel_graph_route(request: Request) -> dict[str, Any]:
    data, freshness = _latest_business_data()
    dashboard = business_dashboard(data=data, freshness=freshness)
    return dashboard.get("graph", {"nodes": [], "links": []})
