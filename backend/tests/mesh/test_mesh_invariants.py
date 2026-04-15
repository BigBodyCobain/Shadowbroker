import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from services.mesh import mesh_crypto, mesh_hashchain, mesh_protocol


def _signed_event_fields(
    event_type: str,
    payload: dict,
    sequence: int,
    *,
    private_key: ed25519.Ed25519PrivateKey | None = None,
):
    priv = private_key or ed25519.Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    pub_b64 = base64.b64encode(pub).decode("utf-8")
    node_id = mesh_crypto.derive_node_id(pub_b64)
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
        "public_key": pub_b64,
        "public_key_algo": "Ed25519",
        "protocol_version": mesh_protocol.PROTOCOL_VERSION,
    }


def test_chain_linkage_and_head(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mesh_hashchain, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_hashchain, "CHAIN_FILE", tmp_path / "infonet.json")

    inf = mesh_hashchain.Infonet()
    evt1_fields = _signed_event_fields(
        "message",
        {"message": "one", "destination": "broadcast", "channel": "LongFast", "priority": "normal", "ephemeral": False},
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
        {"message": "two", "destination": "broadcast", "channel": "LongFast", "priority": "normal", "ephemeral": False},
        2,
    )
    evt2 = inf.append(
        event_type="message",
        node_id=evt2_fields["node_id"],
        payload=evt2_fields["payload"],
        signature=evt2_fields["signature"],
        sequence=2,
        public_key=evt2_fields["public_key"],
        public_key_algo=evt2_fields["public_key_algo"],
        protocol_version=evt2_fields["protocol_version"],
    )

    assert evt1["prev_hash"] == mesh_hashchain.GENESIS_HASH
    assert evt2["prev_hash"] == evt1["event_id"]
    assert inf.head_hash == evt2["event_id"]


def test_ingest_rejects_non_normalized_payload(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mesh_hashchain, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_hashchain, "CHAIN_FILE", tmp_path / "infonet.json")

    inf = mesh_hashchain.Infonet()
    evt = mesh_hashchain.ChainEvent(
        prev_hash=mesh_hashchain.GENESIS_HASH,
        event_type="message",
        node_id="!sb_test",
        payload={"message": "hi", "destination": "broadcast"},
        sequence=1,
        signature="deadbeef",
        public_key="pub",
        public_key_algo="Ed25519",
        protocol_version=mesh_protocol.PROTOCOL_VERSION,
        network_id=mesh_protocol.NETWORK_ID,
    )
    result = inf.ingest_events([evt.to_dict()])

    assert result["accepted"] == 0
    assert result["rejected"]
    assert "normalized" in result["rejected"][0]["reason"].lower()


def test_revoked_key_rejects_future_events(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mesh_hashchain, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_hashchain, "CHAIN_FILE", tmp_path / "infonet.json")

    inf = mesh_hashchain.Infonet()
    now = int(mesh_hashchain.time.time())
    revoke_priv = ed25519.Ed25519PrivateKey.generate()
    revoked_payload = {
        "revoked_public_key": "",
        "revoked_public_key_algo": "Ed25519",
        "revoked_at": now - 10,
        "grace_until": now - 10,
        "reason": "compromised",
    }
    revoke_fields = _signed_event_fields(
        "key_revoke",
        revoked_payload,
        1,
        private_key=revoke_priv,
    )
    revoked_payload["revoked_public_key"] = revoke_fields["public_key"]
    revoke_fields = _signed_event_fields(
        "key_revoke",
        revoked_payload,
        1,
        private_key=revoke_priv,
    )
    inf.append(
        event_type="key_revoke",
        node_id=revoke_fields["node_id"],
        payload=revoked_payload,
        signature=revoke_fields["signature"],
        sequence=1,
        public_key=revoke_fields["public_key"],
        public_key_algo=revoke_fields["public_key_algo"],
        protocol_version=revoke_fields["protocol_version"],
    )

    msg_fields = _signed_event_fields(
        "message",
        {"message": "blocked", "destination": "broadcast", "channel": "LongFast", "priority": "normal", "ephemeral": False},
        2,
        private_key=revoke_priv,
    )
    try:
        inf.append(
            event_type="message",
            node_id=revoke_fields["node_id"],
            payload=msg_fields["payload"],
            signature=msg_fields["signature"],
            sequence=2,
            public_key=revoke_fields["public_key"],
            public_key_algo=revoke_fields["public_key_algo"],
            protocol_version=revoke_fields["protocol_version"],
        )
        assert False, "Expected revocation to block new events"
    except ValueError as exc:
        assert "revoked" in str(exc).lower()
