"""Two-phase commit receipts + enumerated denial codes.

Source of truth: ``infonet-economy/IMPLEMENTATION_PLAN.md`` §4.4
pieces 5-6.

Two phases per redemption:

1. **Verification receipt** (operator → citizen). Operator signs:
   ``(receipt_id, operator_id, day_bucket, nullifier_prefix)``.
   Note: NO timestamp (day-bucket only), NO node_id, NO nullifier
   in full (a prefix that's still distinct enough for fraud auditing
   but doesn't leak the full unforgeable nullifier).

2. **Fulfillment receipt** (citizen → operator). Citizen counter-
   signs the verification receipt after service is rendered. Both
   parties hold a copy.

Receipts are NEVER published on-chain. They surface only in
disputes. Settlement to chain happens through batched aggregation
(``batched_settlement.py``).

Denial codes are an **enumerated** set with exactly three values.
Operators cannot reject for freeform reasons — that would be a
discrimination vector. The three reasons are:

- ``INVALID_SIGNATURE`` — challenge-response verification failed.
- ``NULLIFIER_ALREADY_SEEN`` — the (key, operator) pair has already
  redeemed once.
- ``RATE_LIMIT_EXCEEDED`` — operator-defined throttle (per-day,
  per-hour, etc.) prevents this redemption.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class DenialCode(str, Enum):
    """Enumerated rejection reasons. Adding a new code is a hard fork."""
    INVALID_SIGNATURE = "invalid_signature"
    NULLIFIER_ALREADY_SEEN = "nullifier_already_seen"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"


def _day_bucket(timestamp: float) -> str:
    """Return the UTC day in ``YYYY-MM-DD`` form for ``timestamp``.

    Day-level granularity prevents fine-grained timestamp metadata
    from becoming a de-anonymization vector. An operator that issued
    100 receipts on the same day cannot link them by timestamp —
    they all carry the same day_bucket.
    """
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d")


@dataclass(frozen=True)
class Receipt:
    """One side of the two-phase commit.

    ``role`` is either ``"verification"`` (Phase 1, operator-signed)
    or ``"fulfillment"`` (Phase 2, citizen counter-signed).
    """
    role: str
    receipt_id: str
    operator_id: str
    day_bucket: str
    nullifier_prefix: str
    signature: bytes


@dataclass(frozen=True)
class ReceiptPair:
    """Both phases of a successful redemption.

    Held by both citizen and operator. Surfaces only on dispute —
    the chain never sees these.
    """
    verification: Receipt
    fulfillment: Receipt


def _sign(secret: bytes, body: bytes) -> bytes:
    return hmac.new(secret, body, hashlib.sha256).digest()


def _verify(secret: bytes, body: bytes, signature: bytes) -> bool:
    expected = _sign(secret, body)
    return hmac.compare_digest(expected, signature)


def _receipt_body(*, role: str, receipt_id: str, operator_id: str,
                  day_bucket: str, nullifier_prefix: str) -> bytes:
    return b"|".join([
        b"function_key_receipt",
        role.encode("utf-8"),
        receipt_id.encode("utf-8"),
        operator_id.encode("utf-8"),
        day_bucket.encode("utf-8"),
        nullifier_prefix.encode("utf-8"),
    ])


def issue_verification_receipt(
    *,
    operator_id: str,
    operator_secret: bytes,
    nullifier: str,
    timestamp: float,
    receipt_id: str | None = None,
    nullifier_prefix_len: int = 8,
) -> Receipt:
    """Operator-side: issue a Phase-1 verification receipt.

    ``nullifier_prefix`` is the first ``nullifier_prefix_len`` hex
    chars of the full nullifier — enough for the operator to dispute
    later (fraud auditing) but NOT enough to identify the citizen
    cross-operator. 8 hex chars = 32 bits = ~4 billion possible
    prefixes, statistically unlinkable across operators.
    """
    if not isinstance(nullifier, str) or len(nullifier) < nullifier_prefix_len:
        raise ValueError("nullifier must be a hex string of sufficient length")
    rid = receipt_id or secrets.token_hex(16)
    prefix = nullifier[:nullifier_prefix_len]
    day = _day_bucket(timestamp)
    body = _receipt_body(
        role="verification", receipt_id=rid, operator_id=operator_id,
        day_bucket=day, nullifier_prefix=prefix,
    )
    sig = _sign(operator_secret, body)
    return Receipt(
        role="verification",
        receipt_id=rid,
        operator_id=operator_id,
        day_bucket=day,
        nullifier_prefix=prefix,
        signature=sig,
    )


def counter_sign_fulfillment(
    *,
    verification: Receipt,
    citizen_secret: bytes,
) -> Receipt:
    """Citizen-side: counter-sign a verification receipt to acknowledge
    service rendered.

    The fulfillment receipt has the same field values as the
    verification receipt (linking them to the same redemption) but
    is signed with the CITIZEN's secret instead of the operator's.
    Together they form a ``ReceiptPair``.
    """
    if verification.role != "verification":
        raise ValueError("input must be a Phase-1 verification receipt")
    body = _receipt_body(
        role="fulfillment", receipt_id=verification.receipt_id,
        operator_id=verification.operator_id, day_bucket=verification.day_bucket,
        nullifier_prefix=verification.nullifier_prefix,
    )
    sig = _sign(citizen_secret, body)
    return Receipt(
        role="fulfillment",
        receipt_id=verification.receipt_id,
        operator_id=verification.operator_id,
        day_bucket=verification.day_bucket,
        nullifier_prefix=verification.nullifier_prefix,
        signature=sig,
    )


def verify_receipt_pair(
    *,
    pair: ReceiptPair,
    operator_secret: bytes,
    citizen_secret: bytes,
) -> bool:
    """Verify both signatures on a ``ReceiptPair``.

    Useful in dispute resolution — both parties can independently
    confirm the pair is genuine.
    """
    if pair.verification.role != "verification":
        return False
    if pair.fulfillment.role != "fulfillment":
        return False
    if pair.verification.receipt_id != pair.fulfillment.receipt_id:
        return False
    if pair.verification.operator_id != pair.fulfillment.operator_id:
        return False
    v_body = _receipt_body(
        role="verification", receipt_id=pair.verification.receipt_id,
        operator_id=pair.verification.operator_id,
        day_bucket=pair.verification.day_bucket,
        nullifier_prefix=pair.verification.nullifier_prefix,
    )
    if not _verify(operator_secret, v_body, pair.verification.signature):
        return False
    f_body = _receipt_body(
        role="fulfillment", receipt_id=pair.fulfillment.receipt_id,
        operator_id=pair.fulfillment.operator_id,
        day_bucket=pair.fulfillment.day_bucket,
        nullifier_prefix=pair.fulfillment.nullifier_prefix,
    )
    if not _verify(citizen_secret, f_body, pair.fulfillment.signature):
        return False
    return True


__all__ = [
    "DenialCode",
    "Receipt",
    "ReceiptPair",
    "counter_sign_fulfillment",
    "issue_verification_receipt",
    "verify_receipt_pair",
]
