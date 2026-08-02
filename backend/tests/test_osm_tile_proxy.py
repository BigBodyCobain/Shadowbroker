"""Tests for the OSM tile proxy endpoint (/api/osm-tile/{z}/{x}/{y}.png)."""

from unittest.mock import patch, MagicMock
import pytest


FAKE_PNG = b"\x89PNG_FAKE_TILE_DATA"


def _mock_httpx_response(status_code=200, content=None, headers=None):
    """Build a mock httpx.Response for tile proxy tests."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = content if content is not None else FAKE_PNG
    resp.headers = headers or {"content-type": "image/png"}
    return resp


class TestOsmTileValid:
    """Happy-path: valid tile requests return 200 with image/png."""

    @patch("routers.tools._get_osm_client")
    def test_valid_tile_returns_200(self, mock_get_client, client):
        mock_resp = _mock_httpx_response()
        mock_client = MagicMock()
        mock_client.get = MagicMock(return_value=mock_resp)
        # Make it work with async context
        import asyncio

        async def _async_get(*a, **kw):
            return mock_resp

        mock_client.get = _async_get
        mock_get_client.return_value = mock_client

        r = client.get("/api/osm-tile/10/512/384.png")
        assert r.status_code == 200
        assert r.content == FAKE_PNG
        assert r.headers["content-type"] == "image/png"

    @patch("routers.tools._get_osm_client")
    def test_valid_tile_host_a(self, mock_get_client, client):
        """x % 3 == 0 → a.tile.openstreetmap.org"""
        mock_resp = _mock_httpx_response()
        mock_client = MagicMock()

        async def _async_get(url, **kw):
            assert "a.tile.openstreetmap.org" in str(url)
            return mock_resp

        mock_client.get = _async_get
        mock_get_client.return_value = mock_client

        r = client.get("/api/osm-tile/10/510/384.png")  # 510 % 3 == 0
        assert r.status_code == 200

    @patch("routers.tools._get_osm_client")
    def test_valid_tile_host_b(self, mock_get_client, client):
        """x % 3 == 1 → b.tile.openstreetmap.org"""
        mock_resp = _mock_httpx_response()
        mock_client = MagicMock()

        async def _async_get(url, **kw):
            assert "b.tile.openstreetmap.org" in str(url)
            return mock_resp

        mock_client.get = _async_get
        mock_get_client.return_value = mock_client

        r = client.get("/api/osm-tile/10/511/384.png")  # 511 % 3 == 1
        assert r.status_code == 200

    @patch("routers.tools._get_osm_client")
    def test_valid_tile_host_c(self, mock_get_client, client):
        """x % 3 == 2 → c.tile.openstreetmap.org"""
        mock_resp = _mock_httpx_response()
        mock_client = MagicMock()

        async def _async_get(url, **kw):
            assert "c.tile.openstreetmap.org" in str(url)
            return mock_resp

        mock_client.get = _async_get
        mock_get_client.return_value = mock_client

        r = client.get("/api/osm-tile/10/512/384.png")  # 512 % 3 == 2
        assert r.status_code == 200

    @patch("routers.tools._get_osm_client")
    def test_valid_tile_sends_correct_headers(self, mock_get_client, client):
        """Referer and User-Agent headers are sent to upstream."""
        mock_resp = _mock_httpx_response()
        captured_kw = {}

        async def _async_get(url, **kw):
            captured_kw.update(kw)
            return mock_resp

        mock_client = MagicMock()
        mock_client.get = _async_get
        mock_get_client.return_value = mock_client

        r = client.get("/api/osm-tile/10/512/384.png")
        assert r.status_code == 200
        headers = captured_kw.get("headers", {})
        assert headers.get("Referer") == "https://www.openstreetmap.org/"
        assert headers.get("User-Agent") == "Shadowbroker/1.0"

    @patch("routers.tools._get_osm_client")
    def test_response_has_cache_control(self, mock_get_client, client):
        mock_resp = _mock_httpx_response()
        mock_client = MagicMock()

        async def _async_get(*a, **kw):
            return mock_resp

        mock_client.get = _async_get
        mock_get_client.return_value = mock_client

        r = client.get("/api/osm-tile/10/512/384.png")
        assert r.headers.get("cache-control") == "public, max-age=86400"
        assert r.headers.get("x-content-type-options") == "nosniff"


class TestOsmTileValidation:
    """Invalid zoom/x/y values return 400."""

    def test_zoom_negative(self, client):
        r = client.get("/api/osm-tile/-1/0/0.png")
        assert r.status_code == 400

    def test_zoom_too_high(self, client):
        r = client.get("/api/osm-tile/20/0/0.png")
        assert r.status_code == 400

    def test_x_negative(self, client):
        r = client.get("/api/osm-tile/5/-1/0.png")
        assert r.status_code == 400

    def test_y_negative(self, client):
        r = client.get("/api/osm-tile/5/0/-1.png")
        assert r.status_code == 400

    def test_x_out_of_range(self, client):
        """At zoom 2, max x = 3 (2^2 - 1)."""
        r = client.get("/api/osm-tile/2/4/0.png")
        assert r.status_code == 400

    def test_y_out_of_range(self, client):
        r = client.get("/api/osm-tile/2/0/4.png")
        assert r.status_code == 400

    def test_zoom_zero_valid(self, client):
        """Zoom 0: only (0,0) is valid."""
        with patch("routers.tools._get_osm_client") as mock:
            mock_resp = _mock_httpx_response()
            mock_client = MagicMock()

            async def _async_get(*a, **kw):
                return mock_resp

            mock_client.get = _async_get
            mock.return_value = mock_client

            r = client.get("/api/osm-tile/0/0/0.png")
            assert r.status_code == 200

    def test_zoom_zero_invalid_x(self, client):
        r = client.get("/api/osm-tile/0/1/0.png")
        assert r.status_code == 400


class TestOsmTileUpstreamErrors:
    """Upstream errors are caught and returned as 502."""

    @patch("routers.tools._get_osm_client")
    def test_upstream_404_returns_502(self, mock_get_client, client):
        mock_resp = _mock_httpx_response(status_code=404)
        mock_client = MagicMock()

        async def _async_get(*a, **kw):
            return mock_resp

        mock_client.get = _async_get
        mock_get_client.return_value = mock_client

        r = client.get("/api/osm-tile/10/512/384.png")
        assert r.status_code == 502

    @patch("routers.tools._get_osm_client")
    def test_upstream_500_returns_502(self, mock_get_client, client):
        mock_resp = _mock_httpx_response(status_code=500)
        mock_client = MagicMock()

        async def _async_get(*a, **kw):
            return mock_resp

        mock_client.get = _async_get
        mock_get_client.return_value = mock_client

        r = client.get("/api/osm-tile/10/512/384.png")
        assert r.status_code == 502

    @patch("routers.tools._get_osm_client")
    def test_network_failure_returns_502(self, mock_get_client, client):
        mock_client = MagicMock()

        async def _async_get(*a, **kw):
            raise ConnectionError("network unreachable")

        mock_client.get = _async_get
        mock_get_client.return_value = mock_client

        r = client.get("/api/osm-tile/10/512/384.png")
        assert r.status_code == 502