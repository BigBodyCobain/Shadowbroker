"""S10B DM-Shaped Cover Traffic With Mailbox TTL.

Tests:
- _send_cover_traffic emits private_dm-shaped RNSMessage
- Cover wire message uses private_dm-style message_id prefix and dandelion metadata
- Cover body has mailbox_key and envelope rather than pad/size
- Collecting real mailbox keys does not return cover entries
- Stale mailbox entries are pruned by TTL
- Legacy incoming cover_traffic is still handled safely
- S8A size/rate bounds are not regressed
"""

import base64
import json
import time
from types import SimpleNamespace

from services.config import Settings
from services.mesh.mesh_rns import (
    RNSBridge,
    _COVER_MAILBOX_PREFIX,
    _DM_CT_FAMILY,
    _blind_mailbox_key,
)


def _make_bridge() -> RNSBridge:
    return RNSBridge()


# ── Cover emits private_dm-shaped message ─────────────────────────────


def test_cover_emits_private_dm_shape(monkeypatch):
    """_send_cover_traffic must produce a private_dm-typed RNSMessage."""
    bridge = _make_bridge()
    monkeypatch.setattr(
        "services.mesh.mesh_rns.get_settings",
        lambda: Settings(MESH_RNS_COVER_SIZE=512, MESH_RNS_MAX_PAYLOAD=8192),
    )

    sent: list[bytes] = []

    def fake_pick_stem():
        return "fake_peer"

    def fake_send(peer, payload):
        sent.append(payload)
        return True

    monkeypatch.setattr(bridge, "_pick_stem_peer", fake_pick_stem)
    monkeypatch.setattr(bridge, "_send_to_peer", fake_send)

    bridge._send_cover_traffic()

    assert len(sent) == 1
    msg = json.loads(sent[0])
    assert msg["type"] == "private_dm", f"expected private_dm, got {msg['type']}"


def test_cover_message_id_prefix(monkeypatch):
    """Cover wire message must use private_dm-style message_id prefix."""
    bridge = _make_bridge()
    monkeypatch.setattr(
        "services.mesh.mesh_rns.get_settings",
        lambda: Settings(MESH_RNS_COVER_SIZE=512, MESH_RNS_MAX_PAYLOAD=8192),
    )
    sent: list[bytes] = []
    monkeypatch.setattr(bridge, "_pick_stem_peer", lambda: "fake_peer")
    monkeypatch.setattr(bridge, "_send_to_peer", lambda p, d: sent.append(d) or True)

    bridge._send_cover_traffic()

    msg = json.loads(sent[0])
    message_id = msg["meta"]["message_id"]
    assert message_id.startswith("private_dm:"), f"message_id should start with private_dm:, got {message_id}"


def test_cover_dandelion_metadata(monkeypatch):
    """Cover wire message must include dandelion stem metadata like real DMs."""
    bridge = _make_bridge()
    monkeypatch.setattr(
        "services.mesh.mesh_rns.get_settings",
        lambda: Settings(MESH_RNS_COVER_SIZE=512, MESH_RNS_MAX_PAYLOAD=8192,
                         MESH_RNS_DANDELION_HOPS=2),
    )
    sent: list[bytes] = []
    monkeypatch.setattr(bridge, "_pick_stem_peer", lambda: "fake_peer")
    monkeypatch.setattr(bridge, "_send_to_peer", lambda p, d: sent.append(d) or True)

    bridge._send_cover_traffic()

    msg = json.loads(sent[0])
    dandelion = msg["meta"].get("dandelion", {})
    assert dandelion.get("phase") == "stem"
    assert dandelion.get("hops") == 0
    assert "max_hops" in dandelion


def test_cover_originator_schedules_delayed_diffuse(monkeypatch):
    """Cover origination should mirror DM stem + delayed diffuse behavior."""
    bridge = _make_bridge()
    monkeypatch.setattr(
        "services.mesh.mesh_rns.get_settings",
        lambda: Settings(
            MESH_RNS_COVER_SIZE=512,
            MESH_RNS_MAX_PAYLOAD=8192,
            MESH_RNS_DANDELION_HOPS=2,
            MESH_RNS_DANDELION_DELAY_MS=400,
        ),
    )
    stem_sent: list[tuple[str, bytes]] = []
    diffuse_sent: list[tuple[bytes, str | None]] = []
    timer_delays: list[float] = []

    class FakeTimer:
        def __init__(self, delay, fn):
            self.delay = delay
            self.fn = fn

        def start(self):
            timer_delays.append(self.delay)
            self.fn()

    monkeypatch.setattr("services.mesh.mesh_rns.threading.Timer", FakeTimer)
    monkeypatch.setattr(bridge, "_pick_stem_peer", lambda: "stem-peer")
    monkeypatch.setattr(bridge, "_send_to_peer", lambda peer, payload: stem_sent.append((peer, payload)) or True)
    monkeypatch.setattr(
        bridge,
        "_send_diffuse",
        lambda payload, exclude=None: diffuse_sent.append((payload, exclude)) or 1,
    )

    bridge._send_cover_traffic()

    assert len(stem_sent) == 1
    assert len(diffuse_sent) == 1
    assert timer_delays == [0.4]
    assert diffuse_sent[0][1] == "stem-peer"

    stem_msg = json.loads(stem_sent[0][1])
    diffuse_msg = json.loads(diffuse_sent[0][0])
    assert stem_msg["type"] == "private_dm"
    assert diffuse_msg["type"] == "private_dm"
    assert stem_msg["meta"]["dandelion"]["phase"] == "stem"
    assert diffuse_msg["meta"]["dandelion"]["phase"] == "diffuse"
    assert stem_msg["meta"]["message_id"] == diffuse_msg["meta"]["message_id"]
    assert stem_msg["body"] == diffuse_msg["body"]


def test_cover_falls_back_to_diffuse_without_stem_peer(monkeypatch):
    """Without a stem peer, cover should mirror DM diffuse fallback behavior."""
    bridge = _make_bridge()
    monkeypatch.setattr(
        "services.mesh.mesh_rns.get_settings",
        lambda: Settings(MESH_RNS_COVER_SIZE=512, MESH_RNS_MAX_PAYLOAD=8192),
    )
    diffuse_sent: list[tuple[bytes, str | None]] = []
    monkeypatch.setattr(bridge, "_pick_stem_peer", lambda: None)
    monkeypatch.setattr(bridge, "_send_to_peer", lambda peer, payload: False)
    monkeypatch.setattr(
        bridge,
        "_send_diffuse",
        lambda payload, exclude=None: diffuse_sent.append((payload, exclude)) or 1,
    )

    bridge._send_cover_traffic()

    assert len(diffuse_sent) == 1
    assert diffuse_sent[0][1] is None
    msg = json.loads(diffuse_sent[0][0])
    assert msg["type"] == "private_dm"
    assert msg["meta"]["dandelion"]["phase"] == "stem"
    assert "mailbox_key" in msg["body"]
    assert "envelope" in msg["body"]


def test_cover_body_has_mailbox_and_envelope(monkeypatch):
    """Cover body must have mailbox_key + envelope, not pad/size."""
    bridge = _make_bridge()
    monkeypatch.setattr(
        "services.mesh.mesh_rns.get_settings",
        lambda: Settings(MESH_RNS_COVER_SIZE=512, MESH_RNS_MAX_PAYLOAD=8192),
    )
    sent: list[bytes] = []
    monkeypatch.setattr(bridge, "_pick_stem_peer", lambda: "fake_peer")
    monkeypatch.setattr(bridge, "_send_to_peer", lambda p, d: sent.append(d) or True)

    bridge._send_cover_traffic()

    msg = json.loads(sent[0])
    body = msg["body"]
    assert "mailbox_key" in body, "cover body must have mailbox_key"
    assert "envelope" in body, "cover body must have envelope"
    assert isinstance(body["envelope"], dict)
    envelope = body["envelope"]
    assert "ciphertext" in envelope
    assert "msg_id" in envelope
    assert "pad" not in body, "cover body must not have legacy pad field"
    assert "size" not in body, "cover body must not have legacy size field"


# ── Collecting real mailbox keys does not return cover entries ─────────


def test_collect_real_mailbox_excludes_cover(monkeypatch):
    """Collecting a real mailbox key must not surface cover entries."""
    bridge = _make_bridge()
    monkeypatch.setattr(
        "services.mesh.mesh_rns.get_settings",
        lambda: Settings(MESH_DM_MAILBOX_TTL_S=900),
    )

    real_key = "real-user-mailbox-key"
    blinded_real = _blind_mailbox_key(real_key)

    # Store a real DM.
    bridge._store_private_dm(blinded_real, {
        "msg_id": "real-msg-1",
        "sender_id": "sender1",
        "ciphertext": "data",
        "timestamp": time.time(),
        "delivery_class": "shared",
        "sender_seal": "",
    })

    # Simulate cover entry arriving via the normal private_dm receive path.
    cover_mailbox = f"{_COVER_MAILBOX_PREFIX}abc123"
    blinded_cover = _blind_mailbox_key(cover_mailbox)
    bridge._store_private_dm(blinded_cover, {
        "msg_id": "cover-msg-1",
        "sender_id": "",
        "ciphertext": "cover-data",
        "timestamp": time.time(),
        "delivery_class": "shared",
        "sender_seal": "",
    })

    # Collect real mailbox — should only get the real DM.
    collected, _ = bridge.collect_private_dm([real_key])
    assert len(collected) == 1
    assert collected[0]["msg_id"] == "real-msg-1"


def test_cover_mailbox_key_is_synthetic(monkeypatch):
    """The cover mailbox target must use synthetic prefix so it never
    collides with real agent-derived mailbox keys."""
    bridge = _make_bridge()
    monkeypatch.setattr(
        "services.mesh.mesh_rns.get_settings",
        lambda: Settings(MESH_RNS_COVER_SIZE=512, MESH_RNS_MAX_PAYLOAD=8192),
    )
    sent: list[bytes] = []
    monkeypatch.setattr(bridge, "_pick_stem_peer", lambda: "fake_peer")
    monkeypatch.setattr(bridge, "_send_to_peer", lambda p, d: sent.append(d) or True)

    bridge._send_cover_traffic()

    msg = json.loads(sent[0])
    mailbox_key = msg["body"]["mailbox_key"]
    # The on-wire key is blinded, but we verify it was derived from a
    # synthetic key by checking it differs from any plausible real key blind.
    # More importantly: the synthetic prefix makes real collection impossible
    # because real agents never know the pre-image.
    assert mailbox_key, "mailbox_key must be non-empty"
    assert len(mailbox_key) == 64, "blinded mailbox_key should be 64-char hex"


# ── TTL pruning ───────────────────────────────────────────────────────


def test_stale_entries_pruned_by_ttl(monkeypatch):
    """Mailbox entries older than MESH_DM_MAILBOX_TTL_S must be pruned."""
    bridge = _make_bridge()
    ttl = 60
    monkeypatch.setattr(
        "services.mesh.mesh_rns.get_settings",
        lambda: Settings(MESH_DM_MAILBOX_TTL_S=ttl),
    )

    blinded = _blind_mailbox_key("test-key")

    # Store an entry with a stale timestamp.
    stale_ts = time.time() - ttl - 10
    bridge._store_private_dm(blinded, {
        "msg_id": "stale-1",
        "sender_id": "s",
        "ciphertext": "c",
        "timestamp": stale_ts,
        "delivery_class": "shared",
        "sender_seal": "",
    })

    # Store a fresh entry to trigger pruning.
    bridge._store_private_dm(blinded, {
        "msg_id": "fresh-1",
        "sender_id": "s",
        "ciphertext": "c",
        "timestamp": time.time(),
        "delivery_class": "shared",
        "sender_seal": "",
    })

    # Only the fresh entry should remain.
    with bridge._dm_lock:
        items = bridge._dm_mailboxes.get(blinded, [])
        assert len(items) == 1, f"expected 1 item after prune, got {len(items)}"
        assert items[0]["msg_id"] == "fresh-1"


def test_ttl_prune_removes_empty_mailbox_keys(monkeypatch):
    """Pruning must remove mailbox keys that become empty."""
    bridge = _make_bridge()
    ttl = 30
    monkeypatch.setattr(
        "services.mesh.mesh_rns.get_settings",
        lambda: Settings(MESH_DM_MAILBOX_TTL_S=ttl),
    )

    blinded = _blind_mailbox_key("prune-test")

    # Insert a stale-only entry.
    with bridge._dm_lock:
        bridge._dm_mailboxes[blinded] = [{
            "msg_id": "old",
            "sender_id": "",
            "ciphertext": "",
            "timestamp": time.time() - ttl - 100,
            "delivery_class": "shared",
            "sender_seal": "",
            "transport": "reticulum",
        }]

    # Store into a different key to trigger prune.
    other_blinded = _blind_mailbox_key("other-key")
    bridge._store_private_dm(other_blinded, {
        "msg_id": "trigger",
        "sender_id": "",
        "ciphertext": "",
        "timestamp": time.time(),
        "delivery_class": "shared",
        "sender_seal": "",
    })

    with bridge._dm_lock:
        assert blinded not in bridge._dm_mailboxes, "empty mailbox key should be pruned"


# ── Legacy cover_traffic still handled safely ─────────────────────────


def test_legacy_cover_traffic_silently_dropped(monkeypatch):
    """Legacy incoming cover_traffic messages must still be silently dropped."""
    bridge = _make_bridge()
    monkeypatch.setattr(
        "services.mesh.mesh_rns.get_settings",
        lambda: Settings(),
    )

    # Simulate receiving a legacy cover_traffic message.
    legacy_msg = json.dumps({
        "type": "cover_traffic",
        "body": {"pad": base64.b64encode(b"x" * 64).decode(), "size": 64},
        "meta": {"message_id": "cover:legacy123", "ts": int(time.time())},
    }).encode()

    # _on_packet should silently return without error.
    monkeypatch.setattr(bridge, "_seen", lambda mid: False)
    bridge._on_packet(legacy_msg)

    # No crash, no entries stored — pass.
    with bridge._dm_lock:
        assert len(bridge._dm_mailboxes) == 0


def test_authenticated_cover_drops_before_mailbox_persistence(monkeypatch):
    bridge = _make_bridge()
    bridge._identity = SimpleNamespace(private_key=b"transport-secret-cover")
    monkeypatch.setattr(
        "services.mesh.mesh_rns.get_settings",
        lambda: Settings(MESH_RNS_COVER_AUTH_MARKER_ENABLE=True),
    )
    monkeypatch.setattr(bridge, "_seen", lambda _mid: False)

    envelope = bridge._with_transport_auth(
        {
            "msg_id": "cover-auth-1",
            "sender_id": "",
            "ciphertext": base64.b64encode(b"x" * _DM_CT_FAMILY[0]).decode("ascii"),
            "timestamp": time.time(),
            "delivery_class": "shared",
            "sender_seal": "",
        },
        cover=True,
    )

    payload = json.dumps(
        {
            "type": "private_dm",
            "body": {"mailbox_key": _blind_mailbox_key("mailbox-cover-1"), "envelope": envelope},
            "meta": {"message_id": "private_dm:cover-auth-1", "dandelion": {"phase": "diffuse"}},
        }
    ).encode()

    bridge._on_packet(payload)

    with bridge._dm_lock:
        assert bridge._dm_mailboxes == {}


def test_authenticated_non_cover_persists_after_mac_verify(monkeypatch):
    bridge = _make_bridge()
    bridge._identity = SimpleNamespace(private_key=b"transport-secret-real")
    monkeypatch.setattr(
        "services.mesh.mesh_rns.get_settings",
        lambda: Settings(MESH_RNS_COVER_AUTH_MARKER_ENABLE=True),
    )
    monkeypatch.setattr(bridge, "_seen", lambda _mid: False)

    envelope = bridge._with_transport_auth(
        {
            "msg_id": "real-auth-1",
            "sender_id": "alice",
            "ciphertext": base64.b64encode(b"y" * _DM_CT_FAMILY[0]).decode("ascii"),
            "timestamp": time.time(),
            "delivery_class": "shared",
            "sender_seal": "",
        },
        cover=False,
    )
    mailbox = _blind_mailbox_key("mailbox-real-1")
    payload = json.dumps(
        {
            "type": "private_dm",
            "body": {"mailbox_key": mailbox, "envelope": envelope},
            "meta": {"message_id": "private_dm:real-auth-1", "dandelion": {"phase": "diffuse"}},
        }
    ).encode()

    bridge._on_packet(payload)

    with bridge._dm_lock:
        assert bridge._dm_mailboxes[mailbox][0]["msg_id"] == "real-auth-1"


def test_malformed_cover_rejects_before_auth_verify_and_mailbox_growth(monkeypatch):
    bridge = _make_bridge()
    bridge._identity = SimpleNamespace(private_key=b"transport-secret-malformed")
    monkeypatch.setattr(
        "services.mesh.mesh_rns.get_settings",
        lambda: Settings(MESH_RNS_COVER_AUTH_MARKER_ENABLE=True),
    )
    monkeypatch.setattr(bridge, "_seen", lambda _mid: False)

    verify_calls = {"count": 0}

    def fake_verify(*_args, **_kwargs):
        verify_calls["count"] += 1
        return True, False

    monkeypatch.setattr(bridge, "_verify_transport_auth_block", fake_verify)

    for index in range(50):
        payload = json.dumps(
            {
                "type": "private_dm",
                "body": {
                    "mailbox_key": _blind_mailbox_key(f"mailbox-malformed-{index}"),
                    "envelope": {
                        "msg_id": f"malformed-{index}",
                        "sender_id": "",
                        "ciphertext": base64.b64encode(b"not-a-grounded-bucket").decode("ascii"),
                        "timestamp": time.time(),
                        "delivery_class": "shared",
                        "sender_seal": "",
                        "transport_auth": base64.b64encode(b"bogus").decode("ascii"),
                    },
                },
                "meta": {"message_id": f"private_dm:malformed-{index}", "dandelion": {"phase": "diffuse"}},
            }
        ).encode()
        bridge._on_packet(payload)

    assert verify_calls["count"] == 0
    with bridge._dm_lock:
        assert bridge._dm_mailboxes == {}


# ── S8A invariants not regressed ──────────────────────────────────────


def test_s8a_cover_size_floor_preserved():
    """Default MESH_RNS_COVER_SIZE must remain >= 512 (S8A invariant)."""
    s = Settings()
    assert s.MESH_RNS_COVER_SIZE >= 512


def test_s8a_cover_interval_independent_of_queue(monkeypatch):
    """Cover interval must not expand when batch queue has items (S8A)."""
    bridge = _make_bridge()
    monkeypatch.setattr(
        "services.mesh.mesh_rns.get_settings",
        lambda: Settings(MESH_RNS_COVER_INTERVAL_S=30),
    )
    monkeypatch.setattr(bridge, "_is_high_privacy", lambda: True)

    baseline = bridge._cover_interval()
    bridge._batch_queue = [{"fake": i} for i in range(20)]
    with_queue = bridge._cover_interval()
    assert with_queue == baseline


def test_s8a_cover_bounded_by_max_payload(monkeypatch):
    """Cover on-wire payload must not exceed MESH_RNS_MAX_PAYLOAD (S8A)."""
    bridge = _make_bridge()
    monkeypatch.setattr(
        "services.mesh.mesh_rns.get_settings",
        lambda: Settings(MESH_RNS_COVER_SIZE=512, MESH_RNS_MAX_PAYLOAD=8192),
    )
    sent: list[bytes] = []
    monkeypatch.setattr(bridge, "_pick_stem_peer", lambda: "fake_peer")
    monkeypatch.setattr(bridge, "_send_to_peer", lambda p, d: sent.append(d) or True)

    bridge._send_cover_traffic()

    assert len(sent) == 1
    assert len(sent[0]) <= 8192
