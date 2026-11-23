"""Issue #302 (tg12): OpenClaw connect-info HMAC secret disclosure.

Before this change, ``GET /api/ai/connect-info?reveal=true`` returned the
full HMAC secret in the response body on every modal open AND the same
GET endpoint auto-bootstrapped (generated + persisted) the secret on a
mere read. Even gated to ``require_local_operator``, that put the full
secret into:

  * browser visit history
  * dev-tools network panel
  * browser disk cache
  * HAR exports
  * screen captures / shoulder-surfing

Every single time the OpenClaw Connect modal opened.

After this change:

  GET  /api/ai/connect-info            — always returns the MASKED
                                          fingerprint. No ?reveal param.
                                          No side effects (auto-bootstrap
                                          gone).
  POST /api/ai/connect-info/bootstrap  — mints+persists the secret if
                                          missing. Idempotent. Never
                                          returns the full secret.
  POST /api/ai/connect-info/reveal     — returns the full secret with
                                          strict Cache-Control: no-store
                                          headers. POST so the body
                                          doesn't land in URL history.
  POST /api/ai/connect-info/regenerate — keeps the one-time-disclosure
                                          for the new secret (regen IS a
                                          deliberate destructive action).
                                          Same no-store headers added.

These tests pin every property.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient


# ---------------------------------------------------------------------------
# Loopback test client. ``require_local_operator`` resolves true for
# request.client.host == "127.0.0.1"; FastAPI's TestClient sets it to
# "testclient" which isn't on the allowlist. Use raw ASGITransport.
# ---------------------------------------------------------------------------


@pytest.fixture
def loopback(monkeypatch):
    from main import app
    from services.config import get_settings

    # require_local_operator now needs an explicit operator credential even
    # on loopback; give the test client a valid one.
    key = "test-operator-key-" + "x" * 32
    monkeypatch.setenv("ADMIN_KEY", key)
    get_settings.cache_clear()

    class _Client:
        def __init__(self, peer_ip: str = "127.0.0.1"):
            self._loop = asyncio.new_event_loop()
            self._transport = ASGITransport(app=app, client=(peer_ip, 12345))
            self._base = f"http://{peer_ip}:8000"

        def _do(self, method: str, url: str, **kw):
            headers = dict(kw.pop("headers", {}) or {})
            headers.setdefault("X-Admin-Key", key)
            async def go():
                async with AsyncClient(transport=self._transport, base_url=self._base) as ac:
                    return await ac.request(method, url, headers=headers, **kw)
            return self._loop.run_until_complete(go())

        def get(self, url, **kw):  return self._do("GET", url, **kw)
        def post(self, url, **kw): return self._do("POST", url, **kw)
        def close(self): self._loop.close()

    c = _Client()
    yield c
    c.close()


@pytest.fixture
def remote():
    from main import app

    class _Client:
        def __init__(self):
            self._loop = asyncio.new_event_loop()
            self._transport = ASGITransport(app=app, client=("1.2.3.4", 12345))
            self._base = "http://1.2.3.4:8000"

        def _do(self, method: str, url: str, **kw):
            async def go():
                async with AsyncClient(transport=self._transport, base_url=self._base) as ac:
                    return await ac.request(method, url, **kw)
            return self._loop.run_until_complete(go())

        def get(self, url, **kw):  return self._do("GET", url, **kw)
        def post(self, url, **kw): return self._do("POST", url, **kw)
        def close(self): self._loop.close()

    c = _Client()
    yield c
    c.close()


@pytest.fixture
def stub_env(monkeypatch):
    """Isolate connect-info tests from the dev's real backend .env.

    Pydantic ``Settings()`` reads from ``.env`` file directly on
    instantiation, so monkey-patching ``os.environ`` isn't sufficient
    — the real ``OPENCLAW_HMAC_SECRET`` would leak through. Instead we
    override ``get_settings()`` in the route module to return a fresh
    ``Settings`` instance whose env values are driven entirely by an
    in-test dict, AND we replace ``_write_env_value`` so writes update
    that same dict instead of touching the developer's filesystem.

    Yields the dict so individual tests can pre-seed values or assert
    that writes happened.
    """
    import routers.ai_intel as ai_intel
    import services.config as config

    state: dict[str, str] = {}

    class _FakeSettings:
        @property
        def OPENCLAW_HMAC_SECRET(self) -> str:
            return state.get("OPENCLAW_HMAC_SECRET", "")

        @property
        def OPENCLAW_ACCESS_TIER(self) -> str:
            return state.get("OPENCLAW_ACCESS_TIER", "restricted")

    fake = _FakeSettings()

    def _fake_get_settings():
        return fake

    # Route code calls ``get_settings.cache_clear()`` after writing the
    # env. The production version is wrapped with ``@lru_cache``, so
    # cache_clear exists. Attach a no-op shim here.
    _fake_get_settings.cache_clear = lambda: None  # type: ignore[attr-defined]

    monkeypatch.setattr(config, "get_settings", _fake_get_settings)

    def _fake_write_env_value(key: str, value: str) -> None:
        state[key] = value

    monkeypatch.setattr(ai_intel, "_write_env_value", _fake_write_env_value)

    yield state


# ---------------------------------------------------------------------------
# GET /api/ai/connect-info — always masked, no auto-bootstrap
# ---------------------------------------------------------------------------


class TestGetConnectInfoMasking:
    def test_returns_masked_when_secret_set(self, loopback, stub_env):
        secret = "abcdef" + "0" * 38 + "wxyz"
        stub_env["OPENCLAW_HMAC_SECRET"] = secret

        r = loopback.get("/api/ai/connect-info")
        assert r.status_code == 200
        body = r.json()
        # Body must NOT carry the full secret value anywhere.
        assert secret not in r.text, (
            "GET /api/ai/connect-info MUST NOT include the full HMAC "
            "secret. Response body contained the secret value."
        )
        assert body["hmac_secret_set"] is True
        assert body["masked_hmac_secret"].startswith("abcdef")
        assert body["masked_hmac_secret"].endswith("wxyz")
        assert "•" in body["masked_hmac_secret"]
        # Pre-fix field is gone.
        assert "hmac_secret" not in body

    def test_no_auto_bootstrap_when_secret_missing(self, loopback, stub_env):
        """Side-effect-on-GET was the second half of issue #302. A GET
        with no secret configured must NOT mint one — that should
        require an explicit POST /bootstrap."""
        r = loopback.get("/api/ai/connect-info")
        assert r.status_code == 200
        body = r.json()
        assert body["hmac_secret_set"] is False
        assert body["masked_hmac_secret"] == ""
        # The bootstrap_behavior block should advertise the new flow.
        assert body["bootstrap_behavior"]["auto_generates_when_missing"] is False
        # And no _write_env_value call happened.
        assert "OPENCLAW_HMAC_SECRET" not in stub_env

    def test_no_reveal_query_param(self, loopback, stub_env):
        """Pre-fix, ?reveal=true would return the full secret. Post-fix
        the param is silently ignored — the response is the same as
        without it (still masked, no leak)."""
        secret = "abcdef" + "0" * 38 + "wxyz"
        stub_env["OPENCLAW_HMAC_SECRET"] = secret

        r = loopback.get("/api/ai/connect-info?reveal=true")
        assert r.status_code == 200
        assert secret not in r.text, (
            "?reveal=true must be a no-op on GET — the full secret "
            "MUST NOT come back in the response body."
        )


# ---------------------------------------------------------------------------
# POST /api/ai/connect-info/bootstrap
# ---------------------------------------------------------------------------


class TestBootstrap:
    def test_mints_when_missing(self, loopback, stub_env):
        r = loopback.post("/api/ai/connect-info/bootstrap")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["generated"] is True
        assert body["hmac_secret_set"] is True
        # Bootstrap must NOT return the full secret in-line.
        assert "hmac_secret" not in body or not body.get("hmac_secret")
        assert "•" in body["masked_hmac_secret"]
        # _write_env_value was actually called.
        assert stub_env.get("OPENCLAW_HMAC_SECRET")
        # The full value isn't echoed back in the response text either.
        assert stub_env["OPENCLAW_HMAC_SECRET"] not in r.text

    def test_idempotent_when_already_set(self, loopback, stub_env):
        existing = "abcdef" + "0" * 38 + "wxyz"
        stub_env["OPENCLAW_HMAC_SECRET"] = existing

        r = loopback.post("/api/ai/connect-info/bootstrap")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["generated"] is False
        assert body["hmac_secret_set"] is True
        # Existing secret untouched — value is still the seeded one.
        assert stub_env["OPENCLAW_HMAC_SECRET"] == existing
        # No full secret in the response.
        assert existing not in r.text


# ---------------------------------------------------------------------------
# POST /api/ai/connect-info/reveal
# ---------------------------------------------------------------------------


class TestReveal:
    def test_returns_full_secret_when_set(self, loopback, stub_env):
        secret = "abcdef" + "0" * 38 + "wxyz"
        stub_env["OPENCLAW_HMAC_SECRET"] = secret

        r = loopback.post("/api/ai/connect-info/reveal")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["hmac_secret"] == secret

    def test_strict_cache_control_headers(self, loopback, stub_env):
        """The whole point of POST /reveal vs GET ?reveal=true is that
        the response carries headers that prevent every cache layer
        from persisting the secret."""
        secret = "abcdef" + "0" * 38 + "wxyz"
        stub_env["OPENCLAW_HMAC_SECRET"] = secret

        r = loopback.post("/api/ai/connect-info/reveal")
        cc = r.headers.get("cache-control", "")
        assert "no-store" in cc, (
            f"reveal MUST set Cache-Control: no-store — got {cc!r}"
        )
        assert "no-cache" in cc
        # Pragma + Expires as well for HTTP/1.0 caches.
        assert r.headers.get("pragma", "").lower() == "no-cache"
        assert r.headers.get("expires") == "0"

    def test_404_when_no_secret_configured(self, loopback, stub_env):
        r = loopback.post("/api/ai/connect-info/reveal")
        assert r.status_code == 404
        # Hint should point at the bootstrap endpoint, not just say "404".
        detail = r.json().get("detail", "")
        assert "/bootstrap" in detail or "bootstrap" in detail.lower()


# ---------------------------------------------------------------------------
# POST /api/ai/connect-info/regenerate — still returns the new secret
# inline (deliberate destructive action), but with no-store headers.
# ---------------------------------------------------------------------------


class TestRegenerate:
    def test_returns_new_secret_with_no_store_headers(self, loopback, stub_env):
        # Seed an existing secret so we can prove it changes.
        old = "oldold" + "0" * 38 + "1234"
        stub_env["OPENCLAW_HMAC_SECRET"] = old

        r = loopback.post("/api/ai/connect-info/regenerate")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["hmac_secret"]
        assert body["hmac_secret"] != old
        # no-store headers MUST be present so the new secret doesn't
        # land in browser disk cache after the regenerate click.
        cc = r.headers.get("cache-control", "")
        assert "no-store" in cc and "no-cache" in cc
        assert r.headers.get("pragma", "").lower() == "no-cache"


# ---------------------------------------------------------------------------
# Auth-gate regression — every endpoint still rejects anonymous remote
# callers. This is the property we already enforce for the rest of the
# operator-only surface; adding the three new endpoints to the audit
# coverage prevents a future refactor from dropping the dependency.
# ---------------------------------------------------------------------------


class TestAnonymousRejection:
    @pytest.mark.parametrize(
        "method,path,body",
        [
            ("get",  "/api/ai/connect-info",            None),
            ("post", "/api/ai/connect-info/bootstrap",  None),
            ("post", "/api/ai/connect-info/reveal",     None),
            ("post", "/api/ai/connect-info/regenerate", None),
        ],
    )
    def test_remote_rejected(self, remote, method, path, body):
        fn = getattr(remote, method)
        r = fn(path, json=body) if body is not None else fn(path)
        assert r.status_code == 403, (
            f"{method.upper()} {path} must reject anonymous remote callers; "
            f"got {r.status_code}"
        )
