"""Tests for issue #288: viewport bbox filtering on /api/live-data/{fast,slow}.

Behaviour contract:
 * Without s/w/n/e params, the response is byte-for-byte identical to the
   pre-#288 implementation. (No filtering, no extra fields, no ETag change.)
 * With s/w/n/e supplied, heavy/dense layers are filtered to that viewport
   with a 20% padding box.
 * Light reference layers (datacenters, military_bases, power_plants,
   satellites, news, weather, …) are NEVER filtered, even when bounds are
   supplied — panning must never reveal an "empty world" of infrastructure.
 * World-scale bounds (lng_span >= 300 OR lat_span >= 120) short-circuit
   filtering and share the global ETag.
 * The ETag includes a 1°-quantized bbox so two viewports never poison each
   other's 304 cache.
"""

import pytest


# ───────────────────────── /api/live-data/fast ─────────────────────────────


class TestFastBboxFiltering:
    def _seed_fast(self, monkeypatch):
        """Plant deterministic heavy + light fixtures across the globe."""
        from services.fetchers import _store
        from routers import data as data_router

        # Avoid cross-test ETag byte-cache pollution.
        with data_router._LIVE_DATA_BYTES_CACHE_LOCK:
            data_router._LIVE_DATA_BYTES_CACHE.clear()
        _store.bump_data_version()

        # Heavy collections: dense across the world.
        commercial = [
            {"lat": -60.0, "lng": -120.0, "id": "f-sw"},   # south Pacific
            {"lat": 35.0, "lng": -75.0, "id": "f-ne"},     # eastern US
            {"lat": 35.0, "lng": 100.0, "id": "f-asia"},   # Asia
        ]
        ships = [
            {"lat": -60.0, "lng": -120.0, "id": "s-sw"},
            {"lat": 35.0, "lng": -75.0, "id": "s-ne"},
        ]
        # Real CCTV rows use ``lon`` (not ``lng``) — bbox must honor that alias.
        cctv = [
            {"lat": 35.0, "lon": -75.0, "id": "c-1"},
            {"lat": 35.0, "lon": 100.0, "id": "c-asia"},
        ]

        # Sigint heavy collection.
        sigint = [
            {"source": "meshtastic", "lat": 35.0, "lng": -75.0, "id": "sig-east"},
            {"source": "meshtastic", "lat": 35.0, "lng": 100.0, "id": "sig-asia"},
        ]

        # Light/reference layer — must NEVER be filtered.
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
        # Ensure all layers are on so the response includes them.
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
        # All heavy fixtures pass through unchanged.
        assert len(data["commercial_flights"]) == 3
        assert len(data["ships"]) == 2
        assert len(data["sigint"]) == 2
        # Light layer also full.
        assert len(data["satellites"]) == 3

    def test_bbox_filters_heavy_layers(self, client, monkeypatch):
        self._seed_fast(monkeypatch)
        # Box tightly around the eastern-US fixture (lat 35, lng -75).
        # ±5° → after 20% padding inside _bbox_filter, ~±6° window.
        r = client.get("/api/live-data/fast?s=30&w=-80&n=40&e=-70")
        assert r.status_code == 200
        data = r.json()
        # Heavy layers: only the eastern-US fixture survives.
        assert {f["id"] for f in data["commercial_flights"]} == {"f-ne"}
        assert {s["id"] for s in data["ships"]} == {"s-ne"}
        assert {c["id"] for c in data["cctv"]} == {"c-1"}  # lon alias filtered
        assert {s["id"] for s in data["sigint"]} == {"sig-east"}

    def test_bbox_does_not_filter_light_layers(self, client, monkeypatch):
        self._seed_fast(monkeypatch)
        r = client.get("/api/live-data/fast?s=30&w=-80&n=40&e=-70")
        assert r.status_code == 200
        data = r.json()
        # Satellites are a reference layer — must NOT be bbox-filtered.
        assert len(data["satellites"]) == 3

    def test_world_scale_bbox_skips_filtering(self, client, monkeypatch):
        self._seed_fast(monkeypatch)
        # lng_span = 360 → treated as world-scale; same as no bbox.
        r = client.get("/api/live-data/fast?s=-90&w=-180&n=90&e=180")
        assert r.status_code == 200
        data = r.json()
        assert len(data["commercial_flights"]) == 3
        assert len(data["ships"]) == 2

    def test_partial_bbox_is_treated_as_no_bbox(self, client, monkeypatch):
        self._seed_fast(monkeypatch)
        # Only three of four bounds → filtering must NOT engage.
        r = client.get("/api/live-data/fast?s=30&w=-80&n=40")
        assert r.status_code == 200
        data = r.json()
        assert len(data["commercial_flights"]) == 3

    def test_etag_changes_with_bbox(self, client, monkeypatch):
        self._seed_fast(monkeypatch)
        r_world = client.get("/api/live-data/fast")
        r_local = client.get("/api/live-data/fast?s=30&w=-80&n=40&e=-70")
        assert r_world.status_code == 200
        assert r_local.status_code == 200
        etag_world = r_world.headers.get("etag")
        etag_local = r_local.headers.get("etag")
        assert etag_world and etag_local
        assert etag_world != etag_local, (
            "ETag must differ between world and regional bbox to prevent "
            "304 cache poisoning across viewports"
        )

    def test_etag_stable_for_subdegree_pan(self, client, monkeypatch):
        self._seed_fast(monkeypatch)
        # Sub-degree pan should land in the same 1°-quantized bucket.
        r_a = client.get("/api/live-data/fast?s=30&w=-80&n=40&e=-70")
        r_b = client.get("/api/live-data/fast?s=30.3&w=-79.8&n=39.7&e=-70.4")
        assert r_a.headers.get("etag") == r_b.headers.get("etag")

    def test_if_none_match_returns_304_for_same_bbox(self, client, monkeypatch):
        self._seed_fast(monkeypatch)
        r1 = client.get("/api/live-data/fast?s=30&w=-80&n=40&e=-70")
        etag = r1.headers.get("etag")
        r2 = client.get(
            "/api/live-data/fast?s=30&w=-80&n=40&e=-70",
            headers={"If-None-Match": etag},
        )
        assert r2.status_code == 304


# ───────────────────────── /api/live-data/slow ─────────────────────────────


class TestSlowBboxFiltering:
    def _seed_slow(self, monkeypatch):
        from services.fetchers import _store

        # Heavy collections.
        gdelt = [
            {"lat": 35.0, "lng": -75.0, "id": "g-east"},
            {"lat": 35.0, "lng": 100.0, "id": "g-asia"},
        ]
        firms_fires = [
            {"lat": 35.0, "lng": -75.0, "id": "fire-east"},
            {"lat": -10.0, "lng": 120.0, "id": "fire-ido"},
        ]
        # Light/reference layers — must always ship in full.
        datacenters = [
            {"lat": 35.0, "lng": -75.0, "id": "dc-east"},
            {"lat": 35.0, "lng": 100.0, "id": "dc-asia"},
            {"lat": -10.0, "lng": 120.0, "id": "dc-ido"},
        ]
        military_bases = [
            {"lat": 35.0, "lng": -75.0, "id": "mb-east"},
            {"lat": -10.0, "lng": 120.0, "id": "mb-ido"},
        ]
        power_plants = [
            {"lat": 35.0, "lng": -75.0, "id": "pp-east"},
            {"lat": 35.0, "lng": 100.0, "id": "pp-asia"},
        ]

        monkeypatch.setitem(_store.latest_data, "gdelt", gdelt)
        monkeypatch.setitem(_store.latest_data, "firms_fires", firms_fires)
        monkeypatch.setitem(_store.latest_data, "datacenters", datacenters)
        monkeypatch.setitem(_store.latest_data, "military_bases", military_bases)
        monkeypatch.setitem(_store.latest_data, "power_plants", power_plants)
        for layer in (
            "global_incidents", "firms", "datacenters", "military_bases", "power_plants",
        ):
            monkeypatch.setitem(_store.active_layers, layer, True)

    def test_no_bbox_returns_world_data(self, client, monkeypatch):
        self._seed_slow(monkeypatch)
        r = client.get("/api/live-data/slow")
        assert r.status_code == 200
        data = r.json()
        assert len(data["gdelt"]) == 2
        assert len(data["firms_fires"]) == 2
        assert len(data["datacenters"]) == 3

    def test_bbox_filters_heavy_layers(self, client, monkeypatch):
        self._seed_slow(monkeypatch)
        r = client.get("/api/live-data/slow?s=30&w=-80&n=40&e=-70")
        assert r.status_code == 200
        data = r.json()
        assert {g["id"] for g in data["gdelt"]} == {"g-east"}
        assert {f["id"] for f in data["firms_fires"]} == {"fire-east"}

    def test_bbox_leaves_reference_layers_untouched(self, client, monkeypatch):
        """Datacenters, bases, and power plants are infrastructure overlays —
        they must remain world-scale so panning never hides them."""
        self._seed_slow(monkeypatch)
        r = client.get("/api/live-data/slow?s=30&w=-80&n=40&e=-70")
        assert r.status_code == 200
        data = r.json()
        assert len(data["datacenters"]) == 3
        assert len(data["military_bases"]) == 2
        assert len(data["power_plants"]) == 2

    def test_antimeridian_bbox(self, client, monkeypatch):
        from services.fetchers import _store
        # Box that straddles the antimeridian (Pacific): w=170, e=-170.
        gdelt = [
            {"lat": 0.0, "lng": 175.0, "id": "in-west"},
            {"lat": 0.0, "lng": -175.0, "id": "in-east"},
            {"lat": 0.0, "lng": 0.0, "id": "out-mid"},
        ]
        monkeypatch.setitem(_store.latest_data, "gdelt", gdelt)
        monkeypatch.setitem(_store.active_layers, "global_incidents", True)
        r = client.get("/api/live-data/slow?s=-10&w=170&n=10&e=-170")
        assert r.status_code == 200
        data = r.json()
        ids = {g["id"] for g in data["gdelt"]}
        assert "in-west" in ids
        assert "in-east" in ids
        assert "out-mid" not in ids


# ─────────────────── Direct helper coverage (defensive) ─────────────────────


class TestHelpers:
    def test_has_full_bbox(self):
        from routers.data import _has_full_bbox
        assert _has_full_bbox(1, 2, 3, 4)
        assert not _has_full_bbox(None, 2, 3, 4)
        assert not _has_full_bbox(1, None, 3, 4)
        assert not _has_full_bbox(1, 2, None, 4)
        assert not _has_full_bbox(1, 2, 3, None)

    def test_bbox_etag_suffix_quantizes(self):
        from routers.data import _bbox_etag_suffix
        a = _bbox_etag_suffix(30.1, -79.6, 39.9, -70.1)
        b = _bbox_etag_suffix(30.4, -79.2, 39.4, -70.8)
        assert a == b, "Sub-degree pan must collapse to the same ETag suffix"
        assert a.startswith("|bbox=")

    def test_bbox_etag_suffix_world_collapses(self):
        from routers.data import _bbox_etag_suffix
        # World-scale → empty suffix (shares the global ETag).
        assert _bbox_etag_suffix(-90, -180, 90, 180) == ""

    def test_bbox_etag_suffix_partial_is_empty(self):
        from routers.data import _bbox_etag_suffix
        assert _bbox_etag_suffix(None, -180, 90, 180) == ""

    def test_apply_bbox_preserves_non_list_values(self):
        from routers.data import _apply_bbox_to_payload, _FAST_BBOX_HEAVY_KEYS
        payload = {
            "commercial_flights": [{"lat": 35, "lng": -75, "id": "x"}],
            "satellite_source": "tle",  # not a list, must pass through
            "sigint_totals": {"total": 1},  # dict — must pass through
        }
        out = _apply_bbox_to_payload(dict(payload), _FAST_BBOX_HEAVY_KEYS, 30, -80, 40, -70)
        assert out["satellite_source"] == "tle"
        assert out["sigint_totals"] == {"total": 1}
