"""Privacy scaffolding tests.

The cryptographic primitives (RingCT, stealth, shielded balance,
DEX) are scaffolding only — they expose typed interfaces and report
status truthfully. The Function Keys non-crypto pieces (nullifier,
challenge-response, receipt, batched settlement) are fully
implemented and adversarial-tested here.
"""

from __future__ import annotations

import pytest

from services.infonet.privacy import (
    BatchedSettlementBatch,
    DenialCode,
    DEXScaffolding,
    FunctionKey,
    NullifierTracker,
    PrivacyPrimitiveStatus,
    RingCTScaffolding,
    ShieldedBalanceScaffolding,
    StealthAddressScaffolding,
    derive_nullifier,
    issue_challenge,
    sign_response,
    verify_response,
)
from services.infonet.privacy.function_keys.receipt import (
    Receipt,
    ReceiptPair,
    counter_sign_fulfillment,
    issue_verification_receipt,
    verify_receipt_pair,
)


# ── Scaffolding stubs report NOT_IMPLEMENTED ────────────────────────────

def test_ringct_scaffolding_reports_not_implemented():
    rc = RingCTScaffolding()
    assert rc.status() == PrivacyPrimitiveStatus.NOT_IMPLEMENTED


def test_stealth_address_scaffolding_reports_not_implemented():
    sa = StealthAddressScaffolding()
    assert sa.status() == PrivacyPrimitiveStatus.NOT_IMPLEMENTED


def test_shielded_balance_scaffolding_reports_not_implemented():
    sb = ShieldedBalanceScaffolding()
    assert sb.status() == PrivacyPrimitiveStatus.NOT_IMPLEMENTED


def test_dex_scaffolding_reports_not_implemented():
    dx = DEXScaffolding()
    assert dx.status() == PrivacyPrimitiveStatus.NOT_IMPLEMENTED


def test_scaffolding_methods_raise_with_diagnostic():
    """Calling an unimplemented method raises NotImplementedError
    with a diagnostic that points to the design doc."""
    rc = RingCTScaffolding()
    with pytest.raises(NotImplementedError, match="IMPLEMENTATION_PLAN"):
        rc.sign(message=b"x", signer_private_key=b"k", ring_public_keys=[b"a", b"b"])


# ── Nullifier ───────────────────────────────────────────────────────────

def test_nullifier_is_deterministic():
    secret = b"my-secret-key"
    n1 = derive_nullifier(secret=secret, operator_id="food-bank-1")
    n2 = derive_nullifier(secret=secret, operator_id="food-bank-1")
    assert n1 == n2
    assert len(n1) == 64  # SHA-256 hex


def test_different_operators_produce_different_nullifiers_for_same_secret():
    """The cross-operator-unlinkability property: the same Function
    Key used at two different operators produces two unrelated
    nullifiers. Operators sharing notes cannot link them."""
    secret = b"my-secret-key"
    n_a = derive_nullifier(secret=secret, operator_id="food-bank-A")
    n_b = derive_nullifier(secret=secret, operator_id="food-bank-B")
    assert n_a != n_b


def test_different_secrets_produce_different_nullifiers_for_same_operator():
    n_alice = derive_nullifier(secret=b"alice-secret", operator_id="op")
    n_bob = derive_nullifier(secret=b"bob-secret", operator_id="op")
    assert n_alice != n_bob


def test_nullifier_rejects_invalid_inputs():
    with pytest.raises(TypeError):
        derive_nullifier(secret="string-not-bytes", operator_id="op")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        derive_nullifier(secret=b"x", operator_id="")


def test_nullifier_tracker_one_time_use():
    tracker = NullifierTracker()
    n = derive_nullifier(secret=b"x", operator_id="op-1")
    assert tracker.check_and_record(n) is True
    # Second use of the same nullifier must be rejected.
    assert tracker.check_and_record(n) is False
    assert tracker.has_seen(n)


def test_nullifier_tracker_distinct_nullifiers_independent():
    tracker = NullifierTracker()
    n1 = derive_nullifier(secret=b"x", operator_id="op-1")
    n2 = derive_nullifier(secret=b"y", operator_id="op-1")
    assert tracker.check_and_record(n1) is True
    assert tracker.check_and_record(n2) is True


# ── Challenge-response ──────────────────────────────────────────────────

def test_challenge_response_round_trip_succeeds():
    key = FunctionKey(
        secret=b"alice-secret-32-bytes-padded--xx",
        epoch="2026-04",
        credential=b"issuer-sig",
    )
    challenge = issue_challenge(operator_id="food-bank-1", now=1000.0)
    response = sign_response(key=key, challenge=challenge)
    ok, reason = verify_response(response=response, key=key, now=1000.5)
    assert ok
    assert reason == "ok"


def test_response_with_wrong_key_rejected():
    real_key = FunctionKey(secret=b"real", epoch="2026-04", credential=b"")
    fake_key = FunctionKey(secret=b"fake", epoch="2026-04", credential=b"")
    challenge = issue_challenge(operator_id="op", now=1000.0)
    response = sign_response(key=real_key, challenge=challenge)
    ok, reason = verify_response(response=response, key=fake_key, now=1000.5)
    assert not ok
    assert reason == "invalid_mac"


def test_stale_challenge_rejected():
    key = FunctionKey(secret=b"x", epoch="2026-04", credential=b"")
    challenge = issue_challenge(operator_id="op", now=1000.0)
    response = sign_response(key=key, challenge=challenge)
    ok, reason = verify_response(response=response, key=key, now=999_999.0)
    assert not ok
    assert reason == "stale_challenge"


def test_replay_attack_rejected():
    key = FunctionKey(secret=b"x", epoch="2026-04", credential=b"")
    challenge = issue_challenge(operator_id="op", now=1000.0)
    response = sign_response(key=key, challenge=challenge)
    # Operator records the nonce after first verification.
    seen_nonces = {response.nonce}
    ok, reason = verify_response(response=response, key=key,
                                  now=1000.5, seen_nonces=seen_nonces)
    assert not ok
    assert reason == "replay_nonce_seen"


def test_challenge_carries_nullifier_for_operator_lookup():
    """The signed response includes the nullifier so the operator can
    one-time-check it against the tracker before emitting a receipt."""
    key = FunctionKey(secret=b"x", epoch="2026-04", credential=b"")
    challenge = issue_challenge(operator_id="op", now=1000.0)
    response = sign_response(key=key, challenge=challenge)
    expected = derive_nullifier(secret=b"x", operator_id="op")
    assert response.nullifier == expected


def test_two_challenges_have_distinct_nonces():
    a = issue_challenge(operator_id="op", now=1000.0)
    b = issue_challenge(operator_id="op", now=1001.0)
    assert a.nonce != b.nonce  # 256-bit entropy — collision impossible


# ── Receipt (two-phase commit) ──────────────────────────────────────────

def test_receipt_pair_round_trip():
    operator_secret = b"operator-secret"
    citizen_secret = b"citizen-secret"
    nullifier = derive_nullifier(secret=citizen_secret, operator_id="op")

    v = issue_verification_receipt(
        operator_id="op", operator_secret=operator_secret,
        nullifier=nullifier, timestamp=1_700_000_000.0,
    )
    f = counter_sign_fulfillment(verification=v, citizen_secret=citizen_secret)
    pair = ReceiptPair(verification=v, fulfillment=f)
    assert verify_receipt_pair(
        pair=pair, operator_secret=operator_secret, citizen_secret=citizen_secret,
    )


def test_receipt_uses_day_bucket_not_timestamp():
    """Receipts contain only ``YYYY-MM-DD``, not full timestamps —
    prevents fine-grained metadata leakage."""
    v = issue_verification_receipt(
        operator_id="op", operator_secret=b"s",
        nullifier="0" * 64, timestamp=1_700_000_000.0,  # 2023-11-14
    )
    assert v.day_bucket == "2023-11-14"
    assert "T" not in v.day_bucket  # not an ISO timestamp


def test_receipt_only_includes_nullifier_prefix():
    """Full nullifier never appears in the receipt — only a prefix
    sufficient for fraud auditing."""
    v = issue_verification_receipt(
        operator_id="op", operator_secret=b"s",
        nullifier="abcdef0123456789" * 4,
        timestamp=1_700_000_000.0,
        nullifier_prefix_len=8,
    )
    assert v.nullifier_prefix == "abcdef01"
    assert len(v.nullifier_prefix) == 8


def test_receipt_pair_with_tampered_signature_rejected():
    operator_secret = b"operator"
    citizen_secret = b"citizen"
    nullifier = derive_nullifier(secret=citizen_secret, operator_id="op")
    v = issue_verification_receipt(
        operator_id="op", operator_secret=operator_secret,
        nullifier=nullifier, timestamp=1_700_000_000.0,
    )
    f = counter_sign_fulfillment(verification=v, citizen_secret=citizen_secret)
    # Replace the operator's signature with garbage.
    tampered_v = Receipt(
        role=v.role, receipt_id=v.receipt_id,
        operator_id=v.operator_id, day_bucket=v.day_bucket,
        nullifier_prefix=v.nullifier_prefix, signature=b"\x00" * 32,
    )
    assert not verify_receipt_pair(
        pair=ReceiptPair(verification=tampered_v, fulfillment=f),
        operator_secret=operator_secret, citizen_secret=citizen_secret,
    )


def test_receipt_with_mismatched_role_rejected():
    """A "fulfillment" passed as the verification slot fails."""
    operator_secret = b"operator"
    citizen_secret = b"citizen"
    nullifier = derive_nullifier(secret=citizen_secret, operator_id="op")
    v = issue_verification_receipt(
        operator_id="op", operator_secret=operator_secret,
        nullifier=nullifier, timestamp=1_700_000_000.0,
    )
    f = counter_sign_fulfillment(verification=v, citizen_secret=citizen_secret)
    swapped = ReceiptPair(verification=f, fulfillment=v)  # roles flipped
    assert not verify_receipt_pair(
        pair=swapped, operator_secret=operator_secret, citizen_secret=citizen_secret,
    )


# ── Denial codes ────────────────────────────────────────────────────────

def test_denial_codes_are_enumerated():
    """Exactly three reasons. New denial reasons require a hard fork."""
    assert {c.value for c in DenialCode} == {
        "invalid_signature",
        "nullifier_already_seen",
        "rate_limit_exceeded",
    }


# ── Batched settlement ──────────────────────────────────────────────────

def test_batched_settlement_aggregates_counts_only():
    """Per-redemption details NEVER appear in the on-chain payload."""
    batch = BatchedSettlementBatch(period_id="2026-04", operator_id="op-1")
    for _ in range(50):
        batch.record_redemption()
    batch.record_denial(DenialCode.NULLIFIER_ALREADY_SEEN.value)
    batch.record_denial(DenialCode.RATE_LIMIT_EXCEEDED.value)
    payload = batch.finalize()
    assert payload == {
        "period_id": "2026-04",
        "operator_id": "op-1",
        "successful_count": 50,
        "denial_counts": {
            "nullifier_already_seen": 1,
            "rate_limit_exceeded": 1,
        },
    }
    # Critical privacy property: no per-receipt detail.
    assert "receipts" not in payload
    assert "nullifiers" not in payload
    assert "timestamps" not in payload


def test_batch_cannot_record_after_finalize():
    batch = BatchedSettlementBatch(period_id="2026-04", operator_id="op-1")
    batch.record_redemption()
    batch.finalize()
    with pytest.raises(RuntimeError):
        batch.record_redemption()
    with pytest.raises(RuntimeError):
        batch.record_denial(DenialCode.INVALID_SIGNATURE.value)


def test_batch_double_finalize_rejected():
    batch = BatchedSettlementBatch(period_id="2026-04", operator_id="op-1")
    batch.finalize()
    with pytest.raises(RuntimeError):
        batch.finalize()


# ── End-to-end Function Keys flow ───────────────────────────────────────

def test_full_redemption_flow_one_time_use_per_operator():
    """End-to-end: citizen has a Function Key, operator issues a
    challenge, citizen signs, operator verifies, derives nullifier,
    checks tracker, issues verification receipt, citizen counter-
    signs, operator increments batch counter.

    A second redemption by the same key at the same operator MUST be
    rejected by the nullifier tracker."""
    citizen_secret = b"alice-secret-32-bytes-padded--xx"
    key = FunctionKey(secret=citizen_secret, epoch="2026-04",
                      credential=b"issuer-credential")

    operator_id = "food-bank-1"
    operator_secret = b"operator-private-key"
    tracker = NullifierTracker()
    batch = BatchedSettlementBatch(period_id="2026-04", operator_id=operator_id)

    # First redemption succeeds.
    challenge = issue_challenge(operator_id=operator_id, now=1_700_000_000.0)
    response = sign_response(key=key, challenge=challenge)
    ok, _ = verify_response(response=response, key=key, now=1_700_000_001.0)
    assert ok

    nullifier_unseen = tracker.check_and_record(response.nullifier)
    assert nullifier_unseen
    v = issue_verification_receipt(
        operator_id=operator_id, operator_secret=operator_secret,
        nullifier=response.nullifier, timestamp=1_700_000_001.0,
    )
    f = counter_sign_fulfillment(verification=v, citizen_secret=citizen_secret)
    pair = ReceiptPair(verification=v, fulfillment=f)
    assert verify_receipt_pair(pair=pair,
                               operator_secret=operator_secret,
                               citizen_secret=citizen_secret)
    batch.record_redemption()

    # Second redemption — same key, same operator — rejected at the
    # nullifier-tracker stage.
    challenge2 = issue_challenge(operator_id=operator_id, now=1_700_000_100.0)
    response2 = sign_response(key=key, challenge=challenge2)
    ok2, _ = verify_response(response=response2, key=key, now=1_700_000_101.0)
    assert ok2  # signature is valid
    nullifier_repeat = tracker.check_and_record(response2.nullifier)
    assert not nullifier_repeat  # but operator rejects via tracker
    batch.record_denial(DenialCode.NULLIFIER_ALREADY_SEEN.value)

    payload = batch.finalize()
    assert payload["successful_count"] == 1
    assert payload["denial_counts"]["nullifier_already_seen"] == 1


def test_same_key_at_different_operators_succeeds_twice():
    """Cross-operator unlinkability: a citizen can use the same key
    at TWO different operators, and neither nullifier tracker can
    detect it."""
    citizen_secret = b"alice-secret"
    key = FunctionKey(secret=citizen_secret, epoch="2026-04", credential=b"")

    tracker_a = NullifierTracker()
    tracker_b = NullifierTracker()

    n_a = derive_nullifier(secret=citizen_secret, operator_id="op-A")
    n_b = derive_nullifier(secret=citizen_secret, operator_id="op-B")
    assert n_a != n_b

    assert tracker_a.check_and_record(n_a)
    assert tracker_b.check_and_record(n_b)
    # Cross-tracker checks: tracker_a doesn't know about n_b and
    # vice versa. They cannot link the two redemptions.
    assert not tracker_a.has_seen(n_b)
    assert not tracker_b.has_seen(n_a)
