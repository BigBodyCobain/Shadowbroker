"""Sprint 1 — Adapter skeletons exist and validate via the new schema.

Sprint 1 ships only the dry-run validation surface. Real chain writes
land in Sprint 4 — tests for that will gate the cutover.
"""

from __future__ import annotations

import pytest

from services.infonet.adapters import (
    INFONET_SIGNED_WRITE_KINDS,
    InfonetHashchainAdapter,
    InfonetSignedWriteKind,
    extended_active_event_types,
)
from services.infonet.adapters.gate_adapter import InfonetGateAdapter
from services.infonet.adapters.oracle_adapter import InfonetOracleAdapter
from services.infonet.adapters.reputation_adapter import InfonetReputationAdapter
from services.infonet.schema import INFONET_ECONOMY_EVENT_TYPES
from services.mesh.mesh_schema import ACTIVE_PUBLIC_LEDGER_EVENT_TYPES


def test_extended_active_includes_legacy_and_economy():
    extended = extended_active_event_types()
    assert ACTIVE_PUBLIC_LEDGER_EVENT_TYPES.issubset(extended)
    assert INFONET_ECONOMY_EVENT_TYPES.issubset(extended)


def test_extended_active_is_frozen():
    extended = extended_active_event_types()
    assert isinstance(extended, frozenset)


def test_signed_write_kinds_cover_all_event_types():
    """Every event type has a matching SignedWriteKind value."""
    kind_values = {k.value for k in INFONET_SIGNED_WRITE_KINDS}
    missing = INFONET_ECONOMY_EVENT_TYPES - kind_values
    assert not missing, f"event types without SignedWriteKind: {sorted(missing)}"


def test_signed_write_kind_uprep():
    assert InfonetSignedWriteKind.UPREP.value == "uprep"


def test_dry_run_append_rejects_unknown_event_type():
    adapter = InfonetHashchainAdapter()
    with pytest.raises(ValueError):
        adapter.dry_run_append("not_an_event", "node-1", {}, sequence=1)


def test_dry_run_append_rejects_legacy_event_type():
    adapter = InfonetHashchainAdapter()
    with pytest.raises(ValueError):
        adapter.dry_run_append("message", "node-1", {"message": "x"}, sequence=1)


def test_dry_run_append_rejects_invalid_payload():
    adapter = InfonetHashchainAdapter()
    with pytest.raises(ValueError):
        adapter.dry_run_append("uprep", "node-1", {"target_node_id": "x"}, sequence=1)


def test_dry_run_append_rejects_bad_sequence():
    adapter = InfonetHashchainAdapter()
    with pytest.raises(ValueError):
        adapter.dry_run_append(
            "uprep", "node-1",
            {"target_node_id": "n2", "target_event_id": "e1"},
            sequence=0,
        )


def test_dry_run_append_rejects_empty_node_id():
    adapter = InfonetHashchainAdapter()
    with pytest.raises(ValueError):
        adapter.dry_run_append(
            "uprep", "",
            {"target_node_id": "n2", "target_event_id": "e1"},
            sequence=1,
        )


def test_dry_run_append_returns_canonical_event_dict():
    adapter = InfonetHashchainAdapter()
    out = adapter.dry_run_append(
        "uprep", "node-1",
        {"target_node_id": "n2", "target_event_id": "e1"},
        sequence=1,
        timestamp=1700000000.0,
    )
    assert out["event_type"] == "uprep"
    assert out["node_id"] == "node-1"
    assert out["sequence"] == 1
    assert out["timestamp"] == 1700000000.0
    assert out["payload"] == {"target_node_id": "n2", "target_event_id": "e1"}
    assert out["is_provisional"] is True
    assert isinstance(out["event_id"], str) and len(out["event_id"]) == 64


def test_dry_run_append_event_id_is_deterministic():
    adapter = InfonetHashchainAdapter()
    payload = {"target_node_id": "n2", "target_event_id": "e1"}
    a = adapter.dry_run_append("uprep", "node-1", payload, sequence=1, timestamp=1700000000.0)
    b = adapter.dry_run_append("uprep", "node-1", payload, sequence=1, timestamp=1700000000.0)
    assert a["event_id"] == b["event_id"]


def test_dry_run_append_event_id_changes_on_payload_change():
    adapter = InfonetHashchainAdapter()
    a = adapter.dry_run_append(
        "uprep", "node-1",
        {"target_node_id": "n2", "target_event_id": "e1"},
        sequence=1, timestamp=1700000000.0,
    )
    b = adapter.dry_run_append(
        "uprep", "node-1",
        {"target_node_id": "n2", "target_event_id": "e2"},
        sequence=1, timestamp=1700000000.0,
    )
    assert a["event_id"] != b["event_id"]


def test_reputation_adapter_returns_zero_for_unknown_node():
    """Sprint 2 implementation: unknown nodes have no rep, not NotImplementedError.

    Real coverage of the reputation adapter lives in the Sprint 2 test
    suite (``test_2_*.py``). This case is kept here so the Sprint 1
    "adapter exists" contract still has a smoke check.
    """
    a = InfonetReputationAdapter()
    assert a.oracle_rep("never-seen") == 0.0
    assert a.common_rep("never-seen") == 0.0
    assert a.oracle_rep_lifetime("never-seen") == 0.0


def test_oracle_adapter_returns_predicting_for_unknown_market():
    """Sprint 4 implementation: an unknown market_id is treated as
    PREDICTING (no chain events for it). Real coverage of the oracle
    adapter lives in the Sprint 4 test suite (``test_4_*.py``)."""
    from services.infonet.markets import MarketStatus
    a = InfonetOracleAdapter()
    assert a.market_status("never-seen", now=1.0) == MarketStatus.PREDICTING
    assert a.find_snapshot("never-seen") is None
    assert a.collect_evidence("never-seen") == []


def test_gate_adapter_returns_empty_state_for_unknown_gate():
    """Sprint 6 implementation: an unknown gate has no metadata, no
    members, no locks, status="active". Real coverage of the gate
    adapter lives in the Sprint 6 test suite (``test_6_*.py``)."""
    a = InfonetGateAdapter()
    assert a.gate_meta("never-seen") is None
    assert a.member_set("never-seen") == set()
    assert not a.is_locked("never-seen")
    assert not a.is_ratified("never-seen")
