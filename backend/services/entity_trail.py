"""Resolve live movement history (trail + route) for aircraft and vessels."""

from __future__ import annotations

import math
from typing import Any

from services.telemetry import find_entity


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _norm_key(value: str) -> str:
    return str(value or "").strip().lower()


def _is_known_route_name(value: str) -> bool:
    normalized = str(value or "").strip().upper()
    return bool(normalized and normalized != "UNKNOWN")


def _bearing_deg(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_lambda = math.radians(lng2 - lng1)
    y = math.sin(d_lambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(d_lambda)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def _compact_trail_points(points: list, *, max_points: int = 80) -> list[dict[str, Any]]:
    if not points:
        return []
    if len(points) <= max_points:
        selected = points
    else:
        step = max(1, len(points) // max_points)
        selected = points[::step]
        if selected[-1] is not points[-1]:
            selected.append(points[-1])

    out: list[dict[str, Any]] = []
    for point in selected:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        lat = _coerce_float(point[0])
        lng = _coerce_float(point[1])
        if lat is None or lng is None:
            continue
        item: dict[str, Any] = {
            "lat": round(lat, 5),
            "lng": round(lng, 5),
        }
        if len(point) >= 3:
            alt = _coerce_float(point[2])
            if alt is not None:
                item["alt_ft"] = round(alt, 1)
        if len(point) >= 4:
            ts = _coerce_float(point[3])
            if ts is not None:
                item["ts"] = round(ts, 1)
        out.append(item)
    return out


def _route_from_entity(entity: dict[str, Any]) -> dict[str, Any]:
    origin_name = str(entity.get("origin_name") or "").strip()
    dest_name = str(entity.get("dest_name") or "").strip()
    origin_loc = entity.get("origin_loc")
    dest_loc = entity.get("dest_loc")
    if _is_known_route_name(origin_name) and _is_known_route_name(dest_name):
        return {
            "origin_name": origin_name,
            "dest_name": dest_name,
            "origin_loc": origin_loc,
            "dest_loc": dest_loc,
            "source": "entity_field",
        }
    return {}


def _route_from_database(callsign: str) -> dict[str, Any]:
    from services.fetchers.route_database import lookup_route

    route = lookup_route(callsign)
    if not route:
        return {}
    return {
        "origin_name": route.get("orig_name"),
        "dest_name": route.get("dest_name"),
        "origin_loc": route.get("orig_loc"),
        "dest_loc": route.get("dest_loc"),
        "source": "route_database",
    }


def _datalink_hints(*, icao24: str = "", registration: str = "", callsign: str = "") -> list[str]:
    try:
        from services.fetchers.airframes import lookup_datalink_messages

        result = lookup_datalink_messages(
            icao24=icao24,
            registration=registration,
            callsign=callsign,
            allow_live=False,
        )
    except Exception:
        return []

    hints: list[str] = []
    for message in result.get("messages") or []:
        if not isinstance(message, dict):
            continue
        summary = str(message.get("summary") or "").strip()
        if summary:
            hints.append(summary)
        if len(hints) >= 5:
            break
    return hints


def _flight_trail(icao24: str) -> list:
    from services.fetchers.flights import get_flight_trail

    return get_flight_trail(icao24)


def _ship_trail(mmsi: int | str) -> list:
    from services.ais_stream import get_vessel_trail

    try:
        return get_vessel_trail(int(mmsi))
    except (TypeError, ValueError):
        return []


def _movement_summary(points: list[dict[str, Any]]) -> dict[str, Any]:
    if not points:
        return {}
    first = points[0]
    last = points[-1]
    summary: dict[str, Any] = {
        "first_point": first,
        "last_point": last,
        "point_count": len(points),
    }
    if first.get("ts") and last.get("ts"):
        duration_s = max(0.0, float(last["ts"]) - float(first["ts"]))
        summary["duration_minutes"] = round(duration_s / 60.0, 1)
        summary["first_seen_at"] = first["ts"]
        summary["last_seen_at"] = last["ts"]
    if len(points) >= 2:
        summary["bearing_deg"] = round(
            _bearing_deg(first["lat"], first["lng"], last["lat"], last["lng"]),
            1,
        )
        if len(points) >= 3:
            prev = points[-2]
            summary["current_heading_deg"] = round(
                _bearing_deg(prev["lat"], prev["lng"], last["lat"], last["lng"]),
                1,
            )
    return summary


def get_entity_trail(
    *,
    query: str = "",
    entity_type: str = "",
    callsign: str = "",
    registration: str = "",
    icao24: str = "",
    mmsi: str = "",
    imo: str = "",
    name: str = "",
    owner: str = "",
    max_points: int = 80,
    include_datalink: bool = True,
) -> dict[str, Any]:
    """Return movement history and route context for a resolved aircraft or vessel."""
    lookup = find_entity(
        query=query,
        entity_type=entity_type,
        callsign=callsign,
        registration=registration,
        icao24=icao24,
        mmsi=mmsi,
        imo=imo,
        name=name,
        owner=owner,
        limit=3,
        fallback_search=True,
    )
    entity = lookup.get("best_match") if isinstance(lookup.get("best_match"), dict) else None
    if not entity:
        return {
            "status": "unresolved",
            "lookup": lookup,
            "entity": None,
            "trail": [],
            "route": {},
            "movement": {},
            "datalink_hints": [],
            "notes": [
                "No matching aircraft or vessel in live layers.",
                "Trails accumulate while ShadowBroker is running; they are not pre-flight history.",
            ],
        }

    group = _norm_key(entity.get("group") or entity.get("entity_group") or "")
    source_layer = _norm_key(entity.get("source_layer") or "")
    is_ship = group == "maritime" or source_layer == "ships" or bool(entity.get("mmsi"))

    raw_points: list = []
    entity_id = ""
    if is_ship:
        mmsi_value = entity.get("mmsi")
        if mmsi_value is not None:
            entity_id = str(mmsi_value)
            raw_points = _ship_trail(mmsi_value)
    else:
        hex_id = str(entity.get("icao24") or "").strip().lower()
        entity_id = hex_id
        if hex_id:
            raw_points = _flight_trail(hex_id)

    max_points = max(10, min(int(max_points or 80), 200))
    trail = _compact_trail_points(raw_points, max_points=max_points)
    movement = _movement_summary(trail)

    route = _route_from_entity(entity)
    if not route:
        callsign_value = str(
            entity.get("callsign") or entity.get("flight") or entity.get("call") or callsign or ""
        ).strip()
        if callsign_value:
            route = _route_from_database(callsign_value)

    datalink_hints: list[str] = []
    if include_datalink and not is_ship:
        datalink_hints = _datalink_hints(
            icao24=str(entity.get("icao24") or icao24 or ""),
            registration=str(entity.get("registration") or registration or ""),
            callsign=str(entity.get("callsign") or callsign or ""),
        )

    notes = [
        "Trail points are observed positions since this ShadowBroker instance started tracking the entity.",
        "Use Time Machine snapshots for longer historical playback when enabled.",
    ]
    if not trail:
        notes.insert(
            0,
            "No trail points yet — the entity may have just appeared or trail retention expired.",
        )
    elif not route:
        notes.append("Route origin/destination unknown; infer direction from trail bearing only.")

    status = "trail_available" if trail else "resolved_without_trail"
    return {
        "status": status,
        "lookup": lookup,
        "entity": entity,
        "entity_id": entity_id,
        "entity_kind": "ship" if is_ship else "aircraft",
        "trail": trail,
        "route": route,
        "movement": movement,
        "datalink_hints": datalink_hints,
        "notes": notes,
    }


def movement_context_for_entity(entity: dict[str, Any], *, max_points: int = 40) -> dict[str, Any]:
    """Compact movement block for correlate_entity and dossier helpers."""
    if not isinstance(entity, dict):
        return {}
    result = get_entity_trail(
        icao24=str(entity.get("icao24") or ""),
        mmsi=str(entity.get("mmsi") or ""),
        registration=str(entity.get("registration") or ""),
        callsign=str(entity.get("callsign") or entity.get("flight") or ""),
        entity_type="ship" if entity.get("mmsi") else "aircraft",
        max_points=max_points,
        include_datalink=True,
    )
    return {
        "trail_point_count": len(result.get("trail") or []),
        "trail": result.get("trail") or [],
        "route": result.get("route") or {},
        "movement": result.get("movement") or {},
        "datalink_hints": result.get("datalink_hints") or [],
        "notes": result.get("notes") or [],
    }
