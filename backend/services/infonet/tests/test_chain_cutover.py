"""Sprint 8+ chain cutover — Infonet event types accepted by mesh_schema.

The cutover registers each ``INFONET_ECONOMY_EVENT_TYPES`` entry with
``mesh_schema._EXTENSION_VALIDATORS`` and adds the type set to
``mesh_hashchain.ACTIVE_APPEND_EVENT_TYPES``. After import,
``mesh_schema.validate_event_payload`` accepts new types via the
extension fall-through; ``validate_public_ledger_payload`` also
allows them.
"""

from __future__ import annotations

from services.infonet import _chain_cutover
from services.infonet.schema import INFONET_ECONOMY_EVENT_TYPES
from services.mesh import mesh_hashchain, mesh_schema


def test_cutover_status_reports_done():
    status = _chain_cutover.cutover_status()
    assert status["done"] is True
    assert status["missing_types"] == []
    assert status["active_append_includes_economy"] is True


def test_every_economy_type_registered_with_mesh_schema():
    for et in INFONET_ECONOMY_EVENT_TYPES:
        assert mesh_schema.is_extension_event_type(et), (
            f"{et} is in INFONET_ECONOMY_EVENT_TYPES but not registered "
            f"with mesh_schema. The cutover regressed."
        )


def test_every_economy_type_in_active_append_set():
    for et in INFONET_ECONOMY_EVENT_TYPES:
        assert et in mesh_hashchain.ACTIVE_APPEND_EVENT_TYPES, (
            f"{et} is not in mesh_hashchain.ACTIVE_APPEND_EVENT_TYPES. "
            f"The cutover regressed."
        )


def test_validate_event_payload_routes_to_extension_validator():
    """A previously-unknown event type now succeeds when its payload
    is well-formed."""
    ok, why = mesh_schema.validate_event_payload(
        "uprep",
        {"target_node_id": "alice", "target_event_id": "post1"},
    )
    assert ok, why


def test_validate_event_payload_rejects_malformed_economy_payload():
    """Even when the type is registered, malformed payloads still fail
    via the infonet schema validator."""
    ok, why = mesh_schema.validate_event_payload(
        "uprep",
        {"target_node_id": "alice"},  # missing target_event_id
    )
    assert not ok
    assert "target_event_id" in why


def test_validate_event_payload_rejects_truly_unknown_type():
    """Types not in legacy SCHEMA_REGISTRY and not registered as
    extensions still fail."""
    ok, why = mesh_schema.validate_event_payload("not_an_event", {})
    assert not ok
    assert "Unknown event_type" in why


def test_validate_public_ledger_payload_allows_economy_types():
    """The public-ledger gate now permits economy types alongside
    legacy ones."""
    ok, why = mesh_schema.validate_public_ledger_payload(
        "petition_file",
        {"petition_id": "p1", "petition_payload": {"type": "UPDATE_PARAM",
                                                    "key": "vote_decay_days",
                                                    "value": 30}},
    )
    assert ok, why


def test_legacy_event_types_still_validate_through_legacy_path():
    """The cutover doesn't disturb the legacy validator pipeline.
    Legacy ``message`` events still go through ``SCHEMA_REGISTRY``,
    not the extension fall-through."""
    ok, _ = mesh_schema.validate_event_payload(
        "message",
        {"message": "hello", "destination": "broadcast",
         "channel": "general", "priority": "normal", "ephemeral": False},
    )
    assert ok


def test_cutover_is_idempotent():
    """Calling perform_cutover() twice leaves state unchanged.
    The cutover is triggered automatically at import time; an explicit
    second call must not error or duplicate registration."""
    before = _chain_cutover.cutover_status()
    _chain_cutover.perform_cutover()
    after = _chain_cutover.cutover_status()
    assert before == after


def test_economy_validators_skip_legacy_normalization_check():
    """Extension validators bypass the legacy ``normalize_payload`` +
    ephemeral checks. The infonet schema handles its own normalization,
    and economy events have different payload shapes than legacy ones."""
    # An infonet payload with arbitrary key ordering and no
    # 'ephemeral' field — would trip the legacy "ephemeral required"
    # checks if routed through the legacy path. Routes through the
    # extension validator instead, which accepts it.
    ok, _ = mesh_schema.validate_event_payload(
        "prediction_place",
        {"market_id": "m1", "side": "yes", "probability_at_bet": 50.0},
    )
    assert ok
