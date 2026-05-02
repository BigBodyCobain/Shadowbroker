import asyncio
import json
import time

from starlette.requests import Request

from services.config import get_settings


def _json_request(path: str, body: dict) -> Request:
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
            "path": path,
        },
        receive,
    )


def test_dm_send_keeps_encrypted_payloads_off_ledger(tmp_path, monkeypatch):
    import main
    from services import wormhole_supervisor
    from services.mesh import mesh_hashchain, mesh_dm_relay, mesh_wormhole_contacts

    append_called = {"value": False}

    monkeypatch.setattr(mesh_wormhole_contacts, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_contacts, "CONTACTS_FILE", tmp_path / "wormhole_dm_contacts.json")
    mesh_wormhole_contacts.observe_remote_prekey_identity("bob", fingerprint="aa" * 32)
    monkeypatch.setattr(
        mesh_wormhole_contacts,
        "_derive_expected_contact_sas_phrase",
        lambda *_args, **_kwargs: {"ok": True, "phrase": "able acid", "peer_ref": "bob", "words": 2},
    )
    mesh_wormhole_contacts.confirm_sas_verification("bob", "able acid")

    monkeypatch.setattr(
        main,
        "_verify_signed_write",
        lambda **kwargs: (True, ""),
    )
    monkeypatch.setattr(main, "_secure_dm_enabled", lambda: False)
    monkeypatch.setattr(wormhole_supervisor, "get_transport_tier", lambda: "private_transitional")

    def fake_append(**kwargs):
        append_called["value"] = True
        return {"event_id": "unexpected"}

    monkeypatch.setattr(mesh_hashchain.infonet, "append", fake_append)
    monkeypatch.setattr(mesh_hashchain.infonet, "validate_and_set_sequence", lambda *_args, **_kwargs: (True, ""))
    monkeypatch.setattr(mesh_dm_relay.dm_relay, "consume_nonce", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        main,
        "consume_wormhole_dm_sender_token",
        lambda **kwargs: {
            "ok": True,
            "sender_token_hash": "reqtok-offledger",
            "sender_id": "alice",
            "public_key": "cHVi",
            "public_key_algo": "Ed25519",
            "protocol_version": "infonet/2",
            "recipient_id": kwargs.get("recipient_id", "") or "bob",
            "delivery_class": kwargs.get("delivery_class", "") or "request",
        },
    )
    monkeypatch.setattr(
        mesh_dm_relay.dm_relay,
        "deposit",
        lambda **kwargs: {
            "ok": True,
            "msg_id": kwargs.get("msg_id", ""),
            "detail": "stored",
        },
    )

    req = _json_request(
        "/api/mesh/dm/send",
        {
            "sender_id": "",
            "sender_token": "opaque-request-token",
            "recipient_id": "",
            "delivery_class": "request",
            "recipient_token": "",
            "ciphertext": "x3dh1:opaque",
            "msg_id": "m1",
            "timestamp": int(time.time()),
            "public_key": "",
            "public_key_algo": "",
            "signature": "sig",
            "sequence": 1,
            "protocol_version": "",
            "transport_lock": "private_strong",
        },
    )

    response = asyncio.run(main.dm_send(req))

    assert response["ok"] is True
    assert append_called["value"] is False


def test_dm_request_send_rejects_unverified_first_contact(tmp_path, monkeypatch):
    import main
    from services import wormhole_supervisor
    from services.mesh import mesh_dm_relay, mesh_wormhole_contacts

    monkeypatch.setattr(mesh_wormhole_contacts, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_contacts, "CONTACTS_FILE", tmp_path / "wormhole_dm_contacts.json")
    monkeypatch.setattr(main, "_verify_signed_write", lambda **kwargs: (True, ""))
    monkeypatch.setattr(main, "_secure_dm_enabled", lambda: False)
    monkeypatch.setattr(wormhole_supervisor, "get_transport_tier", lambda: "private_transitional")
    monkeypatch.setattr(mesh_dm_relay.dm_relay, "consume_nonce", lambda *_args, **_kwargs: (True, "ok"))

    req = _json_request(
        "/api/mesh/dm/send",
        {
            "sender_id": "alice",
            "recipient_id": "bob",
            "delivery_class": "request",
            "recipient_token": "",
            "ciphertext": "x3dh1:opaque",
            "msg_id": "m2",
            "timestamp": int(time.time()),
            "public_key": "cHVi",
            "public_key_algo": "Ed25519",
            "signature": "sig",
            "sequence": 1,
            "protocol_version": "infonet/2",
            "transport_lock": "private_strong",
        },
    )

    response = asyncio.run(main.dm_send(req))

    assert response["ok"] is False
    assert response["detail"] == "signed invite or SAS verification required before secure first contact"
    assert response["trust_level"] == "unpinned"


def test_dm_key_registration_keeps_key_material_off_ledger(monkeypatch):
    import main
    from services import wormhole_supervisor
    from services.mesh import mesh_hashchain, mesh_dm_relay

    append_called = {"value": False}

    monkeypatch.setattr(
        main,
        "_verify_signed_write",
        lambda **kwargs: (True, ""),
    )
    monkeypatch.setattr(wormhole_supervisor, "get_transport_tier", lambda: "private_strong")

    def fake_append(**kwargs):
        append_called["value"] = True
        return {"event_id": "unexpected"}

    monkeypatch.setattr(mesh_hashchain.infonet, "append", fake_append)
    monkeypatch.setattr(
        mesh_dm_relay.dm_relay,
        "register_dh_key",
        lambda *args, **kwargs: (True, "ok", {"bundle_fingerprint": "bf", "accepted_sequence": 1}),
    )

    req = _json_request(
        "/api/mesh/dm/register",
        {
            "agent_id": "alice",
            "dh_pub_key": "dhpub",
            "dh_algo": "X25519",
            "timestamp": int(time.time()),
            "public_key": "cHVi",
            "public_key_algo": "Ed25519",
            "signature": "sig",
            "sequence": 1,
            "protocol_version": "infonet/2",
            "transport_lock": "private_strong",
        },
    )

    response = asyncio.run(main.dm_register_key(req))

    assert response["ok"] is True
    assert append_called["value"] is False


def test_wormhole_dm_key_registration_keeps_key_material_off_ledger(tmp_path, monkeypatch):
    import main
    from services.mesh import (
        mesh_hashchain,
        mesh_secure_storage,
        mesh_wormhole_persona,
    )

    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    monkeypatch.setattr(mesh_wormhole_persona, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_persona, "PERSONA_FILE", tmp_path / "wormhole_persona.json")
    monkeypatch.setattr(
        mesh_wormhole_persona,
        "LEGACY_DM_IDENTITY_FILE",
        tmp_path / "wormhole_identity.json",
    )

    append_called = {"value": False}

    def fake_append(**kwargs):
        append_called["value"] = True
        return {"event_id": "unexpected"}

    monkeypatch.setattr(mesh_hashchain.infonet, "append", fake_append)
    monkeypatch.setattr(
        main,
        "register_wormhole_prekey_bundle",
        lambda *args, **kwargs: {"ok": True, "bundle": {}},
    )

    response = asyncio.run(main.api_wormhole_dm_register_key(_json_request("/api/wormhole/dm/register-key", {})))

    assert response["ok"] is True
    assert append_called["value"] is False
    assert response["dm_key_ok"] is True
    assert response["prekeys_ok"] is True


def test_dm_register_key_returns_partial_prep_state(monkeypatch):
    import main

    monkeypatch.setattr(main, "register_wormhole_dm_key", lambda: {"ok": False, "detail": "dm_key_unavailable"})
    monkeypatch.setattr(main, "register_wormhole_prekey_bundle", lambda: {"ok": True, "agent_id": "node-epsilon"})

    response = asyncio.run(main.api_wormhole_dm_register_key(_json_request("/api/wormhole/dm/register-key", {})))

    assert response["ok"] is False
    assert response["dm_key_ok"] is False
    assert response["prekeys_ok"] is True
    assert response["dm_ready"] is False
    assert response["dm_key_detail"]["detail"] == "dm_key_unavailable"
    assert response["prekey_detail"]["agent_id"] == "node-epsilon"


def test_identity_bootstrap_prepares_dm_receive_state(monkeypatch):
    import main

    monkeypatch.setattr(main, "bootstrap_wormhole_identity", lambda: {"ok": True})
    monkeypatch.setattr(main, "bootstrap_wormhole_persona_state", lambda: {"ok": True})
    monkeypatch.setattr(
        main,
        "get_transport_identity",
        lambda: {"ok": True, "node_id": "node-alpha", "dh_pub_key": "dhpub-alpha"},
    )
    monkeypatch.setattr(main, "register_wormhole_dm_key", lambda: {"ok": True, "bundle_registered_at": 123})
    monkeypatch.setattr(main, "register_wormhole_prekey_bundle", lambda: {"ok": True, "agent_id": "node-alpha"})

    response = asyncio.run(main.api_wormhole_identity_bootstrap(_json_request("/api/wormhole/identity/bootstrap", {})))

    assert response["ok"] is True
    assert response["node_id"] == "node-alpha"
    assert response["dm_key_ok"] is True
    assert response["prekeys_ok"] is True
    assert response["dm_ready"] is True
    assert response["dm_key_detail"]["bundle_registered_at"] == 123
    assert response["prekey_detail"]["agent_id"] == "node-alpha"


def test_identity_bootstrap_returns_identity_even_when_dm_prep_is_partial(monkeypatch):
    import main

    monkeypatch.setattr(main, "bootstrap_wormhole_identity", lambda: {"ok": True})
    monkeypatch.setattr(main, "bootstrap_wormhole_persona_state", lambda: {"ok": True})
    monkeypatch.setattr(
        main,
        "get_transport_identity",
        lambda: {"ok": True, "node_id": "node-beta", "dh_pub_key": "dhpub-beta"},
    )
    monkeypatch.setattr(main, "register_wormhole_dm_key", lambda: {"ok": False, "detail": "dm_key_unavailable"})
    monkeypatch.setattr(main, "register_wormhole_prekey_bundle", lambda: {"ok": True, "agent_id": "node-beta"})

    response = asyncio.run(main.api_wormhole_identity_bootstrap(_json_request("/api/wormhole/identity/bootstrap", {})))

    assert response["ok"] is True
    assert response["node_id"] == "node-beta"
    assert response["dm_key_ok"] is False
    assert response["prekeys_ok"] is True
    assert response["dm_ready"] is False
    assert response["dm_key_detail"]["detail"] == "dm_key_unavailable"


def test_prekey_register_prepares_dm_receive_state(monkeypatch):
    import main

    monkeypatch.setattr(main, "register_wormhole_dm_key", lambda: {"ok": True, "bundle_registered_at": 456})
    monkeypatch.setattr(main, "register_wormhole_prekey_bundle", lambda: {"ok": True, "agent_id": "node-gamma"})

    response = asyncio.run(main.api_wormhole_dm_prekey_register(_json_request("/api/wormhole/dm/prekey/register", {})))

    assert response["ok"] is True
    assert response["dm_key_ok"] is True
    assert response["prekeys_ok"] is True
    assert response["dm_ready"] is True
    assert response["dm_key_detail"]["bundle_registered_at"] == 456
    assert response["prekey_detail"]["agent_id"] == "node-gamma"


def test_prekey_register_returns_partial_prep_state(monkeypatch):
    import main

    monkeypatch.setattr(main, "register_wormhole_dm_key", lambda: {"ok": False, "detail": "dm_key_unavailable"})
    monkeypatch.setattr(main, "register_wormhole_prekey_bundle", lambda: {"ok": True, "agent_id": "node-delta"})

    response = asyncio.run(main.api_wormhole_dm_prekey_register(_json_request("/api/wormhole/dm/prekey/register", {})))

    assert response["ok"] is True
    assert response["dm_key_ok"] is False
    assert response["prekeys_ok"] is True
    assert response["dm_ready"] is False
    assert response["dm_key_detail"]["detail"] == "dm_key_unavailable"
    assert response["prekey_detail"]["agent_id"] == "node-delta"


def test_wormhole_dm_helper_request_models_allow_inferred_peer_material():
    import main

    open_req = main.WormholeOpenSealRequest(
        sender_seal="v3:test",
        recipient_id="peer-open",
        expected_msg_id="msg-open",
    )
    build_req = main.WormholeBuildSealRequest(
        recipient_id="peer-build",
        msg_id="msg-build",
        timestamp=123,
    )
    dead_drop_req = main.WormholeDeadDropTokenRequest(peer_id="peer-dead-drop")
    sas_req = main.WormholeSasRequest(peer_id="peer-sas")

    assert open_req.candidate_dh_pub == ""
    assert build_req.recipient_dh_pub == ""
    assert dead_drop_req.peer_dh_pub == ""
    assert sas_req.peer_dh_pub == ""


def test_dead_drop_contact_consent_helpers_round_trip():
    from services.mesh.mesh_wormhole_dead_drop import (
        build_contact_accept,
        build_contact_deny,
        build_contact_offer,
        parse_contact_consent,
    )

    offer = build_contact_offer(dh_pub_key="dhpub", dh_algo="X25519", geo_hint="40.12,-105.27")
    accept = build_contact_accept(shared_alias="dmx_pairwise")
    deny = build_contact_deny(reason="declined")

    assert parse_contact_consent(offer) == {
        "kind": "contact_offer",
        "dh_pub_key": "dhpub",
        "dh_algo": "X25519",
        "geo_hint": "40.12,-105.27",
    }
    assert parse_contact_consent(accept) == {
        "kind": "contact_accept",
        "shared_alias": "dmx_pairwise",
    }
    assert parse_contact_consent(deny) == {
        "kind": "contact_deny",
        "reason": "declined",
    }


def test_pairwise_alias_is_separate_from_gate_identities(tmp_path, monkeypatch):
    from services.mesh import (
        mesh_secure_storage,
        mesh_wormhole_contacts,
        mesh_wormhole_dead_drop,
        mesh_wormhole_persona,
    )

    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    monkeypatch.setattr(mesh_wormhole_persona, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_persona, "PERSONA_FILE", tmp_path / "wormhole_persona.json")
    monkeypatch.setattr(
        mesh_wormhole_persona,
        "LEGACY_DM_IDENTITY_FILE",
        tmp_path / "wormhole_identity.json",
    )
    monkeypatch.setattr(mesh_wormhole_contacts, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_contacts, "CONTACTS_FILE", tmp_path / "wormhole_dm_contacts.json")

    gate_session = mesh_wormhole_persona.enter_gate_anonymously("infonet", rotate=True)["identity"]
    gate_persona = mesh_wormhole_persona.create_gate_persona("infonet", label="watcher")["identity"]
    dm_identity = mesh_wormhole_persona.get_dm_identity()

    issued = mesh_wormhole_dead_drop.issue_pairwise_dm_alias(
        peer_id="peer_alpha",
        peer_dh_pub="dhpub_alpha",
    )

    assert issued["ok"] is True
    assert issued["identity_scope"] == "dm_alias"
    assert issued["shared_alias"].startswith("dmx_")
    assert issued["shared_alias"] != gate_session["node_id"]
    assert issued["shared_alias"] != gate_persona["node_id"]
    assert issued["shared_alias"] != dm_identity["node_id"]
    assert issued["dm_identity_id"] == mesh_wormhole_dead_drop.dead_drop_redact_label(dm_identity["node_id"])
    assert issued["contact"]["dmIdentityId"] == issued["dm_identity_id"]
    assert issued["contact"]["sharedAlias"] == issued["shared_alias"]
    assert issued["contact"]["dhPubKey"] == "dhpub_alpha"


def test_pairwise_alias_uses_invite_pinned_dh_key_when_explicit_missing(tmp_path, monkeypatch):
    from services.mesh import (
        mesh_secure_storage,
        mesh_wormhole_dead_drop,
        mesh_wormhole_persona,
    )

    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    monkeypatch.setattr(mesh_wormhole_persona, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_persona, "PERSONA_FILE", tmp_path / "wormhole_persona.json")
    monkeypatch.setattr(
        mesh_wormhole_persona,
        "LEGACY_DM_IDENTITY_FILE",
        tmp_path / "wormhole_identity.json",
    )
    monkeypatch.setattr(
        mesh_wormhole_dead_drop,
        "list_wormhole_dm_contacts",
        lambda: {
            "peer_invite_alias": {
                "invitePinnedDhPubKey": "invite-dh-alpha",
            }
        },
    )

    issued = mesh_wormhole_dead_drop.issue_pairwise_dm_alias(
        peer_id="peer_invite_alias",
        peer_dh_pub="",
    )

    assert issued["ok"] is True
    assert issued["contact"]["dhPubKey"] == "invite-dh-alpha"


def test_pairwise_alias_rotation_promotes_after_grace(tmp_path, monkeypatch):
    from services.mesh import (
        mesh_secure_storage,
        mesh_wormhole_contacts,
        mesh_wormhole_dead_drop,
        mesh_wormhole_persona,
    )

    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    monkeypatch.setattr(mesh_wormhole_persona, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_persona, "PERSONA_FILE", tmp_path / "wormhole_persona.json")
    monkeypatch.setattr(
        mesh_wormhole_persona,
        "LEGACY_DM_IDENTITY_FILE",
        tmp_path / "wormhole_identity.json",
    )
    monkeypatch.setattr(mesh_wormhole_contacts, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_contacts, "CONTACTS_FILE", tmp_path / "wormhole_dm_contacts.json")

    initial = mesh_wormhole_dead_drop.issue_pairwise_dm_alias(
        peer_id="peer_beta",
        peer_dh_pub="dhpub_beta",
    )
    rotated = mesh_wormhole_dead_drop.rotate_pairwise_dm_alias(
        peer_id="peer_beta",
        peer_dh_pub="dhpub_beta",
        grace_ms=5_000,
    )

    assert rotated["ok"] is True
    assert rotated["active_alias"] == initial["shared_alias"]
    assert rotated["pending_alias"].startswith("dmx_")
    assert rotated["pending_alias"] != initial["shared_alias"]
    assert rotated["contact"]["sharedAlias"] == initial["shared_alias"]
    assert rotated["contact"]["pendingSharedAlias"] == rotated["pending_alias"]
    assert rotated["contact"]["sharedAliasGraceUntil"] >= rotated["grace_until"]

    future = rotated["grace_until"] / 1000.0 + 1
    monkeypatch.setattr(mesh_wormhole_contacts.time, "time", lambda: future)
    promoted = mesh_wormhole_contacts.list_wormhole_dm_contacts()["peer_beta"]

    assert promoted["sharedAlias"] == initial["shared_alias"]
    assert promoted["pendingSharedAlias"] == rotated["pending_alias"]
    assert promoted["sharedAliasGraceUntil"] >= rotated["grace_until"]
    assert initial["shared_alias"] in promoted["previousSharedAliases"]


def test_pairwise_alias_rotation_uses_invite_pinned_dh_key_when_explicit_missing(tmp_path, monkeypatch):
    from services.mesh import (
        mesh_secure_storage,
        mesh_wormhole_dead_drop,
        mesh_wormhole_persona,
    )

    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    monkeypatch.setattr(mesh_wormhole_persona, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_persona, "PERSONA_FILE", tmp_path / "wormhole_persona.json")
    monkeypatch.setattr(
        mesh_wormhole_persona,
        "LEGACY_DM_IDENTITY_FILE",
        tmp_path / "wormhole_identity.json",
    )
    monkeypatch.setattr(
        mesh_wormhole_dead_drop,
        "list_wormhole_dm_contacts",
        lambda: {
            "peer_invite_rotate": {
                "sharedAlias": "dmx_existing",
                "invitePinnedDhPubKey": "invite-dh-beta",
            }
        },
    )

    rotated = mesh_wormhole_dead_drop.rotate_pairwise_dm_alias(
        peer_id="peer_invite_rotate",
        peer_dh_pub="",
        grace_ms=30_000,
    )

    assert rotated["ok"] is True
    assert rotated["contact"]["dhPubKey"] == "invite-dh-beta"


def test_pairwise_alias_contact_summary_marks_pending_promotion(tmp_path, monkeypatch):
    from services.mesh import (
        mesh_secure_storage,
        mesh_wormhole_contacts,
        mesh_wormhole_dead_drop,
        mesh_wormhole_persona,
    )

    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    monkeypatch.setattr(mesh_wormhole_persona, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_persona, "PERSONA_FILE", tmp_path / "wormhole_persona.json")
    monkeypatch.setattr(
        mesh_wormhole_persona,
        "LEGACY_DM_IDENTITY_FILE",
        tmp_path / "wormhole_identity.json",
    )
    monkeypatch.setattr(mesh_wormhole_contacts, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_contacts, "CONTACTS_FILE", tmp_path / "wormhole_dm_contacts.json")

    mesh_wormhole_dead_drop.issue_pairwise_dm_alias(
        peer_id="peer_alias_pending",
        peer_dh_pub="dhpub_pending",
    )
    rotated = mesh_wormhole_dead_drop.rotate_pairwise_dm_alias(
        peer_id="peer_alias_pending",
        peer_dh_pub="dhpub_pending",
        grace_ms=30_000,
    )

    summary = rotated["contact"]["aliasSummary"]
    assert summary["state"] == "pending_promotion"
    assert summary["hasActiveAlias"] is True
    assert summary["hasPendingAlias"] is True
    assert summary["graceRemainingMs"] > 0
    assert summary["canPrepareRotation"] is False
    assert summary["backgroundPrepareAllowed"] is False
    assert summary["recommendedAction"] == "wait_for_promotion"


def test_pairwise_alias_contact_summary_marks_verified_contact_background_ready(tmp_path, monkeypatch):
    from services.mesh import mesh_secure_storage, mesh_wormhole_contacts

    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    monkeypatch.setattr(mesh_wormhole_contacts, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_contacts, "CONTACTS_FILE", tmp_path / "wormhole_dm_contacts.json")

    mesh_wormhole_contacts.upsert_wormhole_dm_contact(
        "peer_alias_ready",
        {
            "sharedAlias": "dmx_ready",
            "dhPubKey": "dhpub_ready",
        },
    )
    contact = mesh_wormhole_contacts.pin_wormhole_dm_invite(
        "peer_alias_ready",
        invite_payload={
            "trust_fingerprint": "fp-ready",
            "identity_dh_pub_key": "dhpub_ready",
        },
        attested=True,
    )

    summary = contact["aliasSummary"]
    assert summary["state"] == "active"
    assert summary["hasPeerDh"] is True
    assert summary["verifiedFirstContact"] is True
    assert summary["canPrepareRotation"] is True
    assert summary["backgroundPrepareAllowed"] is True
    assert summary["recommendedAction"] == "rotate_when_needed"


def test_pairwise_alias_contact_summary_keeps_background_prepare_off_for_tofu(tmp_path, monkeypatch):
    from services.mesh import mesh_secure_storage, mesh_wormhole_contacts

    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    monkeypatch.setattr(mesh_wormhole_contacts, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_contacts, "CONTACTS_FILE", tmp_path / "wormhole_dm_contacts.json")

    mesh_wormhole_contacts.upsert_wormhole_dm_contact(
        "peer_alias_tofu",
        {
            "sharedAlias": "dmx_tofu",
            "dhPubKey": "dhpub_tofu",
        },
    )
    contact = mesh_wormhole_contacts.pin_wormhole_dm_invite(
        "peer_alias_tofu",
        invite_payload={
            "trust_fingerprint": "fp-tofu",
            "identity_dh_pub_key": "dhpub_tofu",
        },
        attested=False,
    )

    summary = contact["aliasSummary"]
    assert summary["state"] == "active"
    assert summary["canPrepareRotation"] is True
    assert summary["backgroundPrepareAllowed"] is False
    assert summary["recommendedAction"] == "verify_sas"


def test_backend_dm_alias_resolution_prefers_shared_alias(tmp_path, monkeypatch):
    import main
    from services.mesh import mesh_secure_storage, mesh_wormhole_contacts

    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    monkeypatch.setattr(mesh_wormhole_contacts, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_contacts, "CONTACTS_FILE", tmp_path / "wormhole_dm_contacts.json")

    mesh_wormhole_contacts.upsert_wormhole_dm_contact(
        "peer_gamma",
        {
            "sharedAlias": "dmx_pairwise_gamma",
            "dhPubKey": "dhpub_gamma",
        },
    )

    local_alias, remote_alias = main._resolve_dm_aliases(
        peer_id="peer_gamma",
        local_alias=None,
        remote_alias=None,
    )

    assert local_alias.startswith("dm-")
    assert remote_alias == "dmx_pairwise_gamma"


def test_dead_drop_token_pair_prefers_shared_alias_context(tmp_path, monkeypatch):
    from services.mesh import (
        mesh_secure_storage,
        mesh_wormhole_contacts,
        mesh_wormhole_dead_drop,
    )
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import x25519
    import base64

    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    monkeypatch.setattr(mesh_wormhole_contacts, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_contacts, "CONTACTS_FILE", tmp_path / "wormhole_dm_contacts.json")
    mesh_secure_storage._MASTER_KEY_CACHE = None
    mesh_secure_storage._DOMAIN_KEY_CACHE.clear()
    peer_dh_pub = base64.b64encode(
        x25519.X25519PrivateKey.generate().public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode("ascii")

    mesh_wormhole_contacts.upsert_wormhole_dm_contact(
        "peer_delta",
        {
            "sharedAlias": "dmx_delta",
            "dhPubKey": peer_dh_pub,
        },
    )

    alias_pair = mesh_wormhole_dead_drop.derive_dead_drop_token_pair(
        peer_id="peer_delta",
        peer_dh_pub=peer_dh_pub,
    )
    public_pair = mesh_wormhole_dead_drop.derive_dead_drop_token_pair(
        peer_id="peer_delta",
        peer_dh_pub=peer_dh_pub,
        peer_ref="peer_delta",
    )

    assert alias_pair["ok"] is True
    assert alias_pair["peer_ref"] == "dmx_delta"
    assert public_pair["ok"] is True
    assert public_pair["peer_ref"] == "peer_delta"
    assert alias_pair["current"] != public_pair["current"]


def test_sas_phrase_prefers_shared_alias_context(tmp_path, monkeypatch):
    from services.mesh import (
        mesh_secure_storage,
        mesh_wormhole_contacts,
        mesh_wormhole_dead_drop,
    )
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import x25519
    import base64

    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    monkeypatch.setattr(mesh_wormhole_contacts, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_contacts, "CONTACTS_FILE", tmp_path / "wormhole_dm_contacts.json")
    peer_dh_pub = base64.b64encode(
        x25519.X25519PrivateKey.generate().public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode("ascii")

    mesh_wormhole_contacts.upsert_wormhole_dm_contact(
        "peer_sigma",
        {
            "sharedAlias": "dmx_sigma",
            "dhPubKey": peer_dh_pub,
        },
    )
    mesh_secure_storage._MASTER_KEY_CACHE = None
    mesh_secure_storage._DOMAIN_KEY_CACHE.clear()

    alias_phrase = mesh_wormhole_dead_drop.derive_sas_phrase(
        peer_id="peer_sigma",
        peer_dh_pub=peer_dh_pub,
        words=6,
    )
    public_phrase = mesh_wormhole_dead_drop.derive_sas_phrase(
        peer_id="peer_sigma",
        peer_dh_pub=peer_dh_pub,
        words=6,
        peer_ref="peer_sigma",
    )

    assert alias_phrase["ok"] is True
    assert alias_phrase["peer_ref"] == "dmx_sigma"
    assert public_phrase["ok"] is True
    assert public_phrase["peer_ref"] == "peer_sigma"
    assert alias_phrase["phrase"] != public_phrase["phrase"]


def test_dead_drop_token_pair_uses_contact_dh_key_when_not_supplied(tmp_path, monkeypatch):
    from services.mesh import (
        mesh_secure_storage,
        mesh_wormhole_contacts,
        mesh_wormhole_dead_drop,
    )
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import x25519
    import base64

    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    monkeypatch.setattr(mesh_wormhole_contacts, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_contacts, "CONTACTS_FILE", tmp_path / "wormhole_dm_contacts.json")
    peer_dh_pub = base64.b64encode(
        x25519.X25519PrivateKey.generate().public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode("ascii")

    mesh_wormhole_contacts.upsert_wormhole_dm_contact(
        "peer_theta",
        {
            "sharedAlias": "dmx_theta",
            "dhPubKey": peer_dh_pub,
        },
    )

    result = mesh_wormhole_dead_drop.derive_dead_drop_token_pair(
        peer_id="peer_theta",
        peer_dh_pub="",
    )

    assert result["ok"] is True
    assert result["peer_ref"] == "dmx_theta"
    assert result["current"]
    assert result["previous"]


def test_sas_phrase_uses_contact_dh_key_when_not_supplied(tmp_path, monkeypatch):
    from services.mesh import (
        mesh_secure_storage,
        mesh_wormhole_contacts,
        mesh_wormhole_dead_drop,
    )
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import x25519
    import base64

    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    monkeypatch.setattr(mesh_wormhole_contacts, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_contacts, "CONTACTS_FILE", tmp_path / "wormhole_dm_contacts.json")
    peer_dh_pub = base64.b64encode(
        x25519.X25519PrivateKey.generate().public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode("ascii")

    mesh_wormhole_contacts.upsert_wormhole_dm_contact(
        "peer_lambda",
        {
            "sharedAlias": "dmx_lambda",
            "dhPubKey": peer_dh_pub,
        },
    )

    result = mesh_wormhole_dead_drop.derive_sas_phrase(
        peer_id="peer_lambda",
        peer_dh_pub="",
        words=4,
    )

    assert result["ok"] is True
    assert result["peer_ref"] == "dmx_lambda"
    assert len(str(result["phrase"]).split()) == 4


def test_compose_wormhole_dm_uses_contact_dh_key_for_legacy_fallback(tmp_path, monkeypatch):
    import main
    from services import wormhole_supervisor
    from services.mesh import mesh_secure_storage, mesh_wormhole_contacts

    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    monkeypatch.setattr(mesh_wormhole_contacts, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_contacts, "CONTACTS_FILE", tmp_path / "wormhole_dm_contacts.json")
    mesh_wormhole_contacts.upsert_wormhole_dm_contact(
        "peer_kappa",
        {
            "sharedAlias": "dmx_kappa",
            "dhPubKey": "dhpub_kappa",
        },
    )

    monkeypatch.setattr(main, "has_mls_dm_session", lambda *_args, **_kwargs: {"ok": True, "exists": False})
    monkeypatch.setattr(main, "fetch_dm_prekey_bundle", lambda *_args, **_kwargs: {"ok": False, "detail": "missing"})
    monkeypatch.setattr(wormhole_supervisor, "get_transport_tier", lambda: "public_degraded")
    monkeypatch.setenv("MESH_DEV_ALLOW_LEGACY_COMPAT", "true")
    monkeypatch.setenv("MESH_ALLOW_LEGACY_DM1_UNTIL", "2099-01-01")
    get_settings.cache_clear()
    monkeypatch.setattr(
        mesh_wormhole_contacts,
        "verified_first_contact_requirement",
        lambda *_args, **_kwargs: {"ok": True, "trust_level": "invite_pinned"},
    )
    monkeypatch.setattr(
        main,
        "encrypt_wormhole_dm",
        lambda *, peer_id, peer_dh_pub, plaintext: {
            "ok": True,
            "result": f"legacy:{peer_id}:{peer_dh_pub}:{plaintext}",
        },
    )

    try:
        result = main.compose_wormhole_dm(
            peer_id="peer_kappa",
            peer_dh_pub="",
            plaintext="hello fallback",
        )
    finally:
        get_settings.cache_clear()

    assert result["ok"] is True
    assert result["peer_id"] == "peer_kappa"
    assert result["local_alias"].startswith("dm-")
    assert result["remote_alias"] == "dmx_kappa"
    assert result["ciphertext"] == "legacy:peer_kappa:dhpub_kappa:hello fallback"
    assert result["nonce"] == ""
    assert result["format"] == "dm1"
    assert result["session_welcome"] == ""
    assert result["local_alias"].startswith("dm-")


def test_compose_wormhole_dm_blocks_legacy_fallback_without_dm1_override(tmp_path, monkeypatch):
    import main
    from services import wormhole_supervisor
    from services.mesh import mesh_secure_storage, mesh_wormhole_contacts

    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    monkeypatch.setattr(mesh_wormhole_contacts, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_contacts, "CONTACTS_FILE", tmp_path / "wormhole_dm_contacts.json")
    mesh_wormhole_contacts.upsert_wormhole_dm_contact(
        "peer_mu",
        {
            "sharedAlias": "dmx_mu",
            "dhPubKey": "dhpub_mu",
        },
    )

    monkeypatch.delenv("MESH_ALLOW_LEGACY_DM1_UNTIL", raising=False)
    get_settings.cache_clear()
    monkeypatch.setattr(main, "has_mls_dm_session", lambda *_args, **_kwargs: {"ok": True, "exists": False})
    monkeypatch.setattr(main, "fetch_dm_prekey_bundle", lambda *_args, **_kwargs: {"ok": False, "detail": "missing"})
    monkeypatch.setattr(wormhole_supervisor, "get_transport_tier", lambda: "public_degraded")
    monkeypatch.setattr(
        mesh_wormhole_contacts,
        "verified_first_contact_requirement",
        lambda *_args, **_kwargs: {"ok": True, "trust_level": "invite_pinned"},
    )

    try:
        result = main.compose_wormhole_dm(
            peer_id="peer_mu",
            peer_dh_pub="",
            plaintext="hello blocked fallback",
        )
    finally:
        get_settings.cache_clear()

    assert result["ok"] is False
    assert result["peer_id"] == "peer_mu"
    assert result["detail"] == "legacy dm1 fallback disabled; MLS bootstrap required"
    assert result["trust_level"] == "unpinned"
