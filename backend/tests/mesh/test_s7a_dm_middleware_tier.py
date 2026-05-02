"""Wormhole DM middleware tier alignment.

Tests:
- Wormhole DM routes resolve to private_control_only
- Gate compose/decrypt routes now align with private_control_only
- DM routes are no longer classified as private_strong-only
"""

from auth import _minimum_transport_tier


def test_dm_compose_requires_private_control_only():
    assert _minimum_transport_tier("/api/wormhole/dm/compose", "POST") == "private_control_only"


def test_dm_decrypt_requires_private_control_only():
    assert _minimum_transport_tier("/api/wormhole/dm/decrypt", "POST") == "private_control_only"


def test_gate_message_compose_is_private_control_only():
    assert _minimum_transport_tier("/api/wormhole/gate/message/compose", "POST") == "private_control_only"


def test_gate_message_decrypt_is_private_control_only():
    assert _minimum_transport_tier("/api/wormhole/gate/message/decrypt", "POST") == "private_control_only"


def test_gate_messages_decrypt_is_private_control_only():
    assert _minimum_transport_tier("/api/wormhole/gate/messages/decrypt", "POST") == "private_control_only"


def test_existing_dm_support_routes_are_control_only():
    for path in [
        "/api/wormhole/dm/encrypt",
        "/api/wormhole/dm/reset",
        "/api/wormhole/dm/register-key",
        "/api/wormhole/dm/prekey/register",
        "/api/wormhole/dm/bootstrap-encrypt",
        "/api/wormhole/dm/bootstrap-decrypt",
        "/api/wormhole/dm/sender-token",
        "/api/wormhole/dm/open-seal",
        "/api/wormhole/dm/build-seal",
        "/api/wormhole/dm/dead-drop-token",
        "/api/wormhole/dm/pairwise-alias",
        "/api/wormhole/dm/pairwise-alias/rotate",
        "/api/wormhole/dm/dead-drop-tokens",
        "/api/wormhole/dm/sas",
    ]:
        assert _minimum_transport_tier(path, "POST") == "private_control_only"


def test_dm_compose_not_in_transitional_set():
    assert _minimum_transport_tier("/api/wormhole/dm/compose", "POST") != "private_transitional"


def test_dm_decrypt_not_in_transitional_set():
    assert _minimum_transport_tier("/api/wormhole/dm/decrypt", "POST") != "private_transitional"
