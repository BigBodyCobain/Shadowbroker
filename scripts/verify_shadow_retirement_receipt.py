#!/usr/bin/env python3
"""Verify the signed, exact ShadowBroker retirement receipt.

The receipt is deliberately kept outside Git because it contains runtime
locators.  This verifier is fail closed: it accepts only an Ed25519 signature
from an explicitly supplied trust anchor and refuses broad or ambiguous
resource targets.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

SCHEMA_VERSION = "shadowbroker-retirement-receipt/v1"
REQUIRED_GATES = {
    "replacement_live",
    "consumer_parity",
    "full_cadence",
    "rollback_receipt",
    "credential_revocation",
    "exact_resource_inventory",
}
ALLOWED_RESOURCE_KINDS = {
    "container",
    "image",
    "ingress",
    "repository_checkout",
    "schedule",
    "secret_binding",
    "service",
    "volume",
}
FORBIDDEN_EXACT_LOCATORS = {"/", "/etc", "/opt", "/srv", "/var", "/var/lib"}
FULL_SHA256 = re.compile(r"^[0-9a-f]{64}$")
FULL_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
WILDCARD_OR_EXPANSION = re.compile(r"[*?\[\]{}]|\$\(|\$\{|`|(^|/)\.\.(/|$)")


def _canonical_payload(receipt: dict[str, Any]) -> bytes:
    payload = {key: value for key, value in receipt.items() if key != "signature"}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _timestamp(value: Any, field: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not value.endswith("Z"):
        errors.append(f"{field} must be an RFC3339 UTC timestamp")
        return
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        errors.append(f"{field} must be an RFC3339 UTC timestamp")


def _evidence(value: Any, field: str, errors: list[str]) -> None:
    if not isinstance(value, list) or not value:
        errors.append(f"{field} must contain evidence references")
        return
    if any(not isinstance(item, str) or not item.strip() for item in value):
        errors.append(f"{field} contains an invalid evidence reference")


def _verify_structure(receipt: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if receipt.get("schema_version") != SCHEMA_VERSION:
        errors.append("unexpected schema_version")
    if receipt.get("product_id") != "shadowbroker":
        errors.append("product_id must be shadowbroker")
    if receipt.get("status") != "ready":
        errors.append("retirement status must be ready")
    if receipt.get("blockers") != []:
        errors.append("blockers must be an empty list")
    if not FULL_GIT_SHA.fullmatch(str(receipt.get("source_revision", ""))):
        errors.append("source_revision must be an exact 40-character Git SHA")
    _timestamp(receipt.get("created_at"), "created_at", errors)

    gates = receipt.get("gates")
    if not isinstance(gates, dict) or set(gates) != REQUIRED_GATES:
        errors.append("gates must exactly match the Shadow deletion contract")
    else:
        for gate_name, gate in gates.items():
            if not isinstance(gate, dict) or gate.get("passed") is not True:
                errors.append(f"gate {gate_name} is not passed")
                continue
            _evidence(gate.get("evidence"), f"gates.{gate_name}.evidence", errors)

    resources = receipt.get("resources")
    if not isinstance(resources, list) or not resources:
        errors.append("resources must be a non-empty exact inventory")
    else:
        resource_ids: set[str] = set()
        positions: set[int] = set()
        for index, resource in enumerate(resources):
            if not isinstance(resource, dict):
                errors.append(f"resources[{index}] must be an object")
                continue
            resource_id = resource.get("resource_id")
            kind = resource.get("kind")
            locator = resource.get("exact_locator")
            identity = resource.get("exact_identity")
            position = resource.get("delete_order")
            if not isinstance(resource_id, str) or not resource_id.strip():
                errors.append(f"resources[{index}].resource_id is required")
            elif resource_id in resource_ids:
                errors.append(f"duplicate resource_id: {resource_id}")
            else:
                resource_ids.add(resource_id)
            if kind not in ALLOWED_RESOURCE_KINDS:
                errors.append(f"resources[{index}].kind is not allowed")
            if not isinstance(locator, str) or not locator.strip():
                errors.append(f"resources[{index}].exact_locator is required")
            elif locator.rstrip("/") in FORBIDDEN_EXACT_LOCATORS or WILDCARD_OR_EXPANSION.search(locator):
                errors.append(f"resources[{index}].exact_locator is broad or ambiguous")
            if not isinstance(identity, str) or not identity.strip():
                errors.append(f"resources[{index}].exact_identity is required")
            if not isinstance(position, int) or position < 1:
                errors.append(f"resources[{index}].delete_order must be a positive integer")
            elif position in positions:
                errors.append(f"duplicate delete_order: {position}")
            else:
                positions.add(position)
        if positions and positions != set(range(1, len(resources) + 1)):
            errors.append("delete_order must be contiguous and cover every resource")

    retained = receipt.get("retained_artifacts")
    if not isinstance(retained, list) or not retained:
        errors.append("retained_artifacts must contain rollback and audit evidence")
    else:
        for index, artifact in enumerate(retained):
            if not isinstance(artifact, dict):
                errors.append(f"retained_artifacts[{index}] must be an object")
                continue
            if not isinstance(artifact.get("exact_locator"), str) or not artifact["exact_locator"].strip():
                errors.append(f"retained_artifacts[{index}].exact_locator is required")
            if not FULL_SHA256.fullmatch(str(artifact.get("sha256", ""))):
                errors.append(f"retained_artifacts[{index}].sha256 must be exact")

    credentials = receipt.get("credential_actions")
    if not isinstance(credentials, list) or not credentials:
        errors.append("credential_actions must be non-empty")
    else:
        for index, action in enumerate(credentials):
            if not isinstance(action, dict) or action.get("action") not in {"revoked", "rotated"}:
                errors.append(f"credential_actions[{index}] must be revoked or rotated")
                continue
            if "secret" in action or "value" in action:
                errors.append(f"credential_actions[{index}] must not contain secret material")
            _evidence(action.get("evidence"), f"credential_actions[{index}].evidence", errors)

    signature = receipt.get("signature")
    if not isinstance(signature, dict) or signature.get("algorithm") != "ed25519":
        errors.append("signature.algorithm must be ed25519")
    else:
        if not FULL_SHA256.fullmatch(str(signature.get("key_sha256", ""))):
            errors.append("signature.key_sha256 must be exact")
        try:
            base64.b64decode(str(signature.get("value", "")), validate=True)
        except (ValueError, TypeError):
            errors.append("signature.value must be valid base64")
    return errors


def verify(receipt_path: Path, public_key_path: Path) -> list[str]:
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot read receipt: {exc}"]
    if not isinstance(receipt, dict):
        return ["receipt root must be an object"]
    errors = _verify_structure(receipt)
    if errors:
        return errors

    try:
        public_key_bytes = public_key_path.read_bytes()
        public_key = serialization.load_pem_public_key(public_key_bytes)
    except (OSError, ValueError, TypeError) as exc:
        return [f"cannot read Ed25519 trust anchor: {exc}"]
    if not isinstance(public_key, Ed25519PublicKey):
        return ["trust anchor is not an Ed25519 public key"]

    signature = receipt["signature"]
    fingerprint = hashlib.sha256(public_key_bytes).hexdigest()
    if signature["key_sha256"] != fingerprint:
        return ["signature key fingerprint does not match the trust anchor"]
    try:
        public_key.verify(base64.b64decode(signature["value"]), _canonical_payload(receipt))
    except InvalidSignature:
        return ["receipt signature is invalid"]
    return []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--public-key", required=True, type=Path)
    args = parser.parse_args()
    errors = verify(args.receipt, args.public_key)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Shadow retirement receipt: signed exact inventory and all deletion gates valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
