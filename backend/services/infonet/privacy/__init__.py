"""Privacy layer scaffolding (Sprint 11+ runway).

The privacy layer protects the protocol's core promise:
**your identity is your reputation, not your legal name**.

Constitutional anchors (IMPLEMENTATION_PLAN.md §4):

- **Reputation chain is fully public.** Every uprep / prediction /
  vote / governance action is signed and visible. The privacy layer
  does NOT hide reputation actions.
- **Coin ledger is privacy-preserving.** When the coin layer ships,
  transfers / balances / DEX trades are shielded. Privacy work in
  this folder is what makes that possible.
- **Optional privacy is no privacy.** The default for coin
  transactions must be shielded — opt-out cannot exist or it
  destroys the anonymity set.

This package is intentionally **scaffolding only** at present. Each
primitive (RingCT, stealth addresses, shielded balance commitments,
DEX) defines its public interface as a typed Protocol so production
code can depend on the *shape* before any specific cryptographic
implementation is committed.

The non-cryptographic pieces of the Function Keys design (nullifier
hashing, challenge-response orchestration, two-phase commit receipts,
batched settlement aggregation) ARE implemented here in pure Python.
The remaining cryptographic primitive (blind signature / anonymous
credential scheme) is the only piece blocking production deployment
of Function Keys; everything around it is ready.

See ``infonet-economy/IMPLEMENTATION_PLAN.md`` §4 and
``infonet-economy/BRAINDUMP.md`` §5.6, §11 item 9 for design
rationale.
"""

from services.infonet.privacy.contracts import (
    BalanceCommitment,
    DEXOrderBook,
    PrivacyPrimitiveStatus,
    RingSignatureScheme,
    StealthAddressScheme,
)
from services.infonet.privacy.dex import DEXScaffolding
from services.infonet.privacy.function_keys import (
    BatchedSettlementBatch,
    DenialCode,
    FunctionKey,
    FunctionKeyChallenge,
    FunctionKeyResponse,
    NullifierTracker,
    Receipt,
    ReceiptPair,
    derive_nullifier,
    issue_challenge,
    sign_response,
    verify_response,
)
from services.infonet.privacy.ringct import RingCTScaffolding
from services.infonet.privacy.shielded_balance import ShieldedBalanceScaffolding
from services.infonet.privacy.stealth_address import StealthAddressScaffolding

__all__ = [
    "BalanceCommitment",
    "BatchedSettlementBatch",
    "DEXOrderBook",
    "DEXScaffolding",
    "DenialCode",
    "FunctionKey",
    "FunctionKeyChallenge",
    "FunctionKeyResponse",
    "NullifierTracker",
    "PrivacyPrimitiveStatus",
    "Receipt",
    "ReceiptPair",
    "RingCTScaffolding",
    "RingSignatureScheme",
    "ShieldedBalanceScaffolding",
    "StealthAddressScaffolding",
    "StealthAddressScheme",
    "derive_nullifier",
    "issue_challenge",
    "sign_response",
    "verify_response",
]
