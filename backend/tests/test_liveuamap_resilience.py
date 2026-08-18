"""Regression coverage for LiveUAMap packaging and parser drift (#516/#517)."""
from __future__ import annotations

import base64
import json
from pathlib import Path

from services import liveuamap_scraper as scraper


def _marker(marker_id: int = 123) -> dict:
    return {
        "id": marker_id,
        "s": "Test incident",
        "d": "Description",
        "lat": 38.9,
        "lng": -77.0,
        "time": 1_700_000_000,
        "link": "/en/123-test-incident",
    }


def test_ovens_normalizer_accepts_plain_marker_array() -> None:
    markers = scraper._normalize_ovens_payload([_marker()])
    assert markers == [_marker()]


def test_ovens_normalizer_accepts_json_encoded_marker_array() -> None:
    payload = json.dumps([_marker()])
    markers = scraper._normalize_ovens_payload(payload)
    assert markers == [_marker()]


def test_ovens_normalizer_accepts_double_encoded_marker_array() -> None:
    payload = json.dumps(json.dumps([_marker()]))
    markers = scraper._normalize_ovens_payload(payload)
    assert markers == [_marker()]


def test_ovens_normalizer_accepts_marker_strings_inside_array() -> None:
    payload = [json.dumps(_marker(1)), json.dumps(_marker(2))]
    markers = scraper._normalize_ovens_payload(payload)
    assert [item["id"] for item in markers] == [1, 2]


def test_ovens_normalizer_accepts_keyed_marker_object() -> None:
    payload = {"1": _marker(1), "2": _marker(2)}
    markers = scraper._normalize_ovens_payload(payload)
    assert [item["id"] for item in markers] == [1, 2]


def test_ovens_normalizer_accepts_common_wrapper_object() -> None:
    payload = {"data": {"markers": [_marker()]}}
    markers = scraper._normalize_ovens_payload(payload)
    assert markers == [_marker()]


def test_ovens_normalizer_accepts_urlquoted_base64_json() -> None:
    encoded = base64.b64encode(json.dumps([_marker()]).encode()).decode()
    markers = scraper._normalize_ovens_payload(encoded)
    assert markers == [_marker()]


def test_ovens_normalizer_skips_malformed_entries_without_losing_good_markers() -> None:
    payload = [_marker(1), "not-json", 17, None, {"junk": "value"}, _marker(2)]
    markers = scraper._normalize_ovens_payload(payload)
    assert [item["id"] for item in markers] == [1, 2]


def test_geojson_feature_collection_is_normalized() -> None:
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-77.0, 38.9]},
                "properties": {"id": 7, "title": "GeoJSON incident"},
            }
        ],
    }
    markers = scraper._normalize_ovens_payload(payload)
    assert markers[0]["id"] == 7
    assert markers[0]["lat"] == 38.9
    assert markers[0]["lng"] == -77.0


def test_marker_conversion_rejects_non_mapping_instead_of_calling_get() -> None:
    assert scraper._marker_to_incident("bad", {"name": "Ukraine", "url": "https://liveuamap.com"}) is None


def test_marker_conversion_preserves_existing_shadowbroker_shape() -> None:
    incident = scraper._marker_to_incident(
        _marker(), {"name": "Ukraine", "url": "https://liveuamap.com"}
    )
    assert incident is not None
    assert incident["id"] == 123
    assert incident["type"] == "liveuamap"
    assert incident["title"] == "Test incident"
    assert incident["lat"] == 38.9
    assert incident["lng"] == -77.0
    assert incident["link"] == "https://liveuamap.com/en/123-test-incident"


def test_dockerfile_uses_shared_playwright_browser_path_and_runtime_verification() -> None:
    dockerfile = Path(__file__).resolve().parents[1] / "Dockerfile"
    text = dockerfile.read_text(encoding="utf-8")
    assert "PLAYWRIGHT_BROWSERS_PATH=/ms-playwright" in text
    assert "chromium.executable_path" in text
    assert "assert path.is_file()" in text
