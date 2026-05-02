"""Rotate the MESH_SECURE_STORAGE_SECRET used to protect key envelopes at rest.

Usage — stop the backend first, then run:

    MESH_OLD_STORAGE_SECRET=<current>  \\
    MESH_NEW_STORAGE_SECRET=<new>      \\
    python -m scripts.rotate_secure_storage_secret

Dry-run mode (validates old secret without writing anything):

    MESH_OLD_STORAGE_SECRET=<current>  \\
    MESH_NEW_STORAGE_SECRET=<new>      \\
    python -m scripts.rotate_secure_storage_secret --dry-run

Or, for Docker deployments:

    docker exec -e MESH_OLD_STORAGE_SECRET=<current> \\
                -e MESH_NEW_STORAGE_SECRET=<new>      \\
                <container> python -m scripts.rotate_secure_storage_secret

After successful rotation, update your .env (or Docker secret file) to set
MESH_SECURE_STORAGE_SECRET to the new value, then restart the backend.

The script fails closed: if the old secret cannot unwrap any existing envelope,
nothing is written. Non-passphrase envelopes (DPAPI, raw) are skipped with a
warning.

Before rewriting, .bak copies of every envelope are created so a mid-rotation
crash leaves recoverable backups on disk.
"""

from __future__ import annotations

import json
import os
import sys


def main() -> None:
    dry_run = "--dry-run" in sys.argv

    old_secret = os.environ.get("MESH_OLD_STORAGE_SECRET", "").strip()
    new_secret = os.environ.get("MESH_NEW_STORAGE_SECRET", "").strip()

    if not old_secret:
        print("ERROR: MESH_OLD_STORAGE_SECRET environment variable is required.", file=sys.stderr)
        sys.exit(1)
    if not new_secret:
        print("ERROR: MESH_NEW_STORAGE_SECRET environment variable is required.", file=sys.stderr)
        sys.exit(1)

    from services.mesh.mesh_secure_storage import SecureStorageError, rotate_storage_secret

    try:
        result = rotate_storage_secret(old_secret, new_secret, dry_run=dry_run)
    except SecureStorageError as exc:
        print(f"ROTATION FAILED: {exc}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(result, indent=2))
    if dry_run:
        print(
            "\nDry run complete. No files were modified. Run again without --dry-run to perform the rotation.",
            file=sys.stderr,
        )
    else:
        print(
            "\nRotation complete. Update MESH_SECURE_STORAGE_SECRET to the new value and restart the backend."
            "\nBackup files (.bak) were created alongside each rotated envelope.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
