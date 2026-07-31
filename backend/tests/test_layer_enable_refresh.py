"""Tests for on-enable layer refresh (Phase 2 UX guardrail)."""
from __future__ import annotations

from unittest.mock import patch

from services.fetchers._store import active_layers, bump_active_layers_version
from services.layer_enable_refresh import refresh_newly_enabled_layers, snapshot_active_layers


def test_refresh_firms_on_enable_only():
    before = snapshot_active_layers()
    active_layers["firms"] = True
    bump_active_layers_version()

    with (
        patch("services.fetchers.earth_observation.fetch_firms_fires") as firms,
        patch("services.fetchers.earth_observation.fetch_firms_country_fires") as country,
        patch("services.layer_enable_refresh._run_slow_enable_fetches") as run_slow,
        patch("services.fetchers._store.bump_data_version") as bump,
    ):
        refresh_newly_enabled_layers({**before, "firms": False})
        firms.assert_not_called()
        country.assert_not_called()
        run_slow.assert_called_once()
        assert run_slow.call_args[0][0] == ("firms",)
        bump.assert_not_called()

    active_layers["firms"] = before.get("firms", False)


def test_refresh_skips_when_layer_stays_off():
    before = {**snapshot_active_layers(), "cctv": False}
    active_layers["cctv"] = False

    with patch("services.fetchers.infrastructure.fetch_cctv") as fetch_cctv:
        refresh_newly_enabled_layers(before)

    fetch_cctv.assert_not_called()


def test_refresh_cctv_runs_on_slow_executor():
    """CCTV SELECT can be large — never block the API worker on enable."""
    before = {**snapshot_active_layers(), "cctv": False}
    active_layers["cctv"] = True

    with (
        patch("services.fetchers.infrastructure.fetch_cctv") as fetch_cctv,
        patch("services.fetchers._store.bump_data_version") as bump,
        patch("services.data_fetcher._SLOW_EXECUTOR") as slow_exec,
    ):
        refresh_newly_enabled_layers(before)

    fetch_cctv.assert_not_called()
    bump.assert_not_called()
    slow_exec.submit.assert_called_once()
    assert slow_exec.submit.call_args[0][1] == ("cctv",)

    active_layers["cctv"] = before.get("cctv", False)
