from services.mesh.mesh_peer_store import (
    PeerStore,
    make_bootstrap_peer_record,
    make_push_peer_record,
    make_sync_peer_record,
)


def test_peer_store_preserves_provenance_across_buckets(tmp_path):
    store = PeerStore(tmp_path / "peer_store.json")
    bootstrap = make_bootstrap_peer_record(
        peer_url="https://seed.example",
        transport="clearnet",
        role="seed",
        signer_id="bootstrap-a",
        now=100,
    )
    sync_peer = make_sync_peer_record(
        peer_url="https://seed.example",
        transport="clearnet",
        role="seed",
        source="bootstrap_promoted",
        signer_id="bootstrap-a",
        now=101,
    )
    push_peer = make_push_peer_record(
        peer_url="https://seed.example",
        transport="clearnet",
        role="seed",
        now=102,
    )

    store.upsert(bootstrap)
    store.upsert(sync_peer)
    store.upsert(push_peer)

    assert [record.bucket for record in store.records()] == ["bootstrap", "push", "sync"]
    assert [record.source for record in store.records_for_bucket("sync")] == ["bootstrap_promoted"]
    assert [record.source for record in store.records_for_bucket("push")] == ["operator"]


def test_peer_store_save_load_roundtrip(tmp_path):
    path = tmp_path / "peer_store.json"
    store = PeerStore(path)
    store.upsert(
        make_bootstrap_peer_record(
            peer_url="https://seed.example",
            transport="clearnet",
            role="seed",
            signer_id="bootstrap-a",
            now=100,
        )
    )
    store.upsert(
        make_sync_peer_record(
            peer_url="http://alphaexample.onion",
            transport="onion",
            role="relay",
            source="operator",
            now=101,
        )
    )
    store.save()

    loaded = PeerStore(path)
    records = loaded.load()

    assert len(records) == 2
    assert [record.bucket for record in records] == ["bootstrap", "sync"]
    assert records[0].signer_id == "bootstrap-a"
    assert records[1].peer_url == "http://alphaexample.onion"


def test_peer_store_failure_and_success_lifecycle(tmp_path):
    store = PeerStore(tmp_path / "peer_store.json")
    store.upsert(
        make_sync_peer_record(
            peer_url="https://sync.example",
            transport="clearnet",
            now=100,
        )
    )
    failed = store.mark_failure(
        "https://sync.example",
        "sync",
        error="timeout",
        cooldown_s=30,
        now=200,
    )
    assert failed.failure_count == 1
    assert failed.cooldown_until == 230
    assert failed.last_error == "timeout"

    recovered = store.mark_sync_success("https://sync.example", now=250)
    assert recovered.failure_count == 0
    assert recovered.cooldown_until == 0
    assert recovered.last_error == ""
    assert recovered.last_sync_ok_at == 250
