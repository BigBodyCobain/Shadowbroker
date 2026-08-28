from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

_SPEC = importlib.util.spec_from_file_location(
    "shadow_retirement_receipt_verifier",
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "verify_shadow_retirement_receipt.py",
)
assert _SPEC is not None and _SPEC.loader is not None
_VERIFIER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_VERIFIER)
_canonical_payload = _VERIFIER._canonical_payload
verify = _VERIFIER.verify


def _signed_receipt(tmp_path: Path) -> tuple[Path, Path, dict]:
    private_key = Ed25519PrivateKey.generate()
    public_key_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    public_key_path = tmp_path / "retirement-public.pem"
    public_key_path.write_bytes(public_key_bytes)
    receipt = {
        "schema_version": "shadowbroker-retirement-receipt/v1",
        "product_id": "shadowbroker",
        "source_revision": "a" * 40,
        "created_at": "2026-08-28T10:00:00Z",
        "status": "ready",
        "blockers": [],
        "gates": {
            name: {"passed": True, "evidence": [f"receipt:{name}"]}
            for name in (
                "replacement_live",
                "consumer_parity",
                "full_cadence",
                "rollback_receipt",
                "credential_revocation",
                "exact_resource_inventory",
            )
        },
        "resources": [
            {
                "resource_id": "shadow-service",
                "kind": "service",
                "exact_locator": "service:shadowbroker-app",
                "exact_identity": "sha256:" + "b" * 64,
                "delete_order": 1,
            }
        ],
        "retained_artifacts": [
            {
                "artifact_id": "final-release-manifest",
                "exact_locator": "protected-archive:shadow/final-release.json",
                "sha256": "c" * 64,
            }
        ],
        "credential_actions": [
            {
                "binding_id": "mesh-hmac",
                "action": "rotated",
                "evidence": ["receipt:mesh-old-rejected"],
            }
        ],
        "signature": {
            "algorithm": "ed25519",
            "key_sha256": hashlib.sha256(public_key_bytes).hexdigest(),
            "value": "",
        },
    }
    receipt["signature"]["value"] = base64.b64encode(
        private_key.sign(_canonical_payload(receipt))
    ).decode()
    receipt_path = tmp_path / "retirement.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    return receipt_path, public_key_path, receipt


def test_signed_exact_retirement_receipt_passes(tmp_path: Path) -> None:
    receipt_path, public_key_path, _ = _signed_receipt(tmp_path)
    assert verify(receipt_path, public_key_path) == []


def test_tampered_receipt_fails_signature(tmp_path: Path) -> None:
    receipt_path, public_key_path, receipt = _signed_receipt(tmp_path)
    receipt["resources"][0]["exact_identity"] = "sha256:" + "d" * 64
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    assert verify(receipt_path, public_key_path) == ["receipt signature is invalid"]


def test_broad_resource_target_is_rejected_before_signature(tmp_path: Path) -> None:
    receipt_path, public_key_path, receipt = _signed_receipt(tmp_path)
    receipt["resources"][0]["exact_locator"] = "/opt"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    errors = verify(receipt_path, public_key_path)
    assert "resources[0].exact_locator is broad or ambiguous" in errors


def test_broad_retained_artifact_target_is_rejected(tmp_path: Path) -> None:
    receipt_path, public_key_path, receipt = _signed_receipt(tmp_path)
    receipt["retained_artifacts"][0]["exact_locator"] = "/var/lib/*"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    errors = verify(receipt_path, public_key_path)
    assert "retained_artifacts[0].exact_locator is broad or ambiguous" in errors


def test_image_requires_digest_identity(tmp_path: Path) -> None:
    receipt_path, public_key_path, receipt = _signed_receipt(tmp_path)
    receipt["resources"][0]["kind"] = "image"
    receipt["resources"][0]["exact_identity"] = "shadowbroker:latest"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    errors = verify(receipt_path, public_key_path)
    assert "resources[0].exact_identity must be an image digest" in errors


def test_credential_action_requires_exact_binding(tmp_path: Path) -> None:
    receipt_path, public_key_path, receipt = _signed_receipt(tmp_path)
    del receipt["credential_actions"][0]["binding_id"]
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    errors = verify(receipt_path, public_key_path)
    assert "credential_actions[0].binding_id is required" in errors
