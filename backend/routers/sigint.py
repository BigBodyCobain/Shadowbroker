from fastapi import APIRouter, Request, Query, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from limiter import limiter
from auth import require_admin, require_local_operator
from services.data_fetcher import get_latest_data

router = APIRouter()


@router.get("/api/oracle/region-intel")
@limiter.limit("30/minute")
async def oracle_region_intel(
    request: Request,
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
):
    """Get oracle intelligence summary for a geographic region."""
    from services.oracle_service import get_region_oracle_intel
    news_items = get_latest_data().get("news", [])
    return get_region_oracle_intel(lat, lng, news_items)


@router.get("/api/thermal/verify")
@limiter.limit("10/minute")
async def thermal_verify(
    request: Request,
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(10, ge=1, le=100),
):
    """On-demand thermal anomaly verification using Sentinel-2 SWIR bands."""
    from services.thermal_sentinel import search_thermal_anomaly
    result = search_thermal_anomaly(lat, lng, radius_km)
    return result


@router.post("/api/sigint/transmit")
@limiter.limit("5/minute")
async def sigint_transmit(request: Request):
    """Send an APRS-IS message to a specific callsign. Requires ham radio credentials."""
    from services.wormhole_supervisor import get_transport_tier
    tier = get_transport_tier()
    if str(tier or "").startswith("private_"):
        return {"ok": False, "detail": "APRS transmit blocked in private transport mode"}
    body = await request.json()
    callsign = body.get("callsign", "")
    passcode = body.get("passcode", "")
    target = body.get("target", "")
    message = body.get("message", "")
    if not all([callsign, passcode, target, message]):
        return {"ok": False, "detail": "Missing required fields: callsign, passcode, target, message"}
    from services.sigint_bridge import send_aprs_message
    return send_aprs_message(callsign, passcode, target, message)


@router.get("/api/sigint/nearest-sdr")
@limiter.limit("30/minute")
async def nearest_sdr(
    request: Request,
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
):
    """Find the nearest KiwiSDR receivers to a given coordinate."""
    from services.sigint_bridge import find_nearest_kiwisdr
    kiwisdr_data = get_latest_data().get("kiwisdr", [])
    return find_nearest_kiwisdr(lat, lng, kiwisdr_data)
