import asyncio

from starlette.requests import Request


def _fresh_persona_state(tmp_path, monkeypatch):
    from services.mesh import mesh_secure_storage, mesh_wormhole_identity, mesh_wormhole_persona

    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    monkeypatch.setattr(mesh_wormhole_persona, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_persona, "PERSONA_FILE", tmp_path / "wormhole_persona.json")
    monkeypatch.setattr(
        mesh_wormhole_persona,
        "LEGACY_DM_IDENTITY_FILE",
        tmp_path / "wormhole_identity.json",
    )
    return mesh_wormhole_persona, mesh_wormhole_identity


def _request(path: str) -> Request:
    return Request(
        {
            "type": "http",
            "headers": [],
            "client": ("test", 12345),
            "method": "POST",
            "path": path,
        }
    )


def test_transport_identity_is_separate_from_dm_identity(tmp_path, monkeypatch):
    persona_mod, identity_mod = _fresh_persona_state(tmp_path, monkeypatch)

    dm_identity = identity_mod.bootstrap_wormhole_identity(force=True)
    persona_state = persona_mod.bootstrap_wormhole_persona_state(force=True)
    transport_identity = persona_state["transport_identity"]

    assert dm_identity["node_id"]
    assert transport_identity["node_id"]
    assert dm_identity["node_id"] != transport_identity["node_id"]
    assert dm_identity["public_key"] != transport_identity["public_key"]


def test_gate_anonymous_session_differs_from_transport_identity(tmp_path, monkeypatch):
    persona_mod, _identity_mod = _fresh_persona_state(tmp_path, monkeypatch)

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    transport_identity = persona_mod.get_transport_identity()
    gate_identity = persona_mod.enter_gate_anonymously("journalists", rotate=True)

    assert gate_identity["ok"] is True
    assert gate_identity["identity"]["scope"] == "gate_session"
    assert gate_identity["identity"]["gate_id"] == "journalists"
    assert gate_identity["identity"]["node_id"] != transport_identity["node_id"]


def test_gate_identities_are_separate_from_root_identity(tmp_path, monkeypatch):
    persona_mod, _identity_mod = _fresh_persona_state(tmp_path, monkeypatch)

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    state = persona_mod.read_wormhole_persona_state()
    root_identity = state["root_identity"]
    gate_session = persona_mod.enter_gate_anonymously("journalists", rotate=True)["identity"]
    gate_persona = persona_mod.create_gate_persona("journalists", label="source-a")["identity"]

    assert root_identity["node_id"]
    assert gate_session["node_id"] != root_identity["node_id"]
    assert gate_session["public_key"] != root_identity["public_key"]
    assert gate_persona["node_id"] != root_identity["node_id"]
    assert gate_persona["public_key"] != root_identity["public_key"]


def test_gate_persona_activation_is_gate_local(tmp_path, monkeypatch):
    persona_mod, _identity_mod = _fresh_persona_state(tmp_path, monkeypatch)

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    first = persona_mod.create_gate_persona("sources", label="source-a")
    second = persona_mod.create_gate_persona("leaks", label="source-a")

    assert first["ok"] is True
    assert second["ok"] is True
    assert first["identity"]["gate_id"] == "sources"
    assert second["identity"]["gate_id"] == "leaks"
    assert first["identity"]["node_id"] != second["identity"]["node_id"]

    active_sources = persona_mod.get_active_gate_identity("sources")
    active_leaks = persona_mod.get_active_gate_identity("leaks")
    assert active_sources["identity"]["persona_id"] == first["identity"]["persona_id"]
    assert active_leaks["identity"]["persona_id"] == second["identity"]["persona_id"]


def test_gate_persona_duplicate_labels_get_unique_suffixes(tmp_path, monkeypatch):
    persona_mod, _identity_mod = _fresh_persona_state(tmp_path, monkeypatch)

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    first = persona_mod.create_gate_persona("sources", label="source-a")
    second = persona_mod.create_gate_persona("sources", label="source-a")
    third = persona_mod.create_gate_persona("sources", label="Source-A")

    assert first["ok"] is True
    assert second["ok"] is True
    assert third["ok"] is True
    assert first["identity"]["label"] == "source-a"
    assert second["identity"]["label"] == "source-a-2"
    assert third["identity"]["label"] == "Source-A-3"


def test_sign_public_event_uses_transport_identity(tmp_path, monkeypatch):
    persona_mod, _identity_mod = _fresh_persona_state(tmp_path, monkeypatch)

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    transport_identity = persona_mod.get_transport_identity()
    signed = persona_mod.sign_public_wormhole_event(
        event_type="message",
        payload={
            "message": "hello",
            "destination": "broadcast",
            "channel": "LongFast",
            "priority": "normal",
            "ephemeral": False,
        },
    )

    assert signed["identity_scope"] == "transport"
    assert signed["node_id"] == transport_identity["node_id"]
    assert signed["public_key"] == transport_identity["public_key"]


def test_sign_gate_event_uses_gate_session_identity(tmp_path, monkeypatch):
    persona_mod, _identity_mod = _fresh_persona_state(tmp_path, monkeypatch)

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    transport_identity = persona_mod.get_transport_identity()
    signed = persona_mod.sign_gate_wormhole_event(
        gate_id="journalists",
        event_type="gate_message",
        payload={
            "gate": "journalists",
            "epoch": 1,
            "ciphertext": "opaque-source-drop",
            "nonce": "nonce-j1",
            "sender_ref": "gate-session-j1",
        },
    )
    gate_identity = persona_mod.get_active_gate_identity("journalists")

    assert signed["identity_scope"] == "gate_session"
    assert signed["gate_id"] == "journalists"
    assert signed["node_id"] == gate_identity["identity"]["node_id"]
    assert signed["node_id"] != transport_identity["node_id"]


def test_leave_gate_forces_new_anonymous_session_on_reentry(tmp_path, monkeypatch):
    persona_mod, _identity_mod = _fresh_persona_state(tmp_path, monkeypatch)

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    first = persona_mod.enter_gate_anonymously("sources", rotate=True)
    persona_mod.leave_gate("sources")
    second = persona_mod.enter_gate_anonymously("sources", rotate=False)

    assert first["identity"]["node_id"]
    assert second["identity"]["node_id"]
    assert first["identity"]["node_id"] != second["identity"]["node_id"]


def test_gate_session_rotation_uses_jitter_window_before_auto_swap(tmp_path, monkeypatch):
    from services.config import get_settings

    persona_mod, _identity_mod = _fresh_persona_state(tmp_path, monkeypatch)
    monkeypatch.setenv("MESH_GATE_SESSION_ROTATE_MSGS", "1")
    monkeypatch.setenv("MESH_GATE_SESSION_ROTATE_JITTER_S", "120")
    get_settings.cache_clear()
    try:
        now = {"value": 1_000.0}
        monkeypatch.setattr(persona_mod.time, "time", lambda: now["value"])
        monkeypatch.setattr(persona_mod.random, "uniform", lambda *_args, **_kwargs: 45.0)

        persona_mod.bootstrap_wormhole_persona_state(force=True)
        first = persona_mod.enter_gate_anonymously("sources", rotate=True)
        persona_mod.sign_gate_wormhole_event(
            gate_id="sources",
            event_type="gate_message",
            payload={
                "gate": "sources",
                "epoch": 1,
                "ciphertext": "opaque",
                "nonce": "nonce-1",
                "sender_ref": "sender-ref-1",
                "format": "mls1",
            },
        )

        same = persona_mod.enter_gate_anonymously("sources", rotate=False)
        scheduled = persona_mod.read_wormhole_persona_state()["gate_sessions"]["sources"]["_rotate_after"]

        assert same["identity"]["node_id"] == first["identity"]["node_id"]
        assert scheduled == 1_045.0

        now["value"] = 1_046.0
        rotated = persona_mod.enter_gate_anonymously("sources", rotate=False)

        assert rotated["identity"]["node_id"] != first["identity"]["node_id"]
    finally:
        get_settings.cache_clear()


def test_gate_enter_leave_do_not_emit_public_breadcrumbs(tmp_path, monkeypatch):
    import main
    from services.mesh import mesh_hashchain

    persona_mod, _identity_mod = _fresh_persona_state(tmp_path, monkeypatch)
    append_called = {"count": 0}

    def fake_append(**kwargs):
        append_called["count"] += 1
        return {"event_id": "unexpected"}

    monkeypatch.setattr(mesh_hashchain.infonet, "append", fake_append)

    body = main.WormholeGateRequest(gate_id="sources", rotate=True)
    entered = asyncio.run(main.api_wormhole_gate_enter(_request("/api/wormhole/gate/enter"), body))
    left = asyncio.run(
        main.api_wormhole_gate_leave(
            _request("/api/wormhole/gate/leave"),
            main.WormholeGateRequest(gate_id="sources"),
        )
    )

    assert entered["ok"] is True
    assert left["ok"] is True
    assert append_called["count"] == 0


def test_clear_active_persona_reverts_gate_to_anonymous_session(tmp_path, monkeypatch):
    persona_mod, _identity_mod = _fresh_persona_state(tmp_path, monkeypatch)

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    persona_mod.enter_gate_anonymously("evidence", rotate=True)
    created = persona_mod.create_gate_persona("evidence", label="reporter")
    cleared = persona_mod.clear_active_gate_persona("evidence")
    active = persona_mod.get_active_gate_identity("evidence")

    assert created["identity"]["scope"] == "gate_persona"
    assert cleared["ok"] is True
    assert cleared["identity"]["scope"] == "gate_session"
    assert active["source"] == "anonymous"


def test_sign_gate_event_uses_active_persona_when_selected(tmp_path, monkeypatch):
    persona_mod, _identity_mod = _fresh_persona_state(tmp_path, monkeypatch)

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    persona_mod.enter_gate_anonymously("ops", rotate=True)
    created = persona_mod.create_gate_persona("ops", label="scribe")
    signed = persona_mod.sign_gate_wormhole_event(
        gate_id="ops",
        event_type="gate_message",
        payload={
            "gate": "ops",
            "epoch": 1,
            "ciphertext": "opaque-persona-post",
            "nonce": "nonce-o1",
            "sender_ref": "persona-ops-1",
        },
    )

    assert created["identity"]["persona_id"]
    assert signed["identity_scope"] == "gate_persona"
    assert signed["node_id"] == created["identity"]["node_id"]


def test_enter_gate_anonymously_clears_existing_active_persona(tmp_path, monkeypatch):
    persona_mod, _identity_mod = _fresh_persona_state(tmp_path, monkeypatch)

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    created = persona_mod.create_gate_persona("ops", label="scribe")
    entered = persona_mod.enter_gate_anonymously("ops", rotate=True)
    active = persona_mod.get_active_gate_identity("ops")

    assert created["identity"]["scope"] == "gate_persona"
    assert entered["identity"]["scope"] == "gate_session"
    assert active["source"] == "anonymous"
    assert active["identity"]["node_id"] == entered["identity"]["node_id"]
    assert active["identity"]["node_id"] != created["identity"]["node_id"]


def test_sign_gate_event_rejects_cross_gate_payload_mismatch(tmp_path, monkeypatch):
    persona_mod, _identity_mod = _fresh_persona_state(tmp_path, monkeypatch)

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    persona_mod.enter_gate_anonymously("ops", rotate=True)
    signed = persona_mod.sign_gate_wormhole_event(
        gate_id="ops",
        event_type="gate_message",
        payload={
            "gate": "finance",
            "epoch": 1,
            "ciphertext": "opaque-cross-gate-post",
            "nonce": "nonce-cross-1",
            "sender_ref": "persona-finance-1",
        },
    )

    assert signed["ok"] is False
    assert signed["detail"] == "gate payload mismatch"
