import hashlib
import json
import time

from services.mesh import mesh_hashchain
from services.mesh.mesh_secure_storage import read_domain_json, write_domain_json


def _make_store(tmp_path, monkeypatch):
    store_dir = tmp_path / "gate_messages"
    store_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(mesh_hashchain, "GATE_STORE_DIR", store_dir)
    monkeypatch.setattr(mesh_hashchain, "GATE_SEGMENT_EVENT_TARGET", 2)
    monkeypatch.setattr(mesh_hashchain, "GATE_SEGMENT_MAX_COMPRESSED_BYTES", 1024 * 1024)
    return mesh_hashchain.GateMessageStore(data_dir=str(store_dir))


def _make_event(gate_id: str, idx: int, *, ts: float | None = None) -> dict:
    now = time.time() if ts is None else ts
    ciphertext = f"ct-{idx}-compressible-secret-" + ("x" * 128)
    return {
        "event_id": hashlib.sha256(f"{gate_id}|{idx}|{now}".encode("utf-8")).hexdigest(),
        "event_type": "gate_message",
        "node_id": f"node-{idx}",
        "timestamp": now,
        "sequence": idx + 1,
        "signature": "deadbeef",
        "public_key": "dGVzdA==",
        "public_key_algo": "Ed25519",
        "protocol_version": "1.0",
        "payload": {
            "gate": gate_id,
            "ciphertext": ciphertext,
            "nonce": f"nonce-{idx}",
            "sender_ref": f"sender-{idx}",
            "format": "mls1",
            "gate_envelope": f"env-{idx}",
            "envelope_hash": hashlib.sha256(f"env-{idx}".encode("ascii")).hexdigest(),
        },
    }


def _manifest(store, gate_id: str) -> dict:
    return read_domain_json(
        mesh_hashchain.GATE_STORAGE_DOMAIN,
        store._gate_manifest_filename(gate_id),
        lambda: {},
        base_dir=store._gate_storage_base_dir(),
    )


def test_gate_storage_segments_compress_and_reload(tmp_path, monkeypatch):
    store = _make_store(tmp_path, monkeypatch)
    base_ts = time.time()
    for idx in range(5):
        store.append("longterm-gate", _make_event("longterm-gate", idx, ts=base_ts + idx))

    manifest = _manifest(store, "longterm-gate")
    assert manifest["storage"] == "gate-segments-v1"
    assert manifest["segment_count"] == 3
    assert manifest["total_events"] == 5
    assert [segment["count"] for segment in manifest["segments"]] == [2, 2, 1]

    first_segment = manifest["segments"][0]
    segment_payload, segment_events = store._read_segment_file(first_segment["filename"])
    assert segment_payload["codec"] == "zlib"
    assert len(segment_events) == 2
    assert "compressible-secret" not in json.dumps(segment_payload)
    assert "compressible-secret" not in (store._gate_domain_dir() / first_segment["filename"]).read_text(encoding="utf-8")

    reloaded = mesh_hashchain.GateMessageStore(data_dir=str(store._data_dir))
    messages = reloaded.get_messages("longterm-gate", limit=10)
    assert [msg["payload"]["ciphertext"] for msg in reversed(messages)] == [
        f"ct-{idx}-compressible-secret-" + ("x" * 128)
        for idx in range(5)
    ]


def test_legacy_encrypted_gate_list_migrates_to_segments(tmp_path, monkeypatch):
    store_dir = tmp_path / "gate_messages"
    store_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(mesh_hashchain, "GATE_STORE_DIR", store_dir)
    monkeypatch.setattr(mesh_hashchain, "GATE_SEGMENT_EVENT_TARGET", 2)

    gate_id = "legacy-domain-gate"
    digest = hashlib.sha256(gate_id.encode("utf-8")).hexdigest()
    legacy_filename = f"gate_{digest}.jsonl"
    legacy_event = _make_event(gate_id, 0)
    write_domain_json(
        mesh_hashchain.GATE_STORAGE_DOMAIN,
        legacy_filename,
        [legacy_event],
        base_dir=store_dir.parent,
    )

    store = mesh_hashchain.GateMessageStore(data_dir=str(store_dir))
    assert store.get_messages(gate_id)[0]["payload"]["ciphertext"].startswith("ct-0-")

    manifest = _manifest(store, gate_id)
    assert manifest["storage"] == "gate-segments-v1"
    assert manifest["total_events"] == 1
    assert not (store._gate_domain_dir() / legacy_filename).exists()


def test_incremental_append_only_writes_head_segment_or_new_segment(tmp_path, monkeypatch):
    store = _make_store(tmp_path, monkeypatch)
    original_write = mesh_hashchain.write_domain_json
    written: list[str] = []

    def _tracking_write(domain, filename, payload, *, base_dir=None):
        written.append(filename)
        return original_write(domain, filename, payload, base_dir=base_dir)

    monkeypatch.setattr(mesh_hashchain, "write_domain_json", _tracking_write)
    base_ts = time.time()
    store.append("append-gate", _make_event("append-gate", 0, ts=base_ts))
    store.append("append-gate", _make_event("append-gate", 1, ts=base_ts + 1))
    written.clear()

    store.append("append-gate", _make_event("append-gate", 2, ts=base_ts + 2))

    digest = hashlib.sha256("append-gate".encode("utf-8")).hexdigest()
    assert f"gate_{digest}_seg_00000000.gseg" not in written
    assert f"gate_{digest}_seg_00000001.gseg" in written
    assert f"gate_{digest}.manifest.json" in written


def test_full_rebuild_removes_stale_segments(tmp_path, monkeypatch):
    store = _make_store(tmp_path, monkeypatch)
    base_ts = time.time()
    for idx in range(5):
        store.append("compact-gate", _make_event("compact-gate", idx, ts=base_ts + idx))

    before = _manifest(store, "compact-gate")
    assert before["segment_count"] == 3
    stale_filename = before["segments"][-1]["filename"]
    assert (store._gate_domain_dir() / stale_filename).exists()

    kept = store._gates["compact-gate"][:2]
    store._persist_gate("compact-gate", kept)

    after = _manifest(store, "compact-gate")
    assert after["segment_count"] == 1
    assert not (store._gate_domain_dir() / stale_filename).exists()
