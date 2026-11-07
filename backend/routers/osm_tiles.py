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

from cachetools import TTLCache
from fastapi import APIRouter, Path
from fastapi.responses import Response

from services.network_utils import fetch_with_curl, outbound_user_agent

logger = logging.getLogger(__name__)

router = APIRouter()

# OpenStreetMap standard tile endpoint.
_OSM_TILE_BASE = "https://tile.openstreetmap.org"
# OSM tiles are served up to zoom 19 on the standard layer.
_OSM_MAX_ZOOM = 19

# In-memory tile cache keyed by "z/x/y". Tiles change infrequently, so a
# multi-day TTL keeps repeated pans/zooms from hitting the upstream.
_TILE_CACHE: TTLCache = TTLCache(maxsize=2048, ttl=7 * 24 * 60 * 60)

# Per-request User-Agent identifying this install to the tile operator.
_OSM_USER_AGENT = outbound_user_agent("osm-tiles")


def _tile_bounds_valid(z: int, x: int, y: int) -> bool:
    if z < 0 or z > _OSM_MAX_ZOOM:
        return False
    limit = 1 << z
    return 0 <= x < limit and 0 <= y < limit


@router.get("/api/osm-tile/{z}/{x}/{y}.png")
async def osm_tile(
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
        status, content, content_type = cached
        return Response(content=content, media_type=content_type, status_code=status)

    url = f"{_OSM_TILE_BASE}/{z}/{x}/{y}.png"
    try:
        upstream = fetch_with_curl(
            url,
            timeout=20,
            headers={"User-Agent": _OSM_USER_AGENT},
        )
    except Exception as exc:  # pragma: no cover - network failure path
        logger.warning("OSM tile proxy request failed for %s: %s", url, exc)
        return Response(status_code=502)

    status = upstream.status_code or 502
    content = getattr(upstream, "content", b"") or b""
    content_type = (
        upstream.headers.get("Content-Type", "image/png")
        if hasattr(upstream, "headers")
        else "image/png"
    )

    # Only cache successful responses — rate limits and errors must propagate.
    if status == 200 and content:
        _TILE_CACHE[cache_key] = (status, content, content_type)

    return Response(content=content, media_type=content_type, status_code=status)
