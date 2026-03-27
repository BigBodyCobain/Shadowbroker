import asyncio
import json
import time

from starlette.requests import Request


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


def test_dm_send_keeps_encrypted_payloads_off_ledger(monkeypatch):
    import main
    from services import wormhole_supervisor
    from services.mesh import mesh_hashchain, mesh_dm_relay

    append_called = {"value": False}

    monkeypatch.setattr(
        main,
        "_verify_signed_event",
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
            "sender_id": "alice",
            "recipient_id": "bob",
            "delivery_class": "request",
            "recipient_token": "",
            "ciphertext": "x3dh1:opaque",
            "msg_id": "m1",
            "timestamp": int(time.time()),
            "public_key": "cHVi",
            "public_key_algo": "Ed25519",
            "signature": "sig",
            "sequence": 1,
            "protocol_version": "infonet/2",
        },
    )

    response = asyncio.run(main.dm_send(req))

    assert response["ok"] is True
    assert append_called["value"] is False


def test_dm_key_registration_keeps_key_material_off_ledger(monkeypatch):
    import main
    from services.mesh import mesh_hashchain, mesh_dm_relay

    append_called = {"value": False}

    monkeypatch.setattr(
        main,
        "_verify_signed_event",
        lambda **kwargs: (True, ""),
    )

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
    assert issued["dm_identity_id"] == dm_identity["node_id"]
    assert issued["contact"]["sharedAlias"] == issued["shared_alias"]
    assert issued["contact"]["dhPubKey"] == "dhpub_alpha"


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

    assert promoted["sharedAlias"] == rotated["pending_alias"]
    assert promoted["pendingSharedAlias"] == ""
    assert promoted["sharedAliasGraceUntil"] == 0
    assert initial["shared_alias"] in promoted["previousSharedAliases"]
