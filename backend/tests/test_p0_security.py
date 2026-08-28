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

    def test_docker_bridge_blocked_without_compose_opt_in(self):
        # Even if DNS would resolve the frontend hostname to this IP,
        # the env opt-in is required.
        with patch.dict("os.environ", {"SHADOWBROKER_TRUST_DOCKER_BRIDGE_LOCAL_OPERATOR": ""}):
            with patch("auth._resolve_trusted_bridge_ips", return_value=frozenset({"172.18.0.3"})):
                assert self._call_with_host("172.18.0.3") == 403

    def test_docker_bridge_passes_with_compose_opt_in(self):
        # Issue #250: opt-in alone is no longer sufficient — the source IP
        # must also reverse-match a trusted frontend container hostname.
        # Here we simulate Docker DNS resolving "frontend" to 172.18.0.3.
        with patch.dict("os.environ", {"SHADOWBROKER_TRUST_DOCKER_BRIDGE_LOCAL_OPERATOR": "1"}):
            with patch("auth._resolve_trusted_bridge_ips", return_value=frozenset({"172.18.0.3"})):
                assert self._call_with_host("172.18.0.3") == 200

    def test_unknown_bridge_ip_blocked_even_with_compose_opt_in(self):
        # Issue #250 core regression: a rogue container on the same bridge
        # whose IP is NOT in the resolved frontend hostname set must NOT
        # be trusted, even when the bridge opt-in flag is on.
        with patch.dict("os.environ", {"SHADOWBROKER_TRUST_DOCKER_BRIDGE_LOCAL_OPERATOR": "1"}):
            with patch("auth._resolve_trusted_bridge_ips", return_value=frozenset({"172.18.0.3"})):
                assert self._call_with_host("172.18.0.99") == 403

    def test_lan_ip_still_blocked_with_compose_opt_in(self):
        with patch.dict("os.environ", {"SHADOWBROKER_TRUST_DOCKER_BRIDGE_LOCAL_OPERATOR": "1"}):
            with patch("auth._resolve_trusted_bridge_ips", return_value=frozenset({"172.18.0.3"})):
                assert self._call_with_host("192.168.1.100") == 403

    def test_rfc1918_192168_blocked_without_key(self):
        assert self._call_with_host("192.168.1.100") == 403

    def test_rfc1918_passes_with_valid_admin_key(self):
        assert self._call_with_host("192.168.1.100", admin_key="test-admin-key-32chars-xxxxxxxxxx") == 200

    def test_public_ip_blocked_without_key(self):
        assert self._call_with_host("8.8.8.8") == 403


# ---------------------------------------------------------------------------
# _validate_peer_push_secret — startup enforcement
# ---------------------------------------------------------------------------

_KNOWN_COMPROMISED = "".join(
    [
        "Mv63UvLfwq",
        "OEVWeRBXjA",
        "8MtFl2nEkk",
        "hUlLYVHiX1Zzo",
    ]
)


class TestValidatePeerPushSecret:
    def _run(self, secret_value: str):
        """Call _validate_peer_push_secret with a patched settings value."""
        from main import _validate_peer_push_secret

        mock_settings = MagicMock()
        mock_settings.MESH_PEER_PUSH_SECRET = secret_value

        with patch("main.get_settings", return_value=mock_settings):
            return _validate_peer_push_secret

    def test_known_default_is_rejected(self):
        from auth import _validate_peer_push_secret

        mock_settings = MagicMock()
        mock_settings.MESH_PEER_PUSH_SECRET = _KNOWN_COMPROMISED

        with patch("auth.get_settings", return_value=mock_settings), pytest.raises(SystemExit):
            _validate_peer_push_secret()

    def test_empty_secret_does_not_exit_without_peers(self):
        from auth import _validate_peer_push_secret

        mock_settings = MagicMock()
        mock_settings.MESH_PEER_PUSH_SECRET = ""
        mock_settings.MESH_RELAY_PEERS = ""
        mock_settings.MESH_RNS_PEERS = ""
        mock_settings.MESH_RNS_ENABLED = False

        with patch("auth.get_settings", return_value=mock_settings):
            _validate_peer_push_secret()  # no exception = pass

    def test_empty_secret_with_peers_is_rejected(self):
        from auth import _validate_peer_push_secret

        mock_settings = MagicMock()
        mock_settings.MESH_PEER_PUSH_SECRET = ""
        mock_settings.MESH_RELAY_PEERS = "https://peer.example"
        mock_settings.MESH_RNS_PEERS = ""
        mock_settings.MESH_RNS_ENABLED = False

        with patch("auth.get_settings", return_value=mock_settings), pytest.raises(SystemExit):
            _validate_peer_push_secret()

    def test_short_secret_with_peers_is_rejected(self):
        from auth import _validate_peer_push_secret

        mock_settings = MagicMock()
        mock_settings.MESH_PEER_PUSH_SECRET = "tooshort"
        mock_settings.MESH_RELAY_PEERS = "https://peer.example"
        mock_settings.MESH_RNS_PEERS = ""
        mock_settings.MESH_RNS_ENABLED = False

        with patch("auth.get_settings", return_value=mock_settings), pytest.raises(SystemExit):
            _validate_peer_push_secret()

    def test_valid_secret_passes(self):
        from auth import _validate_peer_push_secret

        mock_settings = MagicMock()
        mock_settings.MESH_PEER_PUSH_SECRET = "a-completely-unique-per-deployment-secret-value"
        mock_settings.MESH_RELAY_PEERS = "https://peer.example"
        mock_settings.MESH_RNS_PEERS = ""
        mock_settings.MESH_RNS_ENABLED = False

        with patch("auth.get_settings", return_value=mock_settings):
            _validate_peer_push_secret()  # no exception = pass

    def test_valid_rotation_previous_passes(self):
        from auth import _validate_peer_push_secret

        mock_settings = MagicMock()
        mock_settings.MESH_PEER_PUSH_SECRET = "new-primary-secret-value-12345"
        mock_settings.MESH_PEER_PUSH_SECRET_PREVIOUS = "old-previous-secret-value-67890"
        mock_settings.MESH_RELAY_PEERS = "https://peer.example"
        mock_settings.MESH_RNS_PEERS = ""
        mock_settings.MESH_RNS_ENABLED = False

        with patch("auth.get_settings", return_value=mock_settings):
            _validate_peer_push_secret()

    def test_rotation_previous_must_differ_from_primary(self):
        from auth import _validate_peer_push_secret

        mock_settings = MagicMock()
        mock_settings.MESH_PEER_PUSH_SECRET = "same-strong-secret-value-12345"
        mock_settings.MESH_PEER_PUSH_SECRET_PREVIOUS = "same-strong-secret-value-12345"
        mock_settings.MESH_RELAY_PEERS = "https://peer.example"
        mock_settings.MESH_RNS_PEERS = ""
        mock_settings.MESH_RNS_ENABLED = False

        with patch("auth.get_settings", return_value=mock_settings), pytest.raises(SystemExit):
            _validate_peer_push_secret()

    def test_whitespace_only_treated_as_empty(self):
        from auth import _validate_peer_push_secret

        mock_settings = MagicMock()
        mock_settings.MESH_PEER_PUSH_SECRET = "   "
        mock_settings.MESH_RELAY_PEERS = ""
        mock_settings.MESH_RNS_PEERS = ""
        mock_settings.MESH_RNS_ENABLED = False

        with patch("auth.get_settings", return_value=mock_settings):
            _validate_peer_push_secret()  # warns but does not exit
