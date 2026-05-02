"""P0 security regression tests.

Covers:
- _is_local_or_docker() no longer trusts RFC-1918 ranges
- require_local_operator rejects LAN IPs without an admin key
- _validate_peer_push_secret() exits on known-compromised default
- _validate_peer_push_secret() warns but continues on empty secret
"""

import sys
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# _is_local_or_docker — loopback-only after P0 fix
# ---------------------------------------------------------------------------

class TestIsLocalOrDocker:
    def _fn(self):
        from auth import _is_local_or_docker
        return _is_local_or_docker

    def test_loopback_ipv4_trusted(self):
        assert self._fn()("127.0.0.1") is True

    def test_loopback_ipv6_trusted(self):
        assert self._fn()("::1") is True

    def test_localhost_string_trusted(self):
        assert self._fn()("localhost") is True

    def test_rfc1918_10_not_trusted(self):
        assert self._fn()("10.0.0.1") is False

    def test_rfc1918_172_not_trusted(self):
        assert self._fn()("172.16.0.5") is False

    def test_rfc1918_192168_not_trusted(self):
        assert self._fn()("192.168.1.100") is False

    def test_public_ip_not_trusted(self):
        assert self._fn()("8.8.8.8") is False

    def test_empty_string_not_trusted(self):
        assert self._fn()("") is False


# ---------------------------------------------------------------------------
# require_local_operator — LAN IPs must provide admin key
# ---------------------------------------------------------------------------

class TestRequireLocalOperator:
    """Integration tests using the HTTPX test client.

    The test client uses base_url='http://test', so request.client.host == 'test'.
    MESH_DEBUG_MODE defaults False, so the 'test' host bypass is inactive.
    These tests simulate LAN-IP callers by patching request.client.host.
    """

    def _call_with_host(self, host: str, admin_key: str = ""):
        """Call require_local_operator with a faked client host."""
        from unittest.mock import MagicMock
        from fastapi import HTTPException
        from auth import require_local_operator, _current_admin_key

        request = MagicMock()
        request.client.host = host
        request.headers.get = lambda k, default="": admin_key if k == "X-Admin-Key" else default

        # Patch the admin key lookup to return a known key
        with patch("auth._current_admin_key", return_value="test-admin-key-32chars-xxxxxxxxxx"):
            try:
                require_local_operator(request)
                return 200
            except HTTPException as e:
                return e.status_code

    def test_loopback_passes_without_key(self):
        assert self._call_with_host("127.0.0.1") == 200

    def test_rfc1918_10_blocked_without_key(self):
        assert self._call_with_host("10.0.0.1") == 403

    def test_rfc1918_172_blocked_without_key(self):
        assert self._call_with_host("172.16.0.5") == 403

    def test_rfc1918_192168_blocked_without_key(self):
        assert self._call_with_host("192.168.1.100") == 403

    def test_rfc1918_passes_with_valid_admin_key(self):
        assert self._call_with_host("192.168.1.100", admin_key="test-admin-key-32chars-xxxxxxxxxx") == 200

    def test_public_ip_blocked_without_key(self):
        assert self._call_with_host("8.8.8.8") == 403


# ---------------------------------------------------------------------------
# _validate_peer_push_secret — startup enforcement
# ---------------------------------------------------------------------------

_KNOWN_COMPROMISED = "Mv63UvLfwqOEVWeRBXjA8MtFl2nEkkhUlLYVHiX1Zzo"


class TestValidatePeerPushSecret:
    def _run(self, secret_value: str):
        """Call _validate_peer_push_secret with a patched settings value."""
        from main import _validate_peer_push_secret

        mock_settings = MagicMock()
        mock_settings.MESH_PEER_PUSH_SECRET = secret_value

        with patch("main.get_settings", return_value=mock_settings):
            return _validate_peer_push_secret

    def test_known_default_causes_exit(self):
        from auth import _validate_peer_push_secret

        mock_settings = MagicMock()
        mock_settings.MESH_PEER_PUSH_SECRET = _KNOWN_COMPROMISED

        with patch("auth.get_settings", return_value=mock_settings):
            with pytest.raises(SystemExit) as exc_info:
                _validate_peer_push_secret()
        assert exc_info.value.code == 1

    def test_empty_secret_does_not_exit_without_peers(self):
        from auth import _validate_peer_push_secret

        mock_settings = MagicMock()
        mock_settings.MESH_PEER_PUSH_SECRET = ""
        mock_settings.MESH_RELAY_PEERS = ""
        mock_settings.MESH_RNS_PEERS = ""
        mock_settings.MESH_RNS_ENABLED = False

        with patch("auth.get_settings", return_value=mock_settings):
            _validate_peer_push_secret()  # no exception = pass

    def test_empty_secret_with_peers_causes_exit(self):
        from auth import _validate_peer_push_secret

        mock_settings = MagicMock()
        mock_settings.MESH_PEER_PUSH_SECRET = ""
        mock_settings.MESH_RELAY_PEERS = "https://peer.example"
        mock_settings.MESH_RNS_PEERS = ""
        mock_settings.MESH_RNS_ENABLED = False

        with patch("auth.get_settings", return_value=mock_settings):
            with pytest.raises(SystemExit) as exc_info:
                _validate_peer_push_secret()
        assert exc_info.value.code == 1

    def test_short_secret_with_peers_causes_exit(self):
        from auth import _validate_peer_push_secret

        mock_settings = MagicMock()
        mock_settings.MESH_PEER_PUSH_SECRET = "tooshort"
        mock_settings.MESH_RELAY_PEERS = "https://peer.example"
        mock_settings.MESH_RNS_PEERS = ""
        mock_settings.MESH_RNS_ENABLED = False

        with patch("auth.get_settings", return_value=mock_settings):
            with pytest.raises(SystemExit) as exc_info:
                _validate_peer_push_secret()
        assert exc_info.value.code == 1

    def test_valid_secret_passes(self):
        from auth import _validate_peer_push_secret

        mock_settings = MagicMock()
        mock_settings.MESH_PEER_PUSH_SECRET = "a-completely-unique-per-deployment-secret-value"
        mock_settings.MESH_RELAY_PEERS = "https://peer.example"
        mock_settings.MESH_RNS_PEERS = ""
        mock_settings.MESH_RNS_ENABLED = False

        with patch("auth.get_settings", return_value=mock_settings):
            _validate_peer_push_secret()  # no exception = pass

    def test_whitespace_only_treated_as_empty(self):
        from auth import _validate_peer_push_secret

        mock_settings = MagicMock()
        mock_settings.MESH_PEER_PUSH_SECRET = "   "
        mock_settings.MESH_RELAY_PEERS = ""
        mock_settings.MESH_RNS_PEERS = ""
        mock_settings.MESH_RNS_ENABLED = False

        with patch("auth.get_settings", return_value=mock_settings):
            _validate_peer_push_secret()  # warns but does not exit
