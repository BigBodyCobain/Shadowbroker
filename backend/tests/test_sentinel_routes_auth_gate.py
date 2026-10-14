"""Issues #299, #300, #301 (tg12): Sentinel proxy routes must require
local-operator auth.

Before the fix, three Sentinel proxy routes in ``backend/routers/tools.py``
were decorated only with ``@limiter.limit(...)`` — no
``Depends(require_local_operator)``:

  * ``POST /api/sentinel/token``  — Copernicus CDSE OAuth relay for
    caller-supplied client_id + client_secret. Anonymous access made the
    backend a free OAuth-mint relay for any Sentinel account.
  * ``POST /api/sentinel/tile``   — Sentinel Hub Process API relay.
    Caller supplies their own credentials, backend mints a token if
    needed and relays the PNG. Anonymous access was a bandwidth + quota
    relay for any Copernicus account.
  * ``GET  /api/sentinel2/search`` — Planetary Computer STAC search with
    Esri imagery fallback. No caller credentials are involved, but the
    route is still an anonymous external-search relay.

The fix adds ``dependencies=[Depends(require_local_operator)]`` to each.
The parameterized regression in ``test_control_surface_auth.py`` covers
the basic 403 path. This file adds the harder property: when the auth
gate fires, **the underlying upstream HTTP call never happens** — no
outbound Copernicus token mint, no Sentinel Hub Process call, no
Planetary Computer STAC search. The egress-on-403 property is what
separates a real gate from a route that returns 403 *after* burning a
quota.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient


# ---------------------------------------------------------------------------
# Remote client fixture — same shape as test_control_surface_auth.py, but
# inlined here so this file doesn't depend on the shared remote_client
# fixture order. Uses 1.2.3.4 as the peer IP so loopback auth bypass
# doesn't accidentally let the request through.
# ---------------------------------------------------------------------------


class _PeerClient:
    """Raw ASGI client with a configurable peer IP. FastAPI's
    ``TestClient`` reports ``request.client.host`` as ``"testclient"``
    which isn't on the loopback allowlist — we need to set the peer
    explicitly to exercise the real ``require_local_operator`` path.
    """

    def __init__(self, peer_ip: str, headers=None):
        from main import app

        self._loop = asyncio.new_event_loop()
        self._transport = ASGITransport(app=app, client=(peer_ip, 12345))
        self._base = f"http://{peer_ip}:8000"
        self._headers = headers or {}

    def _do(self, method: str, url: str, **kw):
        async def go():
            async with AsyncClient(transport=self._transport, base_url=self._base, headers=self._headers) as ac:
                return await ac.request(method, url, **kw)

        return self._loop.run_until_complete(go())

    def get(self, url, **kw):
        return self._do("GET", url, **kw)

    def post(self, url, **kw):
        return self._do("POST", url, **kw)

    def close(self):
        self._loop.close()


@pytest.fixture
def remote():
    """Untrusted remote caller (1.2.3.4) — must hit the auth gate."""
    client = _PeerClient("1.2.3.4")
    yield client
    client.close()


@pytest.fixture
def loopback():
    """An explicitly authenticated operator on loopback."""
    key = "audit-operator-key-" + "x" * 32
    client = _PeerClient("127.0.0.1", headers={"X-Admin-Key": key})
    with patch("auth._current_admin_key", return_value=key):
        yield client
    client.close()


# ---------------------------------------------------------------------------
# /api/sentinel/token — issue #299
# ---------------------------------------------------------------------------


class TestSentinelTokenAuthGate:
    def test_anonymous_caller_is_rejected(self, remote):
        """A remote (non-loopback, non-bridge) caller MUST be rejected."""
        r = remote.post(
            "/api/sentinel/token",
            data={"client_id": "anything", "client_secret": "anything"},
        )
        assert r.status_code == 403

    def test_no_upstream_token_mint_on_403(self, remote):
        """The Copernicus token endpoint must NOT be contacted when the
        auth gate fires. This is what makes the gate real — without it,
        a 403 returned *after* the upstream call still burns quota.

        We patch ``requests.post`` at the module level so any outbound
        token request would be intercepted. The mock is asserted to have
        ZERO calls.
        """
        fake_post = MagicMock()
        # If the gate is broken, the route would call requests.post; we
        # want this MagicMock to make that fact loud.
        fake_post.side_effect = AssertionError(
            "requests.post was called despite auth-gate 403 — the gate is bypassable"
        )
        with patch("requests.post", fake_post):
            r = remote.post(
                "/api/sentinel/token",
                data={"client_id": "anything", "client_secret": "anything"},
            )
        assert r.status_code == 403
        assert fake_post.call_count == 0

    def test_authenticated_loopback_caller_passes_auth(self, loopback):
        """Valid credentials reach the handler without contacting Copernicus."""
        fake_resp = MagicMock()
        fake_resp.status_code = 401
        fake_resp.content = b'{"error": "invalid_client"}'
        with patch("requests.post", return_value=fake_resp):
            r = loopback.post(
                "/api/sentinel/token",
                data={"client_id": "anything", "client_secret": "anything"},
            )
        # 200 (relayed), 401 (upstream said no), or 502 (upstream blew up)
        # are all acceptable — what matters is we got past the auth gate
        # (no 403). The route relays the upstream response status.
        assert r.status_code != 403


# ---------------------------------------------------------------------------
# /api/sentinel/tile — issue #300
# ---------------------------------------------------------------------------


class TestSentinelTileAuthGate:
    _VALID_BODY = {
        "client_id": "anything",
        "client_secret": "anything",
        "preset": "TRUE-COLOR",
        "date": "2026-01-01",
        "z": 6,
        "x": 30,
        "y": 20,
    }

    def test_anonymous_caller_is_rejected(self, remote):
        r = remote.post("/api/sentinel/tile", json=self._VALID_BODY)
        assert r.status_code == 403

    def test_no_upstream_call_on_403(self, remote):
        """When the gate fires, neither the token mint nor the Process
        API call should happen."""
        fake_post = MagicMock(side_effect=AssertionError(
            "requests.post was called despite auth-gate 403 — gate bypassable"
        ))
        with patch("requests.post", fake_post):
            r = remote.post("/api/sentinel/tile", json=self._VALID_BODY)
        assert r.status_code == 403
        assert fake_post.call_count == 0


# ---------------------------------------------------------------------------
# /api/sentinel2/search — issue #301
# ---------------------------------------------------------------------------


class TestSentinel2SearchAuthGate:
    def test_anonymous_caller_is_rejected(self, remote):
        r = remote.get("/api/sentinel2/search?lat=0&lng=0")
        assert r.status_code == 403

    def test_no_upstream_search_on_403(self, remote):
        """The Planetary Computer STAC search MUST NOT be called when
        the gate fires."""
        fake = MagicMock(side_effect=AssertionError(
            "search_sentinel2_scene was called despite 403 — gate bypassable"
        ))
        # Patch the underlying service function — that's the network
        # surface. If the auth dep fires first, the handler body never
        # runs and this stays uncalled.
        with patch("services.sentinel_search.search_sentinel2_scene", fake):
            r = remote.get("/api/sentinel2/search?lat=0&lng=0")
        assert r.status_code == 403
        assert fake.call_count == 0

    def test_authenticated_loopback_caller_reaches_handler(self, loopback):
        """Valid credentials reach the mocked search function."""
        fake = MagicMock(return_value={"ok": True, "results": []})
        with patch("services.sentinel_search.search_sentinel2_scene", fake):
            r = loopback.get("/api/sentinel2/search?lat=0&lng=0")
        assert r.status_code == 200
        assert fake.call_count == 1


# Note: an earlier draft included a static dependency walker that
# inspected the FastAPI route table to assert require_local_operator
# was wired in. It was deleted because FastAPI's internal route
# representation varies across minor versions — the walker was brittle
# and the behavioral pair (anonymous → 403 with no upstream egress;
# loopback → handler reached) gives stronger end-to-end evidence than
# any structural check.
