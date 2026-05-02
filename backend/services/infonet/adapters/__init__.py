"""Adapter layer between the Infonet economy package and the legacy
``services/mesh/`` primitives.

Rule: **adapters import from mesh, mesh never imports from infonet.**
This keeps the dependency direction one-way and lets us delete the
infonet package without touching mesh.

The legacy mesh files (``mesh_schema.py``, ``mesh_signed_events.py``,
``mesh_hashchain.py``, ``mesh_reputation.py``, ``mesh_oracle.py``) stay
byte-identical through Sprint 3. From Sprint 4 onward, when actual chain
writes for new event types start happening, the hashchain adapter is
the single integration point that decides whether to:

1. Modify ``ACTIVE_APPEND_EVENT_TYPES`` in ``mesh_schema.py`` (one-shot,
   minimal mesh change), OR
2. Maintain a parallel append surface in ``hashchain_adapter`` that
   shares the on-disk chain file but bypasses the legacy event-type
   gate.

The decision is recorded in ``infonet-economy/BUILD_LOG.md`` Sprint 4
when made.
"""

from services.infonet.adapters.hashchain_adapter import (
    InfonetHashchainAdapter,
    extended_active_event_types,
)
from services.infonet.adapters.signed_write_adapter import (
    INFONET_SIGNED_WRITE_KINDS,
    InfonetSignedWriteKind,
)

__all__ = [
    "INFONET_SIGNED_WRITE_KINDS",
    "InfonetHashchainAdapter",
    "InfonetSignedWriteKind",
    "extended_active_event_types",
]
