from __future__ import annotations

import asyncio
import time

import main
from services.config import get_settings
from services.mesh import mesh_compatibility, mesh_wormhole_contacts, mesh_wormhole_prekey
from services.mesh.mesh_schema import PROTOCOL_VERSION


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


def _json_request(path: str, payload: dict):
    from starlette.requests import Request

    body = main.orjson.dumps(payload)

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "headers": [(b"content-type", b"application/json")],
            "client": ("test", 12345),
            "method": "POST",
            "path": path,
            "query_string": b"",
        },
        receive,
    )


def _pin_contact_with_lookup_handle(tmp_path, monkeypatch, peer_id: str, handle: str):
    monkeypatch.setattr(mesh_wormhole_contacts, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        mesh_wormhole_contacts,
        "CONTACTS_FILE",
        tmp_path / "wormhole_dm_contacts.json",
    )
    mesh_wormhole_contacts.pin_wormhole_dm_invite(
        peer_id,
        invite_payload={
            "trust_fingerprint": "aa" * 32,
            "public_key": "pub",
            "public_key_algo": "Ed25519",
            "identity_dh_pub_key": "dh-pub",
            "dh_algo": "X25519",
            "prekey_lookup_handle": handle,
        },
    )


def test_pinned_contact_dm_pubkey_prefers_invite_lookup_handle(tmp_path, monkeypatch):
    _pin_contact_with_lookup_handle(tmp_path, monkeypatch, "peer-123", "invite-handle-123")
    direct_calls: list[str] = []

    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (False, "no"))
    monkeypatch.setattr(main, "_is_debug_test_request", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        "services.mesh.mesh_dm_relay.dm_relay.get_dh_key_by_lookup",
        lambda handle: ({"dh_pub": "pub", "dh_algo": "X25519"}, "peer-123")
        if handle == "invite-handle-123"
        else (None, ""),
    )
    monkeypatch.setattr(
        "services.mesh.mesh_dm_relay.dm_relay.get_dh_key",
        lambda agent_id: direct_calls.append(agent_id) or {"dh_pub": "legacy", "dh_algo": "X25519"},
    )

    result = asyncio.run(main.dm_get_pubkey(_request("/api/mesh/dm/pubkey"), agent_id="peer-123"))

    assert result["ok"] is True
    assert result["lookup_mode"] == "invite_lookup_handle"
    assert "agent_id" not in result
    assert direct_calls == []


def test_pinned_contact_dm_pubkey_does_not_fallback_to_legacy_direct_lookup(tmp_path, monkeypatch):
    _pin_contact_with_lookup_handle(tmp_path, monkeypatch, "peer-124", "invite-handle-124")
    direct_calls: list[str] = []

    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (False, "no"))
    monkeypatch.setattr(main, "_is_debug_test_request", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        "services.mesh.mesh_dm_relay.dm_relay.get_dh_key_by_lookup",
        lambda _handle: (None, ""),
    )
    monkeypatch.setattr(
        "services.mesh.mesh_dm_relay.dm_relay.get_dh_key",
        lambda agent_id: direct_calls.append(agent_id) or {"dh_pub": "legacy", "dh_algo": "X25519"},
    )

    result = asyncio.run(main.dm_get_pubkey(_request("/api/mesh/dm/pubkey"), agent_id="peer-124"))

    assert result == {"ok": False, "detail": "Invite lookup unavailable"}
    assert direct_calls == []


def test_prekey_bundle_route_prefers_invite_lookup_when_local_contact_allows_it(tmp_path, monkeypatch):
    _pin_contact_with_lookup_handle(tmp_path, monkeypatch, "peer-125", "invite-handle-125")
    captured: dict[str, str] = {}

    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (False, "no"))
    monkeypatch.setattr(main, "_is_debug_test_request", lambda *_args, **_kwargs: False)

    def _fetch(**kwargs):
        captured.update(kwargs)
        return {
            "ok": True,
            "agent_id": "peer-125",
            "lookup_mode": "invite_lookup_handle",
            "trust_fingerprint": "bb" * 16,
            "bundle": {"identity_dh_pub_key": "pub"},
        }

    monkeypatch.setattr(main, "fetch_dm_prekey_bundle", _fetch)

    result = asyncio.run(main.dm_get_prekey_bundle(_request("/api/mesh/dm/prekey-bundle"), agent_id="peer-125"))

    assert captured == {"agent_id": "peer-125", "lookup_token": "invite-handle-125"}
    assert result["ok"] is True
    assert result["lookup_mode"] == "invite_lookup_handle"
    assert "agent_id" not in result


def test_legacy_direct_lookup_remains_blocked_without_invite_lookup_handle(monkeypatch):
    monkeypatch.delenv("MESH_BLOCK_LEGACY_AGENT_ID_LOOKUP", raising=False)
    monkeypatch.delenv("MESH_DEV_ALLOW_LEGACY_COMPAT", raising=False)
    get_settings.cache_clear()
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))

    try:
        result = asyncio.run(
            main.dm_get_pubkey(
                _request("/api/mesh/dm/pubkey?exposure=diagnostic"),
                agent_id="peer-legacy",
            )
        )
    finally:
        get_settings.cache_clear()

    assert result["ok"] is False
    assert result["detail"] == "legacy agent_id lookup disabled; use invite lookup handle"
    assert result["removal_target"] == "0.10.0 (2026-06-01)"


def test_legacy_direct_lookup_stays_blocked_even_with_stale_migration_env_without_dev_override(monkeypatch):
    monkeypatch.setenv("MESH_BLOCK_LEGACY_AGENT_ID_LOOKUP", "false")
    monkeypatch.setenv("MESH_ALLOW_LEGACY_AGENT_ID_LOOKUP_UNTIL", "2099-01-01")
    monkeypatch.delenv("MESH_DEV_ALLOW_LEGACY_COMPAT", raising=False)
    get_settings.cache_clear()

    try:
        assert mesh_compatibility.legacy_agent_id_lookup_blocked() is True
        snapshot = mesh_compatibility.compatibility_status_snapshot()
    finally:
        get_settings.cache_clear()

    assert snapshot["sunset"]["legacy_agent_id_lookup"]["blocked"] is True


def test_legacy_direct_lookup_requires_explicit_dev_override(monkeypatch):
    monkeypatch.setenv("MESH_BLOCK_LEGACY_AGENT_ID_LOOKUP", "false")
    monkeypatch.setenv("MESH_ALLOW_LEGACY_AGENT_ID_LOOKUP_UNTIL", "2099-01-01")
    monkeypatch.setenv("MESH_DEV_ALLOW_LEGACY_COMPAT", "true")
    get_settings.cache_clear()

    try:
        assert mesh_compatibility.legacy_agent_id_lookup_blocked() is False
        snapshot = mesh_compatibility.compatibility_status_snapshot()
    finally:
        get_settings.cache_clear()

    assert snapshot["sunset"]["legacy_agent_id_lookup"]["status"] == "dev_migration_override"


def test_legacy_get_mailbox_usage_is_explicit_and_compatibility_debt_is_coarse(tmp_path, monkeypatch):
    monkeypatch.setattr(mesh_compatibility, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        mesh_compatibility,
        "COMPATIBILITY_FILE",
        tmp_path / "mesh_compatibility_usage.json",
    )
    monkeypatch.setenv("MESH_DEV_ALLOW_LEGACY_COMPAT", "true")
    monkeypatch.setenv("MESH_ALLOW_LEGACY_DM_GET_UNTIL", "2099-01-01")
    get_settings.cache_clear()

    monkeypatch.setattr(main, "_secure_dm_enabled", lambda: True)
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(main, "_is_debug_test_request", lambda *_args, **_kwargs: False)
    monkeypatch.setattr("services.mesh.mesh_dm_relay.dm_relay.count_legacy", lambda **_kwargs: 2)
    monkeypatch.setattr(
        main,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": False, "rns_ready": False},
    )
    monkeypatch.setattr(main, "_current_private_lane_tier", lambda *_args, **_kwargs: "private_control_only")
    monkeypatch.setattr(main, "_refresh_lookup_handle_rotation_background", lambda **_kwargs: {"ok": True, "rotated": False})
    monkeypatch.setattr(main, "lookup_handle_rotation_status_snapshot", lambda: {"state": "lookup_handle_rotation_ok"})
    monkeypatch.setattr(main.private_transport_manager, "observe_state", lambda **_kwargs: {"status": {"label": "Preparing private lane"}})
    monkeypatch.setattr(main.private_delivery_outbox, "summary", lambda **_kwargs: {"items": [], "counts": {}})
    monkeypatch.setattr(main, "local_custody_status_snapshot", lambda: {"state": "protected_at_rest"})
    monkeypatch.setattr(main, "_strong_claims_policy_snapshot", lambda **_kwargs: {"allowed": False, "compatibility": {}})
    monkeypatch.setattr(main, "_privacy_core_status", lambda: {"attestation_state": "attested_current"})
    monkeypatch.setattr(main, "_release_gate_status", lambda **_kwargs: {"allowed": False})
    monkeypatch.setattr(main, "_resume_private_delivery_background_work", lambda **_kwargs: None)

    try:
        count_result = asyncio.run(
            main.dm_count(_request("/api/mesh/dm/count?agent_token=legacy-token"), agent_token="legacy-token")
        )
        status = asyncio.run(main.api_wormhole_status(_request("/api/wormhole/status?exposure=diagnostic")))
    finally:
        get_settings.cache_clear()

    assert count_result == {"ok": True, "count": 5}
    assert status["legacy_compatibility"]["usage"]["legacy_dm_get"]["recent_kinds"] == ["count"]
    assert status["compatibility_debt"]["legacy_mailbox_get_reliance"] == {
        "active": True,
        "last_seen_at": status["legacy_compatibility"]["usage"]["legacy_dm_get"]["last_seen_at"],
        "blocked_count": 0,
        "enabled": True,
    }
    assert status["compatibility_debt"]["legacy_lookup_reliance"] == {
        "active": False,
        "last_seen_at": 0,
        "blocked_count": 0,
    }
    assert "recent_targets" not in status["compatibility_debt"]["legacy_lookup_reliance"]
    assert "recent_kinds" not in status["compatibility_debt"]["legacy_mailbox_get_reliance"]


def test_legacy_get_mailbox_path_stays_explicit_when_secure_mode_blocks_it(monkeypatch):
    monkeypatch.delenv("MESH_ALLOW_LEGACY_DM_GET_UNTIL", raising=False)
    monkeypatch.delenv("MESH_DEV_ALLOW_LEGACY_COMPAT", raising=False)
    get_settings.cache_clear()
    monkeypatch.setattr(main, "_secure_dm_enabled", lambda: True)
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))

    try:
        result = asyncio.run(
            main.dm_count(
                _request("/api/mesh/dm/count?agent_token=legacy-token&exposure=diagnostic"),
                agent_token="legacy-token",
            )
        )
    finally:
        get_settings.cache_clear()

    assert result == {"ok": False, "detail": "Legacy GET count is disabled in secure mode", "count": 0}


def test_legacy_get_mailbox_override_date_without_dev_flag_still_blocks(monkeypatch):
    monkeypatch.setenv("MESH_ALLOW_LEGACY_DM_GET_UNTIL", "2099-01-01")
    monkeypatch.delenv("MESH_DEV_ALLOW_LEGACY_COMPAT", raising=False)
    get_settings.cache_clear()
    monkeypatch.setattr(main, "_secure_dm_enabled", lambda: True)
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))

    try:
        result = asyncio.run(
            main.dm_count(
                _request("/api/mesh/dm/count?agent_token=legacy-token&exposure=diagnostic"),
                agent_token="legacy-token",
            )
        )
    finally:
        get_settings.cache_clear()

    assert result == {"ok": False, "detail": "Legacy GET count is disabled in secure mode", "count": 0}


def test_ordinary_authenticated_status_exposes_only_coarse_compatibility_debt(tmp_path, monkeypatch):
    monkeypatch.setattr(mesh_compatibility, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        mesh_compatibility,
        "COMPATIBILITY_FILE",
        tmp_path / "mesh_compatibility_usage.json",
    )
    mesh_compatibility.record_legacy_agent_id_lookup(
        "peer-sensitive-123",
        lookup_kind="dh_pubkey",
        blocked=False,
    )
    mesh_compatibility.record_legacy_dm_get(operation="count", blocked=False)
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        main,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": False, "rns_ready": False},
    )
    monkeypatch.setattr(main, "_current_private_lane_tier", lambda *_args, **_kwargs: "private_control_only")
    monkeypatch.setattr(main, "_refresh_lookup_handle_rotation_background", lambda **_kwargs: {"ok": True, "rotated": False})
    monkeypatch.setattr(main, "lookup_handle_rotation_status_snapshot", lambda: {"state": "lookup_handle_rotation_ok"})
    monkeypatch.setattr(main.private_transport_manager, "observe_state", lambda **_kwargs: {"status": {"label": "Preparing private lane"}})
    monkeypatch.setattr(main.private_delivery_outbox, "summary", lambda **_kwargs: {"items": [], "counts": {}})
    monkeypatch.setattr(main, "local_custody_status_snapshot", lambda: {"state": "protected_at_rest"})
    monkeypatch.setattr(main, "_strong_claims_policy_snapshot", lambda **_kwargs: {"allowed": False, "compatibility": {}})
    monkeypatch.setattr(main, "_privacy_core_status", lambda: {"attestation_state": "attested_current"})
    monkeypatch.setattr(main, "_release_gate_status", lambda **_kwargs: {"allowed": False})
    monkeypatch.setattr(main, "_resume_private_delivery_background_work", lambda **_kwargs: None)

    result = asyncio.run(main.api_wormhole_status(_request("/api/wormhole/status")))

    assert "legacy_compatibility" not in result
    assert result["compatibility_debt"]["legacy_lookup_reliance"]["active"] is True
    assert result["compatibility_debt"]["legacy_mailbox_get_reliance"]["active"] is True
    assert "peer-sensitive-123" not in str(result)
    assert "recent_targets" not in str(result)
    assert "recent_kinds" not in str(result)


def test_diagnostic_status_can_expose_full_legacy_compatibility_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(mesh_compatibility, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        mesh_compatibility,
        "COMPATIBILITY_FILE",
        tmp_path / "mesh_compatibility_usage.json",
    )
    mesh_compatibility.record_legacy_agent_id_lookup(
        "peer-diagnostic-123",
        lookup_kind="prekey_bundle",
        blocked=False,
    )
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        main,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": False, "rns_ready": False},
    )
    monkeypatch.setattr(main, "_current_private_lane_tier", lambda *_args, **_kwargs: "private_control_only")
    monkeypatch.setattr(main, "_refresh_lookup_handle_rotation_background", lambda **_kwargs: {"ok": True, "rotated": False})
    monkeypatch.setattr(main, "lookup_handle_rotation_status_snapshot", lambda: {"state": "lookup_handle_rotation_ok"})
    monkeypatch.setattr(main.private_transport_manager, "observe_state", lambda **_kwargs: {"status": {"label": "Preparing private lane"}})
    monkeypatch.setattr(main.private_delivery_outbox, "summary", lambda **_kwargs: {"items": [], "counts": {}})
    monkeypatch.setattr(main, "local_custody_status_snapshot", lambda: {"state": "protected_at_rest"})
    monkeypatch.setattr(main, "_strong_claims_policy_snapshot", lambda **_kwargs: {"allowed": False, "compatibility": {}})
    monkeypatch.setattr(main, "_privacy_core_status", lambda: {"attestation_state": "attested_current"})
    monkeypatch.setattr(main, "_release_gate_status", lambda **_kwargs: {"allowed": False})
    monkeypatch.setattr(main, "_resume_private_delivery_background_work", lambda **_kwargs: None)

    result = asyncio.run(main.api_wormhole_status(_request("/api/wormhole/status?exposure=diagnostic")))

    assert result["legacy_compatibility"]["usage"]["legacy_agent_id_lookup"]["recent_targets"][0]["agent_id"] == "peer-diagnostic-123"
    assert result["compatibility_debt"]["legacy_lookup_reliance"]["active"] is True


def test_persisted_contact_with_pinned_invite_handle_upgrades_locally_to_invite_scoped_use(tmp_path, monkeypatch):
    monkeypatch.setattr(mesh_wormhole_contacts, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        mesh_wormhole_contacts,
        "CONTACTS_FILE",
        tmp_path / "wormhole_dm_contacts.json",
    )
    mesh_wormhole_contacts._write_contacts(
        {
            "peer-upgrade-1": {
                "alias": "Peer Upgrade",
                "invitePinnedPrekeyLookupHandle": "invite-upgrade-1",
                "remotePrekeyLookupMode": "legacy_agent_id",
            }
        }
    )

    contacts = mesh_wormhole_contacts.list_wormhole_dm_contacts()
    readiness = mesh_wormhole_contacts.compatibility_lookup_readiness_snapshot()

    assert contacts["peer-upgrade-1"]["remotePrekeyLookupMode"] == "invite_lookup_handle"
    assert mesh_wormhole_contacts.preferred_prekey_lookup_handle("peer-upgrade-1") == "invite-upgrade-1"
    assert readiness == {
        "stored_legacy_lookup_contacts_present": False,
        "stored_legacy_lookup_contacts": 0,
        "stored_invite_lookup_contacts": 1,
    }


def test_bootstrap_encrypt_does_not_fallback_to_legacy_direct_lookup_after_invite_path_failure(tmp_path, monkeypatch):
    _pin_contact_with_lookup_handle(tmp_path, monkeypatch, "peer-bootstrap", "invite-bootstrap")
    direct_calls: list[str] = []

    monkeypatch.setattr(
        "services.mesh.mesh_dm_relay.dm_relay.get_prekey_bundle_by_lookup",
        lambda _handle: (None, ""),
    )
    monkeypatch.setattr(
        "services.mesh.mesh_dm_relay.dm_relay.get_prekey_bundle",
        lambda agent_id: direct_calls.append(agent_id) or {"bundle": {}},
    )

    result = mesh_wormhole_prekey.bootstrap_encrypt_for_peer("peer-bootstrap", "hello")

    assert result == {"ok": False, "detail": "peer prekey lookup unavailable"}
    assert direct_calls == []


def test_secure_private_dm_count_with_mailbox_claims_avoids_legacy_get_path(monkeypatch):
    payload = {
        "agent_id": "peer-secure",
        "mailbox_claims": [{"type": "requests", "token": "tok-secure"}],
        "timestamp": int(time.time()),
        "nonce": "nonce-secure",
        "public_key": "pub",
        "public_key_algo": "Ed25519",
        "signature": "sig",
        "sequence": 1,
        "protocol_version": PROTOCOL_VERSION,
        "transport_lock": "private_strong",
    }
    monkeypatch.setattr("services.wormhole_supervisor.get_transport_tier", lambda: "private_strong")
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (False, "no"))
    monkeypatch.setattr(main, "_verify_signed_write", lambda **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        main,
        "_verify_dm_mailbox_request",
        lambda **_kwargs: (True, "ok", {"mailbox_claims": payload["mailbox_claims"]}),
    )
    monkeypatch.setattr(
        "services.mesh.mesh_dm_relay.dm_relay.consume_nonce",
        lambda *_args, **_kwargs: (True, "ok"),
    )
    monkeypatch.setattr(
        "services.mesh.mesh_dm_relay.dm_relay.claim_mailbox_keys",
        lambda *_args, **_kwargs: ["secure-mailbox"],
    )
    monkeypatch.setattr(
        "services.mesh.mesh_dm_relay.dm_relay.claim_message_ids",
        lambda *_args, **_kwargs: {"m1", "m2"},
    )
    monkeypatch.setattr(
        "services.mesh.mesh_hashchain.infonet.validate_and_set_sequence",
        lambda *_args, **_kwargs: (True, "ok"),
    )
    monkeypatch.setattr(main, "_anonymous_dm_hidden_transport_enforced", lambda: True)
    monkeypatch.setattr(
        main,
        "record_legacy_dm_get",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("legacy GET path should not record usage")),
    )
    monkeypatch.setattr(
        "services.mesh.mesh_dm_relay.dm_relay.count_legacy",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("legacy GET counter should not run")),
    )

    result = asyncio.run(
        main.dm_count_secure(_json_request("/api/mesh/dm/count", payload))
    )

    assert result == {"ok": True, "count": 5}


def test_ordinary_wormhole_status_reports_identifier_free_compatibility_readiness(tmp_path, monkeypatch):
    monkeypatch.setattr(mesh_wormhole_contacts, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        mesh_wormhole_contacts,
        "CONTACTS_FILE",
        tmp_path / "wormhole_dm_contacts.json",
    )
    monkeypatch.setattr(mesh_compatibility, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        mesh_compatibility,
        "COMPATIBILITY_FILE",
        tmp_path / "mesh_compatibility_usage.json",
    )
    mesh_wormhole_contacts._write_contacts(
        {
            "peer-ready-1": {
                "invitePinnedPrekeyLookupHandle": "invite-ready-1",
                "remotePrekeyLookupMode": "legacy_agent_id",
            }
        }
    )
    mesh_compatibility.record_legacy_agent_id_lookup(
        "peer-runtime-legacy",
        lookup_kind="prekey_bundle",
        blocked=False,
    )
    mesh_compatibility.record_legacy_dm_get(operation="count", blocked=False)
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        main,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": False, "rns_ready": False},
    )
    monkeypatch.setattr(main, "_current_private_lane_tier", lambda *_args, **_kwargs: "private_control_only")
    monkeypatch.setattr(main, "_refresh_lookup_handle_rotation_background", lambda **_kwargs: {"ok": True, "rotated": False})
    monkeypatch.setattr(main, "lookup_handle_rotation_status_snapshot", lambda: {"state": "lookup_handle_rotation_ok"})
    monkeypatch.setattr(main.private_transport_manager, "observe_state", lambda **_kwargs: {"status": {"label": "Preparing private lane"}})
    monkeypatch.setattr(main.private_delivery_outbox, "summary", lambda **_kwargs: {"items": [], "counts": {}})
    monkeypatch.setattr(main, "local_custody_status_snapshot", lambda: {"state": "protected_at_rest"})
    monkeypatch.setattr(main, "_strong_claims_policy_snapshot", lambda **_kwargs: {"allowed": False, "compatibility": {}})
    monkeypatch.setattr(main, "_privacy_core_status", lambda: {"attestation_state": "attested_current"})
    monkeypatch.setattr(main, "_release_gate_status", lambda **_kwargs: {"allowed": False})
    monkeypatch.setattr(main, "_resume_private_delivery_background_work", lambda **_kwargs: None)

    result = asyncio.run(main.api_wormhole_status(_request("/api/wormhole/status")))

    assert result["compatibility_readiness"] == {
        "stored_legacy_lookup_contacts_present": False,
        "stored_legacy_lookup_contacts": 0,
        "stored_invite_lookup_contacts": 1,
        "legacy_lookup_runtime_active": True,
        "legacy_mailbox_get_runtime_active": True,
        "legacy_mailbox_get_enabled": False,
        "local_contact_upgrade_ok": True,
        "upgraded_contact_preferences": 0,
    }
    assert "legacy_compatibility" not in result
    assert "peer-ready-1" not in str(result)
    assert "peer-runtime-legacy" not in str(result)
    assert "invite-ready-1" not in str(result)
