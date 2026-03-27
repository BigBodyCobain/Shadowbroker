import json
import os
import subprocess
import sys
from types import SimpleNamespace


def _reset_secure_storage_state(mesh_secure_storage) -> None:
    mesh_secure_storage._MASTER_KEY_CACHE = None
    mesh_secure_storage._DOMAIN_KEY_CACHE.clear()


def test_secure_storage_encrypts_and_reads_json(tmp_path, monkeypatch):
    from services.mesh import mesh_secure_storage

    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    _reset_secure_storage_state(mesh_secure_storage)

    path = tmp_path / "secret.json"
    mesh_secure_storage.write_secure_json(path, {"alpha": 1, "bravo": "two"})

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["kind"] == "sb_secure_json"
    assert "alpha" not in path.read_text(encoding="utf-8")

    data = mesh_secure_storage.read_secure_json(path, lambda: {})
    assert data == {"alpha": 1, "bravo": "two"}


def test_secure_storage_migrates_plaintext_json(tmp_path, monkeypatch):
    from services.mesh import mesh_secure_storage

    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    _reset_secure_storage_state(mesh_secure_storage)

    path = tmp_path / "legacy.json"
    path.write_text(json.dumps({"legacy": True}), encoding="utf-8")

    data = mesh_secure_storage.read_secure_json(path, lambda: {})
    assert data == {"legacy": True}

    migrated = json.loads(path.read_text(encoding="utf-8"))
    assert migrated["kind"] == "sb_secure_json"


def test_secure_storage_fails_closed_on_decrypt_error(tmp_path, monkeypatch):
    import pytest

    from services.mesh import mesh_secure_storage

    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    _reset_secure_storage_state(mesh_secure_storage)

    path = tmp_path / "corrupt.json"
    mesh_secure_storage.write_secure_json(path, {"secret": "value"})
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["ciphertext"] = payload["ciphertext"][:-4] + "AAAA"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(mesh_secure_storage.SecureStorageError):
        mesh_secure_storage.read_secure_json(path, lambda: {})


def test_secure_storage_round_trips_across_process_boundary(tmp_path, monkeypatch):
    if os.name != "nt":
        return

    from services.mesh import mesh_secure_storage

    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    _reset_secure_storage_state(mesh_secure_storage)

    path = tmp_path / "cross-process.json"
    mesh_secure_storage.write_secure_json(path, {"alpha": 7, "bravo": "cross-process"})
    backend_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

    script = f"""
import json
from pathlib import Path
from services.mesh import mesh_secure_storage
mesh_secure_storage.DATA_DIR = Path(r"{tmp_path}")
mesh_secure_storage.MASTER_KEY_FILE = Path(r"{tmp_path / 'wormhole_secure_store.key'}")
print(json.dumps(mesh_secure_storage.read_secure_json(r"{path}", lambda: {{}})))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=backend_root,
        capture_output=True,
        text=True,
        env={**os.environ.copy(), "PYTHONPATH": backend_root},
        check=True,
    )

    assert json.loads(result.stdout.strip()) == {"alpha": 7, "bravo": "cross-process"}


def test_domain_storage_isolation_keeps_gate_and_dm_data_separate(tmp_path, monkeypatch):
    from services.mesh import mesh_secure_storage

    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    _reset_secure_storage_state(mesh_secure_storage)

    mesh_secure_storage.write_domain_json("gate_persona", "gate.json", {"gate": "alpha"})
    mesh_secure_storage.write_domain_json("dm_alias", "dm.json", {"alias": "bravo"})

    gate_data = mesh_secure_storage.read_domain_json("gate_persona", "gate.json", lambda: {})
    dm_data = mesh_secure_storage.read_domain_json("dm_alias", "dm.json", lambda: {})

    assert gate_data == {"gate": "alpha"}
    assert dm_data == {"alias": "bravo"}
    assert (tmp_path / "gate_persona" / "gate.json").exists()
    assert (tmp_path / "dm_alias" / "dm.json").exists()


def test_domain_storage_uses_independent_domain_key_files(tmp_path, monkeypatch):
    from services.mesh import mesh_secure_storage

    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    _reset_secure_storage_state(mesh_secure_storage)

    mesh_secure_storage.write_domain_json("gate_persona", "gate.json", {"gate": "alpha"})
    mesh_secure_storage.write_domain_json("dm_alias", "dm.json", {"alias": "bravo"})

    gate_key = tmp_path / "_domain_keys" / "gate_persona.key"
    dm_key = tmp_path / "_domain_keys" / "dm_alias.key"

    assert gate_key.exists()
    assert dm_key.exists()
    assert gate_key.read_text(encoding="utf-8") != dm_key.read_text(encoding="utf-8")
    assert not mesh_secure_storage.MASTER_KEY_FILE.exists()


def test_domain_storage_migrates_legacy_master_derived_ciphertext(tmp_path, monkeypatch):
    import pytest
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    from services.mesh import mesh_secure_storage

    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    _reset_secure_storage_state(mesh_secure_storage)

    domain = "gate_persona"
    filename = "legacy.json"
    payload = {"legacy": True}
    file_path = tmp_path / domain / filename
    file_path.parent.mkdir(parents=True, exist_ok=True)

    nonce = os.urandom(12)
    ciphertext = AESGCM(mesh_secure_storage._derive_legacy_domain_key(domain)).encrypt(
        nonce,
        mesh_secure_storage._stable_json(payload),
        mesh_secure_storage._domain_aad(domain, filename),
    )
    envelope = mesh_secure_storage._secure_envelope(file_path, nonce, ciphertext)
    file_path.write_text(json.dumps(envelope), encoding="utf-8")
    _reset_secure_storage_state(mesh_secure_storage)

    data = mesh_secure_storage.read_domain_json(domain, filename, lambda: {})

    assert data == payload
    assert (tmp_path / "_domain_keys" / f"{domain}.key").exists()

    migrated = json.loads(file_path.read_text(encoding="utf-8"))
    with pytest.raises(Exception):
        AESGCM(mesh_secure_storage._derive_legacy_domain_key(domain)).decrypt(
            mesh_secure_storage._unb64(migrated["nonce"]),
            mesh_secure_storage._unb64(migrated["ciphertext"]),
            mesh_secure_storage._domain_aad(domain, filename),
        )


def test_domain_storage_rejects_path_traversal(tmp_path, monkeypatch):
    import pytest

    from services.mesh import mesh_secure_storage

    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    _reset_secure_storage_state(mesh_secure_storage)

    with pytest.raises(mesh_secure_storage.SecureStorageError):
        mesh_secure_storage._domain_file_path("../../etc", "passwd")


def test_raw_fallback_requires_explicit_opt_in_not_debug(monkeypatch):
    from services import config as config_mod
    from services.mesh import mesh_secure_storage

    monkeypatch.setattr(mesh_secure_storage, "_is_windows", lambda: False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(
        config_mod,
        "get_settings",
        lambda: SimpleNamespace(
            MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK=False,
            MESH_DEBUG_MODE=True,
        ),
    )

    assert mesh_secure_storage._raw_fallback_allowed() is False


def test_raw_fallback_allows_explicit_opt_in(monkeypatch):
    from services import config as config_mod
    from services.mesh import mesh_secure_storage

    monkeypatch.setattr(mesh_secure_storage, "_is_windows", lambda: False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(
        config_mod,
        "get_settings",
        lambda: SimpleNamespace(
            MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK=True,
            MESH_DEBUG_MODE=False,
        ),
    )

    assert mesh_secure_storage._raw_fallback_allowed() is True
