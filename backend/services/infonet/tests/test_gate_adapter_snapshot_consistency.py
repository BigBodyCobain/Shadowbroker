"""Regression coverage for consistent gate-adapter chain snapshots."""

from services.infonet.adapters.gate_adapter import InfonetGateAdapter


def _counting_adapter():
    calls = {"count": 0}

    def chain_provider():
        calls["count"] += 1
        return []

    return InfonetGateAdapter(chain_provider), calls


def test_suspension_state_samples_chain_once():
    adapter, calls = _counting_adapter()

    adapter.suspension_state("never-seen")

    assert calls["count"] == 1


def test_shutdown_state_samples_chain_once():
    adapter, calls = _counting_adapter()

    adapter.shutdown_state("never-seen")

    assert calls["count"] == 1
