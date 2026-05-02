"""S7B DM Sessionless Alias Restart Recovery.

Tests:
- Alias with no active DM session can export a key package after privacy-core restart
- Recreated alias handle differs from the stale old handle
- Persisted alias binding metadata is rewritten with new handle/public_bundle/binding_proof
- Active-session durable restore behavior is not regressed
"""

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
    return mesh_dm_mls


def _simulate_privacy_core_restart(dm_mls):
    """Reset privacy-core (destroys all Rust handles) but keep persisted metadata."""
    dm_mls.reset_dm_mls_state(clear_privacy_core=True, clear_persistence=False)


# ── Sessionless alias recovery after restart ─────────────────────────────


def test_alias_export_key_package_after_restart(tmp_path, monkeypatch):
    """An alias with no active DM session must export a key package after restart."""
    dm_mls = _fresh_dm_mls_state(tmp_path, monkeypatch)

    # Create alias identity (no session).
    result1 = dm_mls.export_dm_key_package_for_alias("alice")
    assert result1["ok"] is True

    # Restart privacy-core — all Rust handles become stale.
    _simulate_privacy_core_restart(dm_mls)

    # Must self-heal and succeed, not fail with stale handle.
    result2 = dm_mls.export_dm_key_package_for_alias("alice")
    assert result2["ok"] is True
    assert result2["alias"] == "alice"
    assert result2["mls_key_package"]  # non-empty


def test_recreated_handle_differs_from_stale(tmp_path, monkeypatch):
    """After restart, the recreated alias handle must differ from the stale one."""
    dm_mls = _fresh_dm_mls_state(tmp_path, monkeypatch)

    dm_mls.export_dm_key_package_for_alias("bob")
    old_handle = dm_mls._ALIAS_IDENTITIES["bob"]
    assert old_handle > 0

    _simulate_privacy_core_restart(dm_mls)

    dm_mls.export_dm_key_package_for_alias("bob")
    new_handle = dm_mls._ALIAS_IDENTITIES["bob"]
    assert new_handle > 0
    assert new_handle != old_handle


def test_persisted_binding_metadata_rewritten(tmp_path, monkeypatch):
    """After restart self-heal, persisted alias binding must have new handle/bundle/proof."""
    from services.mesh.mesh_secure_storage import read_domain_json

    dm_mls = _fresh_dm_mls_state(tmp_path, monkeypatch)

    dm_mls.export_dm_key_package_for_alias("carol")
    old_binding = dict(dm_mls._ALIAS_BINDINGS["carol"])
    old_handle = old_binding["handle"]
    old_bundle = old_binding["public_bundle"]
    old_proof = old_binding["binding_proof"]

    _simulate_privacy_core_restart(dm_mls)

    dm_mls.export_dm_key_package_for_alias("carol")

    # In-memory binding must be updated.
    new_binding = dm_mls._ALIAS_BINDINGS["carol"]
    assert new_binding["handle"] != old_handle
    assert new_binding["handle"] > 0
    assert new_binding["public_bundle"]  # non-empty
    assert new_binding["public_bundle"] != old_bundle
    assert new_binding["binding_proof"]  # non-empty
    assert new_binding["binding_proof"] != old_proof

    # Persisted state must also be updated.
    state = read_domain_json(dm_mls.STATE_DOMAIN, dm_mls.STATE_FILENAME, dm_mls._default_state)
    persisted_alias = state.get("aliases", {}).get("carol", {})
    assert persisted_alias["handle"] == new_binding["handle"]
    assert persisted_alias["public_bundle"] == new_binding["public_bundle"]
    assert persisted_alias["binding_proof"] == new_binding["binding_proof"]


# ── Active-session restore not regressed ─────────────────────────────────


def test_active_session_restore_not_regressed(tmp_path, monkeypatch):
    """S6A durable session restore must still work after this change."""
    dm_mls = _fresh_dm_mls_state(tmp_path, monkeypatch)

    # Establish a session.
    bob_bundle = dm_mls.export_dm_key_package_for_alias("bob")
    assert bob_bundle["ok"] is True
    initiated = dm_mls.initiate_dm_session("alice", "bob", bob_bundle)
    assert initiated["ok"] is True
    accepted = dm_mls.accept_dm_session("bob", "alice", initiated["welcome"])
    assert accepted["ok"] is True

    # Encrypt a message before restart.
    encrypted = dm_mls.encrypt_dm("alice", "bob", "pre-restart secret")
    assert encrypted["ok"] is True

    # Restart: clear in-memory state but keep persistence (including Rust blob).
    dm_mls.reset_dm_mls_state(clear_privacy_core=False, clear_persistence=False)

    # Session should be restored from persisted Rust state.
    has = dm_mls.has_dm_session("alice", "bob")
    assert has["ok"] is True
    assert has["exists"] is True
