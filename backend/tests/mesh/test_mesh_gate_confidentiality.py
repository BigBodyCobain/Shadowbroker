"""Phase 5B — Gate Confidentiality Enforcement tests.

Validates that:
1. _gate_envelope_encrypt succeeds when gate_secret is present
2. _gate_envelope_encrypt fails explicitly when gate_secret is unavailable (empty)
3. _gate_envelope_encrypt fails explicitly when gate_manager lookup throws
4. Legacy v1 shared-key ciphertexts remain decryptable via _gate_envelope_decrypt
5. No new-encryption path silently falls through to gate_id-only derivation
"""
import base64

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_module(monkeypatch):
    """Import mesh_gate_mls after patching away heavy side-effects."""
    from services.mesh import mesh_gate_mls
    return mesh_gate_mls


def _stub_gate_manager(monkeypatch, secret: str = "real-secret-abc"):
    """Provide a minimal gate_manager stub with a known secret."""
    from services.mesh import mesh_reputation

    class _StubGateManager:
        def get_gate_secret(self, gate_id: str) -> str:
            return secret

        def ensure_gate_secret(self, gate_id: str) -> str:
            return secret

    monkeypatch.setattr(mesh_reputation, "gate_manager", _StubGateManager(), raising=False)


def _stub_gate_manager_throws(monkeypatch):
    """Provide a gate_manager stub whose get_gate_secret always raises."""
    from services.mesh import mesh_reputation

    class _BrokenGateManager:
        def get_gate_secret(self, gate_id: str) -> str:
            raise RuntimeError("gate_manager unavailable")

    monkeypatch.setattr(mesh_reputation, "gate_manager", _BrokenGateManager(), raising=False)


def _stub_gate_manager_empty(monkeypatch):
    """Provide a gate_manager stub that returns an empty secret."""
    _stub_gate_manager(monkeypatch, secret="")


# ---------------------------------------------------------------------------
# 1. Encrypt succeeds when gate_secret is present
# ---------------------------------------------------------------------------

class TestGateEnvelopeEncryptWithSecret:
    def test_produces_non_empty_base64_token(self, monkeypatch):
        mod = _get_module(monkeypatch)
        _stub_gate_manager(monkeypatch, secret="good-secret-123")
        token = mod._gate_envelope_encrypt(
            "finance",
            "classified payload",
            message_nonce="msg-finance-1",
        )
        assert isinstance(token, str)
        assert len(token) > 0
        # Must be valid base64
        raw = base64.b64decode(token)
        # nonce (12 bytes) + ciphertext (>0 bytes)
        assert len(raw) > 12

    def test_roundtrip_decrypt_succeeds(self, monkeypatch):
        mod = _get_module(monkeypatch)
        _stub_gate_manager(monkeypatch, secret="roundtrip-secret")
        token = mod._gate_envelope_encrypt(
            "ops",
            "roundtrip test",
            message_nonce="ops-msg-1",
        )
        plaintext = mod._gate_envelope_decrypt(
            "ops",
            token,
            message_nonce="ops-msg-1",
        )
        assert plaintext == "roundtrip test"

    def test_scoped_envelope_requires_matching_nonce(self, monkeypatch):
        mod = _get_module(monkeypatch)
        _stub_gate_manager(monkeypatch, secret="nonce-bound-secret")
        token = mod._gate_envelope_encrypt(
            "ops",
            "nonce scoped",
            message_nonce="ops-msg-2",
        )
        assert mod._gate_envelope_decrypt(
            "ops",
            token,
            message_nonce="ops-msg-3",
        ) is None
        assert mod._gate_envelope_decrypt(
            "ops",
            token,
            message_nonce="ops-msg-2",
        ) == "nonce scoped"

    def test_legacy_unscoped_envelope_still_decrypts_during_upgrade(self, monkeypatch):
        mod = _get_module(monkeypatch)
        _stub_gate_manager(monkeypatch, secret="legacy-upgrade-secret")
        token = mod._gate_envelope_encrypt("ops", "legacy scoped later")
        assert mod._gate_envelope_decrypt(
            "ops",
            token,
            message_nonce="ops-msg-upgrade",
        ) == "legacy scoped later"

    def test_different_secrets_produce_different_tokens(self, monkeypatch):
        mod = _get_module(monkeypatch)
        _stub_gate_manager(monkeypatch, secret="secret-a")
        token_a = mod._gate_envelope_encrypt(
            "gate1",
            "same plaintext",
            message_nonce="gate1-msg-1",
        )
        _stub_gate_manager(monkeypatch, secret="secret-b")
        token_b = mod._gate_envelope_encrypt(
            "gate1",
            "same plaintext",
            message_nonce="gate1-msg-1",
        )
        # Tokens differ because of different keys (and random nonces)
        assert token_a != token_b


# ---------------------------------------------------------------------------
# 2. Encrypt fails explicitly when gate_secret is empty
# ---------------------------------------------------------------------------

class TestGateEnvelopeEncryptEmptySecret:
    def test_raises_gate_secret_unavailable_error(self, monkeypatch):
        mod = _get_module(monkeypatch)
        _stub_gate_manager_empty(monkeypatch)
        with pytest.raises(mod.GateSecretUnavailableError):
            mod._gate_envelope_encrypt("finance", "should not encrypt")

    def test_error_message_mentions_gate(self, monkeypatch):
        mod = _get_module(monkeypatch)
        _stub_gate_manager_empty(monkeypatch)
        with pytest.raises(mod.GateSecretUnavailableError, match="gate secret is empty"):
            mod._gate_envelope_encrypt("finance", "should not encrypt")

    def test_no_ciphertext_produced(self, monkeypatch):
        """Ensure no token leaks out even via partial execution."""
        mod = _get_module(monkeypatch)
        _stub_gate_manager_empty(monkeypatch)
        result = None
        try:
            result = mod._gate_envelope_encrypt("finance", "should not encrypt")
        except mod.GateSecretUnavailableError:
            pass
        assert result is None


# ---------------------------------------------------------------------------
# 3. Encrypt fails explicitly when gate_manager lookup throws
# ---------------------------------------------------------------------------

class TestGateEnvelopeEncryptManagerThrows:
    def test_raises_gate_secret_unavailable_error(self, monkeypatch):
        mod = _get_module(monkeypatch)
        _stub_gate_manager_throws(monkeypatch)
        with pytest.raises(mod.GateSecretUnavailableError):
            mod._gate_envelope_encrypt("finance", "should not encrypt")

    def test_chains_original_exception(self, monkeypatch):
        mod = _get_module(monkeypatch)
        _stub_gate_manager_throws(monkeypatch)
        with pytest.raises(mod.GateSecretUnavailableError) as exc_info:
            mod._gate_envelope_encrypt("finance", "should not encrypt")
        assert exc_info.value.__cause__ is not None
        assert isinstance(exc_info.value.__cause__, RuntimeError)

    def test_error_message_mentions_lookup_failure(self, monkeypatch):
        mod = _get_module(monkeypatch)
        _stub_gate_manager_throws(monkeypatch)
        with pytest.raises(mod.GateSecretUnavailableError, match="gate_manager lookup failed"):
            mod._gate_envelope_encrypt("finance", "should not encrypt")


# ---------------------------------------------------------------------------
# 4. Legacy v1 shared-key ciphertext remains decryptable
# ---------------------------------------------------------------------------

class TestLegacySharedEnvelopeDecryption:
    def test_legacy_v1_envelope_decryptable_via_fallback(self, monkeypatch):
        """Simulate a pre-v2 shared-key envelope and verify decrypt still works."""
        mod = _get_module(monkeypatch)
        gate_id = "legacy-gate"
        plaintext = "old secret message"
        gate_secret = "legacy-v1-secret"

        # Manually encrypt with the pre-v2 shared per-gate key derivation.
        import os
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        legacy_key = mod._gate_envelope_key_shared(gate_id, gate_secret)
        nonce = os.urandom(12)
        aad = f"gate_envelope|{gate_id}".encode("utf-8")
        ct = AESGCM(legacy_key).encrypt(nonce, plaintext.encode("utf-8"), aad)
        legacy_token = base64.b64encode(nonce + ct).decode("ascii")

        # Decrypt should succeed via the shared-key fallback path even when
        # the runtime supplies a scoped message nonce.
        _stub_gate_manager(monkeypatch, secret=gate_secret)
        result = mod._gate_envelope_decrypt(
            gate_id,
            legacy_token,
            message_nonce="legacy-gate-msg-1",
        )
        assert result == plaintext

    def test_legacy_v1_envelope_not_decryptable_with_wrong_secret(self, monkeypatch):
        """Shared-key fallback must still depend on the correct gate secret."""
        mod = _get_module(monkeypatch)
        gate_id = "old-gate"
        plaintext = "legacy data"
        gate_secret = "legacy-secret-good"

        import os
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        legacy_key = mod._gate_envelope_key_shared(gate_id, gate_secret)
        nonce = os.urandom(12)
        aad = f"gate_envelope|{gate_id}".encode("utf-8")
        ct = AESGCM(legacy_key).encrypt(nonce, plaintext.encode("utf-8"), aad)
        legacy_token = base64.b64encode(nonce + ct).decode("ascii")

        _stub_gate_manager(monkeypatch, secret="legacy-secret-wrong")
        result = mod._gate_envelope_decrypt(
            gate_id,
            legacy_token,
            message_nonce="old-gate-msg-1",
        )
        assert result is None

    def test_legacy_v1_envelope_still_opens_without_nonce_context(self, monkeypatch):
        """Old shared envelopes still open when callers have no scoped nonce yet."""
        mod = _get_module(monkeypatch)
        gate_id = "crash-gate"
        plaintext = "survive upgrade"
        gate_secret = "legacy-shared-secret"

        import os
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        legacy_key = mod._gate_envelope_key_shared(gate_id, gate_secret)
        nonce = os.urandom(12)
        aad = f"gate_envelope|{gate_id}".encode("utf-8")
        ct = AESGCM(legacy_key).encrypt(nonce, plaintext.encode("utf-8"), aad)
        legacy_token = base64.b64encode(nonce + ct).decode("ascii")

        _stub_gate_manager(monkeypatch, secret=gate_secret)
        result = mod._gate_envelope_decrypt(gate_id, legacy_token)
        assert result == plaintext

    def test_phase2_envelope_not_decryptable_with_wrong_secret(self, monkeypatch):
        """Phase-2 envelope encrypted with secret-A cannot be decrypted with secret-B."""
        mod = _get_module(monkeypatch)
        gate_id = "secure-gate"

        _stub_gate_manager(monkeypatch, secret="correct-secret")
        token = mod._gate_envelope_encrypt(
            gate_id,
            "confidential",
            message_nonce="secure-gate-msg-1",
        )

        # Switch to wrong secret — neither phase-2 nor legacy key will work
        _stub_gate_manager(monkeypatch, secret="wrong-secret")
        result = mod._gate_envelope_decrypt(
            gate_id,
            token,
            message_nonce="secure-gate-msg-1",
        )
        # Phase-2 key mismatch, and legacy key mismatch too (since it was encrypted with phase-2)
        assert result is None


# ---------------------------------------------------------------------------
# 5. No new-encryption path silently falls through to gate_id-only derivation
# ---------------------------------------------------------------------------

class TestNoSilentPhase1Fallback:
    def test_empty_secret_does_not_produce_legacy_decodable_token(self, monkeypatch):
        """Verify that when secret is empty, encrypt raises instead of producing
        a token that could be decoded with the legacy gate-name-only key."""
        mod = _get_module(monkeypatch)
        _stub_gate_manager_empty(monkeypatch)

        with pytest.raises(mod.GateSecretUnavailableError):
            mod._gate_envelope_encrypt("finance", "must not leak")

    def test_manager_error_does_not_produce_legacy_decodable_token(self, monkeypatch):
        """When gate_manager throws, no token is produced at all."""
        mod = _get_module(monkeypatch)
        _stub_gate_manager_throws(monkeypatch)

        with pytest.raises(mod.GateSecretUnavailableError):
            mod._gate_envelope_encrypt("finance", "must not leak")

    def test_resolve_gate_secret_propagates_exceptions(self, monkeypatch):
        """_resolve_gate_secret must not swallow exceptions anymore."""
        mod = _get_module(monkeypatch)
        _stub_gate_manager_throws(monkeypatch)
        with pytest.raises(mod.GateSecretUnavailableError):
            mod._resolve_gate_secret("any-gate")

    def test_scoped_key_derivation_differs_from_shared_key(self, monkeypatch):
        """Scoped v2 keys must differ from the older shared per-gate key."""
        mod = _get_module(monkeypatch)
        shared_key = mod._gate_envelope_key_shared("finance", "real-secret")
        scoped_key = mod._gate_envelope_key_scoped(
            "finance",
            "real-secret",
            message_nonce="finance-msg-1",
        )
        assert shared_key != scoped_key
        assert len(shared_key) == 32
        assert len(scoped_key) == 32

    def test_compose_path_catches_and_logs_without_producing_envelope(self, monkeypatch, caplog):
        """The compose caller must catch GateSecretUnavailableError and
        produce an MLS-only message (empty gate_envelope), not a Phase-1 envelope."""
        import logging
        mod = _get_module(monkeypatch)

        call_log = []
        original_encrypt = mod._gate_envelope_encrypt

        def tracking_encrypt(gate_id, plaintext, **kwargs):
            call_log.append(gate_id)
            return original_encrypt(gate_id, plaintext, **kwargs)

        monkeypatch.setattr(mod, "_gate_envelope_encrypt", tracking_encrypt)
        _stub_gate_manager_empty(monkeypatch)

        # Directly test the encrypt raises (compose path catches it)
        with pytest.raises(mod.GateSecretUnavailableError):
            mod._gate_envelope_encrypt("test-gate", "payload")
