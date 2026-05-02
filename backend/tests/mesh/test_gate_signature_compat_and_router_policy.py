from __future__ import annotations

from services.mesh.mesh_router import MeshEnvelope, MeshRouter, PayloadType, Priority, TransportResult


def test_gate_legacy_signature_compat_is_disabled_by_default(monkeypatch):
    from services.mesh import mesh_signed_events

    observed_payloads: list[dict] = []

    def fake_verify_signed_event(**kwargs):
        payload = dict(kwargs.get("payload") or {})
        observed_payloads.append(payload)
        if "reply_to" not in payload:
            return True, "legacy_gate_reply_signature_compat"
        return False, "Invalid signature"

    monkeypatch.setattr(mesh_signed_events, "verify_signed_event", fake_verify_signed_event)
    monkeypatch.setattr(mesh_signed_events, "preflight_signed_event_integrity", lambda **_: (True, "ok"))
    monkeypatch.delenv("MESH_DEV_ALLOW_LEGACY_COMPAT", raising=False)
    monkeypatch.delenv("MESH_ALLOW_LEGACY_GATE_SIGNATURE_COMPAT_UNTIL", raising=False)

    ok, detail, effective_reply_to = mesh_signed_events.verify_gate_message_signed_write(
        node_id="!sb_test",
        sequence=7,
        public_key="pub",
        public_key_algo="Ed25519",
        signature="sig",
        payload={"gate": "infonet", "ciphertext": "Zm9v", "nonce": "n1", "epoch": 3},
        reply_to="evt-parent",
        protocol_version="infonet/2",
    )

    assert ok is False
    assert detail == "Invalid signature"
    assert effective_reply_to == "evt-parent"
    assert len(observed_payloads) == 1
    assert observed_payloads[0]["reply_to"] == "evt-parent"


def test_gate_legacy_signature_compat_requires_explicit_dev_override(monkeypatch):
    from services.mesh import mesh_signed_events

    def fake_verify_signed_event(**kwargs):
        payload = dict(kwargs.get("payload") or {})
        if "reply_to" not in payload:
            return True, "legacy_gate_reply_signature_compat"
        return False, "Invalid signature"

    monkeypatch.setattr(mesh_signed_events, "verify_signed_event", fake_verify_signed_event)
    monkeypatch.setattr(mesh_signed_events, "preflight_signed_event_integrity", lambda **_: (True, "ok"))
    monkeypatch.setenv("MESH_DEV_ALLOW_LEGACY_COMPAT", "true")
    monkeypatch.setenv("MESH_ALLOW_LEGACY_GATE_SIGNATURE_COMPAT_UNTIL", "2099-01-01")

    ok, detail, effective_reply_to = mesh_signed_events.verify_gate_message_signed_write(
        node_id="!sb_test",
        sequence=7,
        public_key="pub",
        public_key_algo="Ed25519",
        signature="sig",
        payload={"gate": "infonet", "ciphertext": "Zm9v", "nonce": "n1", "epoch": 3},
        reply_to="evt-parent",
        protocol_version="infonet/2",
    )

    assert ok is True
    assert detail == "legacy_gate_reply_signature_compat"
    assert effective_reply_to == ""


def test_private_emergency_route_skips_internet_transport(monkeypatch):
    from services.mesh import mesh_router as mesh_router_mod

    sent: list[str] = []

    class _Transport:
        def __init__(self, name: str):
            self.NAME = name

        def can_reach(self, envelope):
            return True

        def send(self, envelope, credentials):
            sent.append(self.NAME)
            return TransportResult(True, self.NAME, "sent")

    monkeypatch.setattr(mesh_router_mod, "_supervisor_verified_trust_tier", lambda: "private_transitional")

    router = MeshRouter()
    router.transports = [_Transport("tor_arti"), _Transport("internet")]

    envelope = MeshEnvelope(
        sender_id="!sb_sender",
        destination="peer-a",
        priority=Priority.EMERGENCY,
        payload_type=PayloadType.COMMAND,
        trust_tier="private_transitional",
        payload="secret",
    )

    results = router.route(envelope, {})

    assert [result.transport for result in results] == ["tor_arti"]
    assert sent == ["tor_arti"]
    assert envelope.routed_via == "tor_arti,"
