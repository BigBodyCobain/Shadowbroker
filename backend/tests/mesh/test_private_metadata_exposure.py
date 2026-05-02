from __future__ import annotations

import asyncio
import copy
import logging

import main
from services.mesh import (
    mesh_dm_relay,
    mesh_private_outbox,
    mesh_private_release_worker,
    mesh_private_transport_manager,
    mesh_wormhole_identity,
    mesh_wormhole_prekey,
    mesh_wormhole_sender_token,
)
from services.config import get_settings
from services.mesh import mesh_secure_storage


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


def _json_request(path: str, body: dict):
    import json
    from starlette.requests import Request

    payload = json.dumps(body).encode("utf-8")
    sent = {"value": False}

    async def receive():
        if sent["value"]:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent["value"] = True
        return {"type": "http.request", "body": payload, "more_body": False}

    return Request(
        {
            "type": "http",
            "headers": [(b"content-type", b"application/json")],
            "client": ("test", 12345),
            "method": "POST",
            "path": path.split("?", 1)[0],
            "query_string": path.split("?", 1)[1].encode("utf-8") if "?" in path else b"",
        },
        receive,
    )


def _patch_in_memory_outbox(monkeypatch):
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
    return store


def test_ordinary_private_delivery_listing_omits_dispatch_path_metadata(monkeypatch):
    _patch_in_memory_outbox(monkeypatch)
    item = mesh_private_outbox.private_delivery_outbox.enqueue(
        lane="dm",
        release_key="dm-meta-1",
        payload={"msg_id": "dm-meta-1", "peer_id": "bob"},
        current_tier="private_strong",
        required_tier="private_strong",
    )
    mesh_private_outbox.private_delivery_outbox.mark_delivered(
        item["id"],
        current_tier="private_strong",
        result={
            "ok": True,
            "selected_transport": "relay",
            "selected_carrier": "relay",
            "dispatch_reason": "private_relay_delivery",
            "hidden_transport_effective": False,
            "msg_id": "dm-meta-1",
        },
    )

    ordinary = mesh_private_outbox.private_delivery_outbox.list_items(limit=10)[0]

    assert ordinary["id"] == item["id"]
    assert ordinary["lane"] == "dm"
    assert ordinary["result"] == {}
    assert ordinary["release_key"] == ""
    assert ordinary["meta"] == {
        "msg_id": "",
        "event_id": "",
        "gate_id": "",
        "peer_id": "",
    }
    assert ordinary["last_error"] == ""


def test_diagnostic_private_delivery_listing_preserves_dispatch_path_metadata(monkeypatch):
    _patch_in_memory_outbox(monkeypatch)
    item = mesh_private_outbox.private_delivery_outbox.enqueue(
        lane="dm",
        release_key="dm-meta-2",
        payload={"msg_id": "dm-meta-2", "peer_id": "bob"},
        current_tier="private_strong",
        required_tier="private_strong",
    )
    mesh_private_outbox.private_delivery_outbox.mark_delivered(
        item["id"],
        current_tier="private_strong",
        result={
            "ok": True,
            "selected_transport": "relay",
            "selected_carrier": "relay",
            "dispatch_reason": "private_relay_delivery",
            "hidden_transport_effective": False,
            "msg_id": "dm-meta-2",
        },
    )

    diagnostic = mesh_private_outbox.private_delivery_outbox.list_items(
        limit=10,
        exposure="diagnostic",
    )[0]

    assert diagnostic["release_key"] == "dm-meta-2"
    assert diagnostic["meta"]["msg_id"] == "dm-meta-2"
    assert diagnostic["meta"]["peer_id"] == "bob"
    assert diagnostic["result"]["selected_transport"] == "relay"
    assert diagnostic["result"]["selected_carrier"] == "relay"
    assert diagnostic["result"]["dispatch_reason"] == "private_relay_delivery"
    assert diagnostic["result"]["hidden_transport_effective"] is False


def test_authenticated_wormhole_status_defaults_to_ordinary_private_delivery_summary(monkeypatch):
    _patch_in_memory_outbox(monkeypatch)
    mesh_private_outbox.private_delivery_outbox.enqueue(
        lane="dm",
        release_key="dm-status-1",
        payload={"msg_id": "dm-status-1", "peer_id": "bob"},
        current_tier="private_control_only",
        required_tier="private_strong",
    )
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        main,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": False, "rns_ready": False},
    )
    monkeypatch.setattr(main, "_current_private_lane_tier", lambda *_args, **_kwargs: "private_control_only")

    result = asyncio.run(main.api_wormhole_status(_request("/api/wormhole/status")))

    item = result["private_delivery"]["items"][0]
    assert item["lane"] == "dm"
    assert item["release_key"] == ""
    assert item["meta"] == {
        "msg_id": "",
        "event_id": "",
        "gate_id": "",
        "peer_id": "",
    }
    assert item["result"] == {}


def test_authenticated_wormhole_status_can_request_diagnostic_private_delivery_summary(monkeypatch):
    _patch_in_memory_outbox(monkeypatch)
    mesh_private_outbox.private_delivery_outbox.enqueue(
        lane="dm",
        release_key="dm-status-2",
        payload={"msg_id": "dm-status-2", "peer_id": "bob"},
        current_tier="private_control_only",
        required_tier="private_strong",
    )
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        main,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": False, "rns_ready": False},
    )
    monkeypatch.setattr(main, "_current_private_lane_tier", lambda *_args, **_kwargs: "private_control_only")

    result = asyncio.run(
        main.api_wormhole_status(_request("/api/wormhole/status?exposure=diagnostic"))
    )

    item = result["private_delivery"]["items"][0]
    assert item["release_key"] == "dm-status-2"
    assert item["meta"]["msg_id"] == "dm-status-2"
    assert item["meta"]["peer_id"] == "bob"


def test_dm_pubkey_lookup_token_ordinary_response_omits_resolved_agent_id(monkeypatch):
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (False, "no"))
    monkeypatch.setattr(main, "_is_debug_test_request", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        "services.mesh.mesh_dm_relay.dm_relay.get_dh_key_by_lookup",
        lambda _lookup_token: ({"dh_pub": "pub", "dh_algo": "X25519"}, "peer-123"),
    )

    result = asyncio.run(main.dm_get_pubkey(_request("/api/mesh/dm/pubkey"), lookup_token="invite-handle"))

    assert result["ok"] is True
    assert result["lookup_mode"] == "invite_lookup_handle"
    assert "agent_id" not in result


def test_dm_pubkey_lookup_token_diagnostic_response_exposes_resolved_agent_id(monkeypatch):
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        "services.mesh.mesh_dm_relay.dm_relay.get_dh_key_by_lookup",
        lambda _lookup_token: ({"dh_pub": "pub", "dh_algo": "X25519"}, "peer-123"),
    )

    result = asyncio.run(
        main.dm_get_pubkey(
            _request("/api/mesh/dm/pubkey?exposure=diagnostic"),
            lookup_token="invite-handle",
        )
    )

    assert result["ok"] is True
    assert result["agent_id"] == "peer-123"


def test_prekey_bundle_lookup_token_ordinary_response_omits_resolved_agent_id(monkeypatch):
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (False, "no"))
    monkeypatch.setattr(main, "_is_debug_test_request", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        main,
        "fetch_dm_prekey_bundle",
        lambda **_kwargs: {
            "ok": True,
            "agent_id": "peer-456",
            "lookup_mode": "invite_lookup_handle",
            "trust_fingerprint": "aa" * 16,
            "bundle": {"identity_dh_pub_key": "pub"},
        },
    )

    result = asyncio.run(
        main.dm_get_prekey_bundle(
            _request("/api/mesh/dm/prekey-bundle"),
            lookup_token="invite-handle",
        )
    )

    assert result["ok"] is True
    assert result["lookup_mode"] == "invite_lookup_handle"
    assert "agent_id" not in result
    assert result["trust_fingerprint"] == "aa" * 16


def test_short_lived_sender_token_expires_and_cannot_be_reused_indefinitely(monkeypatch):
    current = {"now": 1_700_000_000}

    monkeypatch.setattr(mesh_wormhole_sender_token.time, "time", lambda: current["now"])
    monkeypatch.setattr(
        mesh_wormhole_sender_token,
        "read_wormhole_identity",
        lambda: {
            "bootstrapped": True,
            "node_id": "!sb_sender",
            "public_key": "pub",
            "public_key_algo": "Ed25519",
        },
    )
    monkeypatch.setattr(mesh_wormhole_sender_token, "bootstrap_wormhole_identity", lambda: None)

    issued = mesh_wormhole_sender_token.issue_wormhole_dm_sender_token(
        recipient_id="peer-789",
        delivery_class="request",
        ttl_seconds=600,
    )

    assert issued["ok"] is True
    assert issued["expires_at"] - current["now"] == 90

    current["now"] = int(issued["expires_at"]) + 1
    consumed = mesh_wormhole_sender_token.consume_wormhole_dm_sender_token(
        sender_token=str(issued["sender_token"]),
        recipient_id="peer-789",
        delivery_class="request",
    )

    assert consumed == {"ok": False, "detail": "sender_token expired"}


def test_legacy_lookup_logs_redact_stable_agent_identifier(monkeypatch, caplog):
    main._WARNED_LEGACY_DM_PUBKEY_LOOKUPS.clear()

    with caplog.at_level(logging.WARNING):
        main._warn_legacy_dm_pubkey_lookup("Peer-Secret-123")

    assert "Peer-Secret-123" not in caplog.text
    assert "peer:" in caplog.text


def test_new_lookup_handles_age_out_on_tighter_default_schedule(tmp_path, monkeypatch):
    from services.mesh import mesh_wormhole_persona
    from services.mesh import mesh_wormhole_prekey as mesh_wormhole_prekey_module

    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    monkeypatch.setattr(mesh_wormhole_persona, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_persona, "PERSONA_FILE", tmp_path / "wormhole_persona.json")
    monkeypatch.setattr(mesh_wormhole_prekey_module, "register_wormhole_prekey_bundle", lambda: {"ok": True})
    now = {"value": 1_700_000_000}
    monkeypatch.setattr(mesh_wormhole_identity.time, "time", lambda: now["value"])
    get_settings.cache_clear()

    try:
        exported = mesh_wormhole_identity.export_wormhole_dm_invite()
        handle = str(exported["invite"]["payload"]["prekey_lookup_handle"] or "")

        assert handle in mesh_wormhole_identity.get_prekey_lookup_handles()

        now["value"] += (3 * 86400) + 1

        assert handle not in mesh_wormhole_identity.get_prekey_lookup_handles()
    finally:
        get_settings.cache_clear()


def test_bounded_use_lookup_handles_cannot_be_reused_indefinitely(tmp_path, monkeypatch):
    import time

    monkeypatch.setattr(mesh_dm_relay, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_dm_relay, "RELAY_FILE", tmp_path / "dm_relay.json")
    relay = mesh_dm_relay.DMRelay()
    agent_id = "peer-bounded"
    relay._prekey_bundles[agent_id] = {
        "bundle": {"identity_dh_pub_key": "pub"},
        "updated_at": int(time.time()),
    }
    relay.register_prekey_lookup_alias("bounded-handle", agent_id, max_uses=2)

    first, first_id = relay.get_prekey_bundle_by_lookup("bounded-handle")
    second, second_id = relay.get_prekey_bundle_by_lookup("bounded-handle")
    third, third_id = relay.get_prekey_bundle_by_lookup("bounded-handle")

    assert first is not None and first_id == agent_id
    assert second is not None and second_id == agent_id
    assert third is None and third_id == ""


def test_ordinary_lookup_failures_are_normalized_for_invite_handles(monkeypatch):
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (False, "no"))
    monkeypatch.setattr(main, "_is_debug_test_request", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        "services.mesh.mesh_dm_relay.dm_relay.get_dh_key_by_lookup",
        lambda _lookup_token: (None, ""),
    )

    result = asyncio.run(main.dm_get_pubkey(_request("/api/mesh/dm/pubkey"), lookup_token="invite-handle"))

    assert result == {"ok": False, "detail": "Invite lookup unavailable"}


def test_diagnostic_lookup_failures_preserve_specific_reason(monkeypatch):
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(main, "_is_debug_test_request", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        "services.mesh.mesh_dm_relay.dm_relay.get_dh_key_by_lookup",
        lambda _lookup_token: (None, ""),
    )

    result = asyncio.run(
        main.dm_get_pubkey(
            _request("/api/mesh/dm/pubkey?exposure=diagnostic"),
            lookup_token="invite-handle",
        )
    )

    assert result == {"ok": False, "detail": "Agent not found or has no DH key", "lookup_mode": "invite_lookup_handle"}


def test_ordinary_dm_count_omits_mailbox_source_detail_while_diagnostic_retains_it(client, monkeypatch):
    monkeypatch.setattr(main, "_secure_dm_enabled", lambda: False)
    monkeypatch.setattr(main, "_legacy_dm_get_allowed", lambda: True)
    monkeypatch.setattr(mesh_dm_relay.dm_relay, "count_legacy", lambda **_kwargs: 7)
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(main, "_transport_tier_is_sufficient", lambda *_args, **_kwargs: True)

    ordinary = asyncio.run(main.dm_count(_request("/api/mesh/dm/count?agent_token=tok1"), agent_token="tok1"))
    diagnostic = asyncio.run(
        main.dm_count(
            _request("/api/mesh/dm/count?agent_token=tok1&exposure=diagnostic"),
            agent_token="tok1",
        )
    )

    assert ordinary == {"ok": True, "count": 20}
    assert diagnostic["ok"] is True
    assert diagnostic["count"] == 20
    assert diagnostic["source_counts"] == {"legacy": 7, "exact_total": 7}
    assert diagnostic["token_count"] == 1


def test_ordinary_dm_poll_errors_are_generic_while_diagnostic_retains_reason(monkeypatch):
    monkeypatch.setattr("services.wormhole_supervisor.get_transport_tier", lambda: "private_strong")
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (False, "no"))
    monkeypatch.setattr(main, "_verify_dm_mailbox_request", lambda **_kwargs: (False, "nonce replay rejected", {}))

    ordinary = asyncio.run(
        main.dm_poll_secure(
            _json_request(
                "/api/mesh/dm/poll",
                {
                    "agent_id": "peer-1",
                    "mailbox_claims": [],
                    "nonce": "n",
                    "timestamp": 1,
                    "protocol_version": "infonet/2",
                    "transport_lock": "private_strong",
                },
            )
        )
    )

    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))
    diagnostic = asyncio.run(
        main.dm_poll_secure(
            _json_request(
                "/api/mesh/dm/poll?exposure=diagnostic",
                {
                    "agent_id": "peer-1",
                    "mailbox_claims": [],
                    "nonce": "n",
                    "timestamp": 1,
                    "protocol_version": "infonet/2",
                    "transport_lock": "private_strong",
                },
            )
        )
    )

    assert ordinary["detail"] == "Mailbox unavailable"
    assert diagnostic["detail"] == "nonce replay rejected"


def test_secure_dm_count_keeps_ordinary_shape_coarse_while_diagnostic_retains_mailbox_detail(monkeypatch):
    monkeypatch.setattr("services.wormhole_supervisor.get_transport_tier", lambda: "private_strong")
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (False, "no"))
    monkeypatch.setattr(
        main,
        "_verify_dm_mailbox_request",
        lambda **_kwargs: (True, "ok", {"mailbox_claims": [{"type": "requests", "token": "tok"}]}),
    )
    monkeypatch.setattr(mesh_dm_relay.dm_relay, "consume_nonce", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        main,
        "_anonymous_dm_hidden_transport_enforced",
        lambda: True,
    )
    monkeypatch.setattr(
        "services.mesh.mesh_hashchain.infonet.validate_and_set_sequence",
        lambda *_args, **_kwargs: (True, "ok"),
    )
    monkeypatch.setattr(mesh_dm_relay.dm_relay, "claim_mailbox_keys", lambda *_args, **_kwargs: ["k1"])
    monkeypatch.setattr(mesh_dm_relay.dm_relay, "claim_message_ids", lambda *_args, **_kwargs: {"a", "b"})

    ordinary = asyncio.run(
        main.dm_count_secure(
            _json_request(
                "/api/mesh/dm/count",
                {
                    "agent_id": "peer-1",
                    "mailbox_claims": [{"type": "requests", "token": "tok"}],
                    "nonce": "n1",
                    "timestamp": 1,
                    "sequence": 1,
                    "protocol_version": "infonet/2",
                    "transport_lock": "private_strong",
                },
            )
        )
    )

    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))
    diagnostic = asyncio.run(
        main.dm_count_secure(
            _json_request(
                "/api/mesh/dm/count?exposure=diagnostic",
                {
                    "agent_id": "peer-1",
                    "mailbox_claims": [{"type": "requests", "token": "tok"}],
                    "nonce": "n2",
                    "timestamp": 1,
                    "sequence": 2,
                    "protocol_version": "infonet/2",
                    "transport_lock": "private_strong",
                },
            )
        )
    )

    assert ordinary == {"ok": True, "count": 5}
    assert diagnostic["ok"] is True
    assert diagnostic["count"] == 5
    assert diagnostic["source_counts"] == {"relay": 2, "direct": 0, "exact_total": 2}
    assert diagnostic["mailbox_claim_count"] == 1


def test_secure_dm_poll_keeps_ordinary_shape_coarse_while_diagnostic_retains_mailbox_detail(monkeypatch):
    monkeypatch.setattr("services.wormhole_supervisor.get_transport_tier", lambda: "private_strong")
    payload = {
        "agent_id": "peer-1",
        "mailbox_claims": [{"type": "requests", "token": "tok"}],
        "nonce": "n1",
        "timestamp": 1,
        "sequence": 1,
        "protocol_version": "infonet/2",
        "transport_lock": "private_strong",
    }
    message = {
        "sender_id": "sender_token:reqtok",
        "ciphertext": "cipher",
        "timestamp": 1.0,
        "msg_id": "m1",
        "delivery_class": "request",
        "sender_seal": "",
        "format": "dm1",
        "session_welcome": "",
    }

    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (False, "no"))
    monkeypatch.setattr(
        main,
        "_verify_dm_mailbox_request",
        lambda **_kwargs: (True, "ok", {"mailbox_claims": payload["mailbox_claims"]}),
    )
    monkeypatch.setattr(mesh_dm_relay.dm_relay, "consume_nonce", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        "services.mesh.mesh_hashchain.infonet.validate_and_set_sequence",
        lambda *_args, **_kwargs: (True, "ok"),
    )
    monkeypatch.setattr(mesh_dm_relay.dm_relay, "claim_mailbox_keys", lambda *_args, **_kwargs: ["k1"])
    monkeypatch.setattr(mesh_dm_relay.dm_relay, "collect_claims", lambda *_args, **_kwargs: ([message], False))
    monkeypatch.setattr(main, "_anonymous_dm_hidden_transport_enforced", lambda: True)

    ordinary = asyncio.run(main.dm_poll_secure(_json_request("/api/mesh/dm/poll", payload)))

    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))
    diagnostic = asyncio.run(
        main.dm_poll_secure(_json_request("/api/mesh/dm/poll?exposure=diagnostic", dict(payload, nonce="n2", sequence=2)))
    )

    assert ordinary == {"ok": True, "messages": [message], "count": 1, "has_more": False}
    assert diagnostic["ok"] is True
    assert diagnostic["count"] == 1
    assert diagnostic["source_counts"] == {"relay": 1, "direct": 0, "returned": 1}
    assert diagnostic["mailbox_claim_count"] == 1


def test_legacy_prekey_lookup_logs_redact_stable_agent_identifier(monkeypatch, caplog):
    mesh_wormhole_prekey._WARNED_LEGACY_PREKEY_LOOKUPS.clear()

    with caplog.at_level(logging.WARNING):
        mesh_wormhole_prekey._warn_legacy_prekey_lookup("Peer-Secret-456")

    assert "Peer-Secret-456" not in caplog.text
    assert "peer:" in caplog.text
