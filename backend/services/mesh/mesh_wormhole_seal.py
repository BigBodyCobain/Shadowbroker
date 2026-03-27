"""Wormhole-owned sender seal helpers."""

from __future__ import annotations

import base64
import json
import os
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

from services.mesh.mesh_crypto import (
    parse_public_key_algo,
    verify_node_binding,
    verify_signature,
)
from services.mesh.mesh_protocol import PROTOCOL_VERSION
from services.mesh.mesh_wormhole_identity import (
    bootstrap_wormhole_identity,
    read_wormhole_identity,
    sign_wormhole_message,
)
from services.wormhole_settings import read_wormhole_settings


def _unb64(data: str | bytes | None) -> bytes:
    if not data:
        return b""
    if isinstance(data, bytes):
        return base64.b64decode(data)
    return base64.b64decode(data.encode("ascii"))


def _derive_aes_key(my_private_b64: str, peer_public_b64: str) -> bytes:
    priv = x25519.X25519PrivateKey.from_private_bytes(_unb64(my_private_b64))
    pub = x25519.X25519PublicKey.from_public_bytes(_unb64(peer_public_b64))
    secret = priv.exchange(pub)
    # For compatibility with the browser path, use the raw 32-byte X25519 secret directly
    # as the AES-256-GCM key material.
    return secret


def _seal_salt(recipient_id: str, msg_id: str, extra: str = "") -> bytes:
    material = f"SB-SEAL-SALT|{recipient_id}|{msg_id}|{PROTOCOL_VERSION}|{extra}".encode("utf-8")
    digest = hashes.Hash(hashes.SHA256())
    digest.update(material)
    return digest.finalize()


def _derive_seal_key_v2(my_private_b64: str, peer_public_b64: str, recipient_id: str, msg_id: str) -> bytes:
    priv = x25519.X25519PrivateKey.from_private_bytes(_unb64(my_private_b64))
    pub = x25519.X25519PublicKey.from_public_bytes(_unb64(peer_public_b64))
    secret = priv.exchange(pub)
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_seal_salt(recipient_id, msg_id),
        info=b"SB-SENDER-SEAL-V2",
    ).derive(secret)


def _x25519_pair() -> tuple[str, str]:
    priv = x25519.X25519PrivateKey.generate()
    priv_raw = priv.private_bytes(
        encoding=Encoding.Raw,
        format=PrivateFormat.Raw,
        encryption_algorithm=NoEncryption(),
    )
    pub_raw = priv.public_key().public_bytes(
        encoding=Encoding.Raw,
        format=PublicFormat.Raw,
    )
    return _b64(priv_raw), _b64(pub_raw)


def _derive_seal_key_v3(
    my_private_b64: str,
    peer_public_b64: str,
    recipient_id: str,
    msg_id: str,
    ephemeral_pub_b64: str,
) -> bytes:
    priv = x25519.X25519PrivateKey.from_private_bytes(_unb64(my_private_b64))
    pub = x25519.X25519PublicKey.from_public_bytes(_unb64(peer_public_b64))
    secret = priv.exchange(pub)
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_seal_salt(recipient_id, msg_id, ephemeral_pub_b64),
        info=b"SB-SENDER-SEAL-V3",
    ).derive(secret)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _seal_payload_version(sender_seal: str) -> tuple[str, str, str]:
    value = str(sender_seal or "").strip()
    if value.startswith("v3:"):
        _, ephemeral_pub, encoded = value.split(":", 2)
        return "v3", ephemeral_pub, encoded
    if value.startswith("v2:"):
        return "v2", "", value[3:]
    return "legacy", "", value


def _legacy_seal_allowed() -> bool:
    try:
        settings = read_wormhole_settings()
        if bool(settings.get("enabled")) or bool(settings.get("anonymous_mode")):
            return False
    except Exception:
        pass
    return True


def build_sender_seal(
    *,
    recipient_id: str,
    recipient_dh_pub: str,
    msg_id: str,
    timestamp: int,
) -> dict[str, Any]:
    recipient_id = str(recipient_id or "").strip()
    recipient_dh_pub = str(recipient_dh_pub or "").strip()
    msg_id = str(msg_id or "").strip()
    timestamp = int(timestamp or 0)
    if not recipient_id or not recipient_dh_pub or not msg_id or timestamp <= 0:
        return {"ok": False, "detail": "recipient_id, recipient_dh_pub, msg_id, and timestamp required"}

    identity = read_wormhole_identity()
    if not identity.get("bootstrapped"):
        bootstrap_wormhole_identity()
        identity = read_wormhole_identity()
    my_private = str(identity.get("dh_private_key", "") or "")
    if not my_private:
        return {"ok": False, "detail": "Missing Wormhole DH private key"}

    try:
        ephemeral_private, ephemeral_public = _x25519_pair()
        signed = sign_wormhole_message(
            f"seal|v3|{msg_id}|{timestamp}|{recipient_id}|{ephemeral_public}"
        )
        if not verify_node_binding(
            str(signed.get("node_id", "") or ""),
            str(signed.get("public_key", "") or ""),
        ):
            return {"ok": False, "detail": "Sender seal node binding failed"}
        key = _derive_seal_key_v3(
            ephemeral_private,
            recipient_dh_pub,
            recipient_id,
            msg_id,
            ephemeral_public,
        )
        plaintext = json.dumps(
            {
                "seal_version": "v3",
                "ephemeral_pub_key": ephemeral_public,
                "sender_id": str(signed.get("node_id", "") or ""),
                "public_key": str(signed.get("public_key", "") or ""),
                "public_key_algo": str(signed.get("public_key_algo", "") or ""),
                "msg_id": msg_id,
                "timestamp": timestamp,
                "signature": str(signed.get("signature", "") or ""),
                "protocol_version": str(signed.get("protocol_version", "") or ""),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        iv = _b64(os.urandom(12))
    except Exception as exc:
        return {"ok": False, "detail": str(exc) or "sender_seal_build_failed"}

    iv_bytes = _unb64(iv)
    ciphertext = AESGCM(key).encrypt(iv_bytes, plaintext, None)
    combined = iv_bytes + ciphertext
    return {
        "ok": True,
        "sender_seal": f"v3:{ephemeral_public}:{_b64(combined)}",
        "sender_id": str(signed.get("node_id", "") or ""),
        "public_key": str(signed.get("public_key", "") or ""),
        "public_key_algo": str(signed.get("public_key_algo", "") or ""),
        "protocol_version": str(signed.get("protocol_version", "") or ""),
    }


def open_sender_seal(
    *,
    sender_seal: str,
    candidate_dh_pub: str,
    recipient_id: str,
    expected_msg_id: str,
) -> dict[str, Any]:
    if not sender_seal or not candidate_dh_pub or not recipient_id or not expected_msg_id:
        return {"ok": False, "detail": "Missing sender_seal, candidate_dh_pub, recipient_id, or expected_msg_id"}

    identity = read_wormhole_identity()
    if not identity.get("bootstrapped"):
        bootstrap_wormhole_identity()
        identity = read_wormhole_identity()
    my_private = str(identity.get("dh_private_key", "") or "")
    if not my_private:
        return {"ok": False, "detail": "Missing Wormhole DH private key"}

    try:
        seal_version, ephemeral_pub, encoded = _seal_payload_version(sender_seal)
        if seal_version == "v3":
            key = _derive_seal_key_v3(my_private, ephemeral_pub, recipient_id, expected_msg_id, ephemeral_pub)
        elif seal_version == "v2":
            key = _derive_seal_key_v2(my_private, candidate_dh_pub, recipient_id, expected_msg_id)
        else:
            if not _legacy_seal_allowed():
                return {"ok": False, "detail": "Legacy sender seals are disabled in hardened modes"}
            key = _derive_aes_key(my_private, candidate_dh_pub)
        combined = _unb64(encoded)
        iv = combined[:12]
        ciphertext = combined[12:]
        plaintext = AESGCM(key).decrypt(iv, ciphertext, None).decode("utf-8")
        seal = json.loads(plaintext)
    except Exception as exc:
        return {"ok": False, "detail": str(exc) or "sender_seal_decrypt_failed"}

    sender_id = str(seal.get("sender_id", "") or "")
    public_key = str(seal.get("public_key", "") or "")
    public_key_algo = str(seal.get("public_key_algo", "") or "")
    msg_id = str(seal.get("msg_id", "") or "")
    timestamp = int(seal.get("timestamp", 0) or 0)
    signature = str(seal.get("signature", "") or "")
    if not sender_id or not public_key or not public_key_algo or not msg_id or not signature:
        return {"ok": False, "detail": "Malformed sender seal"}
    if msg_id != expected_msg_id:
        return {"ok": False, "detail": "Sender seal message mismatch"}
    if seal_version == "v3" and str(seal.get("ephemeral_pub_key", "") or "") != ephemeral_pub:
        return {"ok": False, "detail": "Sender seal ephemeral key mismatch"}

    if not verify_node_binding(sender_id, public_key):
        return {"ok": True, "sender_id": sender_id, "seal_verified": False}

    algo = parse_public_key_algo(public_key_algo)
    if not algo:
        return {"ok": True, "sender_id": sender_id, "seal_verified": False}

    if seal_version == "v3":
        message = f"seal|v3|{msg_id}|{timestamp}|{recipient_id}|{ephemeral_pub}"
    else:
        message = f"seal|{msg_id}|{timestamp}|{recipient_id}"
    verified = verify_signature(
        public_key_b64=public_key,
        public_key_algo=algo,
        signature_hex=signature,
        payload=message,
    )
    return {
        "ok": True,
        "sender_id": sender_id,
        "seal_verified": bool(verified),
        "public_key": public_key,
        "public_key_algo": public_key_algo,
        "timestamp": timestamp,
        "msg_id": msg_id,
    }
