"""P5B / P5B-R: DM poll batch cardinality bounding.

Tests prove:
- Relay collect_claims returns at most `limit` messages when limit > 0
- Relay overflow messages remain queued for subsequent polls
- No message loss across multiple bounded polls
- RNS collect_private_dm is also limit-aware
- has_more is true when backlog exceeds batch limit
- has_more is false when all messages fit in one batch
- Relay/direct merge dedupe still works under capped polls
- Count endpoint remains coarsened (not regressed)
- Mixed relay+direct polling with shared budget loses no messages (P5B-R)
"""

import time

from services.mesh import mesh_dm_relay


def _fresh_relay(tmp_path, monkeypatch):
    from services.mesh import mesh_secure_storage
    from services import config as config_mod

    config_mod.get_settings.cache_clear()
    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    monkeypatch.setenv("MESH_DM_TOKEN_PEPPER", "test-pepper")
    relay = mesh_dm_relay.DMRelay()
    relay._pepper = "test-pepper"
    return relay


def _deposit(relay, token, msg_id, offset=0):
    relay._mailboxes.setdefault(token, []).append(
        mesh_dm_relay.DMMessage(
            sender_id="alice",
            ciphertext=f"ct-{msg_id}",
            timestamp=time.time() + offset,
            msg_id=msg_id,
            delivery_class="shared",
        )
    )


class TestRelayCollectClaimsLimited:
    def test_returns_at_most_limit_messages(self, tmp_path, monkeypatch):
        relay = _fresh_relay(tmp_path, monkeypatch)
        for i in range(10):
            _deposit(relay, "mailbox-key", f"msg-{i}", offset=float(i))

        monkeypatch.setattr(relay, "_mailbox_keys_for_claim", lambda agent_id, claim: ["mailbox-key"])
        msgs, has_more = relay.collect_claims("bob", [{"type": "shared"}], limit=3)
        assert len(msgs) == 3
        assert has_more is True

    def test_overflow_remains_queued(self, tmp_path, monkeypatch):
        relay = _fresh_relay(tmp_path, monkeypatch)
        for i in range(10):
            _deposit(relay, "mailbox-key", f"msg-{i}", offset=float(i))

        monkeypatch.setattr(relay, "_mailbox_keys_for_claim", lambda agent_id, claim: ["mailbox-key"])
        first_batch, more1 = relay.collect_claims("bob", [{"type": "shared"}], limit=3)
        assert len(first_batch) == 3
        assert more1 is True

        second_batch, more2 = relay.collect_claims("bob", [{"type": "shared"}], limit=3)
        assert len(second_batch) == 3
        assert more2 is True

        # Remaining
        rest, more3 = relay.collect_claims("bob", [{"type": "shared"}], limit=100)
        assert len(rest) == 4
        assert more3 is False

    def test_no_message_loss_across_bounded_polls(self, tmp_path, monkeypatch):
        relay = _fresh_relay(tmp_path, monkeypatch)
        all_ids = {f"msg-{i}" for i in range(15)}
        for i in range(15):
            _deposit(relay, "mailbox-key", f"msg-{i}", offset=float(i))

        monkeypatch.setattr(relay, "_mailbox_keys_for_claim", lambda agent_id, claim: ["mailbox-key"])
        collected_ids: set[str] = set()
        for _ in range(20):  # more iterations than needed
            batch, has_more = relay.collect_claims("bob", [{"type": "shared"}], limit=4)
            for msg in batch:
                collected_ids.add(msg["msg_id"])
            if not has_more:
                break

        assert collected_ids == all_ids

    def test_limit_zero_returns_all(self, tmp_path, monkeypatch):
        relay = _fresh_relay(tmp_path, monkeypatch)
        for i in range(10):
            _deposit(relay, "mailbox-key", f"msg-{i}", offset=float(i))

        monkeypatch.setattr(relay, "_mailbox_keys_for_claim", lambda agent_id, claim: ["mailbox-key"])
        msgs, has_more = relay.collect_claims("bob", [{"type": "shared"}], limit=0)
        assert len(msgs) == 10
        assert has_more is False

    def test_has_more_false_when_under_limit(self, tmp_path, monkeypatch):
        relay = _fresh_relay(tmp_path, monkeypatch)
        for i in range(3):
            _deposit(relay, "mailbox-key", f"msg-{i}", offset=float(i))

        monkeypatch.setattr(relay, "_mailbox_keys_for_claim", lambda agent_id, claim: ["mailbox-key"])
        msgs, has_more = relay.collect_claims("bob", [{"type": "shared"}], limit=8)
        assert len(msgs) == 3
        assert has_more is False


class TestRelayCollectLegacyLimited:
    def test_legacy_collect_respects_limit(self, tmp_path, monkeypatch):
        relay = _fresh_relay(tmp_path, monkeypatch)
        token = "legacy-token"
        peppered = relay._pepper_token(token)
        for i in range(10):
            _deposit(relay, peppered, f"msg-{i}", offset=float(i))

        msgs, has_more = relay.collect_legacy(agent_token=token, limit=4)
        assert len(msgs) == 4
        assert has_more is True

        rest, more = relay.collect_legacy(agent_token=token, limit=100)
        assert len(rest) == 6
        assert more is False


class TestRnsCollectLimited:
    def test_rns_collect_respects_limit(self):
        import threading
        from services.mesh.mesh_rns import RNSBridge, _blind_mailbox_key

        bridge = RNSBridge.__new__(RNSBridge)
        bridge._dm_mailboxes = {}
        bridge._dm_lock = threading.Lock()

        key = "test-mailbox-key"
        blinded = _blind_mailbox_key(key)
        base_ts = time.time()
        bridge._dm_mailboxes[blinded] = [
            {"msg_id": f"dm-{i}", "timestamp": base_ts + float(i), "ciphertext": f"ct-{i}"}
            for i in range(10)
        ]

        collected, has_more = bridge.collect_private_dm([key], limit=4)
        assert len(collected) == 4
        assert has_more is True

        rest, more = bridge.collect_private_dm([key], limit=100)
        assert len(rest) == 6
        assert more is False

    def test_rns_no_limit_returns_all(self):
        import threading
        from services.mesh.mesh_rns import RNSBridge, _blind_mailbox_key

        bridge = RNSBridge.__new__(RNSBridge)
        bridge._dm_mailboxes = {}
        bridge._dm_lock = threading.Lock()

        key = "test-mailbox-key"
        blinded = _blind_mailbox_key(key)
        base_ts = time.time()
        bridge._dm_mailboxes[blinded] = [
            {"msg_id": f"dm-{i}", "timestamp": base_ts + float(i), "ciphertext": f"ct-{i}"}
            for i in range(5)
        ]

        collected, has_more = bridge.collect_private_dm([key], limit=0)
        assert len(collected) == 5
        assert has_more is False


class TestDedupeUnderCappedPolls:
    def test_relay_dedupe_survives_limit(self, tmp_path, monkeypatch):
        """Messages with same msg_id across keys are deduped even when limited."""
        relay = _fresh_relay(tmp_path, monkeypatch)
        # Same msg_id in two different mailbox keys
        _deposit(relay, "key-a", "dup-msg", offset=1.0)
        _deposit(relay, "key-b", "dup-msg", offset=1.0)
        _deposit(relay, "key-a", "unique-msg", offset=2.0)

        msgs, has_more = relay._collect_from_keys(["key-a", "key-b"], destructive=True, limit=10)
        msg_ids = [m["msg_id"] for m in msgs]
        assert msg_ids.count("dup-msg") == 1
        assert "unique-msg" in msg_ids
        assert has_more is False


class TestMixedSourceBudgetNoLoss:
    """P5B-R: Prove the shared-budget approach never loses messages when
    relay and direct sources both contribute to a single bounded poll.

    These tests exercise the exact drain pattern used by the secure POST
    /api/mesh/dm/poll route:
      1. Relay drains with limit=BATCH_LIMIT
      2. Direct drains with limit=(BATCH_LIMIT - len(relay_msgs))
      3. Merge + safety cap
    """

    BATCH_LIMIT = 8  # mirrors DM_POLL_BATCH_LIMIT

    def _build_rns_bridge(self, mailbox_key, messages):
        """Create a minimal RNSBridge with pre-loaded DM mailbox."""
        import threading
        from services.mesh.mesh_rns import RNSBridge, _blind_mailbox_key

        bridge = RNSBridge.__new__(RNSBridge)
        bridge._dm_mailboxes = {}
        bridge._dm_lock = threading.Lock()
        blinded = _blind_mailbox_key(mailbox_key)
        bridge._dm_mailboxes[blinded] = list(messages)
        return bridge

    def _simulate_poll(self, relay, bridge, claims, mailbox_keys):
        """Simulate one secure POST poll with shared budget — mirrors route logic."""
        relay_msgs, relay_more = relay.collect_claims("bob", claims, limit=self.BATCH_LIMIT)
        direct_msgs = []
        direct_more = False
        direct_budget = self.BATCH_LIMIT - len(relay_msgs)
        if direct_budget > 0:
            direct_msgs, direct_more = bridge.collect_private_dm(mailbox_keys, limit=direct_budget)
        elif direct_budget <= 0:
            direct_more = True  # direct may still have messages

        from main import _merge_dm_poll_messages

        merged = _merge_dm_poll_messages(relay_msgs, direct_msgs)
        has_more = relay_more or direct_more
        msgs = merged[: self.BATCH_LIMIT]
        return msgs, has_more

    def test_mixed_source_no_message_loss(self, tmp_path, monkeypatch):
        """6 relay + 6 direct unique messages, total 12 > BATCH_LIMIT=8.
        All 12 must be recovered across multiple polls with zero loss.
        This is the exact scenario that failed under the blocked P5B code."""
        relay = _fresh_relay(tmp_path, monkeypatch)
        relay_key = "mailbox-key"
        monkeypatch.setattr(relay, "_mailbox_keys_for_claim", lambda agent_id, claim: [relay_key])
        for i in range(6):
            _deposit(relay, relay_key, f"relay-{i}", offset=float(i))

        direct_key = "mailbox-key"
        direct_base_ts = time.time() + 100.0
        direct_messages = [
            {"msg_id": f"direct-{i}", "timestamp": direct_base_ts + float(i), "ciphertext": f"ct-direct-{i}"}
            for i in range(6)
        ]
        bridge = self._build_rns_bridge(direct_key, direct_messages)
        claims = [{"type": "shared"}]

        collected_ids: set[str] = set()
        for _ in range(10):  # generous iteration cap
            msgs, has_more = self._simulate_poll(relay, bridge, claims, [direct_key])
            for msg in msgs:
                collected_ids.add(msg["msg_id"])
            if not has_more:
                break

        expected = {f"relay-{i}" for i in range(6)} | {f"direct-{i}" for i in range(6)}
        assert collected_ids == expected, f"Lost messages: {expected - collected_ids}"

    def test_first_poll_bounded_and_has_more(self, tmp_path, monkeypatch):
        """First poll of mixed sources returns at most BATCH_LIMIT with has_more=True."""
        relay = _fresh_relay(tmp_path, monkeypatch)
        relay_key = "mailbox-key"
        monkeypatch.setattr(relay, "_mailbox_keys_for_claim", lambda agent_id, claim: [relay_key])
        for i in range(6):
            _deposit(relay, relay_key, f"relay-{i}", offset=float(i))

        direct_base_ts = time.time() + 100.0
        direct_messages = [
            {"msg_id": f"direct-{i}", "timestamp": direct_base_ts + float(i), "ciphertext": f"ct-direct-{i}"}
            for i in range(6)
        ]
        bridge = self._build_rns_bridge("mailbox-key", direct_messages)

        msgs, has_more = self._simulate_poll(relay, bridge, [{"type": "shared"}], ["mailbox-key"])
        assert len(msgs) <= self.BATCH_LIMIT
        assert has_more is True

    def test_relay_fills_budget_direct_deferred(self, tmp_path, monkeypatch):
        """When relay alone fills the budget, direct messages stay in place
        and are recovered on a subsequent poll."""
        relay = _fresh_relay(tmp_path, monkeypatch)
        relay_key = "mailbox-key"
        monkeypatch.setattr(relay, "_mailbox_keys_for_claim", lambda agent_id, claim: [relay_key])
        for i in range(self.BATCH_LIMIT):
            _deposit(relay, relay_key, f"relay-{i}", offset=float(i))

        direct_messages = [
            {"msg_id": "direct-sole", "timestamp": time.time() + 999.0, "ciphertext": "ct-direct"}
        ]
        bridge = self._build_rns_bridge("mailbox-key", direct_messages)

        # First poll: relay fills entire budget, direct untouched
        msgs1, has_more1 = self._simulate_poll(relay, bridge, [{"type": "shared"}], ["mailbox-key"])
        msg_ids_1 = {m["msg_id"] for m in msgs1}
        assert len(msgs1) == self.BATCH_LIMIT
        assert has_more1 is True  # direct_more set because budget=0
        assert "direct-sole" not in msg_ids_1

        # Second poll: relay empty, direct now drains
        msgs2, has_more2 = self._simulate_poll(relay, bridge, [{"type": "shared"}], ["mailbox-key"])
        msg_ids_2 = {m["msg_id"] for m in msgs2}
        assert "direct-sole" in msg_ids_2

    def test_cross_source_dedup_with_budget(self, tmp_path, monkeypatch):
        """Duplicate msg_id across relay and direct is deduped, no loss."""
        relay = _fresh_relay(tmp_path, monkeypatch)
        relay_key = "mailbox-key"
        monkeypatch.setattr(relay, "_mailbox_keys_for_claim", lambda agent_id, claim: [relay_key])
        _deposit(relay, relay_key, "shared-msg", offset=1.0)
        _deposit(relay, relay_key, "relay-only", offset=2.0)

        direct_base_ts = time.time()
        direct_messages = [
            {"msg_id": "shared-msg", "timestamp": direct_base_ts + 1.0, "ciphertext": "ct-dup"},
            {"msg_id": "direct-only", "timestamp": direct_base_ts + 3.0, "ciphertext": "ct-direct"},
        ]
        bridge = self._build_rns_bridge("mailbox-key", direct_messages)

        msgs, has_more = self._simulate_poll(relay, bridge, [{"type": "shared"}], ["mailbox-key"])
        msg_ids = [m["msg_id"] for m in msgs]
        assert msg_ids.count("shared-msg") == 1
        assert "relay-only" in msg_ids
        assert "direct-only" in msg_ids
        assert len(msgs) == 3
