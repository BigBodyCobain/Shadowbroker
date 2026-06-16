"""Tests for Strategic Risk Analytics core scoring."""

from __future__ import annotations

import pytest

from analytics.feed_adapter import normalize_feed_item
from analytics.gt_early_warning import GT_EarlyWarning
from analytics.integration import process_feed_item, refresh_from_latest_data, reset_gt_engine
from analytics.settings import GTAnalyticsSettings


@pytest.fixture
def engine() -> GT_EarlyWarning:
    return GT_EarlyWarning(
        GTAnalyticsSettings(
            enabled=True,
            base_prior=0.15,
            evidence_cap=3.0,
            evidence_scale=5.0,
            high_risk_threshold=0.6,
        )
    )


def test_classify_payroll_loan_signal(engine: GT_EarlyWarning) -> None:
    signals = engine.classify_signals("Franchise owners increasingly rely on payroll loan facilities.")
    assert "payroll_loan" in signals
    assert signals["payroll_loan"] >= 3.0


def test_classify_no_signal_on_generic_text(engine: GT_EarlyWarning) -> None:
    signals = engine.classify_signals("Sunny weather expected across the region this weekend.")
    assert signals == {}


def test_bayesian_update_increases_risk(engine: GT_EarlyWarning) -> None:
    prior = engine.get_prior("uk", "financial")
    posterior = engine.bayesian_update("uk", "financial", evidence_strength=2.0)
    assert posterior > prior


def test_process_feed_item_updates_region(engine: GT_EarlyWarning) -> None:
    item = {
        "id": "test-1",
        "text": "Mass rally and general strike announced; protest mobilization spreads.",
        "source": "t.me/osintdefender",
        "region": "ukraine",
        "domain": "unrest",
        "entities": ["channel:osintdefender"],
        "coords": [50.45, 30.52],
    }
    result = engine.process_feed_item(item)
    assert result["signals"]
    assert result["risk_score"] > engine.settings.base_prior
    assert result["contagion_potential"] >= 0.0


def test_duplicate_items_are_skipped(engine: GT_EarlyWarning) -> None:
    item = {
        "id": "dup-1",
        "text": "GPS jamming spike reported near border corridor.",
        "source": "gdelt",
        "region": "baltics",
        "domain": "conflict",
    }
    first = engine.process_feed_item(item)
    second = engine.process_feed_item(item)
    assert not first.get("skipped")
    assert second.get("skipped") is True


def test_heatmap_returns_geojson_features(engine: GT_EarlyWarning) -> None:
    engine.process_feed_item(
        {
            "id": "heat-1",
            "text": "Troop movement and armored convoy observed overnight.",
            "source": "news",
            "region": "eastern_europe",
            "coords": [48.0, 37.0],
        }
    )
    heatmap = engine.get_risk_heatmap()
    assert heatmap["type"] == "FeatureCollection"
    assert len(heatmap["features"]) >= 1
    feature = heatmap["features"][0]
    assert "risk" in feature["properties"]
    assert feature["geometry"]["type"] == "Point"


def test_dossier_includes_recent_signals(engine: GT_EarlyWarning) -> None:
    engine.process_feed_item(
        {
            "id": "dos-1",
            "text": "Supply chain delay at major port; logistics backlog worsens.",
            "source": "news",
            "region": "china",
            "domain": "financial",
        }
    )
    dossier = engine.get_dossier("china")
    assert dossier["region"] == "china"
    assert dossier["recent_signals"]
    assert "interpretation" in dossier


def test_feed_adapter_normalizes_telegram_post() -> None:
    normalized = normalize_feed_item(
        {
            "title": "Strike expands",
            "description": "General strike and rally planned in capital.",
            "source": "t.me/nexta_live",
            "channel": "nexta_live",
            "coords": [53.9, 27.56],
        },
        source_type="telegram_osint",
    )
    assert normalized["region"] != "global"
    assert normalized["domain"] in {"unrest", "financial", "conflict"}
    assert normalized["text"]


def test_integration_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GT_ANALYTICS_ENABLED", raising=False)
    reset_gt_engine()
    assert process_feed_item({"text": "test", "region": "global"}) is None


def test_refresh_from_latest_data_processes_telegram(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GT_ANALYTICS_ENABLED", "true")
    reset_gt_engine()
    latest = {
        "telegram_osint": {
            "posts": [
                {
                    "id": "tg-1",
                    "title": "GPS jamming",
                    "description": "GPS jamming spike reported along northern border.",
                    "source": "t.me/osintdefender",
                    "channel": "osintdefender",
                    "coords": [59.93, 30.33],
                }
            ]
        },
        "news": [],
        "gdelt": [],
    }
    summary = refresh_from_latest_data(latest, persist=False)
    assert summary["enabled"] is True
    assert summary["processed"] >= 1