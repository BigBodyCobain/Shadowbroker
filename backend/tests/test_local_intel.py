import pytest

from services.local_intel import build_local_intel


@pytest.fixture(autouse=True)
def _suppress_background_services():
    yield


def test_local_intel_ranks_nearby_signals():
    data = {
        "military_flights": [
            {
                "callsign": "RCH123",
                "model": "C17",
                "lat": 39.95,
                "lng": -75.16,
                "alt": 21000,
                "speed_knots": 330,
            }
        ],
        "earthquakes": [
            {"id": "q1", "mag": 4.8, "lat": 40.1, "lng": -75.2, "place": "near test point"}
        ],
        "gdelt": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-75.25, 40.05]},
                "properties": {
                    "name": "Port disruption",
                    "count": 12,
                    "num_mentions": 55,
                    "_headlines_list": ["Port disruption reported"],
                },
            }
        ],
        "datacenters": [{"name": "PHL-1", "company": "Example DC", "lat": 41.5, "lng": -80.0}],
    }

    result = build_local_intel(lat=40.0, lng=-75.0, radius_km=75, data=data, freshness={})

    labels = [item["label"] for item in result["items"]]
    assert "RCH123" in labels
    assert "M4.8 earthquake" in labels
    assert "Port disruption" in labels
    assert "PHL-1" not in labels
    assert result["summary"]["categories"]["air"] == 1
    assert result["summary"]["highest_severity"] in {"critical", "elevated"}


def test_local_intel_centroids_weather_polygons():
    data = {
        "weather_alerts": [
            {
                "id": "wx1",
                "event": "Severe Thunderstorm Warning",
                "severity": "Severe",
                "headline": "Storm warning",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[-75.1, 39.9], [-74.9, 39.9], [-74.9, 40.1], [-75.1, 40.1], [-75.1, 39.9]]],
                },
            }
        ]
    }

    result = build_local_intel(lat=40.0, lng=-75.0, radius_km=20, data=data, freshness={})

    assert result["summary"]["total"] == 1
    assert result["items"][0]["category"] == "hazard"
    assert result["items"][0]["severity"] == "critical"
