"""Tests for OpenClaw direct-mode HMAC body binding (Packet P1A).

Proves that:
  1. Tampered request bodies are rejected.
  2. Untampered request bodies are accepted.
  3. Nonce replay protection still works.
  4. Timestamp freshness still works.
  5. Bodyless (GET) requests still work.
"""

import hashlib
import hmac as hmac_mod
import secrets
import time

import pytest
from starlette.requests import Request


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

HMAC_SECRET = "test-secret-for-hmac-body-binding-packet-p1a"


def _make_scope(method: str, path: str, headers: dict, client_host: str = "1.2.3.4"):
    """Build a minimal ASGI scope for a Starlette Request."""
    raw_headers = [(k.lower().encode(), str(v).encode()) for k, v in headers.items()]
    return {
        "type": "http",
        "method": method.upper(),
        "path": path,
        "headers": raw_headers,
        "query_string": b"",
        "root_path": "",
        "server": (client_host, 80),
        "client": (client_host, 12345),
    }


def _make_receive(body: bytes = b""):
    """Build an ASGI receive callable that returns *body*."""
    async def receive():
        return {"type": "http.request", "body": body}
    return receive


def _sign(method: str, path: str, body: bytes = b"",
          secret: str = HMAC_SECRET, ts: int | None = None,
          nonce: str | None = None) -> dict[str, str]:
    """Produce valid X-SB-* auth headers with body binding."""
    ts_str = str(ts if ts is not None else int(time.time()))
    nonce = nonce or secrets.token_hex(16)
    body_digest = hashlib.sha256(body).hexdigest()
    message = f"{method.upper()}|{path}|{ts_str}|{nonce}|{body_digest}"
    sig = hmac_mod.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return {
        "X-SB-Timestamp": ts_str,
        "X-SB-Nonce": nonce,
        "X-SB-Signature": sig,
    }


def _make_request(method: str, path: str, headers: dict,
                  body: bytes = b"", client_host: str = "1.2.3.4") -> Request:
    scope = _make_scope(method, path, headers, client_host)
    return Request(scope, _make_receive(body))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _patch_hmac_secret(monkeypatch):
    """Ensure _openclaw_hmac_secret() returns our test secret."""
    import auth
    monkeypatch.setattr(auth, "_openclaw_hmac_secret", lambda: HMAC_SECRET)
    # Clear nonce cache between tests to avoid cross-test interference.
    auth._openclaw_nonce_cache.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBodyBinding:
    """Body-bearing requests must bind the body in the HMAC."""

    @pytest.mark.asyncio
    async def test_post_with_matching_body_accepted(self):
        from auth import _verify_openclaw_hmac

        body = b'{"cmd":"get_summary","args":{}}'
        headers = _sign("POST", "/api/ai/channel/command", body)
        req = _make_request("POST", "/api/ai/channel/command", headers, body)
        assert await _verify_openclaw_hmac(req) is True

    @pytest.mark.asyncio
    async def test_post_with_tampered_body_rejected(self):
        from auth import _verify_openclaw_hmac

        original_body = b'{"cmd":"get_summary","args":{}}'
        tampered_body = b'{"cmd":"place_pin","args":{"lat":0,"lng":0,"label":"evil"}}'
        # Sign with original body, send tampered body
        headers = _sign("POST", "/api/ai/channel/command", original_body)
        req = _make_request("POST", "/api/ai/channel/command", headers, tampered_body)
        assert await _verify_openclaw_hmac(req) is False

    @pytest.mark.asyncio
    async def test_put_with_tampered_body_rejected(self):
        from auth import _verify_openclaw_hmac

        original_body = b'{"preset":"fast"}'
        tampered_body = b'{"preset":"off"}'
        headers = _sign("PUT", "/api/ai/timemachine/config", original_body)
        req = _make_request("PUT", "/api/ai/timemachine/config", headers, tampered_body)
        assert await _verify_openclaw_hmac(req) is False

    @pytest.mark.asyncio
    async def test_patch_with_tampered_body_rejected(self):
        from auth import _verify_openclaw_hmac

        original_body = b'{"field":"value"}'
        tampered_body = b'{"field":"evil"}'
        headers = _sign("PATCH", "/api/ai/some-endpoint", original_body)
        req = _make_request("PATCH", "/api/ai/some-endpoint", headers, tampered_body)
        assert await _verify_openclaw_hmac(req) is False

    @pytest.mark.asyncio
    async def test_empty_body_accepted_when_signed_as_empty(self):
        from auth import _verify_openclaw_hmac

        headers = _sign("POST", "/api/ai/channel/poll", b"")
        req = _make_request("POST", "/api/ai/channel/poll", headers, b"")
        assert await _verify_openclaw_hmac(req) is True

    @pytest.mark.asyncio
    async def test_body_injected_into_bodyless_signature_rejected(self):
        """Signing with empty body but sending a body must fail."""
        from auth import _verify_openclaw_hmac

        headers = _sign("POST", "/api/ai/channel/poll", b"")
        injected = b'{"malicious": true}'
        req = _make_request("POST", "/api/ai/channel/poll", headers, injected)
        assert await _verify_openclaw_hmac(req) is False


class TestBodylessRequests:
    """GET/DELETE (no body) must still pass auth."""

    @pytest.mark.asyncio
    async def test_get_no_body_accepted(self):
        from auth import _verify_openclaw_hmac

        headers = _sign("GET", "/api/ai/status")
        req = _make_request("GET", "/api/ai/status", headers)
        assert await _verify_openclaw_hmac(req) is True

    @pytest.mark.asyncio
    async def test_delete_no_body_accepted(self):
        from auth import _verify_openclaw_hmac

        headers = _sign("DELETE", "/api/ai/pins")
        req = _make_request("DELETE", "/api/ai/pins", headers)
        assert await _verify_openclaw_hmac(req) is True


class TestNonceReplay:
    """Nonce replay protection must still work after body-binding changes."""

    @pytest.mark.asyncio
    async def test_replayed_nonce_rejected(self):
        from auth import _verify_openclaw_hmac

        nonce = secrets.token_hex(16)
        body = b'{"cmd":"get_summary","args":{}}'
        headers = _sign("POST", "/api/ai/channel/command", body, nonce=nonce)
        req1 = _make_request("POST", "/api/ai/channel/command", headers, body)
        assert await _verify_openclaw_hmac(req1) is True

        # Replay same nonce — must be rejected
        headers2 = _sign("POST", "/api/ai/channel/command", body, nonce=nonce)
        req2 = _make_request("POST", "/api/ai/channel/command", headers2, body)
        assert await _verify_openclaw_hmac(req2) is False

    @pytest.mark.asyncio
    async def test_short_nonce_rejected(self):
        from auth import _verify_openclaw_hmac

        body = b'{"cmd":"get_summary"}'
        headers = _sign("POST", "/api/ai/channel/command", body, nonce="short")
        # Override nonce to be too short
        headers["X-SB-Nonce"] = "short"
        req = _make_request("POST", "/api/ai/channel/command", headers, body)
        assert await _verify_openclaw_hmac(req) is False


class TestTimestampFreshness:
    """Timestamp freshness checks must still work."""

    @pytest.mark.asyncio
    async def test_stale_timestamp_rejected(self):
        from auth import _verify_openclaw_hmac

        stale_ts = int(time.time()) - 600  # 10 minutes ago
        body = b'{"cmd":"get_summary"}'
        headers = _sign("POST", "/api/ai/channel/command", body, ts=stale_ts)
        req = _make_request("POST", "/api/ai/channel/command", headers, body)
        assert await _verify_openclaw_hmac(req) is False

    @pytest.mark.asyncio
    async def test_future_timestamp_rejected(self):
        from auth import _verify_openclaw_hmac

        future_ts = int(time.time()) + 600  # 10 minutes from now
        body = b'{"cmd":"get_summary"}'
        headers = _sign("POST", "/api/ai/channel/command", body, ts=future_ts)
        req = _make_request("POST", "/api/ai/channel/command", headers, body)
        assert await _verify_openclaw_hmac(req) is False


class TestMissingSecret:
    """No secret configured => always reject."""

    @pytest.mark.asyncio
    async def test_no_secret_rejects(self, monkeypatch):
        import auth
        monkeypatch.setattr(auth, "_openclaw_hmac_secret", lambda: "")
        from auth import _verify_openclaw_hmac

        body = b'{"cmd":"get_summary"}'
        headers = _sign("POST", "/api/ai/channel/command", body)
        req = _make_request("POST", "/api/ai/channel/command", headers, body)
        assert await _verify_openclaw_hmac(req) is False


class TestWrongSecret:
    """Wrong secret => rejected even with valid body binding."""

    @pytest.mark.asyncio
    async def test_wrong_secret_rejected(self):
        from auth import _verify_openclaw_hmac

        body = b'{"cmd":"get_summary"}'
        headers = _sign("POST", "/api/ai/channel/command", body, secret="wrong-secret")
        req = _make_request("POST", "/api/ai/channel/command", headers, body)
        assert await _verify_openclaw_hmac(req) is False
