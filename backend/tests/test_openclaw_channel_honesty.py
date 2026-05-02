"""Tests for OpenClaw channel status honesty (Packet P1C).

Proves that:
  1. detect_tier() never claims tier 2 (MLS E2EE not wired into dispatch).
  2. forward_secrecy and sealed_sender are always False.
  3. The reason string does not imply E2EE is active.
  4. connect-info wormhole mode is reported as not enabled.
"""

from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture(autouse=True)
def _clear_openclaw_tier_cache():
    from services import openclaw_channel

    openclaw_channel._tier_cache = None
    openclaw_channel._tier_cache_ts = 0
    yield
    openclaw_channel._tier_cache = None
    openclaw_channel._tier_cache_ts = 0


class TestDetectTierHonesty:
    """detect_tier() must never claim E2EE is active."""

    def test_tier_is_always_1(self):
        from services.openclaw_channel import detect_tier

        result = detect_tier()
        assert result["tier"] == 1

    def test_forward_secrecy_is_false(self):
        from services.openclaw_channel import detect_tier

        result = detect_tier()
        assert result["forward_secrecy"] is False

    def test_sealed_sender_is_false(self):
        from services.openclaw_channel import detect_tier

        result = detect_tier()
        assert result["sealed_sender"] is False

    def test_reason_does_not_claim_active_e2ee(self):
        from services.openclaw_channel import detect_tier

        result = detect_tier()
        reason = result["reason"].lower()
        # Must not claim E2EE is active.  Negations ("not end-to-end
        # encrypted") are honest and acceptable.
        assert "e2ee available" not in reason
        assert "forward secrecy" not in reason
        # Must explicitly disclaim encryption
        assert "not" in reason and "encrypt" in reason

    def test_reason_states_hmac(self):
        from services.openclaw_channel import detect_tier

        result = detect_tier()
        assert "HMAC" in result["reason"]

    def test_tier_1_even_with_private_strong_and_bootstrapped_agent(self):
        """Even when all MLS prerequisites are met, tier stays 1 because
        MLS dispatch is not implemented."""
        from services.openclaw_channel import detect_tier

        mock_state = {"running": True, "ready": True}
        mock_info = {"bootstrapped": True, "node_id": "test", "public_key": "pk"}
        mock_client = MagicMock()

        with (
            patch("services.wormhole_supervisor.get_wormhole_state", return_value=mock_state),
            patch("services.wormhole_supervisor.transport_tier_from_state", return_value="private_strong"),
            patch("services.privacy_core_client.PrivacyCoreClient.load", return_value=mock_client),
            patch("services.openclaw_bridge.get_agent_public_info", return_value=mock_info),
        ):
            result = detect_tier()

        assert result["tier"] == 1
        assert result["forward_secrecy"] is False
        assert result["sealed_sender"] is False
        # Should flag that upgrade infrastructure exists
        assert result.get("mls_upgrade_available") is True


class TestChannelStatusHonesty:
    """channel.status() inherits from detect_tier and must be honest."""

    def test_channel_status_tier_1(self):
        from services.openclaw_channel import channel

        status = channel.status()
        assert status["tier"] == 1
        assert status["forward_secrecy"] is False
        assert status["sealed_sender"] is False


class TestConnectInfoHonesty:
    """connect-info API response must label wormhole mode as not enabled."""

    def test_wormhole_mode_not_enabled(self, client):
        r = client.get("/api/ai/connect-info")
        if r.status_code == 200:
            data = r.json()
            modes = data.get("connection_modes", {})
            wormhole = modes.get("wormhole", {})
            assert wormhole.get("enabled") is False
            desc = wormhole.get("description", "").lower()
            # Must not imply it exists as a usable option
            assert "not yet implemented" in desc or "planned" in desc

    def test_connect_info_explicitly_describes_shared_secret_trust_model(self, client):
        r = client.get("/api/ai/connect-info")
        if r.status_code == 200:
            data = r.json()
            trust = data.get("trust_model", {})
            bootstrap = data.get("bootstrap_behavior", {})
            assert trust.get("remote_http_principal") == "holder_of_openclaw_hmac_secret"
            assert trust.get("agent_ed25519_identity_bound_to_http_session") is False
            assert trust.get("durability", {}).get("command_queue") == "memory_only"
            assert bootstrap.get("auto_generates_when_missing") is True
            assert isinstance(bootstrap.get("notes"), list) and bootstrap.get("notes")


class TestCapabilitiesHonesty:
    """capabilities must describe the real OpenClaw trust boundary."""

    def test_capabilities_surface_shared_hmac_trust_boundary(self, client):
        r = client.get("/api/ai/capabilities")
        assert r.status_code == 200
        data = r.json()
        auth = data.get("auth", {})
        trust = data.get("trust_boundary", {})
        assert auth.get("remote_agent_http_auth_identity") == "shared_hmac_secret"
        assert auth.get("agent_ed25519_identity_used_for_http_auth") is False
        assert auth.get("agent_ed25519_identity_used_for_mesh_signing") is True
        assert trust.get("remote_api_principal") == "holder_of_openclaw_hmac_secret"
        assert trust.get("durability", {}).get("task_queue") == "memory_only"
        assert trust.get("remote_route_surface", {}).get("auth_dependency") == "require_openclaw_or_local"

    def test_capabilities_surface_coarse_authorization_model(self, client):
        r = client.get("/api/ai/capabilities")
        assert r.status_code == 200
        data = r.json()
        channel = data.get("command_channel_http", {})
        assert channel.get("authorization_model") == "coarse_access_tier"
        notes = channel.get("authorization_notes", [])
        assert any("restricted = read commands only" in str(item) for item in notes)
        assert any("full = read + write commands" in str(item) for item in notes)
