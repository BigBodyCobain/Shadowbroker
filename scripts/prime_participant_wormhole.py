#!/usr/bin/env python3
"""One-shot wormhole/Tor prime for fleet participant nodes (run inside backend container)."""
import json

from routers.ai_intel import _write_env_value
from services.config import get_settings
from services.tor_hidden_service import tor_service
from services.wormhole_settings import write_wormhole_settings
from services.wormhole_supervisor import connect_wormhole

port = int(get_settings().MESH_ARTI_SOCKS_PORT or 9050)
write_wormhole_settings(
    enabled=True,
    transport="tor_arti",
    socks_proxy=f"socks5h://127.0.0.1:{port}",
    socks_dns=True,
    anonymous_mode=True,
)
tor = tor_service.start(target_port=8000)
if tor.get("ok"):
    _write_env_value("MESH_ARTI_ENABLED", "true")
    onion = str(tor.get("onion_address") or "").strip().rstrip("/")
    if onion:
        # Replicate-envelope HMAC checks X-Peer-Url against authenticated_push_peer_urls;
        # fresh participants need their own onion in the push allowlist until fleet manifest sync.
        _write_env_value("MESH_RELAY_PEERS", onion)
    get_settings.cache_clear()
runtime = connect_wormhole(reason="participant_warmup")
print(json.dumps({"ok": True, "tor": tor, "runtime": runtime}))
