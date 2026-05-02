"""Typed protocols for the cryptographic primitives.

Production code depends on the **shape** of each privacy primitive
through a ``Protocol`` defined here. Concrete implementations (Rust
binding, Python reference, test mock) all match the same shape, so
swapping them is a one-line import change.

Sprint 11+ ships:

- A reference Python implementation for testing (probably built on
  ``cryptography`` or ``ecdsa`` packages, narrow scope).
- A production Rust binding via ``privacy-core`` crate.

Today (Sprint 11+ runway), this module ships:

- ``Protocol``s for each primitive.
- ``PrivacyPrimitiveStatus`` enum so callers can introspect which
  implementations are wired in.
- A registry of "not yet implemented" statuses with diagnostic
  pointers for future implementers.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Protocol, runtime_checkable


class PrivacyPrimitiveStatus(str, Enum):
    """Lifecycle status for each privacy primitive.

    Used by health endpoints / UI to communicate "this feature is
    not yet shielded" honestly. The cross-cutting non-hostile UX
    rule (BUILD_LOG.md design rules §1) forbids silently pretending
    a primitive is ready when it isn't — surface the truth.
    """
    NOT_IMPLEMENTED = "not_implemented"
    SCAFFOLDING = "scaffolding"
    REFERENCE_IMPL = "reference_impl"
    PRODUCTION_RUST = "production_rust"


# ─── Ring confidential transactions ─────────────────────────────────────

@runtime_checkable
class RingSignatureScheme(Protocol):
    """Signs a transaction with a ring of public keys, hiding which
    member of the ring actually signed.

    Implementations must guarantee:

    - **Unforgeable.** Without one of the ring members' private keys,
      no valid ring signature exists for the transaction.
    - **Anonymous within the ring.** Verifiers learn that *some*
      ring member signed, not which.
    - **Linkable.** Two signatures from the same private key produce
      the same ``key image`` (used to detect double-spends).
    """

    def sign(
        self,
        *,
        message: bytes,
        signer_private_key: bytes,
        ring_public_keys: list[bytes],
    ) -> dict[str, Any]:
        """Return ``{"signature": ..., "key_image": ...}``."""
        ...

    def verify(
        self,
        *,
        message: bytes,
        signature: dict[str, Any],
        ring_public_keys: list[bytes],
    ) -> bool: ...

    def status(self) -> PrivacyPrimitiveStatus: ...


# ─── Stealth addresses ──────────────────────────────────────────────────

@runtime_checkable
class StealthAddressScheme(Protocol):
    """Derives a one-time recipient address per transaction.

    Implementations must guarantee:

    - **Unlinkable.** An external observer cannot tell that two
      stealth addresses belong to the same recipient.
    - **Recipient-recoverable.** Only the recipient (using their
      view key) can determine that an output is theirs.
    """

    def derive_one_time_address(
        self,
        *,
        recipient_view_key: bytes,
        recipient_spend_key: bytes,
        sender_random: bytes,
    ) -> bytes: ...

    def is_for_recipient(
        self,
        *,
        one_time_address: bytes,
        recipient_view_key: bytes,
        recipient_spend_key: bytes,
        sender_random: bytes,
    ) -> bool: ...

    def status(self) -> PrivacyPrimitiveStatus: ...


# ─── Shielded balance commitment ────────────────────────────────────────

@runtime_checkable
class BalanceCommitment(Protocol):
    """Pedersen / homomorphic commitment to a balance.

    Implementations must allow:

    - Commit to a balance ``B`` with blinding factor ``r``.
    - Verify a sum-of-commitments equals zero (proving inputs ==
      outputs without revealing amounts).
    - Range proofs (proving each output is non-negative).
    """

    def commit(self, *, amount: int, blinding: bytes) -> bytes: ...

    def verify_balance(
        self,
        *,
        input_commitments: list[bytes],
        output_commitments: list[bytes],
    ) -> bool: ...

    def range_proof(
        self,
        *,
        amount: int,
        blinding: bytes,
        max_bits: int = 64,
    ) -> bytes: ...

    def verify_range_proof(
        self,
        *,
        commitment: bytes,
        proof: bytes,
        max_bits: int = 64,
    ) -> bool: ...

    def status(self) -> PrivacyPrimitiveStatus: ...


# ─── DEX order book ─────────────────────────────────────────────────────

@runtime_checkable
class DEXOrderBook(Protocol):
    """Privacy-preserving decentralized exchange interface.

    DEX operates ON TOP of the shielded coin layer — orders reference
    shielded inputs/outputs, settlement burns + mints shielded
    commitments. The ``DEXOrderBook`` Protocol is intentionally
    abstract because the specific scheme (CoW-style batched
    settlement, atomic swap, MimbleWimble-flavored aggregation) is
    still open per IMPLEMENTATION_PLAN.md §6.4.
    """

    def place_order(self, *, order: dict[str, Any]) -> str:
        """Return the on-chain ``order_id``."""
        ...

    def cancel_order(self, *, order_id: str, owner_signature: bytes) -> None: ...

    def match_orders(self) -> list[dict[str, Any]]:
        """Return the list of matched trades for atomic settlement."""
        ...

    def status(self) -> PrivacyPrimitiveStatus: ...


__all__ = [
    "BalanceCommitment",
    "DEXOrderBook",
    "PrivacyPrimitiveStatus",
    "RingSignatureScheme",
    "StealthAddressScheme",
]
