from services.mesh.mesh_fleet_defaults import (
    FLEET_SEED_ONION_URL,
    FLEET_PEER_PUSH_SECRET,
    configured_bootstrap_seed_peers_with_fleet_default,
    effective_bootstrap_signer_public_key_b64,
    effective_fleet_seed_peers,
    effective_peer_push_secret,
    infonet_fleet_join_enabled,
)


def test_fleet_defaults_apply_when_join_enabled(monkeypatch):
    from services.config import get_settings

    monkeypatch.setenv("MESH_BOOTSTRAP_SIGNER_PUBLIC_KEY", "")
    monkeypatch.setenv("MESH_PEER_PUSH_SECRET", "")
    monkeypatch.setenv("MESH_INFONET_FLEET_JOIN", "true")
    get_settings.cache_clear()
    try:
        assert infonet_fleet_join_enabled() is True
        assert effective_bootstrap_signer_public_key_b64()
        assert effective_peer_push_secret() == FLEET_PEER_PUSH_SECRET
    finally:
        get_settings.cache_clear()


def test_empty_bootstrap_peers_use_fleet_seed_defaults(monkeypatch):
    from services.config import get_settings

    monkeypatch.delenv("MESH_FLEET_SEED_PEERS", raising=False)
    monkeypatch.setenv("MESH_INFONET_FLEET_JOIN", "true")
    get_settings.cache_clear()
    try:
        assert configured_bootstrap_seed_peers_with_fleet_default([]) == [FLEET_SEED_ONION_URL]
    finally:
        get_settings.cache_clear()


def test_configured_bootstrap_peers_override_fleet_defaults(monkeypatch):
    from services.config import get_settings

    monkeypatch.setenv("MESH_INFONET_FLEET_JOIN", "true")
    get_settings.cache_clear()
    try:
        assert configured_bootstrap_seed_peers_with_fleet_default(
            ["http://alphaexample.onion:8000", "http://alphaexample.onion:8000"]
        ) == ["http://alphaexample.onion:8000"]
    finally:
        get_settings.cache_clear()


def test_fleet_seed_override_can_ship_multiple_seeds(monkeypatch):
    from services.config import get_settings

    monkeypatch.setenv(
        "MESH_FLEET_SEED_PEERS",
        "http://alphaexample.onion:8000,http://betaexample.onion:8000,http://alphaexample.onion:8000",
    )
    get_settings.cache_clear()
    try:
        assert effective_fleet_seed_peers() == [
            "http://alphaexample.onion:8000",
            "http://betaexample.onion:8000",
        ]
        assert configured_bootstrap_seed_peers_with_fleet_default([]) == [
            "http://alphaexample.onion:8000",
            "http://betaexample.onion:8000",
        ]
    finally:
        get_settings.cache_clear()


def test_fleet_defaults_disabled(monkeypatch):
    from services.config import get_settings

    monkeypatch.setenv("MESH_BOOTSTRAP_SIGNER_PUBLIC_KEY", "")
    monkeypatch.setenv("MESH_PEER_PUSH_SECRET", "")
    monkeypatch.setenv("MESH_INFONET_FLEET_JOIN_DISABLED", "true")
    get_settings.cache_clear()
    try:
        assert infonet_fleet_join_enabled() is False
        assert effective_peer_push_secret() == ""
    finally:
        get_settings.cache_clear()
