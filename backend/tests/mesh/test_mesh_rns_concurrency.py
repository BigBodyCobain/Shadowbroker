import base64
import json
import random
import threading
import time
import uuid
from types import SimpleNamespace

from services.mesh.mesh_hashchain import infonet
from services.mesh.mesh_rns import RNSBridge


def _xor_parity(data: list[bytes]) -> bytes:
    parity = data[0]
    for shard in data[1:]:
        parity = bytes(a ^ b for a, b in zip(parity, shard))
    return parity


def _make_shard_body(
    shard_id: str,
    index: int,
    total: int,
    data_shards: int,
    parity_shards: int,
    size: int,
    length: int,
    parity: bool,
    fec: str,
    blob: bytes,
) -> dict:
    return {
        "shard_id": shard_id,
        "index": index,
        "total": total,
        "data_shards": data_shards,
        "parity_shards": parity_shards,
        "size": size,
        "length": length,
        "parity": parity,
        "fec": fec,
        "data": base64.b64encode(blob).decode("ascii"),
    }


def test_rns_quorum_thread_safety(monkeypatch) -> None:
    bridge = RNSBridge()
    sync_id = "sync-test"
    head_hash = infonet.head_hash or "head"
    with bridge._sync_lock:
        bridge._pending_sync[sync_id] = {
            "created": time.time(),
            "expected": set(),
            "quorum": 2,
            "responses": {},
            "responders": set(),
        }

    ingested: list[list[dict]] = []

    def _fake_ingest(events: list[dict]) -> None:
        ingested.append(events)

    monkeypatch.setattr(bridge, "_ingest_ordered", _fake_ingest)

    threads = []
    for idx in range(4):
        meta = {"sync_id": sync_id, "head_hash": head_hash, "reply_to": f"peer-{idx}"}
        t = threading.Thread(
            target=bridge._ingest_with_quorum, args=([{"event_id": f"e{idx}"}], meta)
        )
        threads.append(t)
        t.start()
    for t in threads:
        t.join()

    assert sync_id not in bridge._pending_sync
    assert ingested


def test_rns_shard_reassembly_thread_safety(monkeypatch) -> None:
    bridge = RNSBridge()
    payload = b"mesh-concurrency" * 256
    data_shards = 4
    data, length = bridge._split_payload(payload, data_shards)
    size = len(data[0])
    parity = _xor_parity(data)
    shard_id = uuid.uuid4().hex
    total = data_shards + 1

    bodies = [
        _make_shard_body(
            shard_id,
            idx,
            total,
            data_shards,
            1,
            size,
            length,
            False,
            "xor",
            shard,
        )
        for idx, shard in enumerate(data)
    ]
    bodies.append(
        _make_shard_body(
            shard_id,
            data_shards,
            total,
            data_shards,
            1,
            size,
            length,
            True,
            "xor",
            parity,
        )
    )
    random.shuffle(bodies)

    assembled: list[bytes] = []

    def _fake_on_packet(data: bytes, packet=None) -> None:
        assembled.append(data)

    monkeypatch.setattr(bridge, "_on_packet", _fake_on_packet)

    threads = [threading.Thread(target=bridge._handle_infonet_shard, args=(body,)) for body in bodies]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert assembled
    assert assembled[-1] == payload


def test_rns_shard_reassembly_with_loss_and_delay(monkeypatch) -> None:
    bridge = RNSBridge()
    payload = b"mesh-loss-delay" * 256
    data_shards = 5
    data, length = bridge._split_payload(payload, data_shards)
    size = len(data[0])
    parity = _xor_parity(data)
    shard_id = uuid.uuid4().hex
    total = data_shards + 1

    bodies = [
        _make_shard_body(
            shard_id,
            idx,
            total,
            data_shards,
            1,
            size,
            length,
            False,
            "xor",
            shard,
        )
        for idx, shard in enumerate(data)
    ]
    bodies.append(
        _make_shard_body(
            shard_id,
            data_shards,
            total,
            data_shards,
            1,
            size,
            length,
            True,
            "xor",
            parity,
        )
    )

    rng = random.Random(1337)
    drop_index = rng.randrange(data_shards)
    bodies = [b for b in bodies if not (not b["parity"] and b["index"] == drop_index)]
    rng.shuffle(bodies)

    assembled: list[bytes] = []

    def _fake_on_packet(data: bytes, packet=None) -> None:
        assembled.append(data)

    monkeypatch.setattr(bridge, "_on_packet", _fake_on_packet)

    def _deliver(body: dict) -> None:
        time.sleep(rng.uniform(0.0, 0.03))
        bridge._handle_infonet_shard(body)

    threads = [threading.Thread(target=_deliver, args=(body,)) for body in bodies]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert assembled
    assert assembled[-1] == payload


def test_rns_publish_gate_event_freezes_current_v1_signer_bundle(monkeypatch) -> None:
    from services import config as config_mod
    from services.mesh import mesh_rns as mesh_rns_mod

    bridge = RNSBridge()
    sent: list[tuple[bytes, str | None]] = []
    settings = SimpleNamespace(
        MESH_PEER_PUSH_SECRET="peer-secret",
        MESH_RNS_MAX_PAYLOAD=8192,
        MESH_RNS_DANDELION_DELAY_MS=0,
    )

    monkeypatch.setattr(config_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(mesh_rns_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(bridge, "enabled", lambda: True)
    monkeypatch.setattr(bridge, "_maybe_rotate_session", lambda: None)
    monkeypatch.setattr(bridge, "_seen", lambda _message_id: False)
    monkeypatch.setattr(bridge, "_make_message_id", lambda prefix: f"{prefix}-wire-id")
    monkeypatch.setattr(bridge, "_dandelion_hops", lambda: 3)
    monkeypatch.setattr(bridge, "_pick_stem_peer", lambda: None)
    monkeypatch.setattr(
        bridge,
        "_send_diffuse",
        lambda payload, exclude=None: sent.append((payload, exclude)),
    )

    bridge.publish_gate_event(
        "finance",
        {
            "event_type": "gate_message",
            "timestamp": 1710000000,
            "event_id": "gate-evt-1",
            "node_id": "!gate-persona-1",
            "sequence": 19,
            "signature": "deadbeef",
            "public_key": "pubkey-1",
            "public_key_algo": "Ed25519",
            "protocol_version": "infonet/2",
            "payload": {
                "gate": "finance",
                "ciphertext": "abc123",
                "format": "mls1",
                "nonce": "nonce-7",
                "sender_ref": "sender-ref-7",
                "epoch": 4,
            },
        },
    )

    assert len(sent) == 1
    message, exclude = sent[0]
    decoded = json.loads(message.decode("utf-8"))
    event = decoded["body"]["event"]

    assert exclude is None
    assert decoded["type"] == "gate_event"
    assert decoded["meta"] == {
        "message_id": "gate-wire-id",
        "dandelion": {"phase": "stem", "hops": 0, "max_hops": 3},
    }
    assert set(event.keys()) == {
        "event_type",
        "timestamp",
        "payload",
        "event_id",
        "node_id",
        "sequence",
        "signature",
        "public_key",
        "public_key_algo",
        "protocol_version",
    }
    assert event["event_id"] == "gate-evt-1"
    assert event["node_id"] == "!gate-persona-1"
    assert event["sequence"] == 19
    assert event["signature"] == "deadbeef"
    assert event["public_key"] == "pubkey-1"
    assert event["public_key_algo"] == "Ed25519"
    assert event["protocol_version"] == "infonet/2"
    assert set(event["payload"].keys()) == {"ciphertext", "format", "gate_ref", "nonce", "sender_ref", "epoch"}
    assert event["payload"]["ciphertext"] == "abc123"
    assert event["payload"]["format"] == "mls1"
    assert event["payload"]["nonce"] == "nonce-7"
    assert event["payload"]["sender_ref"] == "sender-ref-7"
    assert event["payload"]["epoch"] == 4
    assert event["payload"]["gate_ref"]
    assert "gate" not in event["payload"]


def test_rns_inbound_gate_event_resolves_gate_ref_before_local_ingest(monkeypatch) -> None:
    from services import config as config_mod
    from services.mesh import mesh_hashchain as mesh_hashchain_mod, mesh_rns as mesh_rns_mod

    bridge = RNSBridge()
    ingested: list[tuple[str, list[dict]]] = []
    settings = SimpleNamespace(MESH_RNS_DANDELION_HOPS=3)

    monkeypatch.setattr(config_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(mesh_rns_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(bridge, "_seen", lambda _message_id: False)
    monkeypatch.setattr(mesh_hashchain_mod, "resolve_gate_wire_ref", lambda gate_ref, event: "finance")
    monkeypatch.setattr(
        mesh_hashchain_mod.gate_store,
        "ingest_peer_events",
        lambda gate_id, events: ingested.append((gate_id, events)) or {"accepted": 1, "duplicates": 0, "rejected": 0},
    )

    packet = mesh_rns_mod.RNSMessage(
        msg_type="gate_event",
        body={
            "event": {
                "event_type": "gate_message",
                "timestamp": 1710000000,
                "event_id": "gate-evt-inbound",
                "node_id": "!gate-persona-1",
                "sequence": 9,
                "signature": "deadbeef",
                "public_key": "pubkey-1",
                "public_key_algo": "Ed25519",
                "protocol_version": "infonet/2",
                "payload": {
                    "ciphertext": "abc123",
                    "format": "mls1",
                    "nonce": "nonce-7",
                    "sender_ref": "sender-ref-7",
                    "epoch": 4,
                    "gate_ref": "opaque-ref-1",
                },
            }
        },
        meta={"message_id": "gate-inbound-1", "dandelion": {"phase": "diffuse"}},
    ).encode()

    bridge._on_packet(packet)

    assert len(ingested) == 1
    gate_id, events = ingested[0]
    assert gate_id == "finance"
    assert len(events) == 1
    event = events[0]
    assert event["event_id"] == "gate-evt-inbound"
    assert event["node_id"] == "!gate-persona-1"
    assert event["sequence"] == 9
    assert event["signature"] == "deadbeef"
    assert event["public_key"] == "pubkey-1"
    assert event["public_key_algo"] == "Ed25519"
    assert event["protocol_version"] == "infonet/2"
    assert event["payload"]["gate"] == "finance"
    assert event["payload"]["gate_ref"] == "opaque-ref-1"
    assert event["payload"]["ciphertext"] == "abc123"
    assert event["payload"]["nonce"] == "nonce-7"
    assert event["payload"]["sender_ref"] == "sender-ref-7"
    assert event["payload"]["epoch"] == 4


def test_rns_inbound_gate_event_blind_forwards_when_gate_cannot_be_resolved(monkeypatch) -> None:
    from services import config as config_mod
    from services.mesh import mesh_hashchain as mesh_hashchain_mod, mesh_rns as mesh_rns_mod

    bridge = RNSBridge()
    forwarded: list[tuple[str, dict]] = []
    ingested: list[tuple[str, list[dict]]] = []
    settings = SimpleNamespace(MESH_RNS_DANDELION_HOPS=3)

    monkeypatch.setattr(config_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(mesh_rns_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(bridge, "_seen", lambda _message_id: False)
    monkeypatch.setattr(bridge, "_pick_stem_peer", lambda: "peer-stem")
    monkeypatch.setattr(
        bridge,
        "_send_to_peer",
        lambda peer, payload: forwarded.append((peer, json.loads(payload.decode("utf-8")))),
    )
    monkeypatch.setattr(mesh_hashchain_mod, "resolve_gate_wire_ref", lambda gate_ref, event: "")
    monkeypatch.setattr(
        mesh_hashchain_mod.gate_store,
        "ingest_peer_events",
        lambda gate_id, events: ingested.append((gate_id, events)) or {"accepted": 1, "duplicates": 0, "rejected": 0},
    )

    original_event = {
        "event_type": "gate_message",
        "timestamp": 1710000000,
        "event_id": "gate-evt-blind",
        "node_id": "!gate-persona-1",
        "sequence": 9,
        "signature": "deadbeef",
        "public_key": "pubkey-1",
        "public_key_algo": "Ed25519",
        "protocol_version": "infonet/2",
        "payload": {
            "ciphertext": "abc123",
            "format": "mls1",
            "nonce": "nonce-7",
            "sender_ref": "sender-ref-7",
            "epoch": 4,
            "gate_ref": "opaque-ref-1",
        },
    }
    packet = mesh_rns_mod.RNSMessage(
        msg_type="gate_event",
        body={"event": original_event},
        meta={"message_id": "gate-inbound-2", "dandelion": {"phase": "stem", "hops": 0, "max_hops": 2}},
    ).encode()

    bridge._on_packet(packet)

    assert ingested == []
    assert len(forwarded) == 1
    peer, forwarded_msg = forwarded[0]
    assert peer == "peer-stem"
    assert forwarded_msg["type"] == "gate_event"
    assert forwarded_msg["meta"] == {
        "message_id": "gate-inbound-2",
        "dandelion": {"phase": "stem", "hops": 1, "max_hops": 2},
    }
    assert forwarded_msg["body"]["event"] == original_event
