"""Operator OSINT recon routes (server-side proxies, SSRF guarded)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from auth import require_local_operator
from limiter import limiter
from services.osint import lookups

router = APIRouter(dependencies=[Depends(require_local_operator)])

_ALLOWED_SCHEMAS = {
    "Person",
    "Organization",
    "Company",
    "Vessel",
    "Airplane",
    "LegalEntity",
}


class SweepScanRequest(BaseModel):
    ip: str = Field(min_length=7, max_length=45)
    cidr: int = Field(default=24, ge=24, le=32)


def _bad_request(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.get("/api/osint/ip")
@limiter.limit("20/minute")
async def osint_ip(request: Request, ip: str = Query(..., min_length=7, max_length=45)) -> dict:
    try:
        return lookups.lookup_ip(ip)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.get("/api/osint/dns")
@limiter.limit("20/minute")
async def osint_dns(request: Request, domain: str = Query(..., min_length=4, max_length=253)) -> dict:
    try:
        return lookups.lookup_dns(domain)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.get("/api/osint/whois")
@limiter.limit("20/minute")
async def osint_whois(request: Request, domain: str = Query(..., min_length=4, max_length=253)) -> dict:
    try:
        return lookups.lookup_whois(domain)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.get("/api/osint/certs")
@limiter.limit("20/minute")
async def osint_certs(request: Request, domain: str = Query(..., min_length=4, max_length=253)) -> dict:
    try:
        return lookups.lookup_certs(domain)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.get("/api/osint/threats")
@limiter.limit("20/minute")
async def osint_threats(request: Request, query: str | None = Query(default=None, max_length=253)) -> dict:
    return lookups.lookup_threats(query)


@router.get("/api/osint/bgp")
@limiter.limit("20/minute")
async def osint_bgp(request: Request, query: str = Query(..., min_length=2, max_length=64)) -> dict:
    try:
        return lookups.lookup_bgp(query)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.get("/api/osint/sanctions")
@limiter.limit("20/minute")
async def osint_sanctions(
    request: Request,
    query: str = Query(..., min_length=4, max_length=200),
    schema: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
) -> dict:
    if schema and schema not in _ALLOWED_SCHEMAS:
        raise HTTPException(status_code=400, detail=f"Invalid schema. Allowed: {', '.join(sorted(_ALLOWED_SCHEMAS))}")
    return lookups.lookup_sanctions(query, schema=schema, limit=limit)


@router.get("/api/osint/cve")
@limiter.limit("30/minute")
async def osint_cve(request: Request, cve: str = Query(..., min_length=10, max_length=32)) -> dict:
    try:
        return lookups.lookup_cve(cve)
    except ValueError as exc:
        raise HTTPException(status_code=404 if "not found" in str(exc).lower() else 400, detail=str(exc)) from exc


@router.get("/api/osint/mac")
@limiter.limit("20/minute")
async def osint_mac(request: Request, mac: str = Query(..., min_length=5, max_length=32)) -> dict:
    return lookups.lookup_mac(mac)


@router.get("/api/osint/github")
@limiter.limit("20/minute")
async def osint_github(request: Request, username: str = Query(..., min_length=1, max_length=64)) -> dict:
    try:
        return lookups.lookup_github(username)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/osint/leaks")
@limiter.limit("10/minute")
async def osint_leaks(request: Request, email: str = Query(..., min_length=5, max_length=254)) -> dict:
    try:
        return lookups.lookup_leaks(email)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.get("/api/osint/sweep")
@limiter.limit("5/minute")
async def osint_sweep_init(
    request: Request,
    ip: str = Query(..., min_length=7, max_length=45),
    cidr: int = Query(default=24, ge=24, le=32),
) -> dict:
    try:
        return lookups.sweep_init(ip, cidr)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/api/osint/sweep/scan")
@limiter.limit("3/minute")
async def osint_sweep_scan(request: Request, payload: SweepScanRequest) -> dict:
    try:
        subnet = lookups.subnet_start_for(payload.ip, payload.cidr)
        scan = lookups.sweep_scan(subnet, payload.cidr)
        init = lookups.sweep_init(payload.ip, payload.cidr)
        return {**init, **scan, "subnet": f"{subnet}/{payload.cidr}"}
    except ValueError as exc:
        raise _bad_request(exc) from exc
