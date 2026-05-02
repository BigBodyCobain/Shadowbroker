"""Decentralized exchange — Sprint 11+ scaffolding.

Source of truth: ``infonet-economy/IMPLEMENTATION_PLAN.md`` §4.3,
§6.4 (open: same chain vs side-chain).

The DEX operates on top of the shielded coin layer. Orders reference
shielded inputs and outputs; settlement burns + mints commitments
atomically. The Sprint 11+ scaffolding here defines the order /
settlement shapes without committing to a specific matching scheme
(CoW-style batch auction, atomic swap, etc.).

External exchanges WILL list CommonCoin regardless of protocol
design — the protocol's privacy layer is what prevents external-
exchange listings from de-anonymizing protocol participants. The
on-chain DEX is the *primary* exchange mechanism, not the only one.
"""

from __future__ import annotations

from typing import Any

from services.infonet.privacy.contracts import PrivacyPrimitiveStatus


class DEXScaffolding:
    """Placeholder until the DEX scheme decision (§6.4) is made and a
    matching engine is built on top of the shielded coin layer."""

    _DIAGNOSTIC = (
        "DEX is scaffolding only — see IMPLEMENTATION_PLAN.md §6.4 "
        "for the open scheme decision (same chain vs side-chain) and "
        "§4.3 for the privacy requirements. Production implementation "
        "depends on the shielded coin layer being shipped first."
    )

    def place_order(self, *, order: dict[str, Any]) -> str:
        raise NotImplementedError(self._DIAGNOSTIC)

    def cancel_order(self, *, order_id: str, owner_signature: bytes) -> None:
        raise NotImplementedError(self._DIAGNOSTIC)

    def match_orders(self) -> list[dict[str, Any]]:
        raise NotImplementedError(self._DIAGNOSTIC)

    def status(self) -> PrivacyPrimitiveStatus:
        return PrivacyPrimitiveStatus.NOT_IMPLEMENTED


__all__ = ["DEXScaffolding"]
