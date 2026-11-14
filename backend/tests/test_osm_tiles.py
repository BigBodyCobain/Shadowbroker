from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from limiter import limiter
from routers import osm_tiles


@pytest.mark.asyncio
@pytest.mark.parametrize("status,expected,requests", [(200, 200, 1), (429, 429, 2)])
async def test_osm_proxy_caches_only_valid_tiles(monkeypatch, status, expected, requests):
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(osm_tiles.router)
    png = b"\x89PNG\r\n\x1a\nmock"
    get = AsyncMock(return_value=httpx.Response(status, content=png, headers={"Cache-Control": "max-age=300"}))
    monkeypatch.setattr(httpx.AsyncClient, "get", lambda self, *a, **kw: get(*a, **kw))
    osm_tiles._TILE_CACHE.clear()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        path = "/api/osm-tile/2/1/1.png"
        for _ in range(2):
            response = await client.request("GET", path)
            assert response.status_code == expected
            if status == 200:
                assert response.content == png
                assert response.headers["cache-control"] == "max-age=300"
        assert (await client.request("GET", "/api/osm-tile/2/4/1.png")).status_code == 400
    assert get.await_count == requests
    get.assert_awaited_with("https://tile.openstreetmap.org/2/1/1.png", headers={"User-Agent": osm_tiles._OSM_USER_AGENT})
    osm_tiles._TILE_CACHE.clear()
