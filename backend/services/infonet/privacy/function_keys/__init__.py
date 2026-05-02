"""Function Keys — anonymous citizenship proof.

Source of truth: ``infonet-economy/IMPLEMENTATION_PLAN.md`` §4.4,
``infonet-economy/BRAINDUMP.md`` §11 item 9.

A citizen should be able to prove "I am a UBI-eligible Infonet
citizen" to a real-world operator (food bank, community service)
**without revealing their Infonet identity**. The naive approach
(scramble a public key, record each redemption on chain) leaks
identity through metadata correlation (time, location, operator,
frequency).

The full design has six pieces; five are implemented in pure Python
here. The remaining piece — issuance via blind signatures or
anonymous credentials — is the only cryptographic primitive that
needs an external library.

Pieces:

1. **Issuance** (NOT IMPLEMENTED — needs blind sig / BBS+ / U-Prove
   / Idemix). The ``FunctionKey`` dataclass models what an issued
   key looks like; production wires the issuer through a Protocol
   when the scheme is chosen.
2. **Nullifiers** (`nullifier.py`) — SHA-256 of secret + operator_id.
   Different operators see different nullifiers for the same key,
   so cross-operator linkage is impossible. One-time-use per
   operator: tracked via ``NullifierTracker``.
3. **Challenge-response** (`challenge_response.py`) — operator
   issues a fresh nonce, key-holder signs with the Function Key's
   secret. Prevents screenshot attacks, key sharing, replay.
4. **Two-phase commit receipts** (`receipt.py`) — Phase 1
   verification receipt (operator-signed, day-level date NOT
   timestamp, no node_id). Phase 2 fulfillment receipt (citizen
   counter-signs after service rendered). Receipts NEVER published
   on-chain — only surface on dispute.
5. **Enumerated denial codes** (`receipt.py`) — operators can
   reject for exactly three reasons: invalid signature, nullifier
   already seen, rate limit exceeded. Prevents discrimination via
   freeform rejection.
6. **Batched/coarse-grained settlement** (`batched_settlement.py`)
   — operators settle in aggregate. Chain sees "Operator X
   verified N function keys this period." Per-redemption records
   never reach the chain.

Cross-cutting design rule: the user redeeming a Function Key must
not be blocked by privacy/security mechanics. If the cryptographic
primitive is unavailable in the local node, the redemption is
queued for retry once the operator has connectivity, NOT refused.
"""

from services.infonet.privacy.function_keys.batched_settlement import (
    BatchedSettlementBatch,
)
from services.infonet.privacy.function_keys.challenge_response import (
    FunctionKey,
    FunctionKeyChallenge,
    FunctionKeyResponse,
    issue_challenge,
    sign_response,
    verify_response,
)
from services.infonet.privacy.function_keys.nullifier import (
    NullifierTracker,
    derive_nullifier,
)
from services.infonet.privacy.function_keys.receipt import (
    DenialCode,
    Receipt,
    ReceiptPair,
)

__all__ = [
    "BatchedSettlementBatch",
    "DenialCode",
    "FunctionKey",
    "FunctionKeyChallenge",
    "FunctionKeyResponse",
    "NullifierTracker",
    "Receipt",
    "ReceiptPair",
    "derive_nullifier",
    "issue_challenge",
    "sign_response",
    "verify_response",
]
