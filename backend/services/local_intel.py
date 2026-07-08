from __future__ import annotations

import math
import os
import time
from typing import Any


LOCAL_INTEL_KEYS = (
    "commercial_flights",
    "private_flights",
    "private_jets",
    "military_flights",
    "tracked_flights",
    "uavs",
    "ships",
    "earthquakes",
    "firms_fires",
    "weather_alerts",
    "air_quality",
    "volcanoes",
    "internet_outages",
    "military_bases",
    "power_plants",
    "datacenters",
    "cctv",
    "kiwisdr",
    "psk_reporter",
    "satnogs_stations",
    "tinygs_satellites",
    "scanners",
    "sigint",
    "satellites",
    "news",
    "gdelt",
    "liveuamap",
    "wastewater",
    "uap_sightings",
    "trains",
)

EARTH_RADIUS_KM = 6371.0088


def configured_default_point() -> tuple[float, float] | None:
    lat = _to_float(os.environ.get("LOCAL_INTEL_LAT"))
    lng = _to_float(os.environ.get("LOCAL_INTEL_LNG"))
    if lat is None or lng is None or not _valid_point(lat, lng):
        return None
    return lat, lng


def configured_default_radius_km() -> float:
    radius = _to_float(os.environ.get("LOCAL_INTEL_RADIUS_KM"))
    if radius is None:
        return 150.0
    return _clamp(radius, 5.0, 1000.0)


def build_local_intel(
    *,
    lat: float,
    lng: float,
    radius_km: float,
    data: dict[str, Any],
    freshness: dict[str, str] | None = None,
    limit: int = 48,
) -> dict[str, Any]:
    radius = _clamp(radius_km, 5.0, 1000.0)
    items: list[dict[str, Any]] = []

    _collect_air(items, data, lat, lng, radius)
    _collect_maritime(items, data, lat, lng, radius)
    _collect_hazards(items, data, lat, lng, radius)
    _collect_infrastructure(items, data, lat, lng, radius)
    _collect_rf(items, data, lat, lng, radius)
    _collect_space(items, data, lat, lng, radius)
    _collect_intel(items, data, lat, lng, radius)
    _collect_health_and_mobility(items, data, lat, lng, radius)

    items.sort(key=lambda item: (-float(item["score"]), float(item["distance_km"]), str(item["label"])))
    limited = items[: max(1, min(100, int(limit or 48)))]
    counts: dict[str, int] = {}
    for item in items:
        category = str(item.get("category") or "other")
        counts[category] = counts.get(category, 0) + 1

    return {
        "query": {
            "lat": round(lat, 6),
            "lng": round(lng, 6),
            "radius_km": radius,
            "generated_at": int(time.time()),
        },
        "summary": {
            "total": len(items),
            "returned": len(limited),
            "categories": counts,
            "highest_severity": _highest_severity(limited),
        },
        "watch": [item for item in limited if int(item.get("severity_rank", 0)) >= 3][:8],
        "items": limited,
        "freshness": {
            key: freshness[key]
            for key in LOCAL_INTEL_KEYS
            if freshness and freshness.get(key)
        },
    }


def _collect_air(items: list[dict[str, Any]], data: dict[str, Any], lat: float, lng: float, radius: float) -> None:
    specs = (
        ("tracked_flights", "tracked aircraft", 4),
        ("military_flights", "military aircraft", 3),
        ("uavs", "uav", 3),
        ("private_jets", "private jet", 2),
        ("private_flights", "private aircraft", 2),
        ("commercial_flights", "commercial aircraft", 1),
    )
    for key, kind, rank in specs:
        for entry in _iter_entries(data.get(key)):
            callsign = _first_text(entry, "callsign", "tracked_name", "registration", "icao24", fallback=kind)
            model = _first_text(entry, "model", "aircraft_model", "force", fallback="")
            alt = _to_float(entry.get("alt"))
            speed = _to_float(entry.get("speed_knots"))
            detail_parts = [part for part in (model, _format_alt_speed(alt, speed)) if part]
            _append_item(
                items,
                lat,
                lng,
                radius,
                entry,
                category="air",
                kind=kind,
                source_key=key,
                label=callsign,
                detail=" / ".join(detail_parts) or kind,
                severity_rank=rank,
                base_score=7 if rank >= 3 else 3,
            )


def _collect_maritime(items: list[dict[str, Any]], data: dict[str, Any], lat: float, lng: float, radius: float) -> None:
    for entry in _iter_entries(data.get("ships")):
        ship_type = _first_text(entry, "type", fallback="vessel")
        rank = 3 if ship_type in {"carrier", "military_vessel"} else 1
        label = _first_text(entry, "name", "plan_name", "yacht_name", "mmsi", fallback=ship_type)
        destination = _first_text(entry, "destination", "fallback_desc", "country", fallback="")
        _append_item(
            items,
            lat,
            lng,
            radius,
            entry,
            category="maritime",
            kind=ship_type,
            source_key="ships",
            label=label,
            detail=destination or ship_type,
            severity_rank=rank,
            base_score=5 if rank >= 3 else 2,
        )


def _collect_hazards(items: list[dict[str, Any]], data: dict[str, Any], lat: float, lng: float, radius: float) -> None:
    for entry in _iter_entries(data.get("earthquakes")):
        mag = _to_float(entry.get("mag")) or 0.0
        rank = 4 if mag >= 5.5 else 3 if mag >= 4.0 else 2
        _append_item(
            items,
            lat,
            lng,
            radius,
            entry,
            category="hazard",
            kind="earthquake",
            source_key="earthquakes",
            label=f"M{mag:.1f} earthquake",
            detail=_first_text(entry, "place", "title", fallback="USGS event"),
            severity_rank=rank,
            base_score=10,
        )

    for entry in _iter_entries(data.get("weather_alerts")):
        severity = _first_text(entry, "severity", fallback="")
        rank = _rank_from_words(severity, default=2)
        _append_item(
            items,
            lat,
            lng,
            radius,
            entry,
            category="hazard",
            kind="weather alert",
            source_key="weather_alerts",
            label=_first_text(entry, "event", "headline", fallback="Weather alert"),
            detail=_first_text(entry, "headline", "description", fallback=severity or "NWS alert"),
            severity_rank=rank,
            base_score=12,
        )

    for entry in _iter_entries(data.get("firms_fires")):
        frp = _to_float(entry.get("frp")) or 0.0
        rank = 4 if frp >= 500 else 3 if frp >= 100 else 2
        _append_item(
            items,
            lat,
            lng,
            radius,
            entry,
            category="hazard",
            kind="thermal anomaly",
            source_key="firms_fires",
            label="Thermal anomaly",
            detail=f"FRP {frp:.0f} MW / {_first_text(entry, 'confidence', fallback='nominal')}",
            severity_rank=rank,
            base_score=8,
        )

    for entry in _iter_entries(data.get("air_quality")):
        aqi = int(_to_float(entry.get("aqi")) or 0)
        rank = 4 if aqi >= 151 else 3 if aqi >= 101 else 2 if aqi >= 51 else 1
        _append_item(
            items,
            lat,
            lng,
            radius,
            entry,
            category="hazard",
            kind="air quality",
            source_key="air_quality",
            label=_first_text(entry, "name", fallback="Air quality station"),
            detail=f"AQI {aqi}",
            severity_rank=rank,
            base_score=5,
        )

    for entry in _iter_entries(data.get("volcanoes")):
        _append_item(
            items,
            lat,
            lng,
            radius,
            entry,
            category="hazard",
            kind="volcano",
            source_key="volcanoes",
            label=_first_text(entry, "name", fallback="Volcano"),
            detail=_first_text(entry, "type", "region", "country", fallback="volcanic feature"),
            severity_rank=2,
            base_score=3,
        )


def _collect_infrastructure(
    items: list[dict[str, Any]], data: dict[str, Any], lat: float, lng: float, radius: float
) -> None:
    for key, kind, rank in (
        ("military_bases", "military base", 2),
        ("power_plants", "power plant", 1),
        ("datacenters", "data center", 1),
        ("internet_outages", "internet outage", 3),
    ):
        for entry in _iter_entries(data.get(key)):
            label = _first_text(entry, "name", "region_name", "company", fallback=kind)
            detail = _first_text(entry, "operator", "fuel_type", "country_name", "country", "city", fallback=kind)
            severity = rank
            if key == "internet_outages":
                severity = max(rank, min(4, int((_to_float(entry.get("severity")) or 1) + 1)))
            _append_item(
                items,
                lat,
                lng,
                radius,
                entry,
                category="infrastructure",
                kind=kind,
                source_key=key,
                label=label,
                detail=detail,
                severity_rank=severity,
                base_score=4,
            )


def _collect_rf(items: list[dict[str, Any]], data: dict[str, Any], lat: float, lng: float, radius: float) -> None:
    for entry in _iter_entries(data.get("scanners")):
        _append_item(
            items,
            lat,
            lng,
            radius,
            entry,
            category="rf",
            kind="scanner",
            source_key="scanners",
            label=_first_text(entry, "name", "shortName", fallback="OpenMHz scanner"),
            detail=_first_text(entry, "city", "state", "description", fallback="public safety audio"),
            severity_rank=1,
            base_score=7,
        )

    for entry in _iter_entries(data.get("kiwisdr")):
        _append_item(
            items,
            lat,
            lng,
            radius,
            entry,
            category="rf",
            kind="sdr receiver",
            source_key="kiwisdr",
            label=_first_text(entry, "name", "location", fallback="KiwiSDR receiver"),
            detail=_first_text(entry, "bands", "antenna", fallback="shortwave receiver"),
            severity_rank=1,
            base_score=5,
        )

    for entry in _iter_entries(data.get("sigint")):
        emergency = bool(entry.get("emergency"))
        _append_item(
            items,
            lat,
            lng,
            radius,
            entry,
            category="rf",
            kind=_first_text(entry, "source", fallback="radio signal"),
            source_key="sigint",
            label=_first_text(entry, "callsign", "long_name", "short_name", fallback="Radio signal"),
            detail=_first_text(entry, "comment", "status", "region", fallback="positioned signal"),
            severity_rank=4 if emergency else 1,
            base_score=8 if emergency else 4,
        )

    for key, kind in (("psk_reporter", "digital spot"), ("satnogs_stations", "satnogs station")):
        for entry in _iter_entries(data.get(key)):
            _append_item(
                items,
                lat,
                lng,
                radius,
                entry,
                category="rf",
                kind=kind,
                source_key=key,
                label=_first_text(entry, "name", "sender", "station_name", fallback=kind),
                detail=_first_text(entry, "mode", "frequency", "antenna", fallback=kind),
                severity_rank=1,
                base_score=2,
            )


def _collect_space(items: list[dict[str, Any]], data: dict[str, Any], lat: float, lng: float, radius: float) -> None:
    for key, kind in (("satellites", "satellite ground track"), ("tinygs_satellites", "tinygs satellite")):
        for entry in _iter_entries(data.get(key)):
            mission = _first_text(entry, "mission", "sat_type", "status", fallback=kind)
            rank = 2 if any(word in mission.lower() for word in ("military", "sigint", "early_warning")) else 1
            _append_item(
                items,
                lat,
                lng,
                radius,
                entry,
                category="space",
                kind=kind,
                source_key=key,
                label=_first_text(entry, "name", "id", fallback=kind),
                detail=mission,
                severity_rank=rank,
                base_score=3,
            )


def _collect_intel(items: list[dict[str, Any]], data: dict[str, Any], lat: float, lng: float, radius: float) -> None:
    for entry in _iter_entries(data.get("news")):
        risk = _to_float(entry.get("risk_score")) or 0.0
        rank = 4 if risk >= 0.8 else 3 if risk >= 0.55 else 2 if risk >= 0.3 else 1
        _append_item(
            items,
            lat,
            lng,
            radius,
            entry,
            category="intel",
            kind="news",
            source_key="news",
            label=_first_text(entry, "title", fallback="News item"),
            detail=_first_text(entry, "source", "region", "summary", fallback="geocoded news"),
            severity_rank=rank,
            base_score=8,
            url=_first_text(entry, "link", fallback=""),
            timestamp=_first_text(entry, "pub_date", fallback=""),
        )

    for entry in _iter_entries(data.get("gdelt")):
        props = entry.get("properties") if isinstance(entry, dict) else {}
        props = props if isinstance(props, dict) else {}
        count = int(_to_float(props.get("count")) or 0)
        mentions = int(_to_float(props.get("num_mentions")) or 0)
        rank = 4 if count >= 20 or mentions >= 100 else 3 if count >= 8 or mentions >= 40 else 2
        headlines = props.get("_headlines_list") if isinstance(props.get("_headlines_list"), list) else []
        _append_item(
            items,
            lat,
            lng,
            radius,
            entry,
            category="intel",
            kind="gdelt cluster",
            source_key="gdelt",
            label=_first_text(props, "name", fallback="GDELT cluster"),
            detail=str(headlines[0]) if headlines else f"{count} event(s), {mentions} mentions",
            severity_rank=rank,
            base_score=7,
            timestamp=_first_text(props, "event_date", fallback=""),
        )

    for key, kind in (("liveuamap", "live incident"), ("uap_sightings", "uap sighting")):
        for entry in _iter_entries(data.get(key)):
            _append_item(
                items,
                lat,
                lng,
                radius,
                entry,
                category="intel",
                kind=kind,
                source_key=key,
                label=_first_text(entry, "title", "summary", "city", fallback=kind),
                detail=_first_text(entry, "description", "region", "state", "country", fallback=kind),
                severity_rank=2,
                base_score=5,
                url=_first_text(entry, "link", "source", fallback=""),
                timestamp=_first_text(entry, "date", "timestamp", "date_time", fallback=""),
            )


def _collect_health_and_mobility(
    items: list[dict[str, Any]], data: dict[str, Any], lat: float, lng: float, radius: float
) -> None:
    for entry in _iter_entries(data.get("wastewater")):
        alert_count = int(_to_float(entry.get("alert_count")) or 0)
        _append_item(
            items,
            lat,
            lng,
            radius,
            entry,
            category="health",
            kind="wastewater",
            source_key="wastewater",
            label=_first_text(entry, "site_name", "name", fallback="Wastewater site"),
            detail=f"{alert_count} pathogen alert(s)" if alert_count else "pathogen monitoring",
            severity_rank=4 if alert_count >= 3 else 3 if alert_count else 1,
            base_score=5,
        )

    for entry in _iter_entries(data.get("trains")):
        _append_item(
            items,
            lat,
            lng,
            radius,
            entry,
            category="mobility",
            kind="train",
            source_key="trains",
            label=_first_text(entry, "name", "number", "id", fallback="Train"),
            detail=_first_text(entry, "route", "status", "operator", fallback="rail movement"),
            severity_rank=1,
            base_score=2,
        )

    for entry in _iter_entries(data.get("cctv")):
        _append_item(
            items,
            lat,
            lng,
            radius,
            entry,
            category="infrastructure",
            kind="camera",
            source_key="cctv",
            label=_first_text(entry, "source_agency", "id", fallback="Traffic camera"),
            detail=_first_text(entry, "direction_facing", "media_type", fallback="camera"),
            severity_rank=1,
            base_score=1,
        )


def _append_item(
    items: list[dict[str, Any]],
    origin_lat: float,
    origin_lng: float,
    radius_km: float,
    raw: Any,
    *,
    category: str,
    kind: str,
    source_key: str,
    label: str,
    detail: str,
    severity_rank: int,
    base_score: float,
    url: str = "",
    timestamp: str = "",
) -> None:
    point = _point_from_item(raw)
    if point is None:
        return
    item_lat, item_lng = point
    distance = _distance_km(origin_lat, origin_lng, item_lat, item_lng)
    if distance > radius_km:
        return
    closeness = 1.0 - min(1.0, distance / max(radius_km, 1.0))
    rank = max(1, min(4, int(severity_rank or 1)))
    score = base_score + rank * 12.0 + closeness * 18.0
    items.append(
        {
            "id": f"{source_key}:{len(items)}:{round(item_lat, 4)}:{round(item_lng, 4)}",
            "category": category,
            "kind": kind,
            "source_key": source_key,
            "label": _truncate(label, 96),
            "detail": _truncate(detail, 180),
            "lat": round(item_lat, 6),
            "lng": round(item_lng, 6),
            "distance_km": round(distance, 1),
            "severity": _severity_name(rank),
            "severity_rank": rank,
            "score": round(score, 2),
            "timestamp": _truncate(timestamp, 80),
            "url": url if url.startswith(("http://", "https://")) else "",
        }
    )


def _point_from_item(item: Any) -> tuple[float, float] | None:
    if not isinstance(item, dict):
        return None
    lat = _to_float(item.get("lat", item.get("latitude")))
    lng = _to_float(item.get("lng", item.get("lon", item.get("longitude"))))
    if lat is not None and lng is not None and _valid_point(lat, lng):
        return lat, lng

    coords = item.get("coords")
    point = _point_from_coords(coords)
    if point is not None:
        return point

    geometry = item.get("geometry")
    return _point_from_geometry(geometry)


def _point_from_geometry(geometry: Any) -> tuple[float, float] | None:
    if not isinstance(geometry, dict):
        return None
    if geometry.get("type") == "Point":
        return _point_from_coords(geometry.get("coordinates"), geojson=True)
    points: list[tuple[float, float]] = []
    _collect_geojson_points(geometry.get("coordinates"), points)
    if not points:
        return None
    return sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)


def _point_from_coords(coords: Any, *, geojson: bool = False) -> tuple[float, float] | None:
    if not isinstance(coords, (list, tuple)) or len(coords) < 2:
        return None
    first = _to_float(coords[0])
    second = _to_float(coords[1])
    if first is None or second is None:
        return None
    lat, lng = (second, first) if geojson or abs(first) > 90 else (first, second)
    if _valid_point(lat, lng):
        return lat, lng
    return None


def _collect_geojson_points(coords: Any, out: list[tuple[float, float]]) -> None:
    if not isinstance(coords, (list, tuple)):
        return
    if len(coords) >= 2 and _to_float(coords[0]) is not None and _to_float(coords[1]) is not None:
        point = _point_from_coords(coords, geojson=True)
        if point is not None:
            out.append(point)
        return
    for child in coords:
        _collect_geojson_points(child, out)


def _iter_entries(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [entry for entry in value if isinstance(entry, dict)]
    if isinstance(value, dict):
        for key in ("posts", "threats", "suppliers", "corridors", "features"):
            nested = value.get(key)
            if isinstance(nested, list):
                return [entry for entry in nested if isinstance(entry, dict)]
    return []


def _distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _rank_from_words(value: str, *, default: int = 1) -> int:
    text = value.lower()
    if any(word in text for word in ("extreme", "severe", "emergency", "red")):
        return 4
    if any(word in text for word in ("high", "moderate", "warning", "orange")):
        return 3
    if any(word in text for word in ("minor", "low", "watch", "yellow")):
        return 2
    return default


def _severity_name(rank: int) -> str:
    return {4: "critical", 3: "elevated", 2: "watch", 1: "normal"}.get(rank, "normal")


def _highest_severity(items: list[dict[str, Any]]) -> str:
    rank = max((int(item.get("severity_rank", 0)) for item in items), default=0)
    return _severity_name(rank) if rank else "none"


def _format_alt_speed(alt: float | None, speed: float | None) -> str:
    parts = []
    if alt is not None:
        parts.append(f"{int(alt):,} ft")
    if speed is not None:
        parts.append(f"{int(speed)} kt")
    return " / ".join(parts)


def _first_text(source: dict[str, Any], *keys: str, fallback: str = "") -> str:
    for key in keys:
        value = source.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return fallback


def _truncate(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."


def _to_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def _valid_point(lat: float, lng: float) -> bool:
    return -90 <= lat <= 90 and -180 <= lng <= 180


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
