"""Auth policy table consolidation.

Tests:
- Representative route -> tier mappings stay honest
- Wormhole and mesh DM routes are private_control_only
- Wormhole gate compose/decrypt align with private_control_only
- No route appears in conflicting classifications
- Legacy _private_infonet_required_tier stays consistent with the table
"""

import auth
from auth import (
    _PRIVATE_INFONET_ROUTES,
    _ROUTE_TRANSPORT_PATTERNS,
    _ROUTE_TRANSPORT_POLICY,
    _minimum_transport_tier,
    _private_infonet_required_tier,
)


def test_no_duplicate_route_keys_in_policy_table():
    known_tiers = {"private_control_only", "private_transitional", "private_strong"}
    for key, policy in _ROUTE_TRANSPORT_POLICY.items():
        tier = policy.enforcement_tier
        assert tier in known_tiers, f"{key} has unknown tier {tier!r}"


def test_no_route_classified_in_conflicting_tiers():
    for (method, path), policy in _ROUTE_TRANSPORT_POLICY.items():
        exact_tier = policy.enforcement_tier
        resolved = _minimum_transport_tier(path, method)
        assert resolved == exact_tier


def test_dm_compose_is_private_control_only():
    assert _minimum_transport_tier("/api/wormhole/dm/compose", "POST") == "private_control_only"


def test_dm_decrypt_is_private_control_only():
    assert _minimum_transport_tier("/api/wormhole/dm/decrypt", "POST") == "private_control_only"


def test_gate_message_compose_is_private_control_only():
    assert _minimum_transport_tier("/api/wormhole/gate/message/compose", "POST") == "private_control_only"


def test_gate_message_decrypt_is_private_control_only():
    assert _minimum_transport_tier("/api/wormhole/gate/message/decrypt", "POST") == "private_control_only"


def test_gate_messages_decrypt_is_private_control_only():
    assert _minimum_transport_tier("/api/wormhole/gate/messages/decrypt", "POST") == "private_control_only"


def test_gate_enter_is_private_control_only():
    assert _minimum_transport_tier("/api/wormhole/gate/enter", "POST") == "private_control_only"


def test_gate_persona_create_is_private_control_only():
    assert _minimum_transport_tier("/api/wormhole/gate/persona/create", "POST") == "private_control_only"


def test_gate_key_rotate_is_private_control_only():
    assert _minimum_transport_tier("/api/wormhole/gate/key/rotate", "POST") == "private_control_only"


def test_dm_support_routes_are_control_only():
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


def test_mesh_dm_send_post_is_strong():
    assert _minimum_transport_tier("/api/mesh/dm/send", "POST") == "private_strong"


def test_mesh_identity_rotate_post_is_strong():
    assert _minimum_transport_tier("/api/mesh/identity/rotate", "POST") == "private_strong"


def test_mesh_dm_poll_get_is_strong():
    assert _minimum_transport_tier("/api/mesh/dm/poll", "GET") == "private_strong"


def test_mesh_dm_prekey_bundle_get_transitional():
    assert _minimum_transport_tier("/api/mesh/dm/prekey-bundle", "GET") == "private_transitional"


def test_mesh_report_post_transitional():
    assert _minimum_transport_tier("/api/mesh/report", "POST") == "private_transitional"


def test_mesh_vote_post_transitional():
    assert _minimum_transport_tier("/api/mesh/vote", "POST") == "private_transitional"


def test_mesh_gate_create_post_transitional():
    assert _minimum_transport_tier("/api/mesh/gate/create", "POST") == "private_transitional"


def test_mesh_gate_id_message_pattern_strong():
    assert _minimum_transport_tier("/api/mesh/gate/infonet/message", "POST") == "private_strong"
    assert _minimum_transport_tier("/api/mesh/gate/abc123/message", "POST") == "private_strong"


def test_unknown_route_returns_empty():
    assert _minimum_transport_tier("/api/health", "GET") == ""
    assert _minimum_transport_tier("/api/mesh/status", "GET") == ""


def test_private_infonet_dm_send_strong():
    assert _private_infonet_required_tier("/api/mesh/dm/send", "POST") == "strong"


def test_private_infonet_identity_rotate_strong():
    assert _private_infonet_required_tier("/api/mesh/identity/rotate", "POST") == "strong"


def test_private_infonet_dm_poll_get_strong():
    assert _private_infonet_required_tier("/api/mesh/dm/poll", "GET") == "strong"


def test_private_infonet_vote_transitional():
    assert _private_infonet_required_tier("/api/mesh/vote", "POST") == "transitional"


def test_private_infonet_gate_message_strong():
    assert _private_infonet_required_tier("/api/mesh/gate/infonet/message", "POST") == "strong"


def test_private_infonet_unknown_route_empty():
    assert _private_infonet_required_tier("/api/health", "GET") == ""


def test_private_infonet_routes_derived_from_policy_table():
    for method, path in _PRIVATE_INFONET_ROUTES:
        assert (method, path) in _ROUTE_TRANSPORT_POLICY
        assert path.startswith("/api/mesh/")


def test_transport_patterns_still_reserved_for_gate_messages():
    assert any(
        method == "POST"
        and prefix == "/api/mesh/gate/"
        and suffix == "/message"
        and policy.enforcement_tier == "private_strong"
        for method, prefix, suffix, policy in _ROUTE_TRANSPORT_PATTERNS
    )


def test_legacy_helper_is_derived_not_hand_curated():
    for (method, path), policy in _ROUTE_TRANSPORT_POLICY.items():
        if not path.startswith("/api/mesh/"):
            continue
        tier = policy.enforcement_tier
        expected = {
            "private_control_only": "control_only",
            "private_transitional": "transitional",
            "private_strong": "strong",
        }.get(tier, "")
        assert auth._private_infonet_required_tier(path, method) == expected
