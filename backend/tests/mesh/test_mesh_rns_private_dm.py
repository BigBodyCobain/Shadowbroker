import asyncio
import base64
import hashlib
import hmac
import time

from httpx import ASGITransport, AsyncClient

import main
from services.config import get_settings
from services.mesh.mesh_crypto import derive_node_id
from services.mesh import mesh_dm_relay, mesh_hashchain, mesh_rns


def _fresh_relay(tmp_path, monkeypatch):
    from services import wormhole_supervisor

    monkeypatch.setattr(mesh_dm_relay, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_dm_relay, "RELAY_FILE", tmp_path / "dm_relay.json")
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": True},
    )
    get_settings.cache_clear()
    relay = mesh_dm_relay.DMRelay()
    monkeypatch.setattr(mesh_dm_relay, "dm_relay", relay)
    return relay


def _post(path: str, payload: dict):
    async def _run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
            return await ac.post(path, json=payload)

    return asyncio.run(_run())


class _FakeInfonet:
    def __init__(self):
        self.appended = []
        self.sequences = {}

    def append(self, **kwargs):
        self.appended.append(kwargs)

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

    def collect_private_dm(self, mailbox_keys):
        return list(self.direct_messages)

    def private_dm_ids(self, mailbox_keys):
        return set(self.direct_ids_value)

    def count_private_dm(self, mailbox_keys):
        return len(self.direct_ids_value)


TEST_PUBLIC_KEY = base64.b64encode(b"0" * 32).decode("ascii")
TEST_SENDER_ID = derive_node_id(TEST_PUBLIC_KEY)
REQUEST_CLAIMS = [{"type": "requests", "token": "request-claim-token"}]
NOW_TS = lambda: int(time.time())


def test_secure_dm_send_prefers_reticulum(tmp_path, monkeypatch):
    relay = _fresh_relay(tmp_path, monkeypatch)
    infonet = _FakeInfonet()
    direct_rns = _DirectRNS(send_result=True)

    monkeypatch.setattr(main, "_secure_dm_enabled", lambda: True)
    monkeypatch.setattr(main, "_rns_private_dm_ready", lambda: True)
    monkeypatch.setattr(main, "_verify_signed_event", lambda **_kwargs: (True, ""))
    monkeypatch.setattr(mesh_hashchain, "infonet", infonet)
    monkeypatch.setattr(mesh_rns, "rns_bridge", direct_rns)

    response = _post(
        "/api/mesh/dm/send",
        {
            "sender_id": TEST_SENDER_ID,
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
    assert body["transport"] == "reticulum"
    assert relay.count_claims("!sb_recipient1234", REQUEST_CLAIMS) == 0
    assert len(direct_rns.sent) == 1
    assert direct_rns.sent[0]["envelope"]["msg_id"] == "msg-reticulum-1"
    assert len(infonet.appended) == 0


def test_secure_dm_send_falls_back_to_relay(tmp_path, monkeypatch):
    relay = _fresh_relay(tmp_path, monkeypatch)
    infonet = _FakeInfonet()
    direct_rns = _DirectRNS(send_result=False)

    monkeypatch.setattr(main, "_secure_dm_enabled", lambda: True)
    monkeypatch.setattr(main, "_rns_private_dm_ready", lambda: True)
    monkeypatch.setattr(main, "_verify_signed_event", lambda **_kwargs: (True, ""))
    monkeypatch.setattr(mesh_hashchain, "infonet", infonet)
    monkeypatch.setattr(mesh_rns, "rns_bridge", direct_rns)

    response = _post(
        "/api/mesh/dm/send",
        {
            "sender_id": TEST_SENDER_ID,
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
    assert body["transport"] == "relay"
    assert "relay fallback" in body["detail"].lower()
    assert relay.count_claims("!sb_recipient1234", REQUEST_CLAIMS) == 1
    assert len(infonet.appended) == 0


def test_request_sender_seal_reduces_relay_sender_handle_on_fallback(tmp_path, monkeypatch):
    relay = _fresh_relay(tmp_path, monkeypatch)
    infonet = _FakeInfonet()
    direct_rns = _DirectRNS(send_result=False)
    relay_salt = "0123456789abcdef0123456789abcdef"
    expected_sender = "sealed:" + hmac.new(
        bytes.fromhex(relay_salt), TEST_SENDER_ID.encode("utf-8"), hashlib.sha256
    ).hexdigest()[:16]

    monkeypatch.setattr(main, "_secure_dm_enabled", lambda: True)
    monkeypatch.setattr(main, "_rns_private_dm_ready", lambda: True)
    monkeypatch.setattr(main, "_verify_signed_event", lambda **_kwargs: (True, ""))
    monkeypatch.setattr(mesh_hashchain, "infonet", infonet)
    monkeypatch.setattr(mesh_rns, "rns_bridge", direct_rns)

    response = _post(
        "/api/mesh/dm/send",
        {
            "sender_id": TEST_SENDER_ID,
            "recipient_id": "!sb_recipient1234",
            "delivery_class": "request",
            "ciphertext": "ciphertext",
            "sender_seal": "v3:test-seal",
            "relay_salt": relay_salt,
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
    assert body["transport"] == "relay"
    messages = relay.collect_claims("!sb_recipient1234", REQUEST_CLAIMS)
    assert [msg["msg_id"] for msg in messages] == ["msg-relay-sealed-1"]
    assert messages[0]["sender_id"] == expected_sender
    assert messages[0]["sender_id"] != TEST_SENDER_ID
    assert messages[0]["sender_seal"] == "v3:test-seal"


def test_request_sender_seal_reduces_direct_rns_sender_handle(tmp_path, monkeypatch):
    relay = _fresh_relay(tmp_path, monkeypatch)
    infonet = _FakeInfonet()
    direct_rns = _DirectRNS(send_result=True)
    relay_salt = "fedcba9876543210fedcba9876543210"
    expected_sender = "sealed:" + hmac.new(
        bytes.fromhex(relay_salt), TEST_SENDER_ID.encode("utf-8"), hashlib.sha256
    ).hexdigest()[:16]

    monkeypatch.setattr(main, "_secure_dm_enabled", lambda: True)
    monkeypatch.setattr(main, "_rns_private_dm_ready", lambda: True)
    monkeypatch.setattr(main, "_verify_signed_event", lambda **_kwargs: (True, ""))
    monkeypatch.setattr(mesh_hashchain, "infonet", infonet)
    monkeypatch.setattr(mesh_rns, "rns_bridge", direct_rns)

    response = _post(
        "/api/mesh/dm/send",
        {
            "sender_id": TEST_SENDER_ID,
            "recipient_id": "!sb_recipient1234",
            "delivery_class": "request",
            "ciphertext": "ciphertext",
            "sender_seal": "v3:test-seal",
            "relay_salt": relay_salt,
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
    assert body["transport"] == "reticulum"
    assert len(direct_rns.sent) == 1
    assert direct_rns.sent[0]["envelope"]["sender_id"] == expected_sender
    assert direct_rns.sent[0]["envelope"]["sender_id"] != TEST_SENDER_ID
    assert direct_rns.sent[0]["envelope"]["sender_seal"] == "v3:test-seal"
    assert relay.count_claims("!sb_recipient1234", REQUEST_CLAIMS) == 0


def test_request_sender_block_prevents_direct_rns_delivery(tmp_path, monkeypatch):
    relay = _fresh_relay(tmp_path, monkeypatch)
    infonet = _FakeInfonet()
    direct_rns = _DirectRNS(send_result=True)
    relay.block("!sb_recipient1234", TEST_SENDER_ID)

    monkeypatch.setattr(main, "_secure_dm_enabled", lambda: True)
    monkeypatch.setattr(main, "_rns_private_dm_ready", lambda: True)
    monkeypatch.setattr(main, "_verify_signed_event", lambda **_kwargs: (True, ""))
    monkeypatch.setattr(mesh_hashchain, "infonet", infonet)
    monkeypatch.setattr(mesh_rns, "rns_bridge", direct_rns)

    response = _post(
        "/api/mesh/dm/send",
        {
            "sender_id": TEST_SENDER_ID,
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

    monkeypatch.setattr(main, "_secure_dm_enabled", lambda: False)
    monkeypatch.setattr(main, "_verify_signed_event", lambda **_kwargs: (True, ""))
    monkeypatch.setattr(mesh_hashchain, "infonet", infonet)

    response = _post(
        "/api/mesh/dm/send",
        {
            "sender_id": TEST_SENDER_ID,
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


def test_secure_dm_send_rejects_replayed_msg_id_nonce(tmp_path, monkeypatch):
    relay = _fresh_relay(tmp_path, monkeypatch)
    infonet = _FakeInfonet()

    monkeypatch.setattr(main, "_secure_dm_enabled", lambda: False)
    monkeypatch.setattr(main, "_verify_signed_event", lambda **_kwargs: (True, ""))
    monkeypatch.setattr(mesh_hashchain, "infonet", infonet)

    payload = {
        "sender_id": TEST_SENDER_ID,
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
    second = _post("/api/mesh/dm/send", payload)

    assert first.status_code == 200
    assert first.json()["ok"] is True
    assert second.status_code == 200
    assert second.json() == {"ok": False, "detail": "nonce replay detected"}
    assert relay.count_claims("!sb_recipient1234", REQUEST_CLAIMS) == 1


def test_secure_dm_send_rejects_replayed_sequence_with_new_nonce(tmp_path, monkeypatch):
    _fresh_relay(tmp_path, monkeypatch)
    infonet = _FakeInfonet()

    monkeypatch.setattr(main, "_secure_dm_enabled", lambda: False)
    monkeypatch.setattr(main, "_verify_signed_event", lambda **_kwargs: (True, ""))
    monkeypatch.setattr(mesh_hashchain, "infonet", infonet)

    first = _post(
        "/api/mesh/dm/send",
        {
            "sender_id": TEST_SENDER_ID,
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

    monkeypatch.setattr(main, "_secure_dm_enabled", lambda: False)
    monkeypatch.setattr(main, "_verify_signed_event", lambda **_kwargs: (False, "Invalid signature"))
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

    monkeypatch.setattr(main, "_secure_dm_enabled", lambda: True)
    monkeypatch.setattr(main, "_rns_private_dm_ready", lambda: True)
    monkeypatch.setattr(main, "_anonymous_dm_hidden_transport_enforced", lambda: True)
    monkeypatch.setattr(main, "_verify_signed_event", lambda **_kwargs: (True, ""))
    monkeypatch.setattr(mesh_hashchain, "infonet", infonet)
    monkeypatch.setattr(mesh_rns, "rns_bridge", direct_rns)

    response = _post(
        "/api/mesh/dm/send",
        {
            "sender_id": TEST_SENDER_ID,
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
    assert body["transport"] == "relay"
    assert "off direct transport" in body["detail"].lower()
    assert relay.count_claims("!sb_recipient1234", REQUEST_CLAIMS) == 1
    assert len(direct_rns.sent) == 0
    assert len(infonet.appended) == 0


def test_secure_dm_poll_and_count_merge_relay_and_reticulum(tmp_path, monkeypatch):
    relay = _fresh_relay(tmp_path, monkeypatch)
    relay.deposit(
        sender_id="alice",
        recipient_id="bob",
        ciphertext="cipher-relay-dup",
        msg_id="dup",
        delivery_class="request",
    )
    relay.deposit(
        sender_id="alice",
        recipient_id="bob",
        ciphertext="cipher-relay-only",
        msg_id="relay-only",
        delivery_class="request",
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
        {
            "agent_id": "bob",
            "mailbox_claims": REQUEST_CLAIMS,
            "timestamp": NOW_TS(),
            "nonce": "nonce-poll",
            "public_key": "pub",
            "public_key_algo": "Ed25519",
            "signature": "sig",
            "sequence": 10,
            "protocol_version": "infonet/2",
        },
    )
    poll_body = poll_response.json()
    assert poll_response.status_code == 200
    assert poll_body["ok"] is True
    assert poll_body["count"] == 3
    assert {msg["msg_id"] for msg in poll_body["messages"]} == {"dup", "relay-only", "direct-only"}
    dup_message = next(msg for msg in poll_body["messages"] if msg["msg_id"] == "dup")
    assert dup_message["sender_id"] == "alice"
    assert dup_message["ciphertext"] == "cipher-relay-dup"

    count_response = _post(
        "/api/mesh/dm/count",
        {
            "agent_id": "bob",
            "mailbox_claims": REQUEST_CLAIMS,
            "timestamp": NOW_TS(),
            "nonce": "nonce-count",
            "public_key": "pub",
            "public_key_algo": "Ed25519",
            "signature": "sig",
            "sequence": 11,
            "protocol_version": "infonet/2",
        },
    )
    count_body = count_response.json()
    assert count_response.status_code == 200
    assert count_body["ok"] is True
    assert count_body["count"] == 2


def test_secure_dm_poll_marks_reduced_v3_request_recovery_fields(tmp_path, monkeypatch):
    relay = _fresh_relay(tmp_path, monkeypatch)
    relay.deposit(
        sender_id="sealed:relayv3",
        raw_sender_id="alice",
        recipient_id="bob",
        ciphertext="cipher-relay-v3",
        msg_id="relay-v3",
        delivery_class="request",
        sender_seal="v3:relay-seal",
    )
    relay.deposit(
        sender_id="alice",
        recipient_id="bob",
        ciphertext="cipher-legacy",
        msg_id="legacy-raw",
        delivery_class="request",
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
            }
        ],
        direct_ids={"direct-v3"},
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
        {
            "agent_id": "bob",
            "mailbox_claims": REQUEST_CLAIMS,
            "timestamp": NOW_TS(),
            "nonce": "nonce-poll-markers",
            "public_key": "pub",
            "public_key_algo": "Ed25519",
            "signature": "sig",
            "sequence": 12,
            "protocol_version": "infonet/2",
        },
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
    relay = _fresh_relay(tmp_path, monkeypatch)
    relay.deposit(
        sender_id="alice",
        recipient_id="bob",
        ciphertext="cipher-relay-raw",
        msg_id="dup-v2-over-raw",
        delivery_class="request",
    )

    direct_rns = _DirectRNS(
        direct_messages=[
            {
                "sender_id": "sealed:directv3",
                "ciphertext": "cipher-direct-v3",
                "timestamp": 101.0,
                "msg_id": "dup-v2-over-raw",
                "delivery_class": "request",
                "sender_seal": "v3:direct-seal",
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
        {
            "agent_id": "bob",
            "mailbox_claims": REQUEST_CLAIMS,
            "timestamp": NOW_TS(),
            "nonce": "nonce-poll-v2-over-raw",
            "public_key": "pub",
            "public_key_algo": "Ed25519",
            "signature": "sig",
            "sequence": 13,
            "protocol_version": "infonet/2",
        },
    )
    poll_body = poll_response.json()

    assert poll_response.status_code == 200
    assert poll_body["ok"] is True
    assert poll_body["count"] == 1
    message = poll_body["messages"][0]
    assert message["msg_id"] == "dup-v2-over-raw"
    assert message["sender_id"] == "sealed:directv3"
    assert message["ciphertext"] == "cipher-direct-v3"
    assert message["transport"] == "reticulum"
    assert message["request_contract_version"] == "request-v2-reduced-v3"
    assert message["sender_recovery_required"] is True
    assert message["sender_recovery_state"] == "pending"


def test_secure_dm_poll_prefers_legacy_raw_duplicate_over_legacy_sealed(tmp_path, monkeypatch):
    relay = _fresh_relay(tmp_path, monkeypatch)
    relay.deposit(
        sender_id="sealed:relaylegacy",
        raw_sender_id="alice",
        recipient_id="bob",
        ciphertext="cipher-relay-sealed",
        msg_id="dup-raw-over-sealed",
        delivery_class="request",
        sender_seal="v2:legacy-seal",
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
        {
            "agent_id": "bob",
            "mailbox_claims": REQUEST_CLAIMS,
            "timestamp": NOW_TS(),
            "nonce": "nonce-poll-raw-over-sealed",
            "public_key": "pub",
            "public_key_algo": "Ed25519",
            "signature": "sig",
            "sequence": 14,
            "protocol_version": "infonet/2",
        },
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
    relay = _fresh_relay(tmp_path, monkeypatch)
    relay.deposit(
        sender_id="sealed:sharedv3",
        raw_sender_id="alice",
        recipient_id="bob",
        ciphertext="cipher-relay-v3-dup",
        msg_id="dup-v2-tie",
        delivery_class="request",
        sender_seal="v3:relay-seal",
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
        {
            "agent_id": "bob",
            "mailbox_claims": REQUEST_CLAIMS,
            "timestamp": NOW_TS(),
            "nonce": "nonce-poll-v2-tie",
            "public_key": "pub",
            "public_key_algo": "Ed25519",
            "signature": "sig",
            "sequence": 15,
            "protocol_version": "infonet/2",
        },
    )
    poll_body = poll_response.json()

    assert poll_response.status_code == 200
    assert poll_body["ok"] is True
    assert poll_body["count"] == 1
    message = poll_body["messages"][0]
    assert message["msg_id"] == "dup-v2-tie"
    assert message["sender_id"] == "sealed:sharedv3"
    assert message["ciphertext"] == "cipher-relay-v3-dup"
    assert "transport" not in message
    assert message["request_contract_version"] == "request-v2-reduced-v3"
    assert message["sender_recovery_required"] is True
    assert message["sender_recovery_state"] == "pending"


def test_anonymous_mode_poll_and_count_ignore_reticulum(tmp_path, monkeypatch):
    relay = _fresh_relay(tmp_path, monkeypatch)
    relay.deposit(
        sender_id="alice",
        recipient_id="bob",
        ciphertext="cipher-relay-only",
        msg_id="relay-only",
        delivery_class="request",
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
    monkeypatch.setattr(mesh_hashchain, "infonet", infonet)
    monkeypatch.setattr(mesh_rns, "rns_bridge", direct_rns)

    poll_response = _post(
        "/api/mesh/dm/poll",
        {
            "agent_id": "bob",
            "mailbox_claims": REQUEST_CLAIMS,
            "timestamp": NOW_TS(),
            "nonce": "nonce-poll-anon",
            "public_key": "pub",
            "public_key_algo": "Ed25519",
            "signature": "sig",
            "sequence": 12,
            "protocol_version": "infonet/2",
        },
    )
    poll_body = poll_response.json()
    assert poll_response.status_code == 200
    assert poll_body["ok"] is True
    assert poll_body["count"] == 1
    assert {msg["msg_id"] for msg in poll_body["messages"]} == {"relay-only"}

    count_response = _post(
        "/api/mesh/dm/count",
        {
            "agent_id": "bob",
            "mailbox_claims": REQUEST_CLAIMS,
            "timestamp": NOW_TS(),
            "nonce": "nonce-count-anon",
            "public_key": "pub",
            "public_key_algo": "Ed25519",
            "signature": "sig",
            "sequence": 13,
            "protocol_version": "infonet/2",
        },
    )
    count_body = count_response.json()
    assert count_response.status_code == 200
    assert count_body["ok"] is True
    assert count_body["count"] == 0
