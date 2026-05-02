from __future__ import annotations

import asyncio
import copy

import pytest

import main
from services.mesh import (
    mesh_private_outbox,
    mesh_private_release_worker,
    mesh_private_transport_manager,
)


def _request(path: str):
    from starlette.requests import Request

    return Request(
        {
            "type": "http",
            "headers": [],
            "client": ("test", 12345),
            "method": "GET",
            "path": path.split("?", 1)[0],
            "query_string": path.split("?", 1)[1].encode("utf-8") if "?" in path else b"",
        }
    )


@pytest.fixture(autouse=True)
def _isolated_private_delivery(monkeypatch):
    store = {}

    def _read_domain_json(_domain, _filename, default_factory, **_kwargs):
        payload = store.get("payload")
        if payload is None:
            return default_factory()
        return copy.deepcopy(payload)

    def _write_domain_json(_domain, _filename, payload, **_kwargs):
        store["payload"] = copy.deepcopy(payload)

    monkeypatch.setattr(mesh_private_outbox, "read_sensitive_domain_json", _read_domain_json)
    monkeypatch.setattr(mesh_private_outbox, "write_sensitive_domain_json", _write_domain_json)
    mesh_private_release_worker.reset_private_release_worker_for_tests()
    mesh_private_outbox.reset_private_delivery_outbox_for_tests()
    mesh_private_transport_manager.reset_private_transport_manager_for_tests()
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


def test_no_release_occurs_before_durable_outbox_commit(monkeypatch):
    writes = {"count": 0}
    deposit_calls = []

    def _write_then_fail(_domain, _filename, payload, **_kwargs):
        writes["count"] += 1
        if writes["count"] == 1:
            raise OSError("durable queue commit failed")

    monkeypatch.setattr(mesh_private_outbox, "write_sensitive_domain_json", _write_then_fail)
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

    with pytest.raises(OSError, match="durable queue commit failed"):
        main._queue_dm_release(
            current_tier="public_degraded",
            payload={
                "msg_id": "dm-commit-fail-1",
                "sender_id": "alice",
                "recipient_id": "bob",
                "delivery_class": "request",
                "ciphertext": "ciphertext",
                "timestamp": 1,
            },
        )

    mesh_private_release_worker.private_release_worker.run_once()

    assert mesh_private_outbox.private_delivery_outbox.has_pending() is False
    assert mesh_private_outbox.private_delivery_outbox.list_items(limit=10) == []
    assert deposit_calls == []


def test_repeated_worker_runs_and_restart_do_not_double_deliver(monkeypatch):
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
            "msg_id": "dm-adversarial-restart-1",
            "sender_id": "alice",
            "recipient_id": "bob",
            "delivery_class": "request",
            "ciphertext": "ciphertext",
            "timestamp": 1,
        },
    )

    mesh_private_release_worker.private_release_worker.run_once()
    mesh_private_release_worker.private_release_worker.run_once()

    mesh_private_release_worker.reset_private_release_worker_for_tests()
    mesh_private_outbox.reset_private_delivery_outbox_for_tests()
    mesh_private_outbox.private_delivery_outbox._load()
    mesh_private_release_worker.private_release_worker.run_once()

    items = mesh_private_outbox.private_delivery_outbox.list_items(limit=10, exposure="diagnostic")
    item = next(item for item in items if item["id"] == queued["outbox_id"])

    assert len(deposit_calls) == 1
    assert item["release_state"] == "delivered"
    assert mesh_private_outbox.private_delivery_outbox.has_pending() is False


def test_ordinary_status_diagnostic_probe_remains_coarse_when_unauthenticated(monkeypatch):
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (False, "no"))
    monkeypatch.setattr(main, "_is_debug_test_request", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        main,
        "get_wormhole_state",
        lambda: {
            "installed": True,
            "configured": True,
            "running": True,
            "ready": True,
            "arti_ready": True,
            "rns_ready": True,
        },
    )

    result = asyncio.run(main.api_wormhole_status(_request("/api/wormhole/status?exposure=diagnostic")))

    assert result == {
        "installed": True,
        "configured": True,
        "running": True,
        "ready": True,
    }


def test_malformed_persisted_outbox_state_does_not_widen_ordinary_view(_isolated_private_delivery):
    _isolated_private_delivery["payload"] = {
        "version": 1,
        "updated_at": 1,
        "items": [
            {
                "id": "outbox-malicious-1",
                "lane": "dm",
                "release_key": "msg-malicious-1",
                "payload": {"msg_id": "msg-malicious-1", "peer_id": "bob"},
                "status": {"code": "delivered_privately", "label": "Delivered privately"},
                "required_tier": "private_strong",
                "current_tier": "private_strong",
                "release_state": "delivered",
                "attempts": 1,
                "created_at": 1.0,
                "updated_at": 1.0,
                "released_at": 1.0,
                "last_error": "sensitive internal error",
                "result": {
                    "selected_transport": "relay",
                    "selected_carrier": "relay",
                    "dispatch_reason": "private_relay_delivery",
                    "hidden_transport_effective": False,
                    "payload": {"ciphertext": "secret"},
                    "event": {"node_id": "secret-node"},
                    "msg_id": "msg-malicious-1",
                },
            }
        ],
    }
    mesh_private_outbox.reset_private_delivery_outbox_for_tests()
    mesh_private_outbox.private_delivery_outbox._load()

    ordinary = mesh_private_outbox.private_delivery_outbox.list_items(limit=10)[0]

    assert ordinary["release_key"] == ""
    assert ordinary["result"] == {}
    assert ordinary["last_error"] == ""
    assert ordinary["meta"] == {
        "msg_id": "",
        "event_id": "",
        "gate_id": "",
        "peer_id": "",
    }
