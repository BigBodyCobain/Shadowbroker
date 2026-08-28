"""Protected QazLake snapshot/events consumer for Shadow public projections."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

UTC = timezone.utc

SCHEMA_VERSION = "qazlake.shadow-observations-feed/v1"
VALID_MODES = frozenset({"local", "compare", "qazpipe"})
FORBIDDEN_PUBLIC_PROPERTY_KEYS = frozenset(
    {
        "provider_id",
        "source_id",
        "collection_receipt_id",
        "payload_hash_sha256",
        "raw_payload",
        "raw_provider_id",
        "source_url",
        "download_url",
        "url",
        "s3Urls",
        "topology",
        "credentials",
    }
)
DEFAULT_FAMILY_LAYER_KEYS: dict[str, tuple[str, ...]] = {
    "aviation_public": ("commercial_flights", "military_flights"),
    "orbital_public": (
        "satellites",
        "satnogs_stations",
        "satnogs_observations",
        "tinygs_satellites",
    ),
    "geohazards": ("earthquakes", "volcanoes"),
    "weather_environment": ("space_weather", "weather_alerts", "air_quality"),
    "uap_public": ("uap_sightings",),
    "network_observability": ("internet_outages",),
    "events_media": ("gdelt", "news", "telegram_osint"),
    "radio_public": ("kiwisdr", "psk_reporter"),
    "visual_reference": ("cctv", "sar_scenes"),
    "cyber_public": ("cyber_threats",),
    "risk_reference_public": ("sanctions",),
}
LAYER_ENABLE_KEYS: dict[str, str] = {
    "commercial_flights": "flights",
    "military_flights": "military",
    "gdelt": "global_incidents",
    "satnogs_stations": "satnogs",
    "satnogs_observations": "satnogs",
}
_lock = threading.RLock()
_receipt_lock = threading.Lock()
_stop = threading.Event()
_thread: threading.Thread | None = None
_state: dict[str, Any] = {
    "entities": {},
    "cursor": 0,
    "watermark": None,
    "refreshed_at": None,
    "stale": True,
    "error": "not_started",
}


def configured_modes() -> dict[str, str]:
    raw = str(os.environ.get("SHADOW_LAYER_SOURCE_MODES", "") or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        logger.error("SHADOW_LAYER_SOURCE_MODES must be a JSON object")
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {
        str(family): str(mode).lower()
        for family, mode in parsed.items()
        if str(mode).lower() in VALID_MODES and str(mode).lower() != "local"
    }


def uses_qazpipe_mode() -> bool:
    return "qazpipe" in configured_modes().values()


def _cache_path() -> Path:
    return Path(
        os.environ.get("SHADOW_QAZLAKE_CACHE_PATH", "data/qazlake_shadow_cache.json")
    )


def _receipt_path() -> Path:
    return Path(
        os.environ.get(
            "SHADOW_QAZPIPE_COMPARE_RECEIPT_PATH",
            "data/qazpipe_compare_receipts.jsonl",
        )
    )


def _request_page(projection: str, cursor: int) -> dict[str, Any]:
    base_url = str(os.environ.get("QAZLAKE_SHADOW_FEED_URL", "") or "").rstrip("/")
    token = str(os.environ.get("QAZLAKE_SHADOW_FEED_TOKEN", "") or "").strip()
    if not base_url or not token:
        raise RuntimeError("QazLake Shadow feed URL/token are not configured")
    query = urlencode({"cursor": max(0, int(cursor)), "limit": 1000})
    request = Request(
        f"{base_url}/api/internal/v1/feeds/shadow/{projection}?{query}",
        headers={"X-QazLake-Shadow-Feed-Token": token, "Accept": "application/json"},
        method="GET",
    )
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read())
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unexpected QazLake Shadow feed contract")
    if not isinstance(payload.get("items"), list):
        raise TypeError("QazLake Shadow feed is missing items")
    return payload


def _save_cache() -> None:
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        serializable = dict(_state)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(
            serializable, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _load_cache() -> None:
    path = _cache_path()
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        return
    if not isinstance(loaded, dict) or not isinstance(loaded.get("entities"), dict):
        return
    with _lock:
        _state.update(loaded)
        _state["stale"] = True
        _state["error"] = "startup_cache"


def _accept_items(items: list[Any], entities: dict[str, dict[str, Any]]) -> None:
    for item in items:
        if not isinstance(item, dict):
            continue
        entity_id = str(item.get("entity_id") or "").strip()
        properties = item.get("properties")
        if not entity_id or not isinstance(properties, dict):
            continue
        entities[entity_id] = item


def refresh_snapshot() -> None:
    cursor = 0
    entities: dict[str, dict[str, Any]] = {}
    watermark = None
    while True:
        page = _request_page("snapshot", cursor)
        _accept_items(page["items"], entities)
        watermark = page.get("watermark")
        next_cursor = page.get("next_cursor")
        if not page.get("has_more") or next_cursor is None:
            cursor = int((watermark or {}).get("cursor") or cursor)
            break
        cursor = int(next_cursor)
    with _lock:
        _state.update(
            {
                "entities": entities,
                "cursor": cursor,
                "watermark": watermark,
                "refreshed_at": datetime.now(UTC).isoformat(),
                "stale": False,
                "error": None,
            }
        )
    _save_cache()


def poll_events() -> None:
    with _lock:
        cursor = int(_state.get("cursor") or 0)
        entities = dict(_state.get("entities") or {})
    watermark = None
    while True:
        page = _request_page("events", cursor)
        _accept_items(page["items"], entities)
        watermark = page.get("watermark")
        next_cursor = page.get("next_cursor")
        if next_cursor is not None:
            cursor = int(next_cursor)
        if not page.get("has_more"):
            break
    with _lock:
        _state.update(
            {
                "entities": entities,
                "cursor": cursor,
                "watermark": watermark or _state.get("watermark"),
                "refreshed_at": datetime.now(UTC).isoformat(),
                "stale": False,
                "error": None,
            }
        )
    _save_cache()


def _mark_stale(exc: Exception) -> None:
    with _lock:
        _state["stale"] = True
        _state["error"] = type(exc).__name__
    logger.warning(
        "QazLake Shadow feed refresh failed; retaining last valid snapshot: %s",
        type(exc).__name__,
    )


def _sync_loop() -> None:
    try:
        refresh_snapshot()
    except (HTTPError, URLError, OSError, RuntimeError, TypeError, ValueError) as exc:
        _mark_stale(exc)
    interval = max(
        10, int(os.environ.get("QAZLAKE_SHADOW_POLL_INTERVAL_S", "30") or 30)
    )
    while not _stop.wait(interval):
        try:
            poll_events()
        except (
            HTTPError,
            URLError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as exc:
            _mark_stale(exc)


def start_shadow_feed_sync() -> None:
    global _thread
    if not configured_modes():
        return
    _load_cache()
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(
        target=_sync_loop, daemon=True, name="qazlake-shadow-feed"
    )
    _thread.start()


def stop_shadow_feed_sync() -> None:
    _stop.set()


def _public_item(item: dict[str, Any]) -> dict[str, Any]:
    properties = {
        key: value
        for key, value in dict(item.get("properties") or {}).items()
        if key not in FORBIDDEN_PUBLIC_PROPERTY_KEYS
    }
    entity_id = str(item.get("entity_id") or "")
    result = {"id": entity_id, "entity_id": entity_id, **properties}
    if item.get("latitude") is not None:
        result["latitude"] = item["latitude"]
        result["lat"] = item["latitude"]
    if item.get("longitude") is not None:
        result["longitude"] = item["longitude"]
        result["lng"] = item["longitude"]
    if isinstance(item.get("geometry"), dict):
        result["geometry"] = item["geometry"]
    result["observed_at"] = item.get("observed_at")
    layer_key = str(properties.get("layer_key") or "")
    if layer_key in {"commercial_flights", "military_flights"}:
        external_id = str(
            item.get("external_id") or entity_id.removeprefix("aircraft:")
        ).lower()
        altitude_m = properties.get("altitude_m")
        speed_mps = properties.get("speed_mps")
        model = str(properties.get("aircraft_model") or "").strip().upper()
        category = str(properties.get("aircraft_category") or "").strip().upper()
        result.update(
            {
                "id": external_id or entity_id,
                "icao24": external_id,
                "callsign": properties.get("callsign")
                or external_id.upper()
                or "UNKNOWN",
                "alt": (
                    round(float(altitude_m) / 0.3048)
                    if isinstance(altitude_m, (int, float))
                    else None
                ),
                "heading": properties.get("heading_deg") or 0,
                "speed_knots": (
                    round(float(speed_mps) / 0.514444, 1)
                    if isinstance(speed_mps, (int, float))
                    else None
                ),
                "registration": properties.get("registration") or "N/A",
                "model": model or "Unknown",
                "squawk": properties.get("squawk") or None,
                "aircraft_category": "heli" if category == "A7" else "plane",
                # QazLake stays provider-neutral; the product projection carries
                # the attribution required when ADSB.lol data is shown publicly.
                "source": "ADSB.lol contributors",
            }
        )
        if layer_key == "military_flights":
            from services.fetchers.military import (
                _classify_military_type,
                _enrich_country,
            )

            country, force = _enrich_country(external_id, "")
            result.update(
                {
                    "type": "military_flight",
                    "country": country,
                    "force": force,
                    "military_type": _classify_military_type(model),
                    "origin_loc": None,
                    "dest_loc": None,
                    "origin_name": "UNKNOWN",
                    "dest_name": "UNKNOWN",
                }
            )
        else:
            result.update(
                {
                    "type": "commercial_flight",
                    "country": "N/A",
                    "origin_loc": None,
                    "dest_loc": None,
                    "origin_name": "UNKNOWN",
                    "dest_name": "UNKNOWN",
                }
            )
    elif layer_key == "earthquakes":
        if properties.get("magnitude") is not None:
            result["mag"] = properties["magnitude"]
        if properties.get("place") is not None:
            result["place"] = properties["place"]
    elif layer_key == "air_quality":
        if properties.get("pm25_ug_m3") is not None:
            result["pm25"] = properties["pm25_ug_m3"]
        if properties.get("aqi_us_epa") is not None:
            result["aqi"] = properties["aqi_us_epa"]
        if properties.get("name") is not None:
            result["name"] = properties["name"]
        if properties.get("country_code") is not None:
            result["country"] = properties["country_code"]
    elif layer_key == "space_weather":
        if properties.get("kp_index") is not None:
            result["kp_index"] = properties["kp_index"]
        category = str(properties.get("category") or "").lower()
        if category.startswith("g"):
            result["kp_text"] = f"STORM {category.split('_', 1)[0].upper()}"
        elif category == "active":
            result["kp_text"] = "ACTIVE"
        elif properties.get("kp_index") is not None and properties["kp_index"] >= 3:
            result["kp_text"] = "UNSETTLED"
        else:
            result["kp_text"] = "QUIET"
        result["events"] = []
    elif layer_key == "sanctions":
        external_id = str(
            item.get("external_id")
            or entity_id.removeprefix("sanctions:ofac-sdn:")
        ).strip()
        listing_type = str(properties.get("listing_type") or "Entity").strip()
        schema = {
            "Individual": "Person",
            "Entity": "LegalEntity",
            "Vessel": "Vessel",
            "Aircraft": "Airplane",
        }.get(listing_type, listing_type or "LegalEntity")
        aliases = [str(value) for value in properties.get("aliases") or []]
        countries = [str(value) for value in properties.get("countries") or []]
        programs = [str(value) for value in properties.get("programs") or []]
        observed_at = item.get("observed_at")
        result.update(
            {
                "id": external_id or entity_id,
                "schema": schema,
                "name": str(properties.get("name") or "").strip(),
                "aliases": aliases,
                "countries": countries,
                "programs": programs,
                "sanctions": "; ".join(programs),
                "first_seen": observed_at,
                "last_seen": observed_at,
            }
        )
    elif layer_key == "satnogs_stations":
        if properties.get("altitude_m") is not None:
            result["altitude"] = properties["altitude_m"]
        if properties.get("observation_count") is not None:
            result["observations"] = properties["observation_count"]
        if properties.get("last_seen_at") is not None:
            result["last_seen"] = properties["last_seen_at"]
    elif layer_key == "satnogs_observations":
        if properties.get("norad_catalog_id") is not None:
            result["norad_id"] = properties["norad_catalog_id"]
        if properties.get("started_at") is not None:
            result["start"] = properties["started_at"]
        if properties.get("ended_at") is not None:
            result["end"] = properties["ended_at"]
        if properties.get("frequency_hz") is not None:
            result["frequency"] = properties["frequency_hz"]
    elif layer_key == "cyber_threats":
        if properties.get("cve_id") is not None:
            result["id"] = properties["cve_id"]
        if properties.get("date_added") is not None:
            result["date"] = properties["date_added"]
        if properties.get("due_date") is not None:
            result["due"] = properties["due_date"]
    elif layer_key == "weather_alerts":
        if properties.get("alert_id") is not None:
            result["id"] = properties["alert_id"]
        if properties.get("expires_at") is not None:
            result["expires"] = properties["expires_at"]
    elif layer_key == "sar_scenes":
        scene_id = str(item.get("external_id") or entity_id.removeprefix("sar_scene:"))
        result["scene_id"] = scene_id
        result["mode"] = properties.get("beam_mode") or ""
        result["level"] = properties.get("processing_level") or ""
        result["time"] = properties.get("acquisition_start_at") or item.get(
            "observed_at"
        )
        result["bbox"] = _geometry_bbox(item.get("geometry")) or []
        # Keep the legacy public shape without reintroducing product downloads
        # or provider-specific identifiers into the QazLake projection.
        result["download_url"] = ""
        result["provider"] = "QazLake"
    return result


def _geometry_bbox(value: object) -> list[float] | None:
    if not isinstance(value, dict) or not isinstance(value.get("coordinates"), list):
        return None
    points: list[tuple[float, float]] = []

    def visit(coordinates: object) -> None:
        if not isinstance(coordinates, list):
            return
        if len(coordinates) >= 2 and all(
            isinstance(coordinates[index], (int, float))
            and not isinstance(coordinates[index], bool)
            for index in (0, 1)
        ):
            longitude = float(coordinates[0])
            latitude = float(coordinates[1])
            if (
                math.isfinite(longitude)
                and math.isfinite(latitude)
                and -180 <= longitude <= 180
                and -90 <= latitude <= 90
            ):
                points.append((longitude, latitude))
            return
        for child in coordinates:
            visit(child)

    visit(value["coordinates"])
    if not points:
        return None
    longitudes = [point[0] for point in points]
    latitudes = [point[1] for point in points]
    return [min(longitudes), min(latitudes), max(longitudes), max(latitudes)]


def _latest_item(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    def observed_at(item: dict[str, Any]) -> datetime:
        raw = str(item.get("observed_at") or "").replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return datetime.min.replace(tzinfo=UTC)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    return max(items, key=observed_at) if items else None


def _public_layer_value(layer_key: str, items: list[dict[str, Any]]) -> Any:
    """Keep public singleton layers shape-compatible after QazLake cutover."""
    if layer_key == "space_weather":
        return _latest_item(items) or {
            "kp_index": None,
            "kp_text": "QUIET",
            "events": [],
        }
    if layer_key == "telegram_osint":
        return {
            "posts": items,
            "total": len(items),
            "geolocated": sum(
                1
                for item in items
                if item.get("lat") is not None and item.get("lng") is not None
            ),
        }
    if layer_key == "cyber_threats":
        cutoff = datetime.now(UTC) - timedelta(days=30)
        recent: list[dict[str, Any]] = []
        for item in items:
            raw_date = item.get("date_added") or item.get("date")
            try:
                added = datetime.fromisoformat(str(raw_date)).replace(tzinfo=UTC)
            except (TypeError, ValueError):
                continue
            if added >= cutoff:
                recent.append(item)
        recent.sort(
            key=lambda item: (
                str(item.get("date_added") or ""),
                str(item.get("id") or ""),
            ),
            reverse=True,
        )
        recent = recent[:10]
        threats = [
            {
                "id": item.get("cve_id") or item.get("id"),
                "name": item.get("name"),
                "vendor": item.get("vendor"),
                "product": item.get("product"),
                "severity": "CRITICAL",
                "date": item.get("date_added") or item.get("date"),
                "due": item.get("due_date") or item.get("due"),
                "source": "CISA KEV",
            }
            for item in recent
        ]
        catalog_counts = [
            item.get("catalog_count")
            for item in items
            if isinstance(item.get("catalog_count"), int)
        ]
        release_dates = [
            str(item.get("catalog_released_at"))
            for item in items
            if item.get("catalog_released_at")
        ]
        active_count = len(threats)
        return {
            "threats": threats,
            "stats": {
                "cisa_total": max(catalog_counts, default=len(items)),
                "active_cves": active_count,
                "threat_level": (
                    "CRITICAL"
                    if active_count >= 8
                    else "HIGH"
                    if active_count >= 4
                    else "ELEVATED"
                ),
            },
            "timestamp": max(release_dates, default=None),
        }
    if layer_key == "weather_alerts":
        now = datetime.now(UTC)
        active: list[dict[str, Any]] = []
        for item in items:
            raw_expiry = item.get("expires_at") or item.get("expires")
            try:
                expiry = datetime.fromisoformat(str(raw_expiry).replace("Z", "+00:00"))
            except (TypeError, ValueError):
                continue
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=UTC)
            if expiry.astimezone(UTC) > now:
                active.append(item)
        active.sort(
            key=lambda item: (str(item.get("expires") or ""), str(item.get("id") or ""))
        )
        return active
    return items


def _items_by_family() -> dict[str, dict[str, list[dict[str, Any]]]]:
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {}
    with _lock:
        entities = list((_state.get("entities") or {}).values())
    for item in entities:
        properties = item.get("properties") if isinstance(item, dict) else None
        family = str((properties or {}).get("layer_family") or "").strip()
        layer_key = str((properties or {}).get("layer_key") or family).strip()
        if family:
            grouped.setdefault(family, {}).setdefault(layer_key, []).append(
                _public_item(item)
            )
    return grouped


def _family_layer_keys(family: str) -> tuple[str, ...]:
    configured = _json_mapping("SHADOW_LAYER_FAMILY_KEYS")
    value = configured.get(family)
    if isinstance(value, list):
        keys = tuple(str(key).strip() for key in value if str(key).strip())
        if keys:
            return keys
    return DEFAULT_FAMILY_LAYER_KEYS.get(family, (family,))


def _canonical_ids(items: Any) -> set[str]:
    if not isinstance(items, list):
        return set()
    ids = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        identity = next(
            (
                item.get(key)
                for key in ("entity_id", "id", "hex", "icao24", "mmsi")
                if item.get(key)
            ),
            None,
        )
        if identity is not None:
            ids.add(str(identity))
    return ids


def _comparison_rows(layer_key: str, value: Any) -> list[dict[str, Any]]:
    """Normalize public singleton and collection shapes for comparison only."""
    if layer_key == "space_weather":
        item = _latest_item(value) if isinstance(value, list) else value
        if not isinstance(item, dict):
            return []
        normalized = dict(item)
        # The legacy singleton has no public ID. Its layer identity is stable
        # and must compare with the QazLake current-entity projection.
        normalized["id"] = layer_key
        return [normalized]
    if layer_key == "cyber_threats":
        projected = (
            _public_layer_value(layer_key, value) if isinstance(value, list) else value
        )
        if not isinstance(projected, dict) or not isinstance(
            projected.get("threats"), list
        ):
            return []
        return [item for item in projected["threats"] if isinstance(item, dict)]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _json_mapping(name: str) -> dict[str, Any]:
    raw = str(os.environ.get(name, "") or "").strip()
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        logger.error("%s must be a JSON object", name)
        return {}
    return value if isinstance(value, dict) else {}


def _latest_observed_at(items: Any) -> datetime | None:
    latest: datetime | None = None
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        raw = item.get("observed_at") or item.get("timestamp") or item.get("updated_at")
        if not raw:
            continue
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            parsed = parsed.astimezone(UTC)
        except (TypeError, ValueError):
            continue
        latest = parsed if latest is None or parsed > latest else latest
    return latest


def _required_null_rate(items: Any, required_fields: list[str]) -> float:
    rows = (
        [item for item in items if isinstance(item, dict)]
        if isinstance(items, list)
        else []
    )
    if not rows or not required_fields:
        return 0.0
    missing = sum(
        1 for item in rows for field in required_fields if item.get(field) is None
    )
    return missing / (len(rows) * len(required_fields))


def _write_compare_receipt(
    endpoint: str,
    family: str,
    layer_key: str,
    local: Any,
    candidate: Any,
) -> None:
    local_rows = _comparison_rows(layer_key, local)
    candidate_rows = _comparison_rows(layer_key, candidate)
    local_ids = _canonical_ids(local_rows)
    candidate_ids = _canonical_ids(candidate_rows)
    union = local_ids | candidate_ids
    overlap = len(local_ids & candidate_ids) / len(union) if union else 1.0
    comparison_kinds = _json_mapping("SHADOW_COMPARE_FAMILY_KINDS")
    comparison_kind = str(comparison_kinds.get(family) or "streaming").lower()
    if comparison_kind not in {"deterministic", "streaming"}:
        comparison_kind = "streaming"
    required_config = _json_mapping("SHADOW_COMPARE_REQUIRED_FIELDS")
    required_fields = [
        str(field)
        for field in required_config.get(family, [])
        if isinstance(field, str) and field
    ]
    local_null_rate = _required_null_rate(local_rows, required_fields)
    candidate_null_rate = _required_null_rate(candidate_rows, required_fields)
    null_rate_delta = candidate_null_rate - local_null_rate
    cadence_config = _json_mapping("SHADOW_COMPARE_CADENCE_SECONDS")
    try:
        cadence_seconds = max(0, int(cadence_config.get(family, 0)))
    except (TypeError, ValueError):
        cadence_seconds = 0
    local_latest = _latest_observed_at(local_rows)
    candidate_latest = _latest_observed_at(candidate_rows)
    freshness_lag_seconds = None
    freshness_ok = True
    if local_latest is not None:
        freshness_lag_seconds = (
            (local_latest - candidate_latest).total_seconds()
            if candidate_latest is not None
            else None
        )
        freshness_ok = (
            candidate_latest is not None and freshness_lag_seconds <= cadence_seconds
        )
    deterministic_ok = local_ids == candidate_ids and len(local_rows) == len(
        candidate_rows
    )
    identity_ok = (
        deterministic_ok if comparison_kind == "deterministic" else overlap >= 0.90
    )
    status = shadow_feed_status()
    watermark = status["watermark"]
    watermark_ok = (
        isinstance(watermark, dict)
        and isinstance(watermark.get("cursor"), int)
        and watermark["cursor"] >= 0
    )
    accepted = (
        identity_ok
        and freshness_ok
        and null_rate_delta <= 0.01
        and watermark_ok
        and not status["stale"]
    )
    receipt = {
        "schema_version": "shadow.qazpipe-comparison-receipt/v1",
        "recorded_at": datetime.now(UTC).isoformat(),
        "endpoint": endpoint,
        "layer_family": family,
        "layer_key": layer_key,
        "comparison_kind": comparison_kind,
        "local_count": len(local_rows),
        "qazlake_count": len(candidate_rows),
        "id_overlap": overlap,
        "canonical_ids_exact": local_ids == candidate_ids,
        "required_fields": required_fields,
        "local_required_null_rate": local_null_rate,
        "qazlake_required_null_rate": candidate_null_rate,
        "required_null_rate_delta": null_rate_delta,
        "freshness_lag_seconds": freshness_lag_seconds,
        "cadence_seconds": cadence_seconds,
        "watermark": watermark,
        "watermark_valid": watermark_ok,
        "stale": status["stale"],
        "accepted": accepted,
        "failed_gates": [
            name
            for name, passed in (
                ("canonical_identity", identity_ok),
                ("freshness", freshness_ok),
                ("required_null_rate", null_rate_delta <= 0.01),
                ("watermark", watermark_ok),
                ("feed_current", not status["stale"]),
            )
            if not passed
        ],
    }
    path = _receipt_path()
    try:
        with _receipt_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n"
                )
    except OSError as exc:
        logger.error(
            "Unable to write QazLake comparison receipt: %s", type(exc).__name__
        )


def shadow_feed_status() -> dict[str, Any]:
    with _lock:
        return {
            "stale": bool(_state.get("stale", True)),
            "available": bool(_state.get("entities")),
            "watermark": _state.get("watermark"),
            "refreshed_at": _state.get("refreshed_at"),
            "error": _state.get("error"),
        }


def shadow_feed_etag_suffix() -> str:
    modes = configured_modes()
    if not modes:
        return ""
    status = shadow_feed_status()
    material = json.dumps(
        {"modes": modes, "watermark": status["watermark"], "stale": status["stale"]},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return "qazlake-" + hashlib.sha256(material).hexdigest()[:12] + "|"


def apply_layer_source_modes(
    payload: dict[str, Any],
    *,
    endpoint: str,
    enabled_layers: dict[str, bool] | None = None,
) -> dict[str, Any]:
    modes = configured_modes()
    if not modes:
        return payload
    grouped = _items_by_family()
    for family, mode in modes.items():
        for layer_key in _family_layer_keys(family):
            if layer_key not in payload:
                continue
            enable_key = LAYER_ENABLE_KEYS.get(layer_key, layer_key)
            if enabled_layers is not None and not enabled_layers.get(enable_key, True):
                continue
            candidate = grouped.get(family, {}).get(layer_key, [])
            if mode == "compare":
                _write_compare_receipt(
                    endpoint,
                    family,
                    layer_key,
                    payload.get(layer_key),
                    candidate,
                )
            elif mode == "qazpipe":
                # Fail visibly: an unavailable feed projects an empty layer and
                # explicit stale state; it never falls back to the local collector.
                payload[layer_key] = _public_layer_value(layer_key, candidate)
    if "qazpipe" in modes.values():
        status = shadow_feed_status()
        payload["qazpipe_state"] = {
            "schema_version": SCHEMA_VERSION,
            "modes": modes,
            "status": "stale" if status["stale"] else "current",
            "available": status["available"],
            "watermark": status["watermark"],
            "refreshed_at": status["refreshed_at"],
        }
    return payload
