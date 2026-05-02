import asyncio


class _TestGateManager:
    _SECRET = "test-gate-secret-for-envelope-encryption"

    def get_gate_secret(self, gate_id: str) -> str:
        return self._SECRET

    def can_enter(self, sender_id: str, gate_id: str):
        return True, "ok"

    def record_message(self, gate_id: str):
        pass


def _fresh_gate_state(tmp_path, monkeypatch):
    import auth
    from services import wormhole_supervisor
    from services.mesh import (
        mesh_gate_mls,
        mesh_gate_repair,
        mesh_reputation,
        mesh_secure_storage,
        mesh_wormhole_persona,
    )

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
    monkeypatch.setattr(auth, "_debug_mode_enabled", lambda: True)
    monkeypatch.setattr(mesh_reputation, "gate_manager", _TestGateManager(), raising=False)
    mesh_gate_repair.reset_gate_repair_manager_for_tests()
    mesh_gate_mls.reset_gate_mls_state()
    auth._admin_key = None
    return mesh_gate_mls, mesh_gate_repair, mesh_wormhole_persona


def _bootstrap_gate(tmp_path, monkeypatch, gate_id="finance"):
    gate_mls_mod, gate_repair_mod, persona_mod = _fresh_gate_state(tmp_path, monkeypatch)
    persona_mod.bootstrap_wormhole_persona_state(force=True)
    persona_mod.create_gate_persona(gate_id, label="scribe")
    composed = gate_mls_mod.compose_encrypted_gate_message(gate_id, "seed message")
    assert composed["ok"] is True
    return gate_mls_mod, gate_repair_mod, persona_mod, composed


def _gate_key_request(path: str):
    from httpx import ASGITransport, AsyncClient
    import auth
    import main

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            response = await ac.get(
                path,
                headers={"X-Admin-Key": auth._current_admin_key()},
            )
            return response.json()

    return asyncio.run(_run())


def test_stale_local_gate_state_auto_resyncs(tmp_path, monkeypatch):
    gate_mls_mod, gate_repair_mod, _persona_mod, _ = _bootstrap_gate(tmp_path, monkeypatch)
    gate_id = "finance"
    gate_key = gate_mls_mod._stable_gate_ref(gate_id)

    gate_mls_mod.reset_gate_mls_state(clear_persistence=False)
    gate_mls_mod._write_gate_rust_state_snapshot(gate_key, None)

    status = gate_repair_mod.ensure_gate_state_ready(gate_id, operation="status")

    assert status["ok"] is True
    assert status["resynced"] is True
    assert status["repair_state"] == "gate_state_ok"
    assert gate_mls_mod._read_gate_rust_state_snapshot(gate_key) is not None


def test_missing_local_gate_state_attempts_repair_before_failure(tmp_path, monkeypatch):
    gate_mls_mod, gate_repair_mod, _persona_mod, _ = _bootstrap_gate(tmp_path, monkeypatch)
    gate_id = "finance"

    gate_mls_mod.reset_gate_mls_state(clear_persistence=False)
    gate_mls_mod._persist_delete_binding(gate_id)

    status = gate_repair_mod.ensure_gate_state_ready(gate_id, operation="status")
    composed = gate_repair_mod.compose_gate_message_with_repair(gate_id, "after repair")

    assert status["ok"] is True
    assert status["resynced"] is True
    assert composed["ok"] is True


def test_gate_envelope_required_retries_after_secret_repair(monkeypatch):
    from services.mesh import mesh_gate_repair, mesh_reputation

    calls = {"compose": 0, "ensure": 0}

    class _RepairGateManager:
        def ensure_gate_secret(self, gate_id: str) -> str:
            calls["ensure"] += 1
            return "test-gate-secret"

        def get_gate_secret(self, gate_id: str) -> str:
            return "test-gate-secret"

    def fake_compose(gate_id: str, plaintext: str, reply_to: str = ""):
        calls["compose"] += 1
        if calls["compose"] == 1:
            return {"ok": False, "detail": "gate_envelope_required", "gate_id": gate_id}
        return {"ok": True, "gate_id": gate_id, "ciphertext": "ct", "gate_envelope": "env"}

    monkeypatch.setattr(mesh_reputation, "gate_manager", _RepairGateManager(), raising=False)
    monkeypatch.setattr(mesh_gate_repair, "compose_encrypted_gate_message", fake_compose)
    mesh_gate_repair.reset_gate_repair_manager_for_tests()

    result = mesh_gate_repair.compose_gate_message_with_repair("finance", "hello")

    assert result["ok"] is True
    assert calls == {"compose": 2, "ensure": 1}


def test_gate_sign_envelope_required_retries_after_secret_repair(monkeypatch):
    from services.mesh import mesh_gate_repair, mesh_reputation

    calls = {"sign": 0, "ensure": 0}

    class _RepairGateManager:
        def ensure_gate_secret(self, gate_id: str) -> str:
            calls["ensure"] += 1
            return "test-gate-secret"

        def get_gate_secret(self, gate_id: str) -> str:
            return "test-gate-secret"

    def fake_sign(**kwargs):
        calls["sign"] += 1
        if calls["sign"] == 1:
            return {"ok": False, "detail": "gate_envelope_required", "gate_id": kwargs.get("gate_id", "")}
        return {"ok": True, "gate_id": kwargs.get("gate_id", ""), "gate_envelope": "env", "envelope_hash": "hash"}

    monkeypatch.setattr(mesh_reputation, "gate_manager", _RepairGateManager(), raising=False)
    monkeypatch.setattr(mesh_gate_repair, "sign_encrypted_gate_message", fake_sign)
    mesh_gate_repair.reset_gate_repair_manager_for_tests()

    result = mesh_gate_repair.sign_gate_message_with_repair(gate_id="finance", ciphertext="ct", nonce="n")

    assert result["ok"] is True
    assert calls == {"sign": 2, "ensure": 1}


def test_failed_repair_preserves_last_good_state(tmp_path, monkeypatch):
    gate_mls_mod, gate_repair_mod, _persona_mod, _ = _bootstrap_gate(tmp_path, monkeypatch)
    gate_id = "finance"
    gate_key = gate_mls_mod._stable_gate_ref(gate_id)
    rust_backup = gate_mls_mod._read_gate_rust_state_snapshot(gate_key)

    gate_mls_mod.reset_gate_mls_state(clear_persistence=False)
    gate_mls_mod._write_gate_rust_state_snapshot(gate_key, None)

    original_sync = gate_mls_mod._sync_binding
    monkeypatch.setattr(gate_mls_mod, "_sync_binding", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    failed = gate_repair_mod.ensure_gate_state_ready(gate_id, operation="status")

    monkeypatch.setattr(gate_mls_mod, "_sync_binding", original_sync)

    exported = gate_repair_mod.export_gate_state_snapshot_with_repair(gate_id)

    assert failed["ok"] is False
    assert failed["repair_state"] == "gate_state_resync_failed"
    assert rust_backup is not None
    assert exported["ok"] is True


def test_ordinary_gate_status_surface_remains_coarse(tmp_path, monkeypatch):
    _bootstrap_gate(tmp_path, monkeypatch)

    result = _gate_key_request("/api/wormhole/gate/finance/key")

    assert result["ok"] is True
    assert result["repair_state"] == "gate_state_ok"
    assert result["detail"] == "gate access ready"
    assert "current_epoch" not in result
    assert "expected_epoch" not in result
    assert "has_metadata" not in result
    assert "has_rust_state" not in result
    assert "last_error_detail" not in result
    assert "identity_persona_id" not in result
    assert "identity_node_id" not in result


def test_diagnostic_gate_status_surface_can_expose_repair_detail(tmp_path, monkeypatch):
    gate_mls_mod, _gate_repair_mod, _persona_mod, _ = _bootstrap_gate(tmp_path, monkeypatch)
    gate_id = "finance"
    gate_key = gate_mls_mod._stable_gate_ref(gate_id)

    gate_mls_mod.reset_gate_mls_state(clear_persistence=False)
    gate_mls_mod._write_gate_rust_state_snapshot(gate_key, None)

    result = _gate_key_request("/api/wormhole/gate/finance/key?exposure=diagnostic")

    assert result["ok"] is True
    assert result["repair_state"] == "gate_state_ok"
    assert result["repair_attempted"] is True
    assert result["has_metadata"] is True
    assert result["has_rust_state"] is True
    assert "current_epoch" in result
    assert "last_reason" in result


def test_gate_usage_recovers_after_resync_without_confidentiality_regression(tmp_path, monkeypatch):
    gate_mls_mod, gate_repair_mod, _persona_mod, _ = _bootstrap_gate(tmp_path, monkeypatch)
    gate_id = "finance"
    gate_key = gate_mls_mod._stable_gate_ref(gate_id)

    gate_mls_mod.reset_gate_mls_state(clear_persistence=False)
    gate_mls_mod._write_gate_rust_state_snapshot(gate_key, None)

    status = gate_repair_mod.ensure_gate_state_ready(gate_id, operation="decrypt")
    composed = gate_repair_mod.compose_gate_message_with_repair(gate_id, "hello after resync")
    decrypted = gate_repair_mod.decrypt_gate_message_with_repair(
        gate_id=gate_id,
        epoch=int(composed["epoch"]),
        ciphertext=str(composed["ciphertext"]),
        nonce=str(composed["nonce"]),
        sender_ref=str(composed["sender_ref"]),
    )

    assert status["ok"] is True
    assert composed["ok"] is True
    assert decrypted == {
        "ok": True,
        "gate_id": gate_id,
        "epoch": int(composed["epoch"]),
        "plaintext": "hello after resync",
        "identity_scope": "persona",
    }
