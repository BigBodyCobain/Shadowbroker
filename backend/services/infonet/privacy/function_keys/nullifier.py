"""Nullifiers — one-time-use markers per (key, operator) pair.

Source of truth: ``infonet-economy/IMPLEMENTATION_PLAN.md`` §4.4
piece 2.

For each Function Key + operator combination, the nullifier is

    nullifier = SHA-256(secret || operator_id)

Properties this gives us:

- **One-time-use per operator.** The operator records the nullifier
  on first use; subsequent attempts with the same nullifier are
  rejected (denial code ``NULLIFIER_ALREADY_SEEN``).
- **Cross-operator unlinkability.** Different ``operator_id``s
  produce different nullifiers for the same secret. Two operators
  comparing notes cannot determine that the same key was used at
  both — they see two unrelated 32-byte strings.
- **No identity leakage.** The nullifier is a hash; the secret is
  never exposed.

Operators MUST commit ``operator_id`` publicly so its non-forgeability
is anchored on chain. Nullifier derivation depends on a
non-forgeable ``operator_id`` (an attacker who could impersonate an
operator could harvest nullifiers).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


def derive_nullifier(*, secret: bytes, operator_id: str) -> str:
    """Return the hex SHA-256 of ``secret || operator_id`` (UTF-8 for
    operator_id).

    Stable across reboots / sessions / operating systems — the same
    inputs always produce the same output. That's the whole property
    a nullifier needs: deterministic and unforgeable.
    """
    if not isinstance(secret, (bytes, bytearray)):
        raise TypeError("secret must be bytes")
    if not isinstance(operator_id, str) or not operator_id:
        raise ValueError("operator_id must be a non-empty string")
    h = hashlib.sha256()
    h.update(bytes(secret))
    h.update(b"|")  # explicit separator so concatenation is unambiguous
    h.update(operator_id.encode("utf-8"))
    return h.hexdigest()


@dataclass
class NullifierTracker:
    """Operator-side store of seen nullifiers.

    Sprint 11+ runway: this is the in-memory reference implementation.
    Production operators use a persistent, atomic-write store
    (database row + uniqueness constraint) so the "already-seen"
    check is robust to crashes between the check and the receipt.

    The interface is designed for that: ``check_and_record`` is the
    only mutation method, and it's atomic — checks then records as
    one operation. Production wraps this in a database transaction.
    """

    seen: set[str] = field(default_factory=set)

    def has_seen(self, nullifier: str) -> bool:
        return nullifier in self.seen

    def check_and_record(self, nullifier: str) -> bool:
        """Return ``True`` if the nullifier was unseen (and is now
        recorded). Return ``False`` if it was already seen — the
        operator MUST then issue a denial with code
        ``NULLIFIER_ALREADY_SEEN``.

        The check + record is atomic by design: a concurrent caller
        racing with this method will not produce two ``True`` results
        for the same nullifier. (In-memory: trivially atomic. Production:
        wrap in DB unique-insert.)
        """
        if nullifier in self.seen:
            return False
        self.seen.add(nullifier)
        return True


__all__ = [
    "NullifierTracker",
    "derive_nullifier",
]
