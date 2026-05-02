"""S5C DM Ciphertext Bucket Padding — prove padding envelope correctness.

Tests:
- Padded payload length rounds to PAD_BUCKET_STEP
- encrypt_dm + decrypt_dm round-trip returns original plaintext
- Nearby plaintexts collapse into same bucket size
- Legacy unpadded MLS ciphertext still decrypts
- Truncated padding envelope is rejected
"""

import struct

import pytest


# ---------------------------------------------------------------------------
# Unit tests for the padding helpers directly
# ---------------------------------------------------------------------------

def test_pad_rounds_to_bucket_step():
    """Padded output length must be a multiple of PAD_BUCKET_STEP."""
    from services.mesh.mesh_dm_mls import PAD_BUCKET_STEP, _pad_plaintext

    for size in [0, 1, 100, 500, 504, 505, 512, 1000, 2048, 4096]:
        padded = _pad_plaintext(b"x" * size)
        assert len(padded) % PAD_BUCKET_STEP == 0, f"size={size} → len={len(padded)}"
        assert len(padded) >= size + 8  # header is 8 bytes


def test_pad_unpad_round_trip():
    """_pad_plaintext followed by _unpad_plaintext returns the original bytes."""
    from services.mesh.mesh_dm_mls import _pad_plaintext, _unpad_plaintext

    for msg in [b"", b"hello", b"x" * 504, b"x" * 505, b"x" * 1024, b"\xff" * 4096]:
        assert _unpad_plaintext(_pad_plaintext(msg)) == msg


def test_nearby_sizes_same_bucket():
    """Plaintexts of different nearby sizes must collapse into the same padded length."""
    from services.mesh.mesh_dm_mls import PAD_BUCKET_STEP, PAD_HEADER_SIZE, _pad_plaintext

    # All sizes 1..100 should fit within the first bucket (header + data ≤ 512)
    lengths = {len(_pad_plaintext(b"a" * n)) for n in range(1, 101)}
    assert len(lengths) == 1, f"Expected 1 bucket, got {lengths}"
    assert lengths.pop() == PAD_BUCKET_STEP


def test_bucket_boundary_steps_up():
    """Once plaintext + header exceeds one bucket, the next bucket is used."""
    from services.mesh.mesh_dm_mls import PAD_BUCKET_STEP, PAD_HEADER_SIZE, _pad_plaintext

    # Exactly fills one bucket: header(8) + data(504) = 512
    fits = _pad_plaintext(b"x" * (PAD_BUCKET_STEP - PAD_HEADER_SIZE))
    assert len(fits) == PAD_BUCKET_STEP

    # One byte over spills into second bucket
    spills = _pad_plaintext(b"x" * (PAD_BUCKET_STEP - PAD_HEADER_SIZE + 1))
    assert len(spills) == PAD_BUCKET_STEP * 2


def test_legacy_unpadded_passthrough():
    """Bytes without SBP1 magic are returned unchanged (legacy compatibility)."""
    from services.mesh.mesh_dm_mls import _unpad_plaintext

    legacy = b"plain old text without padding"
    assert _unpad_plaintext(legacy) == legacy

    # Also test short data
    assert _unpad_plaintext(b"") == b""
    assert _unpad_plaintext(b"SBP") == b"SBP"  # too short for header


def test_truncated_padded_payload_rejected():
    """A valid magic but truncated body must raise an error."""
    from services.mesh.mesh_dm_mls import PAD_MAGIC, _unpad_plaintext
    from services.privacy_core_client import PrivacyCoreError

    # Claim original_len = 1000, but only provide 10 bytes of body
    bad = PAD_MAGIC + struct.pack(">I", 1000) + b"x" * 10
    with pytest.raises(PrivacyCoreError, match="truncated"):
        _unpad_plaintext(bad)


# ---------------------------------------------------------------------------
# Integration tests through the full encrypt_dm / decrypt_dm seam
# ---------------------------------------------------------------------------

def _fresh_dm_mls_state(tmp_path, monkeypatch):
    from services import wormhole_supervisor
    from services.mesh import mesh_dm_mls, mesh_dm_relay, mesh_secure_storage, mesh_wormhole_persona

    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    monkeypatch.setattr(mesh_wormhole_persona, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_persona, "PERSONA_FILE", tmp_path / "wormhole_persona.json")
    monkeypatch.setattr(
        mesh_wormhole_persona,
        "LEGACY_DM_IDENTITY_FILE",
        tmp_path / "wormhole_identity.json",
    )
    monkeypatch.setattr(mesh_dm_mls, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_dm_mls, "STATE_FILE", tmp_path / "wormhole_dm_mls.json")
    monkeypatch.setattr(mesh_dm_relay, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_dm_relay, "RELAY_FILE", tmp_path / "dm_relay.json")
    monkeypatch.setattr(
        mesh_dm_mls,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": True},
    )
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": True},
    )
    relay = mesh_dm_relay.DMRelay()
    monkeypatch.setattr(mesh_dm_relay, "dm_relay", relay)
    mesh_dm_mls.reset_dm_mls_state(clear_privacy_core=True, clear_persistence=True)
    return mesh_dm_mls, relay


def _establish_session(dm_mls):
    """Helper: create alice→bob MLS session and return dm_mls module."""
    bob_bundle = dm_mls.export_dm_key_package_for_alias("bob")
    assert bob_bundle["ok"] is True
    initiated = dm_mls.initiate_dm_session("alice", "bob", bob_bundle)
    assert initiated["ok"] is True
    accepted = dm_mls.accept_dm_session("bob", "alice", initiated["welcome"])
    assert accepted["ok"] is True


def test_encrypt_decrypt_round_trip_through_mls(tmp_path, monkeypatch):
    """encrypt_dm + decrypt_dm must round-trip the original plaintext with padding active."""
    dm_mls, _ = _fresh_dm_mls_state(tmp_path, monkeypatch)
    _establish_session(dm_mls)

    original = "hello bob, this is a secret message"
    encrypted = dm_mls.encrypt_dm("alice", "bob", original)
    assert encrypted["ok"] is True

    decrypted = dm_mls.decrypt_dm("bob", "alice", encrypted["ciphertext"], encrypted["nonce"])
    assert decrypted["ok"] is True
    assert decrypted["plaintext"] == original


def test_encrypt_produces_padded_ciphertext(tmp_path, monkeypatch):
    """The plaintext fed to privacy-core must be bucket-padded (verify via round-trip size)."""
    dm_mls, _ = _fresh_dm_mls_state(tmp_path, monkeypatch)
    _establish_session(dm_mls)

    # Capture the padded bytes that privacy-core receives
    captured = {}
    original_dm_encrypt = dm_mls._privacy_client().dm_encrypt

    def spy_dm_encrypt(handle, data):
        captured["padded"] = data
        return original_dm_encrypt(handle, data)

    monkeypatch.setattr(dm_mls._privacy_client(), "dm_encrypt", spy_dm_encrypt)

    dm_mls.encrypt_dm("alice", "bob", "short")
    padded = captured["padded"]
    assert padded[:4] == dm_mls.PAD_MAGIC
    assert len(padded) % dm_mls.PAD_BUCKET_STEP == 0


def test_legacy_unpadded_mls_ciphertext_decrypts(tmp_path, monkeypatch):
    """Legacy ciphertext (no SBP1 header) must still decrypt successfully."""
    dm_mls, _ = _fresh_dm_mls_state(tmp_path, monkeypatch)
    _establish_session(dm_mls)

    # Encrypt without padding by calling privacy-core directly (simulating legacy)
    binding = dm_mls._session_binding("alice", "bob")
    raw_plaintext = b"legacy unpadded message"
    raw_ciphertext = dm_mls._privacy_client().dm_encrypt(binding.session_handle, raw_plaintext)
    ciphertext_b64 = dm_mls._b64(raw_ciphertext)

    decrypted = dm_mls.decrypt_dm("bob", "alice", ciphertext_b64, "")
    assert decrypted["ok"] is True
    assert decrypted["plaintext"] == "legacy unpadded message"
