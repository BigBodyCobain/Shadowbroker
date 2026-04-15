"""Train tracking fetchers with normalized metadata and non-redundant merging."""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from datetime import datetime, timezone

from services.fetchers._store import _data_lock, _mark_fresh, latest_data
from services.network_utils import fetch_with_curl

logger = logging.getLogger(__name__)

_EARTH_RADIUS_KM = 6371.0
_MERGE_DISTANCE_KM = 5.0
_MAX_INFERRED_SPEED_KMH = 350.0
_TRACK_CACHE_TTL_S = 6 * 60 * 60

_SOURCE_METADATA: dict[str, dict[str, object]] = {
    "amtrak": {
        "source_label": "Amtraker",
        "operator": "Amtrak",
        "country": "US",
        "telemetry_quality": "aggregated",
        "priority": 70,
    },
    "digitraffic": {
        "source_label": "Digitraffic Finland",
        "operator": "Finnish Rail",
        "country": "FI",
        "telemetry_quality": "official",
        "priority": 100,
    },
    # Future slots so better official feeds can be merged without changing the
    # rest of the train pipeline or duplicating map entities.
    "networkrail": {
        "source_label": "Network Rail Open Data",
        "operator": "Network Rail",
        "country": "GB",
        "telemetry_quality": "official",
        "priority": 98,
    },
    "dbcargo": {
        "source_label": "DB Cargo link2rail",
        "operator": "DB Cargo",
        "country": "DE",
        "telemetry_quality": "commercial",
        "priority": 96,
    },
    "railinc": {
        "source_label": "Railinc RailSight",
        "operator": "Railinc",
        "country": "US",
        "telemetry_quality": "commercial",
        "priority": 97,
    },
    "sncf": {
        "source_label": "SNCF Open Data",
        "operator": "SNCF",
        "country": "FR",
        "telemetry_quality": "official",
        "priority": 94,
    },
}

_TRAIN_TRACK_CACHE: dict[str, dict[str, float]] = {}


def _safe_float(value) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_observed_at(value) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        raw = float(value)
        return raw / 1000.0 if raw > 1_000_000_000_000 else raw
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1_rad, lon1_rad = math.radians(lat1), math.radians(lon1)
    lat2_rad, lon2_rad = math.radians(lat2), math.radians(lon2)
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2.0) ** 2
    )
    return 2.0 * _EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def _bearing_degrees(lat1: float, lon1: float, lat2: float, lon2: float) -> float | None:
    if lat1 == lat2 and lon1 == lon2:
        return None
    lat1_rad, lat2_rad = math.radians(lat1), math.radians(lat2)
    dlon_rad = math.radians(lon2 - lon1)
    y = math.sin(dlon_rad) * math.cos(lat2_rad)
    x = (
        math.cos(lat1_rad) * math.sin(lat2_rad)
        - math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(dlon_rad)
    )
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def _source_meta(source: str) -> dict[str, object]:
    return dict(_SOURCE_METADATA.get(source, {}))


def _normalize_train(
    *,
    source: str,
    raw_id: str,
    number: str,
    lat,
    lng,
    name: str = "",
    status: str = "Active",
    route: str = "",
    speed_kmh=None,
    heading=None,
    operator: str | None = None,
    country: str | None = None,
    source_label: str | None = None,
    telemetry_quality: str | None = None,
    observed_at=None,
) -> dict | None:
    lat_f = _safe_float(lat)
    lng_f = _safe_float(lng)
    if lat_f is None or lng_f is None:
        return None
    if not (-90.0 <= lat_f <= 90.0 and -180.0 <= lng_f <= 180.0):
        return None

    number_text = str(number or "").strip()
    meta = _source_meta(source)
    observed_ts = _parse_observed_at(observed_at) or datetime.now(timezone.utc).timestamp()
    speed_f = _safe_float(speed_kmh)
    heading_f = _safe_float(heading)
    normalized = {
        "id": str(raw_id or f"{source}-{number_text or 'unknown'}"),
        "name": str(name or f"Train {number_text or '?'}").strip(),
        "number": number_text,
        "source": source,
        "source_label": str(source_label or meta.get("source_label") or source.upper()),
        "operator": str(operator or meta.get("operator") or "").strip(),
        "country": str(country or meta.get("country") or "").strip(),
        "telemetry_quality": str(
            telemetry_quality or meta.get("telemetry_quality") or "unknown"
        ).strip(),
        "lat": lat_f,
        "lng": lng_f,
        "speed_kmh": speed_f,
        "heading": heading_f,
        "status": str(status or "Active").strip(),
        "route": str(route or "").strip(),
        "_source_priority": int(meta.get("priority") or 0),
        "_observed_ts": observed_ts,
    }
    _apply_motion_estimates(normalized)
    return normalized


def _prune_track_cache(now_ts: float) -> None:
    stale_before = now_ts - _TRACK_CACHE_TTL_S
    stale_ids = [train_id for train_id, entry in _TRAIN_TRACK_CACHE.items() if entry["ts"] < stale_before]
    for train_id in stale_ids:
        _TRAIN_TRACK_CACHE.pop(train_id, None)


def _apply_motion_estimates(train: dict) -> None:
    train_id = str(train.get("id") or "")
    if not train_id:
        return
    now_ts = float(train.get("_observed_ts") or datetime.now(timezone.utc).timestamp())
    _prune_track_cache(now_ts)
    previous = _TRAIN_TRACK_CACHE.get(train_id)
    if previous:
        dt_s = now_ts - previous["ts"]
        if 5.0 <= dt_s <= 15.0 * 60.0:
            distance_km = _haversine_km(
                float(previous["lat"]),
                float(previous["lng"]),
                float(train["lat"]),
                float(train["lng"]),
            )
            if 0.02 <= distance_km <= (_MAX_INFERRED_SPEED_KMH * (dt_s / 3600.0)):
                if train.get("speed_kmh") is None:
                    inferred_speed = distance_km / (dt_s / 3600.0)
                    train["speed_kmh"] = round(min(inferred_speed, _MAX_INFERRED_SPEED_KMH), 1)
                if train.get("heading") is None:
                    inferred_heading = _bearing_degrees(
                        float(previous["lat"]),
                        float(previous["lng"]),
                        float(train["lat"]),
                        float(train["lng"]),
                    )
                    if inferred_heading is not None:
                        train["heading"] = round(inferred_heading, 1)

    _TRAIN_TRACK_CACHE[train_id] = {
        "lat": float(train["lat"]),
        "lng": float(train["lng"]),
        "ts": now_ts,
    }


def _train_merge_key(train: dict) -> str:
    operator = str(train.get("operator") or "").strip().lower()
    country = str(train.get("country") or "").strip().lower()
    number = str(train.get("number") or "").strip().lower()
    if operator and number:
        return f"{country}|{operator}|{number}"
    return f"{str(train.get('source') or '').lower()}|{str(train.get('id') or '').lower()}"


def _train_completeness(train: dict) -> tuple[int, int, int]:
    return (
        1 if train.get("speed_kmh") is not None else 0,
        1 if train.get("heading") is not None else 0,
        1 if train.get("route") else 0,
    )


def _should_merge(existing: dict, candidate: dict) -> bool:
    if _train_merge_key(existing) != _train_merge_key(candidate):
        return False
    return _haversine_km(
        float(existing["lat"]),
        float(existing["lng"]),
        float(candidate["lat"]),
        float(candidate["lng"]),
    ) <= _MERGE_DISTANCE_KM


def _merge_train_pair(existing: dict, candidate: dict) -> dict:
    existing_priority = int(existing.get("_source_priority") or 0)
    candidate_priority = int(candidate.get("_source_priority") or 0)
    existing_score = (existing_priority, _train_completeness(existing))
    candidate_score = (candidate_priority, _train_completeness(candidate))
    primary = candidate if candidate_score > existing_score else existing
    secondary = existing if primary is candidate else candidate
    merged = dict(primary)

    for field in (
        "speed_kmh",
        "heading",
        "route",
        "status",
        "operator",
        "country",
        "source_label",
        "telemetry_quality",
    ):
        if merged.get(field) in (None, "", "Active"):
            replacement = secondary.get(field)
            if replacement not in (None, ""):
                merged[field] = replacement

    if primary is not candidate and float(candidate.get("_observed_ts") or 0) > float(
        primary.get("_observed_ts") or 0
    ):
        merged["lat"] = candidate["lat"]
        merged["lng"] = candidate["lng"]
        merged["_observed_ts"] = candidate["_observed_ts"]
    return merged


def _merge_nonredundant_trains(*sources: list[dict]) -> list[dict]:
    merged: list[dict] = []
    for source_trains in sources:
        for train in source_trains:
            exact_match = next(
                (
                    idx
                    for idx, existing in enumerate(merged)
                    if existing.get("source") == train.get("source")
                    and existing.get("id") == train.get("id")
                ),
                None,
            )
            if exact_match is not None:
                merged[exact_match] = _merge_train_pair(merged[exact_match], train)
                continue

            merged_idx = next(
                (idx for idx, existing in enumerate(merged) if _should_merge(existing, train)),
                None,
            )
            if merged_idx is not None:
                merged[merged_idx] = _merge_train_pair(merged[merged_idx], train)
                continue
            merged.append(train)

    merged.sort(
        key=lambda train: (
            str(train.get("country") or ""),
            str(train.get("operator") or ""),
            str(train.get("number") or ""),
            str(train.get("id") or ""),
        )
    )
    for train in merged:
        train.pop("_source_priority", None)
        train.pop("_observed_ts", None)
    return merged


def _fetch_amtraker() -> list[dict]:
    """Fetch all active Amtrak trains from the Amtraker API."""
    try:
        resp = fetch_with_curl(
            "https://api.amtraker.com/v3/trains",
            timeout=20,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/136.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json,text/plain,*/*",
                "Referer": "https://www.amtraker.com/",
            },
        )
        if resp.status_code != 200:
            logger.warning("Amtraker returned %s", resp.status_code)
            return []
        raw = resp.json()
        trains: list[dict] = []
        for train_num, variants in raw.items():
            if not isinstance(variants, list):
                continue
            for item in variants:
                normalized = _normalize_train(
                    source="amtrak",
                    raw_id=f"AMTK-{item.get('trainID', train_num)}",
                    name=item.get("routeName", f"Train {train_num}"),
                    number=str(item.get("trainNum", train_num) or train_num),
                    lat=item.get("lat"),
                    lng=item.get("lon"),
                    speed_kmh=item.get("velocity") or item.get("speed"),
                    heading=item.get("heading") or item.get("bearing"),
                    status=item.get("trainTimely") or "On Time",
                    route=item.get("routeName", ""),
                    observed_at=item.get("updatedAt")
                    or item.get("lastValTS")
                    or item.get("eventDT"),
                )
                if normalized:
                    trains.append(normalized)
        return trains
    except Exception as exc:
        logger.warning("Amtraker fetch error: %s", exc)
        return []


def _fetch_digitraffic() -> list[dict]:
    """Fetch live train positions from Finnish DigiTraffic API."""
    try:
        resp = fetch_with_curl(
            "https://rata.digitraffic.fi/api/v1/train-locations/latest",
            timeout=15,
            headers={
                "Accept-Encoding": "gzip",
                "User-Agent": "ShadowBroker-OSINT/1.0",
            },
        )
        if resp.status_code != 200:
            logger.warning("DigiTraffic returned %s", resp.status_code)
            return []
        raw = resp.json()
        trains: list[dict] = []
        for item in raw:
            location = item.get("location", {})
            coords = location.get("coordinates")
            if not coords or len(coords) < 2:
                continue
            lon, lat = coords[0], coords[1]
            train_number = str(item.get("trainNumber", "") or "").strip()
            route_bits = [
                str(item.get("departureStationShortCode") or "").strip(),
                str(item.get("stationShortCode") or "").strip(),
            ]
            route = " -> ".join([bit for bit in route_bits if bit])
            train_type = str(item.get("trainType") or "").strip()
            normalized = _normalize_train(
                source="digitraffic",
                raw_id=f"FIN-{train_number or len(trains)}",
                name=f"{train_type} {train_number}".strip() or f"Train {train_number or '?'}",
                number=train_number,
                lat=lat,
                lng=lon,
                speed_kmh=item.get("speed"),
                heading=item.get("heading"),
                status="Active",
                route=route,
                observed_at=item.get("timestamp"),
            )
            if normalized:
                trains.append(normalized)
        return trains
    except Exception as exc:
        logger.warning("DigiTraffic fetch error: %s", exc)
        return []


_TRAIN_FETCHERS: tuple[tuple[str, Callable[[], list[dict]]], ...] = (
    ("amtrak", _fetch_amtraker),
    ("digitraffic", _fetch_digitraffic),
)


def fetch_trains():
    """Fetch trains from all configured sources and merge without duplicates."""
    with _data_lock:
        existing_trains = list(latest_data.get("trains") or [])
    source_batches: list[list[dict]] = []
    source_counts: list[str] = []
    for source_name, fetcher in _TRAIN_FETCHERS:
        batch = fetcher()
        source_batches.append(batch)
        if batch:
            source_counts.append(f"{source_name}:{len(batch)}")

    trains = _merge_nonredundant_trains(*source_batches)
    if not trains and existing_trains:
        logger.warning(
            "Train refresh returned 0 records — preserving %s cached trains until the next successful poll",
            len(existing_trains),
        )
        trains = existing_trains

    with _data_lock:
        latest_data["trains"] = trains
    _mark_fresh("trains")
    logger.info(
        "Trains: %s total%s",
        len(trains),
        f" ({', '.join(source_counts)})" if source_counts else "",
    )
