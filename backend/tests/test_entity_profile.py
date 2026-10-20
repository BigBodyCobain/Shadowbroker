"""Tests for get_entity_profile bundled dossier."""

import pytest
from unittest.mock import patch


@pytest.fixture()
def sample_store():
    from services.fetchers._store import latest_data, _data_lock

    with _data_lock:
        backup = {
            "tracked_flights": list(latest_data.get("tracked_flights") or []),
            "news": list(latest_data.get("news") or []),
        }
        latest_data["tracked_flights"] = [
            {
                "callsign": "OXE2116",
                "registration": "N36NE",
                "icao24": "a0f011",
                "operator": "Patriots",
                "alert_operator": "Patriots",
                "alert_category": "Sports",
                "alert_color": "orange",
                "alert_tags": "NFL, New England Patriots",
                "type": "Boeing 767-323ER",
                "lat": 39.24,
                "lng": -96.96,
                "alt": 37000,
                "heading": 270,
                "holding": False,
                "emissions": {
                    "fuel_gph": 1200,
                    "co2_kg_per_hour": 11500,
                    "fuel_gallons_burned": 2400,
                    "co2_kg_emitted": 23000,
                },
            }
        ]
        latest_data["news"] = [
            {"title": "Patriots travel day", "summary": "Team jet departed", "lat": 39.0, "lng": -97.0}
        ]
    try:
        yield
    finally:
        with _data_lock:
            latest_data["tracked_flights"] = backup["tracked_flights"]
            latest_data["news"] = backup["news"]


def test_get_entity_profile_aircraft(sample_store):
    from services.entity_profile import get_entity_profile
    from services.fetchers import flights

    flights.flight_trails["a0f011"] = {
        "points": [[39.0, -97.0, 35000, 1000.0], [39.24, -96.96, 37000, 1120.0]],
        "last_seen": 1120.0,
    }

    result = get_entity_profile(registration="N36NE", include_nearby_context=False)
    assert result["status"] in {"trail_available", "resolved_without_trail"}
    assert result["identity"]["alert_operator"] == "Patriots"
    assert result["identity"]["alert_category"] == "Sports"
    assert result["aircraft_state"]["emissions"]["fuel_gallons_burned"] == 2400
    assert len(result["trail"]) == 2
    assert "related_news" in result


@patch("services.fetchers.airframes.lookup_datalink_messages")
def test_get_entity_profile_includes_datalink(mock_lookup, sample_store):
    from services.entity_profile import get_entity_profile

    mock_lookup.return_value = {
        "configured": True,
        "messages": [{"summary": "Position / route report · KABQ→KDEN", "text": "POS..."}],
        "hidden_count": 0,
    }

    result = get_entity_profile(registration="N36NE", include_nearby_context=False, include_news=False)
    assert result["datalink"]["configured"] is True
    assert "KABQ" in result["datalink"]["hints"][0]


def test_openclaw_get_entity_profile_command(sample_store):
    from services.openclaw_channel import _dispatch_command
    from services.fetchers import flights

    flights.flight_trails["a0f011"] = {
        "points": [[39.0, -97.0, 35000, 1000.0]],
        "last_seen": 1000.0,
    }

    result = _dispatch_command("get_entity_profile", {"registration": "N36NE", "compact": True})
    assert result["ok"] is True
    assert result["data"]["identity"]["registration"] == "N36NE"


def test_jet_recon_playbook():
    from services.openclaw_routing import plan_playbook

    plan = plan_playbook("jet_recon", {"registration": "N424PX"})
    assert plan["ok"] is True
    assert plan["batch"][0]["cmd"] == "get_entity_profile"
    assert plan["batch"][1]["cmd"] == "correlate_entity"
