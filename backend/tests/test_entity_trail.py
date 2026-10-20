"""Tests for entity trail resolution."""

import pytest
from unittest.mock import patch


@pytest.fixture()
def sample_store():
    from services.fetchers._store import latest_data, _data_lock

    with _data_lock:
        backup = {"tracked_flights": list(latest_data.get("tracked_flights") or [])}
        latest_data["tracked_flights"] = [
            {
                "callsign": "AF1",
                "registration": "82-8000",
                "icao24": "adfdf8",
                "alert_operator": "POTUS",
                "type": "B744",
                "lat": 38.95,
                "lng": -77.45,
            },
            {
                "callsign": "OXE2116",
                "registration": "N36NE",
                "icao24": "a0f011",
                "operator": "Patriots",
                "type": "Boeing 767-323ER",
                "lat": 39.24,
                "lng": -96.96,
            },
        ]
        latest_data["ships"] = [
            {
                "mmsi": 366999999,
                "name": "BRAVO EUGENIA",
                "lat": 25.77,
                "lng": -80.13,
                "shipType": 37,
            }
        ]
    try:
        yield
    finally:
        with _data_lock:
            latest_data["tracked_flights"] = backup["tracked_flights"]


def test_get_entity_trail_aircraft_with_mock_trail(sample_store):
    from services.entity_trail import get_entity_trail
    from services.fetchers import flights

    flights.flight_trails["a0f011"] = {
        "points": [
            [39.0, -97.0, 35000, 1000.0],
            [39.2, -96.9, 36000, 1060.0],
            [39.24, -96.96, 37000, 1120.0],
        ],
        "last_seen": 1120.0,
    }

    result = get_entity_trail(registration="N36NE", include_datalink=False)
    assert result["status"] == "trail_available"
    assert result["entity_kind"] == "aircraft"
    assert len(result["trail"]) == 3
    assert result["movement"]["bearing_deg"] is not None
    assert "Trail points are observed" in result["notes"][0]


def test_get_entity_trail_ship(sample_store):
    from services.entity_trail import get_entity_trail
    from services import ais_stream

    ais_stream._vessel_trails[366999999] = {
        "points": [
            [25.7, -80.1, 12, 2000.0],
            [25.8, -80.2, 12, 2120.0],
        ],
        "last_seen": 2120.0,
    }

    result = get_entity_trail(mmsi="366999999", entity_type="ship", include_datalink=False)
    assert result["status"] == "trail_available"
    assert result["entity_kind"] == "ship"
    assert len(result["trail"]) == 2


@patch("services.fetchers.route_database.lookup_route")
def test_get_entity_trail_enriches_route_from_database(mock_lookup, sample_store):
    from services.entity_trail import get_entity_trail

    mock_lookup.return_value = {
        "orig_name": "JFK: Kennedy",
        "dest_name": "LAX: Los Angeles",
        "orig_loc": [-73.78, 40.64],
        "dest_loc": [-118.41, 33.94],
    }

    result = get_entity_trail(callsign="AF1", include_datalink=False)
    assert result["route"]["source"] == "route_database"
    assert "Kennedy" in result["route"]["origin_name"]


def test_correlate_entity_includes_movement(sample_store, monkeypatch):
    from services import telemetry
    from services.fetchers import flights

    flights.flight_trails["adfdf8"] = {
        "points": [[38.9, -77.5, 10000, 500.0], [38.95, -77.45, 12000, 560.0]],
        "last_seen": 560.0,
    }

    result = telemetry.correlate_entity(callsign="AF1", entity_type="aircraft", radius_km=80, limit=5)
    assert result["movement"]["trail_point_count"] == 2
    assert len(result["movement"]["trail"]) == 2


def test_openclaw_get_entity_trail_command(sample_store, monkeypatch):
    from services.openclaw_channel import _dispatch_command
    from services.fetchers import flights

    flights.flight_trails["a0f011"] = {
        "points": [[39.0, -97.0, 35000, 1000.0]],
        "last_seen": 1000.0,
    }

    result = _dispatch_command(
        "get_entity_trail",
        {"query": "patriots jet", "compact": True},
    )
    assert result["ok"] is True
    assert result["data"]["status"] in {"trail_available", "resolved_without_trail"}
