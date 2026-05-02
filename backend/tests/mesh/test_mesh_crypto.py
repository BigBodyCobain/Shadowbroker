import base64
import re

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from services.config import get_settings
from services.mesh import mesh_compatibility, mesh_crypto
from services.mesh.mesh_crypto import (
    NODE_ID_COMPAT_HEX_LEN,
    NODE_ID_HEX_LEN,
    build_signature_payload,
    derive_node_id,
    derive_node_id_candidates,
    verify_node_binding,
    verify_signature,
)


def test_ed25519_signature_roundtrip():
    key = ed25519.Ed25519PrivateKey.generate()
    pub_raw = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    public_key_b64 = base64.b64encode(pub_raw).decode("utf-8")

    payload = {"message": "hello", "destination": "broadcast", "channel": "LongFast"}
    sig_payload = build_signature_payload(
        event_type="message",
        node_id="!sb_test",
        sequence=1,
        payload=payload,
    )
    signature = key.sign(sig_payload.encode("utf-8")).hex()

    assert verify_signature(
        public_key_b64=public_key_b64,
        public_key_algo="Ed25519",
        signature_hex=signature,
        payload=sig_payload,
    )


def test_ecdsa_signature_roundtrip():
    key = ec.generate_private_key(ec.SECP256R1())
    pub_raw = key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    public_key_b64 = base64.b64encode(pub_raw).decode("utf-8")

    payload = {"target_id": "!sb_abc12345", "vote": 1, "gate": ""}
    sig_payload = build_signature_payload(
        event_type="vote",
        node_id="!sb_test",
        sequence=5,
        payload=payload,
    )
    signature = key.sign(sig_payload.encode("utf-8"), ec.ECDSA(hashes.SHA256())).hex()

    assert verify_signature(
        public_key_b64=public_key_b64,
        public_key_algo="ECDSA_P256",
        signature_hex=signature,
        payload=sig_payload,
    )


def test_node_id_candidates_prefer_current_and_keep_compat():
    key = ed25519.Ed25519PrivateKey.generate()
    pub_raw = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    public_key_b64 = base64.b64encode(pub_raw).decode("utf-8")

    current = derive_node_id(public_key_b64)
    compat = derive_node_id(public_key_b64, legacy=True)
    candidates = derive_node_id_candidates(public_key_b64)

    assert current == candidates[0]
    assert compat in candidates
    assert re.fullmatch(rf"!sb_[0-9a-f]{{{NODE_ID_HEX_LEN}}}", current)
    assert re.fullmatch(rf"!sb_[0-9a-f]{{{NODE_ID_COMPAT_HEX_LEN}}}", compat)


def test_verify_node_binding_records_telemetry_and_can_be_blocked(tmp_path, monkeypatch):
    key = ed25519.Ed25519PrivateKey.generate()
    pub_raw = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    public_key_b64 = base64.b64encode(pub_raw).decode("utf-8")
    compat = derive_node_id(public_key_b64, legacy=True)

    monkeypatch.setattr(mesh_compatibility, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        mesh_compatibility,
        "COMPATIBILITY_FILE",
        tmp_path / "mesh_compatibility_usage.json",
    )
    monkeypatch.delenv("MESH_ALLOW_LEGACY_NODE_ID_COMPAT_UNTIL", raising=False)
    get_settings.cache_clear()

    try:
        assert verify_node_binding(compat, public_key_b64) is False
        snapshot = mesh_compatibility.compatibility_status_snapshot()
        assert snapshot["sunset"]["legacy_node_id_binding"]["target_version"] == "0.10.0"
        assert snapshot["sunset"]["legacy_node_id_binding"]["target_date"] == "2026-06-01"
        assert snapshot["sunset"]["legacy_node_id_binding"]["status"] == "enforced"
        assert snapshot["sunset"]["legacy_node_id_binding"]["blocked"] is True
        assert snapshot["usage"]["legacy_node_id_binding"]["count"] == 1
        assert snapshot["usage"]["legacy_node_id_binding"]["blocked_count"] == 1
        assert snapshot["usage"]["legacy_node_id_binding"]["recent_targets"][0]["node_id"] == compat
    finally:
        get_settings.cache_clear()


def test_legacy_node_id_override_must_be_dated_and_current(monkeypatch):
    key = ed25519.Ed25519PrivateKey.generate()
    pub_raw = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    public_key_b64 = base64.b64encode(pub_raw).decode("utf-8")
    compat = derive_node_id(public_key_b64, legacy=True)

    monkeypatch.setenv("MESH_BLOCK_LEGACY_NODE_ID_COMPAT", "false")
    monkeypatch.delenv("MESH_ALLOW_LEGACY_NODE_ID_COMPAT_UNTIL", raising=False)
    get_settings.cache_clear()

    try:
        assert verify_node_binding(compat, public_key_b64) is False
        snapshot = mesh_compatibility.compatibility_status_snapshot()
        assert snapshot["sunset"]["legacy_node_id_binding"]["status"] == "enforced"
        assert snapshot["sunset"]["legacy_node_id_binding"]["blocked"] is True
    finally:
        get_settings.cache_clear()
