"""P4B: Secure storage secret rotation / rewrap path.

Tests prove:
- Master key rotates from old secret -> new secret and remains readable
- Domain key rotates from old secret -> new secret and remains readable
- Secure JSON created before rotation is still readable after rotation
- Domain JSON created before rotation is still readable after rotation
- Old secret fails after successful rotation
- Wrong old secret fails closed and does not partially rewrite state
- Missing new secret fails closed
- Same old/new secret fails closed
- No passphrase envelopes to rotate fails closed
- Windows DPAPI path unchanged (skipped by rotation)
- Raw -> passphrase migration path still works after rotation code is present
"""

import json
import os
from types import SimpleNamespace

import pytest


def _reset(mod):
    mod._MASTER_KEY_CACHE = None
    mod._DOMAIN_KEY_CACHE.clear()


def _setup_passphrase_env(monkeypatch, tmp_path, secret):
    """Configure monkeypatch for non-Windows passphrase mode."""
    from services.mesh import mesh_secure_storage
    from services import config as config_mod

    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    monkeypatch.setattr(mesh_secure_storage, "_is_windows", lambda: False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("MESH_SECURE_STORAGE_SECRET", secret)
    monkeypatch.setattr(
        config_mod,
        "get_settings",
        lambda: SimpleNamespace(
            MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK=False,
            MESH_SECURE_STORAGE_SECRET=secret,
        ),
    )
    _reset(mesh_secure_storage)
    return mesh_secure_storage


class TestMasterKeyRotation:
    def test_master_key_rotates_and_remains_readable(self, tmp_path, monkeypatch):
        mod = _setup_passphrase_env(monkeypatch, tmp_path, "old-secret")
        original_key = mod._load_master_key()

        result = mod.rotate_storage_secret("old-secret", "new-secret", base_dir=tmp_path)
        assert result["ok"] is True
        assert "wormhole_secure_store.key" in result["rotated"]

        # Reload with new secret
        _setup_passphrase_env(monkeypatch, tmp_path, "new-secret")
        loaded_key = mod._load_master_key()
        assert loaded_key == original_key

    def test_old_secret_fails_after_rotation(self, tmp_path, monkeypatch):
        mod = _setup_passphrase_env(monkeypatch, tmp_path, "old-secret")
        mod._load_master_key()

        mod.rotate_storage_secret("old-secret", "new-secret", base_dir=tmp_path)

        # Try loading with old secret — must fail
        _setup_passphrase_env(monkeypatch, tmp_path, "old-secret")
        with pytest.raises(mod.SecureStorageError, match="Failed to unwrap"):
            mod._load_master_key()


class TestDomainKeyRotation:
    def test_domain_key_rotates_and_remains_readable(self, tmp_path, monkeypatch):
        mod = _setup_passphrase_env(monkeypatch, tmp_path, "old-secret")
        original_key = mod._load_domain_key("testdomain", base_dir=tmp_path)

        result = mod.rotate_storage_secret("old-secret", "new-secret", base_dir=tmp_path)
        assert result["ok"] is True
        assert "testdomain.key" in result["rotated"]

        _setup_passphrase_env(monkeypatch, tmp_path, "new-secret")
        loaded_key = mod._load_domain_key("testdomain", base_dir=tmp_path)
        assert loaded_key == original_key

    def test_multiple_domain_keys_rotate(self, tmp_path, monkeypatch):
        mod = _setup_passphrase_env(monkeypatch, tmp_path, "old-secret")
        # Create master key first so it's included in rotation
        mod._load_master_key()
        key_a = mod._load_domain_key("domain_a", base_dir=tmp_path)
        key_b = mod._load_domain_key("domain_b", base_dir=tmp_path)

        result = mod.rotate_storage_secret("old-secret", "new-secret", base_dir=tmp_path)
        assert len(result["rotated"]) == 3  # master + 2 domains

        _setup_passphrase_env(monkeypatch, tmp_path, "new-secret")
        assert mod._load_domain_key("domain_a", base_dir=tmp_path) == key_a
        assert mod._load_domain_key("domain_b", base_dir=tmp_path) == key_b


class TestSecureJsonSurvivesRotation:
    def test_secure_json_readable_after_rotation(self, tmp_path, monkeypatch):
        mod = _setup_passphrase_env(monkeypatch, tmp_path, "old-secret")
        json_path = tmp_path / "secret_data.json"
        mod.write_secure_json(json_path, {"classified": "intel"})

        mod.rotate_storage_secret("old-secret", "new-secret", base_dir=tmp_path)

        _setup_passphrase_env(monkeypatch, tmp_path, "new-secret")
        data = mod.read_secure_json(json_path, lambda: {})
        assert data == {"classified": "intel"}

    def test_domain_json_readable_after_rotation(self, tmp_path, monkeypatch):
        mod = _setup_passphrase_env(monkeypatch, tmp_path, "old-secret")
        mod.write_domain_json("gate_persona", "state.json", {"persona": "anon"}, base_dir=tmp_path)

        mod.rotate_storage_secret("old-secret", "new-secret", base_dir=tmp_path)

        _setup_passphrase_env(monkeypatch, tmp_path, "new-secret")
        data = mod.read_domain_json("gate_persona", "state.json", lambda: {}, base_dir=tmp_path)
        assert data == {"persona": "anon"}


class TestRotationFailsClosed:
    def test_wrong_old_secret_fails_without_partial_rewrite(self, tmp_path, monkeypatch):
        mod = _setup_passphrase_env(monkeypatch, tmp_path, "correct-secret")
        mod._load_master_key()
        mod._load_domain_key("testdomain", base_dir=tmp_path)

        # Capture file contents before failed rotation
        master_before = (tmp_path / "wormhole_secure_store.key").read_text(encoding="utf-8")
        domain_before = (tmp_path / "_domain_keys" / "testdomain.key").read_text(encoding="utf-8")

        with pytest.raises(mod.SecureStorageError, match="Old secret cannot unwrap"):
            mod.rotate_storage_secret("wrong-secret", "new-secret", base_dir=tmp_path)

        # Files must be unchanged
        assert (tmp_path / "wormhole_secure_store.key").read_text(encoding="utf-8") == master_before
        assert (tmp_path / "_domain_keys" / "testdomain.key").read_text(encoding="utf-8") == domain_before

    def test_missing_new_secret_fails(self, tmp_path, monkeypatch):
        mod = _setup_passphrase_env(monkeypatch, tmp_path, "old-secret")
        mod._load_master_key()

        with pytest.raises(mod.SecureStorageError, match="New secret is required"):
            mod.rotate_storage_secret("old-secret", "", base_dir=tmp_path)

    def test_missing_old_secret_fails(self, tmp_path, monkeypatch):
        mod = _setup_passphrase_env(monkeypatch, tmp_path, "old-secret")
        mod._load_master_key()

        with pytest.raises(mod.SecureStorageError, match="Old secret is required"):
            mod.rotate_storage_secret("", "new-secret", base_dir=tmp_path)

    def test_same_old_new_secret_fails(self, tmp_path, monkeypatch):
        mod = _setup_passphrase_env(monkeypatch, tmp_path, "same-secret")
        mod._load_master_key()

        with pytest.raises(mod.SecureStorageError, match="must differ"):
            mod.rotate_storage_secret("same-secret", "same-secret", base_dir=tmp_path)

    def test_no_passphrase_envelopes_fails(self, tmp_path, monkeypatch):
        from services.mesh import mesh_secure_storage

        # Empty directory — no envelopes at all
        with pytest.raises(mesh_secure_storage.SecureStorageError, match="No passphrase-protected envelopes"):
            mesh_secure_storage.rotate_storage_secret("old", "new", base_dir=tmp_path)


class TestDPAPISkippedDuringRotation:
    @pytest.mark.skipif(os.name != "nt", reason="DPAPI only available on Windows")
    def test_dpapi_envelopes_skipped_not_broken(self, tmp_path, monkeypatch):
        from services.mesh import mesh_secure_storage

        monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
        _reset(mesh_secure_storage)

        # Create a DPAPI envelope (Windows default)
        key = mesh_secure_storage._load_master_key()
        envelope_before = (tmp_path / "wormhole_secure_store.key").read_text(encoding="utf-8")
        assert json.loads(envelope_before)["provider"] == "dpapi-machine"

        # Rotation should fail with "no passphrase envelopes" — DPAPI is skipped
        with pytest.raises(mesh_secure_storage.SecureStorageError, match="No passphrase-protected envelopes"):
            mesh_secure_storage.rotate_storage_secret("old", "new", base_dir=tmp_path)

        # DPAPI envelope untouched
        assert (tmp_path / "wormhole_secure_store.key").read_text(encoding="utf-8") == envelope_before


class TestRawMigrationNotRegressed:
    """P4A raw -> passphrase migration still works with rotation code present."""

    def test_raw_to_passphrase_migration_still_works(self, tmp_path, monkeypatch):
        from services.mesh import mesh_secure_storage
        from services import config as config_mod

        monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
        monkeypatch.setattr(mesh_secure_storage, "_is_windows", lambda: False)

        # Create raw envelope
        raw_key = os.urandom(32)
        envelope = mesh_secure_storage._master_envelope_for_fallback(raw_key)
        (tmp_path / "wormhole_secure_store.key").write_text(json.dumps(envelope), encoding="utf-8")

        # Set up with secret and no raw fallback
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.setenv("MESH_SECURE_STORAGE_SECRET", "migration-secret")
        monkeypatch.setattr(
            config_mod,
            "get_settings",
            lambda: SimpleNamespace(
                MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK=False,
                MESH_SECURE_STORAGE_SECRET="migration-secret",
            ),
        )
        _reset(mesh_secure_storage)

        loaded = mesh_secure_storage._load_master_key()
        assert loaded == raw_key

        migrated = json.loads((tmp_path / "wormhole_secure_store.key").read_text(encoding="utf-8"))
        assert migrated["provider"] == "passphrase"


class TestRotationSkipsNonPassphrase:
    def test_raw_envelopes_skipped_in_rotation(self, tmp_path, monkeypatch):
        mod = _setup_passphrase_env(monkeypatch, tmp_path, "old-secret")
        # Create a passphrase master key
        mod._load_master_key()

        # Manually write a raw domain key alongside
        raw_domain_key = os.urandom(32)
        dk_dir = tmp_path / "_domain_keys"
        dk_dir.mkdir(parents=True, exist_ok=True)
        raw_envelope = mod._domain_key_envelope_for_fallback("rawdomain", raw_domain_key)
        (dk_dir / "rawdomain.key").write_text(json.dumps(raw_envelope), encoding="utf-8")

        result = mod.rotate_storage_secret("old-secret", "new-secret", base_dir=tmp_path)
        assert "rawdomain.key" in result["skipped"]
        assert "wormhole_secure_store.key" in result["rotated"]

        # Raw domain key file unchanged
        raw_after = json.loads((dk_dir / "rawdomain.key").read_text(encoding="utf-8"))
        assert raw_after["provider"] == "raw"


class TestDryRunMode:
    """Dry-run validates without writing anything."""

    def test_dry_run_returns_would_rotate_without_writing(self, tmp_path, monkeypatch):
        mod = _setup_passphrase_env(monkeypatch, tmp_path, "old-secret")
        mod._load_master_key()
        mod._load_domain_key("testdomain", base_dir=tmp_path)

        master_before = (tmp_path / "wormhole_secure_store.key").read_text(encoding="utf-8")
        domain_before = (tmp_path / "_domain_keys" / "testdomain.key").read_text(encoding="utf-8")

        result = mod.rotate_storage_secret("old-secret", "new-secret", base_dir=tmp_path, dry_run=True)

        assert result["ok"] is True
        assert result["dry_run"] is True
        assert "wormhole_secure_store.key" in result["would_rotate"]
        assert "testdomain.key" in result["would_rotate"]
        assert "rotated" not in result
        assert "backups" not in result

        # Files must be unchanged
        assert (tmp_path / "wormhole_secure_store.key").read_text(encoding="utf-8") == master_before
        assert (tmp_path / "_domain_keys" / "testdomain.key").read_text(encoding="utf-8") == domain_before

    def test_dry_run_fails_on_wrong_old_secret(self, tmp_path, monkeypatch):
        mod = _setup_passphrase_env(monkeypatch, tmp_path, "correct-secret")
        mod._load_master_key()

        with pytest.raises(mod.SecureStorageError, match="Old secret cannot unwrap"):
            mod.rotate_storage_secret("wrong-secret", "new-secret", base_dir=tmp_path, dry_run=True)

    def test_dry_run_no_bak_files_created(self, tmp_path, monkeypatch):
        mod = _setup_passphrase_env(monkeypatch, tmp_path, "old-secret")
        mod._load_master_key()

        mod.rotate_storage_secret("old-secret", "new-secret", base_dir=tmp_path, dry_run=True)

        bak_files = list(tmp_path.rglob("*.bak"))
        assert bak_files == []

    def test_dry_run_reports_skipped_non_passphrase(self, tmp_path, monkeypatch):
        mod = _setup_passphrase_env(monkeypatch, tmp_path, "old-secret")
        mod._load_master_key()

        # Add a raw domain key
        dk_dir = tmp_path / "_domain_keys"
        dk_dir.mkdir(parents=True, exist_ok=True)
        raw_envelope = mod._domain_key_envelope_for_fallback("rawdomain", os.urandom(32))
        (dk_dir / "rawdomain.key").write_text(json.dumps(raw_envelope), encoding="utf-8")

        result = mod.rotate_storage_secret("old-secret", "new-secret", base_dir=tmp_path, dry_run=True)
        assert "rawdomain.key" in result["skipped"]
        assert "wormhole_secure_store.key" in result["would_rotate"]


class TestPreRotationBackups:
    """Phase 2a creates .bak copies before rewriting envelopes."""

    def test_rotation_creates_bak_files(self, tmp_path, monkeypatch):
        mod = _setup_passphrase_env(monkeypatch, tmp_path, "old-secret")
        mod._load_master_key()
        mod._load_domain_key("testdomain", base_dir=tmp_path)

        master_before = (tmp_path / "wormhole_secure_store.key").read_text(encoding="utf-8")
        domain_before = (tmp_path / "_domain_keys" / "testdomain.key").read_text(encoding="utf-8")

        result = mod.rotate_storage_secret("old-secret", "new-secret", base_dir=tmp_path)

        assert "wormhole_secure_store.key.bak" in result["backups"]
        assert "testdomain.key.bak" in result["backups"]

        # .bak files contain the old envelopes
        assert (tmp_path / "wormhole_secure_store.key.bak").read_text(encoding="utf-8") == master_before
        assert (tmp_path / "_domain_keys" / "testdomain.key.bak").read_text(encoding="utf-8") == domain_before

    def test_backup_contains_old_secret_envelope(self, tmp_path, monkeypatch):
        mod = _setup_passphrase_env(monkeypatch, tmp_path, "old-secret")
        original_key = mod._load_master_key()

        mod.rotate_storage_secret("old-secret", "new-secret", base_dir=tmp_path)

        # The .bak envelope should be unwrappable with the old secret
        bak_envelope = json.loads((tmp_path / "wormhole_secure_store.key.bak").read_text(encoding="utf-8"))
        assert bak_envelope["provider"] == "passphrase"
        recovered_key = mod._passphrase_unwrap(bak_envelope, "old-secret")
        assert recovered_key == original_key

    def test_rotation_result_includes_backups_list(self, tmp_path, monkeypatch):
        mod = _setup_passphrase_env(monkeypatch, tmp_path, "old-secret")
        mod._load_master_key()

        result = mod.rotate_storage_secret("old-secret", "new-secret", base_dir=tmp_path)
        assert "backups" in result
        assert len(result["backups"]) == len(result["rotated"])

    def test_old_secret_still_works_via_bak_after_rotation(self, tmp_path, monkeypatch):
        """Operator can recover by restoring .bak files if they lose the new secret."""
        mod = _setup_passphrase_env(monkeypatch, tmp_path, "old-secret")
        original_key = mod._load_master_key()

        mod.rotate_storage_secret("old-secret", "new-secret", base_dir=tmp_path)

        # Simulate restore: copy .bak back over the rotated file
        import shutil
        shutil.copy2(
            str(tmp_path / "wormhole_secure_store.key.bak"),
            str(tmp_path / "wormhole_secure_store.key"),
        )

        _setup_passphrase_env(monkeypatch, tmp_path, "old-secret")
        recovered = mod._load_master_key()
        assert recovered == original_key
