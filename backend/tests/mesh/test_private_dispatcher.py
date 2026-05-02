import copy

from services.mesh.mesh_private_dispatcher import attempt_private_release


def test_dispatcher_chooses_dm_direct_private_path_when_allowed_and_ready(monkeypatch):
    direct_calls = []

    monkeypatch.setattr(
        "services.mesh.mesh_rns.rns_bridge.send_private_dm",
        lambda **kwargs: direct_calls.append(copy.deepcopy(kwargs)) or True,
    )

    result = attempt_private_release(
        lane="dm",
        current_tier="private_strong",
        payload={
            "msg_id": "dm-direct-1",
            "sender_id": "alice",
            "recipient_id": "bob",
            "delivery_class": "request",
            "ciphertext": "ciphertext",
            "timestamp": 1,
        },
        secure_dm_enabled=lambda: True,
        rns_private_dm_ready=lambda: True,
        anonymous_dm_hidden_transport_enforced=lambda: False,
        apply_dm_relay_jitter=lambda: None,
    )

    assert result["ok"] is True
    assert result["selected_transport"] == "reticulum"
    assert result["selected_carrier"] == "reticulum_direct"
    assert result["dispatch_reason"] == "direct_private_transport_ready"
    assert result["hidden_transport_effective"] is False
    assert result["no_acceptable_path"] is False
    assert len(direct_calls) == 1


def test_dispatcher_chooses_dm_relay_when_direct_path_unavailable_but_lane_floor_is_satisfied(monkeypatch):
    deposit_calls = []

    monkeypatch.setattr(
        "services.mesh.mesh_dm_relay.dm_relay.deposit",
        lambda **kwargs: deposit_calls.append(copy.deepcopy(kwargs)) or {"ok": True, "msg_id": kwargs["msg_id"]},
    )

    result = attempt_private_release(
        lane="dm",
        current_tier="private_strong",
        payload={
            "msg_id": "dm-relay-1",
            "sender_id": "alice",
            "recipient_id": "bob",
            "delivery_class": "request",
            "ciphertext": "ciphertext",
            "timestamp": 1,
        },
        secure_dm_enabled=lambda: True,
        rns_private_dm_ready=lambda: False,
        anonymous_dm_hidden_transport_enforced=lambda: False,
        relay_hidden_transport_effective=lambda: False,
        apply_dm_relay_jitter=lambda: None,
    )

    assert result["ok"] is True
    assert result["selected_transport"] == "relay"
    assert result["selected_carrier"] == "relay"
    assert result["dispatch_reason"] == "private_relay_delivery"
    assert result["no_acceptable_path"] is False
    assert len(deposit_calls) == 1


def test_dispatcher_does_not_release_dm_below_private_strong():
    result = attempt_private_release(
        lane="dm",
        current_tier="private_control_only",
        payload={"msg_id": "dm-too-weak"},
    )

    assert result["ok"] is False
    assert result["no_acceptable_path"] is True
    assert result["policy_reason_code"] == "dm_release_waiting_for_private_strong"
    assert result["required_tier"] == "private_strong"


def test_dispatcher_preserves_anonymous_hidden_transport_behavior(monkeypatch):
    direct_calls = []
    deposit_calls = []

    monkeypatch.setattr(
        "services.mesh.mesh_rns.rns_bridge.send_private_dm",
        lambda **kwargs: direct_calls.append(copy.deepcopy(kwargs)) or True,
    )
    monkeypatch.setattr(
        "services.mesh.mesh_dm_relay.dm_relay.deposit",
        lambda **kwargs: deposit_calls.append(copy.deepcopy(kwargs)) or {"ok": True, "msg_id": kwargs["msg_id"]},
    )

    result = attempt_private_release(
        lane="dm",
        current_tier="private_strong",
        payload={
            "msg_id": "dm-anon-1",
            "sender_id": "alice",
            "recipient_id": "bob",
            "delivery_class": "request",
            "ciphertext": "ciphertext",
            "timestamp": 1,
        },
        secure_dm_enabled=lambda: True,
        rns_private_dm_ready=lambda: True,
        anonymous_dm_hidden_transport_enforced=lambda: True,
        anonymous_dm_hidden_transport_requested=lambda: True,
        apply_dm_relay_jitter=lambda: None,
    )

    assert result["ok"] is True
    assert result["selected_transport"] == "relay"
    assert result["selected_carrier"] == "relay"
    assert result["dispatch_reason"] == "anonymous_hidden_transport_requires_relay"
    assert result["hidden_transport_effective"] is True
    assert len(direct_calls) == 0
    assert len(deposit_calls) == 1


def test_dispatcher_keeps_anonymous_dm_queued_until_hidden_transport_is_ready(monkeypatch):
    direct_calls = []
    deposit_calls = []

    monkeypatch.setattr(
        "services.mesh.mesh_rns.rns_bridge.send_private_dm",
        lambda **kwargs: direct_calls.append(copy.deepcopy(kwargs)) or True,
    )
    monkeypatch.setattr(
        "services.mesh.mesh_dm_relay.dm_relay.deposit",
        lambda **kwargs: deposit_calls.append(copy.deepcopy(kwargs)) or {"ok": True, "msg_id": kwargs["msg_id"]},
    )

    result = attempt_private_release(
        lane="dm",
        current_tier="private_strong",
        payload={
            "msg_id": "dm-anon-wait-1",
            "sender_id": "alice",
            "recipient_id": "bob",
            "delivery_class": "request",
            "ciphertext": "ciphertext",
            "timestamp": 1,
        },
        secure_dm_enabled=lambda: True,
        rns_private_dm_ready=lambda: True,
        anonymous_dm_hidden_transport_enforced=lambda: False,
        anonymous_dm_hidden_transport_requested=lambda: True,
        apply_dm_relay_jitter=lambda: None,
    )

    assert result["ok"] is False
    assert result["dispatch_reason"] == "anonymous_mode_waiting_for_hidden_transport"
    assert result["network_state"] == "queued_private_release"
    assert result["hidden_transport_effective"] is False
    assert direct_calls == []
    assert deposit_calls == []


def test_dispatcher_requires_explicit_relay_approval_before_silent_dm_relay(monkeypatch):
    result = attempt_private_release(
        lane="dm",
        current_tier="private_strong",
        payload={
            "msg_id": "dm-approval-needed-1",
            "sender_id": "alice",
            "recipient_id": "bob",
            "delivery_class": "request",
            "ciphertext": "ciphertext",
            "timestamp": 1,
        },
        secure_dm_enabled=lambda: True,
        rns_private_dm_ready=lambda: False,
        anonymous_dm_hidden_transport_enforced=lambda: False,
        apply_dm_relay_jitter=lambda: None,
        relay_consent_granted=False,
    )

    assert result["ok"] is False
    assert result["relay_approval_required"] is True
    assert result["fallback_reason"] == "rns_transport_disabled"
    assert result["dispatch_reason"] == "relay_user_approval_required"


def test_dispatcher_routes_gate_release_through_expected_private_path(monkeypatch):
    appended = []
    published = []

    monkeypatch.setattr(
        "services.mesh.mesh_hashchain.gate_store.append",
        lambda gate_id, event: appended.append((gate_id, copy.deepcopy(event))) or dict(event),
    )
    monkeypatch.setattr(
        "services.mesh.mesh_rns.rns_bridge.publish_gate_event",
        lambda gate_id, event: published.append((gate_id, copy.deepcopy(event))),
    )

    result = attempt_private_release(
        lane="gate",
        current_tier="private_strong",
        payload={
            "gate_id": "gate-1",
            "event_id": "evt-1",
            "event": {"event_id": "evt-1", "event_type": "gate_message"},
        },
    )

    assert result["ok"] is True
    assert result["selected_transport"] == "reticulum"
    assert result["selected_carrier"] == "rns_gate_publish"
    assert result["dispatch_reason"] == "gate_private_rns_publish_after_tor_unavailable"
    assert result["no_acceptable_path"] is False
    assert len(appended) == 1
    assert len(published) == 1


def test_dispatcher_prefers_tor_for_gate_release_when_onion_push_ready(monkeypatch):
    from services.mesh.mesh_router import TransportResult, mesh_router

    appended = []
    tor_calls = []
    rns_calls = []

    monkeypatch.setattr(
        "services.mesh.mesh_hashchain.gate_store.append",
        lambda gate_id, event: appended.append((gate_id, copy.deepcopy(event))) or dict(event),
    )
    monkeypatch.setattr(mesh_router.tor_arti, "can_reach", lambda _envelope: True)
    monkeypatch.setattr(
        mesh_router.tor_arti,
        "send",
        lambda envelope, _credentials: tor_calls.append(envelope) or TransportResult(
            True,
            "tor_arti",
            "Delivered to 1/1 peers via Tor",
        ),
    )
    monkeypatch.setattr(
        "services.mesh.mesh_rns.rns_bridge.publish_gate_event",
        lambda gate_id, event: rns_calls.append((gate_id, copy.deepcopy(event))),
    )

    result = attempt_private_release(
        lane="gate",
        current_tier="private_strong",
        payload={
            "gate_id": "gate-1",
            "event_id": "evt-1",
            "event": {"event_id": "evt-1", "event_type": "gate_message"},
        },
    )

    assert result["ok"] is True
    assert result["selected_transport"] == "tor_arti"
    assert result["selected_carrier"] == "tor_arti_peer_push"
    assert result["dispatch_reason"] == "gate_private_tor_publish"
    assert result["hidden_transport_effective"] is True
    assert result["network_state"] == "published_private"
    assert len(appended) == 1
    assert len(tor_calls) == 1
    assert rns_calls == []


def test_dispatcher_keeps_gate_release_pending_when_private_publish_fails(monkeypatch):
    appended = []

    monkeypatch.setattr(
        "services.mesh.mesh_hashchain.gate_store.append",
        lambda gate_id, event: appended.append((gate_id, copy.deepcopy(event))) or dict(event),
    )

    def _publish_fails(_gate_id, _event):
        raise RuntimeError("rns unavailable")

    monkeypatch.setattr(
        "services.mesh.mesh_rns.rns_bridge.publish_gate_event",
        _publish_fails,
    )

    result = attempt_private_release(
        lane="gate",
        current_tier="private_strong",
        payload={
            "gate_id": "gate-1",
            "event_id": "evt-1",
            "event": {"event_id": "evt-1", "event_type": "gate_message"},
        },
    )

    assert result["ok"] is False
    assert result["selected_transport"] == "gate_private_store"
    assert result["selected_carrier"] == "gate_store_only"
    assert result["dispatch_reason"] == "gate_private_publish_pending"
    assert result["no_acceptable_path"] is False
    assert result["local_state"] == "sealed_local"
    assert result["network_state"] == "queued_private_release"
    assert result["published"] is False
    assert len(appended) == 1


def test_dispatcher_returns_explicit_no_acceptable_path_result_when_unsupported_lane():
    result = attempt_private_release(
        lane="unknown_lane",
        current_tier="private_strong",
        payload={},
    )

    assert result["ok"] is False
    assert result["no_acceptable_path"] is True
    assert result["dispatch_reason"] == "unsupported_private_release_lane"


def test_release_worker_uses_dispatcher_instead_of_lane_specific_release_helpers(monkeypatch):
    import main
    from services.mesh import mesh_private_outbox, mesh_private_release_worker
    from services.config import get_settings

    store = {}
    monkeypatch.setenv("MESH_PRIVATE_RELEASE_APPROVAL_ENABLE", "false")
    get_settings.cache_clear()

    def _read_domain_json(_domain, _filename, default_factory, **_kwargs):
        payload = store.get("payload")
        if payload is None:
            return default_factory()
        return copy.deepcopy(payload)

    def _write_domain_json(_domain, _filename, payload, **_kwargs):
        store["payload"] = copy.deepcopy(payload)

    monkeypatch.setattr(mesh_private_outbox, "read_domain_json", _read_domain_json)
    monkeypatch.setattr(mesh_private_outbox, "write_domain_json", _write_domain_json)
    mesh_private_outbox.reset_private_delivery_outbox_for_tests()
    mesh_private_release_worker.reset_private_release_worker_for_tests()
    mesh_private_outbox.private_delivery_outbox._load()
    monkeypatch.setattr("services.wormhole_supervisor.get_transport_tier", lambda: "private_strong")

    dispatch_calls = []
    monkeypatch.setattr(
        mesh_private_release_worker,
        "attempt_private_release",
        lambda **kwargs: dispatch_calls.append(copy.deepcopy(kwargs))
        or {
            "ok": True,
            "lane": kwargs["lane"],
            "selected_transport": "relay",
            "selected_carrier": "relay",
            "dispatch_reason": "private_relay_delivery",
            "hidden_transport_effective": False,
            "no_acceptable_path": False,
            "transport": "relay",
            "carrier": "relay",
            "detail": "Delivered privately",
            "msg_id": str((kwargs.get("payload") or {}).get("msg_id", "") or ""),
        },
    )

    queued = main._queue_dm_release(
        current_tier="public_degraded",
        payload={
            "msg_id": "dm-worker-dispatch-1",
            "sender_id": "alice",
            "recipient_id": "bob",
            "delivery_class": "request",
            "ciphertext": "ciphertext",
            "timestamp": 1,
        },
    )

    mesh_private_release_worker.private_release_worker.run_once()

    item = next(
        item
        for item in mesh_private_outbox.private_delivery_outbox.list_items(
            limit=10,
            exposure="diagnostic",
        )
        if item["id"] == queued["outbox_id"]
    )
    assert len(dispatch_calls) == 1
    assert dispatch_calls[0]["lane"] == "dm"
    assert item["release_state"] == "delivered"
    assert item["result"]["dispatch_reason"] == "private_relay_delivery"


def test_structured_dispatch_results_remain_stable(monkeypatch):
    monkeypatch.setattr(
        "services.mesh.mesh_dm_relay.dm_relay.deposit",
        lambda **kwargs: {"ok": True, "msg_id": kwargs["msg_id"]},
    )

    result = attempt_private_release(
        lane="dm",
        current_tier="private_strong",
        payload={
            "msg_id": "dm-structured-1",
            "sender_id": "alice",
            "recipient_id": "bob",
            "delivery_class": "request",
            "ciphertext": "ciphertext",
            "timestamp": 1,
        },
        secure_dm_enabled=lambda: False,
        rns_private_dm_ready=lambda: False,
        anonymous_dm_hidden_transport_enforced=lambda: False,
        apply_dm_relay_jitter=lambda: None,
    )

    assert result.keys() >= {
        "ok",
        "lane",
        "selected_transport",
        "selected_carrier",
        "dispatch_reason",
        "hidden_transport_effective",
        "no_acceptable_path",
        "detail",
        "transport",
        "carrier",
    }


def test_dispatcher_records_reason_when_rns_transport_disabled(monkeypatch):
    from services.mesh import mesh_metrics, mesh_private_dispatcher, mesh_router

    mesh_metrics.reset()
    mesh_router.mesh_router.tier_events.clear()
    monkeypatch.setattr(mesh_private_dispatcher, "_LAST_ANONYMOUS_HIDDEN_STATE", False)
    monkeypatch.setattr(
        mesh_private_dispatcher,
        "_rns_private_dm_status",
        lambda _direct_ready: {
            "enabled": False,
            "ready": False,
            "configured_peers": 0,
            "active_peers": 0,
            "private_dm_direct_ready": False,
        },
    )
    monkeypatch.setattr(
        "services.mesh.mesh_dm_relay.dm_relay.deposit",
        lambda **kwargs: {"ok": True, "msg_id": kwargs["msg_id"]},
    )

    result = attempt_private_release(
        lane="dm",
        current_tier="private_strong",
        payload={
            "msg_id": "dm-reason-disabled-1",
            "sender_id": "alice",
            "recipient_id": "bob",
            "delivery_class": "request",
            "ciphertext": "ciphertext",
            "timestamp": 1,
        },
        secure_dm_enabled=lambda: True,
        rns_private_dm_ready=lambda: False,
        anonymous_dm_hidden_transport_enforced=lambda: False,
        relay_hidden_transport_effective=lambda: False,
        apply_dm_relay_jitter=lambda: None,
    )

    fallback = next(event for event in reversed(mesh_router.mesh_router.tier_events) if event["event"] == "fallback")
    snapshot = mesh_metrics.snapshot()

    assert result["ok"] is True
    assert result["selected_transport"] == "relay"
    assert result["dispatch_reason"] == "private_relay_delivery"
    assert fallback["reason"] == mesh_private_dispatcher.DMFallbackReason.RNS_TRANSPORT_DISABLED
    assert snapshot["counters"]["silent_degradations"] == 1


def test_dispatcher_records_reason_when_rns_link_is_down(monkeypatch):
    from services.mesh import mesh_private_dispatcher, mesh_router

    mesh_router.mesh_router.tier_events.clear()
    monkeypatch.setattr(mesh_private_dispatcher, "_LAST_ANONYMOUS_HIDDEN_STATE", False)
    monkeypatch.setattr(
        mesh_private_dispatcher,
        "_rns_private_dm_status",
        lambda _direct_ready: {
            "enabled": True,
            "ready": False,
            "configured_peers": 2,
            "active_peers": 1,
            "private_dm_direct_ready": False,
        },
    )
    monkeypatch.setattr(
        "services.mesh.mesh_dm_relay.dm_relay.deposit",
        lambda **kwargs: {"ok": True, "msg_id": kwargs["msg_id"]},
    )

    attempt_private_release(
        lane="dm",
        current_tier="private_strong",
        payload={
            "msg_id": "dm-reason-linkdown-1",
            "sender_id": "alice",
            "recipient_id": "bob",
            "delivery_class": "request",
            "ciphertext": "ciphertext",
            "timestamp": 1,
        },
        secure_dm_enabled=lambda: True,
        rns_private_dm_ready=lambda: False,
        anonymous_dm_hidden_transport_enforced=lambda: False,
        apply_dm_relay_jitter=lambda: None,
    )

    fallback = next(event for event in reversed(mesh_router.mesh_router.tier_events) if event["event"] == "fallback")

    assert fallback["reason"] == mesh_private_dispatcher.DMFallbackReason.RNS_LINK_DOWN


def test_dispatcher_records_reason_when_peer_is_unknown(monkeypatch):
    from services.mesh import mesh_private_dispatcher, mesh_router

    mesh_router.mesh_router.tier_events.clear()
    monkeypatch.setattr(mesh_private_dispatcher, "_LAST_ANONYMOUS_HIDDEN_STATE", False)
    monkeypatch.setattr(
        mesh_private_dispatcher,
        "_rns_private_dm_status",
        lambda _direct_ready: {
            "enabled": True,
            "ready": True,
            "configured_peers": 0,
            "active_peers": 0,
            "private_dm_direct_ready": False,
        },
    )
    monkeypatch.setattr(
        "services.mesh.mesh_dm_relay.dm_relay.deposit",
        lambda **kwargs: {"ok": True, "msg_id": kwargs["msg_id"]},
    )

    attempt_private_release(
        lane="dm",
        current_tier="private_strong",
        payload={
            "msg_id": "dm-reason-peerunknown-1",
            "sender_id": "alice",
            "recipient_id": "bob",
            "delivery_class": "request",
            "ciphertext": "ciphertext",
            "timestamp": 1,
        },
        secure_dm_enabled=lambda: True,
        rns_private_dm_ready=lambda: False,
        anonymous_dm_hidden_transport_enforced=lambda: False,
        apply_dm_relay_jitter=lambda: None,
    )

    fallback = next(event for event in reversed(mesh_router.mesh_router.tier_events) if event["event"] == "fallback")

    assert fallback["reason"] == mesh_private_dispatcher.DMFallbackReason.RNS_PEER_UNKNOWN


def test_dispatcher_records_reason_when_ready_peers_are_offline(monkeypatch):
    from services.mesh import mesh_metrics, mesh_private_dispatcher, mesh_router

    mesh_metrics.reset()
    mesh_router.mesh_router.tier_events.clear()
    monkeypatch.setattr(mesh_private_dispatcher, "_LAST_ANONYMOUS_HIDDEN_STATE", False)
    monkeypatch.setattr(
        mesh_private_dispatcher,
        "_rns_private_dm_status",
        lambda _direct_ready: {
            "enabled": True,
            "ready": True,
            "configured_peers": 3,
            "active_peers": 0,
            "private_dm_direct_ready": False,
        },
    )
    monkeypatch.setattr(
        "services.mesh.mesh_dm_relay.dm_relay.deposit",
        lambda **kwargs: {"ok": True, "msg_id": kwargs["msg_id"]},
    )

    attempt_private_release(
        lane="dm",
        current_tier="private_strong",
        payload={
            "msg_id": "dm-reason-offline-1",
            "sender_id": "alice",
            "recipient_id": "bob",
            "delivery_class": "request",
            "ciphertext": "ciphertext",
            "timestamp": 1,
        },
        secure_dm_enabled=lambda: True,
        rns_private_dm_ready=lambda: False,
        anonymous_dm_hidden_transport_enforced=lambda: False,
        apply_dm_relay_jitter=lambda: None,
    )

    fallback = next(event for event in reversed(mesh_router.mesh_router.tier_events) if event["event"] == "fallback")

    assert fallback["reason"] == mesh_private_dispatcher.DMFallbackReason.RNS_PEER_OFFLINE


def test_dispatcher_records_reason_when_direct_send_fails(monkeypatch):
    from services.mesh import mesh_metrics, mesh_private_dispatcher, mesh_router

    mesh_metrics.reset()
    mesh_router.mesh_router.tier_events.clear()
    monkeypatch.setattr(mesh_private_dispatcher, "_LAST_ANONYMOUS_HIDDEN_STATE", False)
    monkeypatch.setattr(
        mesh_private_dispatcher,
        "_rns_private_dm_status",
        lambda _direct_ready: {
            "enabled": True,
            "ready": True,
            "configured_peers": 2,
            "active_peers": 1,
            "private_dm_direct_ready": True,
        },
    )
    monkeypatch.setattr(
        "services.mesh.mesh_rns.rns_bridge.send_private_dm",
        lambda **_kwargs: False,
    )
    monkeypatch.setattr(
        "services.mesh.mesh_dm_relay.dm_relay.deposit",
        lambda **kwargs: {"ok": True, "msg_id": kwargs["msg_id"]},
    )

    attempt_private_release(
        lane="dm",
        current_tier="private_strong",
        payload={
            "msg_id": "dm-reason-sendfail-1",
            "sender_id": "alice",
            "recipient_id": "bob",
            "delivery_class": "request",
            "ciphertext": "ciphertext",
            "timestamp": 1,
        },
        secure_dm_enabled=lambda: True,
        rns_private_dm_ready=lambda: True,
        anonymous_dm_hidden_transport_enforced=lambda: False,
        apply_dm_relay_jitter=lambda: None,
    )

    fallback = next(event for event in reversed(mesh_router.mesh_router.tier_events) if event["event"] == "fallback")

    assert fallback["reason"] == mesh_private_dispatcher.DMFallbackReason.RNS_SEND_FAILED_UNKNOWN
    assert isinstance(fallback["reason"], mesh_private_dispatcher.DMFallbackReason)


def test_dispatcher_records_anonymous_hidden_reason_without_sampling_degradation(monkeypatch):
    from services.mesh import mesh_metrics, mesh_private_dispatcher, mesh_router

    mesh_metrics.reset()
    mesh_router.mesh_router.tier_events.clear()
    monkeypatch.setattr(mesh_private_dispatcher, "_LAST_ANONYMOUS_HIDDEN_STATE", False)
    monkeypatch.setattr(
        "services.mesh.mesh_dm_relay.dm_relay.deposit",
        lambda **kwargs: {"ok": True, "msg_id": kwargs["msg_id"]},
    )

    result = attempt_private_release(
        lane="dm",
        current_tier="private_strong",
        payload={
            "msg_id": "dm-reason-anon-1",
            "sender_id": "alice",
            "recipient_id": "bob",
            "delivery_class": "request",
            "ciphertext": "ciphertext",
            "timestamp": 1,
        },
        secure_dm_enabled=lambda: True,
        rns_private_dm_ready=lambda: True,
        anonymous_dm_hidden_transport_enforced=lambda: True,
        apply_dm_relay_jitter=lambda: None,
    )

    fallback = next(event for event in reversed(mesh_router.mesh_router.tier_events) if event["event"] == "fallback")
    snapshot = mesh_metrics.snapshot()

    assert result["dispatch_reason"] == "anonymous_hidden_transport_requires_relay"
    assert fallback["reason"] == mesh_private_dispatcher.DMFallbackReason.ANONYMOUS_MODE_FORCED_RELAY
    assert snapshot["counters"].get("silent_degradations", 0) == 0


def test_dispatcher_records_user_approved_relay_without_sampling_degradation(monkeypatch):
    from services.mesh import mesh_metrics, mesh_private_dispatcher, mesh_router

    mesh_metrics.reset()
    mesh_router.mesh_router.tier_events.clear()
    monkeypatch.setattr(mesh_private_dispatcher, "_LAST_ANONYMOUS_HIDDEN_STATE", False)
    monkeypatch.setattr(
        mesh_private_dispatcher,
        "_rns_private_dm_status",
        lambda _direct_ready: {
            "enabled": True,
            "ready": True,
            "configured_peers": 1,
            "active_peers": 0,
            "private_dm_direct_ready": False,
        },
    )
    monkeypatch.setattr(
        "services.mesh.mesh_dm_relay.dm_relay.deposit",
        lambda **kwargs: {"ok": True, "msg_id": kwargs["msg_id"]},
    )

    result = attempt_private_release(
        lane="dm",
        current_tier="private_strong",
        payload={
            "msg_id": "dm-approved-relay-1",
            "sender_id": "alice",
            "recipient_id": "bob",
            "delivery_class": "request",
            "ciphertext": "ciphertext",
            "timestamp": 1,
        },
        secure_dm_enabled=lambda: True,
        rns_private_dm_ready=lambda: False,
        anonymous_dm_hidden_transport_enforced=lambda: False,
        relay_hidden_transport_effective=lambda: False,
        apply_dm_relay_jitter=lambda: None,
        relay_consent_granted=True,
        relay_consent_explicit=True,
    )

    fallback = next(event for event in reversed(mesh_router.mesh_router.tier_events) if event["event"] == "fallback")
    snapshot = mesh_metrics.snapshot()

    assert result["ok"] is True
    assert result["dispatch_reason"] == "private_relay_delivery"
    assert fallback["reason"] == mesh_private_dispatcher.DMFallbackReason.RELAY_APPROVED_BY_USER
    assert snapshot["counters"].get("silent_degradations", 0) == 0
