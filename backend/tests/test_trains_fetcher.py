from services.fetchers import trains as train_fetcher
from services.fetchers._store import _data_lock, latest_data


def setup_function():
    train_fetcher._TRAIN_TRACK_CACHE.clear()
    with _data_lock:
        latest_data["trains"] = []


def test_merge_nonredundant_trains_prefers_higher_priority_source_and_backfills_fields():
    lower_fidelity = train_fetcher._normalize_train(
        source="amtrak",
        raw_id="AMTK-8",
        number="8",
        lat=40.0000,
        lng=-75.0000,
        route="New York -> Chicago",
        status="On Time",
        operator="Shared Rail",
        country="US",
        observed_at="2026-03-22T18:00:00Z",
    )
    higher_fidelity = train_fetcher._normalize_train(
        source="digitraffic",
        raw_id="FIN-8",
        number="8",
        lat=40.0080,
        lng=-75.0020,
        speed_kmh=128.4,
        status="Active",
        operator="Shared Rail",
        country="US",
        observed_at="2026-03-22T18:00:05Z",
    )

    merged = train_fetcher._merge_nonredundant_trains([lower_fidelity], [higher_fidelity])

    assert len(merged) == 1
    train = merged[0]
    assert train["source"] == "digitraffic"
    assert train["speed_kmh"] == 128.4
    assert train["route"] == "New York -> Chicago"
    assert train["source_label"] == "Digitraffic Finland"


def test_motion_estimates_infer_speed_and_heading_from_previous_position():
    first = train_fetcher._normalize_train(
        source="amtrak",
        raw_id="AMTK-14",
        number="14",
        lat=40.0000,
        lng=-75.0000,
        observed_at=1_000,
    )
    assert first is not None
    second = train_fetcher._normalize_train(
        source="amtrak",
        raw_id="AMTK-14",
        number="14",
        lat=40.0000,
        lng=-74.9900,
        observed_at=1_060,
    )

    assert second is not None
    assert second["speed_kmh"] is not None
    assert 40.0 <= second["speed_kmh"] <= 80.0
    assert second["heading"] is not None
    assert 80.0 <= second["heading"] <= 100.0


def test_fetch_trains_merges_sources_into_store(monkeypatch):
    def _batch_one():
        return [
            train_fetcher._normalize_train(
                source="amtrak",
                raw_id="AMTK-22",
                number="22",
                lat=41.0000,
                lng=-87.0000,
                route="Chicago -> St. Louis",
                operator="Shared Rail",
                country="US",
                observed_at="2026-03-22T19:00:00Z",
            )
        ]

    def _batch_two():
        return [
            train_fetcher._normalize_train(
                source="digitraffic",
                raw_id="FIN-22",
                number="22",
                lat=41.0040,
                lng=-87.0010,
                speed_kmh=96.0,
                operator="Shared Rail",
                country="US",
                observed_at="2026-03-22T19:00:05Z",
            )
        ]

    monkeypatch.setattr(
        train_fetcher,
        "_TRAIN_FETCHERS",
        (("amtrak", _batch_one), ("digitraffic", _batch_two)),
    )

    train_fetcher.fetch_trains()

    with _data_lock:
        trains = list(latest_data["trains"])

    assert len(trains) == 1
    assert trains[0]["source"] == "digitraffic"
    assert trains[0]["route"] == "Chicago -> St. Louis"
    assert trains[0]["speed_kmh"] == 96.0


def test_fetch_trains_preserves_last_good_snapshot_when_refresh_fails(monkeypatch):
    with _data_lock:
        latest_data["trains"] = [
            {
                "id": "AMTK-1",
                "name": "Sunset Limited",
                "number": "1",
                "source": "amtrak",
                "lat": 32.33,
                "lng": -109.76,
                "speed_kmh": None,
                "heading": None,
                "status": "On Time",
                "route": "New Orleans -> Los Angeles",
            }
        ]

    monkeypatch.setattr(
        train_fetcher,
        "_TRAIN_FETCHERS",
        (("amtrak", lambda: []), ("digitraffic", lambda: [])),
    )

    train_fetcher.fetch_trains()

    with _data_lock:
        trains = list(latest_data["trains"])

    assert len(trains) == 1
    assert trains[0]["id"] == "AMTK-1"
