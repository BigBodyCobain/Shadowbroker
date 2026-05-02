"""Ring Confidential Transactions — Sprint 11+ scaffolding.

Source of truth: ``infonet-economy/IMPLEMENTATION_PLAN.md`` §4.3,
``infonet-economy/BRAINDUMP.md`` §11 item 9.

RingCT combines:

1. **Ring signatures** — hide *who* signed within an anonymity set.
2. **Confidential transactions** — Pedersen commitments hide
   *amounts*. A range proof confirms the amount is non-negative.
3. **Key images** — link two outputs spent by the same key (without
   revealing which key). Prevents double-spend without breaking
   anonymity.

Implementation scheme is **undecided** — IMPLEMENTATION_PLAN.md §6.4
calls out RingCT vs CONFIDENTIAL_TX vs MimbleWimble vs ZK-SNARK as
options. The scaffolding here is scheme-agnostic; production wires
in whichever scheme the architect chooses through the
``RingSignatureScheme`` and ``BalanceCommitment`` Protocols.

Sprint 11+ runway:

- The interface contract is locked (see ``contracts.py``).
- A ``RingCTScaffolding`` placeholder reports
  ``status=NOT_IMPLEMENTED`` so callers can introspect honestly.
- When the Rust binding lands, instantiate it via the same Protocol
  shape and swap the scaffolding for the production class — no
  caller changes needed.

Cross-cutting design rule: privacy primitives MUST report their
status truthfully (cross-cutting design rule #1 — non-hostile UX).
A primitive that's not implemented surfaces clearly via the status
endpoint; calling its operations raises ``NotImplementedError`` with
a pointer back to the open issue.
"""

from __future__ import annotations

from typing import Any

from services.infonet.privacy.contracts import PrivacyPrimitiveStatus


class RingCTScaffolding:
    """Placeholder until the Rust ring-signature binding lands.

    Calling ``sign`` / ``verify`` raises with a diagnostic that
    points the caller back to the design doc. The status method
    truthfully reports ``NOT_IMPLEMENTED`` so health endpoints can
    surface this state.
    """

    _DIAGNOSTIC = (
        "RingCT primitive is scaffolding only — see "
        "infonet-economy/IMPLEMENTATION_PLAN.md §6.4 for the open "
        "scheme decision (RingCT vs CONFIDENTIAL_TX vs MimbleWimble "
        "vs ZK-SNARK). Production implementation lands via "
        "privacy-core Rust crate when ready."
    )

    def sign(
        self,
        *,
        message: bytes,
        signer_private_key: bytes,
        ring_public_keys: list[bytes],
    ) -> dict[str, Any]:
        raise NotImplementedError(self._DIAGNOSTIC)

    def verify(
        self,
        *,
        message: bytes,
        signature: dict[str, Any],
        ring_public_keys: list[bytes],
    ) -> bool:
        raise NotImplementedError(self._DIAGNOSTIC)

    def status(self) -> PrivacyPrimitiveStatus:
        return PrivacyPrimitiveStatus.NOT_IMPLEMENTED


__all__ = ["RingCTScaffolding"]
