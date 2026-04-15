import base64

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from services.mesh.mesh_crypto import build_signature_payload, verify_signature


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
