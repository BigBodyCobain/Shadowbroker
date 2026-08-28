"""Issue #256 (tg12): per-peer HMAC secrets must defeat cross-peer
impersonation.

Before the fix, ALL peer-push HMACs were derived from the single
fleet-shared ``MESH_PEER_PUSH_SECRET``. The receiver could only prove
"this request was signed by someone who knows the fleet secret" — not
which peer signed it. Any peer that knew the secret could compute the
expected HMAC for any other peer's URL and impersonate that peer.

The fix introduces ``MESH_PEER_SECRETS``, a per-peer URL-to-secret map.
When a peer URL appears there:

- Only the listed per-peer secret is accepted for that URL.
- The global ``MESH_PEER_PUSH_SECRET`` is ignored for that specific URL.
- A peer that knows only the global secret (or a different peer's
  per-peer secret) cannot forge a request claiming to be that peer.

When a peer URL is NOT listed (the common case for single-peer installs
and for migration windows), the resolver falls back to the global
secret — preserving existing behavior with zero operator action.

These tests exercise ``resolve_peer_key_for_url`` directly so we cover
the security contract without spinning up a full mesh node.
"""
from __future__ import annotations

import hashlib
import hmac

import pytest


# ---------------------------------------------------------------------------
# _lookup_per_peer_secret — env parsing
# ---------------------------------------------------------------------------


class TestLookupPerPeerSecret:
    def setup_method(self):
        # Invalidate the parser cache so each test sees its own env state.
        from services.mesh import mesh_crypto

        mesh_crypto._PEER_SECRETS_CACHE = {}
        mesh_crypto._PEER_SECRETS_CACHE_RAW = ""

    def test_returns_empty_when_env_unset(self, monkeypatch):
        from services.mesh.mesh_crypto import _lookup_per_peer_secret

        monkeypatch.delenv("MESH_PEER_SECRETS", raising=False)
        assert _lookup_per_peer_secret("https://peer.example") == ""

    def test_returns_empty_when_env_blank(self, monkeypatch):
        from services.mesh.mesh_crypto import _lookup_per_peer_secret

        monkeypatch.setenv("MESH_PEER_SECRETS", "")
        assert _lookup_per_peer_secret("https://peer.example") == ""

    def test_returns_per_peer_secret_for_listed_url(self, monkeypatch):
        from services.mesh.mesh_crypto import _lookup_per_peer_secret

        monkeypatch.setenv(
            "MESH_PEER_SECRETS",
            "https://peer-a.example=secretA,https://peer-b.example=secretB",
        )
        assert _lookup_per_peer_secret("https://peer-a.example") == "secretA"
        assert _lookup_per_peer_secret("https://peer-b.example") == "secretB"

    def test_returns_empty_for_url_not_listed(self, monkeypatch):
        from services.mesh.mesh_crypto import _lookup_per_peer_secret

        monkeypatch.setenv(
            "MESH_PEER_SECRETS",
            "https://peer-a.example=secretA",
        )
        assert _lookup_per_peer_secret("https://other.example") == ""

    def test_url_is_normalized_before_lookup(self, monkeypatch):
        from services.mesh.mesh_crypto import _lookup_per_peer_secret

        # Configure with a trailing slash + uppercase host. Lookup with
        # plain lowercase host. Both should normalize to the same key.
        monkeypatch.setenv(
            "MESH_PEER_SECRETS",
            "https://Peer-A.Example/=secretA",
        )
        assert _lookup_per_peer_secret("https://peer-a.example") == "secretA"

    def test_whitespace_around_entries_is_stripped(self, monkeypatch):
        from services.mesh.mesh_crypto import _lookup_per_peer_secret

        monkeypatch.setenv(
            "MESH_PEER_SECRETS",
            "  https://peer-a.example = secretA , https://peer-b.example=secretB  ",
        )
        assert _lookup_per_peer_secret("https://peer-a.example") == "secretA"
        assert _lookup_per_peer_secret("https://peer-b.example") == "secretB"

    def test_malformed_entries_are_skipped_not_raised(self, monkeypatch):
        """A garbled MESH_PEER_SECRETS value must NOT crash the resolver.
        Bad entries are silently dropped; well-formed entries still work.
        This is the "fail-forward, not loud" rule — a typo in operator
        config should not take the whole backend down."""
        from services.mesh.mesh_crypto import _lookup_per_peer_secret

        monkeypatch.setenv(
            "MESH_PEER_SECRETS",
            "no_equals_sign,=missing_url,https://no.secret=,https://good.example=secretGood",
        )
        assert _lookup_per_peer_secret("https://good.example") == "secretGood"
        # The malformed ones produce no entry (and don't poison the cache).
        assert _lookup_per_peer_secret("https://no.secret") == ""

    def test_cache_invalidates_on_env_change(self, monkeypatch):
        """A test (or operator) updating MESH_PEER_SECRETS must see the
        new value immediately — no process restart required."""
        from services.mesh.mesh_crypto import _lookup_per_peer_secret

        monkeypatch.setenv("MESH_PEER_SECRETS", "https://a.example=first")
        assert _lookup_per_peer_secret("https://a.example") == "first"
        monkeypatch.setenv("MESH_PEER_SECRETS", "https://a.example=second")
        assert _lookup_per_peer_secret("https://a.example") == "second"


# ---------------------------------------------------------------------------
# resolve_peer_key_for_url — precedence + fallback
# ---------------------------------------------------------------------------


class TestResolvePeerKeyForUrl:
    def setup_method(self):
        from services.mesh import mesh_crypto

        mesh_crypto._PEER_SECRETS_CACHE = {}
        mesh_crypto._PEER_SECRETS_CACHE_RAW = ""

    def _fake_settings(self, global_secret: str):
        from unittest.mock import MagicMock

        s = MagicMock()
        s.MESH_PEER_PUSH_SECRET = global_secret
        return s

    def test_falls_back_to_global_when_no_per_peer_entry(self, monkeypatch):
        """Single-peer installs: MESH_PEER_SECRETS empty, MESH_PEER_PUSH_SECRET
        set — must keep working as before."""
        from services.mesh.mesh_crypto import (
            resolve_peer_key_for_url,
            _derive_peer_key,
        )

        monkeypatch.delenv("MESH_PEER_SECRETS", raising=False)
        with monkeypatch.context() as m:
            m.setattr(
                "services.config.get_settings",
                lambda: self._fake_settings("global-secret"),
            )
            key = resolve_peer_key_for_url("https://peer.example")
            expected = _derive_peer_key("global-secret", "https://peer.example")
        assert key == expected
        assert len(key) == 32  # SHA-256 output

    def test_per_peer_secret_takes_precedence_over_global(self, monkeypatch):
        from services.mesh.mesh_crypto import (
            resolve_peer_key_for_url,
            _derive_peer_key,
        )

        monkeypatch.setenv(
            "MESH_PEER_SECRETS",
            "https://peer-a.example=per-peer-a-secret",
        )
        with monkeypatch.context() as m:
            m.setattr(
                "services.config.get_settings",
                lambda: self._fake_settings("global-secret"),
            )
            key = resolve_peer_key_for_url("https://peer-a.example")
            expected_per_peer = _derive_peer_key(
                "per-peer-a-secret", "https://peer-a.example"
            )
            expected_global = _derive_peer_key("global-secret", "https://peer-a.example")
        assert key == expected_per_peer
        assert key != expected_global

    def test_unlisted_peer_uses_global_during_migration(self, monkeypatch):
        """Partial migration: peer A is in MESH_PEER_SECRETS, peer B is
        not yet. Peer B must keep working under the global secret."""
        from services.mesh.mesh_crypto import (
            resolve_peer_key_for_url,
            _derive_peer_key,
        )

        monkeypatch.setenv(
            "MESH_PEER_SECRETS",
            "https://peer-a.example=per-peer-a-secret",
        )
        with monkeypatch.context() as m:
            m.setattr(
                "services.config.get_settings",
                lambda: self._fake_settings("global-secret"),
            )
            key_a = resolve_peer_key_for_url("https://peer-a.example")
            key_b = resolve_peer_key_for_url("https://peer-b.example")
            expected_b = _derive_peer_key("global-secret", "https://peer-b.example")
        assert key_b == expected_b
        # Peer A's per-peer key must differ from peer B's global key
        # (they're keyed by different secrets and different URLs).
        assert key_a != key_b

    def test_returns_empty_when_no_secret_available(self, monkeypatch):
        from services.mesh.mesh_crypto import resolve_peer_key_for_url

        monkeypatch.delenv("MESH_PEER_SECRETS", raising=False)
        with monkeypatch.context() as m:
            m.setattr(
                "services.config.get_settings",
                lambda: self._fake_settings(""),
            )
            key = resolve_peer_key_for_url("https://peer.example")
        assert key == b""

    def test_returns_empty_when_url_is_unparseable(self, monkeypatch):
        from services.mesh.mesh_crypto import resolve_peer_key_for_url

        with monkeypatch.context() as m:
            m.setattr(
                "services.config.get_settings",
                lambda: self._fake_settings("global-secret"),
            )
            assert resolve_peer_key_for_url("") == b""
            assert resolve_peer_key_for_url("not-a-url") == b""
            assert resolve_peer_key_for_url(None) == b""

    def test_rotation_accepts_previous_only_for_global_peers(self, monkeypatch):
        from types import SimpleNamespace

        from services.mesh.mesh_crypto import _derive_peer_key, resolve_peer_keys_for_url

        monkeypatch.delenv("MESH_PEER_SECRETS", raising=False)
        monkeypatch.setattr(
            "services.config.get_settings",
            lambda: SimpleNamespace(
                MESH_PEER_PUSH_SECRET="new-secret",
                MESH_PEER_PUSH_SECRET_PREVIOUS="old-secret",
            ),
        )
        monkeypatch.setattr(
            "services.mesh.mesh_fleet_defaults.effective_peer_push_secret",
            lambda: "new-secret",
        )
        keys = resolve_peer_keys_for_url("https://peer.example")
        assert keys == (
            _derive_peer_key("new-secret", "https://peer.example"),
            _derive_peer_key("old-secret", "https://peer.example"),
        )

        monkeypatch.setenv("MESH_PEER_SECRETS", "https://peer.example=exclusive-secret")
        assert resolve_peer_keys_for_url("https://peer.example") == (
            _derive_peer_key("exclusive-secret", "https://peer.example"),
        )


# ---------------------------------------------------------------------------
# The actual #256 attack: peer A cannot impersonate peer B
# ---------------------------------------------------------------------------


class TestCrossPeerImpersonationRefused:
    """The core regression: when MESH_PEER_SECRETS is configured, a peer
    that knows ONLY the global secret (or a different peer's per-peer
    secret) cannot produce a valid HMAC for another peer's URL."""

    def setup_method(self):
        from services.mesh import mesh_crypto

        mesh_crypto._PEER_SECRETS_CACHE = {}
        mesh_crypto._PEER_SECRETS_CACHE_RAW = ""

    def _hmac(self, key: bytes, body: bytes) -> str:
        return hmac.new(key, body, hashlib.sha256).hexdigest()

    def test_peer_a_global_secret_cannot_forge_peer_b_hmac(self, monkeypatch):
        from services.mesh.mesh_crypto import (
            resolve_peer_key_for_url,
            _derive_peer_key,
        )
        from unittest.mock import MagicMock

        # Receiver has BOTH the global secret AND a per-peer secret for B.
        monkeypatch.setenv(
            "MESH_PEER_SECRETS",
            "https://peer-b.example=per-peer-b-secret",
        )
        settings = MagicMock()
        settings.MESH_PEER_PUSH_SECRET = "global-secret"
        monkeypatch.setattr(
            "services.config.get_settings", lambda: settings
        )

        body = b'{"events": [{"id": 1}]}'

        # Attacker (peer A) knows only the global secret. Tries to forge
        # an HMAC claiming to be peer B.
        attacker_key = _derive_peer_key("global-secret", "https://peer-b.example")
        attacker_hmac = self._hmac(attacker_key, body)

        # Receiver derives B's expected key from B's per-peer secret.
        receiver_key = resolve_peer_key_for_url("https://peer-b.example")
        expected_hmac = self._hmac(receiver_key, body)

        # The forgery MUST NOT match.
        assert attacker_hmac != expected_hmac

    def test_peer_a_per_peer_secret_cannot_forge_peer_b_hmac(self, monkeypatch):
        """Even harder case: peer A has its OWN per-peer secret, but
        still does not know peer B's per-peer secret, and so cannot
        forge an HMAC for peer B."""
        from services.mesh.mesh_crypto import (
            resolve_peer_key_for_url,
            _derive_peer_key,
        )
        from unittest.mock import MagicMock

        monkeypatch.setenv(
            "MESH_PEER_SECRETS",
            "https://peer-a.example=secretA,https://peer-b.example=secretB",
        )
        settings = MagicMock()
        settings.MESH_PEER_PUSH_SECRET = ""
        monkeypatch.setattr(
            "services.config.get_settings", lambda: settings
        )

        body = b'{"events": [{"id": 99}]}'

        # Attacker A tries to forge for B using its own secret (secretA).
        attacker_key = _derive_peer_key("secretA", "https://peer-b.example")
        attacker_hmac = self._hmac(attacker_key, body)

        receiver_key = resolve_peer_key_for_url("https://peer-b.example")
        expected_hmac = self._hmac(receiver_key, body)

        assert attacker_hmac != expected_hmac

    def test_legitimate_peer_b_request_verifies(self, monkeypatch):
        """Positive control: when peer B uses ITS per-peer secret and
        claims to be itself, the receiver accepts the HMAC."""
        from services.mesh.mesh_crypto import resolve_peer_key_for_url
        from unittest.mock import MagicMock

        monkeypatch.setenv(
            "MESH_PEER_SECRETS",
            "https://peer-b.example=secretB",
        )
        settings = MagicMock()
        settings.MESH_PEER_PUSH_SECRET = ""
        monkeypatch.setattr(
            "services.config.get_settings", lambda: settings
        )

        body = b'{"events": [{"id": 7}]}'

        # Peer B and the receiver both call resolve_peer_key_for_url.
        sender_key = resolve_peer_key_for_url("https://peer-b.example")
        receiver_key = resolve_peer_key_for_url("https://peer-b.example")

        sender_hmac = self._hmac(sender_key, body)
        expected_hmac = self._hmac(receiver_key, body)

        assert sender_hmac == expected_hmac

    def test_single_peer_install_zero_behavior_change(self, monkeypatch):
        """The "no UX hostility" guarantee: an install with the global
        secret set and NO MESH_PEER_SECRETS entries must derive exactly
        the same key as before this change."""
        from services.mesh.mesh_crypto import (
            resolve_peer_key_for_url,
            _derive_peer_key,
        )
        from unittest.mock import MagicMock

        monkeypatch.delenv("MESH_PEER_SECRETS", raising=False)
        settings = MagicMock()
        settings.MESH_PEER_PUSH_SECRET = "legacy-global-secret"
        monkeypatch.setattr(
            "services.config.get_settings", lambda: settings
        )

        # The legacy derivation that every prior call site used.
        legacy_key = _derive_peer_key("legacy-global-secret", "https://peer.example")
        # The new resolver, with no per-peer entries configured.
        new_key = resolve_peer_key_for_url("https://peer.example")

        assert new_key == legacy_key
