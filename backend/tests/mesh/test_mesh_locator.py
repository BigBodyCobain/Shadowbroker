import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from services.mesh import mesh_crypto, mesh_hashchain, mesh_protocol


def _signed_event_fields(event_type: str, payload: dict, sequence: int, private_key=None):
    priv = private_key or ed25519.Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    public_key = base64.b64encode(pub).decode("utf-8")
    node_id = mesh_crypto.derive_node_id(public_key)
    normalized = mesh_protocol.normalize_payload(event_type, payload)
    sig_payload = mesh_crypto.build_signature_payload(
        event_type=event_type,
        node_id=node_id,
        sequence=sequence,
        payload=normalized,
    )
    signature = priv.sign(sig_payload.encode("utf-8")).hex()
    return {
        "node_id": node_id,
        "payload": normalized,
        "signature": signature,
        "public_key": public_key,
        "public_key_algo": "Ed25519",
        "protocol_version": mesh_protocol.PROTOCOL_VERSION,
        "private_key": priv,
    }


def test_locator_sync(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mesh_hashchain, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_hashchain, "CHAIN_FILE", tmp_path / "infonet.json")

    inf = mesh_hashchain.Infonet()
    evt1_fields = _signed_event_fields(
        "message",
        {"message": "hello", "destination": "broadcast"},
        1,
    )
    evt1 = inf.append(
        event_type="message",
        node_id=evt1_fields["node_id"],
        payload=evt1_fields["payload"],
        signature=evt1_fields["signature"],
        sequence=1,
        public_key=evt1_fields["public_key"],
        public_key_algo=evt1_fields["public_key_algo"],
        protocol_version=evt1_fields["protocol_version"],
    )
    evt2_fields = _signed_event_fields(
        "message",
        {"message": "world", "destination": "broadcast"},
        2,
        private_key=evt1_fields["private_key"],
    )
    evt2 = inf.append(
        event_type="message",
        node_id=evt1_fields["node_id"],
        payload=evt2_fields["payload"],
        signature=evt2_fields["signature"],
        sequence=2,
        public_key=evt1_fields["public_key"],
        public_key_algo=evt1_fields["public_key_algo"],
        protocol_version=evt1_fields["protocol_version"],
    )

    locator = inf.get_locator()
    assert locator[0] == evt2["event_id"]

    matched, _start, events = inf.get_events_after_locator([evt1["event_id"]], limit=10)
    assert matched == evt1["event_id"]
    assert len(events) == 1
    assert events[0]["event_id"] == evt2["event_id"]
