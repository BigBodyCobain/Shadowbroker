"""Supply-chain risk overlay."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from auth import require_local_operator
from limiter import limiter
from services.scm.suppliers import build_scm_payload

router = APIRouter()


@router.get("/api/scm-suppliers")
@limiter.limit("30/minute")
async def scm_suppliers(request: Request, _: None = Depends(require_local_operator)) -> dict:
    return build_scm_payload()
