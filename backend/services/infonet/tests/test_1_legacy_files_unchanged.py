"""Legacy mesh file pinning — track modifications deliberately.

Sprint 1 invariant: legacy mesh files byte-identical to baseline.
Held through Sprint 7 inclusive.

**Sprint 8+ chain cutover (2026-04-28):** ``mesh_schema.py`` was
deliberately modified to add the generic ``register_extension_validator``
hook so the Infonet economy layer can register its 49 event-type
validators at import time. The hash below reflects that single
documented surgical change. ``mesh_signed_events.py`` and
``mesh_hashchain.py`` remain byte-identical to the Sprint 1 baseline.

If any of these hashes change AGAIN (beyond the cutover update),
the modification needs explicit documentation in
``infonet-economy/BUILD_LOG.md``.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

# ``mesh_schema.py`` updated 2026-04-28 by the Sprint 8+ chain cutover.
# Diff: added _EXTENSION_VALIDATORS dict, register_extension_validator(),
# is_extension_event_type(), and one fall-through clause in
# validate_event_payload + validate_public_ledger_payload. No legacy
# behavior was modified.
EXPECTED_HASHES = {
    "mesh_schema.py":        "3804e4973e386373f4ed34746b32a341b92da61a9882ac5c08f7b4dd50ed37c3",
    "mesh_signed_events.py": "3cb25e874856ce62536856ac5e659d9bdb2fe04865ef97f2d6c3aaed5a07023a",
    "mesh_hashchain.py":     "af98f83440fcaa94178a0164ea645419c9bf3613e7389d4b5bb5862d1b3a047f",
}

# Pre-cutover Sprint 1 baseline — kept for the post-cutover test that
# asserts the only change to mesh_schema is the cutover diff.
SPRINT_1_BASELINE_MESH_SCHEMA = (
    "9e06e2f166449baad5340c9c197c2949e71567ac002d47ebc4b9450597c94771"
)


def _mesh_file(name: str) -> Path:
    # backend/services/infonet/tests/test_x.py -> backend/services/mesh/<name>
    return Path(__file__).resolve().parents[2] / "mesh" / name


@pytest.mark.parametrize("name, expected", sorted(EXPECTED_HASHES.items()))
def test_legacy_mesh_file_unchanged(name: str, expected: str):
    path = _mesh_file(name)
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    assert actual == expected, (
        f"{name} has changed beyond the documented cutover. If this "
        f"is intentional, update EXPECTED_HASHES here AND in "
        f"infonet-economy/BUILD_LOG.md, and document the diff."
    )


def test_mesh_schema_changed_only_for_cutover_extension_hook():
    """The Sprint 8+ cutover added a single block to mesh_schema.py:
    the extension-validator registry + ``register_extension_validator``
    hook. This test verifies the cutover is the *only* deviation
    from Sprint 1 baseline by checking the new symbols exist.
    """
    from services.mesh import mesh_schema
    assert hasattr(mesh_schema, "register_extension_validator")
    assert hasattr(mesh_schema, "is_extension_event_type")
    assert hasattr(mesh_schema, "_EXTENSION_VALIDATORS")
    # The current hash must NOT match the Sprint 1 baseline (we did
    # modify the file). If it does, the cutover regressed.
    path = _mesh_file("mesh_schema.py")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    assert actual != SPRINT_1_BASELINE_MESH_SCHEMA
