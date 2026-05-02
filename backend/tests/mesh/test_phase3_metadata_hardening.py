from __future__ import annotations

import asyncio
import time


def test_dm_poll_jitter_uses_high_privacy_window(monkeypatch):
    import main

    observed: list[float] = []

    async def fake_sleep(delay: float):
        observed.append(delay)

    monkeypatch.setattr(main, "_high_privacy_profile_enabled", lambda: True)
    monkeypatch.setattr(main.secrets, "randbelow", lambda upper: upper - 1)
    monkeypatch.setattr(main.asyncio, "sleep", fake_sleep)

    asyncio.run(main._maybe_apply_dm_poll_jitter())

    assert observed == [1.0]


def test_dm_poll_jitter_default_window_stays_small(monkeypatch):
    import main

    observed: list[float] = []

    async def fake_sleep(delay: float):
        observed.append(delay)

    monkeypatch.setattr(main, "_high_privacy_profile_enabled", lambda: False)
    monkeypatch.setattr(main.secrets, "randbelow", lambda upper: upper - 1)
    monkeypatch.setattr(main.asyncio, "sleep", fake_sleep)

    asyncio.run(main._maybe_apply_dm_poll_jitter())

    assert observed == [0.025]


def test_high_privacy_caps_anonymous_gate_session_rotation(tmp_path, monkeypatch):
    from services.config import get_settings
    from services import wormhole_settings
    from services.mesh import mesh_wormhole_persona as persona

    monkeypatch.setattr(persona, "DATA_DIR", tmp_path)
    monkeypatch.setattr(persona, "PERSONA_FILE", tmp_path / "wormhole_persona.json")
    monkeypatch.setattr(wormhole_settings, "DATA_DIR", tmp_path)
    monkeypatch.setattr(wormhole_settings, "WORMHOLE_FILE", tmp_path / "wormhole.json")
    monkeypatch.setattr(wormhole_settings, "_cache", None)
    monkeypatch.setattr(wormhole_settings, "_cache_ts", 0.0)
    monkeypatch.setattr(persona.random, "uniform", lambda _low, _high: 0.0)
    monkeypatch.setenv("MESH_GATE_SESSION_ROTATE_MSGS", "50")
    monkeypatch.setenv("MESH_GATE_SESSION_ROTATE_S", "0")
    get_settings.cache_clear()

    wormhole_settings.write_wormhole_settings(privacy_profile="high")
    persona.bootstrap_wormhole_persona_state(force=True)
    entered = persona.enter_gate_anonymously("ops", rotate=True)
    old_node_id = entered["identity"]["node_id"]

    state = persona.read_wormhole_persona_state()
    state["gate_sessions"]["ops"]["_msg_count"] = 10
    state["gate_sessions"]["ops"]["_created_at"] = time.time()
    persona._write_wormhole_persona_state(state)

    signed = persona.sign_gate_wormhole_event(
        gate_id="ops",
        event_type="gate_message",
        payload={
            "gate": "ops",
            "ciphertext": "ct",
            "nonce": "nonce",
            "sender_ref": "sr",
            "format": "mls1",
            "transport_lock": "private_strong",
        },
    )

    assert signed["node_id"] != old_node_id
    get_settings.cache_clear()


def test_default_profile_does_not_apply_high_privacy_gate_session_cap(tmp_path, monkeypatch):
    from services.config import get_settings
    from services import wormhole_settings
    from services.mesh import mesh_wormhole_persona as persona

    monkeypatch.setattr(persona, "DATA_DIR", tmp_path)
    monkeypatch.setattr(persona, "PERSONA_FILE", tmp_path / "wormhole_persona.json")
    monkeypatch.setattr(wormhole_settings, "DATA_DIR", tmp_path)
    monkeypatch.setattr(wormhole_settings, "WORMHOLE_FILE", tmp_path / "wormhole.json")
    monkeypatch.setattr(wormhole_settings, "_cache", None)
    monkeypatch.setattr(wormhole_settings, "_cache_ts", 0.0)
    monkeypatch.setenv("MESH_GATE_SESSION_ROTATE_MSGS", "50")
    monkeypatch.setenv("MESH_GATE_SESSION_ROTATE_S", "0")
    get_settings.cache_clear()

    wormhole_settings.write_wormhole_settings(privacy_profile="default")
    persona.bootstrap_wormhole_persona_state(force=True)
    entered = persona.enter_gate_anonymously("ops", rotate=True)
    old_node_id = entered["identity"]["node_id"]

    state = persona.read_wormhole_persona_state()
    state["gate_sessions"]["ops"]["_msg_count"] = 10
    state["gate_sessions"]["ops"]["_created_at"] = time.time()
    persona._write_wormhole_persona_state(state)

    signed = persona.sign_gate_wormhole_event(
        gate_id="ops",
        event_type="gate_message",
        payload={
            "gate": "ops",
            "ciphertext": "ct",
            "nonce": "nonce",
            "sender_ref": "sr",
            "format": "mls1",
            "transport_lock": "private_strong",
        },
    )

    assert signed["node_id"] == old_node_id
    get_settings.cache_clear()
