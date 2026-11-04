"""Issue #650: /api/summary is a small, flat payload for home-dashboard widgets."""

import json

from services.fetchers import _store

EXPECTED_KEYS = {
    "threat_level",
    "threat_score",
    "threat_color",
    "threat_driver",
    "flights",
    "military_flights",
    "private_flights",
    "tracked_flights",
    "ships",
    "satellites",
    "uavs",
    "earthquakes",
    "incidents",
    "gps_jamming_zones",
    "news",
    "fires",
    "cctv",
    "last_updated",
    "version",
}


def _seed(monkeypatch, **values):
    for key in (
        "threat_level",
        "commercial_flights",
        "military_flights",
        "private_flights",
        "private_jets",
        "tracked_flights",
        "ships",
        "satellites",
        "uavs",
        "earthquakes",
        "liveuamap",
        "gdelt",
        "gps_jamming",
        "news",
        "firms_fires",
        "cctv",
        "last_updated",
    ):
        monkeypatch.setitem(_store.latest_data, key, values.get(key))


def test_summary_reports_threat_level_and_counts(client, monkeypatch):
    _seed(
        monkeypatch,
        threat_level={
            "score": 63,
            "level": "ELEVATED",
            "color": "#eab308",
            "drivers": ["Military flight spike: 41 tracked", "GPS jamming: 2 HIGH + 1 MED zones"],
        },
        commercial_flights=[{}] * 5,
        military_flights=[{}] * 3,
        private_flights=[{}] * 2,
        private_jets=[{}],
        ships=[{}] * 4,
        liveuamap=[{}] * 2,
        gdelt=[{}] * 3,
        gps_jamming=[{}, {}],
        last_updated="2026-11-04T20:00:00Z",
    )

    r = client.get("/api/summary")

    assert r.status_code == 200
    data = r.json()
    assert set(data) == EXPECTED_KEYS
    assert data["threat_level"] == "ELEVATED"
    assert data["threat_score"] == 63
    assert data["threat_color"] == "#eab308"
    assert data["threat_driver"] == "Military flight spike: 41 tracked"
    assert data["flights"] == 5
    assert data["military_flights"] == 3
    assert data["private_flights"] == 3
    assert data["ships"] == 4
    assert data["incidents"] == 5
    assert data["gps_jamming_zones"] == 2
    assert data["satellites"] == 0
    assert data["last_updated"] == "2026-11-04T20:00:00Z"


def test_summary_before_first_threat_cycle_is_unknown_not_green(client, monkeypatch):
    _seed(monkeypatch)

    data = client.get("/api/summary").json()

    assert data["threat_level"] == "UNKNOWN"
    assert data["threat_score"] is None
    assert data["threat_driver"] is None
    assert data["flights"] == 0


def test_summary_is_flat_and_small(client, monkeypatch):
    # Widgets map one key per field, so nothing nested; and it must stay cheap
    # to poll even when the dashboard is tracking thousands of entities.
    _seed(monkeypatch, commercial_flights=[{"callsign": "X" * 50}] * 20000, ships=[{}] * 20000)

    r = client.get("/api/summary")

    assert all(not isinstance(v, (dict, list)) for v in r.json().values())
    assert len(r.content) < 2048
    assert json.loads(r.content)["flights"] == 20000


def test_summary_needs_no_auth(client, monkeypatch):
    _seed(monkeypatch)
    assert client.get("/api/summary").status_code == 200
