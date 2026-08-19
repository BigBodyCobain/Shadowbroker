"""LiveUAMap provider opt-in and compatibility behavior."""

from __future__ import annotations

import json

import pytest

from services import liveuamap_settings as settings


@pytest.fixture
def opt_in_file(tmp_path, monkeypatch):
    path = tmp_path / "liveuamap_scraper_opt_in.json"
    monkeypatch.setattr(settings, "_OPT_IN_FILE", path)
    monkeypatch.delenv("LIVEUAMAP_API_URL", raising=False)
    monkeypatch.delenv("SHADOWBROKER_ENABLE_LIVEUAMAP_SCRAPER", raising=False)
    return path


def test_windows_defaults_browser_off_without_choice(monkeypatch, opt_in_file):
    monkeypatch.setattr(settings.os, "name", "nt")
    assert settings.liveuamap_requires_ui_opt_in() is True
    assert settings.liveuamap_ui_choice_recorded() is False
    assert settings.liveuamap_browser_scraper_enabled() is False
    assert settings.liveuamap_scraper_enabled() is False


def test_windows_opt_in_enables_browser(monkeypatch, opt_in_file):
    monkeypatch.setattr(settings.os, "name", "nt")
    settings.set_liveuamap_ui_opt_in(True)
    assert settings.liveuamap_ui_choice_recorded() is True
    assert settings.liveuamap_browser_scraper_enabled() is True
    assert json.loads(opt_in_file.read_text())["opted_in"] is True


def test_windows_decline_is_recorded_without_enabling_browser(monkeypatch, opt_in_file):
    monkeypatch.setattr(settings.os, "name", "nt")
    settings.set_liveuamap_ui_opt_in(False)
    assert settings.liveuamap_ui_choice_recorded() is True
    assert settings.get_liveuamap_ui_opt_in() is False
    assert settings.liveuamap_browser_scraper_enabled() is False


def test_linux_preserves_existing_auto_enrichment_default(monkeypatch, opt_in_file):
    monkeypatch.setattr(settings.os, "name", "posix")
    assert settings.liveuamap_requires_ui_opt_in() is False
    assert settings.liveuamap_browser_scraper_enabled() is True
    assert settings.liveuamap_scraper_enabled() is True


def test_env_force_off_disables_browser_even_after_opt_in(monkeypatch, opt_in_file):
    monkeypatch.setattr(settings.os, "name", "nt")
    settings.set_liveuamap_ui_opt_in(True)
    monkeypatch.setenv("SHADOWBROKER_ENABLE_LIVEUAMAP_SCRAPER", "false")
    assert settings.liveuamap_browser_scraper_enabled() is False
    assert settings.liveuamap_scraper_enabled() is False


def test_api_provider_does_not_require_browser_consent(monkeypatch, opt_in_file):
    monkeypatch.setattr(settings.os, "name", "nt")
    monkeypatch.setenv("LIVEUAMAP_API_URL", "https://api.example.test/liveuamap")
    status = settings.liveuamap_scraper_status()
    assert status["api_configured"] is True
    assert status["scraper_enabled"] is False
    assert status["enrichment_enabled"] is True
    assert status["provider_mode"] == "api"
    assert settings.liveuamap_scraper_enabled() is True


def test_invalid_http_api_url_does_not_count_as_configured(monkeypatch, opt_in_file):
    monkeypatch.setattr(settings.os, "name", "nt")
    monkeypatch.setenv("LIVEUAMAP_API_URL", "http://api.example.test/liveuamap")
    assert settings.liveuamap_api_configured() is False
    assert settings.liveuamap_scraper_enabled() is False
