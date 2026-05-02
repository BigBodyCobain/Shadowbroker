"""P4A: Non-Windows secure storage at-rest hardening for Linux/Docker.

Tests prove:
- Docker no longer auto-allows raw fallback
- Non-Windows with no secure secret and no raw opt-in fails closed
- Non-Windows with MESH_SECURE_STORAGE_SECRET works (passphrase provider)
- Passphrase-protected envelopes round-trip correctly (master + domain)
- Raw-to-passphrase migration works when secret is supplied
- Explicit raw fallback still works only when deliberately enabled
- Windows DPAPI path not regressed (skipped on non-Windows)
- Wrong passphrase fails closed
"""

import json
import os
from types import SimpleNamespace

import pytest


def _reset(mod):
    mod._MASTER_KEY_CACHE = None
    mod._DOMAIN_KEY_CACHE.clear()


class TestDockerNoAutoRawFallback:
    """Docker containers must no longer auto-allow raw fallback."""

    def test_docker_container_does_not_auto_allow_raw(self, monkeypatch):
        from services.mesh import mesh_secure_storage
        from services import config as config_mod

        monkeypatch.setattr(mesh_secure_storage, "_is_windows", lambda: False)
        monkeypatch.setattr(mesh_secure_storage, "_is_docker_container", lambda: True)
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("MESH_SECURE_STORAGE_SECRET", raising=False)
        monkeypatch.setattr(
            config_mod,
            "get_settings",
            lambda: SimpleNamespace(
                MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK=False,
                MESH_SECURE_STORAGE_SECRET="",
            ),
        )

        assert mesh_secure_storage._raw_fallback_allowed() is False

    def test_docker_with_explicit_opt_in_still_allows_raw(self, monkeypatch):
        from services.mesh import mesh_secure_storage
        from services import config as config_mod

        monkeypatch.setattr(mesh_secure_storage, "_is_windows", lambda: False)
        monkeypatch.setattr(mesh_secure_storage, "_is_docker_container", lambda: True)
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.setattr(
            config_mod,
            "get_settings",
            lambda: SimpleNamespace(
                MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK=True,
                MESH_SECURE_STORAGE_SECRET="",
            ),
        )

        assert mesh_secure_storage._raw_fallback_allowed() is True


class TestFailClosedWithoutSecret:
    """Non-Windows with no secret and no raw opt-in must fail closed."""

    def test_master_key_creation_fails_closed(self, tmp_path, monkeypatch):
        from services.mesh import mesh_secure_storage
        from services import config as config_mod

        monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "master.key")
        monkeypatch.setattr(mesh_secure_storage, "_is_windows", lambda: False)
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("MESH_SECURE_STORAGE_SECRET", raising=False)
        monkeypatch.setattr(
            config_mod,
            "get_settings",
            lambda: SimpleNamespace(
                MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK=False,
                MESH_SECURE_STORAGE_SECRET="",
            ),
        )
        _reset(mesh_secure_storage)

        with pytest.raises(mesh_secure_storage.SecureStorageError, match="MESH_SECURE_STORAGE_SECRET"):
            mesh_secure_storage._load_master_key()

    def test_domain_key_creation_fails_closed(self, tmp_path, monkeypatch):
        from services.mesh import mesh_secure_storage
        from services import config as config_mod

        monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "master.key")
        monkeypatch.setattr(mesh_secure_storage, "_is_windows", lambda: False)
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("MESH_SECURE_STORAGE_SECRET", raising=False)
        monkeypatch.setattr(
            config_mod,
            "get_settings",
            lambda: SimpleNamespace(
                MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK=False,
                MESH_SECURE_STORAGE_SECRET="",
            ),
        )
        _reset(mesh_secure_storage)

        with pytest.raises(mesh_secure_storage.SecureStorageError, match="MESH_SECURE_STORAGE_SECRET"):
            mesh_secure_storage._load_domain_key("test_domain", base_dir=tmp_path)


class TestPassphraseProvider:
    """Passphrase-based provider works for master and domain keys."""

    def test_master_key_round_trip_with_passphrase(self, tmp_path, monkeypatch):
        from services.mesh import mesh_secure_storage
        from services import config as config_mod

        monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "master.key")
        monkeypatch.setattr(mesh_secure_storage, "_is_windows", lambda: False)
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.setenv("MESH_SECURE_STORAGE_SECRET", "test-secret-phrase-1234")
        monkeypatch.setattr(
            config_mod,
            "get_settings",
            lambda: SimpleNamespace(
                MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK=False,
                MESH_SECURE_STORAGE_SECRET="test-secret-phrase-1234",
            ),
        )
        _reset(mesh_secure_storage)

        # Create master key
        key1 = mesh_secure_storage._load_master_key()
        assert len(key1) == 32

        # Verify envelope is passphrase-protected
        envelope = json.loads((tmp_path / "master.key").read_text(encoding="utf-8"))
        assert envelope["provider"] == "passphrase"
        assert "salt" in envelope
        assert "key" not in envelope  # No raw key exposed

        # Clear cache, reload
        _reset(mesh_secure_storage)
        key2 = mesh_secure_storage._load_master_key()
        assert key1 == key2

    def test_domain_key_round_trip_with_passphrase(self, tmp_path, monkeypatch):
        from services.mesh import mesh_secure_storage
        from services import config as config_mod

        monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "master.key")
        monkeypatch.setattr(mesh_secure_storage, "_is_windows", lambda: False)
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.setenv("MESH_SECURE_STORAGE_SECRET", "test-secret-phrase-1234")
        monkeypatch.setattr(
            config_mod,
            "get_settings",
            lambda: SimpleNamespace(
                MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK=False,
                MESH_SECURE_STORAGE_SECRET="test-secret-phrase-1234",
            ),
        )
        _reset(mesh_secure_storage)

        key1 = mesh_secure_storage._load_domain_key("testdomain", base_dir=tmp_path)
        assert len(key1) == 32

        # Verify envelope
        key_file = tmp_path / "_domain_keys" / "testdomain.key"
        envelope = json.loads(key_file.read_text(encoding="utf-8"))
        assert envelope["provider"] == "passphrase"
        assert envelope["domain"] == "testdomain"
        assert "key" not in envelope

        # Clear cache, reload
        _reset(mesh_secure_storage)
        key2 = mesh_secure_storage._load_domain_key("testdomain", base_dir=tmp_path)
        assert key1 == key2

    def test_secure_json_end_to_end_with_passphrase(self, tmp_path, monkeypatch):
        from services.mesh import mesh_secure_storage
        from services import config as config_mod

        monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "master.key")
        monkeypatch.setattr(mesh_secure_storage, "_is_windows", lambda: False)
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.setenv("MESH_SECURE_STORAGE_SECRET", "test-secret-phrase-1234")
        monkeypatch.setattr(
            config_mod,
            "get_settings",
            lambda: SimpleNamespace(
                MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK=False,
                MESH_SECURE_STORAGE_SECRET="test-secret-phrase-1234",
            ),
        )
        _reset(mesh_secure_storage)

        path = tmp_path / "secret.json"
        mesh_secure_storage.write_secure_json(path, {"wormhole": "data"})

        # Ciphertext on disk, not plaintext
        raw = path.read_text(encoding="utf-8")
        assert "wormhole" not in raw

        _reset(mesh_secure_storage)
        data = mesh_secure_storage.read_secure_json(path, lambda: {})
        assert data == {"wormhole": "data"}

    def test_domain_json_end_to_end_with_passphrase(self, tmp_path, monkeypatch):
        from services.mesh import mesh_secure_storage
        from services import config as config_mod

        monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "master.key")
        monkeypatch.setattr(mesh_secure_storage, "_is_windows", lambda: False)
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.setenv("MESH_SECURE_STORAGE_SECRET", "test-secret-phrase-1234")
        monkeypatch.setattr(
            config_mod,
            "get_settings",
            lambda: SimpleNamespace(
                MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK=False,
                MESH_SECURE_STORAGE_SECRET="test-secret-phrase-1234",
            ),
        )
        _reset(mesh_secure_storage)

        mesh_secure_storage.write_domain_json("gate_persona", "gate.json", {"gate": "secure"}, base_dir=tmp_path)

        _reset(mesh_secure_storage)
        data = mesh_secure_storage.read_domain_json("gate_persona", "gate.json", lambda: {}, base_dir=tmp_path)
        assert data == {"gate": "secure"}


class TestWrongPassphraseFails:
    """Wrong passphrase must fail closed."""

    def test_wrong_passphrase_rejects_master_key(self, tmp_path, monkeypatch):
        from services.mesh import mesh_secure_storage
        from services import config as config_mod

        monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "master.key")
        monkeypatch.setattr(mesh_secure_storage, "_is_windows", lambda: False)
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.setenv("MESH_SECURE_STORAGE_SECRET", "correct-secret")
        monkeypatch.setattr(
            config_mod,
            "get_settings",
            lambda: SimpleNamespace(
                MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK=False,
                MESH_SECURE_STORAGE_SECRET="correct-secret",
            ),
        )
        _reset(mesh_secure_storage)

        mesh_secure_storage._load_master_key()

        # Now try with wrong secret
        _reset(mesh_secure_storage)
        monkeypatch.setenv("MESH_SECURE_STORAGE_SECRET", "wrong-secret")
        monkeypatch.setattr(
            config_mod,
            "get_settings",
            lambda: SimpleNamespace(
                MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK=False,
                MESH_SECURE_STORAGE_SECRET="wrong-secret",
            ),
        )

        with pytest.raises(mesh_secure_storage.SecureStorageError, match="Failed to unwrap"):
            mesh_secure_storage._load_master_key()

    def test_missing_passphrase_rejects_passphrase_envelope(self, tmp_path, monkeypatch):
        from services.mesh import mesh_secure_storage
        from services import config as config_mod

        monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "master.key")
        monkeypatch.setattr(mesh_secure_storage, "_is_windows", lambda: False)
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.setenv("MESH_SECURE_STORAGE_SECRET", "a-secret")
        monkeypatch.setattr(
            config_mod,
            "get_settings",
            lambda: SimpleNamespace(
                MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK=False,
                MESH_SECURE_STORAGE_SECRET="a-secret",
            ),
        )
        _reset(mesh_secure_storage)

        mesh_secure_storage._load_master_key()

        # Remove the secret
        _reset(mesh_secure_storage)
        monkeypatch.delenv("MESH_SECURE_STORAGE_SECRET", raising=False)
        monkeypatch.setattr(
            config_mod,
            "get_settings",
            lambda: SimpleNamespace(
                MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK=False,
                MESH_SECURE_STORAGE_SECRET="",
            ),
        )

        with pytest.raises(mesh_secure_storage.SecureStorageError, match="MESH_SECURE_STORAGE_SECRET is not set"):
            mesh_secure_storage._load_master_key()


class TestRawToPassphraseMigration:
    """Existing raw envelopes migrate to passphrase when secret is supplied."""

    def test_master_key_migrates_from_raw_to_passphrase(self, tmp_path, monkeypatch):
        from services.mesh import mesh_secure_storage
        from services import config as config_mod

        monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "master.key")
        monkeypatch.setattr(mesh_secure_storage, "_is_windows", lambda: False)

        # Step 1: create raw envelope (simulate old Docker behavior)
        raw_key = os.urandom(32)
        envelope = mesh_secure_storage._master_envelope_for_fallback(raw_key)
        (tmp_path / "master.key").write_text(json.dumps(envelope), encoding="utf-8")

        # Step 2: now set up with secret and no raw fallback
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

        loaded_key = mesh_secure_storage._load_master_key()
        assert loaded_key == raw_key

        # Verify file is now passphrase-protected
        migrated = json.loads((tmp_path / "master.key").read_text(encoding="utf-8"))
        assert migrated["provider"] == "passphrase"
        assert "key" not in migrated

        # Verify it still loads correctly
        _reset(mesh_secure_storage)
        assert mesh_secure_storage._load_master_key() == raw_key

    def test_domain_key_migrates_from_raw_to_passphrase(self, tmp_path, monkeypatch):
        from services.mesh import mesh_secure_storage
        from services import config as config_mod

        monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "master.key")
        monkeypatch.setattr(mesh_secure_storage, "_is_windows", lambda: False)

        # Create raw domain key
        raw_key = os.urandom(32)
        domain = "testdomain"
        envelope = mesh_secure_storage._domain_key_envelope_for_fallback(domain, raw_key)
        key_dir = tmp_path / "_domain_keys"
        key_dir.mkdir(parents=True, exist_ok=True)
        key_file = key_dir / f"{domain}.key"
        key_file.write_text(json.dumps(envelope), encoding="utf-8")

        # Set up with secret
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

        loaded_key = mesh_secure_storage._load_domain_key(domain, base_dir=tmp_path)
        assert loaded_key == raw_key

        migrated = json.loads(key_file.read_text(encoding="utf-8"))
        assert migrated["provider"] == "passphrase"
        assert "key" not in migrated


class TestExplicitRawFallbackStillWorks:
    """Explicit MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK=true still works."""

    def test_raw_fallback_with_opt_in(self, tmp_path, monkeypatch):
        from services.mesh import mesh_secure_storage
        from services import config as config_mod

        monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "master.key")
        monkeypatch.setattr(mesh_secure_storage, "_is_windows", lambda: False)
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("MESH_SECURE_STORAGE_SECRET", raising=False)
        monkeypatch.setattr(
            config_mod,
            "get_settings",
            lambda: SimpleNamespace(
                MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK=True,
                MESH_SECURE_STORAGE_SECRET="",
            ),
        )
        _reset(mesh_secure_storage)

        key = mesh_secure_storage._load_master_key()
        assert len(key) == 32

        envelope = json.loads((tmp_path / "master.key").read_text(encoding="utf-8"))
        assert envelope["provider"] == "raw"

    def test_passphrase_preferred_over_raw_even_with_opt_in(self, tmp_path, monkeypatch):
        """When both secret and raw opt-in are set, passphrase is used for new keys."""
        from services.mesh import mesh_secure_storage
        from services import config as config_mod

        monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "master.key")
        monkeypatch.setattr(mesh_secure_storage, "_is_windows", lambda: False)
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.setenv("MESH_SECURE_STORAGE_SECRET", "a-secret")
        monkeypatch.setattr(
            config_mod,
            "get_settings",
            lambda: SimpleNamespace(
                MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK=True,
                MESH_SECURE_STORAGE_SECRET="a-secret",
            ),
        )
        _reset(mesh_secure_storage)

        mesh_secure_storage._load_master_key()

        envelope = json.loads((tmp_path / "master.key").read_text(encoding="utf-8"))
        assert envelope["provider"] == "passphrase"


class TestWindowsDPAPINotRegressed:
    """Windows DPAPI path must not be affected by P4A changes."""

    @pytest.mark.skipif(os.name != "nt", reason="DPAPI only available on Windows")
    def test_windows_creates_dpapi_envelope(self, tmp_path, monkeypatch):
        from services.mesh import mesh_secure_storage

        monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "master.key")
        _reset(mesh_secure_storage)

        key = mesh_secure_storage._load_master_key()
        assert len(key) == 32

        envelope = json.loads((tmp_path / "master.key").read_text(encoding="utf-8"))
        assert envelope["provider"] == "dpapi-machine"


class TestPassphraseWrapUnwrap:
    """Unit tests for the passphrase wrap/unwrap primitives."""

    def test_wrap_unwrap_round_trip(self):
        from services.mesh.mesh_secure_storage import _passphrase_wrap, _passphrase_unwrap

        key = os.urandom(32)
        secret = "test-passphrase"
        wrapped = _passphrase_wrap(key, secret)
        assert "salt" in wrapped
        assert "nonce" in wrapped
        assert "protected_key" in wrapped

        unwrapped = _passphrase_unwrap(wrapped, secret)
        assert unwrapped == key

    def test_wrong_secret_fails(self):
        from services.mesh.mesh_secure_storage import _passphrase_wrap, _passphrase_unwrap

        key = os.urandom(32)
        wrapped = _passphrase_wrap(key, "correct")
        with pytest.raises(Exception):
            _passphrase_unwrap(wrapped, "incorrect")

    def test_deterministic_with_same_salt(self):
        from services.mesh.mesh_secure_storage import _passphrase_wrap, _passphrase_unwrap

        key = os.urandom(32)
        salt = os.urandom(32)
        wrapped1 = _passphrase_wrap(key, "same-secret", salt=salt)
        # Different nonce means different ciphertext, but both unwrap to same key
        wrapped2 = _passphrase_wrap(key, "same-secret", salt=salt)

        assert _passphrase_unwrap(wrapped1, "same-secret") == key
        assert _passphrase_unwrap(wrapped2, "same-secret") == key


class TestGetStorageSecret:
    """_get_storage_secret reads from env and config correctly."""

    def test_reads_from_env(self, monkeypatch):
        from services.mesh import mesh_secure_storage

        monkeypatch.setenv("MESH_SECURE_STORAGE_SECRET", "env-secret")
        assert mesh_secure_storage._get_storage_secret() == "env-secret"

    def test_returns_none_when_empty(self, monkeypatch):
        from services.mesh import mesh_secure_storage
        from services import config as config_mod

        monkeypatch.delenv("MESH_SECURE_STORAGE_SECRET", raising=False)
        monkeypatch.setattr(
            config_mod,
            "get_settings",
            lambda: SimpleNamespace(MESH_SECURE_STORAGE_SECRET=""),
        )
        assert mesh_secure_storage._get_storage_secret() is None

    def test_falls_back_to_config(self, monkeypatch):
        from services.mesh import mesh_secure_storage
        from services import config as config_mod

        monkeypatch.delenv("MESH_SECURE_STORAGE_SECRET", raising=False)
        monkeypatch.setattr(
            config_mod,
            "get_settings",
            lambda: SimpleNamespace(MESH_SECURE_STORAGE_SECRET="config-secret"),
        )
        assert mesh_secure_storage._get_storage_secret() == "config-secret"
