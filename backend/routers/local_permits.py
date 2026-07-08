from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from auth import require_local_operator
from limiter import limiter
from services.local_permits import list_permit_sources, preview_permit_sources

router = APIRouter(dependencies=[Depends(require_local_operator)])


@router.get("/api/local-permits/sources")
@limiter.limit("60/minute")
async def local_permit_sources_route(
    request: Request,
    enabled_only: bool = Query(default=False),
) -> dict[str, Any]:
    sources = list_permit_sources(enabled_only=enabled_only)
    return {"sources": sources, "count": len(sources)}


@router.get("/api/local-permits/preview")
@limiter.limit("20/minute")
async def local_permit_preview_route(
    request: Request,
    source_id: str | None = Query(default=None, max_length=120),
    jurisdiction_id: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=25, ge=1, le=100),
) -> dict[str, Any]:
    return preview_permit_sources(source_id=source_id, jurisdiction_id=jurisdiction_id, limit=limit)
