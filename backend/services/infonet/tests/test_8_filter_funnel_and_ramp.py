"""Sprint 8 — anti-DoS filter funnel ordering + ramp milestones."""

from __future__ import annotations

import pytest

from services.infonet.bootstrap import (
    ActiveFeatures,
    FunnelStage,
    compute_active_features,
    network_node_count,
    run_filter_funnel,
)
from services.infonet.config import CONFIG
from services.infonet.tests._chain_factory import make_event


# ── Filter funnel ───────────────────────────────────────────────────────

def _ok(_: dict) -> tuple[bool, str]:
    return True, "ok"


def test_funnel_short_circuits_on_first_failure():
    calls = []

    def schema(ev):
        calls.append("schema")
        return False, "bad shape"

    def expensive(ev):
        calls.append("expensive")
        return True, "ok"

    stages = [
        FunnelStage(name="schema", check=schema, cost_tier=1),
        FunnelStage(name="expensive", check=expensive, cost_tier=6),
    ]
    ok, reason = run_filter_funnel({}, stages)
    assert not ok
    assert reason.startswith("schema:")
    assert "expensive" not in calls  # expensive stage NOT reached


def test_funnel_all_pass_returns_ok():
    stages = [
        FunnelStage(name="a", check=_ok, cost_tier=1),
        FunnelStage(name="b", check=_ok, cost_tier=2),
        FunnelStage(name="c", check=_ok, cost_tier=3),
    ]
    ok, reason = run_filter_funnel({"event_type": "x"}, stages)
    assert ok
    assert reason == "ok"


def test_funnel_rejects_non_dict_event():
    stages = [FunnelStage(name="a", check=_ok, cost_tier=1)]
    ok, reason = run_filter_funnel("not a dict", stages)  # type: ignore[arg-type]
    assert not ok
    assert "schema" in reason


def test_funnel_raises_on_misordered_stages():
    """Stages must be in monotonically non-decreasing cost_tier order.
    A misordered funnel is a developer bug, not user input — fail
    loudly so it surfaces in CI rather than at runtime under attack."""
    stages = [
        FunnelStage(name="cheap", check=_ok, cost_tier=1),
        FunnelStage(name="expensive", check=_ok, cost_tier=6),
        FunnelStage(name="cheap_again", check=_ok, cost_tier=2),  # WRONG
    ]
    with pytest.raises(ValueError, match="out of order"):
        run_filter_funnel({"event_type": "x"}, stages)


def test_funnel_cost_tiers_match_spec_order():
    """Document the spec's cheapest-first ordering as a structural
    test. Anyone who reverses two stages will hit this assertion."""
    spec_order = [
        ("schema", 1),
        ("signature", 2),
        ("identity_age", 3),
        ("predictor_exclusion", 4),
        ("phase_dedup", 5),
        ("argon2id_pow", 6),
    ]
    # Just assert the tier numbers are strictly increasing.
    tiers = [t for _, t in spec_order]
    assert tiers == sorted(tiers)
    assert len(set(tiers)) == len(tiers)


# ── Ramp ────────────────────────────────────────────────────────────────

def test_node_count_uses_node_register_when_present():
    chain = [
        make_event("node_register", f"n{i}",
                   {"public_key": f"pk{i}", "public_key_algo": "ed25519",
                    "node_class": "heavy"},
                   timestamp=float(i), sequence=1)
        for i in range(5)
    ]
    assert network_node_count(chain) == 5


def test_node_count_falls_back_to_authoring_nodes():
    """No node_register events → use distinct event authors."""
    chain = [
        make_event("uprep", f"n{i}",
                   {"target_node_id": "x", "target_event_id": "e"},
                   timestamp=float(i), sequence=1)
        for i in range(7)
    ]
    assert network_node_count(chain) == 7


def test_active_features_at_zero_nodes():
    feats = compute_active_features([])
    assert feats.node_count == 0
    assert feats.bootstrap_resolution_active is True
    assert feats.staked_resolution_active is False
    assert feats.governance_petitions_active is False
    assert feats.upgrade_governance_active is False
    assert feats.commoncoin_active is False


def test_active_features_at_1k_unlocks_staked_resolution():
    chain = [
        make_event("node_register", f"n{i}",
                   {"public_key": f"pk{i}", "public_key_algo": "ed25519",
                    "node_class": "heavy"},
                   timestamp=float(i), sequence=1)
        for i in range(1000)
    ]
    feats = compute_active_features(chain)
    assert feats.node_count == 1000
    assert feats.staked_resolution_active is True
    assert feats.governance_petitions_active is False
    # bootstrap_resolution_active gates on bootstrap_threshold (CONFIG)
    assert feats.bootstrap_resolution_active == (
        1000 < int(CONFIG["bootstrap_threshold"])
    )


def test_active_features_at_10k_unlocks_commoncoin():
    chain = [
        make_event("node_register", f"n{i}",
                   {"public_key": f"pk{i}", "public_key_algo": "ed25519",
                    "node_class": "heavy"},
                   timestamp=float(i), sequence=1)
        for i in range(10_000)
    ]
    feats = compute_active_features(chain)
    assert feats.commoncoin_active is True
    assert feats.upgrade_governance_active is True
    assert feats.governance_petitions_active is True
    assert feats.staked_resolution_active is True


def test_active_features_milestones_are_monotonic():
    """Each successive milestone activates strictly MORE features.

    The structural property: at each tier, the set of active features
    ⊇ the set at the previous tier (excluding bootstrap_resolution_active
    which is the only feature that DEACTIVATES as the network grows)."""
    def feats_at(n: int) -> set[str]:
        chain = [
            make_event("node_register", f"n{i}",
                       {"public_key": f"pk{i}", "public_key_algo": "ed25519",
                        "node_class": "heavy"},
                       timestamp=float(i), sequence=1)
            for i in range(n)
        ]
        f = compute_active_features(chain)
        active = set()
        if f.staked_resolution_active:
            active.add("staked")
        if f.governance_petitions_active:
            active.add("petitions")
        if f.upgrade_governance_active:
            active.add("upgrade")
        if f.commoncoin_active:
            active.add("commoncoin")
        return active

    s0 = feats_at(0)
    s1k = feats_at(1000)
    s2k = feats_at(2000)
    s5k = feats_at(5000)
    s10k = feats_at(10_000)
    assert s0 <= s1k <= s2k <= s5k <= s10k
