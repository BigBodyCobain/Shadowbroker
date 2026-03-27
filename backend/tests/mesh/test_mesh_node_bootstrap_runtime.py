import asyncio
import base64
import json
from types import SimpleNamespace

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from httpx import ASGITransport, AsyncClient


def _write_signed_manifest(path, *, private_key):
    from services.mesh.mesh_bootstrap_manifest import BOOTSTRAP_MANIFEST_VERSION
    from services.mesh.mesh_crypto import canonical_json

    payload = {
        "version": BOOTSTRAP_MANIFEST_VERSION,
        "issued_at": 1_700_000_000,
        "valid_until": 1_800_000_000,
        "signer_id": "bootstrap-a",
        "peers": [
            {
                "peer_url": "https://seed.example",
                "transport": "clearnet",
                "role": "seed",
                "label": "Seed A",
            }
        ],
    }
    signature = base64.b64encode(private_key.sign(canonical_json(payload).encode("utf-8"))).decode("utf-8")
    path.write_text(json.dumps({**payload, "signature": signature}), encoding="utf-8")


def test_refresh_node_peer_store_promotes_manifest_peers_to_sync_only(tmp_path, monkeypatch):
    import main
    from services.config import get_settings
    from services.mesh import mesh_bootstrap_manifest as manifest_mod
    from services.mesh import mesh_peer_store as peer_store_mod

    manifest_key = ed25519.Ed25519PrivateKey.generate()
    manifest_pub = base64.b64encode(
        manifest_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
    ).decode("utf-8")
    manifest_path = tmp_path / "bootstrap.json"
    peer_store_path = tmp_path / "peer_store.json"
    _write_signed_manifest(manifest_path, private_key=manifest_key)

    monkeypatch.setattr(manifest_mod, "DEFAULT_BOOTSTRAP_MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(peer_store_mod, "DEFAULT_PEER_STORE_PATH", peer_store_path)
    monkeypatch.setenv("MESH_BOOTSTRAP_SIGNER_PUBLIC_KEY", manifest_pub)
    monkeypatch.setenv("MESH_BOOTSTRAP_MANIFEST_PATH", str(manifest_path))
    monkeypatch.setenv("MESH_RELAY_PEERS", "https://operator.example")
    get_settings.cache_clear()

    try:
        snapshot = main._refresh_node_peer_store(now=1_750_000_000)
        store = peer_store_mod.PeerStore(peer_store_path)
        store.load()
    finally:
        get_settings.cache_clear()

    assert snapshot["manifest_loaded"] is True
    assert snapshot["bootstrap_peer_count"] == 1
    assert snapshot["sync_peer_count"] == 2
    assert snapshot["push_peer_count"] == 1
    assert [record.peer_url for record in store.records_for_bucket("bootstrap")] == ["https://seed.example"]
    assert sorted(record.peer_url for record in store.records_for_bucket("sync")) == [
        "https://operator.example",
        "https://seed.example",
    ]
    assert [record.peer_url for record in store.records_for_bucket("push")] == ["https://operator.example"]


def test_verify_peer_push_hmac_requires_allowlisted_peer(monkeypatch):
    import hashlib
    import hmac

    import main
    from services.config import get_settings
    from services.mesh.mesh_crypto import _derive_peer_key

    monkeypatch.setenv("MESH_PEER_PUSH_SECRET", "shared-secret")
    get_settings.cache_clear()
    monkeypatch.setattr(main, "authenticated_push_peer_urls", lambda *args, **kwargs: ["https://good.example"])

    try:
        body = b'{"events":[]}'
        peer_url = "https://bad.example"
        peer_key = _derive_peer_key("shared-secret", peer_url)
        signature = hmac.new(peer_key, body, hashlib.sha256).hexdigest()
        request = SimpleNamespace(
            headers={"x-peer-url": peer_url, "x-peer-hmac": signature},
            url=SimpleNamespace(scheme="https", netloc="bad.example"),
        )
        assert main._verify_peer_push_hmac(request, body) is False
    finally:
        get_settings.cache_clear()


def test_infonet_status_includes_node_runtime_snapshot(monkeypatch):
    import main
    from services import wormhole_supervisor

    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": False},
    )
    monkeypatch.setattr(
        main,
        "_node_runtime_snapshot",
        lambda: {
            "node_mode": "participant",
            "node_enabled": True,
            "bootstrap": {"sync_peer_count": 2, "push_peer_count": 1},
            "sync_runtime": {"last_outcome": "ok"},
            "push_runtime": {"last_event_id": "evt-1"},
        },
    )

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.get("/api/mesh/infonet/status")
            return response.json()

    result = asyncio.run(_run())

    assert result["node_mode"] == "participant"
    assert result["node_enabled"] is True
    assert result["bootstrap"]["sync_peer_count"] == 2
    assert result["bootstrap"]["push_peer_count"] == 1
    assert result["sync_runtime"]["last_outcome"] == "ok"
    assert result["push_runtime"]["last_event_id"] == "evt-1"
