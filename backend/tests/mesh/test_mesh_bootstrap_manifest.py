import base64
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from services.mesh.mesh_bootstrap_manifest import (
    BOOTSTRAP_MANIFEST_VERSION,
    BootstrapManifestError,
    bootstrap_signer_public_key_b64,
    build_bootstrap_manifest_payload,
    generate_bootstrap_signer,
    load_bootstrap_manifest,
    write_signed_bootstrap_manifest,
)
from services.mesh.mesh_crypto import canonical_json


def _write_signed_manifest(
    path,
    *,
    private_key,
    peers,
    issued_at=1_700_000_000,
    valid_until=1_800_000_000,
    signer_id="bootstrap-test",
):
    payload = {
        "version": BOOTSTRAP_MANIFEST_VERSION,
        "issued_at": issued_at,
        "valid_until": valid_until,
        "signer_id": signer_id,
        "peers": peers,
    }
    signature = base64.b64encode(private_key.sign(canonical_json(payload).encode("utf-8"))).decode("utf-8")
    manifest = dict(payload)
    manifest["signature"] = signature
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def test_load_bootstrap_manifest_roundtrip(tmp_path):
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key_b64 = base64.b64encode(
        private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
    ).decode("utf-8")
    manifest_path = tmp_path / "bootstrap.json"
    _write_signed_manifest(
        manifest_path,
        private_key=private_key,
        peers=[
            {
                "peer_url": "https://seed.example",
                "transport": "clearnet",
                "role": "seed",
                "label": "Primary seed",
            },
            {
                "peer_url": "http://alphaexample.onion",
                "transport": "onion",
                "role": "relay",
            },
        ],
    )

    manifest = load_bootstrap_manifest(
        manifest_path,
        signer_public_key_b64=public_key_b64,
        now=1_750_000_000,
    )

    assert manifest.signer_id == "bootstrap-test"
    assert [peer.peer_url for peer in manifest.peers] == [
        "https://seed.example",
        "http://alphaexample.onion",
    ]
    assert [peer.transport for peer in manifest.peers] == ["clearnet", "onion"]


def test_load_bootstrap_manifest_fails_on_tamper(tmp_path):
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key_b64 = base64.b64encode(
        private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
    ).decode("utf-8")
    manifest_path = tmp_path / "bootstrap.json"
    manifest = _write_signed_manifest(
        manifest_path,
        private_key=private_key,
        peers=[
            {
                "peer_url": "https://seed.example",
                "transport": "clearnet",
                "role": "seed",
            }
        ],
    )
    manifest["peers"][0]["peer_url"] = "https://evil.example"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(BootstrapManifestError, match="signature invalid"):
        load_bootstrap_manifest(
            manifest_path,
            signer_public_key_b64=public_key_b64,
            now=1_750_000_000,
        )


def test_load_bootstrap_manifest_rejects_expired_manifest(tmp_path):
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key_b64 = base64.b64encode(
        private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
    ).decode("utf-8")
    manifest_path = tmp_path / "bootstrap.json"
    _write_signed_manifest(
        manifest_path,
        private_key=private_key,
        peers=[
            {
                "peer_url": "https://seed.example",
                "transport": "clearnet",
                "role": "seed",
            }
        ],
        issued_at=100,
        valid_until=200,
    )

    with pytest.raises(BootstrapManifestError, match="expired"):
        load_bootstrap_manifest(
            manifest_path,
            signer_public_key_b64=public_key_b64,
            now=500,
        )


def test_generate_bootstrap_signer_roundtrip():
    signer = generate_bootstrap_signer()
    assert signer["private_key_b64"]
    assert signer["public_key_b64"]
    assert bootstrap_signer_public_key_b64(signer["private_key_b64"]) == signer["public_key_b64"]


def test_write_signed_bootstrap_manifest_roundtrip(tmp_path):
    signer = generate_bootstrap_signer()
    manifest_path = tmp_path / "bootstrap.json"

    manifest = write_signed_bootstrap_manifest(
        manifest_path,
        signer_id="seed-alpha",
        signer_private_key_b64=signer["private_key_b64"],
        peers=[
            {
                "peer_url": "https://seed.example",
                "transport": "clearnet",
                "role": "seed",
                "label": "Primary seed",
            }
        ],
        valid_for_hours=24,
    )

    loaded = load_bootstrap_manifest(
        manifest_path,
        signer_public_key_b64=signer["public_key_b64"],
        now=manifest.issued_at + 60,
    )

    assert loaded.signer_id == "seed-alpha"
    assert [peer.peer_url for peer in loaded.peers] == ["https://seed.example"]


def test_build_bootstrap_manifest_payload_rejects_invalid_peers():
    with pytest.raises(BootstrapManifestError, match="clearnet bootstrap peers must use https://"):
        build_bootstrap_manifest_payload(
            signer_id="seed-alpha",
            peers=[
                {
                    "peer_url": "http://seed.example",
                    "transport": "clearnet",
                    "role": "seed",
                }
            ],
        )
