import base64
import json
import pytest

from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

from services.mesh import mesh_hashchain, mesh_crypto, mesh_protocol, mesh_schema


def test_infonet_ingest_accepts_valid_event(tmp_path, monkeypatch):
    monkeypatch.setattr(mesh_hashchain, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_hashchain, "CHAIN_FILE", tmp_path / "infonet.json")

    inf = mesh_hashchain.Infonet()

    priv = ed25519.Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    pub_b64 = base64.b64encode(pub).decode("utf-8")
    node_id = mesh_crypto.derive_node_id(pub_b64)

    payload = mesh_protocol.normalize_payload(
        "message",
        {"message": "hello", "destination": "broadcast", "channel": "LongFast", "priority": "normal", "ephemeral": False},
    )
    sig_payload = mesh_crypto.build_signature_payload(
        event_type="message", node_id=node_id, sequence=1, payload=payload
    )
    signature = priv.sign(sig_payload.encode("utf-8")).hex()

    evt = mesh_hashchain.ChainEvent(
        prev_hash=mesh_hashchain.GENESIS_HASH,
        event_type="message",
        node_id=node_id,
        payload=payload,
        sequence=1,
        signature=signature,
        public_key=pub_b64,
        public_key_algo="Ed25519",
        protocol_version=mesh_protocol.PROTOCOL_VERSION,
        network_id=mesh_protocol.NETWORK_ID,
    )
    result = inf.ingest_events([evt.to_dict()])

    assert result["accepted"] == 1
    assert inf.head_hash == evt.event_id


def test_verify_node_binding_rejects_legacy_and_accepts_current_ids():
    priv = ed25519.Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    pub_b64 = base64.b64encode(pub).decode("utf-8")

    current = mesh_crypto.derive_node_id(pub_b64)
    legacy = f"{mesh_crypto.NODE_ID_PREFIX}{current[len(mesh_crypto.NODE_ID_PREFIX):len(mesh_crypto.NODE_ID_PREFIX) + 8]}"

    assert mesh_crypto.verify_node_binding(current, pub_b64)
    assert not mesh_crypto.verify_node_binding(legacy, pub_b64)


def test_infonet_append_rejects_missing_signature_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(mesh_hashchain, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_hashchain, "CHAIN_FILE", tmp_path / "infonet.json")

    inf = mesh_hashchain.Infonet()
    payload = mesh_protocol.normalize_payload(
        "message",
        {"message": "hello", "destination": "broadcast", "channel": "LongFast", "priority": "normal", "ephemeral": False},
    )

    try:
        inf.append(
            event_type="message",
            node_id="!sb_test",
            payload=payload,
            sequence=1,
        )
        assert False, "Expected missing signature fields to be rejected"
    except ValueError as exc:
        assert "signature" in str(exc).lower()


def test_infonet_load_fails_closed_on_hash_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(mesh_hashchain, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_hashchain, "CHAIN_FILE", tmp_path / "infonet.json")

    priv = ed25519.Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    pub_b64 = base64.b64encode(pub).decode("utf-8")
    node_id = mesh_crypto.derive_node_id(pub_b64)
    payload = mesh_protocol.normalize_payload(
        "message",
        {"message": "hello", "destination": "broadcast", "channel": "LongFast", "priority": "normal", "ephemeral": False},
    )
    sig_payload = mesh_crypto.build_signature_payload(
        event_type="message", node_id=node_id, sequence=1, payload=payload
    )
    signature = priv.sign(sig_payload.encode("utf-8")).hex()
    evt = mesh_hashchain.ChainEvent(
        prev_hash=mesh_hashchain.GENESIS_HASH,
        event_type="message",
        node_id=node_id,
        payload=payload,
        sequence=1,
        signature=signature,
        public_key=pub_b64,
        public_key_algo="Ed25519",
        protocol_version=mesh_protocol.PROTOCOL_VERSION,
        network_id=mesh_protocol.NETWORK_ID,
    ).to_dict()
    evt["event_id"] = "tampered"
    mesh_hashchain.CHAIN_FILE.write_text(
        json.dumps({"events": [evt], "head_hash": "tampered", "node_sequences": {node_id: 1}}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Hash mismatch on event load"):
        mesh_hashchain.Infonet()


def test_validate_gate_message_payload_rejects_plaintext_shape():
    payload = mesh_protocol.normalize_payload(
        "gate_message",
        {"gate": "infonet", "message": "plaintext should fail"},
    )

    valid, reason = mesh_schema.validate_event_payload("gate_message", payload)

    assert valid is False
    assert reason == "epoch must be a positive integer"


def test_gate_store_accepts_encrypted_gate_payload(tmp_path, monkeypatch):
    priv = ed25519.Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    pub_b64 = base64.b64encode(pub).decode("utf-8")
    node_id = mesh_crypto.derive_node_id(pub_b64)

    payload = mesh_protocol.normalize_payload(
        "gate_message",
        {
            "gate": "infonet",
            "epoch": 2,
            "ciphertext": "opaque-ciphertext",
            "nonce": "nonce-2",
            "sender_ref": "persona-ops-1",
            "format": "mls1",
        },
    )
    sig_payload = mesh_crypto.build_signature_payload(
        event_type="gate_message", node_id=node_id, sequence=1, payload=payload
    )
    signature = priv.sign(sig_payload.encode("utf-8")).hex()

    store = mesh_hashchain.GateMessageStore(data_dir=str(tmp_path / "gate_messages"))
    evt = store.append(
        "infonet",
        {
            "event_id": "evt_gate_cipher",
            "event_type": "gate_message",
            "node_id": node_id,
            "payload": payload,
            "timestamp": 1_700_000_000.0,
            "sequence": 1,
            "signature": signature,
            "public_key": pub_b64,
            "public_key_algo": "Ed25519",
            "protocol_version": mesh_protocol.PROTOCOL_VERSION,
        },
    )

    assert evt["payload"]["gate"] == "infonet"
    assert evt["payload"]["ciphertext"] == "opaque-ciphertext"
    assert evt["payload"]["epoch"] == 2
    assert evt["payload"]["nonce"] == "nonce-2"
    assert evt["payload"]["sender_ref"] == "persona-ops-1"


def test_gate_store_rejects_replayed_ciphertext_across_append_and_peer_ingest(tmp_path):
    store = mesh_hashchain.GateMessageStore(data_dir=str(tmp_path / "gate_messages"))
    gate_id = "infonet"
    first = store.append(
        gate_id,
        {
            "event_id": "a" * 64,
            "event_type": "gate_message",
            "payload": {
                "gate": gate_id,
                "ciphertext": "opaque-ciphertext",
                "format": "mls1",
            },
            "timestamp": float(int(mesh_hashchain.time.time() / 60) * 60),
        },
    )

    replayed = store.append(
        gate_id,
        {
            "event_id": "b" * 64,
            "event_type": "gate_message",
            "payload": {
                "gate": gate_id,
                "ciphertext": "opaque-ciphertext",
                "format": "mls1",
            },
            "timestamp": float(int(mesh_hashchain.time.time() / 60) * 60) + 60.0,
        },
    )
    peer_result = store.ingest_peer_events(
        gate_id,
        [
            {
                "event_type": "gate_message",
                "timestamp": mesh_hashchain.time.time(),
                "payload": {
                    "gate": gate_id,
                    "ciphertext": "opaque-ciphertext",
                    "format": "mls1",
                },
            }
        ],
    )

    assert replayed is first
    assert peer_result == {"accepted": 0, "duplicates": 1, "rejected": 0}
    assert len(store.get_messages(gate_id, limit=10)) == 1


def test_gate_store_prunes_stale_replay_fingerprints(tmp_path):
    store = mesh_hashchain.GateMessageStore(data_dir=str(tmp_path / "gate_messages"))
    old_ts = mesh_hashchain.time.time() - mesh_hashchain.GATE_REPLAY_WINDOW_S - 10

    store.append(
        "infonet",
        {
            "event_id": "c" * 64,
            "event_type": "gate_message",
            "payload": {
                "gate": "infonet",
                "ciphertext": "old-cipher",
                "format": "mls1",
            },
            "timestamp": old_ts,
        },
    )

    assert len(store._replay_index) == 1
    removed = store._prune_replay_index(now=mesh_hashchain.time.time())

    assert removed == 1
    assert store._replay_index == {}
