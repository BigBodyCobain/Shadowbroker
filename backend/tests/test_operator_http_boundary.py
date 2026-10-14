import asyncio
from unittest.mock import patch

import httpx
import pytest
from fastapi import Depends, FastAPI, Request

from auth import require_local_operator
from services.http_security import RequestBodyLimitMiddleware


KEY = "audit-operator-key-" + "x" * 32


def request(app, method="GET", path="/api/operator", peer="127.0.0.1", **kwargs):
    async def send():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=(peer, 12345)),
            base_url="http://localhost:8000",
        ) as client:
            return await client.request(method, path, **kwargs)
    return asyncio.run(send())


@pytest.fixture
def operator_app():
    app = FastAPI()
    writes = []

    @app.api_route("/api/operator", methods=["GET", "POST"], dependencies=[Depends(require_local_operator)])
    async def operation():
        writes.append(True)
        return {"ok": True}

    with patch("auth._current_admin_key", return_value=KEY), patch("auth._debug_mode_enabled", return_value=False):
        yield app, writes


@pytest.mark.parametrize("peer", ["127.0.0.1", "::1", "172.18.0.2", "198.51.100.25"])
def test_source_address_does_not_grant_operator_authority(operator_app, peer):
    app, writes = operator_app
    assert request(app, peer=peer).status_code == 403
    assert writes == []


def test_authenticated_native_and_same_origin_browser_work(operator_app):
    app, writes = operator_app
    assert request(app, headers={"X-Admin-Key": KEY}).status_code == 200
    assert request(app, headers={"X-Admin-Key": KEY, "Origin": "http://localhost:3000"}).status_code == 200
    assert len(writes) == 2


@pytest.mark.parametrize("headers", [
    {"Origin": "https://attacker.example", "Sec-Fetch-Site": "cross-site"},
    {"Origin": "https://localhost:3000"},
    {"Origin": "http://localhost:3001"},
    {"Sec-Fetch-Site": "cross-site"},
])
def test_hostile_browser_write_is_denied_even_with_credentials(operator_app, headers):
    app, writes = operator_app
    result = request(app, "POST", headers={"X-Admin-Key": KEY, **headers}, content=b'{"enable":true}')
    assert result.status_code == 403
    assert writes == []


@pytest.mark.parametrize("declared", [None, "1"])
def test_chunked_or_falsely_declared_body_is_limited(declared):
    app = FastAPI()
    app.add_middleware(RequestBodyLimitMiddleware)
    invoked = []

    @app.post("/api/mesh/infonet/peer-push")
    async def ingest(request: Request):
        invoked.append(True)
        return {"bytes": len(await request.body())}

    async def chunks():
        yield b"x" * (512 * 1024)
        yield b"x"
    headers = {"Content-Length": declared} if declared else {}
    assert request(app, "POST", "/api/mesh/infonet/peer-push", headers=headers, content=chunks()).status_code == 413
    assert invoked == []


def test_body_at_limit_is_replayed_to_the_handler():
    app = FastAPI()
    app.add_middleware(RequestBodyLimitMiddleware)

    @app.post("/api/mesh/infonet/peer-push")
    async def ingest(request: Request):
        return {"bytes": len(await request.body())}

    result = request(app, "POST", "/api/mesh/infonet/peer-push", content=b"x" * (512 * 1024))
    assert result.status_code == 200
    assert result.json()["bytes"] == 512 * 1024


def test_real_application_limits_bodies_before_other_middleware():
    from main import app
    assert app.user_middleware[0].cls is RequestBodyLimitMiddleware

    async def chunks():
        yield b"x" * (512 * 1024)
        yield b"x"

    assert request(app, "POST", "/api/mesh/infonet/peer-push", peer="198.51.100.25", content=chunks()).status_code == 413
