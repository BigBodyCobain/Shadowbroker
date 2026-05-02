import hashlib
import json
import threading


def test_rns_gate_publish_preserves_durable_envelope_fields(monkeypatch):
    from services.mesh import mesh_hashchain
    from services.mesh.mesh_rns import RNSBridge

    bridge = RNSBridge.__new__(RNSBridge)
    bridge._enabled = True
    bridge._ready = True
    bridge._dedupe = {}
    bridge._dedupe_lock = threading.Lock()

    sent: list[bytes] = []
    peer_urls: list[str] = []

    monkeypatch.setattr(bridge, "enabled", lambda: True)
    monkeypatch.setattr(bridge, "_maybe_rotate_session", lambda: None)
    monkeypatch.setattr(bridge, "_seen", lambda _message_id: False)
    monkeypatch.setattr(bridge, "_make_message_id", lambda prefix: f"{prefix}:test")
    monkeypatch.setattr(bridge, "_local_hash", lambda: "abcd1234")
    monkeypatch.setattr(bridge, "_dandelion_hops", lambda: 0)
    monkeypatch.setattr(bridge, "_pick_stem_peer", lambda: None)
    monkeypatch.setattr(bridge, "_send_diffuse", lambda payload, exclude=None: sent.append(payload) or 1)
    monkeypatch.setattr(
        mesh_hashchain,
        "build_gate_wire_ref",
        lambda gate_id, event, peer_url="": peer_urls.append(peer_url) or "gate-ref-test",
    )

    gate_envelope = "durable-envelope-token"
    event = {
        "event_id": "a" * 64,
        "event_type": "gate_message",
        "timestamp": 1710000000.0,
        "node_id": "!sb_sender",
        "sequence": 7,
        "signature": "b" * 128,
        "public_key": "pub",
        "public_key_algo": "ed25519",
        "protocol_version": "infonet/2",
        "payload": {
            "gate": "general-talk",
            "ciphertext": "mls-ciphertext",
            "nonce": "mls-nonce",
            "sender_ref": "sender-ref",
            "format": "mls1",
            "epoch": 3,
            "gate_envelope": gate_envelope,
            "envelope_hash": hashlib.sha256(gate_envelope.encode("ascii")).hexdigest(),
            "reply_to": "parent-event",
            "transport_lock": "private_strong",
        },
    }

    bridge.publish_gate_event("general-talk", event)

    assert sent, "RNS gate publish should emit a gate_event payload"
    wire = json.loads(sent[0].decode("utf-8"))
    payload = wire["body"]["event"]["payload"]
    assert wire["meta"]["reply_to"] == "abcd1234"
    assert payload["ciphertext"] == "mls-ciphertext"
    assert payload["gate_envelope"] == gate_envelope
    assert payload["envelope_hash"] == hashlib.sha256(gate_envelope.encode("ascii")).hexdigest()
    assert payload["reply_to"] == "parent-event"
    assert payload["transport_lock"] == "private_strong"
    assert payload["gate_ref"] == "gate-ref-test"
    assert peer_urls == ["rns://abcd1234"]
    assert "gate" not in payload


def test_private_gate_sanitizer_preserves_distribution_fields():
    from services.mesh.mesh_hashchain import _private_gate_signature_payload, _sanitize_private_gate_event

    event = {
        "event_id": "c" * 64,
        "event_type": "gate_message",
        "timestamp": 1710000000.0,
        "node_id": "!sb_sender",
        "sequence": 9,
        "signature": "d" * 128,
        "public_key": "pub",
        "public_key_algo": "ed25519",
        "protocol_version": "infonet/2",
        "payload": {
            "gate": "general-talk",
            "ciphertext": "mls-ciphertext",
            "nonce": "mls-nonce",
            "sender_ref": "sender-ref",
            "format": "mls1",
            "epoch": 4,
            "envelope_hash": "e" * 64,
            "gate_envelope": "durable-envelope-token",
            "reply_to": "parent-event",
            "transport_lock": "private_strong",
        },
    }

    sanitized = _sanitize_private_gate_event("general-talk", event)
    payload = sanitized["payload"]
    assert payload["gate_envelope"] == "durable-envelope-token"
    assert payload["envelope_hash"] == "e" * 64
    assert payload["reply_to"] == "parent-event"
    assert payload["transport_lock"] == "private_strong"

    signed_payload = _private_gate_signature_payload("general-talk", event)
    assert signed_payload["envelope_hash"] == "e" * 64
    assert signed_payload["reply_to"] == "parent-event"
    assert signed_payload["transport_lock"] == "private_strong"


def test_high_privacy_rns_gate_publish_batches_before_fallback_send(monkeypatch):
    from types import SimpleNamespace

    from services.mesh import mesh_hashchain, mesh_rns
    from services.mesh.mesh_rns import RNSBridge

    bridge = RNSBridge()
    sent: list[bytes] = []
    timers: list[object] = []

    class FakeTimer:
        def __init__(self, delay, fn):
            self.delay = delay
            self.fn = fn
            self.daemon = False
            self.cancelled = False

        def start(self):
            timers.append(self)

        def cancel(self):
            self.cancelled = True

    settings = SimpleNamespace(
        MESH_PEER_PUSH_SECRET="peer-secret",
        MESH_RNS_MAX_PAYLOAD=8192,
        MESH_RNS_DANDELION_DELAY_MS=0,
        MESH_RNS_BATCH_MS=250,
    )
    monkeypatch.setattr(mesh_rns, "get_settings", lambda: settings)
    monkeypatch.setattr(mesh_rns.threading, "Timer", FakeTimer)
    monkeypatch.setattr(mesh_hashchain, "build_gate_wire_ref", lambda gate_id, event, peer_url="": "gate-ref-test")
    monkeypatch.setattr(bridge, "enabled", lambda: True)
    monkeypatch.setattr(bridge, "_is_high_privacy", lambda: True)
    monkeypatch.setattr(bridge, "_maybe_rotate_session", lambda: None)
    monkeypatch.setattr(bridge, "_seen", lambda _message_id: False)
    monkeypatch.setattr(bridge, "_make_message_id", lambda prefix: f"{prefix}:test")
    monkeypatch.setattr(bridge, "_local_hash", lambda: "abcd1234")
    monkeypatch.setattr(bridge, "_dandelion_hops", lambda: 0)
    monkeypatch.setattr(bridge, "_pick_stem_peer", lambda: None)
    monkeypatch.setattr(bridge, "_send_diffuse", lambda payload, exclude=None: sent.append(payload) or 1)

    event = {
        "event_id": "b" * 64,
        "event_type": "gate_message",
        "timestamp": 1710000000.0,
        "node_id": "!sb_sender",
        "sequence": 8,
        "signature": "c" * 128,
        "public_key": "pub",
        "public_key_algo": "ed25519",
        "protocol_version": "infonet/2",
        "payload": {
            "gate": "general-talk",
            "ciphertext": "mls-ciphertext",
            "nonce": "mls-nonce",
            "sender_ref": "sender-ref",
            "format": "mls1",
            "transport_lock": "private_strong",
        },
    }

    bridge.publish_gate_event("general-talk", event)

    assert sent == []
    assert len(timers) == 1
    assert timers[0].delay == 0.25
    timers[0].fn()

    assert len(sent) == 1
    wire = json.loads(sent[0].decode("utf-8"))
    assert wire["type"] == "gate_event"
    assert wire["meta"]["reply_to"] == "abcd1234"
    assert wire["body"]["event"]["payload"]["gate_ref"] == "gate-ref-test"
