"""Bridge between Infonet economy events and the legacy ``mesh_hashchain``.

Sprint 1 ships this as a **dry-run-only** surface. We do NOT call the
legacy ``Infonet.append`` for new event types because that method
hard-rejects anything not in ``ACTIVE_APPEND_EVENT_TYPES`` (defined in
``mesh_schema.py``). Modifying that set is a Sprint 4 task — it requires
the rest of the producer code to exist, otherwise a malformed
``prediction_create`` could land on the chain with no resolver to
process it.

What this adapter DOES today:

- ``extended_active_event_types()`` — returns the union of legacy active
  types and new economy types, for tooling that needs the full surface
  (e.g. RPC layer, frontend type generation).
- ``InfonetHashchainAdapter.dry_run_append`` — validates a payload
  against the new schema and returns the event dict the legacy
  ``Infonet.append`` would have built. Useful for tests and for the
  future cutover plan.

What this adapter will do in Sprint 4:

- ``append_infonet_event`` — actually call ``Infonet.append`` once
  ``ACTIVE_APPEND_EVENT_TYPES`` is unioned with the economy types.

The Sprint 1 contract:

- ``mesh_hashchain.py`` is byte-identical to the pre-Sprint-1 baseline.
- No event reaches the legacy chain via this adapter in Sprint 1.
- Tests cover validation behavior only.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from services.mesh.mesh_schema import (
    ACTIVE_PUBLIC_LEDGER_EVENT_TYPES as _LEGACY_ACTIVE_TYPES,
)

from services.infonet.schema import (
    INFONET_ECONOMY_EVENT_TYPES,
    validate_infonet_event_payload,
)


def extended_active_event_types() -> frozenset[str]:
    """Union of legacy active types and new economy types.

    Frozen at import time. The legacy set is itself a frozenset so this
    is safe to call from any thread.
    """
    return _LEGACY_ACTIVE_TYPES | INFONET_ECONOMY_EVENT_TYPES


class InfonetHashchainAdapter:
    """Validation-only adapter for new Infonet economy events.

    Real chain integration lives in Sprint 4. Tests should use
    ``dry_run_append`` to assert that producer code is constructing
    correctly-shaped events before the cutover.
    """

    def dry_run_append(
        self,
        event_type: str,
        node_id: str,
        payload: dict[str, Any],
        *,
        sequence: int = 1,
        timestamp: float | None = None,
    ) -> dict[str, Any]:
        """Validate and return a synthetic event dict.

        Mirrors the shape that ``mesh_hashchain.Infonet.append`` would
        produce for legacy types — same field set, same ordering. Does
        NOT compute a real signature (Sprint 4 territory) and does NOT
        write to disk.

        Raises ``ValueError`` on validation failure — the same exception
        type the legacy ``append`` raises so callers don't need to
        special-case the cutover later.
        """
        if event_type not in INFONET_ECONOMY_EVENT_TYPES:
            raise ValueError(f"event_type {event_type!r} not in INFONET_ECONOMY_EVENT_TYPES")
        if not isinstance(node_id, str) or not node_id:
            raise ValueError("node_id is required")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence <= 0:
            raise ValueError("sequence must be a positive integer")

        ok, reason = validate_infonet_event_payload(event_type, payload)
        if not ok:
            raise ValueError(reason)

        ts = float(timestamp) if timestamp is not None else float(time.time())

        canonical = {
            "event_type": event_type,
            "node_id": node_id,
            "payload": payload,
            "timestamp": ts,
            "sequence": sequence,
        }
        encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        event_id = hashlib.sha256(encoded.encode("utf-8")).hexdigest()

        return {
            "event_id": event_id,
            "event_type": event_type,
            "node_id": node_id,
            "timestamp": ts,
            "sequence": sequence,
            "payload": payload,
            # signature / public_key intentionally omitted in Sprint 1.
            "is_provisional": True,
        }


__all__ = [
    "InfonetHashchainAdapter",
    "extended_active_event_types",
]
