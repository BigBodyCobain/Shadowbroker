def test_parse_location_handles_three_part_us_format():
    from services.fetchers.nuforc_enrichment import _parse_location

    city, state = _parse_location("Huntsville, TX, USA")
    assert city == "Huntsville"
    assert state == "TX"


def test_parse_date_handles_current_dataset_suffix():
    from services.fetchers.nuforc_enrichment import _parse_date

    assert _parse_date("2014-09-21 13:00:00 Local") == "2014-09-21"


def test_parse_tilequery_date_handles_local_suffix():
    from services.fetchers.earth_observation import _parse_nuforc_tile_date

    parsed = _parse_nuforc_tile_date("2026-04-08 13:00:00 Local")
    assert parsed is not None
    assert parsed.strftime("%Y-%m-%d") == "2026-04-08"


def test_build_recent_uap_sightings_uses_last_year_csv_and_geocodes(monkeypatch):
    from datetime import datetime as real_datetime
    from services.fetchers import earth_observation as eo

    class FixedDateTime(real_datetime):
        @classmethod
        def utcnow(cls):
            return cls(2026, 4, 8, 12, 0, 0)

    sample_csv = """Sighting,Occurred,Location,Shape,Duration,Posted,Summary,Text
1,2026-04-07 21:15:00 Local,"Denver, CO, USA",Triangle,5 minutes,2026-04-08,"Bright triangle over Denver",
2,2026-03-01 20:00:00 Local,"Seattle, WA, USA",Light,30 seconds,2026-03-02,,"Orb over Puget Sound"
2,2026-03-01 20:00:00 Local,"Seattle, WA, USA",Light,30 seconds,2026-03-02,,"Orb over Puget Sound"
3,2025-03-01 20:00:00 Local,"Phoenix, AZ, USA",Disk,2 minutes,2025-03-02,"Too old",
"""

    class Response:
        status_code = 200
        text = sample_csv

    monkeypatch.setattr(eo, "datetime", FixedDateTime)
    monkeypatch.setattr(eo, "fetch_with_curl", lambda *args, **kwargs: Response())
    monkeypatch.setattr(eo, "_load_nuforc_location_cache", lambda: {"Denver, CO, USA": [39.7392, -104.9903]})
    monkeypatch.setattr(eo, "_save_nuforc_location_cache", lambda cache: None)
    monkeypatch.setattr(
        eo,
        "_geocode_uap_location",
        lambda location, city, state: [47.6062, -122.3321] if location == "Seattle, WA, USA" else None,
    )

    sightings = eo._build_recent_uap_sightings()

    assert [s["id"] for s in sightings] == ["1", "2"]
    assert sightings[0]["city"] == "Denver"
    assert sightings[0]["shape"] == "triangle"
    assert sightings[1]["city"] == "Seattle"
    assert sightings[1]["summary"] == "Orb over Puget Sound"
    assert sightings[1]["lat"] == 47.6062


def test_fetch_uap_sightings_prefers_daily_cache(monkeypatch):
    from services.fetchers import earth_observation as eo
    from services.fetchers import _store

    cached = [{"id": "cached-uap", "date_time": "2026-04-08", "lat": 1.0, "lng": 2.0}]
    marked = []
    monkeypatch.setattr(_store, "is_any_active", lambda layer: True)
    monkeypatch.setattr(eo, "_load_nuforc_sightings_cache", lambda force_refresh=False: cached)
    monkeypatch.setattr(eo, "_build_recent_uap_sightings", lambda: (_ for _ in ()).throw(AssertionError("should not rebuild")))
    monkeypatch.setattr(eo, "_save_nuforc_sightings_cache", lambda sightings: None)
    monkeypatch.setattr(eo, "_mark_fresh", lambda *keys: marked.extend(keys))

    with _store._data_lock:
        _store.latest_data["uap_sightings"] = []

    eo.fetch_uap_sightings()

    with _store._data_lock:
        assert _store.latest_data["uap_sightings"] == cached
    assert marked == ["uap_sightings"]


def test_load_nuforc_sightings_cache_rejects_fresh_empty_snapshot(monkeypatch, tmp_path):
    import json
    from datetime import datetime
    from services.fetchers import earth_observation as eo

    cache_file = tmp_path / "nuforc_recent_sightings.json"
    cache_file.write_text(
        json.dumps(
            {
                "built": datetime.utcnow().isoformat(),
                "count": 0,
                "sightings": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(eo, "_NUFORC_SIGHTINGS_CACHE_FILE", cache_file)

    assert eo._load_nuforc_sightings_cache() is None


def test_uap_geocode_candidates_include_city_state_variants():
    from services.fetchers.earth_observation import _uap_geocode_candidates

    candidates = _uap_geocode_candidates("Denver, CO, USA", "Denver", "CO")

    assert "Denver, CO, USA" in candidates
    assert "Denver, CO" in candidates
    assert "Denver" in candidates
