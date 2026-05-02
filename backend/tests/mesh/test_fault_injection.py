"""Fault-injection corpus — Sprint 5 validation.

Replays corrupted, downgraded, tier-spoofed, and replayed messages against
the schema registry, hashchain, MLS bridge, and router. Every category
must be cleanly rejected. Runs on every PR via CI.
"""

import base64
import hashlib
import json
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_vectors() -> dict:
    with open(FIXTURES / "fault_injection_vectors.json") as f:
        return json.load(f)


# ── Corruption vectors ───────────────────────────────────────────────────────

class TestCiphertextCorruption:
    """MLS ciphertext mutations must fail cleanly without panic."""

    def _fresh_gate_state(self, tmp_path, monkeypatch):
        from services import wormhole_supervisor
        from services.mesh import mesh_gate_mls, mesh_reputation, mesh_secure_storage, mesh_wormhole_persona

        monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
        monkeypatch.setattr(mesh_gate_mls, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mesh_gate_mls, "STATE_FILE", tmp_path / "wormhole_gate_mls.json")
        monkeypatch.setattr(mesh_wormhole_persona, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mesh_wormhole_persona, "PERSONA_FILE", tmp_path / "wormhole_persona.json")
        monkeypatch.setattr(
            mesh_wormhole_persona, "LEGACY_DM_IDENTITY_FILE",
            tmp_path / "wormhole_identity.json",
        )
        monkeypatch.setattr(wormhole_supervisor, "get_transport_tier", lambda: "private_transitional")
        monkeypatch.setattr(
            wormhole_supervisor, "get_wormhole_state",
            lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": False},
        )

        class _Mgr:
            def get_gate_secret(self, _gate_id): return "test-secret"
            def get_envelope_policy(self, _gate_id): return "envelope_recovery"
            def can_enter(self, _sender_id, _gate_id): return True, "ok"
            def record_message(self, _gate_id): pass

        monkeypatch.setattr(mesh_reputation, "gate_manager", _Mgr(), raising=False)
        mesh_gate_mls.reset_gate_mls_state()
        return mesh_gate_mls, mesh_wormhole_persona

    def _compose_valid(self, gate_mls, persona, gate_id="finance"):
        persona.bootstrap_wormhole_persona_state(force=True)
        persona.create_gate_persona(gate_id, label="fuzz_sender")
        composed = gate_mls.compose_encrypted_gate_message(gate_id, "valid plaintext for fuzzing")
        assert composed["ok"] is True
        return composed

    def test_bit_flipped_ciphertext_fails_cleanly(self, tmp_path, monkeypatch):
        gate_mls, persona = self._fresh_gate_state(tmp_path, monkeypatch)
        composed = self._compose_valid(gate_mls, persona)

        raw = base64.b64decode(composed["ciphertext"])
        corrupted = bytes([raw[0] ^ 0xFF]) + raw[1:]
        corrupted_b64 = base64.b64encode(corrupted).decode()

        result = gate_mls.decrypt_gate_message_for_local_identity(
            gate_id="finance",
            epoch=int(composed["epoch"]),
            ciphertext=corrupted_b64,
            nonce=str(composed["nonce"]),
            sender_ref=str(composed["sender_ref"]),
        )
        assert result.get("ok") is not True

    def test_truncated_ciphertext_fails_cleanly(self, tmp_path, monkeypatch):
        gate_mls, persona = self._fresh_gate_state(tmp_path, monkeypatch)
        composed = self._compose_valid(gate_mls, persona)

        raw = base64.b64decode(composed["ciphertext"])
        truncated = base64.b64encode(raw[:16]).decode()

        result = gate_mls.decrypt_gate_message_for_local_identity(
            gate_id="finance",
            epoch=int(composed["epoch"]),
            ciphertext=truncated,
            nonce=str(composed["nonce"]),
            sender_ref=str(composed["sender_ref"]),
        )
        assert result.get("ok") is not True

    def test_empty_ciphertext_rejected_by_schema(self):
        from services.mesh.mesh_protocol import normalize_payload
        from services.mesh.mesh_schema import validate_event_payload

        payload = normalize_payload("gate_message", {
            "gate": "finance", "ciphertext": "", "nonce": "abc",
            "sender_ref": "ref1", "epoch": 1,
        })
        ok, reason = validate_event_payload("gate_message", payload)
        assert ok is False
        assert "ciphertext" in reason.lower()


# ── Downgrade vectors ────────────────────────────────────────────────────────

class TestFormatDowngrade:
    """Format downgrade attempts must be rejected."""

    def test_gate_legacy_format_rejected(self):
        from services.mesh.mesh_protocol import normalize_payload
        from services.mesh.mesh_schema import validate_event_payload

        payload = normalize_payload("gate_message", {
            "gate": "finance", "ciphertext": "ZmFrZQ==", "nonce": "abc",
            "sender_ref": "ref1", "epoch": 1, "format": "legacy_cleartext",
        })
        ok, reason = validate_event_payload("gate_message", payload)
        assert ok is False
        assert "format" in reason.lower()

    def test_gate_dm1_format_rejected(self):
        from services.mesh.mesh_protocol import normalize_payload
        from services.mesh.mesh_schema import validate_event_payload

        payload = normalize_payload("gate_message", {
            "gate": "finance", "ciphertext": "ZmFrZQ==", "nonce": "abc",
            "sender_ref": "ref1", "epoch": 1, "format": "dm1",
        })
        ok, reason = validate_event_payload("gate_message", payload)
        assert ok is False

    def test_dm_plaintext_format_rejected(self):
        from services.mesh.mesh_protocol import normalize_payload
        from services.mesh.mesh_schema import validate_event_payload

        payload = normalize_payload("dm_message", {
            "recipient_id": "!sb_abc123", "delivery_class": "shared",
            "recipient_token": "tok1", "ciphertext": "ZmFrZQ==",
            "msg_id": "m1", "timestamp": 1710000000, "format": "plaintext",
        })
        ok, reason = validate_event_payload("dm_message", payload)
        assert ok is False
        assert "format" in reason.lower()


# ── Tier spoofing vectors ────────────────────────────────────────────────────

class TestTierSpoofing:
    """Envelopes claiming a higher tier than the supervisor can deliver must be clamped."""

    def test_private_strong_clamped_to_public_degraded(self, monkeypatch):
        from services.mesh import mesh_router
        monkeypatch.setattr(
            mesh_router, "_supervisor_verified_trust_tier",
            lambda: "public_degraded",
        )

        envelope = mesh_router.MeshEnvelope(
            sender_id="!sb_test1234",
            destination="broadcast",
            payload="test payload",
            trust_tier="private_strong",
        )
        assert envelope.trust_tier == "public_degraded"

    def test_private_strong_clamped_to_transitional(self, monkeypatch):
        from services.mesh import mesh_router
        monkeypatch.setattr(
            mesh_router, "_supervisor_verified_trust_tier",
            lambda: "private_transitional",
        )

        envelope = mesh_router.MeshEnvelope(
            sender_id="!sb_test1234",
            destination="broadcast",
            payload="test payload",
            trust_tier="private_strong",
        )
        assert envelope.trust_tier == "private_transitional"

    def test_matching_tier_not_clamped(self, monkeypatch):
        from services.mesh import mesh_router
        monkeypatch.setattr(
            mesh_router, "_supervisor_verified_trust_tier",
            lambda: "private_strong",
        )

        envelope = mesh_router.MeshEnvelope(
            sender_id="!sb_test1234",
            destination="broadcast",
            payload="test payload",
            trust_tier="private_strong",
        )
        assert envelope.trust_tier == "private_strong"

    def test_integrity_hash_binds_tier(self, monkeypatch):
        from services.mesh import mesh_router
        monkeypatch.setattr(
            mesh_router, "_supervisor_verified_trust_tier",
            lambda: "private_transitional",
        )

        envelope = mesh_router.MeshEnvelope(
            sender_id="!sb_test1234",
            destination="broadcast",
            payload="test payload",
            trust_tier="private_transitional",
        )
        original_hash = envelope.integrity_hash
        assert envelope.trust_tier == "private_transitional"

        # Tamper with tier and recompute — hash must differ because the
        # trust_tier is part of the hashed material (Sprint 2 / Rec #2).
        tampered_hash = mesh_router._compute_integrity_hash(
            sender_id="!sb_test1234",
            destination="broadcast",
            payload="test payload",
            timestamp=envelope.timestamp,
            trust_tier="public_degraded",
        )
        assert original_hash != tampered_hash

    def test_unknown_tier_falls_to_public_degraded(self, monkeypatch):
        from services.mesh import mesh_router
        monkeypatch.setattr(
            mesh_router, "_supervisor_verified_trust_tier",
            lambda: "public_degraded",
        )

        envelope = mesh_router.MeshEnvelope(
            sender_id="!sb_test1234",
            destination="broadcast",
            payload="test payload",
            trust_tier="ultra_secret_tier",
        )
        assert envelope.trust_tier == "public_degraded"


# ── Field injection vectors ──────────────────────────────────────────────────

class TestFieldInjection:
    """Forbidden fields in public ledger payloads must be rejected."""

    def _check_forbidden(self, field_name, field_value):
        from services.mesh.mesh_protocol import normalize_payload
        from services.mesh.mesh_schema import validate_public_ledger_payload

        payload = normalize_payload("message", {
            "message": "hello", "destination": "broadcast",
            "channel": "LongFast", "priority": "normal", "ephemeral": False,
        })
        payload[field_name] = field_value

        ok, reason = validate_public_ledger_payload("message", payload)
        assert ok is False
        assert "forbidden" in reason.lower()

    def test_ip_address_rejected(self):
        self._check_forbidden("ip_address", "10.0.0.1")

    def test_transport_lock_rejected(self):
        self._check_forbidden("transport_lock", "meshtastic")

    def test_origin_ip_rejected(self):
        self._check_forbidden("origin_ip", "192.168.1.1")

    def test_host_rejected(self):
        self._check_forbidden("host", "evil.local")

    def test_route_hint_rejected(self):
        self._check_forbidden("route_hint", "via-tor")

    def test_routed_via_rejected(self):
        self._check_forbidden("routed_via", "clearnet")

    def test_recipient_id_rejected(self):
        self._check_forbidden("recipient_id", "!sb_private")

    def test_dh_pub_key_rejected(self):
        self._check_forbidden("dh_pub_key", "AAAA")

    def test_sender_token_rejected(self):
        self._check_forbidden("sender_token", "tok-leak")


# ── Replay vectors ───────────────────────────────────────────────────────────

class TestReplayProtection:
    """Replayed or sequence-violated events must be rejected."""

    def test_duplicate_event_id_detected_by_replay_filter(self):
        from services.mesh import mesh_hashchain

        rf = mesh_hashchain.ReplayFilter()
        event_id = hashlib.sha256(b"test-event").hexdigest()

        assert rf.seen(event_id) is False, "filter should be empty initially"
        rf.add(event_id)
        assert rf.seen(event_id) is True, "added event should be reported as seen"

    def test_replay_filter_tracks_many_events(self):
        from services.mesh import mesh_hashchain

        rf = mesh_hashchain.ReplayFilter()
        event_ids = [hashlib.sha256(f"event-{i}".encode()).hexdigest() for i in range(500)]
        for eid in event_ids:
            rf.add(eid)

        # All added events should be reported as seen
        for eid in event_ids:
            assert rf.seen(eid) is True

        # A fresh event should not be reported as seen
        fresh = hashlib.sha256(b"never-added").hexdigest()
        assert rf.seen(fresh) is False


# ── Integrity vectors ────────────────────────────────────────────────────────

class TestSignatureIntegrity:
    """Events with corrupted signatures or mismatched node bindings must be rejected."""

    @staticmethod
    def _fresh_keypair():
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization

        private = Ed25519PrivateKey.generate()
        pub_bytes = private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        pub_b64 = base64.b64encode(pub_bytes).decode()
        return private, pub_bytes, pub_b64

    def test_corrupted_signature_rejected(self):
        from services.mesh.mesh_crypto import verify_signature

        private, _, pub_b64 = self._fresh_keypair()
        payload = "test_payload_data"
        sig = private.sign(payload.encode())
        sig_hex = sig.hex()

        # Corrupt the signature
        corrupted = bytearray(sig)
        corrupted[0] ^= 0xFF
        corrupted_hex = bytes(corrupted).hex()

        # Valid signature should pass
        assert verify_signature(
            public_key_b64=pub_b64,
            public_key_algo="Ed25519",
            signature_hex=sig_hex,
            payload=payload,
        ) is True
        # Corrupted signature should fail
        assert verify_signature(
            public_key_b64=pub_b64,
            public_key_algo="Ed25519",
            signature_hex=corrupted_hex,
            payload=payload,
        ) is False

    def test_node_id_binding_mismatch_rejected(self):
        from services.mesh.mesh_crypto import derive_node_id, verify_node_binding

        _, _, pub_b64 = self._fresh_keypair()

        # Correct node_id — use the canonical derivation
        correct_id = derive_node_id(pub_b64)
        assert verify_node_binding(correct_id, pub_b64) is True

        # Wrong node_id
        assert verify_node_binding("!sb_00000000000000000000000000000000", pub_b64) is False

    def test_non_public_ledger_event_type_rejected(self):
        from services.mesh.mesh_schema import validate_public_ledger_payload

        ok, reason = validate_public_ledger_payload("gate_secret_update", {})
        assert ok is False
        assert "not allowed" in reason.lower()


# ── Protocol version vectors ─────────────────────────────────────────────────

class TestProtocolVersionEnforcement:
    """Wrong protocol version or network ID must be rejected."""

    def test_wrong_protocol_version(self):
        from services.mesh.mesh_schema import validate_protocol_fields
        ok, reason = validate_protocol_fields("infonet/99", "sb-testnet-0")
        assert ok is False

    def test_wrong_network_id(self):
        from services.mesh.mesh_schema import validate_protocol_fields
        ok, reason = validate_protocol_fields("infonet/2", "sb-mainnet-evil")
        assert ok is False

    def test_correct_protocol_passes(self):
        from services.mesh.mesh_schema import validate_protocol_fields
        ok, reason = validate_protocol_fields("infonet/2", "sb-testnet-0")
        assert ok is True
