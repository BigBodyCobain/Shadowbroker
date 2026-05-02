"""Challenge-response — live proof of Function Key possession.

Source of truth: ``infonet-economy/IMPLEMENTATION_PLAN.md`` §4.4
piece 3.

Operator issues a fresh nonce; key-holder signs (challenge || nonce
|| epoch_window) with the Function Key's secret. Operator verifies
by re-deriving the signature.

This defends against:

- **Screenshot attacks** — a recorded "valid proof" from yesterday
  is useless against today's challenge.
- **Key sharing** — without the live secret, no valid response
  exists; sharing the secret = sharing the key (which has its own
  social cost via public reputation).
- **Replay** — the operator stores recent nonces; replayed
  responses are rejected.

Sprint 11+ scaffolding ships:

- The ``FunctionKey`` dataclass (the post-issuance shape).
- The challenge / response message structures.
- A pure-Python ``sign_response`` / ``verify_response`` pair using
  HMAC-SHA256 as the placeholder MAC scheme. Production wires this
  through the eventual blind-sig / anonymous credential primitive.

The HMAC placeholder is **explicitly NOT secure for unlinkable
issuance** — it leaks issuer identity through the verification key.
But it's correctly-shaped for testing the rest of the pipeline
(nullifier flow, receipt flow, batched settlement) without blocking
on the cryptographic decision in IMPLEMENTATION_PLAN §6.4.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from typing import Iterable


# Maximum age (in seconds) for a challenge. Outside this window, the
# response is rejected. Defaults to 5 minutes — short enough to defeat
# screenshot attacks, long enough to survive normal network latency on
# slow operator hardware.
DEFAULT_CHALLENGE_TTL_SECONDS = 300


@dataclass(frozen=True)
class FunctionKey:
    """Post-issuance Function Key.

    ``secret`` is what the citizen retains; production keys derive
    additional fields (like ``epoch`` and ``credential``). The blind-
    signature implementation populates ``credential`` with the
    issuer's signature on the secret + epoch.

    Sprint 11+ scaffolding: ``credential`` is just bytes — the
    semantic depends on the chosen scheme. Tests can use any
    deterministic value.
    """
    secret: bytes
    epoch: str
    credential: bytes
    # The issuer's verification context — production stores the
    # public params needed to verify ``credential``. Sprint 11+
    # scaffolding accepts any opaque bytes.
    issuer_context: bytes = b""


@dataclass(frozen=True)
class FunctionKeyChallenge:
    """An operator-generated fresh challenge.

    The ``nonce`` is the entropy source; ``operator_id`` ties the
    challenge to a specific operator (so cross-operator response
    reuse is impossible); ``issued_at`` is the start of the TTL
    window.
    """
    nonce: bytes
    operator_id: str
    issued_at: float

    def canonical_bytes(self) -> bytes:
        # Pipe-delimited UTF-8 — same canonicalization style as the
        # Sprint 8 PoW preimage so the convention is uniform.
        return b"|".join([
            b"function_key_challenge",
            self.nonce,
            self.operator_id.encode("utf-8"),
            repr(self.issued_at).encode("utf-8"),
        ])


@dataclass(frozen=True)
class FunctionKeyResponse:
    """Citizen's signed response to a challenge."""
    nonce: bytes
    operator_id: str
    issued_at: float
    nullifier: str
    mac: bytes  # in production: blind-signature proof; here HMAC-SHA256


def issue_challenge(*, operator_id: str, now: float | None = None) -> FunctionKeyChallenge:
    """Generate a fresh ``FunctionKeyChallenge`` for ``operator_id``.

    The ``nonce`` is 32 bytes from ``secrets.token_bytes`` — full
    256-bit entropy, OS-source. ``issued_at`` defaults to
    ``time.time()`` and is included in the canonical bytes so a
    challenge from yesterday cannot be replayed today.
    """
    if not isinstance(operator_id, str) or not operator_id:
        raise ValueError("operator_id must be a non-empty string")
    return FunctionKeyChallenge(
        nonce=secrets.token_bytes(32),
        operator_id=operator_id,
        issued_at=float(now if now is not None else time.time()),
    )


def sign_response(
    *,
    key: FunctionKey,
    challenge: FunctionKeyChallenge,
) -> FunctionKeyResponse:
    """Sign a challenge with the Function Key's secret.

    Sprint 11+ placeholder uses HMAC-SHA256 with ``key.secret`` as
    the MAC key. Production wires the blind-signature scheme here:
    the response includes a zero-knowledge proof that the holder
    knows a credential signed by the issuer over the secret +
    epoch, without revealing which credential.
    """
    from services.infonet.privacy.function_keys.nullifier import derive_nullifier

    nullifier = derive_nullifier(secret=key.secret, operator_id=challenge.operator_id)
    body = challenge.canonical_bytes() + b"|" + nullifier.encode("utf-8")
    mac = hmac.new(key.secret, body, hashlib.sha256).digest()
    return FunctionKeyResponse(
        nonce=challenge.nonce,
        operator_id=challenge.operator_id,
        issued_at=challenge.issued_at,
        nullifier=nullifier,
        mac=mac,
    )


def verify_response(
    *,
    response: FunctionKeyResponse,
    key: FunctionKey,
    max_age: float = DEFAULT_CHALLENGE_TTL_SECONDS,
    now: float | None = None,
    seen_nonces: Iterable[bytes] = (),
) -> tuple[bool, str]:
    """Verify a response against the matching key + check freshness.

    Returns ``(accepted, reason)``. ``accepted=False`` produces one
    of these diagnostic reasons:

    - ``"stale_challenge"`` — challenge too old.
    - ``"replay_nonce_seen"`` — nonce was used in a prior verified
      response.
    - ``"invalid_mac"`` — MAC didn't verify against the key.

    Operators MUST track recently-seen nonces (for the duration of
    the TTL plus a margin) to defeat replay. Pass them in via
    ``seen_nonces``.

    Note on the verifier-knows-the-secret problem: with the HMAC
    placeholder, the verifier needs ``key.secret`` to verify. That's
    obviously NOT private — it's why this is a placeholder. The
    production blind-sig scheme verifies *without* knowing the
    secret, only the issuer's public verification context.
    """
    seen_set = set(seen_nonces)
    if response.nonce in seen_set:
        return False, "replay_nonce_seen"

    age_s = float(now if now is not None else time.time()) - response.issued_at
    if age_s > max_age or age_s < 0:
        return False, "stale_challenge"

    challenge = FunctionKeyChallenge(
        nonce=response.nonce,
        operator_id=response.operator_id,
        issued_at=response.issued_at,
    )
    body = challenge.canonical_bytes() + b"|" + response.nullifier.encode("utf-8")
    expected = hmac.new(key.secret, body, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, response.mac):
        return False, "invalid_mac"
    return True, "ok"


__all__ = [
    "DEFAULT_CHALLENGE_TTL_SECONDS",
    "FunctionKey",
    "FunctionKeyChallenge",
    "FunctionKeyResponse",
    "issue_challenge",
    "sign_response",
    "verify_response",
]
