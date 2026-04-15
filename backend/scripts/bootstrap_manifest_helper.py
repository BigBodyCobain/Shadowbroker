import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "backend"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.mesh.mesh_bootstrap_manifest import (  # noqa: E402
    bootstrap_signer_public_key_b64,
    generate_bootstrap_signer,
    write_signed_bootstrap_manifest,
)


def _load_peers(args: argparse.Namespace) -> list[dict]:
    peers: list[dict] = []
    if args.peers_file:
        raw = json.loads(Path(args.peers_file).read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError("peers file must be a JSON array")
        for entry in raw:
            if not isinstance(entry, dict):
                raise ValueError("peers file entries must be objects")
            peers.append(dict(entry))
    for peer_arg in args.peer or []:
        parts = [part.strip() for part in str(peer_arg).split(",", 3)]
        if len(parts) < 3:
            raise ValueError("peer entries must look like url,transport,role[,label]")
        peer_url, transport, role = parts[:3]
        label = parts[3] if len(parts) > 3 else ""
        peers.append(
            {
                "peer_url": peer_url,
                "transport": transport,
                "role": role,
                "label": label,
            }
        )
    if not peers:
        raise ValueError("at least one peer is required")
    return peers


def cmd_generate_keypair(_args: argparse.Namespace) -> int:
    signer = generate_bootstrap_signer()
    print(json.dumps(signer, indent=2))
    return 0


def cmd_sign(args: argparse.Namespace) -> int:
    peers = _load_peers(args)
    manifest = write_signed_bootstrap_manifest(
        args.output,
        signer_id=args.signer_id,
        signer_private_key_b64=args.private_key_b64,
        peers=peers,
        valid_for_hours=int(args.valid_hours),
    )
    print(f"Wrote signed bootstrap manifest to {Path(args.output).resolve()}")
    print(f"signer_id={manifest.signer_id}")
    print(f"valid_until={manifest.valid_until}")
    print(f"peer_count={len(manifest.peers)}")
    print(f"MESH_BOOTSTRAP_SIGNER_PUBLIC_KEY={bootstrap_signer_public_key_b64(args.private_key_b64)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate and sign Infonet bootstrap manifests for participant nodes."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    keygen = subparsers.add_parser("generate-keypair", help="Generate an Ed25519 bootstrap signer keypair")
    keygen.set_defaults(func=cmd_generate_keypair)

    sign = subparsers.add_parser("sign", help="Sign a bootstrap manifest from peer entries")
    sign.add_argument("--output", required=True, help="Output path for bootstrap_peers.json")
    sign.add_argument("--signer-id", required=True, help="Manifest signer identifier")
    sign.add_argument(
        "--private-key-b64",
        required=True,
        help="Raw Ed25519 private key in base64 returned by generate-keypair",
    )
    sign.add_argument(
        "--peers-file",
        help="JSON file containing an array of peer objects with peer_url, transport, role, and optional label",
    )
    sign.add_argument(
        "--peer",
        action="append",
        help="Inline peer in the form url,transport,role[,label]. May be repeated.",
    )
    sign.add_argument(
        "--valid-hours",
        type=int,
        default=168,
        help="Manifest validity window in hours (default: 168)",
    )
    sign.set_defaults(func=cmd_sign)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
