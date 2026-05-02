import json
import time

import pytest

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
    base_timestamp = int(time.time())

    ok, reason, meta = relay.register_dh_key(
        "alice",
        "pub1",
        "X25519",
        base_timestamp,
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
        base_timestamp,
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
        base_timestamp - 1,
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
        base_timestamp + 1,
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
        sender_token_hash="reqtok-msg-req",
    )
    shared_result = relay.deposit(
        sender_id="carol",
        recipient_id="bob",
        ciphertext="cipher_shared",
        msg_id="msg_shared",
        delivery_class="shared",
        recipient_token="sharedtoken",
        sender_token_hash="sharedtok-msg-shared",
    )

    assert request_result["ok"]
    assert shared_result["ok"]
    assert relay.count_legacy(agent_id="bob") == 0

    request_claims = REQUEST_CLAIM
    shared_claims = [{"type": "shared", "token": "sharedtoken"}]

    assert relay.count_claims("bob", request_claims) == 1
    assert relay.count_claims("bob", shared_claims) == 1

    request_messages, _ = relay.collect_claims("bob", request_claims)
    assert [msg["msg_id"] for msg in request_messages] == ["msg_req"]
    assert request_messages[0]["delivery_class"] == "request"
    assert relay.count_claims("bob", request_claims) == 0
    assert relay.count_claims("bob", [{"type": "requests"}]) == 0

    shared_messages, _ = relay.collect_claims("bob", shared_claims)
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

    assert relay.collect_legacy(agent_id="bob") == ([], False)
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
        sender_token_hash="reqtok-msg1",
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


def test_mailbox_bindings_are_not_persisted_by_default(tmp_path, monkeypatch):
    relay = _fresh_relay(tmp_path, monkeypatch)

    claimed = relay.claim_mailbox_keys("bob", REQUEST_CLAIM)
    assert claimed
    relay._flush()

    restored = mesh_secure_storage.read_secure_json(mesh_dm_relay.RELAY_FILE, lambda: {})
    assert "mailbox_bindings" not in restored


def test_relay_flush_failure_is_logged_counted_and_fatal_in_tests(tmp_path, monkeypatch, caplog):
    relay = _fresh_relay(tmp_path, monkeypatch)
    relay._dh_keys["alice"] = {"dh_pub_key": "pub", "timestamp": time.time()}
    relay._dirty = True
    metric_calls = []

    def _explode(*_args, **_kwargs):
        raise IOError("disk full")

    monkeypatch.setattr(mesh_dm_relay, "write_secure_json", _explode)
    monkeypatch.setattr(mesh_dm_relay, "metrics_inc", metric_calls.append)

    with caplog.at_level("ERROR", logger="services.mesh.mesh_dm_relay"):
        with pytest.raises(IOError, match="disk full"):
            relay._flush()

    assert metric_calls == ["dm_relay_persist_failure"]
    assert relay._dirty is True
    assert "dm relay flush failed" in caplog.text
    assert "disk full" in caplog.text


def test_relay_save_flushes_synchronously_during_pytest(tmp_path, monkeypatch):
    relay = _fresh_relay(tmp_path, monkeypatch)
    mesh_secure_storage.write_secure_json(mesh_dm_relay.RELAY_FILE, {"saved_at": 0})
    flush_calls = []

    monkeypatch.setattr(relay, "_flush", lambda: flush_calls.append("flushed"))

    relay._save()

    assert flush_calls == ["flushed"]
    assert relay._save_timer is None


def test_mailbox_bindings_persist_only_when_explicitly_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("MESH_DM_METADATA_PERSIST", "true")
    monkeypatch.setenv("MESH_DM_METADATA_PERSIST_ACKNOWLEDGE", "true")
    relay = _fresh_relay(tmp_path, monkeypatch)

    claimed = relay.claim_mailbox_keys("bob", REQUEST_CLAIM)
    assert claimed
    relay._flush()

    restored = mesh_secure_storage.read_secure_json(mesh_dm_relay.RELAY_FILE, lambda: {})
    assert restored["mailbox_bindings"]["bob"]["requests"]["token_hash"] == relay._hashed_mailbox_token(
        "request-claim-token"
    )
    assert restored["mailbox_bindings"]["bob"]["requests"]["bound_at"] > 0
    assert restored["mailbox_bindings"]["bob"]["requests"]["last_used"] > 0
    assert restored["mailbox_bindings"]["bob"]["requests"]["expires_at"] > 0

    reloaded = _fresh_relay(tmp_path, monkeypatch)
    assert reloaded._bound_mailbox_key("bob", "requests") == relay._hashed_mailbox_token(
        "request-claim-token"
    )


def test_mailbox_bindings_remain_memory_only_without_acknowledge_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("MESH_DM_METADATA_PERSIST", "true")
    monkeypatch.delenv("MESH_DM_METADATA_PERSIST_ACKNOWLEDGE", raising=False)
    relay = _fresh_relay(tmp_path, monkeypatch)

    claimed = relay.claim_mailbox_keys("bob", REQUEST_CLAIM)
    assert claimed
    relay._flush()

    restored = mesh_secure_storage.read_secure_json(mesh_dm_relay.RELAY_FILE, lambda: {})
    assert "mailbox_bindings" not in restored

    reloaded = _fresh_relay(tmp_path, monkeypatch)
    assert reloaded._bound_mailbox_key("bob", "requests") == ""


def test_legacy_mailbox_bindings_are_scrubbed_when_persistence_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("MESH_DM_METADATA_PERSIST", "false")
    monkeypatch.setattr(mesh_dm_relay, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_dm_relay, "RELAY_FILE", tmp_path / "dm_relay.json")
    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    get_settings.cache_clear()
    current_timestamp = int(time.time())

    mesh_secure_storage.write_secure_json(
        mesh_dm_relay.RELAY_FILE,
        {
            "saved_at": 123,
            "dh_keys": {"alice": {"dh_pub_key": "pub", "timestamp": current_timestamp}},
            "prekey_bundles": {},
            "witnesses": {},
            "blocks": {},
            "nonce_caches": {},
            "stats": {"messages_in_memory": 0},
            "mailbox_bindings": {
                "bob": {
                    "requests": {
                        "token_hash": "legacy-token-hash",
                        "last_used": 111,
                    }
                }
            },
        },
    )

    relay = mesh_dm_relay.DMRelay()

    assert relay.get_dh_key("alice") == {"dh_pub_key": "pub", "timestamp": current_timestamp}
    assert relay._bound_mailbox_key("bob", "requests") == ""
    assert relay._dirty is True

    relay._flush()
    restored = mesh_secure_storage.read_secure_json(mesh_dm_relay.RELAY_FILE, lambda: {})
    assert "mailbox_bindings" not in restored


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


def test_request_mailbox_binding_expires_on_runtime_access(tmp_path, monkeypatch):
    monkeypatch.setenv("MESH_DM_BINDING_TTL_DAYS", "1")
    relay = _fresh_relay(tmp_path, monkeypatch)
    now = [1_700_000_000.0]
    hashed = relay._hashed_mailbox_token("request-claim-token")

    monkeypatch.setattr(mesh_dm_relay.time, "time", lambda: now[0])

    claimed = relay.claim_mailbox_keys("bob", REQUEST_CLAIM)
    assert claimed[0] == hashed
    assert relay._bound_mailbox_key("bob", "requests") == hashed

    now[0] += 86401

    assert relay._bound_mailbox_key("bob", "requests") == ""
    assert relay.mailbox_key_for_delivery(recipient_id="bob", delivery_class="request") == relay._mailbox_key(
        "requests",
        "bob",
    )


def test_request_mailbox_binding_rotation_claims_previous_bound_once(tmp_path, monkeypatch):
    relay = _fresh_relay(tmp_path, monkeypatch)
    old_hash = "legacy-bound-hash"
    relay._mailbox_bindings["bob"]["requests"] = {
        "token_hash": old_hash,
        "bound_at": time.time(),
        "last_used": time.time(),
    }

    claimed = relay.claim_mailbox_keys("bob", [{"type": "requests", "token": "rotated-token"}])
    new_hash = relay._hashed_mailbox_token("rotated-token")

    assert old_hash in claimed
    assert new_hash in claimed
    assert relay.mailbox_key_for_delivery(recipient_id="bob", delivery_class="request") == new_hash


def test_stale_mailbox_binding_expires_and_is_pruned(tmp_path, monkeypatch):
    relay = _fresh_relay(tmp_path, monkeypatch)
    now = [1_700_000_000.0]

    monkeypatch.setattr(mesh_dm_relay.time, "time", lambda: now[0])
    relay._mailbox_bindings["bob"]["requests"] = {
        "token_hash": "expired-binding",
        "bound_at": now[0] - (4 * 86400),
        "last_used": now[0] - (13 * 60 * 60),
    }

    assert relay._bound_mailbox_key("bob", "requests") == ""
    assert "bob" not in relay._mailbox_bindings


def test_active_mailbox_binding_refreshes_without_breaking_delivery(tmp_path, monkeypatch):
    relay = _fresh_relay(tmp_path, monkeypatch)
    now = [1_700_000_000.0]

    monkeypatch.setattr(mesh_dm_relay.time, "time", lambda: now[0])
    first_claim = relay.claim_mailbox_keys("bob", REQUEST_CLAIM)
    binding_before = dict(relay._mailbox_bindings["bob"]["requests"])
    request_hash = relay._hashed_mailbox_token("request-claim-token")

    assert first_claim[0] == request_hash

    now[0] += (12 * 60 * 60) + 1
    refreshed_claim = relay.claim_mailbox_keys("bob", REQUEST_CLAIM)
    binding_after = dict(relay._mailbox_bindings["bob"]["requests"])

    assert request_hash in refreshed_claim
    assert binding_after["bound_at"] > binding_before["bound_at"]
    assert relay.mailbox_key_for_delivery(recipient_id="bob", delivery_class="request") == request_hash

    delivered_after_refresh = relay.deposit(
        sender_id="alice",
        recipient_id="bob",
        ciphertext="cipher-after-refresh",
        msg_id="msg-after-refresh",
        delivery_class="request",
        sender_token_hash="reqtok-msg-after-refresh",
    )
    assert delivered_after_refresh["ok"] is True

    delivered, _ = relay.collect_claims("bob", REQUEST_CLAIM)
    assert [message["msg_id"] for message in delivered] == ["msg-after-refresh"]


def test_restart_does_not_preserve_expired_mailbox_metadata_as_active(tmp_path, monkeypatch):
    monkeypatch.setenv("MESH_DM_METADATA_PERSIST", "true")
    monkeypatch.setenv("MESH_DM_METADATA_PERSIST_ACKNOWLEDGE", "true")
    monkeypatch.setenv("MESH_DM_BINDING_TTL_DAYS", "1")
    monkeypatch.setattr(mesh_dm_relay, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_dm_relay, "RELAY_FILE", tmp_path / "dm_relay.json")
    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    get_settings.cache_clear()
    now = {"value": 1_700_000_000.0}
    monkeypatch.setattr(mesh_dm_relay.time, "time", lambda: now["value"])

    mesh_secure_storage.write_secure_json(
        mesh_dm_relay.RELAY_FILE,
        {
            "saved_at": int(now["value"]),
            "dh_keys": {},
            "prekey_bundles": {},
            "prekey_lookup_aliases": {},
            "witnesses": {},
            "blocks": {},
            "nonce_caches": {},
            "stats": {"messages_in_memory": 0},
            "mailbox_bindings": {
                "bob": {
                    "requests": {
                        "token_hash": "stale-binding",
                        "bound_at": now["value"] - (2 * 86400),
                        "last_used": now["value"] - (2 * 86400),
                        "expires_at": now["value"] - 1,
                    }
                }
            },
        },
    )

    reloaded = mesh_dm_relay.DMRelay()

    assert reloaded._bound_mailbox_key("bob", "requests") == ""
    assert "bob" not in reloaded._mailbox_bindings
    assert reloaded.consume_nonce("bob", "nonce-after-prune", int(now["value"])) == (True, "ok")
    assert reloaded.consume_nonce("bob", "nonce-after-prune", int(now["value"])) == (
        False,
        "nonce replay detected",
    )


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
        sender_token_hash="reqtok-msg-req-1",
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

    request_messages, _ = relay.collect_claims("bob", [{"type": "requests", "token": "request-claim-token"}])
    shared_messages, _ = relay.collect_claims("bob", [{"type": "shared", "token": "shared-mailbox-token"}])

    assert request_messages == [
        {
            "sender_id": "sender_token:reqtok-msg-req-1",
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
        sender_token_hash="reqtok-sealed-1",
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
        sender_token_hash="reqtok-sealed-2",
    )

    assert second == {"ok": False, "detail": "Recipient is not accepting your messages"}
    assert relay.count_claims("bob", REQUEST_CLAIM) == 0


def test_sender_block_refs_are_recipient_scoped(tmp_path, monkeypatch):
    relay = _fresh_relay(tmp_path, monkeypatch)

    first = relay.deposit(
        sender_id="sealed:alpha",
        raw_sender_id="alice",
        recipient_id="bob",
        ciphertext="cipher-bob",
        msg_id="msg-bob-1",
        delivery_class="request",
        sender_seal="v3:test-seal",
        sender_token_hash="reqtok-alpha",
    )
    second = relay.deposit(
        sender_id="sealed:beta",
        raw_sender_id="alice",
        recipient_id="carol",
        ciphertext="cipher-carol",
        msg_id="msg-carol-1",
        delivery_class="request",
        sender_seal="v3:test-seal",
        sender_token_hash="reqtok-beta",
    )

    assert first["ok"] is True
    assert second["ok"] is True

    bob_key = relay.mailbox_key_for_delivery(recipient_id="bob", delivery_class="request")
    carol_key = relay.mailbox_key_for_delivery(recipient_id="carol", delivery_class="request")
    bob_ref = relay._mailboxes[bob_key][0].sender_block_ref
    carol_ref = relay._mailboxes[carol_key][0].sender_block_ref

    assert bob_ref
    assert carol_ref
    assert bob_ref != carol_ref

    relay.block("bob", "alice")

    assert relay.is_blocked("bob", "alice") is True
    assert relay.is_blocked("carol", "alice") is False
    assert relay.count_claims("bob", REQUEST_CLAIM) == 0
    assert relay.count_claims("carol", [{"type": "requests", "token": "claim-carol"}]) == 1


def test_nonce_cache_is_bounded_and_expires_entries(tmp_path, monkeypatch):
    monkeypatch.setenv("MESH_DM_NONCE_CACHE_MAX", "2")
    monkeypatch.setenv("MESH_DM_NONCE_PER_AGENT_MAX", "2")
    relay = _fresh_relay(tmp_path, monkeypatch)
    current = {"value": 1_000.0}
    monkeypatch.setattr(mesh_dm_relay.time, "time", lambda: current["value"])

    assert relay.consume_nonce("bob", "nonce-1", 1_000)[0] is True
    assert relay.consume_nonce("bob", "nonce-2", 1_000)[0] is True
    assert relay._total_nonce_count() == 2

    ok, reason = relay.consume_nonce("bob", "nonce-3", 1_000)
    assert ok is False
    assert reason == "nonce cache at capacity"
    assert relay._total_nonce_count() == 2
    assert "nonce-1" in relay._nonce_caches["bob"]
    assert "nonce-2" in relay._nonce_caches["bob"]

    current["value"] = 1_000.0 + 301.0
    assert relay.consume_nonce("bob", "nonce-2", 1_000)[0] is True


def test_witness_history_uses_configured_ttl(tmp_path, monkeypatch):
    monkeypatch.setenv("MESH_DM_WITNESS_TTL_DAYS", "1")
    relay = _fresh_relay(tmp_path, monkeypatch)
    current = {"value": 10_000.0}
    monkeypatch.setattr(mesh_dm_relay.time, "time", lambda: current["value"])

    ok, reason = relay.record_witness("witness-a", "alice", "dh-pub-a", int(current["value"]))
    assert ok is True, reason
    assert relay.get_witnesses("alice", "dh-pub-a") != []

    current["value"] += 2 * 86400
    assert relay.get_witnesses("alice", "dh-pub-a") == []
    assert "alice" not in relay._witnesses


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
