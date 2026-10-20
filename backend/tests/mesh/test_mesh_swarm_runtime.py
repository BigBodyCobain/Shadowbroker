import json
import time

import pytest
from httpx import ASGITransport, AsyncClient

from services.mesh.mesh_bootstrap_manifest import (
    BootstrapManifestError,
    generate_bootstrap_signer,
    parse_bootstrap_manifest_dict,
    write_signed_bootstrap_manifest,
)
from services.mesh.mesh_peer_registry import PeerRegistry
from services.mesh.mesh_peer_store import DEFAULT_PEER_STORE_PATH, PeerStore
from services.mesh.mesh_swarm_runtime import (
    merge_manifest_into_peer_store,
    peer_registry_enabled,
    publish_registry_manifest,
    refresh_swarm_manifest_from_seeds,
    record_peer_announcement,
)


def test_peer_registry_upsert_and_prune(tmp_path, monkeypatch):
    registry_path = tmp_path / "peer_registry.json"
    monkeypatch.setattr(
        "services.mesh.mesh_peer_registry.DEFAULT_PEER_REGISTRY_PATH",
        registry_path,
    )
    registry = PeerRegistry(registry_path)
    peer = registry.upsert_announcement(
        peer_url="http://abc123.onion:8000",
        transport="onion",
        role="participant",
        node_id="!sb_test",
        now=1_750_000_000,
    )
    registry.save()
    assert peer.peer_url == "http://abc123.onion:8000"
    assert registry.prune_stale(max_age_s=3600, now=1_750_000_500) == 0
    assert registry.prune_stale(max_age_s=60, now=1_750_010_000) == 1


def test_publish_registry_manifest_round_trip(tmp_path, monkeypatch):
    signer = generate_bootstrap_signer()
    manifest_path = tmp_path / "bootstrap_peers.json"
    registry_path = tmp_path / "peer_registry.json"
    monkeypatch.setenv("MESH_BOOTSTRAP_SIGNER_PUBLIC_KEY", signer["public_key_b64"])
    monkeypatch.setenv("MESH_BOOTSTRAP_SIGNER_PRIVATE_KEY", signer["private_key_b64"])
    monkeypatch.setenv("MESH_PEER_REGISTRY_ENABLED", "true")
    monkeypatch.setenv(
        "MESH_BOOTSTRAP_SEED_PEERS",
        "http://seedpeer.onion:8000",
    )
    monkeypatch.setenv("MESH_BOOTSTRAP_MANIFEST_PATH", str(manifest_path))
    monkeypatch.setattr(
        "services.mesh.mesh_peer_registry.DEFAULT_PEER_REGISTRY_PATH",
        registry_path,
    )
    from services.config import get_settings

    get_settings.cache_clear()
    try:
        assert peer_registry_enabled() is True
        manifest = publish_registry_manifest(now=1_750_000_000, persist=True)
        assert manifest_path.exists()
        parsed = parse_bootstrap_manifest_dict(
            json.loads(manifest_path.read_text(encoding="utf-8")),
            signer_public_key_b64=signer["public_key_b64"],
            now=1_750_000_000,
        )
        assert parsed.signer_id == manifest.signer_id
        assert any(peer.role == "seed" for peer in parsed.peers)
    finally:
        get_settings.cache_clear()


def test_record_peer_announcement_updates_store(tmp_path, monkeypatch):
    signer = generate_bootstrap_signer()
    registry_path = tmp_path / "peer_registry.json"
    peer_store_path = tmp_path / "peer_store.json"
    manifest_path = tmp_path / "bootstrap_peers.json"
    monkeypatch.setenv("MESH_BOOTSTRAP_SIGNER_PUBLIC_KEY", signer["public_key_b64"])
    monkeypatch.setenv("MESH_BOOTSTRAP_SIGNER_PRIVATE_KEY", signer["private_key_b64"])
    monkeypatch.setenv("MESH_PEER_REGISTRY_ENABLED", "true")
    monkeypatch.setenv("MESH_BOOTSTRAP_MANIFEST_PATH", str(manifest_path))
    monkeypatch.setenv("MESH_BOOTSTRAP_SEED_PEERS", "http://seedpeer.onion:8000")
    monkeypatch.setattr(
        "services.mesh.mesh_peer_registry.DEFAULT_PEER_REGISTRY_PATH",
        registry_path,
    )
    monkeypatch.setattr("services.mesh.mesh_peer_store.DEFAULT_PEER_STORE_PATH", peer_store_path)
    monkeypatch.setattr("services.mesh.mesh_swarm_runtime.DEFAULT_PEER_STORE_PATH", peer_store_path)
    from services.config import get_settings

    get_settings.cache_clear()
    try:
        peer = record_peer_announcement(
            {
                "peer_url": "http://participant.onion:8000",
                "transport": "onion",
                "role": "participant",
            },
            now=1_750_000_000,
        )
        assert peer.peer_url == "http://participant.onion:8000"
        store = PeerStore(peer_store_path)
        store.load()
        buckets = {record.bucket for record in store.records()}
        assert buckets == {"push", "sync"}
        assert any(record.source == "swarm" for record in store.records())
    finally:
        get_settings.cache_clear()


def test_merge_manifest_into_peer_store(tmp_path, monkeypatch):
    signer = generate_bootstrap_signer()
    peer_store_path = tmp_path / "peer_store.json"
    manifest_path = tmp_path / "bootstrap_peers.json"
    monkeypatch.setenv("MESH_BOOTSTRAP_SIGNER_PUBLIC_KEY", signer["public_key_b64"])
    monkeypatch.setenv("MESH_BOOTSTRAP_SIGNER_PRIVATE_KEY", signer["private_key_b64"])
    monkeypatch.setattr("services.mesh.mesh_peer_store.DEFAULT_PEER_STORE_PATH", peer_store_path)
    monkeypatch.setattr("services.mesh.mesh_swarm_runtime.DEFAULT_PEER_STORE_PATH", peer_store_path)
    manifest = write_signed_bootstrap_manifest(
        manifest_path,
        signer_id="test-signer",
        signer_private_key_b64=signer["private_key_b64"],
        peers=[
            {
                "peer_url": "http://relay.onion:8000",
                "transport": "onion",
                "role": "relay",
                "label": "relay-a",
            }
        ],
        issued_at=1_750_000_000,
        valid_until=1_750_360_000,
    )
    merged = merge_manifest_into_peer_store(manifest, now=1_750_000_000)
    assert merged == 1
    store = PeerStore(peer_store_path)
    store.load()
    assert len(store.records()) == 2


def test_parse_bootstrap_manifest_dict_rejects_expired():
    signer = generate_bootstrap_signer()
    manifest_path = None
    payload = {
        "version": 1,
        "issued_at": 1,
        "valid_until": 2,
        "signer_id": "test",
        "peers": [
            {
                "peer_url": "http://seedpeer.onion:8000",
                "transport": "onion",
                "role": "seed",
            }
        ],
    }
    from services.mesh.mesh_bootstrap_manifest import build_bootstrap_manifest_payload, sign_bootstrap_manifest_payload

    signed_payload = build_bootstrap_manifest_payload(
        signer_id="test",
        peers=payload["peers"],
        issued_at=1,
        valid_until=2,
    )
    signature = sign_bootstrap_manifest_payload(
        signed_payload,
        signer_private_key_b64=signer["private_key_b64"],
    )
    raw = dict(signed_payload)
    raw["signature"] = signature
    with pytest.raises(BootstrapManifestError, match="expired"):
        parse_bootstrap_manifest_dict(
            raw,
            signer_public_key_b64=signer["public_key_b64"],
            now=time.time(),
        )


def test_refresh_swarm_manifest_reports_retrying_when_all_seeds_unreachable(monkeypatch):
    from services.config import get_settings

    monkeypatch.setenv("MESH_BOOTSTRAP_SIGNER_PUBLIC_KEY", "ul1d0kj/ODPIp0OhHzX8eLAVXzJ3CVvzW1vn2IC6q3I=")
    monkeypatch.setenv(
        "MESH_BOOTSTRAP_SEED_PEERS",
        "http://seed-a.onion:8000,http://seed-b.onion:8000",
    )
    monkeypatch.setattr(
        "services.mesh.mesh_swarm_runtime.fetch_remote_bootstrap_manifest",
        lambda *_args, **_kwargs: None,
    )
    get_settings.cache_clear()
    try:
        result = refresh_swarm_manifest_from_seeds(force=True, now=1_750_000_000)
    finally:
        get_settings.cache_clear()

    assert result["ok"] is False
    assert result["retrying"] is True
    assert result["tried_seed_count"] == 2
    assert result["detail"] == "bootstrap seeds unreachable; local node will retry"


@pytest.mark.asyncio
async def test_bootstrap_manifest_endpoint_serves_live_registry(tmp_path, monkeypatch):
    import main

    signer = generate_bootstrap_signer()
    registry_path = tmp_path / "peer_registry.json"
    manifest_path = tmp_path / "bootstrap_peers.json"
    monkeypatch.setenv("MESH_BOOTSTRAP_SIGNER_PUBLIC_KEY", signer["public_key_b64"])
    monkeypatch.setenv("MESH_BOOTSTRAP_SIGNER_PRIVATE_KEY", signer["private_key_b64"])
    monkeypatch.setenv("MESH_PEER_REGISTRY_ENABLED", "true")
    monkeypatch.setenv("MESH_BOOTSTRAP_MANIFEST_PATH", str(manifest_path))
    monkeypatch.setenv("MESH_BOOTSTRAP_SEED_PEERS", "http://seedpeer.onion:8000")
    monkeypatch.setattr("services.mesh.mesh_peer_registry.DEFAULT_PEER_REGISTRY_PATH", registry_path)
    from services.config import get_settings

    get_settings.cache_clear()
    try:
        now = int(time.time())
        record_peer_announcement(
            {
                "peer_url": "http://participant.onion:8000",
                "transport": "onion",
                "role": "participant",
            },
            now=now,
        )
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.get("/api/mesh/infonet/bootstrap-manifest")
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        manifest = body["manifest"]
        peer_urls = [peer["peer_url"] for peer in manifest["peers"]]
        assert "http://participant.onion:8000" in peer_urls
        assert "http://seedpeer.onion:8000" in peer_urls
    finally:
        get_settings.cache_clear()
