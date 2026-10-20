import asyncio
import base64
import json
from types import SimpleNamespace

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from httpx import ASGITransport, AsyncClient


def test_onion_peer_requests_use_arti_socks_proxy(monkeypatch):
    import main
    from services import wormhole_supervisor

    monkeypatch.setattr(main, "_infonet_private_transport_required", lambda: True)
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: SimpleNamespace(MESH_ARTI_ENABLED=True, MESH_ARTI_SOCKS_PORT=19050),
    )
    monkeypatch.setattr(wormhole_supervisor, "_check_arti_ready", lambda: True)

    proxies = main._infonet_peer_requests_proxies("http://exampleabcd.onion:8000")

    assert proxies == {
        "http": "socks5h://127.0.0.1:19050",
        "https": "socks5h://127.0.0.1:19050",
    }


def test_private_peer_requests_reject_clearnet(monkeypatch):
    import main

    monkeypatch.setattr(main, "_infonet_private_transport_required", lambda: True)

    try:
        main._infonet_peer_requests_proxies("https://seed.example")
    except RuntimeError as exc:
        assert "private Infonet requires onion/RNS transport" in str(exc)
    else:
        raise AssertionError("clearnet peer was allowed while private transport is required")


def test_local_peer_url_prefers_configured_public_peer_url(monkeypatch):
    import main

    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: SimpleNamespace(
            MESH_PUBLIC_PEER_URL="HTTP://LOCALPEEREXAMPLE.onion:8000/",
        ),
    )

    assert main._local_infonet_peer_url() == "http://localpeerexample.onion:8000"


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
    monkeypatch.setenv("MESH_BOOTSTRAP_SEED_PEERS", "")
    monkeypatch.setenv("MESH_DEFAULT_SYNC_PEERS", "")
    monkeypatch.setenv("MESH_INFONET_ALLOW_CLEARNET_SYNC", "true")
    monkeypatch.setenv("MESH_INFONET_FLEET_JOIN_DISABLED", "true")
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


def test_refresh_node_peer_store_adds_bootstrap_seed_as_pull_only_peer(tmp_path, monkeypatch):
    import main
    from services.config import get_settings
    from services.mesh import mesh_peer_store as peer_store_mod

    peer_store_path = tmp_path / "peer_store.json"
    monkeypatch.setattr(peer_store_mod, "DEFAULT_PEER_STORE_PATH", peer_store_path)
    monkeypatch.setenv("MESH_RELAY_PEERS", "")
    monkeypatch.setenv("MESH_BOOTSTRAP_SEED_PEERS", "https://node.shadowbroker.info")
    monkeypatch.setenv("MESH_DEFAULT_SYNC_PEERS", "")
    monkeypatch.setenv("MESH_INFONET_ALLOW_CLEARNET_SYNC", "true")
    monkeypatch.setenv("MESH_BOOTSTRAP_SIGNER_PUBLIC_KEY", "")
    monkeypatch.setenv("MESH_INFONET_FLEET_JOIN_DISABLED", "true")
    get_settings.cache_clear()

    try:
        snapshot = main._refresh_node_peer_store(now=1_750_000_000)
        store = peer_store_mod.PeerStore(peer_store_path)
        store.load()
    finally:
        get_settings.cache_clear()

    assert snapshot["manifest_loaded"] is False
    assert snapshot["bootstrap_seed_peer_count"] == 1
    assert snapshot["default_sync_peer_count"] == 1
    assert snapshot["bootstrap_peer_count"] == 1
    assert snapshot["sync_peer_count"] == 1
    assert snapshot["push_peer_count"] == 0
    assert [record.peer_url for record in store.records_for_bucket("bootstrap")] == [
        "https://node.shadowbroker.info"
    ]
    assert [record.peer_url for record in store.records_for_bucket("sync")] == [
        "https://node.shadowbroker.info"
    ]
    assert store.records_for_bucket("sync")[0].source == "bundle"


def test_refresh_node_peer_store_suppresses_clearnet_seed_by_default(tmp_path, monkeypatch):
    import main
    from services.config import get_settings
    from services.mesh import mesh_peer_store as peer_store_mod

    peer_store_path = tmp_path / "peer_store.json"
    monkeypatch.setattr(peer_store_mod, "DEFAULT_PEER_STORE_PATH", peer_store_path)
    monkeypatch.setenv("MESH_RELAY_PEERS", "")
    monkeypatch.setenv("MESH_BOOTSTRAP_SEED_PEERS", "https://node.shadowbroker.info")
    monkeypatch.setenv("MESH_DEFAULT_SYNC_PEERS", "")
    monkeypatch.delenv("MESH_INFONET_ALLOW_CLEARNET_SYNC", raising=False)
    monkeypatch.setenv("MESH_BOOTSTRAP_SIGNER_PUBLIC_KEY", "")
    monkeypatch.setenv("MESH_INFONET_FLEET_JOIN_DISABLED", "true")
    get_settings.cache_clear()

    try:
        snapshot = main._refresh_node_peer_store(now=1_750_000_000)
        store = peer_store_mod.PeerStore(peer_store_path)
        store.load()
    finally:
        get_settings.cache_clear()

    assert snapshot["private_transport_required"] is True
    assert snapshot["skipped_clearnet_peer_count"] == 1
    assert snapshot["bootstrap_peer_count"] == 0
    assert snapshot["sync_peer_count"] == 0
    assert snapshot["last_bootstrap_error"]
    assert store.records_for_bucket("bootstrap") == []
    assert store.records_for_bucket("sync") == []


def test_refresh_node_peer_store_prunes_persisted_clearnet_records_in_private_mode(tmp_path, monkeypatch):
    import main
    from services.config import get_settings
    from services.mesh import mesh_peer_store as peer_store_mod

    peer_store_path = tmp_path / "peer_store.json"
    monkeypatch.setattr(peer_store_mod, "DEFAULT_PEER_STORE_PATH", peer_store_path)
    store = peer_store_mod.PeerStore(peer_store_path)
    store.upsert(
        peer_store_mod.make_bootstrap_peer_record(
            peer_url="https://node.shadowbroker.info",
            transport="clearnet",
            role="seed",
            signer_id="shadowbroker-default",
            now=1_749_999_900,
        )
    )
    store.upsert(
        peer_store_mod.make_sync_peer_record(
            peer_url="https://node.shadowbroker.info",
            transport="clearnet",
            role="seed",
            source="bundle",
            now=1_749_999_900,
        )
    )
    store.upsert(
        peer_store_mod.make_push_peer_record(
            peer_url="https://node.shadowbroker.info",
            transport="clearnet",
            role="relay",
            now=1_749_999_900,
        )
    )
    store.save()

    onion_seed = "http://gqpbunqbgtkcqilvclm3xrkt3zowjyl3s62kkktvojgvxzizamvbrqid.onion:8000"
    monkeypatch.setenv("MESH_RELAY_PEERS", "")
    monkeypatch.setenv("MESH_BOOTSTRAP_SEED_PEERS", onion_seed)
    monkeypatch.setenv("MESH_DEFAULT_SYNC_PEERS", "")
    monkeypatch.delenv("MESH_INFONET_ALLOW_CLEARNET_SYNC", raising=False)
    monkeypatch.setenv("MESH_BOOTSTRAP_SIGNER_PUBLIC_KEY", "")
    get_settings.cache_clear()

    try:
        snapshot = main._refresh_node_peer_store(now=1_750_000_000)
        store = peer_store_mod.PeerStore(peer_store_path)
        store.load()
    finally:
        get_settings.cache_clear()

    assert snapshot["private_transport_required"] is True
    assert snapshot["pruned_clearnet_peer_count"] == 3
    assert [record.peer_url for record in store.records()] == [onion_seed, onion_seed]
    assert {record.bucket for record in store.records()} == {"bootstrap", "sync"}
    assert all(record.transport == "onion" for record in store.records())


def test_infonet_peer_url_filter_excludes_clearnet_in_private_mode(monkeypatch):
    import main
    from services.config import get_settings

    monkeypatch.delenv("MESH_INFONET_ALLOW_CLEARNET_SYNC", raising=False)
    get_settings.cache_clear()

    try:
        assert main._filter_infonet_peer_urls(
            [
                "https://node.shadowbroker.info",
                "http://gqpbunqbgtkcqilvclm3xrkt3zowjyl3s62kkktvojgvxzizamvbrqid.onion:8000",
            ]
        ) == ["http://gqpbunqbgtkcqilvclm3xrkt3zowjyl3s62kkktvojgvxzizamvbrqid.onion:8000"]
    finally:
        get_settings.cache_clear()


def test_public_sync_cycle_backs_off_on_429_retry_after(tmp_path, monkeypatch):
    import time

    import main
    from services.config import get_settings
    from services.mesh import mesh_peer_store as peer_store_mod

    peer_store_path = tmp_path / "peer_store.json"
    monkeypatch.setattr(peer_store_mod, "DEFAULT_PEER_STORE_PATH", peer_store_path)
    onion_seed = "http://gqpbunqbgtkcqilvclm3xrkt3zowjyl3s62kkktvojgvxzizamvbrqid.onion:8000"
    store = peer_store_mod.PeerStore(peer_store_path)
    store.upsert(
        peer_store_mod.make_sync_peer_record(
            peer_url=onion_seed,
            transport="onion",
            role="seed",
            source="bundle",
            now=1_750_000_000,
        )
    )
    store.save()

    monkeypatch.delenv("MESH_INFONET_ALLOW_CLEARNET_SYNC", raising=False)
    monkeypatch.setenv("MESH_SYNC_FAILURE_BACKOFF_S", "60")
    monkeypatch.setenv("MESH_BOOTSTRAP_SEED_FAILURE_COOLDOWN_S", "15")
    get_settings.cache_clear()
    monkeypatch.setattr(main, "_participant_node_enabled", lambda: True)
    monkeypatch.setattr(main, "_ensure_infonet_private_transport_ready", lambda reason="": True)
    monkeypatch.setattr(
        main,
        "_sync_from_peer",
        lambda peer_url: (_ for _ in ()).throw(
            main.PeerSyncHTTPError(429, "rate limited", retry_after_s=180)
        ),
    )
    main.set_sync_state(main.SyncWorkerState())

    try:
        before = int(time.time())
        state = main._run_public_sync_cycle()
        store = peer_store_mod.PeerStore(peer_store_path)
        store.load()
    finally:
        get_settings.cache_clear()
        main.set_sync_state(main.SyncWorkerState())

    record = store.records_for_bucket("sync")[0]
    assert state.last_error == "HTTP 429: rate limited"
    assert state.next_sync_due_at >= before + 180
    assert record.cooldown_until >= before + 180


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


def test_public_sync_cycle_allows_first_node_without_peers(tmp_path, monkeypatch):
    import main
    from services.config import get_settings
    from services.mesh import mesh_peer_store as peer_store_mod

    peer_store_path = tmp_path / "peer_store.json"
    monkeypatch.setattr(peer_store_mod, "DEFAULT_PEER_STORE_PATH", peer_store_path)
    monkeypatch.setattr(main, "_participant_node_enabled", lambda: True)
    monkeypatch.setenv("MESH_INFONET_ALLOW_CLEARNET_SYNC", "true")
    get_settings.cache_clear()

    try:
        result = main._run_public_sync_cycle()
    finally:
        get_settings.cache_clear()

    assert result.last_outcome == "solo"
    assert result.last_error == ""
    assert result.last_peer_url == ""
    assert result.consecutive_failures == 0


def test_sync_from_peer_explains_stale_genesis_chain(monkeypatch):
    import main
    from services.mesh import mesh_hashchain

    class FakeInfonet:
        events = []
        head_hash = mesh_hashchain.GENESIS_HASH

        def get_locator(self):
            return [mesh_hashchain.GENESIS_HASH]

        def ingest_events(self, events):
            return {
                "accepted": 0,
                "duplicates": 0,
                "rejected": [
                    {"index": 0, "reason": "Event timestamp outside freshness window"},
                    {"index": 1, "reason": "prev_hash does not match head"},
                ],
            }

    stale_events = [
        {
            "event_id": "old-1",
            "prev_hash": mesh_hashchain.GENESIS_HASH,
            "event_type": "message",
            "timestamp": 1,
        },
        {
            "event_id": "old-2",
            "prev_hash": "old-1",
            "event_type": "message",
            "timestamp": 2,
        },
    ]

    monkeypatch.setattr(mesh_hashchain, "infonet", FakeInfonet())
    monkeypatch.setattr(main, "_peer_sync_response", lambda *_args, **_kwargs: {"events": stale_events})
    monkeypatch.setattr(main, "_hydrate_gate_store_from_chain", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "_hydrate_dm_relay_from_chain", lambda *_args, **_kwargs: None)

    ok, error, forked, retry_after_s = main._sync_from_peer("https://node.shadowbroker.info")

    assert ok is False
    assert forked is False
    assert retry_after_s == 0
    assert "Event timestamp outside freshness window" in error
    assert "expired genesis chain" in error
    assert "MESH_INGEST_EVENT_MAX_AGE_S=0" in error


def test_headless_mesh_node_runtime_is_explicit(monkeypatch):
    import main

    monkeypatch.setattr(main, "_MESH_ONLY", True)
    monkeypatch.setattr(main, "_HEADLESS_MESH_NODE_RUNTIME", False)
    assert main._infonet_node_runtime_requested() is False

    monkeypatch.setattr(main, "_HEADLESS_MESH_NODE_RUNTIME", True)
    assert main._infonet_node_runtime_requested() is True


def test_meshnode_scripts_enable_private_hashchain_runtime():
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    bat = (root / "meshnode.bat").read_text(encoding="utf-8")
    sh = (root / "meshnode.sh").read_text(encoding="utf-8")

    for script in (bat, sh):
        assert "SHADOWBROKER_MESH_NODE_RUNTIME=true" in script
        assert "MESH_INFONET_ALLOW_CLEARNET_SYNC=false" in script
        assert "MESH_ARTI_ENABLED=true" in script
        assert "MESH_DM_HASHCHAIN_SPOOL_LIMIT=2" in script
        assert "sb-testnet fleet defaults" in script
