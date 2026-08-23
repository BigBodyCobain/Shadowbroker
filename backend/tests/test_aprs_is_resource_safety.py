"""Regression coverage for APRS-IS resource safety (#533)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from services.aprs_is_bridge import (
    APRSISBridge,
    aprs_connection_config,
)


_APRS_ENV = (
    "APRS_IS_ENABLED",
    "APRS_IS_HOST",
    "APRS_IS_PORT",
    "APRS_IS_PRIVATE_SERVER",
    "APRS_IS_FILTER",
    "APRS_IS_LAT",
    "APRS_IS_LON",
    "APRS_IS_RADIUS_KM",
    "APRS_IS_CALLSIGN",
    "APRS_IS_MAX_SIGNALS",
)


def _clear_aprs_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _APRS_ENV:
        monkeypatch.delenv(name, raising=False)


def _enable_public(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_aprs_env(monkeypatch)
    monkeypatch.setenv("APRS_IS_ENABLED", "true")
    monkeypatch.setenv("APRS_IS_LAT", "40.7128")
    monkeypatch.setenv("APRS_IS_LON", "-74.0060")


def test_aprs_is_is_network_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_aprs_env(monkeypatch)
    assert aprs_connection_config() is None


def test_public_aprs_uses_bounded_geographic_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_public(monkeypatch)
    monkeypatch.setenv("APRS_IS_RADIUS_KM", "250")

    config = aprs_connection_config()

    assert config is not None
    assert config.host == "rotate.aprs2.net"
    assert config.port == 14580
    assert config.filter_expr == "r/40.71280/-74.00600/250"
    assert "filter r/40.71280/-74.00600/250" in config.login
    assert "25000" not in config.login


def test_public_aprs_rejects_global_scale_radius(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_public(monkeypatch)
    monkeypatch.setenv("APRS_IS_RADIUS_KM", "25000")

    with pytest.raises(ValueError, match="between 1 and 500 km"):
        aprs_connection_config()


def test_public_aprs_requires_explicit_center(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_aprs_env(monkeypatch)
    monkeypatch.setenv("APRS_IS_ENABLED", "true")

    with pytest.raises(ValueError, match="APRS_IS_LAT and APRS_IS_LON"):
        aprs_connection_config()


def test_private_full_feed_override_cannot_target_public_aprs(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_aprs_env(monkeypatch)
    monkeypatch.setenv("APRS_IS_ENABLED", "true")
    monkeypatch.setenv("APRS_IS_PRIVATE_SERVER", "true")
    monkeypatch.setenv("APRS_IS_HOST", "rotate.aprs2.net")

    with pytest.raises(ValueError, match="cannot be used with a public APRS-IS host"):
        aprs_connection_config()


def test_private_operator_server_may_use_its_own_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_aprs_env(monkeypatch)
    monkeypatch.setenv("APRS_IS_ENABLED", "true")
    monkeypatch.setenv("APRS_IS_PRIVATE_SERVER", "true")
    monkeypatch.setenv("APRS_IS_HOST", "aprs.internal.example")
    monkeypatch.setenv("APRS_IS_FILTER", "t/p")

    config = aprs_connection_config()

    assert config is not None
    assert config.private_server is True
    assert config.filter_expr == "t/p"
    assert config.login.endswith("filter t/p\r\n")


def test_aprs_buffer_is_hard_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_aprs_env(monkeypatch)
    monkeypatch.setenv("APRS_IS_MAX_SIGNALS", "100")
    bridge = APRSISBridge()

    for index in range(150):
        bridge.signals.append({"id": index})

    assert bridge.signals.maxlen == 100
    assert len(bridge.signals) == 100
    assert bridge.signals[0]["id"] == 50


def test_reconnect_backoff_is_exponential_and_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("services.aprs_is_bridge.random.uniform", lambda _a, _b: 1.0)

    assert APRSISBridge._reconnect_delay(1) == 30.0
    assert APRSISBridge._reconnect_delay(2) == 60.0
    assert APRSISBridge._reconnect_delay(3) == 120.0
    assert APRSISBridge._reconnect_delay(4) == 240.0
    assert APRSISBridge._reconnect_delay(5) == 480.0
    assert APRSISBridge._reconnect_delay(6) == 900.0
    assert APRSISBridge._reconnect_delay(99) == 900.0


def test_invalid_public_config_fails_closed_without_starting_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_aprs_env(monkeypatch)
    monkeypatch.setenv("APRS_IS_ENABLED", "true")
    bridge = APRSISBridge()

    bridge.reconcile(True)

    assert bridge.is_running() is False
    assert "APRS_IS_LAT" in bridge.status()["last_error"]


def test_sigint_lifecycle_does_not_start_legacy_aprs_when_only_mesh_is_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.fetchers import sigint as sigint_fetcher
    from services.sigint_bridge import sigint_grid

    legacy_stop = MagicMock()
    mesh_start = MagicMock()
    mesh_stop = MagicMock()
    js8_start = MagicMock()
    safe_reconcile = MagicMock()

    monkeypatch.setattr(sigint_grid.aprs, "stop", legacy_stop)
    monkeypatch.setattr(sigint_grid.mesh, "start", mesh_start)
    monkeypatch.setattr(sigint_grid.mesh, "stop", mesh_stop)
    monkeypatch.setattr(sigint_grid.js8, "start", js8_start)
    monkeypatch.setattr(sigint_fetcher.aprs_is_bridge, "reconcile", safe_reconcile)
    monkeypatch.setattr(sigint_fetcher, "mqtt_bridge_enabled", lambda: True)

    sigint_fetcher._reconcile_sigint_bridges(aprs_requested=False, mesh_requested=True)

    legacy_stop.assert_called_once_with()
    safe_reconcile.assert_called_once_with(False)
    mesh_start.assert_called_once_with()
    mesh_stop.assert_not_called()
    js8_start.assert_called_once_with()


def test_turning_aprs_layer_off_stops_aprs_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.fetchers import sigint as sigint_fetcher
    from services.sigint_bridge import sigint_grid

    safe_reconcile = MagicMock()
    monkeypatch.setattr(sigint_fetcher.aprs_is_bridge, "reconcile", safe_reconcile)
    monkeypatch.setattr(sigint_fetcher, "mqtt_bridge_enabled", lambda: False)
    monkeypatch.setattr(sigint_grid.aprs, "stop", MagicMock())
    monkeypatch.setattr(sigint_grid.mesh, "stop", MagicMock())
    monkeypatch.setattr(sigint_grid.js8, "start", MagicMock())

    sigint_fetcher._reconcile_sigint_bridges(aprs_requested=False, mesh_requested=True)

    safe_reconcile.assert_called_once_with(False)


def test_fetch_path_never_calls_legacy_grid_start(monkeypatch: pytest.MonkeyPatch) -> None:
    from services.fetchers import sigint as sigint_fetcher
    from services.fetchers import _store
    from services.sigint_bridge import sigint_grid

    monkeypatch.setattr(
        _store,
        "effective_layers",
        lambda: {"sigint_aprs": False, "sigint_meshtastic": False},
    )
    legacy_start = MagicMock(side_effect=AssertionError("legacy grid start must not run"))
    monkeypatch.setattr(sigint_grid, "start", legacy_start)
    monkeypatch.setattr(sigint_fetcher, "_reconcile_sigint_bridges", MagicMock())

    sigint_fetcher.fetch_sigint()

    legacy_start.assert_not_called()
