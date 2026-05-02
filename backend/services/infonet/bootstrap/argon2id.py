"""Argon2id canonicalization — preimage construction and leading-zero check.

Source of truth: ``infonet-economy/RULES_SKELETON.md`` §3.10 step 0.5
+ the ``CONFIG['bootstrap_pow_argon2id_*']`` comment block.

Two consensus-critical pieces of canonicalization:

1. **Canonical preimage** — exact byte sequence the Argon2id call
   takes as `password`. UTF-8 encoded, "|"-delimited, no trailing
   delimiter. Format:

       "bootstrap_resolution_vote" || protocol_version || node_id ||
       market_id || side || snapshot_event_hash || pow_nonce

   The component order MUST match the spec exactly. Any deviation
   causes consensus fork.

2. **Leading-zero check** — operates on RAW Argon2id output bytes,
   MSB first (big-endian bit numbering). Difficulty N requires the
   first N bits of the 32-byte output to be zero. With difficulty=16
   that means the first 2 bytes are 0x00 0x00.

Sprint 8 does NOT execute Argon2id itself — the verifier here takes
an already-computed hash bytes object as input. Production callers
wire this through ``privacy-core`` Rust binding. A stub Python
implementation is intentionally absent to avoid accidental drift
between the Sprint 8 pure-Python path and the eventual Rust path.
"""

from __future__ import annotations

from services.infonet.config import CONFIG, IMMUTABLE_PRINCIPLES


def canonical_pow_preimage(
    *,
    node_id: str,
    market_id: str,
    side: str,
    snapshot_event_hash: str,
    pow_nonce: int,
    protocol_version: str | None = None,
) -> bytes:
    """Build the canonical preimage for the Argon2id ``password`` input.

    Returns UTF-8 bytes of ``"bootstrap_resolution_vote|<version>|<node>|
    <market>|<side>|<snapshot_hash>|<nonce>"`` with NO trailing delimiter.

    ``protocol_version`` defaults to ``IMMUTABLE_PRINCIPLES['protocol_version']``
    — it's pulled at call time so a hard-fork upgrade picks up the
    new value automatically. Pass an explicit value when computing
    against a hypothetical version (test scenarios).
    """
    if not isinstance(node_id, str) or not node_id:
        raise ValueError("node_id must be a non-empty string")
    if not isinstance(market_id, str) or not market_id:
        raise ValueError("market_id must be a non-empty string")
    if side not in ("yes", "no"):
        raise ValueError("side must be 'yes' or 'no'")
    if not isinstance(snapshot_event_hash, str) or not snapshot_event_hash:
        raise ValueError("snapshot_event_hash must be a non-empty string")
    if not isinstance(pow_nonce, int) or isinstance(pow_nonce, bool) or pow_nonce < 0:
        raise ValueError("pow_nonce must be a non-negative int")
    pv = protocol_version if protocol_version is not None else IMMUTABLE_PRINCIPLES["protocol_version"]
    if not isinstance(pv, str) or not pv:
        raise ValueError("protocol_version must be a non-empty string")

    parts = [
        "bootstrap_resolution_vote",
        pv,
        node_id,
        market_id,
        side,
        snapshot_event_hash,
        str(pow_nonce),
    ]
    return "|".join(parts).encode("utf-8")


def has_leading_zero_bits(raw_output: bytes, difficulty: int) -> bool:
    """``True`` if the first ``difficulty`` bits of ``raw_output``
    are all zero.

    Bit numbering: MSB first (big-endian). Byte order: as-is in the
    raw output. With difficulty=16, the first two bytes must be
    ``\\x00\\x00``. With difficulty=4, the first byte must be in
    ``\\x00``..``\\x0f``.
    """
    if not isinstance(raw_output, (bytes, bytearray)):
        raise ValueError("raw_output must be bytes")
    if not isinstance(difficulty, int) or difficulty < 0:
        raise ValueError("difficulty must be a non-negative int")
    if difficulty == 0:
        return True

    full_bytes, remaining_bits = divmod(difficulty, 8)
    if len(raw_output) < full_bytes + (1 if remaining_bits else 0):
        return False
    for i in range(full_bytes):
        if raw_output[i] != 0:
            return False
    if remaining_bits:
        # The next byte's top `remaining_bits` bits must be zero.
        next_byte = raw_output[full_bytes]
        # Mask of the top `remaining_bits` bits (MSB first).
        mask = ((0xFF << (8 - remaining_bits)) & 0xFF)
        if (next_byte & mask) != 0:
            return False
    return True


def verify_pow_structure(
    *,
    raw_output: bytes,
    difficulty: int | None = None,
    expected_output_len: int | None = None,
) -> bool:
    """Verify the Argon2id output's structural properties.

    - Output length must match ``expected_output_len`` (default
      ``CONFIG['bootstrap_pow_argon2id_output_len']``, fixed at 32).
    - Leading zero check passes for ``difficulty`` (default
      ``CONFIG['bootstrap_pow_difficulty']``).

    Does NOT verify that ``raw_output`` was actually produced by
    Argon2id from the canonical preimage — that's the caller's job
    via ``privacy-core`` Rust binding (or Python's ``argon2-cffi`` in
    test environments). Sprint 8 keeps the cryptographic-call layer
    as an external concern.
    """
    if not isinstance(raw_output, (bytes, bytearray)):
        return False
    expected = expected_output_len if expected_output_len is not None else int(
        CONFIG["bootstrap_pow_argon2id_output_len"]
    )
    if len(raw_output) != expected:
        return False
    diff = difficulty if difficulty is not None else int(CONFIG["bootstrap_pow_difficulty"])
    return has_leading_zero_bits(raw_output, diff)


__all__ = [
    "canonical_pow_preimage",
    "has_leading_zero_bits",
    "verify_pow_structure",
]
