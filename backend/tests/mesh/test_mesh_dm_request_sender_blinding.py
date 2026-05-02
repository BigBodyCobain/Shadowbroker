"""Tests for P2A: request-mailbox sender identity blinding.

Proves that:
  1. Request delivery with sender_token_hash blinds relay-visible sender identity.
  2. Request delivery without sender_token_hash is rejected.
  3. Block/refusal still works against the true authority sender even when blinded.
  4. Shared delivery sender_token blinding does not regress.
  5. Annotation logic recognizes sender_token:-prefixed request messages for recovery.
  6. Duplicate authority ranking treats sender_token: as blinded (rank 1).
"""

import time

from services.config import get_settings
from services.mesh import mesh_dm_relay, mesh_secure_storage

REQUEST_CLAIM = [{"type": "requests", "token": "request-claim-token"}]


def _fresh_relay(tmp_path, monkeypatch):
    monkeypatch.setattr(mesh_dm_relay, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_dm_relay, "RELAY_FILE", tmp_path / "dm_relay.json")
    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    get_settings.cache_clear()
    return mesh_dm_relay.DMRelay()


# ---------------------------------------------------------------------------
# 1. Hardened request delivery blinds sender identity
# ---------------------------------------------------------------------------

class TestRequestSenderTokenBlinding:
    """When sender_token_hash is provided, request delivery must use it."""

    def test_request_deposit_with_sender_token_hash_blinds_sender(self, tmp_path, monkeypatch):
        """Request delivery with sender_token_hash → relay stores sender_token:{hash}."""
        relay = _fresh_relay(tmp_path, monkeypatch)

        result = relay.deposit(
            sender_id="alice",
            recipient_id="bob",
            ciphertext="cipher-req",
            msg_id="msg-req-1",
            delivery_class="request",
            sender_token_hash="tok_abc123",
        )

        assert result["ok"] is True
        mailbox_key = relay.mailbox_key_for_delivery(recipient_id="bob", delivery_class="request")
        stored = relay._mailboxes[mailbox_key][0]
        assert stored.sender_id == "sender_token:tok_abc123"
        assert not stored.sender_id.startswith("alice")

    def test_request_deposit_with_sender_token_hash_and_seal_blinds_sender(self, tmp_path, monkeypatch):
        """Request delivery with both sender_seal and sender_token_hash → sender_token wins."""
        relay = _fresh_relay(tmp_path, monkeypatch)

        result = relay.deposit(
            sender_id="sealed:derived_hmac",
            raw_sender_id="alice",
            recipient_id="bob",
            ciphertext="cipher-req",
            msg_id="msg-req-2",
            delivery_class="request",
            sender_seal="v3:test-seal",
            sender_token_hash="tok_xyz789",
        )

        assert result["ok"] is True
        mailbox_key = relay.mailbox_key_for_delivery(recipient_id="bob", delivery_class="request")
        stored = relay._mailboxes[mailbox_key][0]
        assert stored.sender_id == "sender_token:tok_xyz789"
        # Must not contain the sealed: prefix or raw sender
        assert "sealed:" not in stored.sender_id
        assert "alice" not in stored.sender_id

    def test_request_collect_returns_blinded_sender(self, tmp_path, monkeypatch):
        """Collected request messages expose only the blinded sender_id."""
        relay = _fresh_relay(tmp_path, monkeypatch)

        result = relay.deposit(
            sender_id="sealed:hmac_val",
            raw_sender_id="alice",
            recipient_id="bob",
            ciphertext="cipher-req",
            msg_id="msg-collect-1",
            delivery_class="request",
            sender_seal="v3:test-seal",
            sender_token_hash="tok_collect",
        )

        messages, _ = relay.collect_claims("bob", REQUEST_CLAIM)
        assert len(messages) == 1
        assert messages[0]["sender_id"] == "sender_token:tok_collect"
        assert messages[0]["sender_seal"] == "v3:test-seal"
        # Raw sender must not leak
        assert "alice" not in str(messages[0])


# ---------------------------------------------------------------------------
# 2. Request delivery without sender_token_hash is rejected
# ---------------------------------------------------------------------------

class TestRequestDeliveryRequiresSenderToken:
    """Without sender_token_hash, request delivery must fail closed."""

    def test_request_without_sender_token_hash_is_rejected(self, tmp_path, monkeypatch):
        """Legacy request deposit without sender_token_hash → raw sender_id preserved."""
        relay = _fresh_relay(tmp_path, monkeypatch)

        result = relay.deposit(
            sender_id="alice",
            recipient_id="bob",
            ciphertext="cipher-legacy",
            msg_id="msg-legacy-1",
            delivery_class="request",
        )

        assert result["ok"] is False
        assert result["detail"] == "sender_token required for request delivery"

    def test_request_with_sealed_but_no_token_hash_is_rejected(self, tmp_path, monkeypatch):
        """Sealed request delivery is also rejected without sender_token_hash."""
        relay = _fresh_relay(tmp_path, monkeypatch)

        result = relay.deposit(
            sender_id="sealed:hmac_derived",
            raw_sender_id="alice",
            recipient_id="bob",
            ciphertext="cipher-sealed",
            msg_id="msg-sealed-legacy",
            delivery_class="request",
            sender_seal="v3:test-seal",
        )

        assert result["ok"] is False
        assert result["detail"] == "sender_token required for request delivery"


# ---------------------------------------------------------------------------
# 3. Block/refusal works against true authority sender
# ---------------------------------------------------------------------------

class TestBlockWorksWithBlindedRequestSender:
    """Blocking must use the authority sender, not the blinded relay identity."""

    def test_block_rejects_blinded_request_from_blocked_sender(self, tmp_path, monkeypatch):
        """Block alice → reject even when relay_sender_id is sender_token:..."""
        relay = _fresh_relay(tmp_path, monkeypatch)

        first = relay.deposit(
            sender_id="sender_token:tok1",
            raw_sender_id="alice",
            recipient_id="bob",
            ciphertext="cipher-1",
            msg_id="msg-block-1",
            delivery_class="request",
            sender_seal="v3:test-seal",
            sender_token_hash="tok1",
        )
        assert first["ok"] is True

        relay.block("bob", "alice")

        second = relay.deposit(
            sender_id="sender_token:tok2",
            raw_sender_id="alice",
            recipient_id="bob",
            ciphertext="cipher-2",
            msg_id="msg-block-2",
            delivery_class="request",
            sender_seal="v3:test-seal",
            sender_token_hash="tok2",
        )
        assert second["ok"] is False
        assert "not accepting" in second["detail"]

    def test_block_purges_existing_blinded_request_messages(self, tmp_path, monkeypatch):
        """Blocking should purge already-deposited blinded request messages."""
        relay = _fresh_relay(tmp_path, monkeypatch)

        relay.deposit(
            sender_id="sender_token:tok_purge",
            raw_sender_id="alice",
            recipient_id="bob",
            ciphertext="cipher-purge",
            msg_id="msg-purge-1",
            delivery_class="request",
            sender_seal="v3:test-seal",
            sender_token_hash="tok_purge",
        )
        assert relay.count_claims("bob", REQUEST_CLAIM) == 1

        relay.block("bob", "alice")
        assert relay.count_claims("bob", REQUEST_CLAIM) == 0


# ---------------------------------------------------------------------------
# 4. Shared delivery sender_token blinding does not regress
# ---------------------------------------------------------------------------

class TestSharedDeliveryNoRegression:
    """Shared delivery must continue to use sender_token:{hash} as before."""

    def test_shared_deposit_still_uses_sender_token_hash(self, tmp_path, monkeypatch):
        relay = _fresh_relay(tmp_path, monkeypatch)

        result = relay.deposit(
            sender_id="alice",
            recipient_id="",
            ciphertext="cipher-shared",
            msg_id="msg-shared-1",
            delivery_class="shared",
            recipient_token="shared-tok",
            sender_token_hash="shared_hash_abc",
        )

        assert result["ok"] is True
        mailbox_key = relay._hashed_mailbox_token("shared-tok")
        stored = relay._mailboxes[mailbox_key][0]
        assert stored.sender_id == "sender_token:shared_hash_abc"


# ---------------------------------------------------------------------------
# 5. Annotation logic recognizes sender_token: for recovery
# ---------------------------------------------------------------------------

class TestAnnotationRecognizesSenderToken:
    """Recovery annotation must fire for sender_token:-prefixed request messages."""

    def test_sender_token_request_annotated_for_recovery(self):
        from routers.mesh_dm import _annotate_request_recovery_message, _REQUEST_V2_REDUCED_VERSION

        message = {
            "delivery_class": "request",
            "sender_id": "sender_token:tok_abc",
            "sender_seal": "v3:some-seal-data",
            "msg_id": "msg-annotate-1",
        }
        annotated = _annotate_request_recovery_message(message)
        assert annotated["sender_recovery_required"] is True
        assert annotated["request_contract_version"] == _REQUEST_V2_REDUCED_VERSION
        assert annotated["sender_recovery_state"] == "pending"

    def test_sealed_prefix_still_annotated_for_recovery(self):
        """Existing sealed: annotation must not regress."""
        from routers.mesh_dm import _annotate_request_recovery_message, _REQUEST_V2_REDUCED_VERSION

        message = {
            "delivery_class": "request",
            "sender_id": "sealed:hmac_val",
            "sender_seal": "v3:some-seal-data",
        }
        annotated = _annotate_request_recovery_message(message)
        assert annotated["sender_recovery_required"] is True
        assert annotated["request_contract_version"] == _REQUEST_V2_REDUCED_VERSION

    def test_raw_sender_not_annotated_for_recovery(self):
        """Raw sender_id should NOT trigger recovery annotation."""
        from routers.mesh_dm import _annotate_request_recovery_message

        message = {
            "delivery_class": "request",
            "sender_id": "alice",
            "sender_seal": "v3:some-seal-data",
        }
        annotated = _annotate_request_recovery_message(message)
        assert "sender_recovery_required" not in annotated or annotated.get("sender_recovery_required") is not True

    def test_shared_delivery_not_annotated(self):
        """Shared delivery messages should never get recovery annotation."""
        from routers.mesh_dm import _annotate_request_recovery_message

        message = {
            "delivery_class": "shared",
            "sender_id": "sender_token:tok_shared",
            "sender_seal": "v3:some-seal-data",
        }
        annotated = _annotate_request_recovery_message(message)
        assert "sender_recovery_required" not in annotated or annotated.get("sender_recovery_required") is not True


# ---------------------------------------------------------------------------
# 6. Duplicate authority ranking treats sender_token: as blinded
# ---------------------------------------------------------------------------

class TestDuplicateAuthorityRanking:
    """sender_token: prefix should rank the same as sealed: (rank 1)."""

    def test_sender_token_prefix_ranks_as_blinded(self):
        from routers.mesh_dm import _request_duplicate_authority_rank

        msg = {"delivery_class": "request", "sender_id": "sender_token:tok_abc"}
        assert _request_duplicate_authority_rank(msg) == 1

    def test_sealed_prefix_still_ranks_as_blinded(self):
        from routers.mesh_dm import _request_duplicate_authority_rank

        msg = {"delivery_class": "request", "sender_id": "sealed:hmac_val"}
        assert _request_duplicate_authority_rank(msg) == 1

    def test_raw_sender_ranks_higher(self):
        from routers.mesh_dm import _request_duplicate_authority_rank

        msg = {"delivery_class": "request", "sender_id": "alice"}
        assert _request_duplicate_authority_rank(msg) == 2
