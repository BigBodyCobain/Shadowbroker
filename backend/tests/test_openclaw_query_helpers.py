"""Tests for the compact OpenClaw query helpers.

These cover the new server-side lookup path so agents can avoid large
snapshot pulls for common questions.
"""

import pytest


@pytest.fixture()
def sample_store():
    from services.fetchers._store import latest_data, _data_lock

    with _data_lock:
        backup = {
            "tracked_flights": list(latest_data.get("tracked_flights") or []),
            "military_flights": list(latest_data.get("military_flights") or []),
            "private_jets": list(latest_data.get("private_jets") or []),
            "ships": list(latest_data.get("ships") or []),
            "fishing_activity": list(latest_data.get("fishing_activity") or []),
            "wastewater": list(latest_data.get("wastewater") or []),
            "news": list(latest_data.get("news") or []),
            "gdelt": list(latest_data.get("gdelt") or []),
            "crowdthreat": list(latest_data.get("crowdthreat") or []),
            "correlations": list(latest_data.get("correlations") or []),
            "sar_anomalies": list(latest_data.get("sar_anomalies") or []),
            "internet_outages": list(latest_data.get("internet_outages") or []),
            "weather_alerts": list(latest_data.get("weather_alerts") or []),
            "gps_jamming": list(latest_data.get("gps_jamming") or []),
            "military_bases": list(latest_data.get("military_bases") or []),
        }
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
                "category": "Sports",
                "type": "Boeing 767-323ER",
                "intel_tags": "NFL, New England Patriots",
                "lat": 39.24,
                "lng": -96.96,
            },
        ]
        latest_data["military_flights"] = [
            {
                "callsign": "RCH123",
                "registration": "03-3123",
                "icao24": "abcd12",
                "type": "C17",
                "lat": 39.0,
                "lng": -104.7,
            }
        ]
        latest_data["private_jets"] = [
            {
                "callsign": "EJA400",
                "registration": "N400QS",
                "icao24": "beef12",
                "owner": "NetJets",
                "type": "C68A",
                "lat": 40.0,
                "lng": -105.0,
            }
        ]
        latest_data["ships"] = [
            {
                "mmsi": "366999999",
                "imo": "1234567",
                "name": "BRAVO EUGENIA",
                "shipType": "Yacht",
                "yacht_owner": "Jerry Jones",
                "yacht_name": "Bravo Eugenia",
                "yacht_category": "Celebrity / Mogul",
                "lat": 29.7,
                "lng": -95.0,
            }
        ]
        latest_data["fishing_activity"] = [
            {
                "id": "gfw-event-1",
                "name": "Fishing Event Alpha",
                "lat": 12.3,
                "lng": -45.6,
                "flag": "PA",
            }
        ]
        latest_data["wastewater"] = [
            {
                "id": "ww-1",
                "name": "Denver Wastewater Plant",
                "lat": 39.73,
                "lng": -104.99,
            }
        ]
        latest_data["news"] = [
            {
                "title": "Power outage reported near test facility",
                "summary": "Grid instability around Denver area",
                "source": "Example News",
                "link": "https://example.invalid/story",
                "lat": 39.74,
                "lng": -104.99,
                "risk_score": 0.7,
            }
        ]
        latest_data["gdelt"] = [
            {
                "properties": {
                    "title": "Military exercise escalates",
                    "sourceurl": "https://example.invalid/gdelt",
                },
                "geometry": {"coordinates": [-104.8, 39.1]},
            }
        ]
        latest_data["crowdthreat"] = [
            {
                "id": "ct-1",
                "title": "Peaceful Protest Against Administration",
                "summary": "Demonstration in Minnesota suburbs",
                "category": "Protest",
                "city": "Edina",
                "state": "Minnesota",
                "lat": 44.88,
                "lng": -93.32,
            }
        ]
        latest_data["correlations"] = [
            {
                "type": "infra_cascade",
                "severity": "medium",
                "score": 60,
                "drivers": ["Internet outage", "KiwiSDR offline"],
                "lat": 38.97,
                "lng": -77.43,
            }
        ]
        latest_data["sar_anomalies"] = [
            {
                "anomaly_id": "sar-1",
                "kind": "new_object",
                "magnitude": 0.8,
                "lat": 38.96,
                "lon": -77.44,
            }
        ]
        latest_data["internet_outages"] = [
            {
                "id": "outage-1",
                "region": "Northern Virginia",
                "severity": 55,
                "lat": 38.98,
                "lng": -77.42,
            }
        ]
        latest_data["weather_alerts"] = [
            {
                "id": "wx-1",
                "event": "Severe Thunderstorm Warning",
                "headline": "Storms near Washington",
                "severity": "Severe",
                "lat": 38.9,
                "lng": -77.2,
            }
        ]
        latest_data["gps_jamming"] = [
            {
                "id": "gps-1",
                "ratio": 0.8,
                "lat": 38.92,
                "lng": -77.3,
            }
        ]
        latest_data["military_bases"] = [
            {
                "id": "base-1",
                "name": "Joint Base Andrews",
                "lat": 38.81,
                "lng": -76.87,
            }
        ]

    try:
        yield
    finally:
        with _data_lock:
            for key, value in backup.items():
                latest_data[key] = value


def test_find_flights_returns_compact_matches(sample_store, monkeypatch):
    import services.telemetry as telemetry

    monkeypatch.setattr(telemetry, "get_data_version", lambda: 42)
    result = telemetry.find_flights(callsign="AF1", limit=5)

    assert result["version"] == 42
    assert result["truncated"] is False
    assert len(result["results"]) == 1
    match = result["results"][0]
    assert match["source_layer"] == "tracked_flights"
    assert match["callsign"] == "AF1"
    assert match["alert_operator"] == "POTUS"


def test_search_news_matches_news_and_gdelt(sample_store, monkeypatch):
    import services.telemetry as telemetry

    monkeypatch.setattr(telemetry, "get_data_version", lambda: 77)
    result = telemetry.search_news(query="military", limit=10, include_gdelt=True)

    assert result["version"] == 77
    assert result["truncated"] is False
    assert len(result["results"]) == 1
    assert result["results"][0]["source_layer"] == "gdelt"


def test_search_news_matches_crowdthreat_events(sample_store, monkeypatch):
    import services.telemetry as telemetry

    monkeypatch.setattr(telemetry, "get_data_version", lambda: 78)
    result = telemetry.search_news(query="minnesota protest", limit=10, include_gdelt=True)

    assert result["version"] == 78
    assert result["results"]
    assert result["results"][0]["source_layer"] == "crowdthreat"


def test_get_layer_slice_short_circuits_when_version_is_unchanged(sample_store, monkeypatch):
    import services.telemetry as telemetry

    monkeypatch.setattr(telemetry, "get_data_version", lambda: 99)
    result = telemetry.get_layer_slice(
        layers=["tracked_flights", "ships"],
        limit_per_layer=10,
        since_version=99,
    )

    assert result["version"] == 99
    assert result["changed"] is False
    assert result["layers"] == {}
    assert result["requested_layers"] == ["tracked_flights", "ships"]


def test_get_layer_slice_accepts_gfw_alias(sample_store, monkeypatch):
    import services.telemetry as telemetry

    monkeypatch.setattr(telemetry, "get_data_version", lambda: 101)
    result = telemetry.get_layer_slice(
        layers=["global_fishing_watch", "wastewater"],
        limit_per_layer=10,
    )

    assert result["version"] == 101
    assert result["requested_layers"] == ["fishing_activity", "wastewater"]
    assert result["layers"]["fishing_activity"][0]["id"] == "gfw-event-1"
    assert result["layers"]["wastewater"][0]["id"] == "ww-1"


def test_get_layer_slice_is_uncapped_when_limit_is_omitted(sample_store, monkeypatch):
    import services.telemetry as telemetry
    from services.fetchers._store import latest_data, _data_lock

    with _data_lock:
        latest_data["fishing_activity"] = [
            {"id": "gfw-event-1", "lat": 12.3, "lng": -45.6},
            {"id": "gfw-event-2", "lat": 12.4, "lng": -45.7},
        ]

    monkeypatch.setattr(telemetry, "get_data_version", lambda: 111)
    result = telemetry.get_layer_slice(layers=["fishing_activity"])

    assert result["version"] == 111
    assert len(result["layers"]["fishing_activity"]) == 2
    assert result["truncated"] == {}


def test_get_telemetry_summary_includes_slow_layers(sample_store, monkeypatch):
    import services.telemetry as telemetry

    monkeypatch.setattr(telemetry, "get_data_version", lambda: 202)
    result = telemetry.get_telemetry_summary()

    assert result["version"] == 202
    assert result["counts"]["fishing_activity"] == 1
    assert result["counts"]["wastewater"] == 1
    assert "fishing_activity" in result["available_layers"]
    assert result["layer_aliases"]["global_fishing_watch"] == "fishing_activity"


def test_entities_near_finds_nearest_results(sample_store, monkeypatch):
    import services.telemetry as telemetry

    monkeypatch.setattr(telemetry, "get_data_version", lambda: 123)
    result = telemetry.entities_near(
        lat=39.0,
        lng=-104.8,
        radius_km=300,
        entity_types=["military", "tracked"],
        limit=10,
    )

    assert result["version"] == 123
    assert result["results"]
    assert result["results"][0]["source_layer"] in {"military_flights", "tracked_flights"}
    assert result["results"][0]["distance_km"] <= 300


def test_find_ships_matches_yacht_owner_enrichment(sample_store, monkeypatch):
    import services.telemetry as telemetry

    monkeypatch.setattr(telemetry, "get_data_version", lambda: 124)
    result = telemetry.find_ships(query="jerry jones", limit=10)

    assert result["version"] == 124
    assert result["results"]
    match = result["results"][0]
    assert match["name"] == "BRAVO EUGENIA"
    assert match["owner"] == "Jerry Jones"
    assert match["tracked_category"] == "Celebrity / Mogul"


def test_search_telemetry_searches_across_layers(sample_store, monkeypatch):
    import services.telemetry as telemetry

    monkeypatch.setattr(telemetry, "get_data_version", lambda: 125)
    result = telemetry.search_telemetry(query="jerry jones", limit=10)

    assert result["version"] == 125
    assert result["results"]
    assert result["results"][0]["source_layer"] == "ships"
    assert result["results"][0]["label"] == "Bravo Eugenia"


def test_search_telemetry_finds_protests_without_layer_pull(sample_store, monkeypatch):
    import services.telemetry as telemetry

    monkeypatch.setattr(telemetry, "get_data_version", lambda: 126)
    result = telemetry.search_telemetry(query="minnesota protest", limit=10)

    assert result["version"] == 126
    assert result["results"]
    assert any(item["source_layer"] == "crowdthreat" for item in result["results"])


def test_search_telemetry_treats_generic_jet_term_as_aircraft_hint(sample_store, monkeypatch):
    import services.telemetry as telemetry

    monkeypatch.setattr(telemetry, "get_data_version", lambda: 127)
    result = telemetry.search_telemetry(query="patriots jet", limit=10)

    assert result["version"] == 127
    assert result["results"]
    top = result["results"][0]
    assert top["source_layer"] == "tracked_flights"
    assert top["group"] == "aircraft"
    assert top["label"] == "OXE2116"
    assert "patriots" in top["matched_tokens"]
    assert result["groups"][0]["group"] == "aircraft"


def test_search_telemetry_still_returns_entity_when_query_has_extra_noise(sample_store, monkeypatch):
    import services.telemetry as telemetry

    monkeypatch.setattr(telemetry, "get_data_version", lambda: 128)
    result = telemetry.search_telemetry(query="jerry jones diaper", limit=10)

    assert result["version"] == 128
    assert result["results"]
    top = result["results"][0]
    assert top["source_layer"] == "ships"
    assert top["label"] == "Bravo Eugenia"
    assert "jerry" in top["matched_tokens"]
    assert "jones" in top["matched_tokens"]


def test_search_telemetry_handles_typos_with_cached_index(sample_store, monkeypatch):
    import services.telemetry as telemetry

    monkeypatch.setattr(telemetry, "get_data_version", lambda: 129)
    result = telemetry.search_telemetry(query="patriats jet", limit=10)

    assert result["version"] == 129
    assert result["results"]
    top = result["results"][0]
    assert top["source_layer"] == "tracked_flights"
    assert top["label"] == "OXE2116"
    assert "patriots" in top["matched_tokens"]


def test_find_entity_prioritizes_aircraft_operator_and_callsign(sample_store, monkeypatch):
    import services.telemetry as telemetry

    monkeypatch.setattr(telemetry, "get_data_version", lambda: 130)

    by_operator = telemetry.find_entity(query="patriots jet", limit=5)
    assert by_operator["best_match"]["group"] == "aircraft"
    assert by_operator["best_match"]["label"] == "OXE2116"

    by_callsign = telemetry.find_entity(callsign="AF1", entity_type="aircraft", limit=5)
    assert by_callsign["best_match"]["callsign"] == "AF1"
    assert by_callsign["best_match"]["alert_operator"] == "POTUS"


def test_find_entity_prioritizes_maritime_owner_and_identifiers(sample_store, monkeypatch):
    import services.telemetry as telemetry

    monkeypatch.setattr(telemetry, "get_data_version", lambda: 131)

    by_owner = telemetry.find_entity(query="jerry jones yacht", limit=5)
    assert by_owner["best_match"]["group"] == "maritime"
    assert by_owner["best_match"]["name"] == "BRAVO EUGENIA"

    by_mmsi = telemetry.find_entity(mmsi="366999999", entity_type="ship", limit=5)
    assert by_mmsi["best_match"]["mmsi"] == "366999999"
    assert by_mmsi["best_match"]["owner"] == "Jerry Jones"


def test_openclaw_track_entity_creates_precise_aircraft_watch(sample_store, monkeypatch):
    from services import openclaw_watchdog
    from services.openclaw_channel import _dispatch_command

    monkeypatch.setattr(openclaw_watchdog, "_ensure_running", lambda: None)
    openclaw_watchdog.clear_watches()
    try:
        result = _dispatch_command("track_entity", {"query": "patriots jet"})
        assert result["ok"] is True
        data = result["data"]
        assert data["watch_type"] == "track_aircraft"
        assert data["watch"]["params"]["callsign"] == "OXE2116"
        assert data["initial_lookup"]["best_match"]["group"] == "aircraft"
    finally:
        openclaw_watchdog.clear_watches()


def test_watchdog_aircraft_tracking_reads_split_flight_layers(sample_store):
    from services.openclaw_watchdog import _check_track_aircraft, _check_track_callsign
    from services.telemetry import get_cached_telemetry

    fast = get_cached_telemetry()
    by_callsign = _check_track_callsign({"callsign": "AF1"}, fast)
    assert by_callsign is not None
    assert by_callsign["data"]["source_layer"] == "tracked_flights"

    by_owner = _check_track_aircraft({"owner": "patriots"}, fast)
    assert by_owner is not None
    assert by_owner["data"]["callsign"] == "OXE2116"


def test_correlate_entity_returns_evidence_pack_near_aircraft(sample_store, monkeypatch):
    import services.telemetry as telemetry

    monkeypatch.setattr(telemetry, "get_data_version", lambda: 132)
    result = telemetry.correlate_entity(callsign="AF1", entity_type="aircraft", radius_km=80, limit=5)

    assert result["version"] == 132
    assert result["status"] == "context_found"
    assert result["claim_level"] == "evidence_pack_not_verdict"
    assert result["entity"]["callsign"] == "AF1"
    signal_types = {signal["type"] for signal in result["signals"]}
    assert "existing_correlation_near_entity" in signal_types
    assert "sar_anomaly_near_entity" in signal_types
    assert "infrastructure_disruption_near_entity" in signal_types
    assert "environment_or_rf_hazard_near_entity" in signal_types
    assert result["evidence"]["context_layers"]["correlations"][0]["type"] == "infra_cascade"
    assert result["recommended_next"]


def test_openclaw_correlate_entity_command(sample_store, monkeypatch):
    import services.telemetry as telemetry
    from services.openclaw_channel import _dispatch_command

    monkeypatch.setattr(telemetry, "get_data_version", lambda: 133)
    result = _dispatch_command(
        "correlate_entity",
        {"entity_type": "ship", "mmsi": "366999999", "radius_km": 100},
    )

    assert result["ok"] is True
    data = result["data"]
    assert data["entity"]["mmsi"] == "366999999"
    assert data["claim_level"] == "evidence_pack_not_verdict"
    assert data["status"] in {"context_found", "no_nearby_context"}
