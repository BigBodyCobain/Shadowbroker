"""Batched settlement — aggregate counts, no individual records on-chain.

Source of truth: ``infonet-economy/IMPLEMENTATION_PLAN.md`` §4.4
piece 6.

Per-redemption records on-chain would be a privacy disaster: an
observer could correlate "Operator X verified a Function Key at
14:32" with a citizen's known activities to de-anonymize them.

Instead, operators settle in **aggregate**. The chain sees only
``(operator_id, day_bucket, count)`` — verified N keys this day.
Fraud detection happens via statistical auditing rather than
per-redemption traces:

- Operator's count vs their declared population (food bank that
  reports 10,000 daily verifications when their service capacity
  is 200).
- Distribution shape vs other operators (significant outliers
  prompt review).
- Spot audits via dispute mechanism (citizen + operator surface
  receipt pair to adjudicator).

The ``BatchedSettlementBatch`` here is what the operator emits
to chain at the end of a settlement period. Receipts NEVER appear
on-chain — they remain off-chain with both parties.

Sprint 11+ scaffolding ships:

- The aggregate batch dataclass.
- A ``record_redemption`` helper that operators call locally per
  successful redemption — increments the batch's counter without
  storing the receipt.
- A ``finalize_batch`` step that produces the on-chain payload.

This module is **fully implementable** today — it does no
cryptography, just bookkeeping.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BatchedSettlementBatch:
    """Operator-side batch counter for one settlement period.

    Operators construct one of these per ``(period_id, operator_id)``
    pair, increment via ``record_redemption`` per successful
    redemption, and emit the finalized batch payload at period end.

    The data model is intentionally minimal:

    - ``period_id`` — the settlement window identifier (e.g.
      ``"2026-04"`` for monthly).
    - ``operator_id`` — committed publicly on-chain so its
      non-forgeability is anchored.
    - ``successful_count`` — number of successful redemptions
      (verification + fulfillment).
    - ``denial_counts`` — counts per enumerated DenialCode for
      audit visibility. NO per-receipt detail.
    """

    period_id: str
    operator_id: str
    successful_count: int = 0
    denial_counts: dict[str, int] = field(default_factory=dict)
    finalized: bool = False

    def record_redemption(self) -> None:
        """Increment the success counter. NOT idempotent — call
        exactly once per successful (verification, fulfillment)
        receipt pair the operator commits to."""
        if self.finalized:
            raise RuntimeError("batch already finalized; cannot record")
        self.successful_count += 1

    def record_denial(self, code: str) -> None:
        """Track a denial. Operators MUST use one of the enumerated
        ``DenialCode`` values — Sprint 11+ scaffolding accepts the
        string for convenience but production callers should pass
        the enum's ``.value``."""
        if self.finalized:
            raise RuntimeError("batch already finalized; cannot record")
        if not isinstance(code, str) or not code:
            raise ValueError("denial code must be a non-empty string")
        self.denial_counts[code] = self.denial_counts.get(code, 0) + 1

    def finalize(self) -> dict:
        """Produce the on-chain payload for this batch.

        After ``finalize()``, ``record_redemption`` and
        ``record_denial`` raise. The returned dict is the canonical
        batched-settlement event payload.

        Privacy property: per-receipt detail is NOT in the output.
        Only counts. The operator may discard receipts after
        finalization (subject to local retention policy for dispute
        defense).
        """
        if self.finalized:
            raise RuntimeError("batch already finalized")
        self.finalized = True
        return {
            "period_id": self.period_id,
            "operator_id": self.operator_id,
            "successful_count": int(self.successful_count),
            "denial_counts": {k: int(v) for k, v in self.denial_counts.items()},
        }


__all__ = ["BatchedSettlementBatch"]
