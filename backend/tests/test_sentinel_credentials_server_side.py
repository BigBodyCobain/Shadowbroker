"""Issue #298 (tg12): Sentinel credentials must live server-side.

Before the fix, ``frontend/src/components/SettingsPanel.tsx`` stored
``client_id`` and ``client_secret`` in ``localStorage`` /
``sessionStorage`` via the privacy storage helper, and the proxy routes
in ``backend/routers/tools.py`` REQUIRED those values to come in the
request body. Any same-origin script (XSS, malicious extension,
dev-tools HAR export) had read access to real third-party Sentinel
credentials.

After the fix:

  * ``SENTINEL_CLIENT_ID`` and ``SENTINEL_CLIENT_SECRET`` are entries
    in the ``api_settings.API_REGISTRY`` and are persisted via the
    existing ``/api/settings/api-keys`` flow (admin-gated, .env-backed,
    never returned to the browser).
  * The proxy routes prefer request-body values for back-compat but
    fall back to ``os.environ.get("SENTINEL_CLIENT_ID")`` /
    ``os.environ.get("SENTINEL_CLIENT_SECRET")`` when the body omits
    them. The dashboard's ``sentinelHub.ts`` no longer sends credentials
    in the body — every request now hits the env path.
  * When neither source has a value, the route returns a 400 with a
    pointer to the API Keys panel rather than a curt "client_id and
    client_secret required" message.

These tests cover the resolution order and the registry surface.
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helper: import the routes module fresh per test so monkey-patched
# environment variables are picked up by the route's os.environ.get call.
# (The lookup is per-request, not at import time, so this isn't strictly
# required — but it makes the test layout obvious.)
# ---------------------------------------------------------------------------


@pytest.fixture
def loopback_client(monkeypatch):
    """ASGI client with peer IP 127.0.0.1 and a valid operator key.

    require_local_operator now requires an explicit operator credential even
    on loopback, so inject a test ADMIN_KEY.
    """
    import asyncio
    from httpx import ASGITransport, AsyncClient
    from main import app
    from services.config import get_settings

    key = "test-operator-key-" + "x" * 32
    monkeypatch.setenv("ADMIN_KEY", key)
    get_settings.cache_clear()

    class _Loop:
        def __init__(self):
            self._loop = asyncio.new_event_loop()
            self._transport = ASGITransport(app=app, client=("127.0.0.1", 12345))
            self._base = "http://127.0.0.1:8000"

        def _do(self, method: str, url: str, **kw):
            headers = dict(kw.pop("headers", {}) or {})
            headers.setdefault("X-Admin-Key", key)
            async def go():
                async with AsyncClient(transport=self._transport, base_url=self._base) as ac:
                    return await ac.request(method, url, headers=headers, **kw)
            return self._loop.run_until_complete(go())

        def get(self, url, **kw):  return self._do("GET", url, **kw)
        def post(self, url, **kw): return self._do("POST", url, **kw)
        def put(self, url, **kw):  return self._do("PUT", url, **kw)

        def close(self): self._loop.close()

    c = _Loop()
    yield c
    c.close()


# ---------------------------------------------------------------------------
# API_REGISTRY surface
# ---------------------------------------------------------------------------


class TestApiRegistry:
    def test_sentinel_keys_registered(self):
        """Both Sentinel keys must be entries in API_REGISTRY so the
        existing /api/settings/api-keys PUT flow can write them to .env."""
        from services.api_settings import API_REGISTRY, ALLOWED_ENV_KEYS

        ids = {row["id"] for row in API_REGISTRY}
        assert "sentinel_client_id" in ids
        assert "sentinel_client_secret" in ids

        # Critical: ALLOWED_ENV_KEYS is the gate on which .env keys the
        # API can mutate. If we forgot to add the env_key field on the
        # registry rows, callers couldn't actually save the values.
        assert "SENTINEL_CLIENT_ID" in ALLOWED_ENV_KEYS
        assert "SENTINEL_CLIENT_SECRET" in ALLOWED_ENV_KEYS

    def test_api_keys_put_accepts_sentinel_keys(self, loopback_client, monkeypatch, tmp_path):
        """End-to-end: PUT /api/settings/api-keys with SENTINEL_CLIENT_ID
        + SENTINEL_CLIENT_SECRET must persist to .env."""
        import services.api_settings as api_settings

        # Redirect both .env paths to tmp so the test doesn't mutate
        # the developer's real backend .env.
        tmp_env = tmp_path / ".env"
        monkeypatch.setattr(api_settings, "ENV_PATH", tmp_env)
        monkeypatch.setattr(api_settings, "OPERATOR_KEYS_ENV_PATH", tmp_path / "operator_api_keys.env")

        r = loopback_client.put(
            "/api/settings/api-keys",
            json={
                "SENTINEL_CLIENT_ID": "test-sentinel-id",
                "SENTINEL_CLIENT_SECRET": "test-sentinel-secret",
            },
        )
        assert r.status_code == 200, f"PUT failed: {r.text}"
        body = r.json()
        assert body.get("ok") is True

        # File on disk should now carry both keys.
        parsed = api_settings._parse_env_file(tmp_env)
        assert parsed.get("SENTINEL_CLIENT_ID") == "test-sentinel-id"
        assert parsed.get("SENTINEL_CLIENT_SECRET") == "test-sentinel-secret"


# ---------------------------------------------------------------------------
# Credential resolution — body wins, env is fallback, neither is 400
# ---------------------------------------------------------------------------


class TestSentinelTokenCredResolution:
    def test_env_fallback_when_body_empty(self, loopback_client, monkeypatch):
        """No body credentials → backend reads .env values."""
        monkeypatch.setenv("SENTINEL_CLIENT_ID", "env-id")
        monkeypatch.setenv("SENTINEL_CLIENT_SECRET", "env-secret")

        # Mock the upstream Copernicus call so we don't hit the network.
        # Capture what was sent so we can prove env values were used.
        captured: dict = {}
        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.content = b'{"access_token": "stub", "expires_in": 300}'

        def fake_post(url, *args, **kwargs):
            captured["url"] = url
            captured["data"] = kwargs.get("data", {})
            return fake_resp

        with patch("requests.post", side_effect=fake_post):
            r = loopback_client.post(
                "/api/sentinel/token",
                data={},  # ← deliberately empty body
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        assert r.status_code == 200
        # The forwarded creds must come from env, not from a stale cache
        # or fallback string.
        assert captured.get("data", {}).get("client_id") == "env-id"
        assert captured.get("data", {}).get("client_secret") == "env-secret"

    def test_body_credentials_win_over_env(self, loopback_client, monkeypatch):
        """Body values (back-compat path) must win when both sources
        are present. This preserves the pre-#298 behavior for any
        legacy callers that still post credentials."""
        monkeypatch.setenv("SENTINEL_CLIENT_ID", "env-id")
        monkeypatch.setenv("SENTINEL_CLIENT_SECRET", "env-secret")

        captured: dict = {}
        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.content = b'{"access_token": "stub"}'

        def fake_post(url, *args, **kwargs):
            captured["data"] = kwargs.get("data", {})
            return fake_resp

        with patch("requests.post", side_effect=fake_post):
            r = loopback_client.post(
                "/api/sentinel/token",
                data={"client_id": "body-id", "client_secret": "body-secret"},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        assert r.status_code == 200
        assert captured["data"]["client_id"] == "body-id"
        assert captured["data"]["client_secret"] == "body-secret"

    def test_400_when_neither_source_has_credentials(self, loopback_client, monkeypatch):
        """If body is empty AND env is empty, return 400 with a
        friendly pointer to the API Keys panel — not a curt
        "required" message and not a 500."""
        monkeypatch.delenv("SENTINEL_CLIENT_ID", raising=False)
        monkeypatch.delenv("SENTINEL_CLIENT_SECRET", raising=False)

        # If the route ever calls requests.post here, the gate is broken
        # — empty creds should never produce an outbound HTTP call.
        fake = MagicMock(side_effect=AssertionError(
            "requests.post should not be called when no credentials are configured"
        ))
        with patch("requests.post", fake):
            r = loopback_client.post(
                "/api/sentinel/token",
                data={},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        assert r.status_code == 400
        detail = r.json().get("detail", "")
        # The pointer to the API Keys panel is what makes this non-hostile.
        assert "API Keys panel" in detail or "SENTINEL_CLIENT_ID" in detail
        assert fake.call_count == 0


class TestSentinelTileCredResolution:
    def test_env_fallback_when_body_omits_credentials(self, loopback_client, monkeypatch):
        """Tile route: no body credentials → uses env values."""
        monkeypatch.setenv("SENTINEL_CLIENT_ID", "env-id")
        monkeypatch.setenv("SENTINEL_CLIENT_SECRET", "env-secret")

        token_resp = MagicMock()
        token_resp.status_code = 200
        token_resp.json = MagicMock(return_value={"access_token": "stub", "expires_in": 300})

        process_resp = MagicMock()
        process_resp.status_code = 200
        process_resp.content = b"<png bytes>"
        process_resp.headers = {"content-type": "image/png"}

        captured: list = []

        def fake_post(url, *args, **kwargs):
            captured.append({"url": url, "data": kwargs.get("data"), "json": kwargs.get("json")})
            if "openid-connect/token" in url:
                return token_resp
            return process_resp

        with patch("requests.post", side_effect=fake_post):
            r = loopback_client.post(
                "/api/sentinel/tile",
                json={
                    # Note: no client_id / client_secret in body
                    "preset": "TRUE-COLOR",
                    "date": "2026-01-01",
                    "z": 6, "x": 30, "y": 20,
                },
            )

        assert r.status_code == 200
        # First call was the token mint; verify it used env creds.
        token_call = next(c for c in captured if "openid-connect/token" in c["url"])
        assert token_call["data"]["client_id"] == "env-id"
        assert token_call["data"]["client_secret"] == "env-secret"

    def test_400_when_neither_source_has_credentials(self, loopback_client, monkeypatch):
        monkeypatch.delenv("SENTINEL_CLIENT_ID", raising=False)
        monkeypatch.delenv("SENTINEL_CLIENT_SECRET", raising=False)

        fake = MagicMock(side_effect=AssertionError(
            "requests.post should not be called when no credentials are configured"
        ))
        with patch("requests.post", fake):
            r = loopback_client.post(
                "/api/sentinel/tile",
                json={
                    "preset": "TRUE-COLOR",
                    "date": "2026-01-01",
                    "z": 6, "x": 30, "y": 20,
                },
            )

        assert r.status_code == 400
        detail = r.json().get("detail", "")
        assert "API Keys panel" in detail or "SENTINEL_CLIENT_ID" in detail
        assert fake.call_count == 0
