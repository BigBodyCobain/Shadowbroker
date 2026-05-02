"""Sprint 1B: Debug/Admin Hardening Closure — regression tests.

Covers:
- _validate_admin_startup() exits on key < 32 chars in non-debug mode
- _validate_admin_startup() warns (not exits) on key < 32 chars in debug mode
- _validate_admin_startup() passes on key >= 32 chars
- _validate_insecure_admin_startup() exits if ALLOW_INSECURE_ADMIN=True and MESH_DEBUG_MODE=False
- _validate_insecure_admin_startup() passes if ALLOW_INSECURE_ADMIN=True and MESH_DEBUG_MODE=True
- _validate_insecure_admin_startup() passes if ALLOW_INSECURE_ADMIN=False regardless of debug mode
- env_check.py validate_env: CRITICAL when ADMIN_KEY missing + ALLOW_INSECURE_ADMIN=True
- env_check.py validate_env: WARNING (not CRITICAL) when ADMIN_KEY missing + ALLOW_INSECURE_ADMIN=False
"""

import logging
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# _validate_admin_startup — 32-char minimum in non-debug mode
# ---------------------------------------------------------------------------

class TestValidateAdminStartup:
    def _run(self, key: str, debug_mode: bool):
        from auth import _validate_admin_startup

        mock_settings = MagicMock()
        mock_settings.MESH_DEBUG_MODE = debug_mode

        with patch("auth._current_admin_key", return_value=key), \
             patch("auth.get_settings", return_value=mock_settings):
            _validate_admin_startup()

    def test_key_31_chars_non_debug_exits(self):
        with pytest.raises(SystemExit) as exc_info:
            self._run("a" * 31, debug_mode=False)
        assert exc_info.value.code == 1

    def test_key_16_chars_non_debug_exits(self):
        with pytest.raises(SystemExit) as exc_info:
            self._run("a" * 16, debug_mode=False)
        assert exc_info.value.code == 1

    def test_key_1_char_non_debug_exits(self):
        with pytest.raises(SystemExit) as exc_info:
            self._run("x", debug_mode=False)
        assert exc_info.value.code == 1

    def test_key_32_chars_non_debug_passes(self):
        self._run("a" * 32, debug_mode=False)  # no exception

    def test_key_64_chars_non_debug_passes(self):
        self._run("a" * 64, debug_mode=False)  # no exception

    def test_key_31_chars_debug_warns_not_exits(self):
        # In debug mode a short key should log a warning but not sys.exit
        self._run("a" * 31, debug_mode=True)  # no exception

    def test_key_8_chars_debug_warns_not_exits(self):
        self._run("a" * 8, debug_mode=True)  # no exception

    def test_key_32_chars_debug_passes(self):
        self._run("a" * 32, debug_mode=True)  # no exception

    def test_empty_key_non_debug_passes(self):
        # Empty key = no key set; function warns but does NOT exit (endpoints simply lock out)
        self._run("", debug_mode=False)  # no exception


# ---------------------------------------------------------------------------
# _validate_insecure_admin_startup — blocks ALLOW_INSECURE_ADMIN in non-debug
# ---------------------------------------------------------------------------

class TestValidateInsecureAdminStartup:
    def _run(self, allow_insecure: bool, debug_mode: bool):
        from auth import _validate_insecure_admin_startup

        mock_settings = MagicMock()
        mock_settings.ALLOW_INSECURE_ADMIN = allow_insecure
        mock_settings.MESH_DEBUG_MODE = debug_mode

        with patch("auth.get_settings", return_value=mock_settings):
            _validate_insecure_admin_startup()

    def test_insecure_true_debug_false_exits(self):
        with pytest.raises(SystemExit) as exc_info:
            self._run(allow_insecure=True, debug_mode=False)
        assert exc_info.value.code == 1

    def test_insecure_true_debug_true_passes(self):
        self._run(allow_insecure=True, debug_mode=True)  # no exception

    def test_insecure_false_debug_false_passes(self):
        self._run(allow_insecure=False, debug_mode=False)  # no exception

    def test_insecure_false_debug_true_passes(self):
        self._run(allow_insecure=False, debug_mode=True)  # no exception


# ---------------------------------------------------------------------------
# env_check.py validate_env — inverted-severity fix
# ---------------------------------------------------------------------------

class TestEnvCheckAdminKeySeverity:
    """Verify that the ADMIN_KEY critical-warn severity is correctly oriented.

    CRITICAL must fire when ALLOW_INSECURE_ADMIN=True (endpoints exposed).
    Only WARNING should fire when ALLOW_INSECURE_ADMIN=False (endpoints locked out).

    Tests exercise only the _CRITICAL_WARN loop in validate_env; _audit_security_config
    is patched to avoid filesystem I/O from _ensure_dm_token_pepper.
    """

    def _run_validate_env(self, admin_key: str, allow_insecure: bool):
        """Run validate_env and return (critical_fired, warning_fired)."""
        from services.env_check import validate_env

        mock_settings = MagicMock()
        mock_settings.ADMIN_KEY = admin_key
        mock_settings.ALLOW_INSECURE_ADMIN = allow_insecure
        # Safe defaults for attributes the _REQUIRED loop and _CRITICAL_WARN loop read
        mock_settings.configure_mock(**{
            "MESH_DEBUG_MODE": False,
            "MESH_STRICT_SIGNATURES": True,
            "MESH_PEER_PUSH_SECRET": "unique-per-deployment-secret-at-least-32chars",
            "MESH_RNS_ENABLED": False,
            "MESH_RELAY_PEERS": "",
            "MESH_RNS_PEERS": "",
        })

        critical_fired = False
        warning_fired = False

        class CapturingHandler(logging.Handler):
            def emit(self, record):
                nonlocal critical_fired, warning_fired
                if record.levelno >= logging.CRITICAL:
                    critical_fired = True
                elif record.levelno >= logging.WARNING:
                    warning_fired = True

        env_logger = logging.getLogger("services.env_check")
        handler = CapturingHandler()
        env_logger.addHandler(handler)
        try:
            with patch("services.env_check.get_settings", return_value=mock_settings), \
                 patch("services.env_check._audit_security_config"):
                try:
                    validate_env(strict=False)
                except SystemExit:
                    pass
        finally:
            env_logger.removeHandler(handler)

        return critical_fired, warning_fired

    def test_no_admin_key_insecure_true_fires_critical(self):
        critical, warning = self._run_validate_env(admin_key="", allow_insecure=True)
        assert critical is True, "Expected CRITICAL when ADMIN_KEY missing and ALLOW_INSECURE_ADMIN=True"

    def test_no_admin_key_insecure_false_no_critical(self):
        critical, warning = self._run_validate_env(admin_key="", allow_insecure=False)
        assert critical is False, "CRITICAL must NOT fire when ALLOW_INSECURE_ADMIN=False (endpoints locked)"

    def test_no_admin_key_insecure_false_fires_warning(self):
        critical, warning = self._run_validate_env(admin_key="", allow_insecure=False)
        assert warning is True, "Expected WARNING when ADMIN_KEY missing and ALLOW_INSECURE_ADMIN=False"
