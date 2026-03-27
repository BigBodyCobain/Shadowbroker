import argparse
import hashlib
import json
import sys
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Helper for ShadowBroker release version/tag/asset consistency."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    show_parser = subparsers.add_parser("show", help="Show current version, expected tag, and asset")
    show_parser.set_defaults(func=cmd_show)

    set_version_parser = subparsers.add_parser("set-version", help="Update frontend/package.json version")
    set_version_parser.add_argument("version", help="Version like 0.9.6")
    set_version_parser.set_defaults(func=cmd_set_version)

    hash_parser = subparsers.add_parser(
        "hash", help="Compute SHA-256 for a release ZIP and print the updater pin"
    )
    hash_parser.add_argument("zip_path", help="Path to the release ZIP")
    hash_parser.add_argument(
        "--version",
        help="Release version like 0.9.6. Defaults to frontend/package.json version.",
    )
    hash_parser.set_defaults(func=cmd_hash)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
