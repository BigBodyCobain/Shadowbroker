import asyncio
import base64
import json
import copy
import time

import pytest
from starlette.requests import Request

import main
from services.config import get_settings
from services.mesh import (
    mesh_gate_legacy_migration,
    mesh_private_outbox,
    mesh_private_release_worker,
    mesh_private_transport_manager,
    mesh_relay_policy,
    mesh_signed_events,
)
from services.mesh.mesh_protocol import build_signed_context
from services.mesh.mesh_private_dispatcher import attempt_private_release
from services.privacy_claims import (
    privacy_claims_snapshot,
    privacy_status_surface_chip,
    review_export_snapshot,
    rollout_controls_snapshot,
    rollout_readiness_snapshot,
)


@pytest.fixture(autouse=True)
def _isolated_private_state(monkeypatch):
    outbox_store = {}
    relay_policy_store = {}
    legacy_migration_store = {}

    def _read_outbox_json(_domain, _filename, default_factory, **_kwargs):
        payload = outbox_store.get("payload")
        if payload is None:
            return default_factory()
        return copy.deepcopy(payload)

    def _write_outbox_json(_domain, _filename, payload, **_kwargs):
        outbox_store["payload"] = copy.deepcopy(payload)

    def _read_policy_json(_domain, _filename, default_factory, **_kwargs):
        payload = relay_policy_store.get("payload")
        if payload is None:
            return default_factory()
        return copy.deepcopy(payload)

    def _write_policy_json(_domain, _filename, payload, **_kwargs):
        relay_policy_store["payload"] = copy.deepcopy(payload)

    def _read_migration_json(_domain, _filename, default_factory, **_kwargs):
        payload = legacy_migration_store.get("payload")
        if payload is None:
            return default_factory()
        return copy.deepcopy(payload)

    def _write_migration_json(_domain, _filename, payload, **_kwargs):
        legacy_migration_store["payload"] = copy.deepcopy(payload)

    monkeypatch.setattr(mesh_private_outbox, "read_sensitive_domain_json", _read_outbox_json)
    monkeypatch.setattr(mesh_private_outbox, "write_sensitive_domain_json", _write_outbox_json)
    monkeypatch.setattr(mesh_relay_policy, "read_sensitive_domain_json", _read_policy_json)
    monkeypatch.setattr(mesh_relay_policy, "write_sensitive_domain_json", _write_policy_json)
    monkeypatch.setattr(mesh_gate_legacy_migration, "read_sensitive_domain_json", _read_migration_json)
    monkeypatch.setattr(mesh_gate_legacy_migration, "write_sensitive_domain_json", _write_migration_json)
    monkeypatch.setattr(
        mesh_private_transport_manager.private_transport_manager,
        "_kickoff_background_bootstrap",
        lambda **_kwargs: False,
    )
    monkeypatch.setattr(main, "_kickoff_dm_send_transport_upgrade", lambda: None)
    monkeypatch.setattr(main, "_kickoff_private_control_transport_upgrade", lambda: None)
    mesh_private_release_worker.reset_private_release_worker_for_tests()
    mesh_private_outbox.reset_private_delivery_outbox_for_tests()
    mesh_private_transport_manager.reset_private_transport_manager_for_tests()
    mesh_relay_policy.reset_relay_policy_for_tests()
    mesh_gate_legacy_migration.reset_gate_legacy_migration_for_tests()
    get_settings.cache_clear()
    mesh_private_outbox.private_delivery_outbox._load()
    yield
    mesh_private_release_worker.reset_private_release_worker_for_tests()
    mesh_private_outbox.reset_private_delivery_outbox_for_tests()
    mesh_private_transport_manager.reset_private_transport_manager_for_tests()
    get_settings.cache_clear()


def _outbox_item(item_id: str, *, exposure: str = "diagnostic") -> dict:
    return next(
        item
        for item in mesh_private_outbox.private_delivery_outbox.list_items(
            limit=50,
            exposure=exposure,
        )
        if item["id"] == item_id
    )


def _make_receive(body: bytes):
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return receive


def _request(body: dict, path: str = "/api/mesh/send") -> Request:
    return Request(
        {
            "type": "http",
            "headers": [(b"content-type", b"application/json")],
            "client": ("test", 12345),
            "method": "POST",
            "path": path,
            "query_string": b"",
            "root_path": "",
            "server": ("test", 80),
        },
        _make_receive(json.dumps(body).encode("utf-8")),
    )


def _mesh_send_body() -> dict:
    return {
        "destination": "broadcast",
        "message": "hello",
        "node_id": "node-1",
        "public_key": "pub",
        "public_key_algo": "Ed25519",
        "signature": "sig",
        "sequence": 7,
        "protocol_version": mesh_signed_events.PROTOCOL_VERSION,
    }


def _dm_send_body_for_context(*, context_endpoint: str = "/api/wormhole/dm/send") -> dict:
    sequence = 17
    sender_id = "!sb_sender"
    payload = {
        "recipient_id": "!sb_recipient",
        "delivery_class": "alias",
        "recipient_token": "recipient-token",
        "ciphertext": "ciphertext",
        "format": "mls1",
        "msg_id": "ctx-msg-1",
        "timestamp": int(time.time()),
        "transport_lock": "private_strong",
    }
    signed_context = build_signed_context(
        event_type="dm_message",
        kind="dm_send",
        endpoint=context_endpoint,
        lane_floor="private_strong",
        sequence_domain="dm_send",
        node_id=sender_id,
        sequence=sequence,
        payload=payload,
        recipient_id=payload["recipient_id"],
    )
    return {
        "sender_id": sender_id,
        "recipient_id": payload["recipient_id"],
        "delivery_class": payload["delivery_class"],
        "recipient_token": payload["recipient_token"],
        "ciphertext": payload["ciphertext"],
        "format": payload["format"],
        "msg_id": payload["msg_id"],
        "timestamp": payload["timestamp"],
        "transport_lock": payload["transport_lock"],
        "signed_context": signed_context,
        "sequence": sequence,
        "public_key": base64.b64encode(b"x" * 32).decode("ascii"),
        "public_key_algo": "Ed25519",
        "protocol_version": mesh_signed_events.PROTOCOL_VERSION,
        "signature": "sig",
    }


def _protected_custody() -> dict:
    return {
        "code": "protected_at_rest",
        "provider": "passphrase",
        "protected_at_rest": True,
    }


def _attested_current() -> dict:
    return {
        "attestation_state": "attested_current",
        "override_active": False,
        "detail": "privacy-core version and trusted artifact hash are current",
    }


def _compatibility_clear() -> dict:
    return {
        "stored_legacy_lookup_contacts_present": False,
        "legacy_lookup_runtime_active": False,
        "legacy_mailbox_get_runtime_active": False,
        "legacy_mailbox_get_enabled": False,
        "local_contact_upgrade_ok": True,
    }


def _gate_privilege_ok() -> dict:
    return {
        "ordinary_gate_view_scope_class": "gate_member_or_gate_scope",
        "privileged_gate_event_scope_class": "explicit_gate_audit",
        "repair_detail_scope_class": "local_operator_diagnostic",
        "privileged_gate_event_view_enabled": True,
        "repair_detail_view_enabled": True,
    }


def _strong_claims_good() -> dict:
    return {
        "allowed": True,
        "compat_overrides_clear": True,
        "clearnet_fallback_blocked": True,
        "compatibility": {},
        "reasons": [],
    }


def _release_gate_good() -> dict:
    return {
        "ready": True,
        "blocking_reasons": [],
    }


@pytest.mark.parametrize(
    "verifier_reason",
    [
        "Replay detected: sequence 7 <= last 7",
        "public key is revoked",
    ],
)
def test_signed_write_replay_or_revocation_rejects_before_handler(monkeypatch, verifier_reason):
    reached = {"value": False}
    monkeypatch.setenv("MESH_SIGNED_WRITE_CONTENT_PRIVATE_TRANSPORT_LOCK_REQUIRED", "false")
    monkeypatch.setattr(
        mesh_signed_events,
        "verify_signed_write",
        lambda **_kwargs: (False, verifier_reason),
    )

    @mesh_signed_events.requires_signed_write(kind=mesh_signed_events.SignedWriteKind.MESH_SEND)
    async def handler(request: Request):
        reached["value"] = True
        return {"ok": True}

    result = asyncio.run(handler(_request(_mesh_send_body())))

    assert result == {"ok": False, "detail": verifier_reason}
    assert reached["value"] is False


def test_missing_signed_context_returns_canonical_resign_payload_before_handler(monkeypatch):
    reached = {"value": False}
    monkeypatch.setenv("MESH_SIGNED_WRITE_CONTEXT_REQUIRED", "true")
    monkeypatch.setenv("MESH_SIGNED_WRITE_CONTENT_PRIVATE_TRANSPORT_LOCK_REQUIRED", "true")
    body = _dm_send_body_for_context()
    body.pop("signed_context")

    @mesh_signed_events.requires_signed_write(kind=mesh_signed_events.SignedWriteKind.DM_SEND)
    async def handler(request: Request):
        reached["value"] = True
        return {"ok": True}

    result = asyncio.run(handler(_request(body, "/api/wormhole/dm/send")))

    assert reached["value"] is False
    assert result["ok"] is False
    assert result["retryable"] is True
    assert result["resign_required"] is True
    assert result["canonical"]["signed_context"]["endpoint"] == "/api/wormhole/dm/send"
    assert result["canonical"]["signed_context"]["lane_floor"] == "private_strong"
    assert result["canonical"]["payload"]["signed_context"] == result["canonical"]["signed_context"]
    assert isinstance(result["canonical"]["signature_payload"], str)


def test_signed_context_mismatch_returns_canonical_resign_payload_before_handler(monkeypatch):
    reached = {"value": False}
    monkeypatch.setenv("MESH_SIGNED_WRITE_CONTEXT_REQUIRED", "true")
    monkeypatch.setenv("MESH_SIGNED_WRITE_CONTENT_PRIVATE_TRANSPORT_LOCK_REQUIRED", "true")
    body = _dm_send_body_for_context(context_endpoint="/api/wormhole/dm/poll")

    @mesh_signed_events.requires_signed_write(kind=mesh_signed_events.SignedWriteKind.DM_SEND)
    async def handler(request: Request):
        reached["value"] = True
        return {"ok": True}

    result = asyncio.run(handler(_request(body, "/api/wormhole/dm/send")))

    assert reached["value"] is False
    assert result["ok"] is False
    assert result["detail"] == "signed_context_mismatch"
    assert result["retryable"] is True
    assert result["resign_required"] is True
    assert result["canonical"]["signed_context"]["endpoint"] == "/api/wormhole/dm/send"
    assert result["canonical"]["payload"]["signed_context"] == result["canonical"]["signed_context"]


def test_privacy_claims_do_not_overclaim_when_release_profile_blocks(monkeypatch):
    monkeypatch.setenv("MESH_RELEASE_PROFILE", "release-candidate")
    monkeypatch.setenv("MESH_DEBUG_MODE", "false")
    monkeypatch.setenv("PRIVACY_CORE_ALLOWED_SHA256", "")
    get_settings.cache_clear()

    snapshot = privacy_claims_snapshot(
        transport_tier="private_strong",
        local_custody=_protected_custody(),
        privacy_core=_attested_current(),
        compatibility_readiness=_compatibility_clear(),
        gate_privilege_access=_gate_privilege_ok(),
    )

    dm = snapshot["claims"]["dm_strong"]
    gate = snapshot["claims"]["gate_transitional"]
    assert dm["allowed"] is False
    assert gate["allowed"] is False
    assert any(str(blocker).startswith("profile_") for blocker in dm["blockers"])
    assert snapshot["chip"]["state"] == "dm_strong_blocked"


def test_privacy_claims_do_not_overclaim_gate_without_privileged_scope_evidence():
    snapshot = privacy_claims_snapshot(
        transport_tier="private_strong",
        local_custody=_protected_custody(),
        privacy_core=_attested_current(),
        compatibility_readiness=_compatibility_clear(),
        gate_privilege_access={
            "ordinary_gate_view_scope_class": "gate_member_or_gate_scope",
            "privileged_gate_event_scope_class": "gate_member",
            "repair_detail_scope_class": "ordinary_gate_view",
        },
    )

    gate = snapshot["claims"]["gate_transitional"]
    assert gate["allowed"] is False
    assert "gate_privileged_event_scope_not_explicit_audit" in gate["blockers"]
    assert "gate_repair_scope_not_local_operator_diagnostic" in gate["blockers"]
    assert snapshot["chip"]["state"] != "gate_transitional_ready"


def test_ready_raw_claim_chip_degrades_when_rollout_controls_are_not_safe():
    claims = privacy_claims_snapshot(
        transport_tier="private_strong",
        local_custody=_protected_custody(),
        privacy_core=_attested_current(),
        compatibility_readiness=_compatibility_clear(),
        gate_privilege_access=_gate_privilege_ok(),
    )

    chip = privacy_status_surface_chip(
        claims,
        strong_claims_allowed=False,
        release_gate_ready=True,
    )

    assert claims["chip"]["state"] == "dm_strong_ready"
    assert chip["state"] == "dm_strong_pending"
    assert chip["authoritative_claim"] == "dm_strong"


def test_review_export_blocks_private_default_when_controls_have_override():
    claims = privacy_claims_snapshot(
        transport_tier="private_strong",
        local_custody=_protected_custody(),
        privacy_core=_attested_current(),
        compatibility_readiness=_compatibility_clear(),
        gate_privilege_access=_gate_privilege_ok(),
    )
    readiness = rollout_readiness_snapshot(
        privacy_claims=claims,
        transport_tier="private_strong",
        local_custody=_protected_custody(),
        privacy_core=_attested_current(),
        compatibility_debt={},
        compatibility_readiness=_compatibility_clear(),
        gate_privilege_access=_gate_privilege_ok(),
        strong_claims=_strong_claims_good(),
        release_gate=_release_gate_good(),
    )
    controls = rollout_controls_snapshot(
        rollout_readiness=readiness,
        privacy_core={**_attested_current(), "override_active": True},
        strong_claims=_strong_claims_good(),
        transport_tier="private_strong",
    )
    export = review_export_snapshot(
        privacy_claims=claims,
        rollout_readiness=readiness,
        rollout_controls=controls,
        rollout_health={"state": "healthy"},
    )

    assert readiness["allowed"] is True
    assert controls["state"] == "override_active"
    assert export["review_summary"]["private_default_rollout_safe"]["allowed"] is False
    assert (
        export["review_summary"]["private_default_rollout_safe"]["state"]
        == "blocked_by_operator_override"
    )
    assert export["review_summary"]["major_blocker"]["state"] == "operator_override"


@pytest.mark.parametrize(
    ("lane", "current_tier", "payload"),
    [
        (
            "dm",
            "public_degraded",
            {
                "msg_id": "adv-dm-floor-1",
                "sender_id": "alice",
                "recipient_id": "bob",
                "delivery_class": "request",
                "ciphertext": "ciphertext",
                "timestamp": 1,
            },
        ),
        (
            "gate",
            "private_transitional",
            {
                "gate_id": "adv-gate-floor-1",
                "event_id": "adv-gate-event-floor-1",
                "event": {
                    "event_id": "adv-gate-event-floor-1",
                    "event_type": "gate_message",
                    "payload": {"gate": "adv-gate-floor-1", "ciphertext": "ciphertext"},
                },
            },
        ),
    ],
)
def test_lane_floor_failure_has_no_delivery_or_public_side_effects(monkeypatch, lane, current_tier, payload):
    public_calls = []
    private_calls = []

    monkeypatch.setattr(
        "services.mesh.mesh_dm_relay.dm_relay.deposit",
        lambda **kwargs: private_calls.append(("relay", copy.deepcopy(kwargs))) or {"ok": True},
    )
    monkeypatch.setattr(
        "services.mesh.mesh_rns.rns_bridge.send_private_dm",
        lambda **kwargs: private_calls.append(("rns_dm", copy.deepcopy(kwargs))) or True,
    )
    monkeypatch.setattr(
        "services.mesh.mesh_rns.rns_bridge.publish_gate_event",
        lambda gate_id, event: private_calls.append(("rns_gate", gate_id, copy.deepcopy(event))),
    )
    monkeypatch.setattr(
        "services.mesh.mesh_hashchain.gate_store.append",
        lambda gate_id, event: private_calls.append(("gate_store", gate_id, copy.deepcopy(event))) or dict(event),
    )
    monkeypatch.setattr(
        "services.mesh.mesh_router.mesh_router.route",
        lambda envelope, credentials: public_calls.append((envelope, credentials)) or [],
    )

    result = attempt_private_release(
        lane=lane,
        current_tier=current_tier,
        payload=payload,
    )

    assert result["ok"] is False
    assert result["no_acceptable_path"] is True
    assert result["selected_transport"] == ""
    assert "network_state" not in result
    assert private_calls == []
    assert public_calls == []


def test_dm_route_only_queues_and_never_directly_publishes(monkeypatch):
    from services import wormhole_supervisor
    from services.mesh import mesh_hashchain

    direct_calls = []

    monkeypatch.setattr(wormhole_supervisor, "get_transport_tier", lambda: "private_strong")
    monkeypatch.setattr(main, "_secure_dm_enabled", lambda: False)
    monkeypatch.setattr(main, "_verify_signed_write", lambda **_kwargs: (True, "ok"))
    monkeypatch.setattr(mesh_hashchain.infonet, "validate_and_set_sequence", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        "services.mesh.mesh_dm_relay.dm_relay.consume_nonce",
        lambda *_args, **_kwargs: (True, "ok"),
    )
    monkeypatch.setattr(
        "services.mesh.mesh_dm_relay.dm_relay.is_blocked",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        "services.mesh.mesh_wormhole_contacts.verified_first_contact_requirement",
        lambda *_args, **_kwargs: {"ok": True, "trust_level": "verified"},
    )
    monkeypatch.setattr(
        "services.mesh.mesh_dm_relay.dm_relay.deposit",
        lambda **kwargs: direct_calls.append(("relay", copy.deepcopy(kwargs))) or {"ok": True},
    )
    monkeypatch.setattr(
        "services.mesh.mesh_rns.rns_bridge.send_private_dm",
        lambda **kwargs: direct_calls.append(("rns", copy.deepcopy(kwargs))) or True,
    )

    response = asyncio.run(
        main.dm_send(
            _request(
                (lambda body: body | {
                    "signed_context": build_signed_context(
                        event_type="dm_message",
                        kind="dm_send",
                        endpoint="/api/mesh/dm/send",
                        lane_floor="private_strong",
                        sequence_domain="dm_send",
                        node_id=body["sender_id"],
                        sequence=body["sequence"],
                        payload={
                            "recipient_id": body["recipient_id"],
                            "delivery_class": body["delivery_class"],
                            "recipient_token": body["recipient_token"],
                            "ciphertext": body["ciphertext"],
                            "format": body["format"],
                            "msg_id": body["msg_id"],
                            "timestamp": body["timestamp"],
                            "transport_lock": body["transport_lock"],
                        },
                        recipient_id=body["recipient_id"],
                    )
                })(
                    {
                        "sender_id": "!sb_sender",
                        "sender_token_hash": "sender-token-hash",
                        "recipient_id": "!sb_recipient",
                        "delivery_class": "request",
                        "recipient_token": "",
                        "ciphertext": "ciphertext",
                        "format": "mls1",
                        "msg_id": "route-sole-publisher-1",
                        "timestamp": int(time.time()),
                        "transport_lock": "private_strong",
                        "public_key": base64.b64encode(b"x" * 32).decode("ascii"),
                        "public_key_algo": "Ed25519",
                        "signature": "sig",
                        "sequence": 91,
                        "protocol_version": mesh_signed_events.PROTOCOL_VERSION,
                    }
                ),
                path="/api/mesh/dm/send",
            )
        )
    )

    assert response["ok"] is True
    assert response["queued"] is True
    assert response["delivery"]["local_state"] == "sealed_local"
    assert direct_calls == []
    item = _outbox_item(response["outbox_id"], exposure="diagnostic")
    assert item["lane"] == "dm"
    assert response["msg_id"] == "route-sole-publisher-1"


def test_gate_release_is_tor_first_and_never_uses_rns_or_public_when_tor_succeeds(monkeypatch):
    from services.mesh.mesh_router import TransportResult, mesh_router

    appended = []
    tor_calls = []
    rns_calls = []
    public_calls = []

    monkeypatch.setattr(
        "services.mesh.mesh_hashchain.gate_store.append",
        lambda gate_id, event: appended.append((gate_id, copy.deepcopy(event))) or dict(event),
    )
    monkeypatch.setattr(mesh_router.tor_arti, "can_reach", lambda _envelope: True)
    monkeypatch.setattr(
        mesh_router.tor_arti,
        "send",
        lambda envelope, _credentials: tor_calls.append(envelope)
        or TransportResult(True, "tor_arti", "delivered over onion peers"),
    )
    monkeypatch.setattr(
        "services.mesh.mesh_rns.rns_bridge.publish_gate_event",
        lambda gate_id, event: rns_calls.append((gate_id, copy.deepcopy(event))),
    )
    monkeypatch.setattr(
        "services.mesh.mesh_router.mesh_router.route",
        lambda envelope, credentials: public_calls.append((envelope, credentials)) or [],
    )

    result = attempt_private_release(
        lane="gate",
        current_tier="private_strong",
        payload={
            "gate_id": "adv-gate-tor-1",
            "event_id": "adv-gate-event-tor-1",
            "event": {
                "event_id": "adv-gate-event-tor-1",
                "event_type": "gate_message",
                "payload": {"gate": "adv-gate-tor-1", "ciphertext": "ciphertext"},
            },
        },
    )

    assert result["ok"] is True
    assert result["selected_carrier"] == "tor_arti_peer_push"
    assert result["network_state"] == "published_private"
    assert result["hidden_transport_effective"] is True
    assert len(appended) == 1
    assert len(tor_calls) == 1
    assert rns_calls == []
    assert public_calls == []


def test_gate_release_all_private_carriers_fail_stays_pending_not_delivered(monkeypatch):
    from services.mesh.mesh_router import TransportResult, mesh_router

    appended = []
    public_calls = []

    monkeypatch.setattr(
        "services.mesh.mesh_hashchain.gate_store.append",
        lambda gate_id, event: appended.append((gate_id, copy.deepcopy(event))) or dict(event),
    )
    monkeypatch.setattr(mesh_router.tor_arti, "can_reach", lambda _envelope: True)
    monkeypatch.setattr(
        mesh_router.tor_arti,
        "send",
        lambda _envelope, _credentials: TransportResult(False, "tor_arti", "onion peers unavailable"),
    )
    monkeypatch.setattr(
        "services.mesh.mesh_rns.rns_bridge.publish_gate_event",
        lambda _gate_id, _event: (_ for _ in ()).throw(RuntimeError("rns unavailable")),
    )
    monkeypatch.setattr(
        "services.mesh.mesh_router.mesh_router.route",
        lambda envelope, credentials: public_calls.append((envelope, credentials)) or [],
    )

    result = attempt_private_release(
        lane="gate",
        current_tier="private_strong",
        payload={
            "gate_id": "adv-gate-pending-1",
            "event_id": "adv-gate-event-pending-1",
            "event": {
                "event_id": "adv-gate-event-pending-1",
                "event_type": "gate_message",
                "payload": {"gate": "adv-gate-pending-1", "ciphertext": "ciphertext"},
            },
        },
    )

    assert result["ok"] is False
    assert result["dispatch_reason"] == "gate_private_publish_pending"
    assert result["published"] is False
    assert result["local_state"] == "sealed_local"
    assert result["network_state"] == "queued_private_release"
    assert len(appended) == 1
    assert public_calls == []


def test_strong_release_attestation_failure_queues_without_transport_side_effects(monkeypatch):
    deposit_calls = []
    direct_calls = []

    monkeypatch.setenv("MESH_RELEASE_PROFILE", "testnet-private")
    get_settings.cache_clear()
    monkeypatch.setattr("services.wormhole_supervisor.get_transport_tier", lambda: "private_strong")
    monkeypatch.setattr(
        "services.privacy_core_attestation.privacy_core_attestation",
        lambda *_args, **_kwargs: {
            "attestation_state": "attestation_mismatch",
            "detail": "privacy-core artifact mismatch",
        },
    )
    monkeypatch.setattr(mesh_private_release_worker, "_secure_dm_enabled", lambda: True)
    monkeypatch.setattr(mesh_private_release_worker, "_rns_private_dm_ready", lambda: True)
    monkeypatch.setattr(mesh_private_release_worker, "_maybe_apply_dm_relay_jitter", lambda: None)
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
            "msg_id": "adv-dm-attestation-1",
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
    assert direct_calls == []
    assert item["release_state"] == "queued"
    assert item["status"]["reason_code"] == "privacy_core_attestation_not_current"
    assert item["network_state"] == "queued_private_release"


def test_scoped_relay_policy_cannot_bypass_hidden_transport_requirement(monkeypatch):
    deposit_calls = []

    monkeypatch.setenv("MESH_PRIVATE_RELEASE_APPROVAL_ENABLE", "true")
    get_settings.cache_clear()
    monkeypatch.setattr("services.wormhole_supervisor.get_transport_tier", lambda: "private_strong")
    monkeypatch.setattr(mesh_private_release_worker, "_secure_dm_enabled", lambda: True)
    monkeypatch.setattr(mesh_private_release_worker, "_rns_private_dm_ready", lambda: False)
    monkeypatch.setattr(mesh_private_release_worker, "_anonymous_dm_hidden_transport_enforced", lambda: False)
    monkeypatch.setattr(mesh_private_release_worker, "_hidden_relay_transport_effective", lambda: False)
    monkeypatch.setattr(mesh_private_release_worker, "_maybe_apply_dm_relay_jitter", lambda: None)
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
    monkeypatch.setattr(
        "services.mesh.mesh_dm_relay.dm_relay.deposit",
        lambda **kwargs: deposit_calls.append(kwargs) or {"ok": True, "msg_id": kwargs["msg_id"]},
    )
    mesh_relay_policy.grant_relay_policy(
        scope_type="dm_contact",
        scope_id="bob",
        profile="dev",
        hidden_transport_required=True,
        reason="adversarial_hidden_transport_required",
    )

    queued = main._queue_dm_release(
        current_tier="private_strong",
        payload={
            "msg_id": "adv-dm-hidden-policy-1",
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
    assert item["approval"]["required"] is False
    denied = mesh_relay_policy.relay_policy_grants_dm(
        recipient_id="bob",
        profile="dev",
        hidden_transport_effective=False,
    )
    assert denied["reason_code"] == "relay_policy_hidden_transport_required"


def test_legacy_gate_migration_never_relabels_original_author_or_signature(monkeypatch):
    original = {
        "event_id": "adv-legacy-event-1",
        "event_type": "gate_message",
        "node_id": "original-author",
        "payload": {
            "gate": "adv-legacy-gate",
            "ciphertext": "legacy-ct",
            "nonce": "legacy-nonce",
            "sender_ref": "legacy-sender",
            "format": "mls1",
            "gate_envelope": "legacy-envelope-token",
        },
        "signature": "original-signature",
        "public_key": "original-key",
        "public_key_algo": "Ed25519",
        "protocol_version": "infonet/2",
    }

    monkeypatch.setattr(
        "services.mesh.mesh_hashchain.gate_store.get_messages",
        lambda gate_id, limit=500, offset=0: [copy.deepcopy(original)],
    )
    monkeypatch.setattr(
        "services.mesh.mesh_hashchain.gate_store.get_event",
        lambda event_id: copy.deepcopy(original) if event_id == "adv-legacy-event-1" else None,
    )
    monkeypatch.setattr(
        "services.mesh.mesh_wormhole_persona.sign_gate_wormhole_event",
        lambda **_kwargs: {
            "node_id": "local-wrapper-signer",
            "identity_scope": "gate_persona",
            "sequence": 1,
            "signature": "local-wrapper-signature",
            "public_key": "local-wrapper-key",
            "public_key_algo": "Ed25519",
            "protocol_version": "infonet/2",
        },
    )

    result = mesh_gate_legacy_migration.create_missing_local_archival_rewraps(
        gate_id="adv-legacy-gate",
    )

    assert result["ok"] is True
    assert result["created"] == 1
    wrapper = result["wrappers"][0]
    assert wrapper["event_type"] == "gate_archival_rewrap"
    assert wrapper["node_id"] == "local-wrapper-signer"
    assert wrapper["signature"] == "local-wrapper-signature"
    assert wrapper["payload"]["original_author_node_id"] == "original-author"
    assert wrapper["payload"]["original_event_id"] == "adv-legacy-event-1"
    assert wrapper["payload"]["original_signature_hash"]
    assert "original-signature" not in str(wrapper["payload"])
    assert original["node_id"] == "original-author"
    assert original["signature"] == "original-signature"
