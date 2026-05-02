from services.mesh import mesh_privacy_prewarm


def test_privacy_prewarm_runs_highest_privacy_tasks_first(monkeypatch):
    mesh_privacy_prewarm.reset_privacy_prewarm_for_tests()
    calls = []

    monkeypatch.setattr(mesh_privacy_prewarm, "_privacy_mode", lambda: "private")
    monkeypatch.setattr(
        mesh_privacy_prewarm,
        "_kickoff_hidden_transport",
        lambda reason: calls.append(("hidden_transport_warmup", reason)) or {"ok": True, "triggered": True},
    )
    monkeypatch.setattr(
        mesh_privacy_prewarm,
        "_register_prekeys",
        lambda: calls.append(("dm_prekey_bundle", "")) or {"ok": True},
    )
    monkeypatch.setattr(
        mesh_privacy_prewarm,
        "_rotate_lookup_handles",
        lambda: calls.append(("prekey_lookup_rotation", "")) or {"ok": True},
    )
    monkeypatch.setattr(
        mesh_privacy_prewarm,
        "_prepare_gate_personas",
        lambda: calls.append(("gate_persona_state", "")) or {"ok": True},
    )
    monkeypatch.setattr(
        mesh_privacy_prewarm,
        "_probe_rns_readiness",
        lambda: calls.append(("rns_readiness_probe", "")) or {"ok": True, "ready": False},
    )
    monkeypatch.setattr(
        mesh_privacy_prewarm,
        "_outbox_capacity_snapshot",
        lambda: calls.append(("outbox_capacity", "")) or {"ok": True, "pending_count": 0},
    )

    result = mesh_privacy_prewarm.privacy_prewarm_service.run_once(
        reason="queued_gate_delivery",
        current_tier="public_degraded",
        required_tier="private_strong",
        include_transport=True,
    )

    assert result["ok"] is True
    assert [task for task, _reason in calls] == [
        "hidden_transport_warmup",
        "dm_prekey_bundle",
        "prekey_lookup_rotation",
        "gate_persona_state",
        "rns_readiness_probe",
        "outbox_capacity",
    ]
    assert result["tasks"][0]["task"] == "hidden_transport_warmup"


def test_anonymous_user_action_prewarm_defers_transport_until_cadence(monkeypatch):
    mesh_privacy_prewarm.reset_privacy_prewarm_for_tests()

    monkeypatch.setattr(mesh_privacy_prewarm, "_privacy_mode", lambda: "anonymous")
    monkeypatch.setattr(mesh_privacy_prewarm, "_hidden_transport_ready", lambda: False)

    user_action = mesh_privacy_prewarm.privacy_prewarm_service.request_prewarm(
        reason="queued_dm_delivery",
        current_tier="public_degraded",
        required_tier="private_strong",
        now=1000.0,
    )

    assert user_action["mode"] == "anonymous"
    assert user_action["transport_bootstrap_allowed"] is False
    assert user_action["background_prewarm_allowed"] is False
    assert user_action["background_started"] is False

    scheduled = mesh_privacy_prewarm.privacy_prewarm_service.request_prewarm(
        reason="scheduled_prewarm",
        current_tier="public_degraded",
        required_tier="private_strong",
        now=float(user_action["next_anonymous_prewarm_at"]),
    )

    assert scheduled["transport_bootstrap_allowed"] is True
    assert scheduled["background_prewarm_allowed"] is True


def test_anonymous_scheduled_prewarm_runs_on_cadence_not_between_ticks(monkeypatch):
    mesh_privacy_prewarm.reset_privacy_prewarm_for_tests()
    calls = []

    monkeypatch.setattr(mesh_privacy_prewarm, "_privacy_mode", lambda: "anonymous")
    monkeypatch.setattr(mesh_privacy_prewarm, "_current_transport_tier", lambda: "public_degraded")
    monkeypatch.setattr(
        mesh_privacy_prewarm,
        "_kickoff_hidden_transport",
        lambda reason: calls.append(("hidden_transport_warmup", reason)) or {"ok": True, "triggered": True},
    )
    monkeypatch.setattr(mesh_privacy_prewarm, "_register_prekeys", lambda: {"ok": True})
    monkeypatch.setattr(mesh_privacy_prewarm, "_rotate_lookup_handles", lambda: {"ok": True})
    monkeypatch.setattr(mesh_privacy_prewarm, "_prepare_gate_personas", lambda: {"ok": True})
    monkeypatch.setattr(mesh_privacy_prewarm, "_probe_rns_readiness", lambda: {"ok": True})
    monkeypatch.setattr(mesh_privacy_prewarm, "_outbox_capacity_snapshot", lambda: {"ok": True})

    first = mesh_privacy_prewarm.privacy_prewarm_service.run_scheduled_once(
        reason="scheduled_prewarm",
        now=2000.0,
    )
    second = mesh_privacy_prewarm.privacy_prewarm_service.run_scheduled_once(
        reason="scheduled_prewarm",
        now=2010.0,
    )

    assert first["skipped"] is False
    assert second["skipped"] is True
    assert calls == [("hidden_transport_warmup", "scheduled_prewarm")]
    snapshot = mesh_privacy_prewarm.privacy_prewarm_service.snapshot()
    assert snapshot["scheduled_count"] == 2


def test_private_scheduled_prewarm_targets_private_strong(monkeypatch):
    mesh_privacy_prewarm.reset_privacy_prewarm_for_tests()

    monkeypatch.setattr(mesh_privacy_prewarm, "_privacy_mode", lambda: "private")
    monkeypatch.setattr(mesh_privacy_prewarm, "_current_transport_tier", lambda: "private_control_only")
    monkeypatch.setattr(mesh_privacy_prewarm, "_kickoff_hidden_transport", lambda reason: {"ok": True})
    monkeypatch.setattr(mesh_privacy_prewarm, "_register_prekeys", lambda: {"ok": True})
    monkeypatch.setattr(mesh_privacy_prewarm, "_rotate_lookup_handles", lambda: {"ok": True})
    monkeypatch.setattr(mesh_privacy_prewarm, "_prepare_gate_personas", lambda: {"ok": True})
    monkeypatch.setattr(mesh_privacy_prewarm, "_probe_rns_readiness", lambda: {"ok": True})
    monkeypatch.setattr(mesh_privacy_prewarm, "_outbox_capacity_snapshot", lambda: {"ok": True})

    result = mesh_privacy_prewarm.privacy_prewarm_service.run_scheduled_once(
        reason="scheduled_prewarm",
        now=3000.0,
    )

    assert result["current_tier"] == "private_control_only"
    assert result["required_tier"] == "private_strong"
    assert result["skipped"] is False


def test_transport_manager_respects_anonymous_prewarm_transport_gate(monkeypatch):
    from services.mesh.mesh_private_transport_manager import (
        private_transport_manager,
        reset_private_transport_manager_for_tests,
    )

    reset_private_transport_manager_for_tests()
    mesh_privacy_prewarm.reset_privacy_prewarm_for_tests()
    bootstrap_calls = []

    monkeypatch.setattr(mesh_privacy_prewarm, "_privacy_mode", lambda: "anonymous")
    monkeypatch.setattr(mesh_privacy_prewarm, "_hidden_transport_ready", lambda: False)
    monkeypatch.setattr(
        private_transport_manager,
        "_kickoff_background_bootstrap",
        lambda **kwargs: bootstrap_calls.append(kwargs) or True,
    )

    snapshot = private_transport_manager.request_warmup(
        reason="queued_dm_delivery",
        current_tier="public_degraded",
        now=1000.0,
    )

    assert bootstrap_calls == []
    assert snapshot["status"]["label"] == "Preparing private lane"
    assert snapshot["suppressed_count"] == 1
