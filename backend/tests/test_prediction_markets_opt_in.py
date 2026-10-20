"""UI opt-in for prediction markets (Global Threat Intercept)."""

from services import prediction_markets_settings as pm_settings
from services.fetchers import prediction_markets


def test_ui_opt_in_enables_fetch(monkeypatch, tmp_path):
    opt_file = tmp_path / "prediction_markets_opt_in.json"
    monkeypatch.setattr(pm_settings, "_OPT_IN_FILE", opt_file)
    monkeypatch.delenv("PREDICTION_MARKETS_ENABLED", raising=False)

    assert pm_settings.prediction_markets_fetch_enabled() is False

    pm_settings.set_prediction_markets_ui_opt_in(True)
    assert pm_settings.prediction_markets_fetch_enabled() is True
    assert prediction_markets.prediction_markets_fetch_enabled() is True


def test_env_force_on_without_ui_file(monkeypatch, tmp_path):
    opt_file = tmp_path / "prediction_markets_opt_in.json"
    monkeypatch.setattr(pm_settings, "_OPT_IN_FILE", opt_file)
    monkeypatch.setenv("PREDICTION_MARKETS_ENABLED", "true")

    assert pm_settings.prediction_markets_fetch_enabled() is True
