"""Tests for the Phase-4 P0 security fixes:

* coordinate-bounds validation on the agent pin/zone stores (was bypassable);
* SSRF guard wired into the operator/agent-supplied feed fetcher.
"""

import math

import pytest

from services import ai_pin_store, analysis_zone_store
from services.ssrf_guard import validate_host


# -- coordinate validation -------------------------------------------------- #
@pytest.mark.parametrize("lat,lng", [
    (999, 10), (10, 999), (float("nan"), 10), (10, float("inf")), (-91, 0), (0, 181),
])
def test_create_pin_rejects_bad_coords(lat, lng):
    with pytest.raises(ValueError):
        ai_pin_store.create_pin(lat, lng, label="x")


def test_create_pin_accepts_valid_coords():
    pin = ai_pin_store.create_pin(45.0, 33.0, label="ok", layer_id="test_layer")
    assert pin["lat"] == 45.0 and pin["lng"] == 33.0


def test_create_pins_batch_skips_invalid():
    items = [
        {"lat": 45.0, "lng": 33.0, "label": "good"},
        {"lat": 999, "lng": 0, "label": "bad-lat"},
        {"lat": float("nan"), "lng": 0, "label": "nan"},
        {"lat": 10.0, "lng": 20.0, "label": "good2"},
    ]
    created = ai_pin_store.create_pins_batch(items, default_layer_id="test_batch")
    assert len(created) == 2
    assert all(not math.isnan(p["lat"]) for p in created)


def test_create_zone_rejects_bad_coords():
    with pytest.raises(ValueError):
        analysis_zone_store.create_zone(lat=999, lng=0, title="t", body="b")


def test_create_zone_accepts_valid():
    z = analysis_zone_store.create_zone(lat=45.0, lng=33.0, title="t", body="b")
    assert z["lat"] == 45.0


# -- SSRF guard on feed ingestion ------------------------------------------ #
def test_ssrf_guard_blocks_internal_targets():
    # Loopback, RFC1918, and cloud-metadata must all be rejected.
    assert not validate_host("127.0.0.1")["ok"]
    assert not validate_host("169.254.169.254")["ok"]
    assert not validate_host("localhost")["ok"]
    assert not validate_host("10.0.0.5")["ok"]
    assert not validate_host("metadata.google.internal")["ok"]


def test_feed_ingester_uses_ssrf_guard_and_blocks_internal(monkeypatch):
    """A feed_url pointing at cloud metadata must be blocked before any pins
    are written (read-back SSRF prevented)."""
    import services.feed_ingester as fi

    called = {"replace": False}

    def _fake_replace(layer_id, pins):
        called["replace"] = True
        return len(pins)

    monkeypatch.setattr("services.ai_pin_store.replace_layer_pins", _fake_replace, raising=False)
    monkeypatch.setattr("services.ai_pin_store.update_layer", lambda *a, **k: None, raising=False)

    # Should return quietly (blocked by SSRF guard) without writing pins.
    fi._fetch_layer_feed({"id": "L1", "feed_url": "http://169.254.169.254/latest/meta-data/", "name": "evil"})
    assert called["replace"] is False

    fi._fetch_layer_feed({"id": "L2", "feed_url": "http://127.0.0.1:8787/internal", "name": "loopback"})
    assert called["replace"] is False
