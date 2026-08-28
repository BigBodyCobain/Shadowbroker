import json

from services import qazlake_shadow_feed as feed


def test_qazpipe_mode_never_falls_back_to_local(monkeypatch) -> None:
    monkeypatch.setenv(
        "SHADOW_LAYER_SOURCE_MODES", json.dumps({"earthquakes": "qazpipe"})
    )
    monkeypatch.setattr(feed, "_items_by_family", dict)
    with feed._lock:
        feed._state.update({"entities": {}, "stale": True, "watermark": None})
    payload = feed.apply_layer_source_modes(
        {"earthquakes": [{"id": "old-local"}]}, endpoint="slow"
    )
    assert payload["earthquakes"] == []
    assert payload["qazpipe_state"]["status"] == "stale"


def test_compare_preserves_public_payload_and_records_receipt(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv(
        "SHADOW_LAYER_SOURCE_MODES", json.dumps({"earthquakes": "compare"})
    )
    monkeypatch.setenv(
        "SHADOW_QAZPIPE_COMPARE_RECEIPT_PATH", str(tmp_path / "receipts.jsonl")
    )
    monkeypatch.setattr(
        feed,
        "_items_by_family",
        lambda: {"earthquakes": {"earthquakes": [{"id": "q-1"}]}},
    )
    with feed._lock:
        feed._state.update(
            {"entities": {"q-1": {}}, "stale": False, "watermark": {"cursor": 7}}
        )
    local = [{"id": "local-1"}]
    original = {"earthquakes": local}
    payload = feed.apply_layer_source_modes(original, endpoint="slow")
    assert payload == {"earthquakes": local}
    assert payload["earthquakes"] is local
    receipt = json.loads((tmp_path / "receipts.jsonl").read_text().strip())
    assert receipt["layer_family"] == "earthquakes"
    assert receipt["layer_key"] == "earthquakes"
    assert receipt["local_count"] == 1
    assert receipt["qazlake_count"] == 1
    assert receipt["accepted"] is False
    assert "canonical_identity" in receipt["failed_gates"]


def test_compare_preserves_public_payload_when_receipt_is_unwritable(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv(
        "SHADOW_LAYER_SOURCE_MODES", json.dumps({"earthquakes": "compare"})
    )
    monkeypatch.setenv("SHADOW_QAZPIPE_COMPARE_RECEIPT_PATH", str(tmp_path))
    monkeypatch.setattr(
        feed,
        "_items_by_family",
        lambda: {"earthquakes": {"earthquakes": [{"id": "q-1"}]}},
    )
    with feed._lock:
        feed._state.update(
            {"entities": {"q-1": {}}, "stale": False, "watermark": {"cursor": 7}}
        )
    local = [{"id": "local-1"}]
    payload = feed.apply_layer_source_modes({"earthquakes": local}, endpoint="slow")
    assert payload == {"earthquakes": local}


def test_deterministic_comparison_requires_exact_ids_and_counts(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv(
        "SHADOW_LAYER_SOURCE_MODES", json.dumps({"earthquakes": "compare"})
    )
    monkeypatch.setenv(
        "SHADOW_COMPARE_FAMILY_KINDS", json.dumps({"earthquakes": "deterministic"})
    )
    monkeypatch.setenv(
        "SHADOW_COMPARE_REQUIRED_FIELDS", json.dumps({"earthquakes": ["magnitude"]})
    )
    monkeypatch.setenv(
        "SHADOW_COMPARE_CADENCE_SECONDS", json.dumps({"earthquakes": 3600})
    )
    monkeypatch.setenv(
        "SHADOW_QAZPIPE_COMPARE_RECEIPT_PATH", str(tmp_path / "receipt.jsonl")
    )
    rows = [
        {
            "id": "q-1",
            "magnitude": 4.2,
            "observed_at": "2026-08-28T00:00:00Z",
        }
    ]
    monkeypatch.setattr(
        feed,
        "_items_by_family",
        lambda: {"earthquakes": {"earthquakes": rows}},
    )
    with feed._lock:
        feed._state.update(
            {"entities": {"q-1": {}}, "stale": False, "watermark": {"cursor": 7}}
        )
    feed.apply_layer_source_modes({"earthquakes": list(rows)}, endpoint="slow")
    receipt = json.loads((tmp_path / "receipt.jsonl").read_text().strip())
    assert receipt["canonical_ids_exact"] is True
    assert receipt["required_null_rate_delta"] == 0
    assert receipt["watermark_valid"] is True
    assert receipt["accepted"] is True


def test_family_mode_maps_to_existing_public_layer_keys(monkeypatch) -> None:
    monkeypatch.setenv(
        "SHADOW_LAYER_SOURCE_MODES", json.dumps({"geohazards": "qazpipe"})
    )
    monkeypatch.setattr(
        feed,
        "_items_by_family",
        lambda: {
            "geohazards": {
                "earthquakes": [{"id": "eq-1"}],
                "volcanoes": [{"id": "volcano-1"}],
            }
        },
    )
    with feed._lock:
        feed._state.update(
            {"entities": {"eq-1": {}}, "stale": False, "watermark": {"cursor": 8}}
        )
    payload = feed.apply_layer_source_modes(
        {"earthquakes": [{"id": "local"}], "volcanoes": [], "unrelated": [1]},
        endpoint="slow",
    )
    assert payload["earthquakes"] == [{"id": "eq-1"}]
    assert payload["volcanoes"] == [{"id": "volcano-1"}]
    assert payload["unrelated"] == [1]
    assert "geohazards" not in payload


def test_public_projection_does_not_expose_provider_or_receipt() -> None:
    item = feed._public_item(
        {
            "entity_id": "entity-1",
            "provider_id": "private-provider",
            "source_id": "source",
            "collection_receipt_id": "receipt",
            "payload_hash_sha256": "a" * 64,
            "properties": {"layer_family": "earthquakes", "magnitude": 4.2},
            "latitude": 43.2,
            "longitude": 76.9,
            "observed_at": "2026-08-28T00:00:00Z",
        }
    )
    assert item["id"] == "entity-1"
    assert {
        "provider_id",
        "source_id",
        "collection_receipt_id",
        "payload_hash_sha256",
    }.isdisjoint(item)


def test_public_projection_preserves_earthquake_shape() -> None:
    item = feed._public_item(
        {
            "entity_id": "us-test-1",
            "properties": {
                "layer_family": "geohazards",
                "layer_key": "earthquakes",
                "magnitude": 4.2,
                "place": "Kazakhstan region",
            },
            "latitude": 43.2,
            "longitude": 76.9,
            "observed_at": "2026-08-28T00:00:00Z",
        }
    )
    assert item["mag"] == 4.2
    assert item["place"] == "Kazakhstan region"
    assert item["lat"] == 43.2
    assert item["lng"] == 76.9


def test_public_projection_preserves_air_quality_shape() -> None:
    item = feed._public_item(
        {
            "entity_id": "station-1",
            "properties": {
                "layer_family": "weather_environment",
                "layer_key": "air_quality",
                "name": "Almaty station",
                "country_code": "KZ",
                "pm25_ug_m3": 18.4,
                "aqi_us_epa": 63,
            },
            "latitude": 43.2,
            "longitude": 76.9,
            "observed_at": "2026-08-28T00:00:00Z",
        }
    )
    assert item["name"] == "Almaty station"
    assert item["country"] == "KZ"
    assert item["pm25"] == 18.4
    assert item["aqi"] == 63


def test_public_projection_preserves_space_weather_singleton_shape() -> None:
    older = feed._public_item(
        {
            "entity_id": "space_weather",
            "properties": {
                "layer_family": "weather_environment",
                "layer_key": "space_weather",
                "category": "quiet",
                "kp_index": 2.0,
            },
            "observed_at": "2026-08-28T06:00:00Z",
        }
    )
    latest = feed._public_item(
        {
            "entity_id": "space_weather",
            "properties": {
                "layer_family": "weather_environment",
                "layer_key": "space_weather",
                "category": "g1_minor",
                "kp_index": 5.0,
            },
            "observed_at": "2026-08-28T09:00:00Z",
        }
    )

    projected = feed._public_layer_value("space_weather", [older, latest])

    assert projected["kp_index"] == 5.0
    assert projected["kp_text"] == "STORM G1"
    assert projected["events"] == []
    assert isinstance(projected, dict)


def test_space_weather_compare_uses_stable_singleton_identity(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv(
        "SHADOW_LAYER_SOURCE_MODES", json.dumps({"weather_environment": "compare"})
    )
    monkeypatch.setenv(
        "SHADOW_LAYER_FAMILY_KEYS",
        json.dumps({"weather_environment": ["space_weather"]}),
    )
    monkeypatch.setenv(
        "SHADOW_COMPARE_FAMILY_KINDS",
        json.dumps({"weather_environment": "deterministic"}),
    )
    monkeypatch.setenv(
        "SHADOW_QAZPIPE_COMPARE_RECEIPT_PATH", str(tmp_path / "receipt.jsonl")
    )
    candidate = {
        "id": "space_weather",
        "kp_index": 5.0,
        "observed_at": "2026-08-28T09:00:00Z",
    }
    monkeypatch.setattr(
        feed,
        "_items_by_family",
        lambda: {"weather_environment": {"space_weather": [candidate]}},
    )
    with feed._lock:
        feed._state.update(
            {
                "entities": {"space_weather": {}},
                "stale": False,
                "watermark": {"cursor": 9},
            }
        )
    local = {"kp_index": 5.0, "observed_at": "2026-08-28T09:00:00Z"}

    payload = feed.apply_layer_source_modes({"space_weather": local}, endpoint="fast")

    assert payload == {"space_weather": local}
    receipt = json.loads((tmp_path / "receipt.jsonl").read_text().strip())
    assert receipt["canonical_ids_exact"] is True
    assert receipt["local_count"] == 1
    assert receipt["qazlake_count"] == 1
    assert receipt["accepted"] is True


def test_satnogs_projection_preserves_public_shape_without_media_urls() -> None:
    station = feed._public_item(
        {
            "entity_id": "satnogs_station:12",
            "latitude": 43.24,
            "longitude": 76.95,
            "observed_at": "2026-08-28T10:00:00Z",
            "properties": {
                "layer_family": "orbital_public",
                "layer_key": "satnogs_stations",
                "name": "Almaty station",
                "status": "online",
                "altitude_m": 850,
                "antenna": "Turnstile",
                "observation_count": 42,
                "last_seen_at": "2026-08-28T10:00:00Z",
            },
        }
    )
    observation = feed._public_item(
        {
            "entity_id": "satellite_observation:99",
            "latitude": 43.24,
            "longitude": 76.95,
            "observed_at": "2026-08-28T10:00:00Z",
            "properties": {
                "layer_family": "orbital_public",
                "layer_key": "satnogs_observations",
                "satellite_name": "ISS (ZARYA)",
                "norad_catalog_id": 25544,
                "station_name": "Almaty station",
                "started_at": "2026-08-28T10:00:00Z",
                "ended_at": "2026-08-28T10:05:00Z",
                "frequency_hz": 145800000,
                "mode": "FM",
                "status": "good",
            },
        }
    )

    assert station["altitude"] == 850
    assert station["observations"] == 42
    assert station["last_seen"] == "2026-08-28T10:00:00Z"
    assert observation["norad_id"] == 25544
    assert observation["start"] == "2026-08-28T10:00:00Z"
    assert observation["end"] == "2026-08-28T10:05:00Z"
    assert observation["frequency"] == 145800000
    assert "waterfall" not in observation
    assert "audio" not in observation


def test_cisa_projection_preserves_public_shape_and_keeps_risk_derived() -> None:
    item = feed._public_item(
        {
            "entity_id": "known_exploited_vulnerability:CVE-2026-12345",
            "observed_at": "2026-08-27T00:00:00Z",
            "properties": {
                "layer_family": "cyber_public",
                "layer_key": "cyber_threats",
                "entity_type": "known_exploited_vulnerability",
                "status": "catalogued",
                "cve_id": "CVE-2026-12345",
                "name": "Example Vulnerability",
                "vendor": "Example Vendor",
                "product": "Example Product",
                "date_added": "2026-08-27",
                "due_date": "2026-09-10",
                "known_ransomware_use": "Unknown",
                "catalog_version": "2026.08.27",
                "catalog_released_at": "2026-08-27T17:00:36+00:00",
                "catalog_count": 1685,
            },
        }
    )

    projected = feed._public_layer_value("cyber_threats", [item])

    assert projected == {
        "threats": [
            {
                "id": "CVE-2026-12345",
                "name": "Example Vulnerability",
                "vendor": "Example Vendor",
                "product": "Example Product",
                "severity": "CRITICAL",
                "date": "2026-08-27",
                "due": "2026-09-10",
                "source": "CISA KEV",
            }
        ],
        "stats": {
            "cisa_total": 1685,
            "active_cves": 1,
            "threat_level": "ELEVATED",
        },
        "timestamp": "2026-08-27T17:00:36+00:00",
    }
    assert "severity" not in item
    assert "threat_level" not in item


def test_weather_alert_projection_preserves_shape_and_filters_expired() -> None:
    current = feed._public_item(
        {
            "entity_id": "weather_alert:urn:oid:current",
            "observed_at": "2099-08-28T11:34:00Z",
            "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [0, 0]]]},
            "properties": {
                "layer_family": "weather_environment",
                "layer_key": "weather_alerts",
                "entity_type": "weather_alert",
                "status": "active",
                "alert_id": "urn:oid:current",
                "event": "Special Weather Statement",
                "severity": "Moderate",
                "certainty": "Observed",
                "urgency": "Expected",
                "headline": "Example headline",
                "description": "Example description",
                "expires_at": "2099-08-28T12:00:00Z",
            },
        }
    )
    expired = {
        **current,
        "id": "urn:oid:expired",
        "expires": "2000-01-01T00:00:00Z",
        "expires_at": "2000-01-01T00:00:00Z",
    }

    assert feed._public_layer_value("weather_alerts", [expired, current]) == [current]
    assert current["id"] == "urn:oid:current"
    assert current["event"] == "Special Weather Statement"
    assert current["expires"] == "2099-08-28T12:00:00Z"
    assert current["geometry"]["type"] == "Polygon"
