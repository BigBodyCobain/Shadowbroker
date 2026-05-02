"""Sprint 1 — Schema mismatch rejection, unknown event types rejected, registry coverage.

Maps to BUILD_LOG.md Sprint 1 invariants #5 and #6 plus
IMPLEMENTATION_PLAN.md §3.1 (events extend, do not replace) and §7.1.
"""

from __future__ import annotations

import pytest

from services.infonet.events import EventConstructionError, build_event
from services.infonet.schema import (
    INFONET_ECONOMY_EVENT_TYPES,
    assert_registry_complete,
    get_infonet_schema,
    validate_infonet_event_payload,
)
from services.mesh.mesh_schema import (
    ACTIVE_PUBLIC_LEDGER_EVENT_TYPES as LEGACY_ACTIVE,
    LEGACY_PUBLIC_LEDGER_EVENT_TYPES as LEGACY_LEGACY,
)


def test_economy_types_disjoint_from_legacy_active():
    """Sprint 1 invariant #5."""
    overlap = INFONET_ECONOMY_EVENT_TYPES & LEGACY_ACTIVE
    assert not overlap, f"economy types overlap legacy active: {sorted(overlap)}"


def test_economy_types_disjoint_from_legacy_legacy():
    overlap = INFONET_ECONOMY_EVENT_TYPES & LEGACY_LEGACY
    assert not overlap, f"economy types overlap legacy legacy set: {sorted(overlap)}"


def test_every_economy_event_type_has_validator():
    """Sprint 1 invariant #6."""
    assert_registry_complete()


def test_unknown_event_type_rejected():
    ok, why = validate_infonet_event_payload("totally_made_up_event", {})
    assert not ok
    assert "Unknown event_type" in why


def test_legacy_event_type_rejected_by_economy_validator():
    """Legacy ``message`` is not part of the economy layer — must reject."""
    ok, why = validate_infonet_event_payload("message", {"message": "x"})
    assert not ok


def test_uprep_missing_required_field_rejected():
    ok, why = validate_infonet_event_payload("uprep", {"target_node_id": "n1"})
    assert not ok
    assert "target_event_id" in why


def test_uprep_with_empty_target_rejected():
    ok, why = validate_infonet_event_payload(
        "uprep", {"target_node_id": "", "target_event_id": "evt1"}
    )
    assert not ok


def test_prediction_place_invalid_side_rejected():
    ok, why = validate_infonet_event_payload(
        "prediction_place",
        {"market_id": "m1", "side": "maybe", "probability_at_bet": 50},
    )
    assert not ok


def test_prediction_place_probability_out_of_range_rejected():
    ok, why = validate_infonet_event_payload(
        "prediction_place",
        {"market_id": "m1", "side": "yes", "probability_at_bet": 150},
    )
    assert not ok


def test_resolution_stake_invalid_side_rejected():
    ok, why = validate_infonet_event_payload(
        "resolution_stake",
        {"market_id": "m1", "side": "maybe", "amount": 5, "rep_type": "oracle"},
    )
    assert not ok


def test_resolution_stake_data_unavailable_accepted():
    ok, why = validate_infonet_event_payload(
        "resolution_stake",
        {"market_id": "m1", "side": "data_unavailable", "amount": 5, "rep_type": "oracle"},
    )
    assert ok, why


def test_petition_file_unknown_payload_type_rejected():
    ok, why = validate_infonet_event_payload(
        "petition_file",
        {"petition_id": "p1", "petition_payload": {"type": "DELETE_EVERYTHING"}},
    )
    assert not ok
    assert "petition_payload" in why


def test_petition_file_update_param_accepted():
    ok, why = validate_infonet_event_payload(
        "petition_file",
        {
            "petition_id": "p1",
            "petition_payload": {"type": "UPDATE_PARAM", "key": "vote_decay_days", "value": 30},
        },
    )
    assert ok, why


def test_node_register_invalid_class_rejected():
    ok, why = validate_infonet_event_payload(
        "node_register",
        {"public_key": "abc", "public_key_algo": "ed25519", "node_class": "medium"},
    )
    assert not ok


def test_build_event_rejects_unknown_type():
    with pytest.raises(EventConstructionError):
        build_event("not_an_event", {})


def test_build_event_rejects_invalid_payload():
    with pytest.raises(EventConstructionError):
        build_event("uprep", {"target_node_id": "x"})


def test_build_event_returns_validated_payload():
    out = build_event("uprep", {"target_node_id": "n1", "target_event_id": "e1"})
    assert out == {"target_node_id": "n1", "target_event_id": "e1"}


def test_get_schema_returns_none_for_unknown():
    assert get_infonet_schema("nope") is None


def test_get_schema_returns_validator_for_known():
    schema = get_infonet_schema("uprep")
    assert schema is not None
    assert schema.event_type == "uprep"
    assert "target_node_id" in schema.required_fields
