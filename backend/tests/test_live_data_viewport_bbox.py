"""Live-data viewport params are accepted but no longer truncate telemetry."""

import pytest


class TestFastBboxFiltering:
    def _seed_fast(self, monkeypatch):
        from services.fetchers import _store
        from routers import data as data_router

        with data_router._LIVE_DATA_BYTES_CACHE_LOCK:
            data_router._LIVE_DATA_BYTES_CACHE.clear()
        _store.bump_data_version()

        commercial = [
            {"lat": -60.0, "lng": -120.0, "id": "f-sw"},
            {"lat": 35.0, "lng": -75.0, "id": "f-ne"},
            {"lat": 35.0, "lng": 100.0, "id": "f-asia"},
        ]
        ships = [
            {"lat": -60.0, "lng": -120.0, "id": "s-sw"},
            {"lat": 35.0, "lng": -75.0, "id": "s-ne"},
        ]
        cctv = [
            {"lat": 35.0, "lon": -75.0, "id": "c-1"},
            {"lat": 35.0, "lon": 100.0, "id": "c-asia"},
        ]
        sigint = [
            {"source": "meshtastic", "lat": 35.0, "lng": -75.0, "id": "sig-east"},
            {"source": "meshtastic", "lat": 35.0, "lng": 100.0, "id": "sig-asia"},
        ]
        satellites = [
            {"lat": -60.0, "lng": -120.0, "id": "sat-sw"},
            {"lat": 35.0, "lng": -75.0, "id": "sat-ne"},
            {"lat": 35.0, "lng": 100.0, "id": "sat-asia"},
        ]

        monkeypatch.setitem(_store.latest_data, "commercial_flights", commercial)
        monkeypatch.setitem(_store.latest_data, "ships", ships)
        monkeypatch.setitem(_store.latest_data, "cctv", cctv)
        monkeypatch.setitem(_store.latest_data, "sigint", sigint)
        monkeypatch.setitem(_store.latest_data, "satellites", satellites)
        for layer in (
            "flights", "ships_military", "ships_cargo", "ships_civilian",
            "ships_passenger", "ships_tracked_yachts", "cctv",
            "sigint_meshtastic", "sigint_aprs", "satellites",
        ):
            monkeypatch.setitem(_store.active_layers, layer, True)

    def test_no_bbox_returns_world_data(self, client, monkeypatch):
        self._seed_fast(monkeypatch)
        r = client.get("/api/live-data/fast")
        assert r.status_code == 200
        data = r.json()
        assert len(data["commercial_flights"]) == 3
        assert len(data["ships"]) == 2
        assert len(data["sigint"]) == 2
        assert len(data["satellites"]) == 3

    def test_bbox_does_not_truncate_heavy_layers(self, client, monkeypatch):
        self._seed_fast(monkeypatch)
        r = client.get("/api/live-data/fast?s=30&w=-80&n=40&e=-70")
        assert r.status_code == 200
        data = r.json()
        assert {f["id"] for f in data["commercial_flights"]} == {"f-sw", "f-ne", "f-asia"}
        assert {s["id"] for s in data["ships"]} == {"s-sw", "s-ne"}
        assert {c["id"] for c in data["cctv"]} == {"c-1", "c-asia"}
        assert {s["id"] for s in data["sigint"]} == {"sig-east", "sig-asia"}
        assert len(data["satellites"]) == 3

    def test_world_scale_bbox_returns_full_set(self, client, monkeypatch):
        self._seed_fast(monkeypatch)
        r = client.get("/api/live-data/fast?s=-90&w=-180&n=90&e=180")
        assert r.status_code == 200
        data = r.json()
        assert len(data["commercial_flights"]) == 3
        assert len(data["ships"]) == 2

    def test_partial_bbox_is_treated_as_no_bbox(self, client, monkeypatch):
        self._seed_fast(monkeypatch)
        r = client.get("/api/live-data/fast?s=30&w=-80&n=40")
        assert r.status_code == 200
        data = r.json()
        assert len(data["commercial_flights"]) == 3

    def test_etag_shared_across_bbox_and_world(self, client, monkeypatch):
        self._seed_fast(monkeypatch)
        r_world = client.get("/api/live-data/fast")
        r_local = client.get("/api/live-data/fast?s=30&w=-80&n=40&e=-70")
        assert r_world.status_code == 200
        assert r_local.status_code == 200
        assert r_world.headers.get("ETag") == r_local.headers.get("ETag")

    def test_if_none_match_returns_304(self, client, monkeypatch):
        self._seed_fast(monkeypatch)
        r1 = client.get("/api/live-data/fast")
        etag = r1.headers.get("ETag")
        r2 = client.get("/api/live-data/fast", headers={"If-None-Match": etag})
        assert r2.status_code == 304


class TestSlowBboxFiltering:
    def _seed_slow(self, monkeypatch):
        from services.fetchers import _store
        from routers import data as data_router

        with data_router._LIVE_DATA_BYTES_CACHE_LOCK:
            data_router._LIVE_DATA_BYTES_CACHE.clear()
        _store.bump_data_version()

        gdelt = [
            {"lat": 35.0, "lng": -75.0, "id": "g-ne"},
            {"lat": 35.0, "lng": 100.0, "id": "g-asia"},
        ]
        firms = [
            {"lat": 35.0, "lng": -75.0, "id": "fire-ne"},
            {"lat": -20.0, "lng": 140.0, "id": "fire-au"},
        ]
        datacenters = [
            {"lat": 35.0, "lng": -75.0, "id": "dc-ne"},
            {"lat": 51.0, "lng": 0.0, "id": "dc-uk"},
        ]
        monkeypatch.setitem(_store.latest_data, "gdelt", gdelt)
        monkeypatch.setitem(_store.latest_data, "firms_fires", firms)
        monkeypatch.setitem(_store.latest_data, "datacenters", datacenters)
        for layer in ("global_incidents", "firms", "datacenters"):
            monkeypatch.setitem(_store.active_layers, layer, True)

    def test_no_bbox_returns_world_data(self, client, monkeypatch):
        self._seed_slow(monkeypatch)
        r = client.get("/api/live-data/slow")
        assert r.status_code == 200
        data = r.json()
        assert len(data["gdelt"]) == 2
        assert len(data["firms_fires"]) == 2
        assert len(data["datacenters"]) == 2

    def test_bbox_does_not_truncate_slow_layers(self, client, monkeypatch):
        self._seed_slow(monkeypatch)
        r = client.get("/api/live-data/slow?s=30&w=-80&n=40&e=-70")
        assert r.status_code == 200
        data = r.json()
        assert {g["id"] for g in data["gdelt"]} == {"g-ne", "g-asia"}
        assert {f["id"] for f in data["firms_fires"]} == {"fire-ne", "fire-au"}
        assert len(data["datacenters"]) == 2


class TestBboxHelpers:
    def test_has_full_bbox(self):
        from routers.data import _has_full_bbox
        assert _has_full_bbox(1, 2, 3, 4)
        assert not _has_full_bbox(None, 2, 3, 4)

    def test_bbox_etag_suffix_always_empty(self):
        from routers.data import _bbox_etag_suffix
        assert _bbox_etag_suffix(30.1, -79.6, 39.9, -70.1) == ""
        assert _bbox_etag_suffix(-90, -180, 90, 180) == ""
        assert _bbox_etag_suffix(None, -180, 90, 180) == ""

    def test_apply_bbox_is_noop(self):
        from routers.data import _apply_bbox_to_payload, _FAST_BBOX_HEAVY_KEYS

        payload = {
            "commercial_flights": [
                {"lat": 35.0, "lng": -75.0, "id": "in"},
                {"lat": 35.0, "lng": 100.0, "id": "out"},
            ],
            "note": "keep",
        }
        out = _apply_bbox_to_payload(dict(payload), _FAST_BBOX_HEAVY_KEYS, 30, -80, 40, -70)
        assert len(out["commercial_flights"]) == 2
        assert out["note"] == "keep"
