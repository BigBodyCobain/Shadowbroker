import base64
import json
import time

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from services.config import get_settings
from services.mesh import mesh_crypto, mesh_dm_relay, mesh_hashchain, mesh_protocol, mesh_secure_storage


def _keypair():
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    public_key = base64.b64encode(public_raw).decode("utf-8")
    node_id = mesh_crypto.derive_node_id(public_key)
    return private_key, public_key, node_id


def _payload(recipient_id: str = "recipient-a", msg_id: str = "dm-1") -> dict:
    return mesh_protocol.normalize_payload(
        "dm_message",
        {
            "recipient_id": recipient_id,
            "delivery_class": "request",
            "recipient_token": "",
            "ciphertext": base64.b64encode(f"cipher-{msg_id}".encode("utf-8")).decode("ascii"),
            "msg_id": msg_id,
            "timestamp": int(time.time()),
            "format": "mls1",
            "transport_lock": "private_strong",
        },
    )


def _signature(private_key, node_id: str, sequence: int, payload: dict) -> str:
    signature_payload = mesh_crypto.build_signature_payload(
        event_type="dm_message",
        node_id=node_id,
        sequence=sequence,
        payload=payload,
    )
    return private_key.sign(signature_payload.encode("utf-8")).hex()


def _fresh_infonet(tmp_path, monkeypatch) -> mesh_hashchain.Infonet:
    monkeypatch.setattr(mesh_hashchain, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_hashchain, "CHAIN_FILE", tmp_path / "infonet.json")
    monkeypatch.setattr(mesh_hashchain, "WAL_FILE", tmp_path / "infonet.wal")
    return mesh_hashchain.Infonet()


def _fresh_relay(tmp_path, monkeypatch) -> mesh_dm_relay.DMRelay:
    monkeypatch.setattr(mesh_dm_relay, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_dm_relay, "RELAY_FILE", tmp_path / "dm_relay.json")
    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    get_settings.cache_clear()
    return mesh_dm_relay.DMRelay()


def test_private_dm_hashchain_spools_two_ciphertexts_per_recipient_from_distinct_senders(tmp_path, monkeypatch):
    inf = _fresh_infonet(tmp_path, monkeypatch)
    senders = [_keypair(), _keypair()]

    for idx, (private_key, public_key, node_id) in enumerate(senders, start=1):
        payload = _payload(msg_id=f"dm-{idx}")
        event = inf.append_private_dm_message(
            node_id=node_id,
            payload=payload,
            signature=_signature(private_key, node_id, 1, payload),
            sequence=1,
            public_key=public_key,
            public_key_algo="Ed25519",
            protocol_version=mesh_protocol.PROTOCOL_VERSION,
            timestamp=float(payload["timestamp"]),
        )
        assert event["event_type"] == "dm_message"

    private_key, public_key, node_id = _keypair()
    third = _payload(msg_id="dm-3")
    try:
        inf.append_private_dm_message(
            node_id=node_id,
            payload=third,
            signature=_signature(private_key, node_id, 1, third),
            sequence=1,
            public_key=public_key,
            public_key_algo="Ed25519",
            protocol_version=mesh_protocol.PROTOCOL_VERSION,
            timestamp=float(third["timestamp"]),
        )
    except ValueError as exc:
        assert "spool full" in str(exc)
    else:
        raise AssertionError("third DM spool event was accepted")

    for _private_key, _public_key, sender_node_id in senders:
        assert inf.sequence_domains[f"{sender_node_id}|dm_message"] == 1
    assert inf.validate_chain(verify_signatures=True)[0] is True


def test_private_dm_hashchain_limits_one_active_spool_per_sender_recipient_pair(tmp_path, monkeypatch):
    inf = _fresh_infonet(tmp_path, monkeypatch)
    private_key, public_key, node_id = _keypair()

    first = _payload(msg_id="dm-1")
    inf.append_private_dm_message(
        node_id=node_id,
        payload=first,
        signature=_signature(private_key, node_id, 1, first),
        sequence=1,
        public_key=public_key,
        public_key_algo="Ed25519",
        protocol_version=mesh_protocol.PROTOCOL_VERSION,
        timestamp=float(first["timestamp"]),
    )

    second = _payload(msg_id="dm-2")
    try:
        inf.append_private_dm_message(
            node_id=node_id,
            payload=second,
            signature=_signature(private_key, node_id, 2, second),
            sequence=2,
            public_key=public_key,
            public_key_algo="Ed25519",
            protocol_version=mesh_protocol.PROTOCOL_VERSION,
            timestamp=float(second["timestamp"]),
        )
    except ValueError as exc:
        assert "sender spool full" in str(exc)
    else:
        raise AssertionError("second DM from same sender to same recipient was accepted")


def test_private_dm_hashchain_rejects_plaintext(tmp_path, monkeypatch):
    inf = _fresh_infonet(tmp_path, monkeypatch)
    private_key, public_key, node_id = _keypair()
    payload = _payload()
    payload["message"] = "plaintext"

    try:
        inf.append_private_dm_message(
            node_id=node_id,
            payload=payload,
            signature=_signature(private_key, node_id, 1, _payload()),
            sequence=1,
            public_key=public_key,
            public_key_algo="Ed25519",
            protocol_version=mesh_protocol.PROTOCOL_VERSION,
        )
    except ValueError as exc:
        assert "plaintext" in str(exc)
    else:
        raise AssertionError("private DM append accepted plaintext")


def test_private_dm_hashchain_rejects_non_sealed_ciphertext_shape(tmp_path, monkeypatch):
    inf = _fresh_infonet(tmp_path, monkeypatch)
    private_key, public_key, node_id = _keypair()
    payload = _payload()
    payload["ciphertext"] = "not sealed plaintext"

    try:
        inf.append_private_dm_message(
            node_id=node_id,
            payload=payload,
            signature=_signature(private_key, node_id, 1, payload),
            sequence=1,
            public_key=public_key,
            public_key_algo="Ed25519",
            protocol_version=mesh_protocol.PROTOCOL_VERSION,
        )
    except ValueError as exc:
        assert "sealed bytes" in str(exc)
    else:
        raise AssertionError("private DM append accepted non-base64 ciphertext")


def test_private_dm_hashchain_accepts_x3dh1_prefixed_ciphertext(tmp_path, monkeypatch):
    inf = _fresh_infonet(tmp_path, monkeypatch)
    private_key, public_key, node_id = _keypair()
    envelope = {
        "h": {"ik_pub": "aGVsbG8=", "ek_pub": "d29ybGQ=", "spk_id": 1, "otk_id": 0},
        "ct": base64.b64encode(b"\x00" * 32).decode("ascii"),
    }
    payload = _payload(msg_id="dm-x3dh-1")
    payload["ciphertext"] = "x3dh1:" + base64.b64encode(
        json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    event = inf.append_private_dm_message(
        node_id=node_id,
        payload=payload,
        signature=_signature(private_key, node_id, 1, payload),
        sequence=1,
        public_key=public_key,
        public_key_algo="Ed25519",
        protocol_version=mesh_protocol.PROTOCOL_VERSION,
        timestamp=float(payload["timestamp"]),
    )
    assert event["event_type"] == "dm_message"
    assert str(event["payload"]["ciphertext"]).startswith("x3dh1:")


def test_hydrate_dm_relay_from_chain_delivers_to_poll_claim(tmp_path, monkeypatch):
    inf = _fresh_infonet(tmp_path / "chain", monkeypatch)
    relay = _fresh_relay(tmp_path / "relay", monkeypatch)
    monkeypatch.setattr(mesh_hashchain, "infonet", inf)
    monkeypatch.setattr(mesh_dm_relay, "dm_relay", relay)

    private_key, public_key, node_id = _keypair()
    payload = _payload(recipient_id="recipient-a", msg_id="dm-chain-1")
    event = inf.append_private_dm_message(
        node_id=node_id,
        payload=payload,
        signature=_signature(private_key, node_id, 1, payload),
        sequence=1,
        public_key=public_key,
        public_key_algo="Ed25519",
        protocol_version=mesh_protocol.PROTOCOL_VERSION,
        timestamp=float(payload["timestamp"]),
    )

    from main import _hydrate_dm_relay_from_chain

    assert _hydrate_dm_relay_from_chain([event]) == 1
    messages, more = relay.collect_claims(
        "recipient-a",
        [{"type": "requests", "token": "recipient-request-token"}],
        limit=8,
    )

    assert more is False
    assert [message["msg_id"] for message in messages] == ["dm-chain-1"]
    assert messages[0]["ciphertext"] == payload["ciphertext"]
