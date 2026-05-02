from types import SimpleNamespace


def test_dead_drop_read_grace_accepts_cleartext_and_redacted(monkeypatch):
    from services.mesh import mesh_wormhole_contacts
    from services.mesh.mesh_wormhole_dead_drop import dead_drop_redact_label

    raw_contacts = {
        "peer-clear": {
            "sharedAlias": "dmx_clear",
            "dmIdentityId": "node-clear",
        },
        "peer-redacted": {
            "sharedAlias": "dmx_redacted",
            "dmIdentityId": dead_drop_redact_label("node-redacted"),
        },
    }
    monkeypatch.setattr(mesh_wormhole_contacts, "read_secure_json", lambda *_args, **_kwargs: raw_contacts)
    monkeypatch.setattr(mesh_wormhole_contacts, "write_secure_json", lambda *_args, **_kwargs: None)

    contacts = mesh_wormhole_contacts.list_wormhole_dm_contacts()

    assert contacts["peer-clear"]["dmIdentityId"] == dead_drop_redact_label("node-clear")
    assert contacts["peer-redacted"]["dmIdentityId"] == dead_drop_redact_label("node-redacted")


def test_silent_degradations_increment_on_relay_fallback(monkeypatch):
    from services.mesh import mesh_dm_relay, mesh_private_dispatcher, mesh_router
    from services.mesh import mesh_metrics

    mesh_metrics.reset()
    mesh_router.mesh_router.tier_events.clear()
    monkeypatch.setattr(mesh_private_dispatcher, "_LAST_ANONYMOUS_HIDDEN_STATE", None)
    monkeypatch.setattr(
        mesh_dm_relay.dm_relay,
        "deposit",
        lambda **_kwargs: {"ok": True, "detail": "Delivered privately", "msg_id": "msg-1"},
    )

    result = mesh_private_dispatcher._dispatch_dm(
        {
            "sender_id": "alice",
            "recipient_id": "bob",
            "delivery_class": "shared",
            "recipient_token": "shared",
            "ciphertext": "ciphertext",
            "format": "mls1",
            "msg_id": "msg-1",
            "timestamp": 1,
        },
        secure_dm_enabled=lambda: True,
        rns_private_dm_ready=lambda: False,
        anonymous_dm_hidden_transport_enforced=lambda: False,
        apply_dm_relay_jitter=lambda: None,
    )

    snapshot = mesh_metrics.snapshot()

    assert result["ok"] is True
    assert snapshot["counters"]["silent_degradations"] == 1
    assert any(event["event"] == "fallback" for event in mesh_router.mesh_router.tier_events)


def test_session_restore_failures_increment_when_restored_session_invalidated(monkeypatch):
    from services.mesh import mesh_dm_mls, mesh_metrics

    mesh_metrics.reset()
    monkeypatch.setattr(mesh_dm_mls, "_session_expired_result", lambda *_args, **_kwargs: {"ok": False})
    monkeypatch.setattr(mesh_dm_mls, "_clear_rust_dm_state", lambda: None)

    mesh_dm_mls._invalidate_restored_session("alias-a", "alias-b")

    assert mesh_metrics.snapshot()["counters"]["session_restore_failures"] == 1


def test_envelope_policy_transitions_increment_only_on_change(monkeypatch):
    from services.mesh import mesh_metrics, mesh_reputation

    mesh_metrics.reset()
    monkeypatch.setattr(mesh_reputation.gate_manager, "_save", lambda: None)
    mesh_reputation.gate_manager.gates["sprint0-gate"] = {"envelope_policy": "envelope_disabled"}

    ok, _detail = mesh_reputation.gate_manager.set_envelope_policy("sprint0-gate", "envelope_recovery")
    assert ok is True
    assert mesh_metrics.snapshot()["counters"]["envelope_policy_transitions"] == 1

    ok, _detail = mesh_reputation.gate_manager.set_envelope_policy("sprint0-gate", "envelope_recovery")
    assert ok is True
    assert mesh_metrics.snapshot()["counters"]["envelope_policy_transitions"] == 1


def test_envelope_policy_transitions_count_each_distinct_change(monkeypatch):
    from services.mesh import mesh_metrics, mesh_reputation

    mesh_metrics.reset()
    monkeypatch.setattr(mesh_reputation.gate_manager, "_save", lambda: None)
    mesh_reputation.gate_manager.gates["sprint4-gate"] = {"envelope_policy": "envelope_disabled"}

    ok, _detail = mesh_reputation.gate_manager.set_envelope_policy("sprint4-gate", "envelope_recovery")
    assert ok is True
    ok, _detail = mesh_reputation.gate_manager.set_envelope_policy(
        "sprint4-gate",
        "envelope_always",
        acknowledge_recovery_risk=True,
    )
    assert ok is True

    assert mesh_metrics.snapshot()["counters"]["envelope_policy_transitions"] == 2


def test_ban_rotation_latency_timer_records_samples():
    from services.mesh import mesh_metrics

    mesh_metrics.reset()
    mesh_metrics.observe_ms("ban_rotation_latency_ms", 42.5)
    snapshot = mesh_metrics.snapshot()

    assert snapshot["timers"]["ban_rotation_latency_ms"]["count"] == 1.0
    assert snapshot["timers"]["ban_rotation_latency_ms"]["last_ms"] == 42.5


def test_cover_emits_increment_when_cover_traffic_is_built(monkeypatch):
    from services.mesh import mesh_metrics, mesh_rns

    mesh_metrics.reset()
    monkeypatch.setattr(
        mesh_rns,
        "get_settings",
        lambda: SimpleNamespace(
            MESH_RNS_COVER_SIZE=64,
            MESH_RNS_MAX_PAYLOAD=8192,
            MESH_RNS_DANDELION_HOPS=1,
            MESH_RNS_DANDELION_DELAY_MS=0,
        ),
    )
    monkeypatch.setattr(mesh_rns.rns_bridge, "_pick_stem_peer", lambda: None)
    monkeypatch.setattr(mesh_rns.rns_bridge, "_send_diffuse", lambda *_args, **_kwargs: None)

    mesh_rns.rns_bridge._send_cover_traffic()

    assert mesh_metrics.snapshot()["counters"]["cover_emits"] == 1


def test_tier_event_ring_buffer_is_bounded_under_heavy_churn():
    from services.mesh.mesh_router import MeshRouter

    router = MeshRouter()
    for index in range(10_000):
        router.record_tier_event(
            "tier_change",
            previous_tier=f"tier-{index}",
            current_tier=f"tier-{index + 1}",
            detail=f"event-{index}",
        )

    assert len(router.tier_events) <= 128
    assert router.tier_events[0]["detail"] != "event-0"
    assert router.tier_events[-1]["detail"] == "event-9999"
