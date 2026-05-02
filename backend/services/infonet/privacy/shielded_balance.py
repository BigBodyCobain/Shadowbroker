"""Shielded balance commitments — Sprint 11+ scaffolding.

Source of truth: ``infonet-economy/IMPLEMENTATION_PLAN.md`` §4.3.

Pedersen commitments hide balance amounts while preserving
homomorphic add/subtract. Range proofs (Bulletproofs or similar)
prove each output is non-negative without revealing it.

A balance is committed as ``C = amount * G + blinding * H`` where
``G, H`` are independent generators. ``sum(inputs) - sum(outputs)
== 0`` proves "no value created or destroyed" without revealing any
of the values.

Production implementation lands through the ``BalanceCommitment``
Protocol when the Rust binding is ready.
"""

from __future__ import annotations

from services.infonet.privacy.contracts import PrivacyPrimitiveStatus


class ShieldedBalanceScaffolding:
    """Placeholder until the Rust balance-commitment binding lands."""

    _DIAGNOSTIC = (
        "Shielded balance primitive is scaffolding only — production "
        "implementation requires a Pedersen commitment + range-proof "
        "library (e.g. bulletproofs). See "
        "infonet-economy/IMPLEMENTATION_PLAN.md §4.3."
    )

    def commit(self, *, amount: int, blinding: bytes) -> bytes:
        raise NotImplementedError(self._DIAGNOSTIC)

    def verify_balance(
        self,
        *,
        input_commitments: list[bytes],
        output_commitments: list[bytes],
    ) -> bool:
        raise NotImplementedError(self._DIAGNOSTIC)

    def range_proof(
        self,
        *,
        amount: int,
        blinding: bytes,
        max_bits: int = 64,
    ) -> bytes:
        raise NotImplementedError(self._DIAGNOSTIC)

    def verify_range_proof(
        self,
        *,
        commitment: bytes,
        proof: bytes,
        max_bits: int = 64,
    ) -> bool:
        raise NotImplementedError(self._DIAGNOSTIC)

    def status(self) -> PrivacyPrimitiveStatus:
        return PrivacyPrimitiveStatus.NOT_IMPLEMENTED


__all__ = ["ShieldedBalanceScaffolding"]
