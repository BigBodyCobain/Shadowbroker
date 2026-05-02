"""S6A DM MLS Durable State — prove Rust-state persistence survives restart.

Tests:
- Real restart round-trip: establish, persist, simulate restart, decrypt
- Imported state yields fresh handles; Python metadata is remapped
- Corrupted or wrong-version persisted DM state is rejected and invalidated
- Legacy state with no Rust blob retains fail-closed behavior
- reset clears persisted Rust state as well as Python metadata
"""

import logging


def _fresh_dm_mls_state(tmp_path, monkeypatch):
    from services import wormhole_supervisor
    from services.mesh import mesh_dm_mls, mesh_dm_relay, mesh_secure_storage, mesh_wormhole_persona

    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    monkeypatch.setattr(mesh_wormhole_persona, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_persona, "PERSONA_FILE", tmp_path / "wormhole_persona.json")
    monkeypatch.setattr(
        mesh_wormhole_persona,
        "LEGACY_DM_IDENTITY_FILE",
        tmp_path / "wormhole_identity.json",
    )
    monkeypatch.setattr(mesh_dm_mls, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_dm_mls, "STATE_FILE", tmp_path / "wormhole_dm_mls.json")
    monkeypatch.setattr(mesh_dm_relay, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_dm_relay, "RELAY_FILE", tmp_path / "dm_relay.json")
    monkeypatch.setattr(
        mesh_dm_mls,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": True},
    )
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": True},
    )
    relay = mesh_dm_relay.DMRelay()
    monkeypatch.setattr(mesh_dm_relay, "dm_relay", relay)
    mesh_dm_mls.reset_dm_mls_state(clear_privacy_core=True, clear_persistence=True)
    return mesh_dm_mls, relay


def _establish_session(dm_mls):
    """Create alice→bob MLS session, return (dm_mls, session_id)."""
    bob_bundle = dm_mls.export_dm_key_package_for_alias("bob")
    assert bob_bundle["ok"] is True
    initiated = dm_mls.initiate_dm_session("alice", "bob", bob_bundle)
    assert initiated["ok"] is True
    accepted = dm_mls.accept_dm_session("bob", "alice", initiated["welcome"])
    assert accepted["ok"] is True
    return accepted["session_id"]


def test_restart_round_trip_decrypt_after_reload(tmp_path, monkeypatch):
    """Establish session, persist, simulate restart, decrypt successfully."""
    dm_mls, _ = _fresh_dm_mls_state(tmp_path, monkeypatch)
    session_id = _establish_session(dm_mls)

    # Encrypt a message before restart.
    encrypted = dm_mls.encrypt_dm("alice", "bob", "pre-restart secret")
    assert encrypted["ok"] is True
    ciphertext = encrypted["ciphertext"]
    nonce = encrypted["nonce"]

    # Simulate restart: clear in-memory state but NOT persistence.
    dm_mls.reset_dm_mls_state(clear_privacy_core=True, clear_persistence=False)

    # After reload, session should be restored from persisted Rust state.
    decrypted = dm_mls.decrypt_dm("bob", "alice", ciphertext, nonce)
    assert decrypted["ok"] is True
    assert decrypted["plaintext"] == "pre-restart secret"
    assert decrypted["session_id"] == session_id


def test_imported_handles_are_fresh_and_remapped(tmp_path, monkeypatch):
    """After restart, handles must be fresh (different from originals); Python metadata remapped."""
    dm_mls, _ = _fresh_dm_mls_state(tmp_path, monkeypatch)
    _establish_session(dm_mls)

    # Record original handles.
    original_alice_handle = dm_mls._ALIAS_IDENTITIES["alice"]
    original_bob_handle = dm_mls._ALIAS_IDENTITIES["bob"]
    original_session = dm_mls._SESSIONS["alice::bob"]
    original_session_handle = original_session.session_handle

    # Simulate restart.
    dm_mls.reset_dm_mls_state(clear_privacy_core=True, clear_persistence=False)

    # Trigger lazy load by querying session existence.
    dm_mls.has_dm_session("alice", "bob")

    # After reload, handles must be different.
    assert dm_mls._ALIAS_IDENTITIES["alice"] != original_alice_handle
    assert dm_mls._ALIAS_IDENTITIES["bob"] != original_bob_handle
    restored_session = dm_mls._SESSIONS.get("alice::bob")
    assert restored_session is not None
    assert restored_session.session_handle != original_session_handle
    assert restored_session.session_handle > 0

    # Binding records must also be updated.
    alice_binding = dm_mls._ALIAS_BINDINGS.get("alice")
    assert alice_binding is not None
    assert int(alice_binding["handle"]) == dm_mls._ALIAS_IDENTITIES["alice"]


def test_corrupted_rust_blob_invalidates_sessions(tmp_path, monkeypatch, caplog):
    """Corrupted Rust state blob must be rejected; sessions must be cleared."""
    from services.mesh.mesh_secure_storage import write_domain_json

    dm_mls, _ = _fresh_dm_mls_state(tmp_path, monkeypatch)
    _establish_session(dm_mls)

    # Persist valid state first.
    dm_mls._save_state()

    # Corrupt the Rust state blob.
    write_domain_json(
        dm_mls.RUST_STATE_DOMAIN,
        dm_mls.RUST_STATE_FILENAME,
        {"version": 1, "blob_b64": "AAAA"},  # invalid/truncated blob
    )

    # Simulate restart.
    dm_mls._ALIAS_IDENTITIES.clear()
    dm_mls._ALIAS_BINDINGS.clear()
    dm_mls._ALIAS_SEAL_KEYS.clear()
    dm_mls._SESSIONS.clear()
    dm_mls._DM_FORMAT_LOCKS.clear()
    dm_mls._STATE_LOADED = False

    with caplog.at_level(logging.WARNING):
        dm_mls._load_state()

    # Sessions must be cleared (fail-closed).
    assert len(dm_mls._SESSIONS) == 0
    assert len(dm_mls._ALIAS_IDENTITIES) == 0
    assert "corrupt or incompatible" in caplog.text.lower()

    # Corrupted Rust state file must be cleaned up.
    rust_path = tmp_path / dm_mls.RUST_STATE_DOMAIN / dm_mls.RUST_STATE_FILENAME
    assert not rust_path.exists()


def test_wrong_version_rust_blob_invalidates(tmp_path, monkeypatch, caplog):
    """Wrong version in Rust state envelope must be rejected."""
    from services.mesh.mesh_secure_storage import write_domain_json

    dm_mls, _ = _fresh_dm_mls_state(tmp_path, monkeypatch)
    _establish_session(dm_mls)
    dm_mls._save_state()

    # Write wrong version.
    write_domain_json(
        dm_mls.RUST_STATE_DOMAIN,
        dm_mls.RUST_STATE_FILENAME,
        {"version": 999, "blob_b64": "AAAA"},
    )

    dm_mls._ALIAS_IDENTITIES.clear()
    dm_mls._SESSIONS.clear()
    dm_mls._STATE_LOADED = False

    with caplog.at_level(logging.WARNING):
        dm_mls._load_state()

    assert len(dm_mls._SESSIONS) == 0
    assert "corrupt or incompatible" in caplog.text.lower()


def test_legacy_no_rust_blob_retains_fail_closed(tmp_path, monkeypatch):
    """Legacy state with no Rust blob: sessions with stale handles must fail-closed."""
    dm_mls, _ = _fresh_dm_mls_state(tmp_path, monkeypatch)
    _establish_session(dm_mls)

    # Persist Python state.
    dm_mls._save_state()

    # Delete the Rust state blob (simulating legacy / pre-S6A state).
    rust_path = tmp_path / dm_mls.RUST_STATE_DOMAIN / dm_mls.RUST_STATE_FILENAME
    rust_path.unlink(missing_ok=True)

    # Simulate restart (clear Rust state but not Python persistence).
    dm_mls.reset_dm_mls_state(clear_privacy_core=True, clear_persistence=False)

    # Sessions are loaded from Python metadata but have stale handles.
    # encrypt_dm should fail with session_expired because the Rust handles are gone.
    result = dm_mls.encrypt_dm("alice", "bob", "should fail")
    assert result["ok"] is False
    assert result["detail"] == "session_expired"


def test_reset_clears_rust_state(tmp_path, monkeypatch):
    """reset_dm_mls_state(clear_persistence=True) must remove the Rust state blob."""
    dm_mls, _ = _fresh_dm_mls_state(tmp_path, monkeypatch)
    _establish_session(dm_mls)
    dm_mls._save_state()

    rust_path = tmp_path / dm_mls.RUST_STATE_DOMAIN / dm_mls.RUST_STATE_FILENAME
    assert rust_path.exists()

    dm_mls.reset_dm_mls_state(clear_privacy_core=True, clear_persistence=True)

    assert not rust_path.exists()
    assert len(dm_mls._SESSIONS) == 0
    assert len(dm_mls._ALIAS_IDENTITIES) == 0


def test_legacy_custody_migration_preserves_dm_restart_recovery(tmp_path, monkeypatch):
    from services.mesh import mesh_local_custody
    from services.mesh.mesh_secure_storage import read_domain_json, write_domain_json

    dm_mls, _ = _fresh_dm_mls_state(tmp_path, monkeypatch)
    _establish_session(dm_mls)
    encrypted = dm_mls.encrypt_dm("alice", "bob", "after legacy custody migration")
    assert encrypted["ok"] is True
    dm_mls._save_state()

    state_payload = mesh_local_custody.read_sensitive_domain_json(
        dm_mls.STATE_DOMAIN,
        dm_mls.STATE_FILENAME,
        dm_mls._default_state,
        custody_scope=dm_mls.STATE_CUSTODY_SCOPE,
    )
    rust_payload = mesh_local_custody.read_sensitive_domain_json(
        dm_mls.RUST_STATE_DOMAIN,
        dm_mls.RUST_STATE_FILENAME,
        lambda: None,
        custody_scope=dm_mls.RUST_STATE_CUSTODY_SCOPE,
    )
    write_domain_json(dm_mls.STATE_DOMAIN, dm_mls.STATE_FILENAME, state_payload)
    write_domain_json(dm_mls.RUST_STATE_DOMAIN, dm_mls.RUST_STATE_FILENAME, rust_payload)

    dm_mls.reset_dm_mls_state(clear_privacy_core=True, clear_persistence=False)

    decrypted = dm_mls.decrypt_dm(
        "bob",
        "alice",
        encrypted["ciphertext"],
        encrypted["nonce"],
    )
    wrapped_state = read_domain_json(dm_mls.STATE_DOMAIN, dm_mls.STATE_FILENAME, lambda: None)
    wrapped_rust = read_domain_json(dm_mls.RUST_STATE_DOMAIN, dm_mls.RUST_STATE_FILENAME, lambda: None)

    assert decrypted["ok"] is True
    assert decrypted["plaintext"] == "after legacy custody migration"
    assert wrapped_state["kind"] == "sb_local_custody"
    assert wrapped_rust["kind"] == "sb_local_custody"
