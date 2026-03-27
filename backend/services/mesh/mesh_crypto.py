"""Cryptographic helpers for Mesh protocol verification."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any
from urllib.parse import urlparse

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from cryptography.exceptions import InvalidSignature

from services.mesh.mesh_protocol import PROTOCOL_VERSION, NETWORK_ID, normalize_payload

NODE_ID_PREFIX = "!sb_"
NODE_ID_HEX_LEN = 16


def canonical_json(obj: dict[str, Any]) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def normalize_peer_url(peer_url: str) -> str:
    raw = str(peer_url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    scheme = str(parsed.scheme or "").strip().lower()
    hostname = str(parsed.hostname or "").strip().lower()
    if not scheme or not hostname:
        return ""
    port = parsed.port
    default_port = 443 if scheme == "https" else 80 if scheme == "http" else None
    netloc = hostname
    if port and port != default_port:
        netloc = f"{hostname}:{port}"
    path = str(parsed.path or "").rstrip("/")
    return f"{scheme}://{netloc}{path}"


def _derive_peer_key(shared_secret: str, peer_url: str) -> bytes:
    normalized_url = normalize_peer_url(peer_url)
    if not shared_secret or not normalized_url:
        return b""
    # HKDF-Extract per RFC 5869 §2.2: PRK = HMAC-Hash(salt, IKM).
    # Python's hmac.new(key=salt, msg=IKM) maps directly to that definition.
    prk = hmac.new(
        b"sb-peer-auth-v1",
        shared_secret.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return hmac.new(
        prk,
        normalized_url.encode("utf-8") + b"\x01",
        hashlib.sha256,
    ).digest()


def _node_digest(public_key_b64: str) -> str:
    raw = base64.b64decode(public_key_b64)
    return hashlib.sha256(raw).hexdigest()


def derive_node_id(public_key_b64: str, *, legacy: bool = False) -> str:
    digest = _node_digest(public_key_b64)
    length = NODE_ID_HEX_LEN
    return NODE_ID_PREFIX + digest[:length]


def derive_node_id_candidates(public_key_b64: str) -> tuple[str, ...]:
    current = derive_node_id(public_key_b64, legacy=False)
    return (current,)


def build_signature_payload(
    *,
    event_type: str,
    node_id: str,
    sequence: int,
    payload: dict[str, Any],
) -> str:
    normalized = normalize_payload(event_type, payload)
    # gate_envelope and reply_to ride alongside the signed payload — they are
    # added after the message is signed so must be excluded from verification.
    if event_type == "gate_message":
        for _unsig in ("gate_envelope", "reply_to"):
            normalized.pop(_unsig, None)
    payload_json = canonical_json(normalized)
    return "|".join(
        [PROTOCOL_VERSION, NETWORK_ID, event_type, node_id, str(sequence), payload_json]
    )


def parse_public_key_algo(value: str) -> str:
    val = (value or "").strip().upper()
    if val in ("ED25519", "EDDSA"):
        return "Ed25519"
    if val in ("ECDSA", "ECDSA_P256", "P-256", "P256"):
        return "ECDSA_P256"
    return ""


def verify_signature(
    *,
    public_key_b64: str,
    public_key_algo: str,
    signature_hex: str,
    payload: str,
) -> bool:
    try:
        sig_bytes = bytes.fromhex(signature_hex)
    except Exception:
        return False

    try:
        pub_raw = base64.b64decode(public_key_b64)
    except Exception:
        return False

    algo = parse_public_key_algo(public_key_algo)
    data = payload.encode("utf-8")

    try:
        if algo == "Ed25519":
            pub = ed25519.Ed25519PublicKey.from_public_bytes(pub_raw)
            pub.verify(sig_bytes, data)
            return True
        if algo == "ECDSA_P256":
            pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), pub_raw)
            pub.verify(sig_bytes, data, ec.ECDSA(hashes.SHA256()))
            return True
    except InvalidSignature:
        return False
    except Exception:
        return False

    return False


def verify_node_binding(node_id: str, public_key_b64: str) -> bool:
    try:
        return str(node_id or "") in derive_node_id_candidates(public_key_b64)
    except Exception:
        return False
