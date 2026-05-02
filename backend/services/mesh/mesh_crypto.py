"""Cryptographic helpers for Mesh protocol verification."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from typing import Any
from urllib.parse import urlparse

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from cryptography.exceptions import InvalidSignature

from services.mesh.mesh_compatibility import (
    legacy_node_id_compat_blocked,
    record_legacy_node_id_binding,
    sunset_target_label,
    LEGACY_NODE_ID_BINDING_TARGET,
)
from services.mesh.mesh_protocol import PROTOCOL_VERSION, NETWORK_ID, normalize_payload

NODE_ID_PREFIX = "!sb_"
NODE_ID_HEX_LEN = 32
NODE_ID_COMPAT_HEX_LEN = 16
logger = logging.getLogger(__name__)
_WARNED_LEGACY_NODE_BINDINGS: set[str] = set()


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


def _derive_node_id_from_digest(digest: str, length: int) -> str:
    return NODE_ID_PREFIX + digest[:length]


def derive_node_id(public_key_b64: str, *, legacy: bool = False) -> str:
    digest = _node_digest(public_key_b64)
    length = NODE_ID_COMPAT_HEX_LEN if legacy else NODE_ID_HEX_LEN
    return _derive_node_id_from_digest(digest, length)


def derive_node_id_candidates(public_key_b64: str) -> tuple[str, ...]:
    digest = _node_digest(public_key_b64)
    candidates: list[str] = []
    for length in (NODE_ID_HEX_LEN, NODE_ID_COMPAT_HEX_LEN):
        candidate = _derive_node_id_from_digest(digest, length)
        if candidate not in candidates:
            candidates.append(candidate)
    return tuple(candidates)


def _warn_legacy_node_binding(node_id: str, current_node_id: str) -> None:
    legacy_node_id = str(node_id or "").strip().lower()
    if not legacy_node_id or legacy_node_id in _WARNED_LEGACY_NODE_BINDINGS:
        return
    _WARNED_LEGACY_NODE_BINDINGS.add(legacy_node_id)
    logger.warning(
        "mesh legacy node-id compatibility match used for %s; rotate peers to current 32-hex id %s before removal in %s",
        legacy_node_id,
        str(current_node_id or "").strip().lower(),
        sunset_target_label(LEGACY_NODE_ID_BINDING_TARGET),
    )


def build_signature_payload(
    *,
    event_type: str,
    node_id: str,
    sequence: int,
    payload: dict[str, Any],
) -> str:
    normalized = normalize_payload(event_type, payload)
    # gate_envelope rides alongside the signed payload. envelope_hash binds it,
    # but the envelope itself is never part of the signature payload.
    if event_type == "gate_message":
        normalized.pop("gate_envelope", None)
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
        raw_node_id = str(node_id or "").strip()
        current_id, *compat_ids = derive_node_id_candidates(public_key_b64)
        if raw_node_id == current_id:
            return True
        if raw_node_id in compat_ids:
            blocked = legacy_node_id_compat_blocked()
            record_legacy_node_id_binding(raw_node_id, current_id, blocked=blocked)
            _warn_legacy_node_binding(raw_node_id, current_id)
            return not blocked
        return False
    except Exception:
        return False
