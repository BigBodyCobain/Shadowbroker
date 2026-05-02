def _fresh_selftest_state(tmp_path, monkeypatch):
    from services import wormhole_supervisor
    from services.mesh import (
        mesh_dm_mls,
        mesh_dm_relay,
        mesh_secure_storage,
        mesh_wormhole_persona,
    )

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
    monkeypatch.setattr(wormhole_supervisor, "get_transport_tier", lambda: "private_strong")
    mesh_dm_mls.reset_dm_mls_state(clear_privacy_core=True, clear_persistence=True)
    return mesh_dm_mls


def test_dm_selftest_runs_without_returning_plaintext_or_contacts(tmp_path, monkeypatch):
    dm_mls = _fresh_selftest_state(tmp_path, monkeypatch)

    from services.mesh.mesh_dm_selftest import run_dm_selftest

    result = run_dm_selftest("do not return this plaintext")

    assert result["ok"] is True
    assert result["mode"] == "local_synthetic_peer"
    assert result["artifacts"]["plaintext_returned"] is False
    assert result["artifacts"]["contact_created"] is False
    assert result["artifacts"]["network_release_attempted"] is False
    assert result["artifacts"]["plaintext_sha256"]
    assert result["artifacts"]["ciphertext_sha256"]
    assert "do not return this plaintext" not in str(result)
    assert all(check["ok"] for check in result["privacy_checks"])
    assert result["cleanup"]["ok"] is True
    assert dm_mls.has_dm_session(f"sb_dm_selftest_local_{result['run_id']}", f"sb_dm_selftest_peer_{result['run_id']}")[
        "exists"
    ] is False
