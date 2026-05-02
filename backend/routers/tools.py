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


@router.get("/api/sentinel2/search")
@limiter.limit("30/minute")
def api_sentinel2_search(
    request: Request,
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
):
    """Search for latest Sentinel-2 imagery at a point. Sync for threadpool execution."""
    from services.sentinel_search import search_sentinel2_scene
    return search_sentinel2_scene(lat, lng)


@router.post("/api/sentinel/token")
@limiter.limit("60/minute")
async def api_sentinel_token(request: Request):
    """Proxy Copernicus CDSE OAuth2 token request (avoids browser CORS block)."""
    import requests as req
    body = await request.body()
    from urllib.parse import parse_qs
    params = parse_qs(body.decode("utf-8"))
    client_id = params.get("client_id", [""])[0]
    client_secret = params.get("client_secret", [""])[0]
    if not client_id or not client_secret:
        raise HTTPException(400, "client_id and client_secret required")
    token_url = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
    try:
        resp = await asyncio.to_thread(req.post, token_url,
            data={"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret},
            timeout=15)
        return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")
    except Exception:
        logger.exception("Token request failed")
        raise HTTPException(502, "Token request failed")


_sh_token_cache: dict = {"token": None, "expiry": 0, "client_id": ""}


@router.post("/api/sentinel/tile")
@limiter.limit("300/minute")
async def api_sentinel_tile(request: Request):
    """Proxy Sentinel Hub Process API tile request (avoids CORS block)."""
    import requests as req
    import time as _time
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=422, content={"ok": False, "detail": "invalid JSON body"})

    client_id = body.get("client_id", "")
    client_secret = body.get("client_secret", "")
    preset = body.get("preset", "TRUE-COLOR")
    date_str = body.get("date", "")
    z = body.get("z", 0)
    x = body.get("x", 0)
    y = body.get("y", 0)

    if not client_id or not client_secret or not date_str:
        raise HTTPException(400, "client_id, client_secret, and date required")

    now = _time.time()
    if (_sh_token_cache["token"] and _sh_token_cache["client_id"] == client_id
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
            _sh_token_cache["client_id"] = client_id
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
