"""Defensive parsing helpers for LiveUAMap provider payloads.

LiveUAMap's browser page exposes an undocumented ``ovens`` value whose shape
has changed over time. The optional supported API may also return JSON or
GeoJSON. Keep representation decoding and schema normalization isolated here so
upstream drift degrades one provider instead of crashing the fetch scheduler.
"""

from __future__ import annotations

import ast
import base64
import binascii
import json
import math
import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import unquote

_MAX_DECODE_DEPTH = 5
_MAX_CANDIDATES = 10_000
_MAX_STRING_BYTES = 8 * 1024 * 1024
_WRAPPER_KEYS = ("ovens", "markers", "items", "events", "data", "results", "features")


def extract_ovens_expression(html: str) -> str | None:
    """Extract a legacy ``var/let/const ovens = ...;`` expression from HTML.

    Evaluating ``window.ovens`` in the browser is preferred; this exists only
    as a fallback for pages that still embed the value in source text.
    """
    if not html:
        return None
    match = re.search(
        r"(?:var|let|const)\s+ovens\s*=\s*(.+?);(?=\s*(?:</script>|(?:var|let|const|function)\b|$))",
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()

    # Compatibility with older pages where the next token after the semicolon
    # is arbitrary markup rather than another JavaScript declaration.
    match = re.search(r"(?:var|let|const)\s+ovens\s*=\s*(.*?);", html, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else None


def payload_shape(value: Any) -> str:
    """Return a non-sensitive structural description for drift diagnostics."""
    if isinstance(value, dict):
        keys = sorted(str(key) for key in value.keys())[:8]
        return f"dict(keys={keys}, size={len(value)})"
    if isinstance(value, list):
        item_types = sorted({type(item).__name__ for item in value[:20]})
        return f"list(size={len(value)}, item_types={item_types})"
    if isinstance(value, str):
        return f"str(len={len(value)})"
    return type(value).__name__


def normalize_liveuamap_payload(value: Any) -> list[dict[str, Any]]:
    """Normalize JSON/GeoJSON/legacy payload shapes into marker dictionaries.

    Unknown or malformed values are ignored. This function intentionally never
    assumes iterable items are mappings; issue #517 was caused by calling
    ``.get`` on strings after an upstream representation change.
    """
    out: list[dict[str, Any]] = []
    _collect(value, out, depth=0, inherited_id=None)
    return out[:_MAX_CANDIDATES]


def _collect(
    value: Any,
    out: list[dict[str, Any]],
    *,
    depth: int,
    inherited_id: str | None,
) -> None:
    if depth > _MAX_DECODE_DEPTH or len(out) >= _MAX_CANDIDATES:
        return

    if value is None:
        return

    if isinstance(value, str):
        decoded = _decode_string(value)
        if decoded is value or decoded == value:
            return
        _collect(decoded, out, depth=depth + 1, inherited_id=inherited_id)
        return

    if isinstance(value, list):
        for item in value[:_MAX_CANDIDATES - len(out)]:
            _collect(item, out, depth=depth + 1, inherited_id=None)
            if len(out) >= _MAX_CANDIDATES:
                break
        return

    if not isinstance(value, dict):
        return

    # GeoJSON FeatureCollection / Feature.
    if value.get("type") == "FeatureCollection" and isinstance(value.get("features"), list):
        _collect(value["features"], out, depth=depth + 1, inherited_id=None)
        return
    if value.get("type") == "Feature":
        marker = _marker_from_geojson_feature(value)
        if marker is not None:
            if inherited_id and not marker.get("id"):
                marker["id"] = inherited_id
            out.append(marker)
        return

    # Coordinate-bearing objects are markers even if they also contain a field
    # named `data`/`events`. Check them before generic wrapper traversal so a
    # legitimate marker cannot be swallowed by wrapper heuristics.
    if _looks_like_marker(value):
        marker = dict(value)
        if inherited_id and not marker.get("id"):
            marker["id"] = inherited_id
        out.append(marker)
        return

    # Common wrapper shapes returned by APIs or page-side serialization.
    for key in _WRAPPER_KEYS:
        if key in value and isinstance(value[key], (dict, list, str)):
            _collect(value[key], out, depth=depth + 1, inherited_id=None)
            return

    # Some versions expose a dictionary keyed by marker ID. Traverse mapping
    # values while preserving the key as a fallback identifier.
    traversable = [
        (str(key), item)
        for key, item in value.items()
        if isinstance(item, (dict, list, str))
    ]
    if traversable:
        for key, item in traversable[:_MAX_CANDIDATES - len(out)]:
            _collect(item, out, depth=depth + 1, inherited_id=key)
            if len(out) >= _MAX_CANDIDATES:
                break


def _decode_string(raw: str) -> Any:
    text = raw.strip()
    if not text or len(text.encode("utf-8", errors="ignore")) > _MAX_STRING_BYTES:
        return raw

    # A JavaScript string literal can include escaping that plain strip("'")
    # corrupts. literal_eval safely handles quoted string syntax only.
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        try:
            literal = ast.literal_eval(text)
        except (SyntaxError, ValueError):
            literal = None
        if isinstance(literal, str) and literal != text:
            return literal

    decoded = _try_json(text)
    if decoded is not None:
        return decoded

    # Legacy LiveUAMap payloads have appeared URL-encoded before decoding.
    url_decoded = unquote(text)
    if url_decoded != text:
        decoded = _try_json(url_decoded)
        if decoded is not None:
            return decoded
        text = url_decoded

    # Older scraper versions expected a base64-wrapped JSON blob. Decode only
    # when the result itself is valid JSON, so arbitrary titles/IDs are never
    # interpreted as base64 data.
    compact = "".join(text.split())
    if compact and len(compact) % 4 == 0:
        try:
            raw_bytes = base64.b64decode(compact, validate=True)
            decoded_text = raw_bytes.decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            decoded_text = ""
        if decoded_text:
            decoded = _try_json(decoded_text)
            if decoded is not None:
                return decoded

    return raw


def _try_json(text: str) -> Any | None:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def _looks_like_marker(value: dict[str, Any]) -> bool:
    keys = set(value)
    if {"lat", "lng"}.issubset(keys) or {"lat", "lon"}.issubset(keys):
        return True
    if "latitude" in keys and ("longitude" in keys or "lon" in keys or "lng" in keys):
        return True
    marker_metadata = {"id", "s", "title", "d", "desc", "description", "link", "url", "time", "t"}
    return bool(keys.intersection(marker_metadata)) and not any(key in value for key in _WRAPPER_KEYS)


def _marker_from_geojson_feature(feature: dict[str, Any]) -> dict[str, Any] | None:
    geometry = feature.get("geometry")
    if not isinstance(geometry, dict) or geometry.get("type") != "Point":
        return None
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, (list, tuple)) or len(coordinates) < 2:
        return None
    lng = _finite_coordinate(coordinates[0], minimum=-180.0, maximum=180.0)
    lat = _finite_coordinate(coordinates[1], minimum=-90.0, maximum=90.0)
    if lat is None or lng is None:
        return None
    properties = feature.get("properties")
    marker = dict(properties) if isinstance(properties, dict) else {}
    marker.setdefault("lat", lat)
    marker.setdefault("lng", lng)
    feature_id = feature.get("id")
    if feature_id is not None:
        marker.setdefault("id", feature_id)
    return marker


def _finite_coordinate(value: Any, *, minimum: float, maximum: float) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or not minimum <= number <= maximum:
        return None
    return number


def iter_valid_coordinates(markers: Iterable[dict[str, Any]]) -> Iterable[tuple[dict[str, Any], float, float]]:
    """Yield markers with finite in-range latitude/longitude values."""
    for marker in markers:
        if not isinstance(marker, dict):
            continue
        lat = marker.get("lat", marker.get("latitude"))
        lng = marker.get("lng", marker.get("lon", marker.get("longitude")))
        lat_value = _finite_coordinate(lat, minimum=-90.0, maximum=90.0)
        lng_value = _finite_coordinate(lng, minimum=-180.0, maximum=180.0)
        if lat_value is None or lng_value is None:
            continue
        yield marker, lat_value, lng_value
