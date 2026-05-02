"""Sprint 8 — Argon2id canonical preimage + leading-zero check.

Maps to IMPLEMENTATION_PLAN §7.1 Sprint 8 row:
"Argon2id parameters are deterministic across implementations.
Salt = raw `snapshot_event_hash` bytes.
Leading zero check is MSB-first on raw output bytes."
"""

from __future__ import annotations

import pytest

from services.infonet.bootstrap import (
    canonical_pow_preimage,
    has_leading_zero_bits,
    verify_pow_structure,
)


# ── Canonical preimage ──────────────────────────────────────────────────

def test_preimage_is_pipe_delimited_utf8_no_trailing():
    pre = canonical_pow_preimage(
        node_id="alice",
        market_id="m1",
        side="yes",
        snapshot_event_hash="abc123",
        pow_nonce=42,
        protocol_version="0.1.0",
    )
    expected = b"bootstrap_resolution_vote|0.1.0|alice|m1|yes|abc123|42"
    assert pre == expected


def test_preimage_uses_immutable_protocol_version_default():
    """When protocol_version is omitted, the executor pulls from
    IMMUTABLE_PRINCIPLES at call time."""
    from services.infonet.config import IMMUTABLE_PRINCIPLES
    pre = canonical_pow_preimage(
        node_id="alice", market_id="m1", side="yes",
        snapshot_event_hash="abc", pow_nonce=0,
    )
    assert IMMUTABLE_PRINCIPLES["protocol_version"].encode() in pre


def test_preimage_deterministic_across_calls():
    args = dict(node_id="alice", market_id="m1", side="yes",
                snapshot_event_hash="abc", pow_nonce=42, protocol_version="0.1.0")
    a = canonical_pow_preimage(**args)
    b = canonical_pow_preimage(**args)
    assert a == b


def test_preimage_changes_when_any_field_changes():
    base = dict(node_id="alice", market_id="m1", side="yes",
                snapshot_event_hash="abc", pow_nonce=42, protocol_version="0.1.0")
    baseline = canonical_pow_preimage(**base)
    for field, mutated in [
        ("node_id", "bob"),
        ("market_id", "m2"),
        ("side", "no"),
        ("snapshot_event_hash", "abd"),
        ("pow_nonce", 43),
        ("protocol_version", "0.2.0"),
    ]:
        d = dict(base)
        d[field] = mutated
        assert canonical_pow_preimage(**d) != baseline, (
            f"changing {field} did not change the preimage — "
            f"this would create cross-domain PoW reuse"
        )


def test_preimage_rejects_invalid_inputs():
    with pytest.raises(ValueError):
        canonical_pow_preimage(node_id="", market_id="m1", side="yes",
                               snapshot_event_hash="abc", pow_nonce=0,
                               protocol_version="0.1.0")
    with pytest.raises(ValueError):
        canonical_pow_preimage(node_id="alice", market_id="m1", side="maybe",
                               snapshot_event_hash="abc", pow_nonce=0,
                               protocol_version="0.1.0")
    with pytest.raises(ValueError):
        canonical_pow_preimage(node_id="alice", market_id="m1", side="yes",
                               snapshot_event_hash="abc", pow_nonce=-1,
                               protocol_version="0.1.0")
    with pytest.raises(ValueError):
        canonical_pow_preimage(node_id="alice", market_id="m1", side="yes",
                               snapshot_event_hash="abc", pow_nonce=True,  # bool not int
                               protocol_version="0.1.0")  # type: ignore[arg-type]


# ── Leading-zero check (MSB first) ──────────────────────────────────────

def test_difficulty_zero_always_passes():
    assert has_leading_zero_bits(b"\xff\xff", 0)
    assert has_leading_zero_bits(b"", 0)


def test_difficulty_one_requires_msb_zero():
    # 0x80 = 0b10000000 — MSB set → fails.
    assert not has_leading_zero_bits(b"\x80", 1)
    # 0x7f = 0b01111111 — MSB clear → passes.
    assert has_leading_zero_bits(b"\x7f", 1)


def test_difficulty_eight_requires_first_byte_zero():
    assert has_leading_zero_bits(b"\x00\xff", 8)
    assert not has_leading_zero_bits(b"\x01\x00", 8)


def test_difficulty_sixteen_requires_first_two_bytes_zero():
    assert has_leading_zero_bits(b"\x00\x00\xff", 16)
    assert not has_leading_zero_bits(b"\x00\x01\xff", 16)
    assert not has_leading_zero_bits(b"\x01\x00\xff", 16)


def test_difficulty_partial_byte_msb_first():
    """difficulty=4 → first byte's TOP 4 bits must be zero. Bytes
    with values in 0x00–0x0f satisfy; 0x10 or higher do not."""
    for ok in (0x00, 0x05, 0x0f):
        assert has_leading_zero_bits(bytes([ok]), 4), f"{ok:#04x} should pass"
    for bad in (0x10, 0x80, 0xff):
        assert not has_leading_zero_bits(bytes([bad]), 4), f"{bad:#04x} should fail"


def test_lsb_first_would_fail_test_vectors():
    """Sanity check: if an implementation MISTAKENLY used LSB-first
    bit numbering, our test vectors would diverge. We pin the
    MSB-first convention explicitly so a future change to LSB-first
    breaks loudly."""
    # 0x01 = 0b00000001 — MSB-first: 7 leading zeros.
    #                     LSB-first: 0 leading zeros (LSB is set).
    # Our impl says 7 leading zeros.
    assert has_leading_zero_bits(b"\x01", 7)
    # And not 8 (because the 8th-from-MSB bit is 1).
    assert not has_leading_zero_bits(b"\x01", 8)


def test_short_output_against_high_difficulty_fails():
    # 1 byte of \x00, asked for 16 leading zero bits → not enough bytes.
    assert not has_leading_zero_bits(b"\x00", 16)


# ── verify_pow_structure ────────────────────────────────────────────────

def test_verify_pow_rejects_wrong_output_length():
    raw = b"\x00" * 31  # one byte short
    assert not verify_pow_structure(raw_output=raw, difficulty=8)


def test_verify_pow_accepts_canonical_output():
    raw = b"\x00\x00" + b"\xff" * 30
    assert verify_pow_structure(raw_output=raw, difficulty=16)


def test_verify_pow_with_default_difficulty_from_config():
    """The default difficulty is read from CONFIG; bumping CONFIG is
    a governance petition, not a code change."""
    from services.infonet.config import CONFIG
    diff = int(CONFIG["bootstrap_pow_difficulty"])
    full_bytes, rem_bits = divmod(diff, 8)
    # Build a passing output: all-zero leading bytes then 0xff filler.
    raw = bytes([0] * full_bytes) + (
        bytes([0]) if rem_bits else b""
    ) + b"\xff" * (32 - full_bytes - (1 if rem_bits else 0))
    raw = raw[:32]
    assert verify_pow_structure(raw_output=raw)


def test_verify_pow_rejects_non_bytes():
    assert not verify_pow_structure(raw_output="not bytes", difficulty=0)  # type: ignore[arg-type]
