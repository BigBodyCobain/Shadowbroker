"""Public Infonet fleet defaults for sb-testnet-0 participants.

Operators who run private single-node installs can set ``MESH_INFONET_FLEET_JOIN=false``
and provide their own signer keys / peer secrets.
"""

from __future__ import annotations

FLEET_NETWORK_ID = "sb-testnet-0"
FLEET_SEED_ONION_URL = (
    "http://gqpbunqbgtkcqilvclm3xrkt3zowjyl3s62kkktvojgvxzizamvbrqid.onion:8000"
)
FLEET_SEED_ONION_URLS = (
    FLEET_SEED_ONION_URL,
)
FLEET_BOOTSTRAP_SIGNER_PUBLIC_KEY_B64 = (
    "ul1d0kj/ODPIp0OhHzX8eLAVXzJ3CVvzW1vn2IC6q3I="
)
# Shared fleet HMAC for sb-testnet peer announce/push/sync. Public testnet join model.
FLEET_PEER_PUSH_SECRET = "b7GoqsvoUD9MV7tyt0ZOzMptLA84QG6KCfaV9nDqz5Y"


def infonet_fleet_join_enabled() -> bool:
    try:
        from services.config import get_settings

        if bool(getattr(get_settings(), "MESH_INFONET_FLEET_JOIN_DISABLED", False)):
            return False
        return bool(getattr(get_settings(), "MESH_INFONET_FLEET_JOIN", True))
    except Exception:
        return True


def effective_bootstrap_signer_public_key_b64() -> str:
    try:
        from services.config import get_settings

        configured = str(getattr(get_settings(), "MESH_BOOTSTRAP_SIGNER_PUBLIC_KEY", "") or "").strip()
        if configured:
            return configured
    except Exception:
        pass
    if infonet_fleet_join_enabled():
        return FLEET_BOOTSTRAP_SIGNER_PUBLIC_KEY_B64
    return ""


def effective_peer_push_secret() -> str:
    try:
        from services.config import get_settings

        configured = str(getattr(get_settings(), "MESH_PEER_PUSH_SECRET", "") or "").strip()
        if configured:
            return configured
    except Exception:
        pass
    if infonet_fleet_join_enabled():
        return FLEET_PEER_PUSH_SECRET
    return ""


def _dedupe_peer_urls(peers: list[str]) -> list[str]:
    from services.mesh.mesh_router import parse_configured_relay_peers

    seen: set[str] = set()
    normalized: list[str] = []
    for peer in parse_configured_relay_peers(",".join(str(item or "") for item in peers)):
        if peer in seen:
            continue
        seen.add(peer)
        normalized.append(peer)
    return normalized


def effective_fleet_seed_peers() -> list[str]:
    try:
        from services.config import get_settings

        configured = str(getattr(get_settings(), "MESH_FLEET_SEED_PEERS", "") or "").strip()
        if configured:
            return _dedupe_peer_urls([configured])
    except Exception:
        pass
    return _dedupe_peer_urls(list(FLEET_SEED_ONION_URLS))


def configured_bootstrap_seed_peers_with_fleet_default(peers: list[str]) -> list[str]:
    normalized_peers = _dedupe_peer_urls(peers)
    if normalized_peers:
        return normalized_peers
    if infonet_fleet_join_enabled():
        return effective_fleet_seed_peers()
    return []
