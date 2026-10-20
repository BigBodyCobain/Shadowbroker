"""Reuse Shadowbroker Sentinel Hub / Copernicus CDSE credentials."""
from __future__ import annotations

import os

from .config import CACHE_DIR


def resolve_sentinel_credentials() -> tuple[str, str]:
    client_id = (os.environ.get("SENTINEL_CLIENT_ID") or "").strip()
    client_secret = (os.environ.get("SENTINEL_CLIENT_SECRET") or "").strip()
    return client_id, client_secret


def sentinel_credentials_configured() -> bool:
    client_id, client_secret = resolve_sentinel_credentials()
    return bool(client_id and client_secret)


def build_sh_config():
    from sentinelhub import SHConfig

    client_id, client_secret = resolve_sentinel_credentials()
    if not client_id or not client_secret:
        raise RuntimeError(
            "SENTINEL_CLIENT_ID and SENTINEL_CLIENT_SECRET are required for road corridor analysis"
        )
    config = SHConfig()
    config.sh_client_id = client_id
    config.sh_client_secret = client_secret
    config.sh_base_url = "https://sh.dataspace.copernicus.eu"
    config.sh_token_url = (
        "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
    )
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    config.cache_dir = str(CACHE_DIR / "sentinelhub")
    return config
