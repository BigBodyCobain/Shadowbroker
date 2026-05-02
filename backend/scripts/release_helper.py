import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE_JSON = ROOT / "frontend" / "package.json"


def _normalize_version(raw: str) -> str:
    version = str(raw or "").strip()
    if version.startswith("v"):
        version = version[1:]
    parts = version.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise ValueError("Version must look like X.Y.Z")
    return version


def _read_package_json() -> dict:
    return json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))


def _write_package_json(data: dict) -> None:
    PACKAGE_JSON.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def current_version() -> str:
    return str(_read_package_json().get("version") or "").strip()


def set_version(version: str) -> str:
    normalized = _normalize_version(version)
    data = _read_package_json()
    data["version"] = normalized
    _write_package_json(data)
    return normalized


def expected_tag(version: str) -> str:
    return f"v{_normalize_version(version)}"


def expected_asset(version: str) -> str:
    normalized = _normalize_version(version)
    return f"ShadowBroker_v{normalized}.zip"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 128), b""):
            digest.update(chunk)
    return digest.hexdigest().lower()


def _default_generated_at() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_release_attestation(
    *,
    suite_green: bool,
    suite_name: str = "dm_relay_security",
    detail: str = "",
    report: str = "",
    command: str = "",
    commit: str = "",
    generated_at: str = "",
    threat_model_reference: str = "docs/mesh/threat-model.md",
    workflow: str = "",
    run_id: str = "",
    run_attempt: str = "",
    ref: str = "",
) -> dict:
    normalized_generated_at = str(generated_at or "").strip() or _default_generated_at()
    normalized_commit = str(commit or "").strip() or os.environ.get("GITHUB_SHA", "").strip()
    normalized_workflow = str(workflow or "").strip() or os.environ.get("GITHUB_WORKFLOW", "").strip()
    normalized_run_id = str(run_id or "").strip() or os.environ.get("GITHUB_RUN_ID", "").strip()
    normalized_run_attempt = str(run_attempt or "").strip() or os.environ.get("GITHUB_RUN_ATTEMPT", "").strip()
    normalized_ref = str(ref or "").strip() or os.environ.get("GITHUB_REF", "").strip()
    normalized_suite_name = str(suite_name or "").strip() or "dm_relay_security"
    normalized_report = str(report or "").strip()
    normalized_command = str(command or "").strip()
    normalized_detail = str(detail or "").strip() or (
        "CI attestation confirms the DM relay security suite is green."
        if suite_green
        else "CI attestation recorded a failing DM relay security suite run."
    )
    payload = {
        "generated_at": normalized_generated_at,
        "commit": normalized_commit,
        "threat_model_reference": str(threat_model_reference or "").strip()
        or "docs/mesh/threat-model.md",
        "dm_relay_security_suite": {
            "name": normalized_suite_name,
            "green": bool(suite_green),
            "detail": normalized_detail,
            "report": normalized_report,
        },
    }
    if normalized_command:
        payload["dm_relay_security_suite"]["command"] = normalized_command
    ci = {
        "workflow": normalized_workflow,
        "run_id": normalized_run_id,
        "run_attempt": normalized_run_attempt,
        "ref": normalized_ref,
    }
    if any(ci.values()):
        payload["ci"] = ci
    return payload


def write_release_attestation(output_path: Path | str, **kwargs) -> dict:
    path = Path(output_path).resolve()
    payload = build_release_attestation(**kwargs)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def cmd_show(_args: argparse.Namespace) -> int:
    version = current_version()
    if not version:
        print("package.json has no version", file=sys.stderr)
        return 1
    print(f"package.json version : {version}")
    print(f"expected git tag     : {expected_tag(version)}")
    print(f"expected zip asset   : {expected_asset(version)}")
    return 0


def cmd_set_version(args: argparse.Namespace) -> int:
    version = set_version(args.version)
    print(f"Set frontend/package.json version to {version}")
    print(f"Next release tag  : {expected_tag(version)}")
    print(f"Next zip asset    : {expected_asset(version)}")
    return 0


def cmd_hash(args: argparse.Namespace) -> int:
    version = _normalize_version(args.version) if args.version else current_version()
    if not version:
        print("No version available; pass --version or set frontend/package.json", file=sys.stderr)
        return 1

    zip_path = Path(args.zip_path).resolve()
    if not zip_path.is_file():
        print(f"ZIP not found: {zip_path}", file=sys.stderr)
        return 1

    digest = sha256_file(zip_path)
    expected_name = expected_asset(version)
    asset_matches = zip_path.name == expected_name

    print(f"release version     : {version}")
    print(f"expected git tag    : {expected_tag(version)}")
    print(f"zip path            : {zip_path}")
    print(f"zip name matches    : {'yes' if asset_matches else 'no'}")
    print(f"expected zip asset  : {expected_name}")
    print(f"SHA-256             : {digest}")
    print("")
    print("Updater pin:")
    print(f"MESH_UPDATE_SHA256={digest}")
    return 0 if asset_matches else 2


def cmd_write_attestation(args: argparse.Namespace) -> int:
    suite_green = bool(args.suite_green)
    payload = write_release_attestation(
        args.output_path,
        suite_green=suite_green,
        suite_name=args.suite_name,
        detail=args.detail,
        report=args.report,
        command=args.command,
        commit=args.commit,
        generated_at=args.generated_at,
        threat_model_reference=args.threat_model_reference,
        workflow=args.workflow,
        run_id=args.run_id,
        run_attempt=args.run_attempt,
        ref=args.ref,
    )
    output_path = Path(args.output_path).resolve()
    print(f"Wrote release attestation: {output_path}")
    print(f"DM relay security suite : {'green' if suite_green else 'red'}")
    print(f"Commit                  : {payload.get('commit', '')}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Helper for ShadowBroker release version/tag/asset consistency."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    show_parser = subparsers.add_parser("show", help="Show current version, expected tag, and asset")
    show_parser.set_defaults(func=cmd_show)

    set_version_parser = subparsers.add_parser("set-version", help="Update frontend/package.json version")
    set_version_parser.add_argument("version", help="Version like 0.9.7")
    set_version_parser.set_defaults(func=cmd_set_version)

    hash_parser = subparsers.add_parser(
        "hash", help="Compute SHA-256 for a release ZIP and print the updater pin"
    )
    hash_parser.add_argument("zip_path", help="Path to the release ZIP")
    hash_parser.add_argument(
        "--version",
        help="Release version like 0.9.7. Defaults to frontend/package.json version.",
    )
    hash_parser.set_defaults(func=cmd_hash)

    attestation_parser = subparsers.add_parser(
        "write-attestation",
        help="Write a structured Sprint 8 release attestation JSON file",
    )
    attestation_parser.add_argument("output_path", help="Where to write the attestation JSON")
    suite_group = attestation_parser.add_mutually_exclusive_group(required=True)
    suite_group.add_argument(
        "--suite-green",
        action="store_true",
        help="Mark the DM relay security suite as green",
    )
    suite_group.add_argument(
        "--suite-red",
        action="store_true",
        help="Mark the DM relay security suite as failing",
    )
    attestation_parser.add_argument(
        "--suite-name",
        default="dm_relay_security",
        help="Suite name to record in the attestation",
    )
    attestation_parser.add_argument(
        "--detail",
        default="",
        help="Human-readable suite detail. Defaults to a CI-generated message.",
    )
    attestation_parser.add_argument(
        "--report",
        default="",
        help="Path to the suite report or artifact reference to embed in the attestation.",
    )
    attestation_parser.add_argument(
        "--command",
        default="",
        help="Exact suite command used to generate the attestation.",
    )
    attestation_parser.add_argument(
        "--commit",
        default="",
        help="Commit SHA. Defaults to GITHUB_SHA when available.",
    )
    attestation_parser.add_argument(
        "--generated-at",
        default="",
        help="UTC timestamp for the attestation. Defaults to current UTC time.",
    )
    attestation_parser.add_argument(
        "--threat-model-reference",
        default="docs/mesh/threat-model.md",
        help="Threat model reference to embed in the attestation.",
    )
    attestation_parser.add_argument(
        "--workflow",
        default="",
        help="Workflow name. Defaults to GITHUB_WORKFLOW when available.",
    )
    attestation_parser.add_argument(
        "--run-id",
        default="",
        help="Workflow run ID. Defaults to GITHUB_RUN_ID when available.",
    )
    attestation_parser.add_argument(
        "--run-attempt",
        default="",
        help="Workflow run attempt. Defaults to GITHUB_RUN_ATTEMPT when available.",
    )
    attestation_parser.add_argument(
        "--ref",
        default="",
        help="Git ref. Defaults to GITHUB_REF when available.",
    )
    attestation_parser.set_defaults(func=cmd_write_attestation)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
