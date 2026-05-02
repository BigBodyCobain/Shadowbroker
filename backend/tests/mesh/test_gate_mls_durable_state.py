"""S6B Gate MLS Durable State — prove Rust-state persistence survives restart.

Tests:
- Real restart round-trip: establish gate binding, persist, simulate restart, decrypt
- Imported handles are fresh and Python gate bindings are remapped correctly
- Corrupted or wrong-version Rust gate blob is rejected, invalidated, falls back to rebuild
- High-water epoch regression rejects restore and rebuilds
- Legacy metadata with no Rust blob retains the current rebuild path
- reset clears persisted Rust gate state as well as in-memory binding state
"""

import logging

from services.privacy_core_client import PrivacyCoreError


class _TestGateManager:
    _SECRET = "test-gate-secret-for-envelope-encryption"

    def get_gate_secret(self, gate_id: str) -> str:
        return self._SECRET

    def can_enter(self, sender_id: str, gate_id: str):
        return True, "ok"

    def record_message(self, gate_id: str):
        pass


def _fresh_gate_state(tmp_path, monkeypatch):
    from services import wormhole_supervisor
    from services.mesh import mesh_gate_mls, mesh_reputation, mesh_secure_storage, mesh_wormhole_persona

    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    monkeypatch.setattr(mesh_gate_mls, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_gate_mls, "STATE_FILE", tmp_path / "wormhole_gate_mls.json")
    monkeypatch.setattr(mesh_wormhole_persona, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_persona, "PERSONA_FILE", tmp_path / "wormhole_persona.json")
    monkeypatch.setattr(
        mesh_wormhole_persona,
        "LEGACY_DM_IDENTITY_FILE",
        tmp_path / "wormhole_identity.json",
    )
    monkeypatch.setattr(wormhole_supervisor, "get_transport_tier", lambda: "private_transitional")
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": False},
    )
    monkeypatch.setattr(mesh_reputation, "gate_manager", _TestGateManager(), raising=False)
    mesh_gate_mls.reset_gate_mls_state()
    return mesh_gate_mls, mesh_wormhole_persona


def _compose_and_verify(gate_mls_mod, persona_mod, gate_id, label="scribe"):
    """Create a gate persona, compose a message, return (composed, binding)."""
    persona_mod.bootstrap_wormhole_persona_state(force=True)
    persona_mod.create_gate_persona(gate_id, label=label)
    composed = gate_mls_mod.compose_encrypted_gate_message(gate_id, "pre-restart secret")
    assert composed["ok"] is True
    binding = gate_mls_mod._GATE_BINDINGS.get(gate_mls_mod._stable_gate_ref(gate_id))
    assert binding is not None
    return composed, binding


def test_restart_round_trip_decrypt_after_reload(tmp_path, monkeypatch):
    """Establish gate binding, persist, simulate restart, decrypt successfully."""
    gate_mls_mod, persona_mod = _fresh_gate_state(tmp_path, monkeypatch)
    gate_id = "restart-lab"

    composed, _ = _compose_and_verify(gate_mls_mod, persona_mod, gate_id)

    # Simulate restart: clear in-memory state but NOT persistence.
    gate_mls_mod.reset_gate_mls_state(clear_persistence=False)

    # After reload, binding should be restored from persisted Rust state.
    decrypted = gate_mls_mod.decrypt_gate_message_for_local_identity(
        gate_id=gate_id,
        epoch=int(composed["epoch"]),
        ciphertext=str(composed["ciphertext"]),
        nonce=str(composed["nonce"]),
        sender_ref=str(composed["sender_ref"]),
    )
    assert decrypted["ok"] is True
    assert decrypted["plaintext"] == "pre-restart secret"


def test_imported_handles_are_fresh_and_remapped(tmp_path, monkeypatch):
    """After restart, handles must be fresh; Python gate bindings must be remapped."""
    gate_mls_mod, persona_mod = _fresh_gate_state(tmp_path, monkeypatch)
    gate_id = "handle-lab"

    _compose_and_verify(gate_mls_mod, persona_mod, gate_id)

    gate_key = gate_mls_mod._stable_gate_ref(gate_id)
    binding = gate_mls_mod._GATE_BINDINGS[gate_key]
    original_root_handle = binding.root_group_handle
    original_member_handles = {
        pid: (m.identity_handle, m.group_handle)
        for pid, m in binding.members.items()
    }

    # Simulate restart.
    gate_mls_mod.reset_gate_mls_state(clear_persistence=False)

    # Trigger reload via compose or decrypt.
    gate_mls_mod.compose_encrypted_gate_message(gate_id, "after restart")

    restored_binding = gate_mls_mod._GATE_BINDINGS.get(gate_key)
    assert restored_binding is not None
    assert restored_binding.root_group_handle != original_root_handle
    assert restored_binding.root_group_handle > 0
    for pid, (orig_id_h, orig_grp_h) in original_member_handles.items():
        member = restored_binding.members.get(pid)
        assert member is not None, f"member {pid} missing after restore"
        assert member.identity_handle != orig_id_h
        assert member.identity_handle > 0
        if orig_grp_h > 0:
            assert member.group_handle != orig_grp_h
            assert member.group_handle > 0


def test_corrupted_rust_blob_falls_back_to_rebuild(tmp_path, monkeypatch, caplog):
    """Corrupted Rust gate state blob must be rejected and fall back to rebuild."""
    from services.mesh.mesh_secure_storage import write_domain_json

    gate_mls_mod, persona_mod = _fresh_gate_state(tmp_path, monkeypatch)
    gate_id = "corrupt-lab"

    _compose_and_verify(gate_mls_mod, persona_mod, gate_id)

    gate_key = gate_mls_mod._stable_gate_ref(gate_id)
    filename = gate_mls_mod._rust_gate_state_filename(gate_key)

    # Corrupt the Rust state blob.
    write_domain_json(
        gate_mls_mod.RUST_GATE_STATE_DOMAIN,
        filename,
        {"version": 1, "blob_b64": "AAAA"},  # invalid/truncated blob
    )

    # Simulate restart.
    gate_mls_mod.reset_gate_mls_state(clear_persistence=False)

    with caplog.at_level(logging.WARNING):
        # Should fall back to rebuild, not crash.
        composed = gate_mls_mod.compose_encrypted_gate_message(gate_id, "after corruption")

    assert composed["ok"] is True
    assert "corrupt or incompatible" in caplog.text.lower()

    # After rebuild, a fresh valid Rust state blob should exist (from _persist_binding).
    rust_path = tmp_path / gate_mls_mod.RUST_GATE_STATE_DOMAIN / filename
    assert rust_path.exists(), "rebuild must persist a fresh Rust gate state blob"


def test_wrong_version_rust_blob_falls_back_to_rebuild(tmp_path, monkeypatch, caplog):
    """Wrong version in Rust gate state envelope must be rejected and fall back to rebuild."""
    from services.mesh.mesh_secure_storage import write_domain_json

    gate_mls_mod, persona_mod = _fresh_gate_state(tmp_path, monkeypatch)
    gate_id = "version-lab"

    _compose_and_verify(gate_mls_mod, persona_mod, gate_id)

    gate_key = gate_mls_mod._stable_gate_ref(gate_id)
    filename = gate_mls_mod._rust_gate_state_filename(gate_key)

    # Write wrong version.
    write_domain_json(
        gate_mls_mod.RUST_GATE_STATE_DOMAIN,
        filename,
        {"version": 999, "blob_b64": "AAAA"},
    )

    gate_mls_mod.reset_gate_mls_state(clear_persistence=False)

    with caplog.at_level(logging.WARNING):
        composed = gate_mls_mod.compose_encrypted_gate_message(gate_id, "after version mismatch")

    assert composed["ok"] is True
    assert "corrupt or incompatible" in caplog.text.lower()


def test_high_water_epoch_regression_rejects_restore_and_rebuilds(tmp_path, monkeypatch, caplog):
    """If restored Rust state would regress below high_water, reject and rebuild."""
    gate_mls_mod, persona_mod = _fresh_gate_state(tmp_path, monkeypatch)
    gate_id = "epoch-lab"

    _compose_and_verify(gate_mls_mod, persona_mod, gate_id)

    gate_key = gate_mls_mod._stable_gate_ref(gate_id)

    # Artificially set high_water_epochs above the persisted epoch.
    gate_mls_mod._HIGH_WATER_EPOCHS[gate_key] = 9999

    gate_mls_mod.reset_gate_mls_state(clear_persistence=False)

    # Restore the high-water mark (it was cleared by reset).
    gate_mls_mod._HIGH_WATER_EPOCHS[gate_key] = 9999

    with caplog.at_level(logging.WARNING):
        composed = gate_mls_mod.compose_encrypted_gate_message(gate_id, "after epoch regression")

    assert composed["ok"] is True
    assert "epoch regressed" in caplog.text.lower()


def test_legacy_no_rust_blob_retains_rebuild_path(tmp_path, monkeypatch):
    """Legacy metadata with no Rust blob must fall back to the rebuild path."""
    gate_mls_mod, persona_mod = _fresh_gate_state(tmp_path, monkeypatch)
    gate_id = "legacy-lab"

    _compose_and_verify(gate_mls_mod, persona_mod, gate_id)

    gate_key = gate_mls_mod._stable_gate_ref(gate_id)

    # Delete the Rust state blob (simulating legacy/pre-S6B state).
    rust_path = (
        tmp_path
        / gate_mls_mod.RUST_GATE_STATE_DOMAIN
        / gate_mls_mod._rust_gate_state_filename(gate_key)
    )
    rust_path.unlink(missing_ok=True)

    # Also strip handle fields from persisted metadata to simulate legacy.
    from services.mesh.mesh_secure_storage import read_domain_json, write_domain_json

    state = read_domain_json(
        gate_mls_mod.STATE_DOMAIN,
        gate_mls_mod.STATE_FILENAME,
        gate_mls_mod._default_binding_store,
    )
    gate_entry = state.get("gates", {}).get(gate_key, {})
    gate_entry.pop("root_group_handle", None)
    for m in gate_entry.get("members", {}).values():
        m.pop("identity_handle", None)
        m.pop("group_handle", None)
    write_domain_json(gate_mls_mod.STATE_DOMAIN, gate_mls_mod.STATE_FILENAME, state)

    # Simulate restart.
    gate_mls_mod.reset_gate_mls_state(clear_persistence=False)

    # Should rebuild from metadata and compose successfully.
    composed = gate_mls_mod.compose_encrypted_gate_message(gate_id, "legacy hello")
    assert composed["ok"] is True


def test_reset_clears_rust_gate_state(tmp_path, monkeypatch):
    """reset_gate_mls_state(clear_persistence=True) must remove the Rust gate state blob."""
    gate_mls_mod, persona_mod = _fresh_gate_state(tmp_path, monkeypatch)
    gate_id = "reset-lab"

    _compose_and_verify(gate_mls_mod, persona_mod, gate_id)

    gate_key = gate_mls_mod._stable_gate_ref(gate_id)
    rust_path = (
        tmp_path
        / gate_mls_mod.RUST_GATE_STATE_DOMAIN
        / gate_mls_mod._rust_gate_state_filename(gate_key)
    )
    assert rust_path.exists()

    gate_mls_mod.reset_gate_mls_state(clear_persistence=True)

    assert not rust_path.exists()
    assert len(gate_mls_mod._GATE_BINDINGS) == 0


def test_legacy_custody_migration_preserves_gate_restart_recovery(tmp_path, monkeypatch):
    from services.mesh import mesh_local_custody
    from services.mesh.mesh_secure_storage import read_domain_json, write_domain_json

    gate_mls_mod, persona_mod = _fresh_gate_state(tmp_path, monkeypatch)
    gate_id = "custody-migrate-lab"

    composed, _binding = _compose_and_verify(gate_mls_mod, persona_mod, gate_id)
    gate_key = gate_mls_mod._stable_gate_ref(gate_id)
    rust_filename = gate_mls_mod._rust_gate_state_filename(gate_key)
    gate_state = mesh_local_custody.read_sensitive_domain_json(
        gate_mls_mod.STATE_DOMAIN,
        gate_mls_mod.STATE_FILENAME,
        gate_mls_mod._default_binding_store,
        custody_scope=gate_mls_mod.STATE_CUSTODY_SCOPE,
    )
    rust_state = mesh_local_custody.read_sensitive_domain_json(
        gate_mls_mod.RUST_GATE_STATE_DOMAIN,
        rust_filename,
        lambda: None,
        custody_scope=f"gate_mls_rust_state::{gate_key}",
    )
    write_domain_json(gate_mls_mod.STATE_DOMAIN, gate_mls_mod.STATE_FILENAME, gate_state)
    write_domain_json(gate_mls_mod.RUST_GATE_STATE_DOMAIN, rust_filename, rust_state)

    gate_mls_mod.reset_gate_mls_state(clear_persistence=False)

    decrypted = gate_mls_mod.decrypt_gate_message_for_local_identity(
        gate_id=gate_id,
        epoch=int(composed["epoch"]),
        ciphertext=str(composed["ciphertext"]),
        nonce=str(composed["nonce"]),
        sender_ref=str(composed["sender_ref"]),
    )
    wrapped_state = read_domain_json(gate_mls_mod.STATE_DOMAIN, gate_mls_mod.STATE_FILENAME, lambda: None)
    wrapped_rust = read_domain_json(gate_mls_mod.RUST_GATE_STATE_DOMAIN, rust_filename, lambda: None)

    assert decrypted["ok"] is True
    assert decrypted["plaintext"] == "pre-restart secret"
    assert wrapped_state["kind"] == "sb_local_custody"
    assert wrapped_rust["kind"] == "sb_local_custody"
