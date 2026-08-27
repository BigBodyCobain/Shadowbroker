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


def test_cctv_enable_seeds_empty_catalog_before_loading():
    """An empty CCTV DB must trigger the public ingestors on first enable."""
    from services.layer_enable_refresh import _slow_fetch

    with (
        patch("services.cctv_pipeline.get_camera_count", return_value=0) as count,
        patch("services.cctv_pipeline.run_all_ingestors") as seed,
        patch("services.fetchers.infrastructure.fetch_cctv") as fetch_cctv,
    ):
        _slow_fetch("cctv")

    count.assert_called_once()
    seed.assert_called_once()
    fetch_cctv.assert_called_once()


def test_cctv_enable_reuses_nonempty_catalog():
    """A populated CCTV DB should stay fast and avoid re-seeding on enable."""
    from services.layer_enable_refresh import _slow_fetch

    with (
        patch("services.cctv_pipeline.get_camera_count", return_value=12) as count,
        patch("services.cctv_pipeline.run_all_ingestors") as seed,
        patch("services.fetchers.infrastructure.fetch_cctv") as fetch_cctv,
    ):
        _slow_fetch("cctv")

    count.assert_called_once()
    seed.assert_not_called()
    fetch_cctv.assert_called_once()


def test_refreshes_intelligence_layers_on_enable():
    """Cold optional feeds must not wait for the next slow-tier scheduler tick."""
    keys = {
        "uap_sightings",
        "malware_c2",
        "cyber_threats",
        "scm_suppliers",
        "telegram_osint",
        "gt_risk",
    }
    before = snapshot_active_layers()
    for key in keys:
        active_layers[key] = True

    try:
        with patch("services.data_fetcher._SLOW_EXECUTOR") as slow_exec:
            refresh_newly_enabled_layers({**before, **{key: False for key in keys}})

        slow_exec.submit.assert_called_once()
        assert set(slow_exec.submit.call_args.args[1]) == keys
    finally:
        for key in keys:
            active_layers[key] = before.get(key, False)


def test_slow_fetch_supports_intelligence_layers_without_network():
    """Each newly supported layer dispatches to its existing fetcher."""
    from services.layer_enable_refresh import _slow_fetch

    with (
        patch("services.fetchers.earth_observation.fetch_uap_sightings") as uap,
        patch("services.fetchers.malware.fetch_malware_threats") as malware,
        patch("services.fetchers.cyber_status.fetch_cyber_threats") as cyber,
        patch("services.scm.suppliers.fetch_scm_suppliers") as scm,
        patch("services.fetchers.telegram_osint.fetch_telegram_osint") as telegram,
        patch("analytics.integration.maybe_refresh_gt_analytics") as gt,
    ):
        for key in (
            "uap_sightings",
            "malware_c2",
            "cyber_threats",
            "scm_suppliers",
            "telegram_osint",
            "gt_risk",
        ):
            _slow_fetch(key)

    uap.assert_called_once_with()
    malware.assert_called_once_with()
    cyber.assert_called_once_with()
    scm.assert_called_once_with()
    telegram.assert_called_once_with()
    gt.assert_called_once_with()
