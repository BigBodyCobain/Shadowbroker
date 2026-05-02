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
    def test_empty_pepper_auto_generates(self, caplog, tmp_path, monkeypatch):
        os.environ.pop("MESH_DM_TOKEN_PEPPER", None)
        get_settings.cache_clear()
        from services import env_check

        monkeypatch.setattr(env_check, "_PEPPER_FILE", tmp_path / "dm_token_pepper.key")

        with caplog.at_level(logging.WARNING):
            env_check._audit_security_config(get_settings())

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


class TestPeerSecretEnforcement:
    """P1B: MESH_PEER_PUSH_SECRET is mandatory when relay/RNS peers are configured."""

    def test_empty_secret_with_peers_exits_in_strict_mode(self):
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

            with pytest.raises(SystemExit) as exc_info:
                validate_env(strict=True)
            assert exc_info.value.code == 1

    def test_placeholder_secret_with_peers_exits_in_strict_mode(self):
        with patch.dict(
            os.environ,
            {
                "MESH_RELAY_PEERS": "https://peer.example",
                "MESH_PEER_PUSH_SECRET": "change-me",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            from services.env_check import validate_env

            with pytest.raises(SystemExit) as exc_info:
                validate_env(strict=True)
            assert exc_info.value.code == 1

    def test_short_secret_with_peers_exits_in_strict_mode(self):
        with patch.dict(
            os.environ,
            {
                "MESH_RELAY_PEERS": "https://peer.example",
                "MESH_PEER_PUSH_SECRET": "tooshort",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            from services.env_check import validate_env

            with pytest.raises(SystemExit) as exc_info:
                validate_env(strict=True)
            assert exc_info.value.code == 1

    def test_empty_secret_with_rns_peers_exits_in_strict_mode(self):
        with patch.dict(
            os.environ,
            {
                "MESH_RNS_PEERS": "rns://some-peer-hash",
                "MESH_PEER_PUSH_SECRET": "",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            from services.env_check import validate_env

            with pytest.raises(SystemExit) as exc_info:
                validate_env(strict=True)
            assert exc_info.value.code == 1

    def test_empty_secret_with_rns_enabled_exits_in_strict_mode(self):
        with patch.dict(
            os.environ,
            {
                "MESH_RNS_ENABLED": "true",
                "MESH_PEER_PUSH_SECRET": "",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            from services.env_check import validate_env

            with pytest.raises(SystemExit) as exc_info:
                validate_env(strict=True)
            assert exc_info.value.code == 1

    def test_valid_secret_with_peers_passes(self, caplog):
        with patch.dict(
            os.environ,
            {
                "MESH_RELAY_PEERS": "https://peer.example",
                "MESH_PEER_PUSH_SECRET": "a-valid-secret-at-least-16-chars-long",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            from services.env_check import validate_env

            with caplog.at_level(logging.WARNING):
                result = validate_env(strict=True)

            assert result is True
            assert "MESH_PEER_PUSH_SECRET is invalid" not in caplog.text

    def test_no_peers_no_secret_passes(self, caplog):
        """Default posture: no peers configured, no secret needed."""
        with patch.dict(
            os.environ,
            {
                "MESH_RELAY_PEERS": "",
                "MESH_RNS_PEERS": "",
                "MESH_RNS_ENABLED": "false",
                "MESH_PEER_PUSH_SECRET": "",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            from services.env_check import validate_env

            with caplog.at_level(logging.WARNING):
                result = validate_env(strict=True)

            assert result is True
            assert "MESH_PEER_PUSH_SECRET is invalid" not in caplog.text

    def test_empty_secret_with_peers_returns_false_in_nonstrict_mode(self, caplog):
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

            with caplog.at_level(logging.ERROR):
                result = validate_env(strict=False)

            assert result is False
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

    def test_placeholder_peer_secret_is_flagged_in_audit(self, caplog):
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


class TestRawSecureStorageFallbackGuard:
    def test_raw_fallback_without_ack_exits_in_strict_mode(self, monkeypatch):
        from services import env_check

        monkeypatch.setattr(env_check, "_raw_secure_storage_fallback_requested", lambda _snapshot: True)
        monkeypatch.setattr(env_check, "_raw_secure_storage_fallback_missing_ack", lambda _snapshot: True)
        monkeypatch.setenv("MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK", "true")
        monkeypatch.delenv("MESH_ACK_RAW_FALLBACK_AT_OWN_RISK", raising=False)
        monkeypatch.delenv("MESH_SECURE_STORAGE_SECRET", raising=False)
        monkeypatch.setenv("MESH_DM_TOKEN_PEPPER", "valid-test-pepper-value")
        get_settings.cache_clear()

        with pytest.raises(SystemExit) as exc_info:
            env_check.validate_env(strict=True)

        assert exc_info.value.code == 1

    def test_raw_fallback_without_ack_returns_false_in_nonstrict_mode(self, monkeypatch, caplog):
        from services import env_check

        monkeypatch.setattr(env_check, "_raw_secure_storage_fallback_requested", lambda _snapshot: True)
        monkeypatch.setattr(env_check, "_raw_secure_storage_fallback_missing_ack", lambda _snapshot: True)
        monkeypatch.setenv("MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK", "true")
        monkeypatch.delenv("MESH_ACK_RAW_FALLBACK_AT_OWN_RISK", raising=False)
        monkeypatch.delenv("MESH_SECURE_STORAGE_SECRET", raising=False)
        monkeypatch.setenv("MESH_DM_TOKEN_PEPPER", "valid-test-pepper-value")
        get_settings.cache_clear()

        with caplog.at_level(logging.ERROR):
            result = env_check.validate_env(strict=False)

        assert result is False
        assert "MESH_ACK_RAW_FALLBACK_AT_OWN_RISK=true" in caplog.text

    def test_raw_fallback_with_ack_passes_strict_mode(self, monkeypatch, caplog):
        from services import env_check

        monkeypatch.setattr(env_check, "_raw_secure_storage_fallback_requested", lambda _snapshot: True)
        monkeypatch.setattr(env_check, "_raw_secure_storage_fallback_missing_ack", lambda _snapshot: False)
        monkeypatch.setenv("MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK", "true")
        monkeypatch.setenv("MESH_ACK_RAW_FALLBACK_AT_OWN_RISK", "true")
        monkeypatch.delenv("MESH_SECURE_STORAGE_SECRET", raising=False)
        monkeypatch.setenv("MESH_DM_TOKEN_PEPPER", "valid-test-pepper-value")
        get_settings.cache_clear()

        with caplog.at_level(logging.WARNING):
            result = env_check.validate_env(strict=True)

        assert result is True
        assert "with MESH_ACK_RAW_FALLBACK_AT_OWN_RISK=true leaves Wormhole keys in raw local files" in caplog.text

    def test_security_posture_reports_missing_raw_fallback_ack(self, monkeypatch):
        from services import env_check

        monkeypatch.setattr(env_check, "_raw_secure_storage_fallback_requested", lambda _snapshot: True)
        monkeypatch.setattr(env_check, "_raw_secure_storage_fallback_missing_ack", lambda _snapshot: True)
        monkeypatch.setenv("MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK", "true")
        monkeypatch.delenv("MESH_ACK_RAW_FALLBACK_AT_OWN_RISK", raising=False)
        get_settings.cache_clear()

        warnings = env_check.get_security_posture_warnings(get_settings())

        assert any(
            "MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK=true without MESH_ACK_RAW_FALLBACK_AT_OWN_RISK=true"
            in item
            for item in warnings
        )


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


class TestDmMetadataPersistenceWarnings:
    def test_metadata_persist_without_ack_logs_memory_only_warning(self, caplog):
        with patch.dict(
            os.environ,
            {
                "MESH_DM_METADATA_PERSIST": "true",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            from services.env_check import _audit_security_config

            with caplog.at_level(logging.WARNING):
                _audit_security_config(get_settings())

            assert "MESH_DM_METADATA_PERSIST=true without MESH_DM_METADATA_PERSIST_ACKNOWLEDGE=true" in caplog.text

    def test_metadata_persist_with_ack_logs_disk_warning(self, caplog):
        with patch.dict(
            os.environ,
            {
                "MESH_DM_METADATA_PERSIST": "true",
                "MESH_DM_METADATA_PERSIST_ACKNOWLEDGE": "true",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            from services.env_check import _audit_security_config

            with caplog.at_level(logging.WARNING):
                _audit_security_config(get_settings())

            assert "MESH_DM_METADATA_PERSIST=true — DM request/self mailbox binding metadata will be written to disk" in caplog.text

    def test_security_posture_warnings_include_memory_only_warning_without_ack(self):
        with patch.dict(
            os.environ,
            {
                "MESH_DM_METADATA_PERSIST": "true",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            from services.env_check import get_security_posture_warnings

            warnings = get_security_posture_warnings(get_settings())

            assert any(
                "MESH_DM_METADATA_PERSIST=true without MESH_DM_METADATA_PERSIST_ACKNOWLEDGE=true" in item
                for item in warnings
            )

    def test_security_posture_warnings_include_metadata_persist_when_acknowledged(self):
        with patch.dict(
            os.environ,
            {
                "MESH_DM_METADATA_PERSIST": "true",
                "MESH_DM_METADATA_PERSIST_ACKNOWLEDGE": "true",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            from services.env_check import get_security_posture_warnings

            warnings = get_security_posture_warnings(get_settings())

            assert any(
                "MESH_DM_METADATA_PERSIST=true — DM request/self mailbox binding metadata will be written to disk"
                in item
                for item in warnings
            )


class TestPrivateClearnetFallbackWarnings:
    def test_clearnet_fallback_without_ack_warns_blocked_until_acknowledged(self, caplog):
        with patch.dict(
            os.environ,
            {
                "MESH_PRIVATE_CLEARNET_FALLBACK": "allow",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            from services.env_check import _audit_security_config

            with caplog.at_level(logging.WARNING):
                _audit_security_config(get_settings())

            assert (
                "MESH_PRIVATE_CLEARNET_FALLBACK=allow without MESH_PRIVATE_CLEARNET_FALLBACK_ACKNOWLEDGE=true"
                in caplog.text
            )

    def test_clearnet_fallback_with_ack_warns_active_downgrade(self, caplog):
        with patch.dict(
            os.environ,
            {
                "MESH_PRIVATE_CLEARNET_FALLBACK": "allow",
                "MESH_PRIVATE_CLEARNET_FALLBACK_ACKNOWLEDGE": "true",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            from services.env_check import _audit_security_config

            with caplog.at_level(logging.WARNING):
                _audit_security_config(get_settings())

            assert (
                "MESH_PRIVATE_CLEARNET_FALLBACK=allow with MESH_PRIVATE_CLEARNET_FALLBACK_ACKNOWLEDGE=true"
                in caplog.text
            )

    def test_security_posture_reports_blocked_until_acknowledged(self):
        with patch.dict(
            os.environ,
            {
                "MESH_PRIVATE_CLEARNET_FALLBACK": "allow",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            from services.env_check import get_security_posture_warnings

            warnings = get_security_posture_warnings(get_settings())

            assert any(
                "MESH_PRIVATE_CLEARNET_FALLBACK=allow without MESH_PRIVATE_CLEARNET_FALLBACK_ACKNOWLEDGE=true"
                in item
                for item in warnings
            )

    def test_security_posture_reports_active_clearnet_downgrade_with_ack(self):
        with patch.dict(
            os.environ,
            {
                "MESH_PRIVATE_CLEARNET_FALLBACK": "allow",
                "MESH_PRIVATE_CLEARNET_FALLBACK_ACKNOWLEDGE": "true",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            from services.env_check import get_security_posture_warnings

            warnings = get_security_posture_warnings(get_settings())

            assert any(
                "MESH_PRIVATE_CLEARNET_FALLBACK=allow with MESH_PRIVATE_CLEARNET_FALLBACK_ACKNOWLEDGE=true"
                in item
                for item in warnings
            )


class TestLegacyDmGetWarnings:
    def test_compatibility_snapshot_marks_legacy_dm_get_override(self):
        with patch.dict(
            os.environ,
            {
                "MESH_DEV_ALLOW_LEGACY_COMPAT": "true",
                "MESH_ALLOW_LEGACY_DM_GET_UNTIL": "2099-01-01",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            from services.mesh.mesh_compatibility import compatibility_status_snapshot

            snapshot = compatibility_status_snapshot()

            assert snapshot["sunset"]["legacy_dm_get"]["status"] == "dev_migration_override"
            assert snapshot["sunset"]["legacy_dm_get"]["override_until"] == "2099-01-01"

    def test_compatibility_snapshot_marks_compat_dm_invite_import_override(self):
        with patch.dict(
            os.environ,
            {
                "MESH_DEV_ALLOW_LEGACY_COMPAT": "true",
                "MESH_ALLOW_COMPAT_DM_INVITE_IMPORT_UNTIL": "2099-01-01",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            from services.mesh.mesh_compatibility import compatibility_status_snapshot

            snapshot = compatibility_status_snapshot()

            assert snapshot["sunset"]["compat_dm_invite_import"]["status"] == "dev_migration_override"
            assert snapshot["sunset"]["compat_dm_invite_import"]["override_until"] == "2099-01-01"

    def test_compatibility_snapshot_marks_legacy_dm1_override(self):
        with patch.dict(
            os.environ,
            {
                "MESH_DEV_ALLOW_LEGACY_COMPAT": "true",
                "MESH_ALLOW_LEGACY_DM1_UNTIL": "2099-01-01",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            from services.mesh.mesh_compatibility import compatibility_status_snapshot

            snapshot = compatibility_status_snapshot()

            assert snapshot["sunset"]["legacy_dm1"]["status"] == "dev_migration_override"
            assert snapshot["sunset"]["legacy_dm1"]["override_until"] == "2099-01-01"


class TestLegacyDmSignatureCompatWarnings:
    def test_security_posture_reports_legacy_dm_signature_compat(self):
        with patch.dict(
            os.environ,
            {
                "MESH_DEV_ALLOW_LEGACY_COMPAT": "true",
                "MESH_ALLOW_LEGACY_DM_SIGNATURE_COMPAT_UNTIL": "2099-01-01",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            from services.env_check import get_security_posture_warnings

            warnings = get_security_posture_warnings(get_settings())

            assert any(
                "MESH_ALLOW_LEGACY_DM_SIGNATURE_COMPAT_UNTIL" in item
                for item in warnings
            )

    def test_audit_logs_legacy_dm_signature_compat_warning(self, caplog):
        with patch.dict(
            os.environ,
            {
                "MESH_DEV_ALLOW_LEGACY_COMPAT": "true",
                "MESH_ALLOW_LEGACY_DM_SIGNATURE_COMPAT_UNTIL": "2099-01-01",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            from services.env_check import _audit_security_config

            with caplog.at_level(logging.WARNING):
                _audit_security_config(get_settings())

            assert "MESH_ALLOW_LEGACY_DM_SIGNATURE_COMPAT_UNTIL" in caplog.text


class TestGatePlaintextPersistWarnings:
    def test_security_posture_reports_active_gate_plaintext_persist(self):
        with patch.dict(
            os.environ,
            {
                "MESH_GATE_PLAINTEXT_PERSIST": "true",
                "MESH_GATE_PLAINTEXT_PERSIST_ACKNOWLEDGE": "true",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            from services.env_check import get_security_posture_warnings

            warnings = get_security_posture_warnings(get_settings())

            assert any(
                "MESH_GATE_PLAINTEXT_PERSIST=true with MESH_GATE_PLAINTEXT_PERSIST_ACKNOWLEDGE=true"
                in item
                for item in warnings
            )


class TestGateRecoveryEnvelopeWarnings:
    def test_security_posture_reports_active_gate_recovery_envelope_runtime(self):
        with patch.dict(
            os.environ,
            {
                "MESH_GATE_RECOVERY_ENVELOPE_ENABLE": "true",
                "MESH_GATE_RECOVERY_ENVELOPE_ENABLE_ACKNOWLEDGE": "true",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            from services.env_check import get_security_posture_warnings

            warnings = get_security_posture_warnings(get_settings())

            assert any(
                "MESH_GATE_RECOVERY_ENVELOPE_ENABLE=true with MESH_GATE_RECOVERY_ENVELOPE_ENABLE_ACKNOWLEDGE=true"
                in item
                for item in warnings
            )


class TestReleaseAttestationWarnings:
    def test_security_posture_reports_missing_explicit_release_attestation(self, tmp_path):
        with patch.dict(
            os.environ,
            {
                "MESH_RELEASE_ATTESTATION_PATH": str(tmp_path / "missing_release_attestation.json"),
                "MESH_RELEASE_DM_RELAY_SECURITY_SUITE_GREEN": "false",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            from services.env_check import get_security_posture_warnings

            warnings = get_security_posture_warnings(get_settings())

            assert any(
                "MESH_RELEASE_ATTESTATION_PATH is set but the release attestation file is missing"
                in item
                for item in warnings
            )

    def test_security_posture_reports_manual_release_attestation_env_without_file(
        self, monkeypatch, tmp_path
    ):
        with patch.dict(
            os.environ,
            {
                "MESH_RELEASE_ATTESTATION_PATH": "",
                "MESH_RELEASE_DM_RELAY_SECURITY_SUITE_GREEN": "true",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            from services import env_check

            monkeypatch.setattr(
                env_check,
                "_DEFAULT_RELEASE_ATTESTATION_PATH",
                tmp_path / "release_attestation.json",
            )

            warnings = env_check.get_security_posture_warnings(get_settings())

            assert any(
                "MESH_RELEASE_DM_RELAY_SECURITY_SUITE_GREEN=true without a file-based release attestation"
                in item
                for item in warnings
            )

    def test_audit_logs_missing_release_attestation_warning(self, monkeypatch, tmp_path, caplog):
        with patch.dict(
            os.environ,
            {
                "MESH_RELEASE_ATTESTATION_PATH": "",
                "MESH_RELEASE_DM_RELAY_SECURITY_SUITE_GREEN": "false",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            from services import env_check

            monkeypatch.setattr(
                env_check,
                "_DEFAULT_RELEASE_ATTESTATION_PATH",
                tmp_path / "release_attestation.json",
            )

            with caplog.at_level(logging.WARNING):
                env_check._audit_security_config(get_settings())

            assert "No file-based Sprint 8 release attestation is staged" in caplog.text
