import base64
import asyncio
import json
import time

import pytest
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat
from starlette.requests import Request


def _fresh_mesh_state(tmp_path, monkeypatch):
    from services.mesh import (
        mesh_dm_relay,
        mesh_secure_storage,
        mesh_wormhole_identity,
        mesh_wormhole_persona,
    )

    monkeypatch.setattr(mesh_dm_relay, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_dm_relay, "RELAY_FILE", tmp_path / "dm_relay.json")
    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    monkeypatch.setattr(mesh_wormhole_persona, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_persona, "PERSONA_FILE", tmp_path / "wormhole_persona.json")
    monkeypatch.setattr(
        mesh_wormhole_persona,
        "LEGACY_DM_IDENTITY_FILE",
        tmp_path / "wormhole_identity.json",
    )
    relay = mesh_dm_relay.DMRelay()
    monkeypatch.setattr(mesh_dm_relay, "dm_relay", relay)
    return relay, mesh_wormhole_identity


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


def test_sender_token_can_resolve_recipient_without_clear_recipient_id(tmp_path, monkeypatch):
    _relay, identity_mod = _fresh_mesh_state(tmp_path, monkeypatch)
    identity_mod.bootstrap_wormhole_identity(force=True)

    from services.mesh.mesh_wormhole_sender_token import (
        consume_wormhole_dm_sender_token,
        issue_wormhole_dm_sender_token,
    )

    issued = issue_wormhole_dm_sender_token(
        recipient_id="peer123",
        delivery_class="shared",
        recipient_token="tok123",
    )
    assert issued["ok"]

    consumed = consume_wormhole_dm_sender_token(
        sender_token=issued["sender_token"],
        recipient_id="",
        delivery_class="shared",
        recipient_token="tok123",
    )
    assert consumed["ok"]
    assert consumed["recipient_id"] == "peer123"
    assert consumed["sender_token_hash"]


def test_signed_prekey_rotation_preserves_old_bootstrap_decrypt(tmp_path, monkeypatch):
    _relay, identity_mod = _fresh_mesh_state(tmp_path, monkeypatch)
    identity_mod.bootstrap_wormhole_identity(force=True)

    from services.mesh.mesh_wormhole_prekey import (
        SIGNED_PREKEY_ROTATE_AFTER_S,
        bootstrap_decrypt_from_sender,
        bootstrap_encrypt_for_peer,
        register_wormhole_prekey_bundle,
    )

    reg1 = register_wormhole_prekey_bundle(force_signed_prekey=True)
    assert reg1["ok"]
    agent_id = reg1["agent_id"]

    old_envelope = bootstrap_encrypt_for_peer(agent_id, "ACCESS_REQUEST:X25519:testpub|geo=1,2")
    assert old_envelope["ok"]

    data = identity_mod.read_wormhole_identity()
    data["signed_prekey_generated_at"] = int(time.time()) - SIGNED_PREKEY_ROTATE_AFTER_S - 10
    identity_mod._write_identity(data)

    reg2 = register_wormhole_prekey_bundle()
    assert reg2["ok"]
    assert reg2["bundle"]["signed_prekey_id"] != reg1["bundle"]["signed_prekey_id"]

    refreshed = identity_mod.read_wormhole_identity()
    history = list(refreshed.get("signed_prekey_history") or [])
    assert any(int(item.get("signed_prekey_id", 0) or 0) == reg1["bundle"]["signed_prekey_id"] for item in history)

    dec = bootstrap_decrypt_from_sender(agent_id, old_envelope["result"])
    assert dec["ok"]
    assert dec["result"] == "ACCESS_REQUEST:X25519:testpub|geo=1,2"


def test_prekey_bundle_fetch_rejects_stale_or_tampered_bundle(tmp_path, monkeypatch):
    relay, identity_mod = _fresh_mesh_state(tmp_path, monkeypatch)
    identity_mod.bootstrap_wormhole_identity(force=True)

    from services.mesh import mesh_wormhole_prekey as prekey_mod

    registered = prekey_mod.register_wormhole_prekey_bundle(force_signed_prekey=True)
    assert registered["ok"] is True
    agent_id = registered["agent_id"]

    fresh = prekey_mod.fetch_dm_prekey_bundle(agent_id)
    assert fresh["ok"] is True
    assert int(fresh["signed_at"]) > 0
    assert fresh["bundle_signature"]

    stored = relay.get_prekey_bundle(agent_id)
    stale_bundle = dict(stored.get("bundle") or {})
    stale_bundle["signed_at"] = int(time.time()) - prekey_mod._max_prekey_bundle_age_s() - 10
    stale_bundle = prekey_mod._attach_bundle_signature(stale_bundle, signed_at=stale_bundle["signed_at"])
    relay._prekey_bundles[agent_id]["bundle"] = stale_bundle

    stale = prekey_mod.fetch_dm_prekey_bundle(agent_id)
    assert stale == {"ok": False, "detail": "Prekey bundle is stale"}

    tampered_bundle = dict(stale_bundle)
    tampered_bundle["signed_at"] = int(time.time())
    tampered_bundle = prekey_mod._attach_bundle_signature(tampered_bundle, signed_at=tampered_bundle["signed_at"])
    tampered_bundle["bundle_signature"] = "00" * 64
    relay._prekey_bundles[agent_id]["bundle"] = tampered_bundle

    tampered = prekey_mod.fetch_dm_prekey_bundle(agent_id)
    assert tampered == {"ok": False, "detail": "Prekey bundle signature invalid"}


def test_prekey_bundle_fetch_rejects_future_dated_bundle(tmp_path, monkeypatch):
    relay, identity_mod = _fresh_mesh_state(tmp_path, monkeypatch)
    identity_mod.bootstrap_wormhole_identity(force=True)

    from services.mesh import mesh_wormhole_prekey as prekey_mod

    registered = prekey_mod.register_wormhole_prekey_bundle(force_signed_prekey=True)
    assert registered["ok"] is True
    agent_id = registered["agent_id"]

    stored = relay.get_prekey_bundle(agent_id)
    future_bundle = dict(stored.get("bundle") or {})
    future_bundle["signed_at"] = int(time.time()) + 301
    future_bundle = prekey_mod._attach_bundle_signature(future_bundle, signed_at=future_bundle["signed_at"])
    relay._prekey_bundles[agent_id]["bundle"] = future_bundle

    future = prekey_mod.fetch_dm_prekey_bundle(agent_id)
    assert future == {"ok": False, "detail": "Prekey bundle signed_at is in the future"}


def test_remote_prekey_identity_is_pinned_and_detects_mismatch(tmp_path, monkeypatch):
    _relay, _identity_mod = _fresh_mesh_state(tmp_path, monkeypatch)
    from services.mesh import mesh_wormhole_contacts

    monkeypatch.setattr(mesh_wormhole_contacts, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_contacts, "CONTACTS_FILE", tmp_path / "wormhole_dm_contacts.json")

    pinned = mesh_wormhole_contacts.observe_remote_prekey_identity(
        "peer-alpha",
        fingerprint="aa" * 32,
        sequence=3,
        signed_at=111,
    )
    same = mesh_wormhole_contacts.observe_remote_prekey_identity(
        "peer-alpha",
        fingerprint="aa" * 32,
        sequence=4,
        signed_at=222,
    )
    changed = mesh_wormhole_contacts.observe_remote_prekey_identity(
        "peer-alpha",
        fingerprint="bb" * 32,
        sequence=5,
        signed_at=333,
    )

    assert pinned["trust_changed"] is False
    assert same["trust_changed"] is False
    assert changed["trust_changed"] is True
    stored = mesh_wormhole_contacts.list_wormhole_dm_contacts()["peer-alpha"]
    assert stored["remotePrekeyFingerprint"] == "aa" * 32
    assert stored["remotePrekeyObservedFingerprint"] == "bb" * 32
    assert stored["remotePrekeyMismatch"] is True


def test_compose_wormhole_dm_rejects_remote_prekey_identity_change(tmp_path, monkeypatch):
    _relay, _identity_mod = _fresh_mesh_state(tmp_path, monkeypatch)
    import main
    from services.mesh import mesh_wormhole_contacts

    monkeypatch.setattr(mesh_wormhole_contacts, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_contacts, "CONTACTS_FILE", tmp_path / "wormhole_dm_contacts.json")
    monkeypatch.setattr(main, "has_mls_dm_session", lambda *_args, **_kwargs: {"ok": True, "exists": False})
    monkeypatch.setattr(main, "initiate_mls_dm_session", lambda *_args, **_kwargs: {"ok": True, "welcome": "welcome"})
    monkeypatch.setattr(main, "encrypt_mls_dm", lambda *_args, **_kwargs: {"ok": True, "ciphertext": "ct", "nonce": "n"})

    initial = {
        "ok": True,
        "agent_id": "peer-alpha",
        "mls_key_package": "ZmFrZQ==",
        "identity_dh_pub_key": "peer-dh-pub",
        "public_key": "peer-signing-pub",
        "public_key_algo": "Ed25519",
        "protocol_version": "infonet/2",
        "sequence": 2,
        "signed_at": int(time.time()),
        "trust_fingerprint": "11" * 32,
    }
    changed = {
        **initial,
        "sequence": 3,
        "signed_at": int(time.time()) + 1,
        "trust_fingerprint": "22" * 32,
    }

    first = main.compose_wormhole_dm(
        peer_id="peer-alpha",
        peer_dh_pub="peer-dh-pub",
        plaintext="hello",
        remote_prekey_bundle=initial,
    )
    second = main.compose_wormhole_dm(
        peer_id="peer-alpha",
        peer_dh_pub="peer-dh-pub",
        plaintext="hello again",
        remote_prekey_bundle=changed,
    )

    assert first["ok"] is True
    assert second == {
        "ok": False,
        "peer_id": "peer-alpha",
        "detail": "remote prekey identity changed; verification required",
        "trust_changed": True,
    }


def test_prekey_bundle_registration_rejects_invalid_bundle(tmp_path, monkeypatch):
    relay, identity_mod = _fresh_mesh_state(tmp_path, monkeypatch)
    identity = identity_mod.bootstrap_wormhole_identity(force=True)

    from services.mesh import mesh_wormhole_prekey as prekey_mod

    bundle = prekey_mod.ensure_wormhole_prekeys(force_signed_prekey=True)
    bundle = prekey_mod._attach_bundle_signature(bundle, signed_at=int(time.time()) + 301)

    ok, reason, meta = relay.register_prekey_bundle(
        identity["node_id"],
        bundle,
        "sig",
        identity["public_key"],
        identity["public_key_algo"],
        "infonet/2",
        1,
    )

    assert ok is False
    assert reason == "Prekey bundle signed_at is in the future"
    assert meta is None
    assert relay.get_prekey_bundle(identity["node_id"]) is None


def test_dm_mailbox_token_derivation_and_shared_sender_token_routing(tmp_path, monkeypatch):
    relay, identity_mod = _fresh_mesh_state(tmp_path, monkeypatch)
    identity = identity_mod.bootstrap_wormhole_identity(force=True)

    from services.mesh.mesh_wormhole_identity import derive_dm_mailbox_token
    from services.mesh.mesh_wormhole_sender_token import issue_wormhole_dm_sender_token
    import main
    from services import wormhole_supervisor
    from services.mesh import mesh_dm_relay, mesh_hashchain

    mailbox_token = derive_dm_mailbox_token(identity["node_id"])
    assert mailbox_token

    issued = issue_wormhole_dm_sender_token(
        recipient_id="peer123",
        delivery_class="shared",
        recipient_token=mailbox_token,
    )
    assert issued["ok"] is True

    monkeypatch.setattr(main, "_verify_signed_event", lambda **_kwargs: (True, ""))
    monkeypatch.setattr(main, "_secure_dm_enabled", lambda: False)
    monkeypatch.setattr(wormhole_supervisor, "get_transport_tier", lambda: "private_strong")
    monkeypatch.setattr(mesh_hashchain.infonet, "validate_and_set_sequence", lambda *_args, **_kwargs: (True, ""))
    monkeypatch.setattr(mesh_dm_relay, "dm_relay", relay)

    response = asyncio.run(
        main.dm_send(
            _json_request(
                "/api/mesh/dm/send",
                {
                    "sender_token": issued["sender_token"],
                    "recipient_id": "",
                    "delivery_class": "shared",
                    "recipient_token": mailbox_token,
                    "ciphertext": "cipher-shared",
                    "sender_seal": "v3:test-seal",
                    "msg_id": "shared-msg-1",
                    "timestamp": int(time.time()),
                    "public_key": "",
                    "public_key_algo": "Ed25519",
                    "signature": "sig",
                    "sequence": 1,
                    "protocol_version": "infonet/2",
                },
            )
        )
    )

    assert response["ok"] is True
    hashed_mailbox = relay._hashed_mailbox_token(mailbox_token)
    assert list(relay._mailboxes.keys()) == [hashed_mailbox]
    assert relay._mailboxes[hashed_mailbox][0].sender_id.startswith("sender_token:")
    assert relay._mailboxes[hashed_mailbox][0].sender_id != identity["node_id"]
    delivered = relay.collect_claims(identity["node_id"], [{"type": "shared", "token": mailbox_token}])
    assert [msg["msg_id"] for msg in delivered] == ["shared-msg-1"]


def test_open_sender_seal_verifies_in_wormhole(tmp_path, monkeypatch):
    _relay, identity_mod = _fresh_mesh_state(tmp_path, monkeypatch)
    identity = identity_mod.bootstrap_wormhole_identity(force=True)

    from services.mesh.mesh_wormhole_seal import build_sender_seal, open_sender_seal

    msg_id = "dm_test_1"
    timestamp = 1234567890
    built = build_sender_seal(
        recipient_id=identity["node_id"],
        recipient_dh_pub=identity["dh_pub_key"],
        msg_id=msg_id,
        timestamp=timestamp,
    )
    assert built["ok"]
    assert str(built["sender_seal"]).startswith("v3:")

    opened = open_sender_seal(
        sender_seal=built["sender_seal"],
        candidate_dh_pub=identity["dh_pub_key"],
        recipient_id=identity["node_id"],
        expected_msg_id=msg_id,
    )
    assert opened["ok"]
    assert opened["sender_id"] == identity["node_id"]
    assert opened["seal_verified"] is True


def test_open_sender_seal_still_accepts_legacy_format(tmp_path, monkeypatch):
    _relay, identity_mod = _fresh_mesh_state(tmp_path, monkeypatch)
    identity = identity_mod.bootstrap_wormhole_identity(force=True)

    from services.mesh.mesh_wormhole_identity import sign_wormhole_message
    from services.mesh.mesh_wormhole_seal import open_sender_seal

    sender_priv = x25519.X25519PrivateKey.generate()
    sender_pub = sender_priv.public_key()
    recipient_pub = x25519.X25519PublicKey.from_public_bytes(base64.b64decode(identity["dh_pub_key"]))
    shared = sender_priv.exchange(recipient_pub)

    msg_id = "dm_test_legacy"
    timestamp = 1234567890
    signed = sign_wormhole_message(f"seal|{msg_id}|{timestamp}|{identity['node_id']}")
    seal_payload = {
        "sender_id": signed["node_id"],
        "public_key": signed["public_key"],
        "public_key_algo": signed["public_key_algo"],
        "msg_id": msg_id,
        "timestamp": timestamp,
        "signature": signed["signature"],
    }
    iv = b"\x00" * 12
    ciphertext = AESGCM(shared).encrypt(iv, json.dumps(seal_payload).encode("utf-8"), None)
    sender_seal = base64.b64encode(iv + ciphertext).decode("ascii")
    candidate_dh_pub = base64.b64encode(
        sender_pub.public_bytes(Encoding.Raw, PublicFormat.Raw)
    ).decode("ascii")

    opened = open_sender_seal(
        sender_seal=sender_seal,
        candidate_dh_pub=candidate_dh_pub,
        recipient_id=identity["node_id"],
        expected_msg_id=msg_id,
    )
    assert opened["ok"]
    assert opened["sender_id"] == identity["node_id"]
    assert opened["seal_verified"] is True


def test_legacy_sender_seal_rejected_in_hardened_mode(tmp_path, monkeypatch):
    _relay, identity_mod = _fresh_mesh_state(tmp_path, monkeypatch)
    identity = identity_mod.bootstrap_wormhole_identity(force=True)

    from services.mesh.mesh_wormhole_identity import sign_wormhole_message
    from services.mesh import mesh_wormhole_seal

    monkeypatch.setattr(
        mesh_wormhole_seal,
        "read_wormhole_settings",
        lambda: {"enabled": True, "anonymous_mode": True},
    )

    sender_priv = x25519.X25519PrivateKey.generate()
    sender_pub = sender_priv.public_key()
    recipient_pub = x25519.X25519PublicKey.from_public_bytes(base64.b64decode(identity["dh_pub_key"]))
    shared = sender_priv.exchange(recipient_pub)

    msg_id = "dm_test_legacy_hardened"
    timestamp = 1234567890
    signed = sign_wormhole_message(f"seal|{msg_id}|{timestamp}|{identity['node_id']}")
    seal_payload = {
        "sender_id": signed["node_id"],
        "public_key": signed["public_key"],
        "public_key_algo": signed["public_key_algo"],
        "msg_id": msg_id,
        "timestamp": timestamp,
        "signature": signed["signature"],
    }
    iv = b"\x00" * 12
    ciphertext = AESGCM(shared).encrypt(iv, json.dumps(seal_payload).encode("utf-8"), None)
    sender_seal = base64.b64encode(iv + ciphertext).decode("ascii")
    candidate_dh_pub = base64.b64encode(
        sender_pub.public_bytes(Encoding.Raw, PublicFormat.Raw)
    ).decode("ascii")

    opened = mesh_wormhole_seal.open_sender_seal(
        sender_seal=sender_seal,
        candidate_dh_pub=candidate_dh_pub,
        recipient_id=identity["node_id"],
        expected_msg_id=msg_id,
    )
    assert opened["ok"] is False
    assert "Legacy sender seals" in opened["detail"]


def test_require_admin_no_longer_trusts_loopback_without_override(monkeypatch):
    from fastapi import HTTPException
    from starlette.requests import Request
    import main

    monkeypatch.setattr(main, "_current_admin_key", lambda: "")
    monkeypatch.setattr(main, "_allow_insecure_admin", lambda: False)

    request = Request(
        {
            "type": "http",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "method": "GET",
            "path": "/api/wormhole/status",
        }
    )

    with pytest.raises(HTTPException) as exc:
        main.require_admin(request)
    assert exc.value.status_code == 403
