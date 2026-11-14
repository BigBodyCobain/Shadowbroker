"""OpenStreetMap standard raster tile proxy.

Proxies ``GET /api/osm-tile/{z}/{x}/{y}.png`` to ``tile.openstreetmap.org`` so
the frontend can render a keyless OSM basemap without browsers calling the tile
server directly.

OSM tile usage policy
(https://operations.osmfoundation.org/policies/tiles/):
- identify the client with a descriptive User-Agent (per-install operator
  handle, never a shared project-wide string)
- cache tiles instead of re-fetching on every pan / zoom
- keep request rates reasonable
"""

import logging

import httpx
from cachetools import TLRUCache
from fastapi import APIRouter, Path, Request
from fastapi.responses import Response

from limiter import limiter
from services.network_utils import outbound_user_agent

logger = logging.getLogger(__name__)

router = APIRouter()

# OpenStreetMap standard tile endpoint.
_OSM_TILE_BASE = "https://tile.openstreetmap.org"
# OSM tiles are served up to zoom 19 on the standard layer.
_OSM_MAX_ZOOM = 19

# In-memory tile cache keyed by "z/x/y". Tiles change infrequently, so a
# multi-day TTL keeps repeated pans/zooms from hitting the upstream.
_TILE_CACHE = TLRUCache(maxsize=2048, ttu=lambda _key, value, now: now + value[2])

# Per-request User-Agent identifying this install to the tile operator.
_OSM_USER_AGENT = outbound_user_agent("osm-tiles")


def _tile_bounds_valid(z: int, x: int, y: int) -> bool:
    if z < 0 or z > _OSM_MAX_ZOOM:
        return False
    limit = 1 << z
    return 0 <= x < limit and 0 <= y < limit


@router.get("/api/osm-tile/{z}/{x}/{y}.png")
@limiter.limit("180/minute")
async def osm_tile(
    request: Request,
    z: int = Path(..., ge=0, le=_OSM_MAX_ZOOM),
    x: int = Path(..., ge=0),
    y: int = Path(..., ge=0),
) -> Response:
    """Proxy a single OSM raster tile, cached per z/x/y."""
    if not _tile_bounds_valid(z, x, y):
        return Response(status_code=400)

    cache_key = f"{z}/{x}/{y}"
    cached = _TILE_CACHE.get(cache_key)
    if cached is not None:
        content, cache_control, _ = cached
        return Response(content=content, media_type="image/png", headers={"Cache-Control": cache_control})

    url = f"{_OSM_TILE_BASE}/{z}/{x}/{y}.png"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10, connect=3)) as client:
            upstream = await client.get(url, headers={"User-Agent": _OSM_USER_AGENT})
    except httpx.RequestError as exc:
        logger.warning("OSM tile proxy request failed for %s: %s", url, exc)
        return Response(status_code=502)

    if upstream.status_code != 200:
        retry_after = upstream.headers.get("Retry-After")
        return Response(
            status_code=upstream.status_code if upstream.status_code in (403, 404, 429) else 502,
            headers={"Retry-After": retry_after} if retry_after else None,
        )
    if not upstream.content.startswith(b"\x89PNG\r\n\x1a\n"):
        return Response(status_code=502)

    cache_control = upstream.headers.get("Cache-Control", "public, max-age=604800")
    directives = dict(
        (key.strip(), value.strip(' "'))
        for key, _, value in (part.strip().lower().partition("=") for part in cache_control.split(","))
    )
    max_age = directives.get("s-maxage", directives.get("max-age", "0"))
    if max_age.isdecimal() and not {"no-store", "no-cache", "private"}.intersection(directives):
        _TILE_CACHE[cache_key] = (upstream.content, cache_control, min(int(max_age), 604800))
    return Response(content=upstream.content, media_type="image/png", headers={"Cache-Control": cache_control})
