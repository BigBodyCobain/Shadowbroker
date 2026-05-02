import asyncio
import base64
import copy
import time

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from httpx import ASGITransport, AsyncClient

import main
from services.config import Settings, get_settings
from services.mesh.mesh_crypto import build_signature_payload, derive_node_id
from services.mesh import (
    mesh_dm_relay,
    mesh_hashchain,
    mesh_private_outbox,
    mesh_private_release_worker,
    mesh_private_transport_manager,
    mesh_relay_policy,
    mesh_rns,
)
from services.mesh.mesh_protocol import (
    normalize_dm_count_payload,
    normalize_dm_message_payload_legacy,
    normalize_dm_poll_payload,
)


def _fresh_private_outbox(monkeypatch):
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
    mesh_relay_policy.reset_relay_policy_for_tests()
    mesh_private_outbox.private_delivery_outbox._load()
    return store


def _run_private_release_once(
    monkeypatch,
    *,
    secure_dm: bool,
    rns_ready: bool,
    anonymous_hidden: bool = False,
):
    monkeypatch.setattr(mesh_private_release_worker, "_secure_dm_enabled", lambda: secure_dm)
    monkeypatch.setattr(mesh_private_release_worker, "_rns_private_dm_ready", lambda: rns_ready)
    monkeypatch.setattr(
        mesh_private_release_worker,
        "_anonymous_dm_hidden_transport_enforced",
        lambda: anonymous_hidden,
    )
    monkeypatch.setattr(mesh_private_release_worker, "_maybe_apply_dm_relay_jitter", lambda: None)
    mesh_private_release_worker.private_release_worker.run_once()


def _private_outbox_item(item_id: str) -> dict:
    return next(
        item
        for item in mesh_private_outbox.private_delivery_outbox.list_items(limit=50, exposure="diagnostic")
        if item["id"] == item_id
    )


def _fresh_relay(tmp_path, monkeypatch):
    from services import wormhole_supervisor
    from services.mesh import mesh_wormhole_contacts

    _fresh_private_outbox(monkeypatch)
    monkeypatch.setenv("MESH_PRIVATE_RELEASE_APPROVAL_ENABLE", "false")
    monkeypatch.setattr(mesh_dm_relay, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_dm_relay, "RELAY_FILE", tmp_path / "dm_relay.json")
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": True},
    )
    monkeypatch.setattr(
        mesh_wormhole_contacts,
        "verified_first_contact_requirement",
        lambda peer_id="", trust_level=None: {"ok": True, "trust_level": "sas_verified"},
    )
    get_settings.cache_clear()
    relay = mesh_dm_relay.DMRelay()
    monkeypatch.setattr(mesh_dm_relay, "dm_relay", relay)
    return relay


def _post(path: str, payload: dict):
    async def _run():
        request_payload = dict(payload)
        if path in {"/api/mesh/dm/send", "/api/mesh/dm/poll", "/api/mesh/dm/count"}:
            request_payload.setdefault("transport_lock", "private_strong")
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            return await ac.post(path, json=request_payload)

    return asyncio.run(_run())


class _FakeInfonet:
    def __init__(self):
        self.appended = []
        self.sequences = {}
        self.node_sequences = self.sequences
        self.public_key_bindings = {}

    def append(self, **kwargs):
        self.appended.append(kwargs)

    def check_replay(self, node_id, sequence):
        return sequence <= self.sequences.get(node_id, 0)

    def _revocation_status(self, _public_key):
        return False, {}

    def _rebuild_revocations(self):
        return None

    def validate_and_set_sequence(self, node_id, sequence):
        last = self.sequences.get(node_id, 0)
        if sequence <= last:
            return False, f"Replay detected: sequence {sequence} <= last {last}"
        self.sequences[node_id] = sequence
        return True, ""


class _DirectRNS:
    def __init__(self, send_result=True, direct_messages=None, direct_ids=None):
        self.send_result = send_result
        self.sent = []
        self.direct_messages = list(direct_messages or [])
        self.direct_ids_value = set(direct_ids or [])

    def send_private_dm(self, *, mailbox_key, envelope):
        self.sent.append({"mailbox_key": mailbox_key, "envelope": envelope})
        return self.send_result

    def collect_private_dm(self, mailbox_keys, *, limit=0):
        return list(self.direct_messages), False

    def private_dm_ids(self, mailbox_keys):
        return set(self.direct_ids_value)

    def count_private_dm(self, mailbox_keys):
        return len(self.direct_ids_value)


TEST_PUBLIC_KEY = base64.b64encode(b"0" * 32).decode("ascii")
TEST_SENDER_ID = derive_node_id(TEST_PUBLIC_KEY)
REQUEST_CLAIMS = [{"type": "requests", "token": "request-claim-token"}]
REQUEST_SENDER_TOKEN = "opaque-sender-token"
REQUEST_SENDER_TOKEN_HASH = "reqtok-rns-private-dm"
NOW_TS = lambda: int(time.time())


def _install_request_sender_token(
    monkeypatch,
    *,
    sender_token_hash: str = REQUEST_SENDER_TOKEN_HASH,
    sender_id: str = TEST_SENDER_ID,
    public_key: str = TEST_PUBLIC_KEY,
    public_key_algo: str = "Ed25519",
    protocol_version: str = "infonet/2",
):
    from services.mesh import mesh_wormhole_sender_token

    def _fake_consume_token(*, sender_token, recipient_id, delivery_class, recipient_token=""):
        return {
            "ok": True,
            "recipient_id": recipient_id,
            "sender_id": sender_id,
            "sender_token_hash": sender_token_hash,
            "public_key": public_key,
            "public_key_algo": public_key_algo,
            "protocol_version": protocol_version,
            "delivery_class": delivery_class,
            "recipient_token": recipient_token,
        }

    monkeypatch.setattr(main, "consume_wormhole_dm_sender_token", _fake_consume_token)
    monkeypatch.setattr(mesh_wormhole_sender_token, "consume_wormhole_dm_sender_token", _fake_consume_token)


def _legacy_signed_dm_send_body(
    *,
    msg_id: str = "msg-legacy-1",
    timestamp: int | None = None,
    overrides: dict | None = None,
):
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key_raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    public_key = base64.b64encode(public_key_raw).decode("ascii")
    sender_id = derive_node_id(public_key)
    payload = {
        "recipient_id": "!sb_recipient1234",
        "delivery_class": "request",
        "recipient_token": "",
        "ciphertext": "ciphertext",
        "msg_id": msg_id,
        "timestamp": int(timestamp or NOW_TS()),
        "transport_lock": "private_strong",
    }
    signature_payload = build_signature_payload(
        event_type="dm_message",
        node_id=sender_id,
        sequence=41,
        payload=normalize_dm_message_payload_legacy(payload),
    )
    signature = private_key.sign(signature_payload.encode("utf-8")).hex()
    body = {
        "sender_id": sender_id,
        "sender_token": "sender-token",
        **payload,
        "format": "mls1",
        "session_welcome": "WELCOME",
        "sender_seal": "v3:test-seal",
        "relay_salt": "00112233445566778899aabbccddeeff",
        "public_key": public_key,
        "public_key_algo": "Ed25519",
        "signature": signature,
        "sequence": 41,
        "protocol_version": "infonet/2",
    }
    if overrides:
        body.update(overrides)
    return body


def _mailbox_request_identity() -> dict:
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key_raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    public_key = base64.b64encode(public_key_raw).decode("ascii")
    return {
        "private_key": private_key,
        "public_key": public_key,
        "agent_id": derive_node_id(public_key),
    }


def _signed_dm_mailbox_request_body(
    *,
    event_type: str,
    identity: dict | None = None,
    agent_id: str = "",
    mailbox_claims: list[dict] | None = None,
    timestamp: int | None = None,
    nonce: str = "nonce-mailbox",
    sequence: int = 1,
    overrides: dict | None = None,
):
    current_identity = dict(identity or _mailbox_request_identity())
    private_key = current_identity["private_key"]
    public_key = str(current_identity["public_key"] or "")
    bound_agent_id = str(current_identity["agent_id"] or "")
    resolved_agent_id = str(agent_id or bound_agent_id).strip()
    if resolved_agent_id != bound_agent_id:
        raise ValueError("agent_id must match the signing public key")
    payload = {
        "mailbox_claims": list(mailbox_claims or REQUEST_CLAIMS),
        "timestamp": int(timestamp or NOW_TS()),
        "nonce": str(nonce or ""),
        "transport_lock": "private_strong",
    }
    normalized = (
        normalize_dm_poll_payload(payload)
        if event_type == "dm_poll"
        else normalize_dm_count_payload(payload)
    )
    signature_payload = build_signature_payload(
        event_type=event_type,
        node_id=resolved_agent_id,
        sequence=int(sequence),
        payload=normalized,
    )
    signature = private_key.sign(signature_payload.encode("utf-8")).hex()
    body = {
        "agent_id": resolved_agent_id,
        **payload,
        "public_key": public_key,
        "public_key_algo": "Ed25519",
        "signature": signature,
        "sequence": int(sequence),
        "protocol_version": "infonet/2",
    }
    if overrides:
        body.update(overrides)
    return body


def test_secure_dm_send_prefers_reticulum(tmp_path, monkeypatch):
    relay = _fresh_relay(tmp_path, monkeypatch)
    infonet = _FakeInfonet()
    direct_rns = _DirectRNS(send_result=True)

    _install_request_sender_token(monkeypatch)
    monkeypatch.setattr(main, "_secure_dm_enabled", lambda: True)
    monkeypatch.setattr(main, "_rns_private_dm_ready", lambda: True)
    monkeypatch.setattr(main, "_verify_signed_write", lambda **_kwargs: (True, ""))
    monkeypatch.setattr(mesh_hashchain, "infonet", infonet)
    monkeypatch.setattr(mesh_rns, "rns_bridge", direct_rns)

    response = _post(
        "/api/mesh/dm/send",
        {
            "sender_id": TEST_SENDER_ID,
            "sender_token": REQUEST_SENDER_TOKEN,
            "recipient_id": "!sb_recipient1234",
            "delivery_class": "request",
            "ciphertext": "ciphertext",
            "msg_id": "msg-reticulum-1",
            "timestamp": NOW_TS(),
            "public_key": TEST_PUBLIC_KEY,
            "public_key_algo": "Ed25519",
            "signature": "sig",
            "sequence": 7,
            "protocol_version": "infonet/2",
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["ok"] is True
    assert body["queued"] is True
    outbox_id = body["outbox_id"]
    assert relay.count_claims("!sb_recipient1234", REQUEST_CLAIMS) == 0
    assert len(direct_rns.sent) == 0
    _run_private_release_once(monkeypatch, secure_dm=True, rns_ready=True)
    delivered = _private_outbox_item(outbox_id)
    assert delivered["release_state"] == "delivered"
    assert delivered["result"]["transport"] == "reticulum"
    assert delivered["result"]["carrier"] == "reticulum_direct"
    assert len(direct_rns.sent) == 1
    assert direct_rns.sent[0]["envelope"]["msg_id"] == "msg-reticulum-1"
    assert len(infonet.appended) == 0


def test_verify_signed_event_rejects_legacy_dm_signature_compat_by_default(monkeypatch):
    body = _legacy_signed_dm_send_body()
    payload = {
        "recipient_id": body["recipient_id"],
        "delivery_class": body["delivery_class"],
        "recipient_token": body["recipient_token"],
        "ciphertext": body["ciphertext"],
        "format": body["format"],
        "msg_id": body["msg_id"],
        "timestamp": body["timestamp"],
        "session_welcome": body["session_welcome"],
        "sender_seal": body["sender_seal"],
        "relay_salt": body["relay_salt"],
    }

    monkeypatch.delenv("MESH_ALLOW_LEGACY_DM_SIGNATURE_COMPAT", raising=False)
    monkeypatch.delenv("MESH_ALLOW_LEGACY_DM_SIGNATURE_COMPAT_UNTIL", raising=False)
    get_settings.cache_clear()
    try:
        ok, reason = main._verify_signed_event(
            event_type="dm_message",
            node_id=body["sender_id"],
            sequence=body["sequence"],
            public_key=body["public_key"],
            public_key_algo=body["public_key_algo"],
            signature=body["signature"],
            payload=payload,
            protocol_version=body["protocol_version"],
        )
    finally:
        get_settings.cache_clear()

    assert ok is False
    assert reason == "Invalid signature"


def test_verify_signed_event_ignores_legacy_dm_signature_bool_without_override(monkeypatch):
    body = _legacy_signed_dm_send_body()
    payload = {
        "recipient_id": body["recipient_id"],
        "delivery_class": body["delivery_class"],
        "recipient_token": body["recipient_token"],
        "ciphertext": body["ciphertext"],
        "format": body["format"],
        "msg_id": body["msg_id"],
        "timestamp": body["timestamp"],
        "session_welcome": body["session_welcome"],
        "sender_seal": body["sender_seal"],
        "relay_salt": body["relay_salt"],
    }

    monkeypatch.setenv("MESH_ALLOW_LEGACY_DM_SIGNATURE_COMPAT", "true")
    monkeypatch.delenv("MESH_ALLOW_LEGACY_DM_SIGNATURE_COMPAT_UNTIL", raising=False)
    get_settings.cache_clear()
    try:
        ok, reason = main._verify_signed_event(
            event_type="dm_message",
            node_id=body["sender_id"],
            sequence=body["sequence"],
            public_key=body["public_key"],
            public_key_algo=body["public_key_algo"],
            signature=body["signature"],
            payload=payload,
            protocol_version=body["protocol_version"],
        )
    finally:
        get_settings.cache_clear()

    assert ok is False
    assert reason == "Invalid signature"


def test_verify_signed_event_marks_legacy_dm_signature_compat_when_enabled(monkeypatch):
    body = _legacy_signed_dm_send_body()
    payload = {
        "recipient_id": body["recipient_id"],
        "delivery_class": body["delivery_class"],
        "recipient_token": body["recipient_token"],
        "ciphertext": body["ciphertext"],
        "format": body["format"],
        "msg_id": body["msg_id"],
        "timestamp": body["timestamp"],
        "session_welcome": body["session_welcome"],
        "sender_seal": body["sender_seal"],
        "relay_salt": body["relay_salt"],
    }

    monkeypatch.setenv("MESH_ALLOW_LEGACY_DM_SIGNATURE_COMPAT_UNTIL", "2099-01-01")
    monkeypatch.setenv("MESH_DEV_ALLOW_LEGACY_COMPAT", "true")
    get_settings.cache_clear()
    try:
        ok, reason = main._verify_signed_event(
            event_type="dm_message",
            node_id=body["sender_id"],
            sequence=body["sequence"],
            public_key=body["public_key"],
            public_key_algo=body["public_key_algo"],
            signature=body["signature"],
            payload=payload,
            protocol_version=body["protocol_version"],
        )
    finally:
        get_settings.cache_clear()

    assert ok is True
    assert reason == "legacy_dm_signature_compat"


def test_legacy_signed_dm_strips_unsigned_modern_fields_before_relay_side_effects(tmp_path, monkeypatch):
    from services import wormhole_supervisor
    from services.mesh import mesh_wormhole_sender_token

    relay = _fresh_relay(tmp_path, monkeypatch)
    infonet = _FakeInfonet()
    body = _legacy_signed_dm_send_body(msg_id="msg-legacy-strip-1")
    monkeypatch.setenv("MESH_ALLOW_LEGACY_DM_SIGNATURE_COMPAT_UNTIL", "2099-01-01")
    monkeypatch.setenv("MESH_DEV_ALLOW_LEGACY_COMPAT", "true")
    get_settings.cache_clear()

    monkeypatch.setattr(wormhole_supervisor, "get_transport_tier", lambda: "public_degraded")
    monkeypatch.setattr(main, "_is_debug_test_request", lambda _request: True)
    monkeypatch.setattr(main, "_secure_dm_enabled", lambda: False)
    monkeypatch.setattr(mesh_hashchain, "infonet", infonet)
    monkeypatch.setattr(
        main,
        "consume_wormhole_dm_sender_token",
        lambda **_kwargs: {
            "ok": True,
            "recipient_id": body["recipient_id"],
            "sender_id": body["sender_id"],
            "sender_token_hash": "reqtok-legacy-strip-1",
            "public_key": body["public_key"],
            "public_key_algo": body["public_key_algo"],
            "protocol_version": body["protocol_version"],
        },
    )
    monkeypatch.setattr(
        mesh_wormhole_sender_token,
        "consume_wormhole_dm_sender_token",
        lambda **_kwargs: {
            "ok": True,
            "recipient_id": body["recipient_id"],
            "sender_id": body["sender_id"],
            "sender_token_hash": "reqtok-legacy-strip-1",
            "public_key": body["public_key"],
            "public_key_algo": body["public_key_algo"],
            "protocol_version": body["protocol_version"],
        },
    )

    try:
        response = _post("/api/mesh/dm/send", body)

        assert response.status_code == 200
        response_body = response.json()
        assert response_body["ok"] is True
        assert response_body["queued"] is True
        messages, _ = relay.collect_claims("!sb_recipient1234", REQUEST_CLAIMS)
        assert messages == []
        monkeypatch.setattr(wormhole_supervisor, "get_transport_tier", lambda: "private_strong")
        _run_private_release_once(monkeypatch, secure_dm=False, rns_ready=False)
        messages, _ = relay.collect_claims("!sb_recipient1234", REQUEST_CLAIMS)
        assert [msg["msg_id"] for msg in messages] == ["msg-legacy-strip-1"]
        assert messages[0]["format"] == "dm1"
        assert messages[0]["session_welcome"] == ""
        assert messages[0]["sender_seal"] == ""
        assert messages[0]["sender_id"] == "sender_token:reqtok-legacy-strip-1"
    finally:
        get_settings.cache_clear()


def test_legacy_signed_dm_cannot_smuggle_dm1_through_private_transport(tmp_path, monkeypatch):
    from services import wormhole_supervisor
    from services.mesh import mesh_wormhole_sender_token

    _fresh_relay(tmp_path, monkeypatch)
    body = _legacy_signed_dm_send_body(msg_id="msg-legacy-private-1")
    monkeypatch.setenv("MESH_ALLOW_LEGACY_DM_SIGNATURE_COMPAT_UNTIL", "2099-01-01")
    monkeypatch.setenv("MESH_DEV_ALLOW_LEGACY_COMPAT", "true")
    get_settings.cache_clear()

    monkeypatch.setattr(wormhole_supervisor, "get_transport_tier", lambda: "private_strong")
    monkeypatch.setattr(main, "_secure_dm_enabled", lambda: False)
    monkeypatch.setattr(
        main,
        "consume_wormhole_dm_sender_token",
        lambda **_kwargs: {
            "ok": True,
            "recipient_id": body["recipient_id"],
            "sender_id": body["sender_id"],
            "sender_token_hash": "reqtok-legacy-private-1",
            "public_key": body["public_key"],
            "public_key_algo": body["public_key_algo"],
            "protocol_version": body["protocol_version"],
        },
    )
    monkeypatch.setattr(
        mesh_wormhole_sender_token,
        "consume_wormhole_dm_sender_token",
        lambda **_kwargs: {
            "ok": True,
            "recipient_id": body["recipient_id"],
            "sender_id": body["sender_id"],
            "sender_token_hash": "reqtok-legacy-private-1",
            "public_key": body["public_key"],
            "public_key_algo": body["public_key_algo"],
            "protocol_version": body["protocol_version"],
        },
    )

    response = _post("/api/mesh/dm/send", body)

    assert response.status_code == 403
    assert response.json() == {
        "ok": False,
        "detail": "MLS session required in private transport mode - dm1 blocked on raw send path",
    }
    get_settings.cache_clear()


def test_secure_dm_send_falls_back_to_relay(tmp_path, monkeypatch):
    relay = _fresh_relay(tmp_path, monkeypatch)
    infonet = _FakeInfonet()
    direct_rns = _DirectRNS(send_result=False)

    _install_request_sender_token(monkeypatch)
    monkeypatch.setattr(main, "_secure_dm_enabled", lambda: True)
    monkeypatch.setattr(main, "_rns_private_dm_ready", lambda: True)
    monkeypatch.setattr(main, "_verify_signed_write", lambda **_kwargs: (True, ""))
    monkeypatch.setattr(mesh_hashchain, "infonet", infonet)
    monkeypatch.setattr(mesh_rns, "rns_bridge", direct_rns)

    response = _post(
        "/api/mesh/dm/send",
        {
            "sender_id": TEST_SENDER_ID,
            "sender_token": REQUEST_SENDER_TOKEN,
            "recipient_id": "!sb_recipient1234",
            "delivery_class": "request",
            "ciphertext": "ciphertext",
            "msg_id": "msg-relay-1",
            "timestamp": NOW_TS(),
            "public_key": TEST_PUBLIC_KEY,
            "public_key_algo": "Ed25519",
            "signature": "sig",
            "sequence": 8,
            "protocol_version": "infonet/2",
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["ok"] is True
    assert body["queued"] is True
    outbox_id = body["outbox_id"]
    assert relay.count_claims("!sb_recipient1234", REQUEST_CLAIMS) == 0
    _run_private_release_once(monkeypatch, secure_dm=True, rns_ready=True)
    delivered = _private_outbox_item(outbox_id)
    assert delivered["release_state"] == "delivered"
    assert delivered["result"]["transport"] == "relay"
    assert delivered["result"]["carrier"] == "relay"
    assert relay.count_claims("!sb_recipient1234", REQUEST_CLAIMS) == 1
    assert len(infonet.appended) == 0


def test_dm_send_accepts_public_degraded_and_starts_transport_in_background(tmp_path, monkeypatch):
    from services import wormhole_supervisor

    relay = _fresh_relay(tmp_path, monkeypatch)
    infonet = _FakeInfonet()
    kickoff = {"count": 0}

    _install_request_sender_token(monkeypatch)
    monkeypatch.setattr(main, "_secure_dm_enabled", lambda: False)
    monkeypatch.setattr(main, "_verify_signed_write", lambda **_kwargs: (True, ""))
    monkeypatch.setattr(mesh_hashchain, "infonet", infonet)
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {
            "configured": False,
            "ready": False,
            "arti_ready": False,
            "rns_ready": False,
        },
    )
    monkeypatch.setattr(wormhole_supervisor, "get_transport_tier", lambda: "public_degraded")
    monkeypatch.setattr(
        main,
        "_kickoff_dm_send_transport_upgrade",
        lambda: kickoff.__setitem__("count", kickoff["count"] + 1),
    )

    response = _post(
        "/api/mesh/dm/send",
        {
            "sender_id": TEST_SENDER_ID,
            "sender_token": REQUEST_SENDER_TOKEN,
            "recipient_id": "!sb_recipient1234",
            "delivery_class": "request",
            "ciphertext": "ciphertext",
            "msg_id": "msg-background-upgrade-1",
            "timestamp": NOW_TS(),
            "public_key": TEST_PUBLIC_KEY,
            "public_key_algo": "Ed25519",
            "signature": "sig",
            "sequence": 9,
            "protocol_version": "infonet/2",
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["ok"] is True
    assert body["queued"] is True
    assert body["private_transport_pending"] is True
    assert body["detail"] == "Preparing private lane"
    assert relay.count_claims("!sb_recipient1234", REQUEST_CLAIMS) == 0
    assert len(infonet.appended) == 0
    assert kickoff["count"] >= 1


def test_request_sender_seal_reduces_relay_sender_handle_on_fallback(tmp_path, monkeypatch):
    relay = _fresh_relay(tmp_path, monkeypatch)
    infonet = _FakeInfonet()
    direct_rns = _DirectRNS(send_result=False)

    _install_request_sender_token(monkeypatch)
    monkeypatch.setattr(main, "_secure_dm_enabled", lambda: True)
    monkeypatch.setattr(main, "_rns_private_dm_ready", lambda: True)
    monkeypatch.setattr(main, "_verify_signed_write", lambda **_kwargs: (True, ""))
    monkeypatch.setattr(mesh_hashchain, "infonet", infonet)
    monkeypatch.setattr(mesh_rns, "rns_bridge", direct_rns)

    response = _post(
        "/api/mesh/dm/send",
        {
            "sender_id": TEST_SENDER_ID,
            "sender_token": REQUEST_SENDER_TOKEN,
            "recipient_id": "!sb_recipient1234",
            "delivery_class": "request",
            "ciphertext": "ciphertext",
            "sender_seal": "v3:test-seal",
            "relay_salt": "0123456789abcdef0123456789abcdef",
            "msg_id": "msg-relay-sealed-1",
            "timestamp": NOW_TS(),
            "public_key": TEST_PUBLIC_KEY,
            "public_key_algo": "Ed25519",
            "signature": "sig",
            "sequence": 18,
            "protocol_version": "infonet/2",
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["ok"] is True
    assert body["queued"] is True
    _run_private_release_once(monkeypatch, secure_dm=True, rns_ready=True)
    messages, _ = relay.collect_claims("!sb_recipient1234", REQUEST_CLAIMS)
    assert [msg["msg_id"] for msg in messages] == ["msg-relay-sealed-1"]
    assert messages[0]["sender_id"] == f"sender_token:{REQUEST_SENDER_TOKEN_HASH}"
    assert messages[0]["sender_id"] != TEST_SENDER_ID
    assert messages[0]["sender_seal"] == "v3:test-seal"


def test_request_sender_seal_reduces_direct_rns_sender_handle(tmp_path, monkeypatch):
    relay = _fresh_relay(tmp_path, monkeypatch)
    infonet = _FakeInfonet()
    direct_rns = _DirectRNS(send_result=True)

    _install_request_sender_token(monkeypatch)
    monkeypatch.setattr(main, "_secure_dm_enabled", lambda: True)
    monkeypatch.setattr(main, "_rns_private_dm_ready", lambda: True)
    monkeypatch.setattr(main, "_verify_signed_write", lambda **_kwargs: (True, ""))
    monkeypatch.setattr(mesh_hashchain, "infonet", infonet)
    monkeypatch.setattr(mesh_rns, "rns_bridge", direct_rns)

    response = _post(
        "/api/mesh/dm/send",
        {
            "sender_id": TEST_SENDER_ID,
            "sender_token": REQUEST_SENDER_TOKEN,
            "recipient_id": "!sb_recipient1234",
            "delivery_class": "request",
            "ciphertext": "ciphertext",
            "sender_seal": "v3:test-seal",
            "relay_salt": "fedcba9876543210fedcba9876543210",
            "msg_id": "msg-direct-sealed-1",
            "timestamp": NOW_TS(),
            "public_key": TEST_PUBLIC_KEY,
            "public_key_algo": "Ed25519",
            "signature": "sig",
            "sequence": 19,
            "protocol_version": "infonet/2",
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["ok"] is True
    assert body["queued"] is True
    assert len(direct_rns.sent) == 0
    _run_private_release_once(monkeypatch, secure_dm=True, rns_ready=True)
    assert len(direct_rns.sent) == 1
    assert direct_rns.sent[0]["envelope"]["sender_id"] == f"sender_token:{REQUEST_SENDER_TOKEN_HASH}"
    assert direct_rns.sent[0]["envelope"]["sender_id"] != TEST_SENDER_ID
    assert direct_rns.sent[0]["envelope"]["sender_seal"] == "v3:test-seal"
    assert relay.count_claims("!sb_recipient1234", REQUEST_CLAIMS) == 0


def test_request_sender_block_prevents_direct_rns_delivery(tmp_path, monkeypatch):
    relay = _fresh_relay(tmp_path, monkeypatch)
    infonet = _FakeInfonet()
    direct_rns = _DirectRNS(send_result=True)
    relay.block("!sb_recipient1234", TEST_SENDER_ID)

    _install_request_sender_token(monkeypatch)
    monkeypatch.setattr(main, "_secure_dm_enabled", lambda: True)
    monkeypatch.setattr(main, "_rns_private_dm_ready", lambda: True)
    monkeypatch.setattr(main, "_verify_signed_write", lambda **_kwargs: (True, ""))
    monkeypatch.setattr(mesh_hashchain, "infonet", infonet)
    monkeypatch.setattr(mesh_rns, "rns_bridge", direct_rns)

    response = _post(
        "/api/mesh/dm/send",
        {
            "sender_id": TEST_SENDER_ID,
            "sender_token": REQUEST_SENDER_TOKEN,
            "recipient_id": "!sb_recipient1234",
            "delivery_class": "request",
            "ciphertext": "ciphertext",
            "sender_seal": "v3:test-seal",
            "relay_salt": "00112233445566778899aabbccddeeff",
            "msg_id": "msg-direct-blocked-1",
            "timestamp": NOW_TS(),
            "public_key": TEST_PUBLIC_KEY,
            "public_key_algo": "Ed25519",
            "signature": "sig",
            "sequence": 20,
            "protocol_version": "infonet/2",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"ok": False, "detail": "Recipient is not accepting your messages"}
    assert len(direct_rns.sent) == 0
    assert relay.count_claims("!sb_recipient1234", REQUEST_CLAIMS) == 0


def test_request_sender_seal_respects_raw_sender_block_on_relay_send_path(tmp_path, monkeypatch):
    relay = _fresh_relay(tmp_path, monkeypatch)
    infonet = _FakeInfonet()
    relay.block("!sb_recipient1234", TEST_SENDER_ID)

    _install_request_sender_token(monkeypatch)
    monkeypatch.setattr(main, "_secure_dm_enabled", lambda: False)
    monkeypatch.setattr(main, "_verify_signed_write", lambda **_kwargs: (True, ""))
    monkeypatch.setattr(mesh_hashchain, "infonet", infonet)

    response = _post(
        "/api/mesh/dm/send",
        {
            "sender_id": TEST_SENDER_ID,
            "sender_token": REQUEST_SENDER_TOKEN,
            "recipient_id": "!sb_recipient1234",
            "delivery_class": "request",
            "ciphertext": "ciphertext",
            "sender_seal": "v3:test-seal",
            "relay_salt": "00112233445566778899aabbccddeeff",
            "msg_id": "msg-blocked-sealed-1",
            "timestamp": NOW_TS(),
            "public_key": TEST_PUBLIC_KEY,
            "public_key_algo": "Ed25519",
            "signature": "sig",
            "sequence": 20,
            "protocol_version": "infonet/2",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"ok": False, "detail": "Recipient is not accepting your messages"}
    assert relay.count_claims("!sb_recipient1234", REQUEST_CLAIMS) == 0


def test_private_dm_accessors_prune_expired_mailboxes(monkeypatch):
    ttl = 60
    now = [1_700_000_000.0]
    bridge = mesh_rns.RNSBridge()
    blinded = mesh_rns._blind_mailbox_key("mailbox-1")

    monkeypatch.setattr(
        "services.mesh.mesh_rns.get_settings",
        lambda: Settings(MESH_DM_MAILBOX_TTL_S=ttl),
    )
    monkeypatch.setattr(mesh_rns.time, "time", lambda: now[0])

    bridge._store_private_dm(blinded, {
        "msg_id": "direct-1",
        "sender_id": "sender-a",
        "ciphertext": "ciphertext",
        "timestamp": now[0],
        "delivery_class": "shared",
        "sender_seal": "",
    })

    assert bridge.count_private_dm(["mailbox-1"]) == 1
    assert bridge.private_dm_ids(["mailbox-1"]) == {"direct-1"}

    now[0] += ttl + 1

    assert bridge.count_private_dm(["mailbox-1"]) == 0
    assert bridge.private_dm_ids(["mailbox-1"]) == set()
    messages, has_more = bridge.collect_private_dm(["mailbox-1"])
    assert messages == []
    assert has_more is False
    with bridge._dm_lock:
        assert blinded not in bridge._dm_mailboxes


def test_secure_dm_send_rejects_replayed_msg_id_nonce(tmp_path, monkeypatch):
    relay = _fresh_relay(tmp_path, monkeypatch)
    infonet = _FakeInfonet()

    _install_request_sender_token(monkeypatch)
    monkeypatch.setattr(main, "_secure_dm_enabled", lambda: False)
    monkeypatch.setattr(main, "_verify_signed_write", lambda **_kwargs: (True, ""))
    monkeypatch.setattr(mesh_hashchain, "infonet", infonet)

    payload = {
        "sender_id": TEST_SENDER_ID,
        "sender_token": REQUEST_SENDER_TOKEN,
        "recipient_id": "!sb_recipient1234",
        "delivery_class": "request",
        "ciphertext": "ciphertext",
        "msg_id": "msg-replay-1",
        "timestamp": NOW_TS(),
        "public_key": TEST_PUBLIC_KEY,
        "public_key_algo": "Ed25519",
        "signature": "sig",
        "sequence": 14,
        "protocol_version": "infonet/2",
    }

    first = _post("/api/mesh/dm/send", payload)
    _run_private_release_once(monkeypatch, secure_dm=False, rns_ready=False)
    second = _post("/api/mesh/dm/send", payload)

    assert first.status_code == 200
    assert first.json()["ok"] is True
    assert second.status_code == 200
    assert second.json() == {"ok": False, "detail": "nonce replay detected"}
    assert relay.count_claims("!sb_recipient1234", REQUEST_CLAIMS) == 1


def test_secure_dm_send_rejects_replayed_sequence_with_new_nonce(tmp_path, monkeypatch):
    _fresh_relay(tmp_path, monkeypatch)
    infonet = _FakeInfonet()

    _install_request_sender_token(monkeypatch)
    monkeypatch.setattr(main, "_secure_dm_enabled", lambda: False)
    monkeypatch.setattr(main, "_verify_signed_write", lambda **_kwargs: (True, ""))
    monkeypatch.setattr(mesh_hashchain, "infonet", infonet)

    first = _post(
        "/api/mesh/dm/send",
        {
            "sender_id": TEST_SENDER_ID,
            "sender_token": REQUEST_SENDER_TOKEN,
            "recipient_id": "!sb_recipient1234",
            "delivery_class": "request",
            "ciphertext": "ciphertext",
            "msg_id": "msg-seq-1",
            "nonce": "nonce-seq-1",
            "timestamp": NOW_TS(),
            "public_key": TEST_PUBLIC_KEY,
            "public_key_algo": "Ed25519",
            "signature": "sig",
            "sequence": 15,
            "protocol_version": "infonet/2",
        },
    )
    second = _post(
        "/api/mesh/dm/send",
        {
            "sender_id": TEST_SENDER_ID,
            "sender_token": REQUEST_SENDER_TOKEN,
            "recipient_id": "!sb_recipient1234",
            "delivery_class": "request",
            "ciphertext": "ciphertext-again",
            "msg_id": "msg-seq-2",
            "nonce": "nonce-seq-2",
            "timestamp": NOW_TS(),
            "public_key": TEST_PUBLIC_KEY,
            "public_key_algo": "Ed25519",
            "signature": "sig",
            "sequence": 15,
            "protocol_version": "infonet/2",
        },
    )

    assert first.status_code == 200
    assert first.json()["ok"] is True
    assert second.status_code == 200
    assert second.json() == {"ok": False, "detail": "Replay detected: sequence 15 <= last 15"}


def test_secure_dm_send_does_not_consume_nonce_before_signature_verification(tmp_path, monkeypatch):
    _fresh_relay(tmp_path, monkeypatch)
    infonet = _FakeInfonet()
    consumed = {"count": 0}

    _install_request_sender_token(monkeypatch)
    monkeypatch.setattr(main, "_secure_dm_enabled", lambda: False)
    monkeypatch.setattr(main, "_verify_signed_write", lambda **_kwargs: (False, "Invalid signature"))
    monkeypatch.setattr(mesh_hashchain, "infonet", infonet)
    monkeypatch.setattr(
        mesh_dm_relay.dm_relay,
        "consume_nonce",
        lambda *_args, **_kwargs: consumed.__setitem__("count", consumed["count"] + 1) or (True, "ok"),
    )

    response = _post(
        "/api/mesh/dm/send",
        {
            "sender_id": TEST_SENDER_ID,
            "sender_token": REQUEST_SENDER_TOKEN,
            "recipient_id": "!sb_recipient1234",
            "delivery_class": "request",
            "ciphertext": "ciphertext",
            "msg_id": "msg-invalid-sig",
            "timestamp": NOW_TS(),
            "public_key": TEST_PUBLIC_KEY,
            "public_key_algo": "Ed25519",
            "signature": "sig",
            "sequence": 16,
            "protocol_version": "infonet/2",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"ok": False, "detail": "Invalid signature"}
    assert consumed["count"] == 0


def test_anonymous_mode_dm_send_stays_off_reticulum(tmp_path, monkeypatch):
    relay = _fresh_relay(tmp_path, monkeypatch)
    infonet = _FakeInfonet()
    direct_rns = _DirectRNS(send_result=True)

    _install_request_sender_token(monkeypatch)
    monkeypatch.setattr(main, "_secure_dm_enabled", lambda: True)
    monkeypatch.setattr(main, "_rns_private_dm_ready", lambda: True)
    monkeypatch.setattr(main, "_anonymous_dm_hidden_transport_enforced", lambda: True)
    monkeypatch.setattr(main, "_verify_signed_write", lambda **_kwargs: (True, ""))
    monkeypatch.setattr(mesh_hashchain, "infonet", infonet)
    monkeypatch.setattr(mesh_rns, "rns_bridge", direct_rns)

    response = _post(
        "/api/mesh/dm/send",
        {
            "sender_id": TEST_SENDER_ID,
            "sender_token": REQUEST_SENDER_TOKEN,
            "recipient_id": "!sb_recipient1234",
            "delivery_class": "request",
            "ciphertext": "ciphertext",
            "msg_id": "msg-anon-relay-1",
            "timestamp": NOW_TS(),
            "public_key": TEST_PUBLIC_KEY,
            "public_key_algo": "Ed25519",
            "signature": "sig",
            "sequence": 9,
            "protocol_version": "infonet/2",
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["ok"] is True
    assert body["queued"] is True
    _run_private_release_once(monkeypatch, secure_dm=True, rns_ready=True, anonymous_hidden=True)
    delivered = _private_outbox_item(body["outbox_id"])
    assert delivered["result"]["transport"] == "relay"
    assert "off direct transport" in delivered["result"]["detail"].lower()
    assert relay.count_claims("!sb_recipient1234", REQUEST_CLAIMS) == 1
    assert len(direct_rns.sent) == 0
    assert len(infonet.appended) == 0


def test_secure_dm_poll_and_count_merge_relay_and_reticulum(tmp_path, monkeypatch):
    identity = _mailbox_request_identity()
    agent_id = identity["agent_id"]
    relay = _fresh_relay(tmp_path, monkeypatch)
    relay.deposit(
        sender_id="sender_token:tok-relay-dup",
        raw_sender_id="alice",
        recipient_id=agent_id,
        ciphertext="cipher-relay-dup",
        msg_id="dup",
        delivery_class="request",
        sender_token_hash="tok-relay-dup",
    )
    relay.deposit(
        sender_id="sender_token:tok-relay-only",
        raw_sender_id="alice",
        recipient_id=agent_id,
        ciphertext="cipher-relay-only",
        msg_id="relay-only",
        delivery_class="request",
        sender_token_hash="tok-relay-only",
    )

    direct_rns = _DirectRNS(
        direct_messages=[
            {
                "sender_id": "sealed:1234",
                "ciphertext": "cipher-direct-dup",
                "timestamp": 100.0,
                "msg_id": "dup",
                "delivery_class": "request",
                "sender_seal": "",
                "transport": "reticulum",
            },
            {
                "sender_id": "sealed:1234",
                "ciphertext": "cipher-direct-only",
                "timestamp": 101.0,
                "msg_id": "direct-only",
                "delivery_class": "request",
                "sender_seal": "",
                "transport": "reticulum",
            },
        ],
        direct_ids={"dup", "direct-only"},
    )
    infonet = _FakeInfonet()

    monkeypatch.setattr(
        main,
        "_verify_dm_mailbox_request",
        lambda **_kwargs: (True, "", {"mailbox_claims": REQUEST_CLAIMS}),
    )
    monkeypatch.setattr(mesh_hashchain, "infonet", infonet)
    monkeypatch.setattr(mesh_rns, "rns_bridge", direct_rns)

    poll_response = _post(
        "/api/mesh/dm/poll",
        _signed_dm_mailbox_request_body(
            event_type="dm_poll",
            identity=identity,
            nonce="nonce-poll",
            sequence=10,
        ),
    )
    poll_body = poll_response.json()
    assert poll_response.status_code == 200
    assert poll_body["ok"] is True
    assert poll_body["count"] == 3
    assert {msg["msg_id"] for msg in poll_body["messages"]} == {"dup", "relay-only", "direct-only"}
    dup_message = next(msg for msg in poll_body["messages"] if msg["msg_id"] == "dup")
    assert dup_message["sender_id"] == "sender_token:tok-relay-dup"
    assert dup_message["ciphertext"] == "cipher-relay-dup"

    count_response = _post(
        "/api/mesh/dm/count",
        _signed_dm_mailbox_request_body(
            event_type="dm_count",
            identity=identity,
            nonce="nonce-count",
            sequence=11,
        ),
    )
    count_body = count_response.json()
    assert count_response.status_code == 200
    assert count_body["ok"] is True
    # After draining relay (0 left) + 2 RNS direct IDs → exact=2, coarsened to 5
    assert count_body["count"] == 5


def test_secure_dm_poll_marks_reduced_v3_request_recovery_fields(tmp_path, monkeypatch):
    identity = _mailbox_request_identity()
    agent_id = identity["agent_id"]
    relay = _fresh_relay(tmp_path, monkeypatch)
    relay.deposit(
        sender_id="sender_token:tok-relay-v3",
        raw_sender_id="alice",
        recipient_id=agent_id,
        ciphertext="cipher-relay-v3",
        msg_id="relay-v3",
        delivery_class="request",
        sender_seal="v3:relay-seal",
        sender_token_hash="tok-relay-v3",
    )

    direct_rns = _DirectRNS(
        direct_messages=[
            {
                "sender_id": "sealed:directv3",
                "ciphertext": "cipher-direct-v3",
                "timestamp": 101.0,
                "msg_id": "direct-v3",
                "delivery_class": "request",
                "sender_seal": "v3:direct-seal",
                "transport": "reticulum",
            },
            {
                "sender_id": "alice",
                "ciphertext": "cipher-legacy",
                "timestamp": 102.0,
                "msg_id": "legacy-raw",
                "delivery_class": "request",
                "sender_seal": "",
                "transport": "reticulum",
            },
        ],
        direct_ids={"direct-v3", "legacy-raw"},
    )
    infonet = _FakeInfonet()

    monkeypatch.setattr(
        main,
        "_verify_dm_mailbox_request",
        lambda **_kwargs: (True, "", {"mailbox_claims": REQUEST_CLAIMS}),
    )
    monkeypatch.setattr(mesh_hashchain, "infonet", infonet)
    monkeypatch.setattr(mesh_rns, "rns_bridge", direct_rns)

    poll_response = _post(
        "/api/mesh/dm/poll",
        _signed_dm_mailbox_request_body(
            event_type="dm_poll",
            identity=identity,
            nonce="nonce-poll-markers",
            sequence=12,
        ),
    )
    poll_body = poll_response.json()

    assert poll_response.status_code == 200
    assert poll_body["ok"] is True
    assert poll_body["count"] == 3

    by_id = {msg["msg_id"]: msg for msg in poll_body["messages"]}

    assert by_id["relay-v3"]["request_contract_version"] == "request-v2-reduced-v3"
    assert by_id["relay-v3"]["sender_recovery_required"] is True
    assert by_id["relay-v3"]["sender_recovery_state"] == "pending"

    assert by_id["direct-v3"]["request_contract_version"] == "request-v2-reduced-v3"
    assert by_id["direct-v3"]["sender_recovery_required"] is True
    assert by_id["direct-v3"]["sender_recovery_state"] == "pending"

    assert "request_contract_version" not in by_id["legacy-raw"]
    assert "sender_recovery_required" not in by_id["legacy-raw"]
    assert "sender_recovery_state" not in by_id["legacy-raw"]


def test_secure_dm_poll_prefers_canonical_v2_duplicate_over_legacy_raw(tmp_path, monkeypatch):
    identity = _mailbox_request_identity()
    agent_id = identity["agent_id"]
    relay = _fresh_relay(tmp_path, monkeypatch)
    relay.deposit(
        sender_id="sender_token:tok-v2-over-raw",
        raw_sender_id="alice",
        recipient_id=agent_id,
        ciphertext="cipher-relay-raw",
        msg_id="dup-v2-over-raw",
        delivery_class="request",
        sender_seal="v3:relay-seal",
        sender_token_hash="tok-v2-over-raw",
    )

    direct_rns = _DirectRNS(
        direct_messages=[
            {
                "sender_id": "alice",
                "ciphertext": "cipher-direct-raw",
                "timestamp": 101.0,
                "msg_id": "dup-v2-over-raw",
                "delivery_class": "request",
                "sender_seal": "",
                "transport": "reticulum",
            }
        ],
        direct_ids={"dup-v2-over-raw"},
    )
    infonet = _FakeInfonet()

    monkeypatch.setattr(
        main,
        "_verify_dm_mailbox_request",
        lambda **_kwargs: (True, "", {"mailbox_claims": REQUEST_CLAIMS}),
    )
    monkeypatch.setattr(mesh_hashchain, "infonet", infonet)
    monkeypatch.setattr(mesh_rns, "rns_bridge", direct_rns)

    poll_response = _post(
        "/api/mesh/dm/poll",
        _signed_dm_mailbox_request_body(
            event_type="dm_poll",
            identity=identity,
            nonce="nonce-poll-v2-over-raw",
            sequence=13,
        ),
    )
    poll_body = poll_response.json()

    assert poll_response.status_code == 200
    assert poll_body["ok"] is True
    assert poll_body["count"] == 1
    message = poll_body["messages"][0]
    assert message["msg_id"] == "dup-v2-over-raw"
    assert message["sender_id"] == "sender_token:tok-v2-over-raw"
    assert message["ciphertext"] == "cipher-relay-raw"
    assert "transport" not in message
    assert message["request_contract_version"] == "request-v2-reduced-v3"
    assert message["sender_recovery_required"] is True
    assert message["sender_recovery_state"] == "pending"


def test_secure_dm_poll_prefers_legacy_raw_duplicate_over_legacy_sealed(tmp_path, monkeypatch):
    identity = _mailbox_request_identity()
    agent_id = identity["agent_id"]
    relay = _fresh_relay(tmp_path, monkeypatch)
    relay.deposit(
        sender_id="sender_token:tok-legacy-sealed",
        raw_sender_id="alice",
        recipient_id=agent_id,
        ciphertext="cipher-relay-sealed",
        msg_id="dup-raw-over-sealed",
        delivery_class="request",
        sender_seal="v2:legacy-seal",
        sender_token_hash="tok-legacy-sealed",
    )

    direct_rns = _DirectRNS(
        direct_messages=[
            {
                "sender_id": "alice",
                "ciphertext": "cipher-direct-raw",
                "timestamp": 101.0,
                "msg_id": "dup-raw-over-sealed",
                "delivery_class": "request",
                "sender_seal": "",
                "transport": "reticulum",
            }
        ],
        direct_ids={"dup-raw-over-sealed"},
    )
    infonet = _FakeInfonet()

    monkeypatch.setattr(
        main,
        "_verify_dm_mailbox_request",
        lambda **_kwargs: (True, "", {"mailbox_claims": REQUEST_CLAIMS}),
    )
    monkeypatch.setattr(mesh_hashchain, "infonet", infonet)
    monkeypatch.setattr(mesh_rns, "rns_bridge", direct_rns)

    poll_response = _post(
        "/api/mesh/dm/poll",
        _signed_dm_mailbox_request_body(
            event_type="dm_poll",
            identity=identity,
            nonce="nonce-poll-raw-over-sealed",
            sequence=14,
        ),
    )
    poll_body = poll_response.json()

    assert poll_response.status_code == 200
    assert poll_body["ok"] is True
    assert poll_body["count"] == 1
    message = poll_body["messages"][0]
    assert message["msg_id"] == "dup-raw-over-sealed"
    assert message["sender_id"] == "alice"
    assert message["ciphertext"] == "cipher-direct-raw"
    assert message["transport"] == "reticulum"
    assert "request_contract_version" not in message
    assert "sender_recovery_required" not in message
    assert "sender_recovery_state" not in message


def test_secure_dm_poll_keeps_relay_copy_for_same_contract_v2_duplicate(tmp_path, monkeypatch):
    identity = _mailbox_request_identity()
    agent_id = identity["agent_id"]
    relay = _fresh_relay(tmp_path, monkeypatch)
    relay.deposit(
        sender_id="sender_token:tok-v2-tie",
        raw_sender_id="alice",
        recipient_id=agent_id,
        ciphertext="cipher-relay-v3-dup",
        msg_id="dup-v2-tie",
        delivery_class="request",
        sender_seal="v3:relay-seal",
        sender_token_hash="tok-v2-tie",
    )

    direct_rns = _DirectRNS(
        direct_messages=[
            {
                "sender_id": "sealed:sharedv3",
                "ciphertext": "cipher-direct-v3-dup",
                "timestamp": 101.0,
                "msg_id": "dup-v2-tie",
                "delivery_class": "request",
                "sender_seal": "v3:relay-seal",
                "transport": "reticulum",
            }
        ],
        direct_ids={"dup-v2-tie"},
    )
    infonet = _FakeInfonet()

    monkeypatch.setattr(
        main,
        "_verify_dm_mailbox_request",
        lambda **_kwargs: (True, "", {"mailbox_claims": REQUEST_CLAIMS}),
    )
    monkeypatch.setattr(mesh_hashchain, "infonet", infonet)
    monkeypatch.setattr(mesh_rns, "rns_bridge", direct_rns)

    poll_response = _post(
        "/api/mesh/dm/poll",
        _signed_dm_mailbox_request_body(
            event_type="dm_poll",
            identity=identity,
            nonce="nonce-poll-v2-tie",
            sequence=15,
        ),
    )
    poll_body = poll_response.json()

    assert poll_response.status_code == 200
    assert poll_body["ok"] is True
    assert poll_body["count"] == 1
    message = poll_body["messages"][0]
    assert message["msg_id"] == "dup-v2-tie"
    assert message["sender_id"] == "sender_token:tok-v2-tie"
    assert message["ciphertext"] == "cipher-relay-v3-dup"
    assert "transport" not in message
    assert message["request_contract_version"] == "request-v2-reduced-v3"
    assert message["sender_recovery_required"] is True
    assert message["sender_recovery_state"] == "pending"


def test_anonymous_mode_poll_and_count_ignore_reticulum(tmp_path, monkeypatch):
    identity = _mailbox_request_identity()
    agent_id = identity["agent_id"]
    relay = _fresh_relay(tmp_path, monkeypatch)
    relay.deposit(
        sender_id="sender_token:tok-relay-only",
        raw_sender_id="alice",
        recipient_id=agent_id,
        ciphertext="cipher-relay-only",
        msg_id="relay-only",
        delivery_class="request",
        sender_token_hash="tok-relay-only",
    )

    direct_rns = _DirectRNS(
        direct_messages=[
            {
                "sender_id": "sealed:1234",
                "ciphertext": "cipher-direct-only",
                "timestamp": 101.0,
                "msg_id": "direct-only",
                "delivery_class": "request",
                "sender_seal": "",
                "transport": "reticulum",
            },
        ],
        direct_ids={"direct-only"},
    )
    infonet = _FakeInfonet()

    monkeypatch.setattr(
        main,
        "_verify_dm_mailbox_request",
        lambda **_kwargs: (True, "", {"mailbox_claims": REQUEST_CLAIMS}),
    )
    monkeypatch.setattr(main, "_anonymous_dm_hidden_transport_enforced", lambda: True)
    monkeypatch.setattr(main, "_anonymous_dm_hidden_transport_requested", lambda: True)
    monkeypatch.setattr(mesh_hashchain, "infonet", infonet)
    monkeypatch.setattr(mesh_rns, "rns_bridge", direct_rns)

    poll_response = _post(
        "/api/mesh/dm/poll",
        _signed_dm_mailbox_request_body(
            event_type="dm_poll",
            identity=identity,
            nonce="nonce-poll-anon",
            sequence=12,
        ),
    )
    poll_body = poll_response.json()
    assert poll_response.status_code == 200
    assert poll_body["ok"] is True
    assert poll_body["count"] == 1
    assert {msg["msg_id"] for msg in poll_body["messages"]} == {"relay-only"}

    count_response = _post(
        "/api/mesh/dm/count",
        _signed_dm_mailbox_request_body(
            event_type="dm_count",
            identity=identity,
            nonce="nonce-count-anon",
            sequence=13,
        ),
    )
    count_body = count_response.json()
    assert count_response.status_code == 200
    assert count_body["ok"] is True
    assert count_body["count"] == 0
