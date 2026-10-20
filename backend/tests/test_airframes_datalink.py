import json
from unittest.mock import patch

import pytest


@pytest.fixture
def airframes_env(tmp_path, monkeypatch):
    from services.fetchers import airframes

    cache_path = tmp_path / "airframes_datalink_cache.json"
    monkeypatch.setattr(airframes, "_CACHE_PATH", cache_path)
    monkeypatch.setattr(airframes, "_DATA_DIR", tmp_path)
    airframes._cache = {
        "last_sync_at": None,
        "last_success_at": None,
        "last_error": None,
        "pages_fetched": 0,
        "messages_ingested": 0,
        "priority_aircraft_synced": 0,
        "bulk_pages_this_cycle": 0,
        "ticks_processed": 0,
        "by_icao": {},
        "by_tail": {},
        "by_callsign": {},
    }
    airframes._queue.clear()
    airframes._queued_aircraft_keys.clear()
    airframes._bulk_cursor = {"since_iso": "", "before_id": None, "pages": 0}
    airframes._cache_loaded = True
    airframes._api_key_known_configured = True
    monkeypatch.setenv("AIRFRAMES_API_KEY", "test-key")
    return airframes


def test_sync_skips_without_api_key(airframes_env, monkeypatch):
    monkeypatch.delenv("AIRFRAMES_API_KEY", raising=False)
    airframes_env._api_key_known_configured = None
    result = airframes_env.sync_airframes_messages(force=True)
    assert result["ok"] is False
    assert result["skipped"] is True


@patch("services.fetchers.airframes.requests.get")
def test_sync_ingests_messages(mock_get, airframes_env):
    from datetime import datetime, timezone

    recent = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    mock_get.return_value.status_code = 200
    mock_get.return_value.headers = {}
    mock_get.return_value.json.return_value = [
        {
            "id": 101,
            "timestamp": recent,
            "label": "H1",
            "text": "ETA 1432",
            "sourceType": "acars",
            "fromHex": "A022B9",
            "tail": "9H-TJZ",
            "flightNumber": "CXI3SY",
        }
    ]

    result = airframes_env.sync_airframes_messages(force=True)
    assert result["ok"] is True
    assert result["queued"] >= 1

    ingested = airframes_env._process_one_staggered_tick()
    assert ingested == 1

    lookup = airframes_env.lookup_datalink_messages(
        icao24="a022b9",
        registration="9H-TJZ",
        callsign="CXI3SY",
        allow_live=False,
    )
    assert lookup["configured"] is True
    assert len(lookup["messages"]) == 1
    assert lookup["messages"][0]["text"] == "ETA 1432"


def test_lookup_queues_priority_scan_on_every_open(airframes_env):
    lookup = airframes_env.lookup_datalink_messages(icao24="abc123", allow_live=False)
    assert lookup["configured"] is True
    assert lookup["messages"] == []
    assert lookup["queued_refresh"] is True
    assert lookup["priority_scan"] is True
    with airframes_env._queue_lock:
        assert airframes_env._queue[0]["type"] == "aircraft"
        assert airframes_env._queue[0]["icao24"] == "abc123"


def test_priority_scan_jumps_ahead_of_bulk(airframes_env):
    airframes_env._refill_queue(since_iso="2026-01-01T00:00:00Z", force=True)
    with airframes_env._queue_lock:
        assert airframes_env._queue[0]["type"] == "bulk"

    airframes_env.lookup_datalink_messages(icao24="deadbeef", allow_live=False)

    with airframes_env._queue_lock:
        assert airframes_env._queue[0]["type"] == "aircraft"
        assert airframes_env._queue[0]["icao24"] == "deadbeef"


def test_lookup_still_queues_when_cache_hit(airframes_env):
    from datetime import datetime, timezone

    recent = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    airframes_env._ingest_message(
        {
            "id": 404,
            "timestamp": recent,
            "text": "CACHED MSG",
            "fromHex": "a022b9",
        }
    )
    lookup = airframes_env.lookup_datalink_messages(icao24="a022b9", allow_live=False)
    assert len(lookup["messages"]) == 1
    assert lookup["priority_scan"] is True
    with airframes_env._queue_lock:
        assert airframes_env._queue[0]["icao24"] == "a022b9"


def test_lookup_unconfigured_shows_hint(airframes_env, monkeypatch):
    monkeypatch.delenv("AIRFRAMES_API_KEY", raising=False)
    airframes_env._api_key_known_configured = None
    lookup = airframes_env.lookup_datalink_messages(icao24="abc123")
    assert lookup["configured"] is False
    assert lookup["messages"] == []
    assert "AIRFRAMES_API_KEY" in lookup["hint"]


def test_lookup_indexes_to_hex_and_callsign(airframes_env):
    from datetime import datetime, timezone

    recent = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    airframes_env._ingest_message(
        {
            "id": 202,
            "timestamp": recent,
            "text": "DESCENT TO FL100",
            "fromHex": "ABCDEF",
            "toHex": "a022b9",
            "flightNumber": "RCH123",
        }
    )

    by_icao = airframes_env.lookup_datalink_messages(icao24="a022b9", allow_live=False)
    assert len(by_icao["messages"]) == 1

    by_callsign = airframes_env.lookup_datalink_messages(callsign="RCH123", allow_live=False)
    assert len(by_callsign["messages"]) == 1


def test_tail_lookup_normalizes_dashes(airframes_env):
    from datetime import datetime, timezone

    recent = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    airframes_env._ingest_message(
        {
            "id": 303,
            "timestamp": recent,
            "text": "ON GROUND",
            "tail": "9H-TJZ",
        }
    )

    lookup = airframes_env.lookup_datalink_messages(registration="9HTJZ", allow_live=False)
    assert len(lookup["messages"]) == 1


def test_api_registry_includes_airframes_key():
    from services.api_settings import API_REGISTRY, ALLOWED_ENV_KEYS

    entry = next(item for item in API_REGISTRY if item["id"] == "airframes_api_key")
    assert entry["env_key"] == "AIRFRAMES_API_KEY"
    assert "AIRFRAMES_API_KEY" in ALLOWED_ENV_KEYS
