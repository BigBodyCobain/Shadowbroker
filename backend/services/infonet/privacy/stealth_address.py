"""Stealth addresses — Sprint 11+ scaffolding.

Source of truth: ``infonet-economy/IMPLEMENTATION_PLAN.md`` §4.3.

Each transaction generates a fresh one-time recipient address
unlinkable from the recipient's published key. The recipient uses a
private *view key* to scan the chain and identify outputs intended
for them.

Standard scheme (Monero-style, dual-key):

- Recipient publishes ``(view_pub, spend_pub)``.
- Sender generates random ``r``, computes
  ``one_time_address = H(r * view_pub) * G + spend_pub``.
- Recipient scans chain by checking if
  ``H(view_priv * R) * G + spend_pub == one_time_address`` for each
  output's ``R = r * G``.

Production implementation lands through the ``StealthAddressScheme``
Protocol when the Rust binding is ready. Today, this module ships a
``StealthAddressScaffolding`` placeholder that reports
``NOT_IMPLEMENTED``.
"""

from __future__ import annotations

from services.infonet.privacy.contracts import PrivacyPrimitiveStatus


class StealthAddressScaffolding:
    """Placeholder until the Rust stealth-address binding lands."""

    _DIAGNOSTIC = (
        "Stealth address primitive is scaffolding only — see "
        "infonet-economy/IMPLEMENTATION_PLAN.md §4.3 for the design. "
        "Production implementation lands via privacy-core Rust crate."
    )

    def derive_one_time_address(
        self,
        *,
        recipient_view_key: bytes,
        recipient_spend_key: bytes,
        sender_random: bytes,
    ) -> bytes:
        raise NotImplementedError(self._DIAGNOSTIC)

    def is_for_recipient(
        self,
        *,
        one_time_address: bytes,
        recipient_view_key: bytes,
        recipient_spend_key: bytes,
        sender_random: bytes,
    ) -> bool:
        raise NotImplementedError(self._DIAGNOSTIC)

    def status(self) -> PrivacyPrimitiveStatus:
        return PrivacyPrimitiveStatus.NOT_IMPLEMENTED


__all__ = ["StealthAddressScaffolding"]
