"""Tests for security config guardrails in env_check._audit_security_config."""

import logging
import os
from unittest.mock import patch

import pytest

# Reset pydantic settings cache before importing, so env overrides take effect
os.environ.pop("MESH_DM_TOKEN_PEPPER", None)

from services.config import get_settings, Settings


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """Bust the lru_cache so each test gets fresh Settings."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _clean_pepper_env():
    """Remove any auto-generated pepper between tests."""
    os.environ.pop("MESH_DM_TOKEN_PEPPER", None)
    yield
    os.environ.pop("MESH_DM_TOKEN_PEPPER", None)


class TestInsecureAdminWarning:
    def test_allow_insecure_admin_without_key_logs_critical(self, caplog):
        with patch.dict(os.environ, {"ALLOW_INSECURE_ADMIN": "true", "ADMIN_KEY": ""}):
            get_settings.cache_clear()
            from services.env_check import _audit_security_config

            with caplog.at_level(logging.CRITICAL):
                _audit_security_config(get_settings())

            assert "ALLOW_INSECURE_ADMIN=true with no ADMIN_KEY" in caplog.text
            assert "completely unauthenticated" in caplog.text

    def test_admin_key_present_no_warning(self, caplog):
        with patch.dict(
            os.environ, {"ALLOW_INSECURE_ADMIN": "true", "ADMIN_KEY": "secret123"}
        ):
            get_settings.cache_clear()
            from services.env_check import _audit_security_config

            with caplog.at_level(logging.CRITICAL):
                _audit_security_config(get_settings())

            assert "ALLOW_INSECURE_ADMIN=true with no ADMIN_KEY" not in caplog.text


class TestSignatureConfigWarnings:
    def test_non_strict_logs_warning(self, caplog):
        with patch.dict(os.environ, {"MESH_STRICT_SIGNATURES": "false"}):
            get_settings.cache_clear()
            from services.env_check import _audit_security_config

            with caplog.at_level(logging.WARNING):
                _audit_security_config(get_settings())

            assert "MESH_STRICT_SIGNATURES=false" in caplog.text


class TestTokenPepperAutoGeneration:
    def test_empty_pepper_auto_generates(self, caplog):
        os.environ.pop("MESH_DM_TOKEN_PEPPER", None)
        get_settings.cache_clear()
        from services.env_check import _audit_security_config

        with caplog.at_level(logging.WARNING):
            _audit_security_config(get_settings())

        generated = os.environ.get("MESH_DM_TOKEN_PEPPER", "")
        assert len(generated) == 64  # 32 bytes hex
        assert "Auto-generated a random pepper" in caplog.text

    def test_existing_pepper_preserved(self, caplog):
        os.environ["MESH_DM_TOKEN_PEPPER"] = "my-secret-pepper"
        get_settings.cache_clear()
        from services.env_check import _audit_security_config

        with caplog.at_level(logging.WARNING):
            _audit_security_config(get_settings())

        assert os.environ["MESH_DM_TOKEN_PEPPER"] == "my-secret-pepper"
        assert "Auto-generated" not in caplog.text


class TestPeerSecretWarnings:
    def test_missing_peer_secret_only_warns_and_does_not_fail_validation(self, caplog):
        with patch.dict(
            os.environ,
            {
                "MESH_RELAY_PEERS": "https://peer.example",
                "MESH_PEER_PUSH_SECRET": "",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            from services.env_check import validate_env

            with caplog.at_level(logging.WARNING):
                result = validate_env(strict=True)

            assert result is True
            assert "MESH_PEER_PUSH_SECRET is invalid (empty)" in caplog.text

    def test_security_posture_warnings_include_missing_peer_secret(self):
        with patch.dict(
            os.environ,
            {
                "MESH_RELAY_PEERS": "https://peer.example",
                "MESH_PEER_PUSH_SECRET": "",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            from services.env_check import get_security_posture_warnings

            warnings = get_security_posture_warnings(get_settings())

            assert any("MESH_PEER_PUSH_SECRET is invalid (empty)" in item for item in warnings)

    def test_placeholder_peer_secret_is_flagged(self, caplog):
        with patch.dict(
            os.environ,
            {
                "MESH_RELAY_PEERS": "https://peer.example",
                "MESH_PEER_PUSH_SECRET": "change-me",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            from services.env_check import _audit_security_config

            with caplog.at_level(logging.WARNING):
                _audit_security_config(get_settings())

            assert "MESH_PEER_PUSH_SECRET is invalid (placeholder)" in caplog.text


class TestCoverTrafficWarnings:
    def test_disabled_cover_traffic_logs_warning_when_rns_enabled(self, caplog):
        with patch.dict(
            os.environ,
            {
                "MESH_RNS_ENABLED": "true",
                "MESH_RNS_COVER_INTERVAL_S": "0",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            from services.env_check import _audit_security_config

            with caplog.at_level(logging.WARNING):
                _audit_security_config(get_settings())

            assert "MESH_RNS_COVER_INTERVAL_S<=0 disables background RNS cover traffic" in caplog.text

    def test_security_posture_warnings_include_disabled_cover_traffic(self):
        with patch.dict(
            os.environ,
            {
                "MESH_RNS_ENABLED": "true",
                "MESH_RNS_COVER_INTERVAL_S": "0",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            from services.env_check import get_security_posture_warnings

            warnings = get_security_posture_warnings(get_settings())

            assert any("MESH_RNS_COVER_INTERVAL_S<=0" in item for item in warnings)
