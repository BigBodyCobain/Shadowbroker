import asyncio
import logging
import math
from typing import Any
from fastapi import APIRouter, Request, Query, Depends, HTTPException, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from limiter import limiter
from auth import require_admin, require_local_operator

logger = logging.getLogger(__name__)

router = APIRouter()


def _safe_int(val, default=0):
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _safe_float(val, default=0.0):
    try:
        parsed = float(val)
        if not math.isfinite(parsed):
            return default
        return parsed
    except (TypeError, ValueError):
        return default


class ShodanSearchRequest(BaseModel):
    query: str
    page: int = 1
    facets: list[str] = []


class ShodanCountRequest(BaseModel):
    query: str
    facets: list[str] = []


class ShodanHostRequest(BaseModel):
    ip: str
    history: bool = False


@router.get("/api/region-dossier")
@limiter.limit("30/minute")
def api_region_dossier(
    request: Request,
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
):
    """Sync def so FastAPI runs it in a threadpool — prevents blocking the event loop."""
    from services.region_dossier import get_region_dossier
    return get_region_dossier(lat, lng)


@router.get("/api/geocode/search")
@limiter.limit("30/minute")
async def api_geocode_search(
    request: Request,
    q: str = "",
    limit: int = 5,
    local_only: bool = False,
):
    from services.geocode import search_geocode
    if not q or len(q.strip()) < 2:
        return {"results": [], "query": q, "count": 0}
    results = await asyncio.to_thread(search_geocode, q, limit, local_only)
    return {"results": results, "query": q, "count": len(results)}


@router.get("/api/geocode/reverse")
@limiter.limit("60/minute")
async def api_geocode_reverse(
    request: Request,
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    local_only: bool = False,
):
    from services.geocode import reverse_geocode
    return await asyncio.to_thread(reverse_geocode, lat, lng, local_only)


# ── Wikimedia proxy (#360) — browser calls these instead of wikipedia.org ───
@router.get("/api/wikipedia/summary")
@limiter.limit("60/minute")
def api_wikipedia_summary(
    request: Request,
    title: str = Query(..., min_length=1, max_length=256),
):
    """Proxy Wikipedia REST summaries through the self-hosted backend."""
    from services.region_dossier import fetch_wikipedia_page_summary

    summary = fetch_wikipedia_page_summary(title)
    if summary is None:
        return JSONResponse(status_code=404, content={"detail": "not_found"})
    return summary


class WikidataSparqlRequest(BaseModel):
    query: str


@router.post("/api/wikidata/sparql")
@limiter.limit("30/minute")
def api_wikidata_sparql(request: Request, body: WikidataSparqlRequest):
    """Proxy Wikidata SPARQL so the browser never contacts query.wikidata.org."""
    from services.region_dossier import fetch_wikidata_sparql_bindings

    q = (body.query or "").strip()
    if len(q) > 12_000:
        raise HTTPException(400, "SPARQL query too large")
    bindings = fetch_wikidata_sparql_bindings(q)
    return {"bindings": bindings}


# ── Sentinel proxy routes (Issue #299/#300/#301, reported by tg12) ──────────
# These three endpoints relay external Sentinel / Planetary Computer
# requests through the backend to avoid browser CORS blocks. They are
# operator-only helpers — they MUST NOT be callable by anonymous remote
# users, because:
#
#   * /api/sentinel/token  — caller supplies their own Sentinel client_id +
#     client_secret. Without operator gating, the backend becomes a free
#     anonymous OAuth-mint relay for any Copernicus account.
#   * /api/sentinel/tile   — same shape as the token route but for tile
#     imagery. Without gating, the backend acts as an anonymous quota and
#     bandwidth relay for Sentinel Hub Process API calls.
#   * /api/sentinel2/search — hits the Planetary Computer STAC search API
#     and falls back to Esri imagery. No caller credentials are involved,
#     but the route is still an anonymous external-search relay. We gate
#     it the same way for consistency with the rest of the operator-only
#     helper surface.
#
# Gating is via require_local_operator (loopback / bridge / admin key),
# matching the same allowlist already used by /api/region-dossier and
# the other operator helpers further up this file. Single-operator nodes
# see no behavior change — their dashboard already lives on loopback or
# the trusted Docker bridge, so it still resolves.
@router.get("/api/sentinel2/search", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
def api_sentinel2_search(
    request: Request,
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
):
    """Search for latest Sentinel-2 imagery at a point. Sync for threadpool execution."""
    from services.sentinel_search import search_sentinel2_scene
    return search_sentinel2_scene(lat, lng)


# Issue #298 (tg12): Sentinel credentials moved server-side
# ---------------------------------------------------------------------------
# Previously the frontend kept Copernicus CDSE client_id + client_secret in
# browser localStorage / sessionStorage and forwarded them on every tile
# request through this proxy. That exposed real third-party credentials to
# any same-origin script (XSS, malicious browser extension, dev-tools HAR
# export).
#
# Resolution order (first match wins):
#   1. Request body — kept for back-compat. A small number of legacy
#      operator setups may still post credentials; we don't break them.
#   2. Backend .env — SENTINEL_CLIENT_ID / SENTINEL_CLIENT_SECRET, managed
#      through the existing /api/settings/api-keys flow (admin-gated).
#
# The frontend in ``sentinelHub.ts`` no longer reads browser storage and no
# longer forwards credentials — every dashboard request now lands in (2).
# The require_local_operator gate (added in #303/PR #303) stays — both layers
# are independent: the gate blocks anonymous callers, the env fallback lets
# legitimate (gated) callers omit credentials from the body.
# ---------------------------------------------------------------------------
def _resolve_sentinel_credentials(body_id: str, body_secret: str) -> tuple[str, str]:
    """Return (client_id, client_secret) using body values when present,
    otherwise falling back to backend .env. Empty strings if neither is set."""
    import os as _os
    cid = (body_id or "").strip() or (_os.environ.get("SENTINEL_CLIENT_ID", "") or "").strip()
    csec = (body_secret or "").strip() or (_os.environ.get("SENTINEL_CLIENT_SECRET", "") or "").strip()
    return cid, csec


@router.post("/api/sentinel/token", dependencies=[Depends(require_local_operator)])
@limiter.limit("60/minute")
async def api_sentinel_token(request: Request):
    """Proxy Copernicus CDSE OAuth2 token request (avoids browser CORS block).

    Credentials are resolved by ``_resolve_sentinel_credentials`` — body
    fields are honored for back-compat, otherwise the backend .env values
    populated through ``/api/settings/api-keys`` are used.
    """
    import requests as req
    body = await request.body()
    from urllib.parse import parse_qs
    params = parse_qs(body.decode("utf-8"))
    body_id = params.get("client_id", [""])[0]
    body_secret = params.get("client_secret", [""])[0]
    client_id, client_secret = _resolve_sentinel_credentials(body_id, body_secret)
    if not client_id or not client_secret:
        # Friendly, non-hostile error — points the operator at the place
        # they configure other API keys instead of just saying "required".
        raise HTTPException(
            400,
            "Sentinel client_id/client_secret are not configured. "
            "Set SENTINEL_CLIENT_ID and SENTINEL_CLIENT_SECRET in the "
            "API Keys panel (Settings → API Keys) or your backend .env.",
        )
    token_url = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
    try:
        resp = await asyncio.to_thread(req.post, token_url,
            data={"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret},
            timeout=15)
        return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")
    except Exception:
        logger.exception("Token request failed")
        raise HTTPException(502, "Token request failed")


# Cache key is an HMAC of (client_id, client_secret) — a caller cannot hit
# this cache without knowing the same secret that originally populated it.
# Without this binding, the lookup only checked client_id, so anyone who
# knew a valid client_id could reuse another caller's cached token (and
# burn their Copernicus quota / access tiles on their account).
_sh_token_cache: dict = {"token": None, "expiry": 0, "credential_fp": ""}


def _credential_fingerprint(client_id: str, client_secret: str) -> str:
    """Return a stable, secret-binding fingerprint for the Sentinel cache key.

    Uses HMAC-SHA256 so the raw secret is never stored in process memory as
    a cache key. The HMAC key is a per-process random value, which means the
    fingerprint cannot be precomputed across restarts (additional defense
    against an attacker who learned a valid client_id but not the secret).
    """
    import hashlib
    import hmac

    return hmac.new(
        _SH_TOKEN_CACHE_HMAC_KEY,
        f"{client_id}\x00{client_secret}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


# Per-process random HMAC key. Regenerated on each backend startup so cached
# fingerprints don't survive restarts.
import os as _os
_SH_TOKEN_CACHE_HMAC_KEY = _os.urandom(32)


@router.post("/api/sentinel/tile", dependencies=[Depends(require_local_operator)])
@limiter.limit("300/minute")
async def api_sentinel_tile(request: Request):
    """Proxy Sentinel Hub Process API tile request (avoids CORS block)."""
    import requests as req
    import time as _time
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=422, content={"ok": False, "detail": "invalid JSON body"})

    # Issue #298: same resolution order as /api/sentinel/token — body
    # values for back-compat, otherwise backend .env.
    body_id = body.get("client_id", "")
    body_secret = body.get("client_secret", "")
    client_id, client_secret = _resolve_sentinel_credentials(body_id, body_secret)
    preset = body.get("preset", "TRUE-COLOR")
    date_str = body.get("date", "")
    z = body.get("z", 0)
    x = body.get("x", 0)
    y = body.get("y", 0)

    if not client_id or not client_secret or not date_str:
        # Distinguish "no creds" from "no date" so the operator knows
        # what to fix. Same friendly pointer as the /token route.
        if not client_id or not client_secret:
            raise HTTPException(
                400,
                "Sentinel client_id/client_secret are not configured. "
                "Set SENTINEL_CLIENT_ID and SENTINEL_CLIENT_SECRET in the "
                "API Keys panel (Settings → API Keys) or your backend .env.",
            )
        raise HTTPException(400, "date required")

    now = _time.time()
    credential_fp = _credential_fingerprint(client_id, client_secret)
    if (_sh_token_cache["token"]
            and _sh_token_cache["credential_fp"] == credential_fp
            and now < _sh_token_cache["expiry"] - 30):
        token = _sh_token_cache["token"]
    else:
        token_url = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
        try:
            tresp = await asyncio.to_thread(req.post, token_url,
                data={"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret},
                timeout=15)
            if tresp.status_code != 200:
                raise HTTPException(401, f"Token auth failed: {tresp.text[:200]}")
            tdata = tresp.json()
            token = tdata["access_token"]
            _sh_token_cache["token"] = token
            _sh_token_cache["expiry"] = now + tdata.get("expires_in", 300)
            _sh_token_cache["credential_fp"] = credential_fp
        except HTTPException:
            raise
        except Exception:
            logger.exception("Token request failed")
            raise HTTPException(502, "Token request failed")

    half = 20037508.342789244
    tile_size = (2 * half) / math.pow(2, z)
    min_x = -half + x * tile_size
    max_x = min_x + tile_size
    max_y = half - y * tile_size
    min_y = max_y - tile_size
    bbox = [min_x, min_y, max_x, max_y]

    evalscripts = {
        "TRUE-COLOR": '//VERSION=3\nfunction setup(){return{input:["B04","B03","B02"],output:{bands:3}};}\nfunction evaluatePixel(s){return[2.5*s.B04,2.5*s.B03,2.5*s.B02];}',
        "FALSE-COLOR": '//VERSION=3\nfunction setup(){return{input:["B08","B04","B03"],output:{bands:3}};}\nfunction evaluatePixel(s){return[2.5*s.B08,2.5*s.B04,2.5*s.B03];}',
        "NDVI": '//VERSION=3\nfunction setup(){return{input:["B04","B08"],output:{bands:3}};}\nfunction evaluatePixel(s){var n=(s.B08-s.B04)/(s.B08+s.B04);if(n<-0.2)return[0.05,0.05,0.05];if(n<0)return[0.75,0.75,0.75];if(n<0.1)return[0.86,0.86,0.86];if(n<0.2)return[0.92,0.84,0.68];if(n<0.3)return[0.77,0.88,0.55];if(n<0.4)return[0.56,0.80,0.32];if(n<0.5)return[0.35,0.72,0.18];if(n<0.6)return[0.20,0.60,0.08];if(n<0.7)return[0.10,0.48,0.04];return[0.0,0.36,0.0];}',
        "MOISTURE-INDEX": '//VERSION=3\nfunction setup(){return{input:["B8A","B11"],output:{bands:3}};}\nfunction evaluatePixel(s){var m=(s.B8A-s.B11)/(s.B8A+s.B11);var r=Math.max(0,Math.min(1,1.5-3*m));var g=Math.max(0,Math.min(1,m<0?1.5+3*m:1.5-3*m));var b=Math.max(0,Math.min(1,1.5+3*(m-0.5)));return[r,g,b];}',
    }
    evalscript = evalscripts.get(preset, evalscripts["TRUE-COLOR"])

    from datetime import datetime as _dt, timedelta as _td
    try:
        end_date = _dt.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        end_date = _dt.utcnow()

    if z <= 6:
        lookback_days = 30
    elif z <= 9:
        lookback_days = 14
    elif z <= 11:
        lookback_days = 7
    else:
        lookback_days = 5

    start_date = end_date - _td(days=lookback_days)

    process_body = {
        "input": {
            "bounds": {"bbox": bbox, "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/3857"}},
            "data": [{"type": "sentinel-2-l2a", "dataFilter": {
                "timeRange": {
                    "from": start_date.strftime("%Y-%m-%dT00:00:00Z"),
                    "to": end_date.strftime("%Y-%m-%dT23:59:59Z"),
                },
                "maxCloudCoverage": 30, "mosaickingOrder": "leastCC",
            }}],
        },
        "output": {"width": 256, "height": 256,
            "responses": [{"identifier": "default", "format": {"type": "image/png"}}]},
        "evalscript": evalscript,
    }
    try:
        resp = await asyncio.to_thread(req.post,
            "https://sh.dataspace.copernicus.eu/api/v1/process",
            json=process_body,
            headers={"Authorization": f"Bearer {token}", "Accept": "image/png"},
            timeout=30)
        return Response(content=resp.content, status_code=resp.status_code,
            media_type=resp.headers.get("content-type", "image/png"))
    except Exception:
        logger.exception("Process API failed")
        raise HTTPException(502, "Process API failed")


@router.get("/api/tools/shodan/status", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_shodan_status(request: Request):
    from services.shodan_connector import get_shodan_connector_status
    return get_shodan_connector_status()


@router.post("/api/tools/shodan/search", dependencies=[Depends(require_local_operator)])
@limiter.limit("12/minute")
async def api_shodan_search(request: Request, body: ShodanSearchRequest):
    from services.shodan_connector import ShodanConnectorError, search_shodan
    try:
        return search_shodan(body.query, page=body.page, facets=body.facets)
    except ShodanConnectorError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/api/tools/shodan/count", dependencies=[Depends(require_local_operator)])
@limiter.limit("12/minute")
async def api_shodan_count(request: Request, body: ShodanCountRequest):
    from services.shodan_connector import ShodanConnectorError, count_shodan
    try:
        return count_shodan(body.query, facets=body.facets)
    except ShodanConnectorError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/api/tools/shodan/host", dependencies=[Depends(require_local_operator)])
@limiter.limit("12/minute")
async def api_shodan_host(request: Request, body: ShodanHostRequest):
    from services.shodan_connector import ShodanConnectorError, lookup_shodan_host
    try:
        return lookup_shodan_host(body.ip, history=body.history)
    except ShodanConnectorError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/api/tools/uw/status", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_uw_status(request: Request):
    from services.unusual_whales_connector import get_uw_status
    return get_uw_status()


@router.post("/api/tools/uw/congress", dependencies=[Depends(require_local_operator)])
@limiter.limit("12/minute")
async def api_uw_congress(request: Request):
    from services.unusual_whales_connector import FinnhubConnectorError, fetch_congress_trades
    try:
        return fetch_congress_trades()
    except FinnhubConnectorError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/api/tools/uw/darkpool", dependencies=[Depends(require_local_operator)])
@limiter.limit("12/minute")
async def api_uw_darkpool(request: Request):
    from services.unusual_whales_connector import FinnhubConnectorError, fetch_insider_transactions
    try:
        return fetch_insider_transactions()
    except FinnhubConnectorError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/api/tools/uw/flow", dependencies=[Depends(require_local_operator)])
@limiter.limit("12/minute")
async def api_uw_flow(request: Request):
    from services.unusual_whales_connector import FinnhubConnectorError, fetch_defense_quotes
    try:
        return fetch_defense_quotes()
    except FinnhubConnectorError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
