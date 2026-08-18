from __future__ import annotations

import base64
import json
from urllib.parse import quote

from services.liveuamap_parser import (
    extract_ovens_expression,
    iter_valid_coordinates,
    normalize_liveuamap_payload,
)


def _ids(value):
    return [str(item.get("id")) for item in normalize_liveuamap_payload(value)]


def test_plain_marker_list():
    payload = [{"id": 1, "lat": 1, "lng": 2, "title": "a"}]
    assert _ids(payload) == ["1"]


def test_double_encoded_json():
    payload = json.dumps(json.dumps([{"id": "double", "lat": 1, "lng": 2}]))
    assert _ids(payload) == ["double"]


def test_list_of_json_strings_regression_517():
    payload = [
        json.dumps({"id": "a", "lat": 10, "lng": 20}),
        json.dumps({"id": "b", "lat": 30, "lng": 40}),
    ]
    assert _ids(payload) == ["a", "b"]


def test_mapping_key_becomes_fallback_marker_id():
    payload = {"123": {"lat": 1, "lng": 2, "title": "keyed"}}
    markers = normalize_liveuamap_payload(payload)
    assert markers[0]["id"] == "123"


def test_common_wrapper_shape():
    payload = {"data": {"markers": [{"id": "wrapped", "lat": 1, "lng": 2}]}}
    assert _ids(payload) == ["wrapped"]


def test_coordinate_marker_wins_over_wrapper_named_field():
    payload = {
        "id": "direct",
        "lat": 10,
        "lng": 20,
        "data": {"diagnostic": "metadata, not a marker wrapper"},
    }
    markers = normalize_liveuamap_payload(payload)
    assert len(markers) == 1
    assert markers[0]["id"] == "direct"
    assert markers[0]["lat"] == 10


def test_legacy_urlencoded_base64_json():
    raw = json.dumps([{"id": "legacy", "lat": 1, "lng": 2}]).encode()
    payload = quote(base64.b64encode(raw).decode())
    assert _ids(payload) == ["legacy"]


def test_geojson_feature_collection():
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "geo",
                "geometry": {"type": "Point", "coordinates": [20, 10]},
                "properties": {"title": "Geo event"},
            }
        ],
    }
    markers = normalize_liveuamap_payload(payload)
    assert markers == [{"title": "Geo event", "lat": 10.0, "lng": 20.0, "id": "geo"}]


def test_malformed_scalars_are_ignored_instead_of_crashing():
    payload = ["not-json", 42, None, True, {"nested": object()}]
    assert normalize_liveuamap_payload(payload) == []


def test_coordinate_iterator_rejects_out_of_range_and_nonfinite():
    markers = [
        {"id": "good", "lat": "10", "lng": "20"},
        {"id": "bad-lat", "lat": 100, "lng": 20},
        {"id": "bad-lng", "lat": 10, "lng": 200},
        {"id": "nan", "lat": float("nan"), "lng": 20},
    ]
    valid = list(iter_valid_coordinates(markers))
    assert [(item[0]["id"], item[1], item[2]) for item in valid] == [("good", 10.0, 20.0)]


def test_extracts_var_let_and_const_ovens():
    assert extract_ovens_expression('<script>var ovens = [{"id":1}];</script>') == '[{"id":1}]'
    assert extract_ovens_expression('<script>let ovens = "abc";</script>') == '"abc"'
    assert extract_ovens_expression('<script>const ovens = {"data":[]};</script>') == '{"data":[]}'
