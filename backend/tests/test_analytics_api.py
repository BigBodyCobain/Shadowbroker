"""API tests for Strategic Risk Analytics routes."""

from __future__ import annotations

import pytest

from analytics.integration import reset_gt_engine
from services.fetchers import _store


@pytest.fixture(autouse=True)
def _reset_gt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GT_ANALYTICS_ENABLED", raising=False)
    reset_gt_engine()


def test_risk_heatmap_disabled(client) -> None:
    response = client.get("/api/analytics/risk_heatmap")
    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is False
    assert payload["type"] == "FeatureCollection"
    assert payload["features"] == []


def test_dossier_disabled(client) -> None:
    response = client.get("/api/analytics/dossier/ukraine")
    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is False
    assert payload["region"] == "ukraine"


def test_risk_heatmap_enabled_after_refresh(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GT_ANALYTICS_ENABLED", "true")
    reset_gt_engine()

    _store.latest_data["telegram_osint"] = {
        "posts": [
            {
                "id": "api-tg-1",
                "title": "Troop buildup",
                "description": "Troop movement and armored convoy reported near border.",
                "source": "t.me/war_monitor",
                "channel": "war_monitor",
                "coords": [48.5, 37.5],
            }
        ],
        "total": 1,
        "geolocated": 1,
    }
    _store.latest_data["news"] = []
    _store.latest_data["gdelt"] = []

    from analytics.integration import refresh_from_latest_data

    refresh_from_latest_data(dict(_store.latest_data), persist=True)

    response = client.get("/api/analytics/risk_heatmap")
    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    assert len(payload["features"]) >= 1
    assert payload["timestamp"] is not None


def test_dossier_enabled(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GT_ANALYTICS_ENABLED", "true")
    reset_gt_engine()

    _store.latest_data["telegram_osint"] = {
        "posts": [
            {
                "id": "api-tg-2",
                "title": "Strike",
                "description": "General strike and protest mobilization in capital.",
                "source": "t.me/nexta_live",
                "channel": "nexta_live",
                "coords": [50.45, 30.52],
            }
        ]
    }
    _store.latest_data["news"] = []
    _store.latest_data["gdelt"] = []

    from analytics.integration import refresh_from_latest_data

    refresh_from_latest_data(dict(_store.latest_data), persist=True)

    response = client.get("/api/analytics/dossier/50.45,30.52")
    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    assert payload["recent_signals"]
    assert "interpretation" in payload


def test_post_risk_heatmap_ingest(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GT_ANALYTICS_ENABLED", "true")
    reset_gt_engine()

    response = client.post(
        "/api/analytics/risk_heatmap",
        json={
            "refresh": False,
            "items": [
                {
                    "title": "GPS interference",
                    "description": "GPS jamming spike along northern corridor.",
                    "source": "manual",
                    "region": "baltics",
                    "domain": "conflict",
                }
            ],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    assert payload["ingested"] == 1


def test_backtest_disabled(client) -> None:
    response = client.get("/api/analytics/backtest")
    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is False


def test_backtest_enabled(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GT_ANALYTICS_ENABLED", "true")
    reset_gt_engine()

    response = client.get("/api/analytics/backtest?expanded=true&tune=false")
    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    assert payload["accuracy"] == 1.0
    assert payload["confidence_rate"] >= 0.95
    assert payload["meets_target"] is True
    assert payload["total_cases"] >= 80