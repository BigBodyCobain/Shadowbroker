from fastapi import APIRouter, Request, Query, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from limiter import limiter
from auth import require_admin, require_local_operator

router = APIRouter()


@router.get("/api/radio/top")
@limiter.limit("30/minute")
async def get_top_radios(request: Request):
    from services.radio_intercept import get_top_broadcastify_feeds
    return get_top_broadcastify_feeds()


@router.get("/api/radio/openmhz/systems")
@limiter.limit("30/minute")
async def api_get_openmhz_systems(request: Request):
    from services.radio_intercept import get_openmhz_systems
    return get_openmhz_systems()


@router.get("/api/radio/openmhz/calls/{sys_name}")
@limiter.limit("60/minute")
async def api_get_openmhz_calls(request: Request, sys_name: str):
    from services.radio_intercept import get_recent_openmhz_calls
    return get_recent_openmhz_calls(sys_name)


@router.get("/api/radio/openmhz/audio")
@limiter.limit("120/minute")
async def api_get_openmhz_audio(request: Request, url: str = Query(..., min_length=10)):
    from services.radio_intercept import openmhz_audio_response
    return openmhz_audio_response(url)


@router.get("/api/radio/nearest")
@limiter.limit("60/minute")
async def api_get_nearest_radio(
    request: Request,
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
):
    from services.radio_intercept import find_nearest_openmhz_system
    return find_nearest_openmhz_system(lat, lng)


@router.get("/api/radio/nearest-list")
@limiter.limit("60/minute")
async def api_get_nearest_radios_list(
    request: Request,
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    limit: int = Query(5, ge=1, le=20),
):
    from services.radio_intercept import find_nearest_openmhz_systems_list
    return find_nearest_openmhz_systems_list(lat, lng, limit=limit)


@router.get("/api/route/{callsign}")
@limiter.limit("60/minute")
async def get_flight_route(request: Request, callsign: str, lat: float = 0.0, lng: float = 0.0):
    from services.network_utils import fetch_with_curl
    r = fetch_with_curl(
        "https://api.adsb.lol/api/0/routeset",
        method="POST",
        json_data={"planes": [{"callsign": callsign, "lat": lat, "lng": lng}]},
        timeout=10,
    )
    if r and r.status_code == 200:
        data = r.json()
        route_list = []
        if isinstance(data, dict):
            route_list = data.get("value", [])
        elif isinstance(data, list):
            route_list = data

        if route_list and len(route_list) > 0:
            route = route_list[0]
            airports = route.get("_airports", [])
            if len(airports) >= 2:
                orig = airports[0]
                dest = airports[-1]
                return {
                    "orig_loc": [orig.get("lon", 0), orig.get("lat", 0)],
                    "dest_loc": [dest.get("lon", 0), dest.get("lat", 0)],
                    "origin_name": f"{orig.get('iata', '') or orig.get('icao', '')}: {orig.get('name', 'Unknown')}",
                    "dest_name": f"{dest.get('iata', '') or dest.get('icao', '')}: {dest.get('name', 'Unknown')}",
                }
    return {}
