"""Entity graph expansion (intel layer)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from auth import require_local_operator
from limiter import limiter
from services.osint_intel.resolve import resolve_entity

router = APIRouter()


@router.get("/api/entity/expand")
@limiter.limit("30/minute")
async def entity_expand(
    request: Request,
    _: None = Depends(require_local_operator),
    type: str = Query(..., min_length=3, max_length=32),
    id: str = Query(..., min_length=2, max_length=200),
    registration: str | None = Query(default=None, max_length=32),
    model: str | None = Query(default=None, max_length=64),
    icao24: str | None = Query(default=None, max_length=16),
) -> dict:
    props = {"label": id, "registration": registration, "model": model, "icao24": icao24}
    try:
        return resolve_entity(type, id, props)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Intelligence layer unavailable") from exc
