"""Route-level security regression tests for OpenClaw direct channel (P1D).

Exercises actual FastAPI route behavior through ASGITransport — not just
helper functions.  Proves the security contract at the HTTP surface:

  1. Valid HMAC-signed write request succeeds through the full dependency chain.
  2. Tampered bodies are rejected at the route layer (P1A body-binding).
  3. Stale timestamps are rejected at the route layer.
  4. Replayed nonces are rejected at the route layer.
  5. Wrong or missing secrets are rejected at the route layer.
  6. Unsigned remote requests to protected routes are rejected.
  7. Channel status and connect-info surfaces remain honest (P1C).
"""

import hashlib
import hmac as hmac_mod
import json
import secrets
import time

import pytest
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

HMAC_SECRET = "test-route-secret-for-p1d-verification"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _serialize_json(data: dict) -> bytes:
    """Deterministic JSON serialization matching sb_query._serialize_body."""
    return json.dumps(data, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _signed_post(rc, path: str, payload: dict, **sign_kw):
    """POST with a correctly signed JSON body through the remote client."""
    body = _serialize_json(payload)
    headers = _sign("POST", path, body, **sign_kw)
    headers["Content-Type"] = "application/json"
    return rc.post(path, content=body, headers=headers)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _patch_openclaw_auth(monkeypatch):
    """Set HMAC secret and clear nonce cache for each test.

    Also pushes _OPENCLAW_STARTUP_TIME back so the startup grace period
    (which tightens max_age to 10s) does not interfere with normal tests.
    """
    import auth
    monkeypatch.setattr(auth, "_openclaw_hmac_secret", lambda: HMAC_SECRET)
    auth._openclaw_nonce_cache.clear()
    monkeypatch.setattr(auth, "_OPENCLAW_STARTUP_TIME", time.time() - 300)


# ---------------------------------------------------------------------------
# 1. Valid authenticated requests succeed
# ---------------------------------------------------------------------------

class TestAuthenticatedRequestSucceeds:
    """A correctly signed remote request passes through require_openclaw_or_local."""

    def test_signed_post_channel_command(self, remote_client):
        """Write-capable POST /api/ai/channel/command with valid HMAC → 200."""
        payload = {"cmd": "get_summary", "args": {}}
        r = _signed_post(remote_client, "/api/ai/channel/command", payload)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert data["tier"] == 1

    def test_signed_post_compact_lookup_command(self, remote_client):
        """New lookup-style commands should be remotely callable with the same auth contract."""
        payload = {"cmd": "find_flights", "args": {"callsign": "TEST123", "limit": 5}}
        r = _signed_post(remote_client, "/api/ai/channel/command", payload)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert data["tier"] == 1
        assert data["result"]["ok"] is True
        assert "results" in data["result"]["data"]

    def test_signed_post_channel_poll(self, remote_client):
        """POST /api/ai/channel/poll with valid HMAC → 200."""
        body = b""
        headers = _sign("POST", "/api/ai/channel/poll", body)
        # poll accepts empty body
        r = remote_client.post("/api/ai/channel/poll", content=body, headers=headers)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True

    def test_signed_get_ai_status(self, remote_client):
        """GET /api/ai/status with valid HMAC → 200."""
        headers = _sign("GET", "/api/ai/status")
        r = remote_client.get("/api/ai/status", headers=headers)
        assert r.status_code == 200, r.text

    def test_tools_manifest_includes_all_available_commands(self, remote_client):
        """Every advertised available command should have a tool definition the agent can load."""
        headers = _sign("GET", "/api/ai/tools")
        r = remote_client.get("/api/ai/tools", headers=headers)
        assert r.status_code == 200, r.text
        data = r.json()
        tool_names = {tool["name"] for tool in data["tools"]}
        assert set(data["available_commands"]).issubset(tool_names)


# ---------------------------------------------------------------------------
# 2. Tampered body rejected (P1A body-binding at route layer)
# ---------------------------------------------------------------------------

class TestTamperedBodyRejected:
    """Body modification after signing must be caught by the route."""

    def test_tampered_command_body_403(self, remote_client):
        """Sign with get_summary, send place_pin → 403."""
        original = _serialize_json({"cmd": "get_summary", "args": {}})
        tampered = _serialize_json({"cmd": "place_pin", "args": {"lat": 0, "lng": 0, "label": "evil"}})
        headers = _sign("POST", "/api/ai/channel/command", original)
        headers["Content-Type"] = "application/json"
        r = remote_client.post("/api/ai/channel/command", content=tampered, headers=headers)
        assert r.status_code == 403

    def test_body_injected_into_empty_post_403(self, remote_client):
        """Sign an empty-body poll, inject a body → 403."""
        headers = _sign("POST", "/api/ai/channel/poll", b"")
        injected = b'{"malicious": true}'
        r = remote_client.post("/api/ai/channel/poll", content=injected, headers=headers)
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# 3. Stale timestamp rejected
# ---------------------------------------------------------------------------

class TestStaleTimestampRejected:
    """Timestamps outside the freshness window must be rejected."""

    def test_old_timestamp_403(self, remote_client):
        """Timestamp 10 minutes in the past → 403."""
        stale_ts = int(time.time()) - 600
        payload = {"cmd": "get_summary", "args": {}}
        r = _signed_post(remote_client, "/api/ai/channel/command", payload, ts=stale_ts)
        assert r.status_code == 403

    def test_future_timestamp_403(self, remote_client):
        """Timestamp 10 minutes in the future → 403."""
        future_ts = int(time.time()) + 600
        payload = {"cmd": "get_summary", "args": {}}
        r = _signed_post(remote_client, "/api/ai/channel/command", payload, ts=future_ts)
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# 4. Replayed nonce rejected
# ---------------------------------------------------------------------------

class TestReplayedNonceRejected:
    """Reusing a nonce must be caught at the route layer."""

    def test_nonce_replay_403(self, remote_client):
        """First request succeeds, replay with same nonce → 403."""
        nonce = secrets.token_hex(16)
        payload = {"cmd": "get_summary", "args": {}}

        r1 = _signed_post(remote_client, "/api/ai/channel/command", payload, nonce=nonce)
        assert r1.status_code == 200, r1.text

        # Replay: same nonce, fresh timestamp, same body
        r2 = _signed_post(remote_client, "/api/ai/channel/command", payload, nonce=nonce)
        assert r2.status_code == 403


# ---------------------------------------------------------------------------
# 5. Wrong or missing secret rejected
# ---------------------------------------------------------------------------

class TestWrongOrMissingSecret:
    """Invalid or absent credentials must be rejected."""

    def test_wrong_secret_403(self, remote_client):
        """Request signed with a different secret → 403."""
        payload = {"cmd": "get_summary", "args": {}}
        r = _signed_post(remote_client, "/api/ai/channel/command", payload,
                         secret="wrong-secret-not-matching")
        assert r.status_code == 403

    def test_no_hmac_headers_403(self, remote_client):
        """Remote request with zero auth headers → 403."""
        body = _serialize_json({"cmd": "get_summary", "args": {}})
        r = remote_client.post(
            "/api/ai/channel/command",
            content=body,
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 403

    def test_missing_signature_header_403(self, remote_client):
        """Timestamp + nonce present but no signature → 403."""
        body = _serialize_json({"cmd": "get_summary", "args": {}})
        headers = {
            "X-SB-Timestamp": str(int(time.time())),
            "X-SB-Nonce": secrets.token_hex(16),
            "Content-Type": "application/json",
        }
        r = remote_client.post("/api/ai/channel/command", content=body, headers=headers)
        assert r.status_code == 403

    def test_no_secret_configured_403(self, remote_client, monkeypatch):
        """Server has no HMAC secret → all signed requests rejected."""
        import auth
        monkeypatch.setattr(auth, "_openclaw_hmac_secret", lambda: "")
        payload = {"cmd": "get_summary", "args": {}}
        r = _signed_post(remote_client, "/api/ai/channel/command", payload)
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# 6. Unsigned remote GET to protected routes
# ---------------------------------------------------------------------------

class TestUnsignedRemoteRejected:
    """Remote requests without any auth must not reach protected endpoints."""

    def test_unsigned_get_ai_status_403(self, remote_client):
        r = remote_client.get("/api/ai/status")
        assert r.status_code == 403

    def test_unsigned_get_ai_pins_403(self, remote_client):
        r = remote_client.get("/api/ai/pins")
        assert r.status_code == 403

    def test_unsigned_post_pins_403(self, remote_client):
        body = _serialize_json({"lat": 0, "lng": 0, "label": "x", "category": "custom"})
        r = remote_client.post(
            "/api/ai/pins",
            content=body,
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# 7. P1C honesty at the route/API surface
# ---------------------------------------------------------------------------

class TestChannelStatusHonestyRoute:
    """GET /api/ai/channel/status must report honest tier info.

    This route is local-operator only, so it uses the default local client.
    """

    def test_channel_status_tier_1(self, client):
        r = client.get("/api/ai/channel/status")
        assert r.status_code == 200
        data = r.json()
        assert data["tier"] == 1
        assert data["forward_secrecy"] is False
        assert data["sealed_sender"] is False
        assert "HMAC" in data["reason"]
        assert "not" in data["reason"].lower() and "encrypt" in data["reason"].lower()


class TestConnectInfoHonestyRoute:
    """GET /api/ai/connect-info must honestly describe transport modes."""

    def test_connect_info_wormhole_not_enabled(self, client):
        r = client.get("/api/ai/connect-info")
        assert r.status_code == 200
        data = r.json()
        modes = data.get("connection_modes", {})

        direct = modes.get("direct", {})
        assert direct.get("enabled") is True
        assert "HMAC" in direct.get("description", "")

        wormhole = modes.get("wormhole", {})
        assert wormhole.get("enabled") is False
        desc = wormhole.get("description", "").lower()
        assert "not yet implemented" in desc or "planned" in desc

    def test_connect_info_remote_rejected(self, remote_client):
        """connect-info is local-operator only — remote access must be blocked."""
        r = remote_client.get("/api/ai/connect-info")
        assert r.status_code == 403
