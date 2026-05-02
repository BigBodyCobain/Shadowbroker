def test_repeated_warmup_requests_coalesce(monkeypatch):
    from services.mesh.mesh_private_transport_manager import (
        private_transport_manager,
        reset_private_transport_manager_for_tests,
    )

    reset_private_transport_manager_for_tests()
    bootstrap_calls = []
    monkeypatch.setattr(
        private_transport_manager,
        "_kickoff_background_bootstrap",
        lambda **kwargs: bootstrap_calls.append(kwargs) or True,
    )

    first = private_transport_manager.request_warmup(
        reason="queued_dm_delivery",
        current_tier="public_degraded",
        now=100.0,
    )
    second = private_transport_manager.request_warmup(
        reason="queued_gate_delivery",
        current_tier="public_degraded",
        now=101.0,
    )

    assert len(bootstrap_calls) == 1
    assert first["status"]["label"] == "Preparing private lane"
    assert second["status"]["label"] == "Preparing private lane"
    assert set(second["reasons"]) == {"queued_dm_delivery", "queued_gate_delivery"}


def test_cooldown_suppresses_bootstrap_spam(monkeypatch):
    from services.mesh.mesh_private_transport_manager import (
        private_transport_manager,
        reset_private_transport_manager_for_tests,
    )

    reset_private_transport_manager_for_tests()
    bootstrap_calls = []
    monkeypatch.setattr(
        private_transport_manager,
        "_kickoff_background_bootstrap",
        lambda **kwargs: bootstrap_calls.append(kwargs) or True,
    )

    private_transport_manager.request_warmup(
        reason="queued_dm_delivery",
        current_tier="public_degraded",
        now=100.0,
    )
    snapshot = private_transport_manager.request_warmup(
        reason="queued_dm_delivery",
        current_tier="public_degraded",
        now=102.0,
    )

    assert len(bootstrap_calls) == 1
    assert snapshot["suppressed_count"] == 1


def test_ready_state_stops_unnecessary_warmup_attempts(monkeypatch):
    from services.mesh.mesh_private_transport_manager import (
        private_transport_manager,
        reset_private_transport_manager_for_tests,
    )

    reset_private_transport_manager_for_tests()
    bootstrap_calls = []
    monkeypatch.setattr(
        private_transport_manager,
        "_kickoff_background_bootstrap",
        lambda **kwargs: bootstrap_calls.append(kwargs) or True,
    )

    snapshot = private_transport_manager.request_warmup(
        reason="queued_gate_delivery",
        current_tier="private_strong",
        now=100.0,
    )

    assert bootstrap_calls == []
    assert snapshot["status"]["label"] == "Private lane ready"
    assert snapshot["attempt_count"] == 0


def test_readiness_state_transitions_are_deterministic(monkeypatch):
    from services.mesh.mesh_private_transport_manager import (
        private_transport_manager,
        reset_private_transport_manager_for_tests,
    )

    reset_private_transport_manager_for_tests()
    monkeypatch.setattr(
        private_transport_manager,
        "_kickoff_background_bootstrap",
        lambda **kwargs: True,
    )

    preparing = private_transport_manager.request_warmup(
        reason="queued_dm_delivery",
        current_tier="public_degraded",
        now=100.0,
    )
    retrying = private_transport_manager.observe_state(
        current_tier="public_degraded",
        now=106.0,
    )
    second_attempt = private_transport_manager.request_warmup(
        reason="queued_dm_delivery",
        current_tier="public_degraded",
        now=106.0,
    )
    ready = private_transport_manager.observe_state(
        current_tier="private_strong",
        now=107.0,
    )

    assert preparing["status"]["label"] == "Preparing private lane"
    assert retrying["status"]["label"] == "Retrying private lane"
    assert second_attempt["status"]["label"] == "Retrying private lane"
    assert ready["status"]["label"] == "Private lane ready"


def test_plain_language_readiness_state_mapping_remains_stable():
    from services.mesh.mesh_privacy_policy import (
        PRIVATE_LANE_READINESS_LABELS,
        private_lane_readiness_status,
    )

    assert PRIVATE_LANE_READINESS_LABELS["preparing_private_lane"] == "Preparing private lane"
    assert PRIVATE_LANE_READINESS_LABELS["private_lane_ready"] == "Private lane ready"
    assert PRIVATE_LANE_READINESS_LABELS["retrying_private_lane"] == "Retrying private lane"
    assert PRIVATE_LANE_READINESS_LABELS["private_lane_unavailable"] == "Private lane unavailable"
    assert (
        PRIVATE_LANE_READINESS_LABELS["weaker_privacy_approval_required"]
        == "Needs your approval to send with weaker privacy"
    )
    assert private_lane_readiness_status("retrying_private_lane")["label"] == "Retrying private lane"


def test_pending_outbox_on_startup_resume_requests_warmup(monkeypatch):
    import main

    calls = []
    started = {"value": 0}
    woken = {"value": 0}

    monkeypatch.setattr(
        main.private_delivery_outbox,
        "pending_items",
        lambda: [
            {"lane": "gate", "required_tier": "private_transitional"},
            {"lane": "dm", "required_tier": "private_strong"},
        ],
    )
    monkeypatch.setattr(
        main.private_release_worker,
        "ensure_started",
        lambda: started.__setitem__("value", started["value"] + 1) or True,
    )
    monkeypatch.setattr(
        main.private_release_worker,
        "wake",
        lambda: woken.__setitem__("value", woken["value"] + 1),
    )
    monkeypatch.setattr(
        main.private_transport_manager,
        "request_warmup",
        lambda **kwargs: calls.append(kwargs) or {"status": {"label": "Preparing private lane"}},
    )

    main._resume_private_delivery_background_work(
        current_tier="public_degraded",
        reason="startup_resume",
    )

    assert started["value"] == 1
    assert woken["value"] == 1
    assert calls == [
        {
            "reason": "startup_resume",
            "current_tier": "public_degraded",
            "required_tier": "private_strong",
        }
    ]


def test_dm_surface_open_triggers_warmup(monkeypatch):
    import main

    calls = []

    monkeypatch.setattr(
        main.private_transport_manager,
        "request_warmup",
        lambda **kwargs: calls.append(kwargs) or {"status": {"label": "Preparing private lane"}},
    )
    main._request_private_surface_warmup(
        path="/api/wormhole/dm/compose",
        method="POST",
        current_tier="public_degraded",
    )

    assert calls == [
        {
            "reason": "dm_surface_open",
            "current_tier": "public_degraded",
            "required_tier": "private_control_only",
        }
    ]


def test_gate_surface_open_triggers_warmup(monkeypatch):
    import main

    calls = []

    monkeypatch.setattr(
        main.private_transport_manager,
        "request_warmup",
        lambda **kwargs: calls.append(kwargs) or {"status": {"label": "Preparing private lane"}},
    )
    main._request_private_surface_warmup(
        path="/api/mesh/gate/infonet/messages",
        method="GET",
        current_tier="public_degraded",
    )

    assert calls == [
        {
            "reason": "gate_surface_open",
            "current_tier": "public_degraded",
            "required_tier": "private_control_only",
        }
    ]
