"""Chain-write cutover — register Infonet economy event types with the
legacy mesh_schema + mesh_hashchain at import time.

Source of truth: ``infonet-economy/BUILD_LOG.md`` Sprint 4 §6.2 cutover
decision (Option C — rename + coexist with new event-type names).

Before this cutover, Sprints 1-7 produced economy events through
``InfonetHashchainAdapter.dry_run_append`` only. None of them landed
on the legacy chain because ``mesh_hashchain.Infonet.append`` rejected
any event_type not in ``ACTIVE_APPEND_EVENT_TYPES``.

This module performs the surgical wiring needed for production writes:

1. Mutates ``mesh_hashchain.ACTIVE_APPEND_EVENT_TYPES`` (a mutable
   set, not a frozenset) to include every type in
   ``INFONET_ECONOMY_EVENT_TYPES``.
2. Registers each economy event type's payload validator with
   ``mesh_schema._EXTENSION_VALIDATORS`` via the Sprint-8-polish
   ``register_extension_validator`` hook.

The cutover is **idempotent**: importing this module twice leaves the
state unchanged.

The direction is **one-way**: infonet imports mesh_*; mesh never
imports infonet. mesh_schema's hook is generic — it doesn't know
about infonet specifically.

What is NOT modified by this cutover:

- ``mesh_schema.SCHEMA_REGISTRY`` — legacy validators stay as-is.
  Economy types use the parallel ``_EXTENSION_VALIDATORS`` registry.
- ``mesh_schema.ACTIVE_PUBLIC_LEDGER_EVENT_TYPES`` — legacy frozenset
  unchanged. The runtime decision in
  ``mesh_hashchain.Infonet.append`` consults the mutable
  ``ACTIVE_APPEND_EVENT_TYPES`` set.
- ``mesh_hashchain.py`` — byte-identical to its Sprint 1 baseline.
- The legacy ``normalize_payload`` and "no ephemeral on this type"
  checks — extension events skip them. Economy event payloads
  already have their own normalization (the schema in
  ``services/infonet/schema.py``).
"""

from __future__ import annotations

import threading

from services.infonet.schema import (
    INFONET_ECONOMY_EVENT_TYPES,
    validate_infonet_event_payload,
)
from services.mesh import mesh_hashchain, mesh_schema


_CUTOVER_LOCK = threading.Lock()
_CUTOVER_DONE = False


def perform_cutover() -> None:
    """Idempotent registration of every Infonet economy event type.

    Safe to call multiple times. After the first call, repeat calls
    are no-ops (the lock + sentinel guard re-entry).
    """
    global _CUTOVER_DONE
    with _CUTOVER_LOCK:
        if _CUTOVER_DONE:
            return
        # Extend the active-append set so mesh_hashchain.Infonet.append
        # accepts these types. The set is mutable by design (legacy
        # mesh_hashchain.py line 163 uses set(), not frozenset()).
        mesh_hashchain.ACTIVE_APPEND_EVENT_TYPES.update(INFONET_ECONOMY_EVENT_TYPES)
        # Register a validator for each. The lambda binds to the loop
        # variable via default-arg trick to avoid late-binding bugs.
        for event_type in INFONET_ECONOMY_EVENT_TYPES:
            mesh_schema.register_extension_validator(
                event_type,
                lambda payload, _et=event_type: validate_infonet_event_payload(_et, payload),
            )
        _CUTOVER_DONE = True


def cutover_status() -> dict[str, object]:
    """Diagnostic — used by tests and health endpoints to confirm the
    cutover ran and registered every type."""
    return {
        "done": _CUTOVER_DONE,
        "registered_types": sorted(
            t for t in INFONET_ECONOMY_EVENT_TYPES
            if mesh_schema.is_extension_event_type(t)
        ),
        "missing_types": sorted(
            t for t in INFONET_ECONOMY_EVENT_TYPES
            if not mesh_schema.is_extension_event_type(t)
        ),
        "active_append_includes_economy": INFONET_ECONOMY_EVENT_TYPES.issubset(
            mesh_hashchain.ACTIVE_APPEND_EVENT_TYPES
        ),
    }


# Run automatically when the module is imported. The infonet package
# __init__ imports this module, so any code that uses
# ``services.infonet`` at all triggers the cutover. Production callers
# don't need to do anything explicit.
perform_cutover()


__all__ = ["cutover_status", "perform_cutover"]
