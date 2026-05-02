"""Sprint 1 — IMMUTABLE_PRINCIPLES mutation attempts must fail.

Maps to BUILD_LOG.md Sprint 1 invariant #1 and IMPLEMENTATION_PLAN.md
§9 (constitutional reminders).
"""

from __future__ import annotations

import pytest

from services.infonet.config import IMMUTABLE_PRINCIPLES


def test_immutable_principles_is_mappingproxy():
    from types import MappingProxyType
    assert isinstance(IMMUTABLE_PRINCIPLES, MappingProxyType)


def test_cannot_assign_existing_key():
    with pytest.raises(TypeError):
        IMMUTABLE_PRINCIPLES["audit_public"] = False  # type: ignore[index]


def test_cannot_add_new_key():
    with pytest.raises(TypeError):
        IMMUTABLE_PRINCIPLES["new_principle"] = True  # type: ignore[index]


def test_cannot_delete_key():
    with pytest.raises(TypeError):
        del IMMUTABLE_PRINCIPLES["coin_governance_firewall"]  # type: ignore[arg-type]


def test_required_principles_present():
    required = {
        "oracle_rep_source",
        "hashchain_append_only",
        "audit_public",
        "identity_permissionless",
        "signature_required",
        "redemption_path_exists",
        "coin_governance_firewall",
        "protocol_version",
    }
    assert required.issubset(IMMUTABLE_PRINCIPLES.keys())


def test_oracle_rep_source_is_predictions_only():
    """Constitutional anchor — RULES §1.1 forbids any other source."""
    assert IMMUTABLE_PRINCIPLES["oracle_rep_source"] == "predictions_only"


def test_coin_governance_firewall_true():
    """Coins cannot buy governance power — RULES §1.1, plan §9 #7."""
    assert IMMUTABLE_PRINCIPLES["coin_governance_firewall"] is True
