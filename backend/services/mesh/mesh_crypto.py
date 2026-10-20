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


# ---------------------------------------------------------------------------
# Issue #256 (tg12): per-peer HMAC secrets
# ---------------------------------------------------------------------------
#
# Before this change, ALL peer-push HMACs were derived from a single
# fleet-shared ``MESH_PEER_PUSH_SECRET``. The receiver could prove a
# request was signed by *someone who knows the fleet secret*, but it
# could NOT prove which peer signed it — any peer could compute the
# expected HMAC for any other peer's URL and impersonate that peer.
#
# Fix: an optional ``MESH_PEER_SECRETS`` env var maps specific peer URLs
# to per-peer secrets. When a peer URL is listed there, only that
# per-peer secret is accepted for that URL — the global secret is
# ignored for that peer. Peer A no longer learns peer B's secret, so
# peer A cannot forge a request claiming to be peer B.
#
# Backwards-compatible by design:
#
# - Single-peer installs (``MESH_PEER_SECRETS`` empty) keep using the
#   global secret. Zero behavior change. Zero operator action required.
# - Multi-peer installs that haven't migrated yet keep using the global
#   secret for every peer. Same behavior as before — same exposure.
# - Multi-peer installs that have migrated configure
#   ``MESH_PEER_SECRETS=urlA=secretA,urlB=secretB`` and immediately get
#   per-peer identity. Migration is incremental: peers not yet listed
#   continue using the global secret until both sides of that peering
#   add their entry.

_PEER_SECRETS_CACHE: dict[str, str] = {}
_PEER_SECRETS_CACHE_RAW: str = ""


def _lookup_per_peer_secret(normalized_url: str) -> str:
    """Return the per-peer secret for ``normalized_url`` from MESH_PEER_SECRETS.

    Returns "" if no per-peer entry is configured for that URL. The parser
    is forgiving:

    - Whitespace around items, URLs, and secrets is stripped.
    - Items without ``=`` or with empty URL/secret halves are skipped.
    - The URL half is normalized via ``normalize_peer_url`` so config
      authors don't have to match scheme/port/path quirks exactly.

    The cache is invalidated whenever the env var's raw value changes,
    which keeps tests' ``monkeypatch.setenv`` calls effective without
    forcing a process restart.
    """
    import os

    raw = str(os.environ.get("MESH_PEER_SECRETS", "") or "").strip()

    global _PEER_SECRETS_CACHE, _PEER_SECRETS_CACHE_RAW
    if raw != _PEER_SECRETS_CACHE_RAW:
        new_cache: dict[str, str] = {}
        for chunk in raw.split(","):
            chunk = chunk.strip()
            if not chunk or "=" not in chunk:
                continue
            url_part, _, secret_part = chunk.partition("=")
            normalized = normalize_peer_url(url_part.strip())
            secret = secret_part.strip()
            if normalized and secret:
                new_cache[normalized] = secret
        _PEER_SECRETS_CACHE = new_cache
        _PEER_SECRETS_CACHE_RAW = raw

    return _PEER_SECRETS_CACHE.get(normalized_url, "")


def resolve_peer_key_for_url(peer_url: str) -> bytes:
    """Return the HMAC key for ``peer_url``, preferring per-peer secret.

    Issue #256: this is the function every peer-push call site should
    use. It looks up the peer-specific secret first, falling back to the
    fleet-shared ``MESH_PEER_PUSH_SECRET`` only when the URL is NOT
    listed in ``MESH_PEER_SECRETS``.

    Both sender (computing X-Peer-HMAC) and receiver (verifying it) call
    this with the SENDER's URL — they must derive the same key, so
    operators on both ends of a peering need matching MESH_PEER_SECRETS
    entries for that URL to stay in sync.

    Returns empty bytes when no usable secret exists. Callers must treat
    that as fail-closed (skip the push, reject the verification).
    """
    normalized_url = normalize_peer_url(peer_url)
    if not normalized_url:
        return b""

    per_peer_secret = _lookup_per_peer_secret(normalized_url)
    if per_peer_secret:
        return _derive_peer_key(per_peer_secret, normalized_url)

    # No per-peer entry for this URL — fall back to the legacy global
    # secret. This is what preserves zero-hostility for single-peer
    # installs and the migration window for multi-peer installs.
    try:
        from services.config import get_settings

        from services.mesh.mesh_fleet_defaults import effective_peer_push_secret

        global_secret = effective_peer_push_secret()
    except Exception:
        return b""
    if not global_secret:
        return b""
    return _derive_peer_key(global_secret, normalized_url)


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
