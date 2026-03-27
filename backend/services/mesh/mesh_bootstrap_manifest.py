from __future__ import annotations

import base64
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from services.config import get_settings
from services.mesh.mesh_crypto import canonical_json, normalize_peer_url

BACKEND_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BACKEND_DIR / "data"
DEFAULT_BOOTSTRAP_MANIFEST_PATH = DATA_DIR / "bootstrap_peers.json"
BOOTSTRAP_MANIFEST_VERSION = 1
ALLOWED_BOOTSTRAP_TRANSPORTS = {"clearnet", "onion"}
ALLOWED_BOOTSTRAP_ROLES = {"participant", "relay", "seed"}


class BootstrapManifestError(ValueError):
    pass


@dataclass(frozen=True)
class BootstrapPeer:
    peer_url: str
    transport: str
    role: str
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BootstrapManifest:
    version: int
    issued_at: int
    valid_until: int
    signer_id: str
    peers: tuple[BootstrapPeer, ...]
    signature: str

    def payload_dict(self) -> dict[str, Any]:
        return {
            "version": int(self.version),
            "issued_at": int(self.issued_at),
            "valid_until": int(self.valid_until),
            "signer_id": str(self.signer_id or ""),
            "peers": [peer.to_dict() for peer in self.peers],
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.payload_dict()
        payload["signature"] = str(self.signature or "")
        return payload


def _resolve_manifest_path(raw_path: str) -> Path:
    raw = str(raw_path or "").strip()
    if not raw:
        return DEFAULT_BOOTSTRAP_MANIFEST_PATH
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate
    return BACKEND_DIR / candidate


def _canonical_manifest_payload(payload: dict[str, Any]) -> str:
    return canonical_json(payload)


def _load_signer_private_key(private_key_b64: str) -> ed25519.Ed25519PrivateKey:
    try:
        signer_private_key = base64.b64decode(
            str(private_key_b64 or "").encode("utf-8"),
            validate=True,
        )
        return ed25519.Ed25519PrivateKey.from_private_bytes(signer_private_key)
    except Exception as exc:
        raise BootstrapManifestError("bootstrap signer private key must be raw Ed25519 base64") from exc


def bootstrap_signer_public_key_b64(private_key_b64: str) -> str:
    signer = _load_signer_private_key(private_key_b64)
    public_key = signer.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    return base64.b64encode(public_key).decode("utf-8")


def generate_bootstrap_signer() -> dict[str, str]:
    signer = ed25519.Ed25519PrivateKey.generate()
    private_key = signer.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    public_key = signer.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    return {
        "private_key_b64": base64.b64encode(private_key).decode("utf-8"),
        "public_key_b64": base64.b64encode(public_key).decode("utf-8"),
    }


def _verify_manifest_signature(
    payload: dict[str, Any],
    *,
    signature_b64: str,
    signer_public_key_b64: str,
) -> None:
    try:
        signature = base64.b64decode(str(signature_b64 or "").encode("utf-8"), validate=True)
    except Exception as exc:
        raise BootstrapManifestError("bootstrap manifest signature must be base64") from exc

    try:
        signer_public_key = base64.b64decode(
            str(signer_public_key_b64 or "").encode("utf-8"),
            validate=True,
        )
        verifier = ed25519.Ed25519PublicKey.from_public_bytes(signer_public_key)
    except Exception as exc:
        raise BootstrapManifestError("bootstrap signer public key must be raw Ed25519 base64") from exc

    serialized = _canonical_manifest_payload(payload).encode("utf-8")
    try:
        verifier.verify(signature, serialized)
    except InvalidSignature as exc:
        raise BootstrapManifestError("bootstrap manifest signature invalid") from exc


def _validate_bootstrap_peer(peer_data: dict[str, Any]) -> BootstrapPeer:
    peer_url = str(peer_data.get("peer_url", "") or "").strip()
    transport = str(peer_data.get("transport", "") or "").strip().lower()
    role = str(peer_data.get("role", "") or "").strip().lower()
    label = str(peer_data.get("label", "") or "").strip()

    if transport not in ALLOWED_BOOTSTRAP_TRANSPORTS:
        raise BootstrapManifestError(f"unsupported bootstrap transport: {transport or 'missing'}")
    if role not in ALLOWED_BOOTSTRAP_ROLES:
        raise BootstrapManifestError(f"unsupported bootstrap role: {role or 'missing'}")

    normalized = normalize_peer_url(peer_url)
    if not normalized or normalized != peer_url:
        raise BootstrapManifestError("bootstrap peer_url must be normalized")

    parsed = urlparse(normalized)
    hostname = str(parsed.hostname or "").strip().lower()
    if transport == "clearnet":
        if parsed.scheme != "https" or hostname.endswith(".onion"):
            raise BootstrapManifestError("clearnet bootstrap peers must use https://")
    elif transport == "onion":
        if parsed.scheme != "http" or not hostname.endswith(".onion"):
            raise BootstrapManifestError("onion bootstrap peers must use http://*.onion")

    return BootstrapPeer(
        peer_url=normalized,
        transport=transport,
        role=role,
        label=label,
    )


def _validate_bootstrap_manifest_payload(
    payload: dict[str, Any],
    *,
    now: float | None = None,
) -> BootstrapManifest:
    version = int(payload.get("version", 0) or 0)
    issued_at = int(payload.get("issued_at", 0) or 0)
    valid_until = int(payload.get("valid_until", 0) or 0)
    signer_id = str(payload.get("signer_id", "") or "").strip()
    peers_raw = payload.get("peers", [])
    current_time = int(now if now is not None else time.time())

    if version != BOOTSTRAP_MANIFEST_VERSION:
        raise BootstrapManifestError(f"unsupported bootstrap manifest version: {version}")
    if not signer_id:
        raise BootstrapManifestError("bootstrap manifest signer_id is required")
    if issued_at <= 0 or valid_until <= 0 or valid_until <= issued_at:
        raise BootstrapManifestError("bootstrap manifest validity window is invalid")
    if current_time > valid_until:
        raise BootstrapManifestError("bootstrap manifest expired")
    if not isinstance(peers_raw, list):
        raise BootstrapManifestError("bootstrap manifest peers must be a list")

    peers: list[BootstrapPeer] = []
    seen: set[tuple[str, str]] = set()
    for entry in peers_raw:
        if not isinstance(entry, dict):
            raise BootstrapManifestError("bootstrap manifest peers must be objects")
        peer = _validate_bootstrap_peer(entry)
        key = (peer.transport, peer.peer_url)
        if key in seen:
            raise BootstrapManifestError("bootstrap manifest peers must be unique")
        seen.add(key)
        peers.append(peer)

    if not peers:
        raise BootstrapManifestError("bootstrap manifest must contain at least one peer")

    return BootstrapManifest(
        version=version,
        issued_at=issued_at,
        valid_until=valid_until,
        signer_id=signer_id,
        peers=tuple(peers),
        signature="",
    )


def build_bootstrap_manifest_payload(
    *,
    signer_id: str,
    peers: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    issued_at: int | None = None,
    valid_until: int | None = None,
    valid_for_hours: int = 168,
) -> dict[str, Any]:
    timestamp = int(issued_at if issued_at is not None else time.time())
    expiry = int(valid_until if valid_until is not None else timestamp + max(1, int(valid_for_hours or 0)) * 3600)
    payload = {
        "version": BOOTSTRAP_MANIFEST_VERSION,
        "issued_at": timestamp,
        "valid_until": expiry,
        "signer_id": str(signer_id or "").strip(),
        "peers": list(peers),
    }
    manifest = _validate_bootstrap_manifest_payload(payload, now=timestamp)
    return manifest.payload_dict()


def sign_bootstrap_manifest_payload(
    payload: dict[str, Any],
    *,
    signer_private_key_b64: str,
) -> str:
    signer = _load_signer_private_key(signer_private_key_b64)
    serialized = _canonical_manifest_payload(payload).encode("utf-8")
    signature = signer.sign(serialized)
    return base64.b64encode(signature).decode("utf-8")


def write_signed_bootstrap_manifest(
    path: str | Path,
    *,
    signer_id: str,
    signer_private_key_b64: str,
    peers: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    issued_at: int | None = None,
    valid_until: int | None = None,
    valid_for_hours: int = 168,
) -> BootstrapManifest:
    manifest_path = _resolve_manifest_path(str(path))
    payload = build_bootstrap_manifest_payload(
        signer_id=signer_id,
        peers=list(peers),
        issued_at=issued_at,
        valid_until=valid_until,
        valid_for_hours=valid_for_hours,
    )
    signature = sign_bootstrap_manifest_payload(
        payload,
        signer_private_key_b64=signer_private_key_b64,
    )
    manifest = BootstrapManifest(
        version=int(payload["version"]),
        issued_at=int(payload["issued_at"]),
        valid_until=int(payload["valid_until"]),
        signer_id=str(payload["signer_id"]),
        peers=tuple(_validate_bootstrap_peer(dict(peer)) for peer in payload["peers"]),
        signature=signature,
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest.to_dict(), indent=2) + "\n", encoding="utf-8")
    return manifest


def load_bootstrap_manifest(
    path: str | Path,
    *,
    signer_public_key_b64: str,
    now: float | None = None,
) -> BootstrapManifest:
    manifest_path = _resolve_manifest_path(str(path))
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BootstrapManifestError(f"bootstrap manifest not found: {manifest_path}") from exc
    except json.JSONDecodeError as exc:
        raise BootstrapManifestError("bootstrap manifest is not valid JSON") from exc

    if not isinstance(raw, dict):
        raise BootstrapManifestError("bootstrap manifest root must be an object")

    signature = str(raw.get("signature", "") or "").strip()
    payload = {key: value for key, value in raw.items() if key != "signature"}
    if not signature:
        raise BootstrapManifestError("bootstrap manifest signature is required")

    _verify_manifest_signature(
        payload,
        signature_b64=signature,
        signer_public_key_b64=signer_public_key_b64,
    )
    manifest = _validate_bootstrap_manifest_payload(payload, now=now)
    return BootstrapManifest(
        version=manifest.version,
        issued_at=manifest.issued_at,
        valid_until=manifest.valid_until,
        signer_id=manifest.signer_id,
        peers=manifest.peers,
        signature=signature,
    )


def load_bootstrap_manifest_from_settings(*, now: float | None = None) -> BootstrapManifest | None:
    settings = get_settings()
    if bool(getattr(settings, "MESH_BOOTSTRAP_DISABLED", False)):
        return None
    signer_public_key_b64 = str(getattr(settings, "MESH_BOOTSTRAP_SIGNER_PUBLIC_KEY", "") or "").strip()
    if not signer_public_key_b64:
        return None
    manifest_path = _resolve_manifest_path(str(getattr(settings, "MESH_BOOTSTRAP_MANIFEST_PATH", "") or ""))
    return load_bootstrap_manifest(
        manifest_path,
        signer_public_key_b64=signer_public_key_b64,
        now=now,
    )
