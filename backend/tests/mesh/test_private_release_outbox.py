import copy

import main
import pytest

from services.config import get_settings
from services.mesh import (
    mesh_private_outbox,
    mesh_private_release_worker,
    mesh_private_transport_manager,
    mesh_relay_policy,
)
from services.mesh.mesh_privacy_policy import (
    PRIVATE_DELIVERY_STATUS_LABELS,
    evaluate_network_release,
)


@pytest.fixture(autouse=True)
def _isolated_private_delivery(monkeypatch):
    store = {}
    relay_policy_store = {}

    def _read_domain_json(_domain, _filename, default_factory, **_kwargs):
        payload = store.get("payload")
        if payload is None:
            return default_factory()
        return copy.deepcopy(payload)

    def _write_domain_json(_domain, _filename, payload, **_kwargs):
        store["payload"] = copy.deepcopy(payload)

    def _read_relay_policy_json(_domain, _filename, default_factory, **_kwargs):
        payload = relay_policy_store.get("payload")
        if payload is None:
            return default_factory()
        return copy.deepcopy(payload)

    def _write_relay_policy_json(_domain, _filename, payload, **_kwargs):
        relay_policy_store["payload"] = copy.deepcopy(payload)

    monkeypatch.setattr(mesh_private_outbox, "read_sensitive_domain_json", _read_domain_json)
    monkeypatch.setattr(mesh_private_outbox, "write_sensitive_domain_json", _write_domain_json)
    monkeypatch.setattr(mesh_relay_policy, "read_sensitive_domain_json", _read_relay_policy_json)
    monkeypatch.setattr(mesh_relay_policy, "write_sensitive_domain_json", _write_relay_policy_json)
    mesh_private_release_worker.reset_private_release_worker_for_tests()
    mesh_private_outbox.reset_private_delivery_outbox_for_tests()
    mesh_private_transport_manager.reset_private_transport_manager_for_tests()
    get_settings.cache_clear()
    mesh_private_outbox.private_delivery_outbox._load()
    monkeypatch.setattr(
        mesh_private_transport_manager.private_transport_manager,
        "_kickoff_background_bootstrap",
        lambda **_kwargs: False,
    )
    monkeypatch.setattr(main, "_kickoff_dm_send_transport_upgrade", lambda: None)
    monkeypatch.setattr(main, "_kickoff_private_control_transport_upgrade", lambda: None)
    yield store
    mesh_private_release_worker.reset_private_release_worker_for_tests()
    mesh_private_outbox.reset_private_delivery_outbox_for_tests()
    mesh_private_transport_manager.reset_private_transport_manager_for_tests()
    get_settings.cache_clear()


def _outbox_item(item_id: str, *, exposure: str = "") -> dict:
    return next(
        item
        for item in mesh_private_outbox.private_delivery_outbox.list_items(
            limit=50,
            exposure=exposure,
        )
        if item["id"] == item_id
    )


def test_private_dm_compose_queues_when_strong_transport_unavailable(monkeypatch):
    response = main._queue_dm_release(
        current_tier="private_control_only",
        payload={
            "msg_id": "dm-queued-1",
            "sender_id": "alice",
            "recipient_id": "bob",
            "delivery_class": "request",
            "ciphertext": "ciphertext",
            "timestamp": 1,
        },
    )

    assert response["ok"] is True
    assert response["queued"] is True
    assert response["detail"] == "Queued for private delivery"
    item = _outbox_item(response["outbox_id"])
    assert item["lane"] == "dm"
    assert item["release_state"] == "queued"
    assert item["required_tier"] == "private_strong"


def test_gate_compose_queues_when_transitional_transport_unavailable(monkeypatch):
    response = main._queue_gate_release(
        current_tier="private_control_only",
        gate_id="gate-1",
        payload={
            "gate_id": "gate-1",
            "event_id": "gate-event-1",
            "event": {"event_id": "gate-event-1", "payload": {"gate": "gate-1"}},
        },
    )

    assert response["ok"] is True
    assert response["queued"] is True
    assert response["detail"] == "Queued for private delivery"
    item = _outbox_item(response["outbox_id"])
    assert item["lane"] == "gate"
    assert item["release_state"] == "queued"
    assert item["required_tier"] == "private_strong"


def test_queued_dm_releases_automatically_once_transport_upgrades_to_private_strong(monkeypatch):
    deposit_calls = []

    monkeypatch.setattr(
        "services.wormhole_supervisor.get_transport_tier",
        lambda: "private_strong",
    )
    monkeypatch.setattr(mesh_private_release_worker, "_secure_dm_enabled", lambda: False)
    monkeypatch.setattr(mesh_private_release_worker, "_rns_private_dm_ready", lambda: False)
    monkeypatch.setattr(mesh_private_release_worker, "_maybe_apply_dm_relay_jitter", lambda: None)
    monkeypatch.setattr(
        "services.mesh.mesh_dm_relay.dm_relay.deposit",
        lambda **kwargs: deposit_calls.append(kwargs) or {"ok": True, "msg_id": kwargs["msg_id"]},
    )

    queued = main._queue_dm_release(
        current_tier="public_degraded",
        payload={
            "msg_id": "dm-upgrade-1",
            "sender_id": "alice",
            "recipient_id": "bob",
            "delivery_class": "request",
            "ciphertext": "ciphertext",
            "timestamp": 1,
        },
    )

    mesh_private_release_worker.private_release_worker.run_once()

    item = _outbox_item(queued["outbox_id"], exposure="diagnostic")
    assert len(deposit_calls) == 1
    assert item["release_state"] == "delivered"
    assert item["result"]["transport"] == "relay"
    assert item["result"]["carrier"] == "relay"


def test_queued_dm_commits_alias_rotation_only_after_private_release(monkeypatch):
    deposit_calls = []
    commit_calls = []

    monkeypatch.setattr(
        "services.wormhole_supervisor.get_transport_tier",
        lambda: "private_strong",
    )
    monkeypatch.setattr(mesh_private_release_worker, "_secure_dm_enabled", lambda: False)
    monkeypatch.setattr(mesh_private_release_worker, "_rns_private_dm_ready", lambda: False)
    monkeypatch.setattr(mesh_private_release_worker, "_maybe_apply_dm_relay_jitter", lambda: None)
    monkeypatch.setattr(
        "services.mesh.mesh_dm_relay.dm_relay.deposit",
        lambda **kwargs: deposit_calls.append(kwargs) or {"ok": True, "msg_id": kwargs["msg_id"]},
    )
    monkeypatch.setattr(
        "services.mesh.mesh_wormhole_dead_drop.commit_outbound_alias_rotation_if_present",
        lambda **kwargs: commit_calls.append(kwargs) or True,
    )

    queued = main._queue_dm_release(
        current_tier="private_strong",
        payload={
            "msg_id": "dm-alias-commit-1",
            "sender_id": "alice",
            "recipient_id": "bob",
            "delivery_class": "request",
            "ciphertext": "ciphertext-for-alias",
            "format": "mls1",
            "timestamp": 1,
        },
    )

    assert commit_calls == []
    mesh_private_release_worker.private_release_worker.run_once()

    item = _outbox_item(queued["outbox_id"], exposure="diagnostic")
    assert len(deposit_calls) == 1
    assert item["release_state"] == "delivered"
    assert commit_calls == [
        {
            "peer_id": "bob",
            "payload_format": "mls1",
            "ciphertext": "ciphertext-for-alias",
        }
    ]


def test_queued_gate_releases_automatically_once_transport_upgrades_to_private_strong(monkeypatch):
    # Hardening Rec #4: gate release floor lifted to private_strong (was
    # private_transitional); queue + release behavior unchanged.
    appended = []
    published = []

    monkeypatch.setattr(
        "services.wormhole_supervisor.get_transport_tier",
        lambda: "private_strong",
    )
    monkeypatch.setattr(
        "services.mesh.mesh_hashchain.gate_store.append",
        lambda gate_id, event: appended.append((gate_id, copy.deepcopy(event))) or dict(event),
    )
    monkeypatch.setattr(
        "services.mesh.mesh_rns.rns_bridge.publish_gate_event",
        lambda gate_id, event: published.append((gate_id, copy.deepcopy(event))),
    )

    queued = main._queue_gate_release(
        current_tier="private_control_only",
        gate_id="gate-upgrade-1",
        payload={
            "gate_id": "gate-upgrade-1",
            "event_id": "gate-event-upgrade-1",
            "event": {
                "event_id": "gate-event-upgrade-1",
                "event_type": "gate_message",
                "payload": {"gate": "gate-upgrade-1", "ciphertext": "ciphertext"},
            },
        },
    )

    mesh_private_release_worker.private_release_worker.run_once()

    item = _outbox_item(queued["outbox_id"], exposure="diagnostic")
    assert len(appended) == 1
    assert len(published) == 1
    assert item["release_state"] == "delivered"
    assert item["local_state"] == "sealed_local"
    assert item["network_state"] == "published_private"
    assert item["delivery_phase"] == {
        "local": "sealed_local",
        "network": "published_private",
        "internal": "delivered",
    }
    assert item["result"]["event_id"] == "gate-event-upgrade-1"


def test_queued_gate_publish_failure_stays_pending_without_losing_local_event(monkeypatch):
    appended = []

    monkeypatch.setattr(
        "services.wormhole_supervisor.get_transport_tier",
        lambda: "private_strong",
    )
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

    queued = main._queue_gate_release(
        current_tier="private_control_only",
        gate_id="gate-pending-1",
        payload={
            "gate_id": "gate-pending-1",
            "event_id": "gate-event-pending-1",
            "event": {
                "event_id": "gate-event-pending-1",
                "event_type": "gate_message",
                "payload": {"gate": "gate-pending-1", "ciphertext": "ciphertext"},
            },
        },
    )

    mesh_private_release_worker.private_release_worker.run_once()

    item = _outbox_item(queued["outbox_id"], exposure="diagnostic")
    assert len(appended) == 1
    assert item["release_state"] == "queued"
    assert item["canonical_release_state"] == "queued_private_release"
    assert item["local_state"] == "sealed_local"
    assert item["network_state"] == "queued_private_release"
    assert item["last_error"] == "Gate message is sealed locally and queued for private publication"


def test_no_private_release_from_private_control_only(monkeypatch):
    deposit_calls = []

    monkeypatch.setattr(
        "services.wormhole_supervisor.get_transport_tier",
        lambda: "private_control_only",
    )
    monkeypatch.setattr(mesh_private_release_worker, "_secure_dm_enabled", lambda: False)
    monkeypatch.setattr(mesh_private_release_worker, "_rns_private_dm_ready", lambda: False)
    monkeypatch.setattr(mesh_private_release_worker, "_maybe_apply_dm_relay_jitter", lambda: None)
    monkeypatch.setattr(
        "services.mesh.mesh_dm_relay.dm_relay.deposit",
        lambda **kwargs: deposit_calls.append(kwargs) or {"ok": True},
    )

    queued = main._queue_dm_release(
        current_tier="private_control_only",
        payload={
            "msg_id": "dm-control-only-1",
            "sender_id": "alice",
            "recipient_id": "bob",
            "delivery_class": "request",
            "ciphertext": "ciphertext",
            "timestamp": 1,
        },
    )

    mesh_private_release_worker.private_release_worker.run_once()

    item = _outbox_item(queued["outbox_id"])
    assert deposit_calls == []
    assert item["release_state"] == "queued"
    assert item["status"]["label"] == "Preparing private lane"


def test_no_silent_downgrade_after_queue_retry(monkeypatch):
    deposit_calls = []

    monkeypatch.setattr(
        "services.wormhole_supervisor.get_transport_tier",
        lambda: "public_degraded",
    )
    monkeypatch.setattr(mesh_private_release_worker, "_secure_dm_enabled", lambda: False)
    monkeypatch.setattr(mesh_private_release_worker, "_rns_private_dm_ready", lambda: False)
    monkeypatch.setattr(mesh_private_release_worker, "_maybe_apply_dm_relay_jitter", lambda: None)
    monkeypatch.setattr(
        "services.mesh.mesh_dm_relay.dm_relay.deposit",
        lambda **kwargs: deposit_calls.append(kwargs) or {"ok": True},
    )

    queued = main._queue_dm_release(
        current_tier="public_degraded",
        payload={
            "msg_id": "dm-retry-1",
            "sender_id": "alice",
            "recipient_id": "bob",
            "delivery_class": "request",
            "ciphertext": "ciphertext",
            "timestamp": 1,
        },
    )

    mesh_private_release_worker.private_release_worker.run_once()
    mesh_private_release_worker.private_release_worker.run_once()

    item = _outbox_item(queued["outbox_id"])
    assert deposit_calls == []
    assert item["release_state"] == "queued"
    assert item["status"]["label"] == "Preparing private lane"


def test_strict_profile_waits_for_privacy_core_attestation_before_release(monkeypatch):
    deposit_calls = []

    monkeypatch.setenv("MESH_RELEASE_PROFILE", "testnet-private")
    get_settings.cache_clear()
    monkeypatch.setattr(
        "services.wormhole_supervisor.get_transport_tier",
        lambda: "private_strong",
    )
    monkeypatch.setattr(
        "services.privacy_core_attestation.privacy_core_attestation",
        lambda *_args, **_kwargs: {
            "attestation_state": "attestation_mismatch",
            "detail": "privacy-core artifact mismatch",
        },
    )
    monkeypatch.setattr(mesh_private_release_worker, "_secure_dm_enabled", lambda: False)
    monkeypatch.setattr(mesh_private_release_worker, "_rns_private_dm_ready", lambda: False)
    monkeypatch.setattr(mesh_private_release_worker, "_maybe_apply_dm_relay_jitter", lambda: None)
    monkeypatch.setattr(
        "services.mesh.mesh_dm_relay.dm_relay.deposit",
        lambda **kwargs: deposit_calls.append(kwargs) or {"ok": True},
    )

    queued = main._queue_dm_release(
        current_tier="private_strong",
        payload={
            "msg_id": "dm-attestation-wait-1",
            "sender_id": "alice",
            "recipient_id": "bob",
            "delivery_class": "request",
            "ciphertext": "ciphertext",
            "timestamp": 1,
        },
    )

    mesh_private_release_worker.private_release_worker.run_once()

    item = _outbox_item(queued["outbox_id"], exposure="diagnostic")
    assert deposit_calls == []
    assert item["release_state"] == "queued"
    assert item["status"]["reason_code"] == "privacy_core_attestation_not_current"
    assert item["last_error"] == "attestation_mismatch"


def test_queued_artifacts_survive_restart_and_release_idempotently(monkeypatch):
    deposit_calls = []

    monkeypatch.setattr(
        "services.wormhole_supervisor.get_transport_tier",
        lambda: "private_strong",
    )
    monkeypatch.setattr(mesh_private_release_worker, "_secure_dm_enabled", lambda: False)
    monkeypatch.setattr(mesh_private_release_worker, "_rns_private_dm_ready", lambda: False)
    monkeypatch.setattr(mesh_private_release_worker, "_maybe_apply_dm_relay_jitter", lambda: None)
    monkeypatch.setattr(
        "services.mesh.mesh_dm_relay.dm_relay.deposit",
        lambda **kwargs: deposit_calls.append(kwargs) or {"ok": True, "msg_id": kwargs["msg_id"]},
    )

    queued = main._queue_dm_release(
        current_tier="public_degraded",
        payload={
            "msg_id": "dm-restart-1",
            "sender_id": "alice",
            "recipient_id": "bob",
            "delivery_class": "request",
            "ciphertext": "ciphertext",
            "timestamp": 1,
        },
    )

    mesh_private_outbox.private_delivery_outbox._load()
    mesh_private_release_worker.private_release_worker.run_once()
    mesh_private_release_worker.private_release_worker.run_once()

    item = _outbox_item(queued["outbox_id"])
    assert len(deposit_calls) == 1
    assert item["release_state"] == "delivered"
    assert mesh_private_outbox.private_delivery_outbox.has_pending() is False


def test_user_facing_status_mapping_remains_plain_language_and_stable():
    assert PRIVATE_DELIVERY_STATUS_LABELS == {
        "preparing_private_lane": "Preparing private lane",
        "queued_private_delivery": "Queued for private delivery",
        "delivered_privately": "Delivered privately",
        "weaker_privacy_approval_required": "Needs your approval to send with weaker privacy",
        "sealed_local": "Sealed locally",
        "queued_private_release": "Queued for private release",
        "publishing_private": "Publishing privately",
        "published_private": "Published privately",
        "delivered_private": "Delivered privately",
        "released_private": "Released privately",
        "release_failed": "Private release failed",
    }
    assert evaluate_network_release("dm", "public_degraded").status_label == "Preparing private lane"
    assert evaluate_network_release("dm", "private_control_only").status_label == "Queued for private delivery"
    assert evaluate_network_release("dm", "private_strong").status_label == "Delivered privately"


def test_outbox_exposes_publishing_state_without_claiming_delivery():
    item = mesh_private_outbox.private_delivery_outbox.enqueue(
        lane="dm",
        release_key="dm-publishing-1",
        payload={"msg_id": "dm-publishing-1"},
        current_tier="private_strong",
        required_tier="private_strong",
    )

    mesh_private_outbox.private_delivery_outbox.mark_releasing(
        item["id"],
        current_tier="private_strong",
    )

    exposed = _outbox_item(item["id"], exposure="diagnostic")
    assert exposed["release_state"] == "releasing"
    assert exposed["canonical_release_state"] == "publishing_private"
    assert exposed["network_state"] == "publishing_private"
    assert exposed["status"]["label"] == "Publishing privately"
    assert exposed["delivery_phase"] == {
        "local": "sealed_local",
        "network": "publishing_private",
        "internal": "releasing",
    }


def test_release_approval_window_arms_then_requires_explicit_per_item_relay_consent(monkeypatch):
    now = {"value": 100.0}
    deposit_calls = []

    monkeypatch.setenv("MESH_PRIVATE_RELEASE_APPROVAL_ENABLE", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(mesh_private_outbox, "_now", lambda: now["value"])
    monkeypatch.setattr("services.wormhole_supervisor.get_transport_tier", lambda: "private_strong")
    monkeypatch.setattr(mesh_private_release_worker, "_secure_dm_enabled", lambda: True)
    monkeypatch.setattr(mesh_private_release_worker, "_rns_private_dm_ready", lambda: False)
    monkeypatch.setattr(mesh_private_release_worker, "_anonymous_dm_hidden_transport_enforced", lambda: False)
    monkeypatch.setattr(
        mesh_private_release_worker,
        "_rns_private_dm_status",
        lambda _direct_ready: {
            "enabled": True,
            "ready": True,
            "configured_peers": 1,
            "active_peers": 0,
            "private_dm_direct_ready": False,
        },
    )
    monkeypatch.setattr(mesh_private_release_worker, "_maybe_apply_dm_relay_jitter", lambda: None)
    monkeypatch.setattr(
        "services.mesh.mesh_dm_relay.dm_relay.deposit",
        lambda **kwargs: deposit_calls.append(kwargs) or {"ok": True, "msg_id": kwargs["msg_id"]},
    )

    queued = main._queue_dm_release(
        current_tier="public_degraded",
        payload={
            "msg_id": "dm-approval-window-1",
            "sender_id": "alice",
            "recipient_id": "bob",
            "delivery_class": "request",
            "ciphertext": "ciphertext",
            "timestamp": 1,
        },
    )

    now["value"] = 100.0
    mesh_private_release_worker.private_release_worker.run_once()
    preparing = _outbox_item(queued["outbox_id"])
    assert preparing["status"]["label"] == "Preparing private lane"
    assert preparing["approval"]["required"] is False
    assert deposit_calls == []

    now["value"] = 116.0
    mesh_private_release_worker.private_release_worker.run_once()
    waiting_consent = _outbox_item(queued["outbox_id"])
    assert waiting_consent["status"]["label"] == "More private routing currently unavailable"
    assert waiting_consent["approval"]["required"] is True
    assert waiting_consent["approval"]["actions"] == [
        {"code": "wait", "label": "Keep waiting", "emphasis": "primary"},
        {"code": "relay", "label": "Send via relay", "emphasis": "secondary"},
    ]
    assert deposit_calls == []

    mesh_private_outbox.private_delivery_outbox.approve_relay_release(queued["outbox_id"])
    mesh_private_release_worker.private_release_worker.run_once()
    delivered = _outbox_item(queued["outbox_id"], exposure="diagnostic")
    assert len(deposit_calls) == 1
    assert delivered["release_state"] == "delivered"
    assert delivered["result"]["dispatch_reason"] == "private_relay_delivery"
    policy = mesh_relay_policy.relay_policy_grants_dm(
        recipient_id="bob",
        profile="dev",
        hidden_transport_effective=True,
    )
    assert policy["granted"] is True
    denied_without_hidden = mesh_relay_policy.relay_policy_grants_dm(
        recipient_id="bob",
        profile="dev",
        hidden_transport_effective=False,
    )
    assert denied_without_hidden["granted"] is False
    assert denied_without_hidden["reason_code"] == "relay_policy_hidden_transport_required"


def test_scoped_relay_policy_releases_in_background_only_when_hidden_transport_effective(monkeypatch):
    deposit_calls = []

    monkeypatch.setenv("MESH_PRIVATE_RELEASE_APPROVAL_ENABLE", "true")
    get_settings.cache_clear()
    monkeypatch.setattr("services.wormhole_supervisor.get_transport_tier", lambda: "private_strong")
    monkeypatch.setattr(mesh_private_release_worker, "_secure_dm_enabled", lambda: True)
    monkeypatch.setattr(mesh_private_release_worker, "_rns_private_dm_ready", lambda: False)
    monkeypatch.setattr(mesh_private_release_worker, "_anonymous_dm_hidden_transport_enforced", lambda: False)
    monkeypatch.setattr(mesh_private_release_worker, "_hidden_relay_transport_effective", lambda: True)
    monkeypatch.setattr(
        mesh_private_release_worker,
        "_rns_private_dm_status",
        lambda _direct_ready: {
            "enabled": True,
            "ready": True,
            "configured_peers": 1,
            "active_peers": 0,
            "private_dm_direct_ready": False,
        },
    )
    monkeypatch.setattr(mesh_private_release_worker, "_maybe_apply_dm_relay_jitter", lambda: None)
    monkeypatch.setattr(
        "services.mesh.mesh_dm_relay.dm_relay.deposit",
        lambda **kwargs: deposit_calls.append(kwargs) or {"ok": True, "msg_id": kwargs["msg_id"]},
    )
    mesh_relay_policy.grant_relay_policy(
        scope_type="dm_contact",
        scope_id="bob",
        profile="dev",
        hidden_transport_required=True,
        reason="test_scoped_hidden_policy",
    )

    queued = main._queue_dm_release(
        current_tier="public_degraded",
        payload={
            "msg_id": "dm-scoped-policy-1",
            "sender_id": "alice",
            "recipient_id": "bob",
            "delivery_class": "request",
            "ciphertext": "ciphertext",
            "timestamp": 1,
        },
    )

    mesh_private_release_worker.private_release_worker.run_once()
    delivered = _outbox_item(queued["outbox_id"], exposure="diagnostic")
    assert len(deposit_calls) == 1
    assert delivered["release_state"] == "delivered"
    assert delivered["result"]["dispatch_reason"] == "private_relay_delivery"
    assert delivered["result"]["hidden_transport_effective"] is True


def test_scoped_relay_policy_does_not_release_without_hidden_transport(monkeypatch):
    deposit_calls = []

    monkeypatch.setenv("MESH_PRIVATE_RELEASE_APPROVAL_ENABLE", "true")
    get_settings.cache_clear()
    monkeypatch.setattr("services.wormhole_supervisor.get_transport_tier", lambda: "private_strong")
    monkeypatch.setattr(mesh_private_release_worker, "_secure_dm_enabled", lambda: True)
    monkeypatch.setattr(mesh_private_release_worker, "_rns_private_dm_ready", lambda: False)
    monkeypatch.setattr(mesh_private_release_worker, "_anonymous_dm_hidden_transport_enforced", lambda: False)
    monkeypatch.setattr(mesh_private_release_worker, "_hidden_relay_transport_effective", lambda: False)
    monkeypatch.setattr(
        mesh_private_release_worker,
        "_rns_private_dm_status",
        lambda _direct_ready: {
            "enabled": True,
            "ready": True,
            "configured_peers": 1,
            "active_peers": 0,
            "private_dm_direct_ready": False,
        },
    )
    monkeypatch.setattr(mesh_private_release_worker, "_maybe_apply_dm_relay_jitter", lambda: None)
    monkeypatch.setattr(
        "services.mesh.mesh_dm_relay.dm_relay.deposit",
        lambda **kwargs: deposit_calls.append(kwargs) or {"ok": True, "msg_id": kwargs["msg_id"]},
    )
    mesh_relay_policy.grant_relay_policy(
        scope_type="dm_contact",
        scope_id="bob",
        profile="dev",
        hidden_transport_required=True,
        reason="test_scoped_hidden_policy",
    )

    queued = main._queue_dm_release(
        current_tier="public_degraded",
        payload={
            "msg_id": "dm-scoped-policy-hidden-required-1",
            "sender_id": "alice",
            "recipient_id": "bob",
            "delivery_class": "request",
            "ciphertext": "ciphertext",
            "timestamp": 1,
        },
    )

    mesh_private_release_worker.private_release_worker.run_once()
    waiting = _outbox_item(queued["outbox_id"])
    assert deposit_calls == []
    assert waiting["release_state"] == "queued"
    assert waiting["status"]["label"] == "Preparing private lane"


def test_anonymous_mode_release_worker_keeps_dm_queued_until_hidden_transport_is_ready(monkeypatch):
    deposit_calls = []
    direct_calls = []

    monkeypatch.setenv("MESH_PRIVATE_RELEASE_APPROVAL_ENABLE", "true")
    get_settings.cache_clear()
    monkeypatch.setattr("services.wormhole_supervisor.get_transport_tier", lambda: "private_strong")
    monkeypatch.setattr(mesh_private_release_worker, "_secure_dm_enabled", lambda: True)
    monkeypatch.setattr(mesh_private_release_worker, "_rns_private_dm_ready", lambda: True)
    monkeypatch.setattr(mesh_private_release_worker, "_anonymous_dm_hidden_transport_requested", lambda: True)
    monkeypatch.setattr(mesh_private_release_worker, "_anonymous_dm_hidden_transport_enforced", lambda: False)
    monkeypatch.setattr(mesh_private_release_worker, "_hidden_relay_transport_effective", lambda: False)
    monkeypatch.setattr(
        "services.mesh.mesh_dm_relay.dm_relay.deposit",
        lambda **kwargs: deposit_calls.append(kwargs) or {"ok": True, "msg_id": kwargs["msg_id"]},
    )
    monkeypatch.setattr(
        "services.mesh.mesh_rns.rns_bridge.send_private_dm",
        lambda **kwargs: direct_calls.append(kwargs) or True,
    )

    queued = main._queue_dm_release(
        current_tier="private_strong",
        payload={
            "msg_id": "dm-anon-queued-1",
            "sender_id": "alice",
            "recipient_id": "bob",
            "delivery_class": "request",
            "ciphertext": "ciphertext",
            "timestamp": 1,
        },
    )

    mesh_private_release_worker.private_release_worker.run_once()
    waiting = _outbox_item(queued["outbox_id"])

    assert deposit_calls == []
    assert direct_calls == []
    assert waiting["release_state"] == "queued"
    assert waiting["status"]["reason_code"] == "anonymous_mode_waiting_for_hidden_transport"
    assert waiting["status"]["label"] == "Preparing private lane"
    assert waiting["network_state"] == "queued_private_release"


def test_keep_waiting_suppresses_relay_prompt_until_private_lane_recovers(monkeypatch):
    now = {"value": 200.0}

    monkeypatch.setenv("MESH_PRIVATE_RELEASE_APPROVAL_ENABLE", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(mesh_private_outbox, "_now", lambda: now["value"])
    monkeypatch.setattr("services.wormhole_supervisor.get_transport_tier", lambda: "private_strong")
    monkeypatch.setattr(mesh_private_release_worker, "_secure_dm_enabled", lambda: True)
    monkeypatch.setattr(mesh_private_release_worker, "_rns_private_dm_ready", lambda: False)
    monkeypatch.setattr(mesh_private_release_worker, "_anonymous_dm_hidden_transport_enforced", lambda: False)
    monkeypatch.setattr(
        mesh_private_release_worker,
        "_rns_private_dm_status",
        lambda _direct_ready: {
            "enabled": True,
            "ready": True,
            "configured_peers": 1,
            "active_peers": 0,
            "private_dm_direct_ready": False,
        },
    )
    monkeypatch.setattr(mesh_private_release_worker, "_maybe_apply_dm_relay_jitter", lambda: None)

    queued = main._queue_dm_release(
        current_tier="public_degraded",
        payload={
            "msg_id": "dm-wait-choice-1",
            "sender_id": "alice",
            "recipient_id": "bob",
            "delivery_class": "request",
            "ciphertext": "ciphertext",
            "timestamp": 1,
        },
    )

    now["value"] = 200.0
    mesh_private_release_worker.private_release_worker.run_once()
    now["value"] = 216.0
    mesh_private_release_worker.private_release_worker.run_once()
    armed = _outbox_item(queued["outbox_id"])
    assert armed["approval"]["required"] is True

    mesh_private_outbox.private_delivery_outbox.continue_waiting_for_release(queued["outbox_id"])
    now["value"] = 230.0
    mesh_private_release_worker.private_release_worker.run_once()
    waiting = _outbox_item(queued["outbox_id"])
    assert waiting["status"]["label"] == "Preparing private lane"
    assert waiting["approval"]["required"] is False


def test_release_approval_flag_off_preserves_existing_relay_fallback(monkeypatch):
    deposit_calls = []

    monkeypatch.setenv("MESH_PRIVATE_RELEASE_APPROVAL_ENABLE", "false")
    get_settings.cache_clear()
    monkeypatch.setattr("services.wormhole_supervisor.get_transport_tier", lambda: "private_strong")
    monkeypatch.setattr(mesh_private_release_worker, "_secure_dm_enabled", lambda: True)
    monkeypatch.setattr(mesh_private_release_worker, "_rns_private_dm_ready", lambda: False)
    monkeypatch.setattr(mesh_private_release_worker, "_anonymous_dm_hidden_transport_enforced", lambda: False)
    monkeypatch.setattr(
        mesh_private_release_worker,
        "_rns_private_dm_status",
        lambda _direct_ready: {
            "enabled": True,
            "ready": True,
            "configured_peers": 1,
            "active_peers": 0,
            "private_dm_direct_ready": False,
        },
    )
    monkeypatch.setattr(mesh_private_release_worker, "_maybe_apply_dm_relay_jitter", lambda: None)
    monkeypatch.setattr(
        "services.mesh.mesh_dm_relay.dm_relay.deposit",
        lambda **kwargs: deposit_calls.append(kwargs) or {"ok": True, "msg_id": kwargs["msg_id"]},
    )

    queued = main._queue_dm_release(
        current_tier="public_degraded",
        payload={
            "msg_id": "dm-approval-flag-off-1",
            "sender_id": "alice",
            "recipient_id": "bob",
            "delivery_class": "request",
            "ciphertext": "ciphertext",
            "timestamp": 1,
        },
    )

    mesh_private_release_worker.private_release_worker.run_once()

    delivered = _outbox_item(queued["outbox_id"], exposure="diagnostic")
    assert len(deposit_calls) == 1
    assert delivered["release_state"] == "delivered"
    assert delivered["result"]["dispatch_reason"] == "private_relay_delivery"
    assert (
        mesh_private_outbox.private_delivery_outbox.release_approval_state(queued["outbox_id"])["approval_required"]
        is False
    )
