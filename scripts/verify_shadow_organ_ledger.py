#!/usr/bin/env python3
"""Fail closed when Shadow retirement coverage becomes incomplete or stale."""

from __future__ import annotations

import json
import sys
from pathlib import Path, PurePosixPath


EXPECTED_PLANES = {
    "product_and_user_value",
    "data_and_provenance",
    "backend_and_api",
    "frontend_components",
    "ux_and_avds",
    "security_privacy_compliance",
    "platform_and_shared_services",
    "information_architecture",
    "content_and_localization",
    "discovery_seo_public_ai",
    "quality_operations_docs",
}
EXPECTED_REUSE_FAMILIES = {
    "provider-neutral-feed-cutover",
    "correlation-early-warning-backtest",
    "temporal-snapshots-and-diffs",
    "hmac-rotation-replay",
    "operational-map-and-source-state-ui",
}
REQUIRED_ORGAN_FIELDS = {
    "id",
    "plane",
    "donor_refs",
    "capability",
    "target_owner",
    "disposition",
    "status",
    "acceptance",
}
FORBIDDEN_REF_PARTS = {".env", "node_modules", ".next", "output", "__pycache__"}


def _fail(errors: list[str], message: str) -> None:
    errors.append(message)


def verify(repo_root: Path) -> list[str]:
    ledger_path = repo_root / "config" / "shadow_organ_ledger.json"
    data = json.loads(ledger_path.read_text(encoding="utf-8"))
    errors: list[str] = []

    if data.get("schema_version") != "shadowbroker-organ-ledger/v1":
        _fail(errors, "unexpected schema_version")

    organs = data.get("organs")
    if not isinstance(organs, list) or not organs:
        return ["organs must be a non-empty list"]

    organ_ids: set[str] = set()
    organ_planes: set[str] = set()
    for index, organ in enumerate(organs):
        missing = REQUIRED_ORGAN_FIELDS - set(organ)
        if missing:
            _fail(errors, f"organs[{index}] missing fields: {sorted(missing)}")
            continue
        organ_id = organ["id"]
        if organ_id in organ_ids:
            _fail(errors, f"duplicate organ id: {organ_id}")
        organ_ids.add(organ_id)
        organ_planes.add(organ["plane"])
        if not organ["donor_refs"]:
            _fail(errors, f"{organ_id}: donor_refs must not be empty")
        if not organ["acceptance"]:
            _fail(errors, f"{organ_id}: acceptance must not be empty")
        for ref in organ["donor_refs"]:
            path = PurePosixPath(ref)
            if path.is_absolute() or ".." in path.parts:
                _fail(errors, f"{organ_id}: unsafe donor ref: {ref}")
                continue
            if FORBIDDEN_REF_PARTS.intersection(path.parts):
                _fail(errors, f"{organ_id}: generated or sensitive donor ref: {ref}")
                continue
            if not (repo_root / path).exists():
                _fail(errors, f"{organ_id}: missing donor ref: {ref}")

    if organ_planes != EXPECTED_PLANES:
        _fail(
            errors,
            "organ plane coverage mismatch: "
            f"missing={sorted(EXPECTED_PLANES - organ_planes)} "
            f"extra={sorted(organ_planes - EXPECTED_PLANES)}",
        )

    reuse_decisions = data.get("reuse_decisions")
    if not isinstance(reuse_decisions, list):
        _fail(errors, "reuse_decisions must be a list")
    else:
        reuse_families: set[str] = set()
        for index, decision in enumerate(reuse_decisions):
            required = {"family", "canonical_owner", "owner_baseline", "decision", "reason"}
            missing = required - set(decision)
            if missing:
                _fail(errors, f"reuse_decisions[{index}] missing fields: {sorted(missing)}")
                continue
            family = decision["family"]
            if family in reuse_families:
                _fail(errors, f"duplicate reuse family: {family}")
            reuse_families.add(family)
            for field in required:
                if not isinstance(decision[field], str) or not decision[field].strip():
                    _fail(errors, f"reuse_decisions[{index}].{field} must be non-empty text")
        if reuse_families != EXPECTED_REUSE_FAMILIES:
            _fail(
                errors,
                "reuse decision coverage mismatch: "
                f"missing={sorted(EXPECTED_REUSE_FAMILIES - reuse_families)} "
                f"extra={sorted(reuse_families - EXPECTED_REUSE_FAMILIES)}",
            )

    planes = data.get("coverage_planes")
    if not isinstance(planes, list):
        return errors + ["coverage_planes must be a list"]
    plane_names = {plane.get("plane") for plane in planes}
    if plane_names != EXPECTED_PLANES:
        _fail(
            errors,
            "declared coverage plane mismatch: "
            f"missing={sorted(EXPECTED_PLANES - plane_names)} "
            f"extra={sorted(plane_names - EXPECTED_PLANES)}",
        )
    for plane in planes:
        name = plane.get("plane", "<missing>")
        roots = plane.get("roots")
        mapped_ids = plane.get("organ_ids")
        if not isinstance(roots, list) or not roots:
            _fail(errors, f"{name}: roots must be a non-empty list")
            continue
        if not isinstance(mapped_ids, list) or not mapped_ids:
            _fail(errors, f"{name}: organ_ids must be a non-empty list")
            continue
        unknown = set(mapped_ids) - organ_ids
        if unknown:
            _fail(errors, f"{name}: unknown organ ids: {sorted(unknown)}")
        for ref in roots:
            path = PurePosixPath(ref)
            if path.is_absolute() or ".." in path.parts or not (repo_root / path).exists():
                _fail(errors, f"{name}: missing or unsafe coverage root: {ref}")

    rules = data.get("rules", {})
    required_deletion_gates = {
        "replacement_live",
        "consumer_parity",
        "full_cadence",
        "rollback_receipt",
        "credential_revocation",
        "exact_resource_inventory",
    }
    if set(rules.get("deletion_gate", [])) != required_deletion_gates:
        _fail(errors, "deletion_gate does not match the retirement contract")
    retirement = data.get("retirement", {})
    if retirement.get("status") == "ready" and retirement.get("blockers"):
        _fail(errors, "retirement cannot be ready while blockers remain")

    return errors


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    errors = verify(repo_root)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Shadow organ ledger: 11/11 planes covered; donor refs and retirement gates valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
