import json
import time

from services.config import get_settings
from services.mesh import mesh_dm_relay, mesh_schema, mesh_secure_storage

REQUEST_CLAIM = [{"type": "requests", "token": "request-claim-token"}]


def _fresh_relay(tmp_path, monkeypatch):
    monkeypatch.setattr(mesh_dm_relay, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_dm_relay, "RELAY_FILE", tmp_path / "dm_relay.json")
    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    get_settings.cache_clear()
    return mesh_dm_relay.DMRelay()


def test_dm_key_registration_is_monotonic(tmp_path, monkeypatch):
    relay = _fresh_relay(tmp_path, monkeypatch)

    ok, reason, meta = relay.register_dh_key(
        "alice",
        "pub1",
        "X25519",
        100,
        "sig1",
        "nodepub",
        "Ed25519",
        "infonet/2",
        1,
    )
    assert ok, reason
    assert meta["accepted_sequence"] == 1
    assert meta["bundle_fingerprint"]

    ok, reason, _ = relay.register_dh_key(
        "alice",
        "pub1",
        "X25519",
        100,
        "sig1",
        "nodepub",
        "Ed25519",
        "infonet/2",
        1,
    )
    assert not ok
    assert "rollback" in reason.lower() or "replay" in reason.lower()

    ok, reason, _ = relay.register_dh_key(
        "alice",
        "pub2",
        "X25519",
        99,
        "sig2",
        "nodepub",
        "Ed25519",
        "infonet/2",
        2,
    )
    assert not ok
    assert "older" in reason.lower()

    ok, reason, meta = relay.register_dh_key(
        "alice",
        "pub3",
        "X25519",
        101,
        "sig3",
        "nodepub",
        "Ed25519",
        "infonet/2",
        2,
    )
    assert ok, reason
    assert meta["accepted_sequence"] == 2


def test_secure_mailbox_claims_split_requests_and_shared(tmp_path, monkeypatch):
    relay = _fresh_relay(tmp_path, monkeypatch)

    request_result = relay.deposit(
        sender_id="alice",
        recipient_id="bob",
        ciphertext="cipher_req",
        msg_id="msg_req",
        delivery_class="request",
    )
    shared_result = relay.deposit(
        sender_id="carol",
        recipient_id="bob",
        ciphertext="cipher_shared",
        msg_id="msg_shared",
        delivery_class="shared",
        recipient_token="sharedtoken",
    )

    assert request_result["ok"]
    assert shared_result["ok"]
    assert relay.count_legacy(agent_id="bob") == 0

    request_claims = REQUEST_CLAIM
    shared_claims = [{"type": "shared", "token": "sharedtoken"}]

    assert relay.count_claims("bob", request_claims) == 1
    assert relay.count_claims("bob", shared_claims) == 1

    request_messages = relay.collect_claims("bob", request_claims)
    assert [msg["msg_id"] for msg in request_messages] == ["msg_req"]
    assert request_messages[0]["delivery_class"] == "request"
    assert relay.count_claims("bob", request_claims) == 0
    assert relay.count_claims("bob", [{"type": "requests"}]) == 0

    shared_messages = relay.collect_claims("bob", shared_claims)
    assert [msg["msg_id"] for msg in shared_messages] == ["msg_shared"]
    assert shared_messages[0]["delivery_class"] == "shared"
    assert relay.count_claims("bob", shared_claims) == 0


def test_legacy_collect_and_count_require_agent_token(tmp_path, monkeypatch):
    relay = _fresh_relay(tmp_path, monkeypatch)

    relay._mailboxes["legacy-token"].append(
        mesh_dm_relay.DMMessage(
            sender_id="alice",
            ciphertext="cipher",
            timestamp=time.time(),
            msg_id="legacy-1",
            delivery_class="request",
        )
    )

    assert relay.collect_legacy(agent_id="bob") == []
    assert relay.count_legacy(agent_id="bob") == 0
    assert relay.count_legacy(agent_token="legacy-token") == 1


def test_nonce_replay_and_memory_only_spool(tmp_path, monkeypatch):
    monkeypatch.setenv("MESH_DM_PERSIST_SPOOL", "false")
    relay = _fresh_relay(tmp_path, monkeypatch)

    result = relay.deposit(
        sender_id="alice",
        recipient_id="bob",
        ciphertext="cipher",
        msg_id="msg1",
        delivery_class="request",
    )
    assert result["ok"]
    assert mesh_dm_relay.RELAY_FILE.exists()

    payload = json.loads(mesh_dm_relay.RELAY_FILE.read_text(encoding="utf-8"))
    assert payload.get("kind") == "sb_secure_json"

    restored = mesh_secure_storage.read_secure_json(mesh_dm_relay.RELAY_FILE, lambda: {})
    assert "mailboxes" not in restored

    ok, reason = relay.consume_nonce("bob", "nonce-1", 100)
    assert ok, reason
    ok, reason = relay.consume_nonce("bob", "nonce-1", 100)
    assert not ok
    assert reason == "nonce replay detected"


def test_request_mailbox_token_binding_requires_presented_token(tmp_path, monkeypatch):
    relay = _fresh_relay(tmp_path, monkeypatch)

    legacy_key = relay.mailbox_key_for_delivery(
        recipient_id="bob",
        delivery_class="request",
    )
    presented_token = "mailbox-token-bob"
    hashed = relay._hashed_mailbox_token(presented_token)

    assert legacy_key != hashed
    claimed = relay.claim_mailbox_keys("bob", [{"type": "requests", "token": presented_token}])
    assert claimed[0] == hashed
    assert legacy_key in claimed
    assert relay.mailbox_key_for_delivery(recipient_id="bob", delivery_class="request") == hashed


def test_shared_delivery_uses_hashed_mailbox_token(tmp_path, monkeypatch):
    relay = _fresh_relay(tmp_path, monkeypatch)

    result = relay.deposit(
        sender_id="alice",
        recipient_id="",
        ciphertext="cipher_shared",
        msg_id="msg_shared_hash",
        delivery_class="shared",
        recipient_token="shared-mailbox-token",
        sender_token_hash="abc123",
    )

    assert result["ok"] is True
    mailbox_key = relay._hashed_mailbox_token("shared-mailbox-token")
    assert list(relay._mailboxes.keys()) == [mailbox_key]
    assert relay._mailboxes[mailbox_key][0].sender_id == "sender_token:abc123"


def test_request_and_shared_claims_freeze_current_sender_identity_contract(tmp_path, monkeypatch):
    relay = _fresh_relay(tmp_path, monkeypatch)

    request_result = relay.deposit(
        sender_id="alice",
        recipient_id="bob",
        ciphertext="cipher-req",
        msg_id="msg-req-1",
        delivery_class="request",
    )
    shared_result = relay.deposit(
        sender_id="alice",
        recipient_id="",
        ciphertext="cipher-shared",
        msg_id="msg-shared-1",
        delivery_class="shared",
        recipient_token="shared-mailbox-token",
        sender_token_hash="abc123",
        sender_seal="v3:sealed",
    )

    assert request_result["ok"] is True
    assert shared_result["ok"] is True

    request_messages = relay.collect_claims("bob", [{"type": "requests", "token": "request-claim-token"}])
    shared_messages = relay.collect_claims("bob", [{"type": "shared", "token": "shared-mailbox-token"}])

    assert request_messages == [
        {
            "sender_id": "alice",
            "ciphertext": "cipher-req",
            "timestamp": request_messages[0]["timestamp"],
            "msg_id": "msg-req-1",
            "delivery_class": "request",
            "sender_seal": "",
            "format": "dm1",
            "session_welcome": "",
        }
    ]
    assert shared_messages == [
        {
            "sender_id": "sender_token:abc123",
            "ciphertext": "cipher-shared",
            "timestamp": shared_messages[0]["timestamp"],
            "msg_id": "msg-shared-1",
            "delivery_class": "shared",
            "sender_seal": "v3:sealed",
            "format": "dm1",
            "session_welcome": "",
        }
    ]


def test_block_purges_and_rejects_reduced_sender_handles(tmp_path, monkeypatch):
    relay = _fresh_relay(tmp_path, monkeypatch)

    first = relay.deposit(
        sender_id="sealed:first",
        raw_sender_id="alice",
        recipient_id="bob",
        ciphertext="cipher-req",
        msg_id="msg-sealed-1",
        delivery_class="request",
        sender_seal="v3:test-seal",
    )

    assert first["ok"] is True
    relay.block("bob", "alice")
    assert relay.count_claims("bob", REQUEST_CLAIM) == 0

    second = relay.deposit(
        sender_id="sealed:second",
        raw_sender_id="alice",
        recipient_id="bob",
        ciphertext="cipher-req-2",
        msg_id="msg-sealed-2",
        delivery_class="request",
        sender_seal="v3:test-seal",
    )

    assert second == {"ok": False, "detail": "Recipient is not accepting your messages"}
    assert relay.count_claims("bob", REQUEST_CLAIM) == 0


def test_nonce_cache_is_bounded_and_expires_entries(tmp_path, monkeypatch):
    monkeypatch.setenv("MESH_DM_NONCE_CACHE_MAX", "2")
    relay = _fresh_relay(tmp_path, monkeypatch)
    current = {"value": 1_000.0}
    monkeypatch.setattr(mesh_dm_relay.time, "time", lambda: current["value"])

    assert relay.consume_nonce("bob", "nonce-1", 1_000)[0] is True
    assert relay.consume_nonce("bob", "nonce-2", 1_000)[0] is True
    assert len(relay._nonce_cache) == 2

    ok, reason = relay.consume_nonce("bob", "nonce-3", 1_000)
    assert ok is False
    assert reason == "nonce cache at capacity"
    assert len(relay._nonce_cache) == 2
    assert "bob:nonce-1" in relay._nonce_cache
    assert "bob:nonce-2" in relay._nonce_cache

    current["value"] = 1_000.0 + 301.0
    assert relay.consume_nonce("bob", "nonce-2", 1_000)[0] is True


def test_dm_schema_requires_tokens_for_all_mailbox_claims():
    ok, reason = mesh_schema.validate_event_payload(
        "dm_poll",
        {
            "mailbox_claims": [{"type": "requests", "token": ""}],
            "timestamp": 123,
            "nonce": "abc",
        },
    )
    assert not ok
    assert "token" in reason.lower()

    ok, reason = mesh_schema.validate_event_payload(
        "dm_count",
        {
            "mailbox_claims": [{"type": "shared", "token": ""}],
            "timestamp": 123,
            "nonce": "abc",
        },
    )
    assert not ok
    assert "token" in reason.lower()

    ok, reason = mesh_schema.validate_event_payload(
        "dm_message",
        {
            "recipient_id": "bob",
            "delivery_class": "shared",
            "recipient_token": "",
            "ciphertext": "cipher",
            "format": "mls1",
            "msg_id": "m1",
            "timestamp": 123,
        },
    )
    assert not ok
    assert "recipient_token" in reason.lower()
