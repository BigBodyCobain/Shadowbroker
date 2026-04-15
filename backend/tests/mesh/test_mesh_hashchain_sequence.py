import pytest
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


def test_infonet_sequence_enforced(tmp_path, monkeypatch):
    monkeypatch.setattr(mesh_hashchain, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_hashchain, "CHAIN_FILE", tmp_path / "infonet.json")

    inf = mesh_hashchain.Infonet()
    evt1_fields = _signed_event_fields(
        "message",
        {"message": "hello", "destination": "broadcast"},
        1,
    )

    evt = inf.append(
        event_type="message",
        node_id=evt1_fields["node_id"],
        payload=evt1_fields["payload"],
        signature=evt1_fields["signature"],
        sequence=1,
        public_key=evt1_fields["public_key"],
        public_key_algo=evt1_fields["public_key_algo"],
        protocol_version=evt1_fields["protocol_version"],
    )
    assert evt["payload"]["channel"] == "LongFast"
    assert evt["payload"]["priority"] == "normal"

    replay_fields = _signed_event_fields(
        "message",
        {"message": "replay", "destination": "broadcast", "channel": "LongFast"},
        1,
    )
    with pytest.raises(ValueError):
        inf.append(
            event_type="message",
            node_id=evt1_fields["node_id"],
            payload=replay_fields["payload"],
            signature=replay_fields["signature"],
            sequence=1,
            public_key=evt1_fields["public_key"],
            public_key_algo=evt1_fields["public_key_algo"],
            protocol_version=evt1_fields["protocol_version"],
        )

    out_of_order_fields = _signed_event_fields(
        "message",
        {"message": "out-of-order", "destination": "broadcast", "channel": "LongFast"},
        1,
    )
    with pytest.raises(ValueError):
        inf.append(
            event_type="message",
            node_id=evt1_fields["node_id"],
            payload=out_of_order_fields["payload"],
            signature=out_of_order_fields["signature"],
            sequence=1,
            public_key=evt1_fields["public_key"],
            public_key_algo=evt1_fields["public_key_algo"],
            protocol_version=evt1_fields["protocol_version"],
        )

    evt2_fields = _signed_event_fields(
        "message",
        {"message": "next", "destination": "broadcast", "channel": "LongFast"},
        2,
        private_key=evt1_fields["private_key"],
    )
    inf.append(
        event_type="message",
        node_id=evt1_fields["node_id"],
        payload=evt2_fields["payload"],
        signature=evt2_fields["signature"],
        sequence=2,
        public_key=evt1_fields["public_key"],
        public_key_algo=evt1_fields["public_key_algo"],
        protocol_version=evt1_fields["protocol_version"],
    )

    with pytest.raises(ValueError):
        inf.append(
            event_type="not_valid",
            node_id=evt1_fields["node_id"],
            payload={"message": "nope", "destination": "broadcast"},
            signature=evt1_fields["signature"],
            sequence=1,
            public_key=evt1_fields["public_key"],
            public_key_algo=evt1_fields["public_key_algo"],
            protocol_version=evt1_fields["protocol_version"],
        )
