import base64
import copy

import pytest


class _FailingProvider:
    name = "failing"
    protected_at_rest = True

    def wrap(self, scope: str, plaintext: bytes) -> dict:
        raise RuntimeError(f"wrap_failed:{scope}")

    def unwrap(self, envelope: dict, scope: str) -> bytes:
        raise RuntimeError(f"unwrap_failed:{scope}")


class _RawProvider:
    name = "raw"
    protected_at_rest = False

    def wrap(self, scope: str, plaintext: bytes) -> dict:
        from services.mesh import mesh_secure_storage

        return {"payload_b64": mesh_secure_storage._b64(plaintext)}

    def unwrap(self, envelope: dict, scope: str) -> bytes:
        from services.mesh import mesh_secure_storage

        return mesh_secure_storage._unb64(envelope.get("payload_b64"))


class _TestProtectedProvider:
    protected_at_rest = True

    def __init__(self, name: str, xor_byte: int) -> None:
        self.name = name
        self._xor_byte = xor_byte

    def wrap(self, scope: str, plaintext: bytes) -> dict:
        protected = bytes(byte ^ self._xor_byte for byte in reversed(plaintext))
        return {
            "protected_payload": base64.b64encode(protected).decode("ascii"),
        }

    def unwrap(self, envelope: dict, scope: str) -> bytes:
        protected = base64.b64decode(str(envelope.get("protected_payload", "") or ""))
        return bytes(byte ^ self._xor_byte for byte in reversed(protected))


@pytest.fixture()
def custody_env(tmp_path, monkeypatch):
    from services.mesh import mesh_local_custody, mesh_private_outbox, mesh_secure_storage

    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    monkeypatch.setattr(mesh_secure_storage, "_is_windows", lambda: False)
    monkeypatch.setenv("MESH_SECURE_STORAGE_SECRET", "custody-secret")
    mesh_secure_storage._MASTER_KEY_CACHE = None
    mesh_secure_storage._DOMAIN_KEY_CACHE.clear()
    mesh_local_custody.reset_local_custody_for_tests()
    mesh_private_outbox.reset_private_delivery_outbox_for_tests()
    mesh_private_outbox.private_delivery_outbox._load()
    yield tmp_path, mesh_local_custody, mesh_private_outbox, mesh_secure_storage
    mesh_secure_storage._MASTER_KEY_CACHE = None
    mesh_secure_storage._DOMAIN_KEY_CACHE.clear()
    mesh_local_custody.reset_local_custody_for_tests()
    mesh_private_outbox.reset_private_delivery_outbox_for_tests()


def test_sensitive_domain_json_persists_wrapped_payload_and_not_plaintext(custody_env):
    tmp_path, mesh_local_custody, _mesh_private_outbox, mesh_secure_storage = custody_env

    payload = {"msg_id": "dm-1", "ciphertext": "top-secret"}
    mesh_local_custody.write_sensitive_domain_json(
        "private_outbox",
        "sealed_private_outbox.json",
        payload,
        custody_scope="private_outbox",
    )

    wrapped = mesh_secure_storage.read_domain_json(
        "private_outbox",
        "sealed_private_outbox.json",
        lambda: None,
    )
    raw_file = (tmp_path / "private_outbox" / "sealed_private_outbox.json").read_text(encoding="utf-8")

    assert wrapped["kind"] == "sb_local_custody"
    assert wrapped["provider"] == "passphrase"
    assert "ciphertext" not in wrapped
    assert "top-secret" not in raw_file
    assert mesh_local_custody.local_custody_status_snapshot()["code"] == "protected_at_rest"


def test_legacy_payload_auto_migrates_and_reads_after_restart(custody_env):
    _tmp_path, mesh_local_custody, _mesh_private_outbox, mesh_secure_storage = custody_env

    legacy = {"gate_id": "ops", "ciphertext": "sealed"}
    mesh_secure_storage.write_domain_json("gate_persona", "legacy.json", copy.deepcopy(legacy))

    loaded = mesh_local_custody.read_sensitive_domain_json(
        "gate_persona",
        "legacy.json",
        lambda: {},
        custody_scope="gate_migration",
    )
    assert loaded == legacy

    mesh_secure_storage._MASTER_KEY_CACHE = None
    mesh_secure_storage._DOMAIN_KEY_CACHE.clear()
    mesh_local_custody.reset_local_custody_for_tests()

    reloaded = mesh_local_custody.read_sensitive_domain_json(
        "gate_persona",
        "legacy.json",
        lambda: {},
        custody_scope="gate_migration",
    )
    wrapped = mesh_secure_storage.read_domain_json("gate_persona", "legacy.json", lambda: None)

    assert reloaded == legacy
    assert wrapped["kind"] == "sb_local_custody"
    assert wrapped["provider"] == "passphrase"


def test_failed_migration_preserves_legacy_readable_state_and_sets_status(custody_env):
    _tmp_path, mesh_local_custody, _mesh_private_outbox, mesh_secure_storage = custody_env

    legacy = {"session": "dm", "blob_b64": "AAAA"}
    mesh_secure_storage.write_domain_json("dm_alias_rust", "legacy.bin", copy.deepcopy(legacy))
    mesh_local_custody.set_local_custody_provider_for_tests(_FailingProvider())

    loaded = mesh_local_custody.read_sensitive_domain_json(
        "dm_alias_rust",
        "legacy.bin",
        lambda: None,
        custody_scope="dm_migration_failure",
    )
    persisted = mesh_secure_storage.read_domain_json("dm_alias_rust", "legacy.bin", lambda: None)
    status = mesh_local_custody.local_custody_status_snapshot()

    assert loaded == legacy
    assert persisted == legacy
    assert status["code"] == "migration_failed"
    assert "wrap_failed" in status["last_error"]


def test_degraded_local_custody_status_exposed_when_provider_is_raw(custody_env):
    _tmp_path, mesh_local_custody, _mesh_private_outbox, mesh_secure_storage = custody_env

    mesh_local_custody.set_local_custody_provider_for_tests(_RawProvider())
    mesh_local_custody.write_sensitive_domain_json(
        "private_outbox",
        "raw.json",
        {"msg_id": "raw-1"},
        custody_scope="raw_provider",
    )
    wrapped = mesh_secure_storage.read_domain_json("private_outbox", "raw.json", lambda: None)
    status = mesh_local_custody.local_custody_status_snapshot()

    assert wrapped["kind"] == "sb_local_custody"
    assert wrapped["provider"] == "raw"
    assert status["code"] == "degraded_local_custody"
    assert status["protected_at_rest"] is False


def test_raw_envelope_remains_readable_after_switching_to_passphrase_provider(custody_env):
    _tmp_path, mesh_local_custody, _mesh_private_outbox, mesh_secure_storage = custody_env

    mesh_local_custody.set_local_custody_provider_for_tests(_RawProvider())
    mesh_local_custody.write_sensitive_domain_json(
        "private_outbox",
        "provider_transition.json",
        {"msg_id": "transition-1", "ciphertext": "sealed"},
        custody_scope="provider_transition",
    )

    mesh_local_custody.set_local_custody_provider_for_tests(None)
    loaded = mesh_local_custody.read_sensitive_domain_json(
        "private_outbox",
        "provider_transition.json",
        lambda: {},
        custody_scope="provider_transition",
    )
    status = mesh_local_custody.local_custody_status_snapshot()

    assert loaded["msg_id"] == "transition-1"
    assert status["provider"] == "raw"
    assert status["code"] == "degraded_local_custody"


def test_raw_envelope_remains_readable_after_provider_switch_and_restart(custody_env):
    _tmp_path, mesh_local_custody, _mesh_private_outbox, mesh_secure_storage = custody_env

    mesh_local_custody.set_local_custody_provider_for_tests(_RawProvider())
    mesh_local_custody.write_sensitive_domain_json(
        "private_outbox",
        "provider_transition_restart.json",
        {"msg_id": "transition-restart-1", "ciphertext": "sealed"},
        custody_scope="provider_transition_restart",
    )

    mesh_secure_storage._MASTER_KEY_CACHE = None
    mesh_secure_storage._DOMAIN_KEY_CACHE.clear()
    mesh_local_custody.reset_local_custody_for_tests()
    mesh_local_custody.set_local_custody_provider_for_tests(None)

    loaded = mesh_local_custody.read_sensitive_domain_json(
        "private_outbox",
        "provider_transition_restart.json",
        lambda: {},
        custody_scope="provider_transition_restart",
    )
    status = mesh_local_custody.local_custody_status_snapshot()

    assert loaded["msg_id"] == "transition-restart-1"
    assert status["provider"] == "raw"
    assert status["code"] == "degraded_local_custody"


def test_provider_aware_unwrap_reads_existing_envelope_after_switching_test_provider(custody_env):
    _tmp_path, mesh_local_custody, _mesh_private_outbox, mesh_secure_storage = custody_env

    provider_a = _TestProtectedProvider("test-a", 0x2A)
    provider_b = _TestProtectedProvider("test-b", 0x39)
    mesh_local_custody.set_local_custody_provider_for_tests(provider_a)
    mesh_local_custody.write_sensitive_domain_json(
        "gate_persona",
        "provider_aware.json",
        {"gate_id": "ops", "ciphertext": "wrapped"},
        custody_scope="provider_aware",
    )

    mesh_local_custody.set_local_custody_provider_for_tests(provider_b)
    loaded = mesh_local_custody.read_sensitive_domain_json(
        "gate_persona",
        "provider_aware.json",
        lambda: {},
        custody_scope="provider_aware",
    )
    status = mesh_local_custody.local_custody_status_snapshot()

    assert loaded["gate_id"] == "ops"
    assert status["provider"] == "test-a"
    assert status["code"] == "protected_at_rest"


def test_unknown_provider_mismatch_does_not_destroy_readable_state(custody_env):
    _tmp_path, mesh_local_custody, _mesh_private_outbox, mesh_secure_storage = custody_env

    mesh_local_custody.set_local_custody_provider_for_tests(_RawProvider())
    mesh_local_custody.write_sensitive_domain_json(
        "dm_alias",
        "unknown_provider.json",
        {"session_id": "alice::bob"},
        custody_scope="unknown_provider",
    )
    envelope = mesh_secure_storage.read_domain_json("dm_alias", "unknown_provider.json", lambda: None)
    envelope["provider"] = "missing-provider"
    mesh_secure_storage.write_domain_json("dm_alias", "unknown_provider.json", envelope)

    with pytest.raises(mesh_local_custody.LocalCustodyError, match="Unsupported local custody provider"):
        mesh_local_custody.read_sensitive_domain_json(
            "dm_alias",
            "unknown_provider.json",
            lambda: {},
            custody_scope="unknown_provider",
        )

    persisted = mesh_secure_storage.read_domain_json("dm_alias", "unknown_provider.json", lambda: None)
    assert persisted["provider"] == "missing-provider"


def test_private_outbox_recovers_after_legacy_custody_migration(custody_env):
    _tmp_path, mesh_local_custody, mesh_private_outbox, mesh_secure_storage = custody_env

    legacy_outbox = {
        "version": 1,
        "updated_at": 1,
        "items": [
            {
                "id": "outbox-legacy-1",
                "lane": "dm",
                "release_key": "dm-legacy-1",
                "payload": {"msg_id": "dm-legacy-1", "ciphertext": "sealed"},
                "status": {"code": "queued_private_delivery"},
                "required_tier": "private_strong",
                "current_tier": "private_control_only",
                "release_state": "queued",
                "attempts": 0,
                "created_at": 1.0,
                "updated_at": 1.0,
                "released_at": 0.0,
                "last_error": "",
                "result": {},
            }
        ],
    }
    mesh_secure_storage.write_domain_json(
        mesh_private_outbox.OUTBOX_DOMAIN,
        mesh_private_outbox.OUTBOX_FILENAME,
        copy.deepcopy(legacy_outbox),
    )

    mesh_private_outbox.reset_private_delivery_outbox_for_tests()
    mesh_private_outbox.private_delivery_outbox._load()
    wrapped = mesh_secure_storage.read_domain_json(
        mesh_private_outbox.OUTBOX_DOMAIN,
        mesh_private_outbox.OUTBOX_FILENAME,
        lambda: None,
    )

    items = mesh_private_outbox.private_delivery_outbox.list_items(
        limit=10,
        exposure="diagnostic",
    )
    assert len(items) == 1
    assert items[0]["release_key"] == "dm-legacy-1"
    assert wrapped["kind"] == "sb_local_custody"
