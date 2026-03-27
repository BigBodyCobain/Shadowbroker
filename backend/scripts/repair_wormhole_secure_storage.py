from __future__ import annotations

import json
from pathlib import Path

from services.mesh import mesh_secure_storage
from services.mesh.mesh_wormhole_contacts import CONTACTS_FILE
from services.mesh.mesh_wormhole_identity import IDENTITY_FILE, _default_identity
from services.mesh.mesh_wormhole_persona import PERSONA_FILE, _default_state as _default_persona_state
from services.mesh.mesh_wormhole_ratchet import STATE_FILE as RATCHET_FILE


def _load_payloads() -> dict[Path, object]:
    return {
        IDENTITY_FILE: mesh_secure_storage.read_secure_json(IDENTITY_FILE, _default_identity),
        PERSONA_FILE: mesh_secure_storage.read_secure_json(PERSONA_FILE, _default_persona_state),
        RATCHET_FILE: mesh_secure_storage.read_secure_json(RATCHET_FILE, lambda: {}),
        CONTACTS_FILE: mesh_secure_storage.read_secure_json(CONTACTS_FILE, lambda: {}),
    }


def main() -> None:
    payloads = _load_payloads()

    master_key_file = mesh_secure_storage.MASTER_KEY_FILE
    backup_key_file = master_key_file.with_suffix(master_key_file.suffix + ".bak")
    if master_key_file.exists():
        if backup_key_file.exists():
            backup_key_file.unlink()
        master_key_file.replace(backup_key_file)

    for path, payload in payloads.items():
        mesh_secure_storage.write_secure_json(path, payload)

    print(
        json.dumps(
            {
                "ok": True,
                "rewrapped": [str(path.name) for path in payloads.keys()],
                "master_key": str(master_key_file),
                "backup_master_key": str(backup_key_file) if backup_key_file.exists() else "",
            }
        )
    )


if __name__ == "__main__":
    main()
