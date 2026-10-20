"""Bundled entity intelligence profile for OpenClaw agents."""

from __future__ import annotations

from typing import Any

from services.entity_trail import get_entity_trail
from services.fetchers._store import get_latest_data_subset_refs
from services.telemetry import find_entity, search_news

_AIRCRAFT_LAYERS = (
    "tracked_flights",
    "military_flights",
    "private_jets",
    "private_flights",
    "commercial_flights",
)


def _pick_str(entity: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = entity.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _full_record(entity: dict[str, Any]) -> dict[str, Any]:
    """Re-load the enriched store record (holding, emissions, alert_tags, etc.)."""
    icao = _pick_str(entity, "icao24").lower()
    mmsi = _pick_str(entity, "mmsi")
    if icao:
        snap = get_latest_data_subset_refs(*_AIRCRAFT_LAYERS)
        for layer in _AIRCRAFT_LAYERS:
            for item in snap.get(layer) or []:
                if not isinstance(item, dict):
                    continue
                if str(item.get("icao24") or "").lower() == icao:
                    merged = dict(item)
                    merged.setdefault("source_layer", layer)
                    return merged
    if mmsi:
        snap = get_latest_data_subset_refs("ships")
        items = snap.get("ships") or []
        if isinstance(items, dict):
            items = items.get("vessels", []) or items.get("items", [])
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            if str(item.get("mmsi") or "") == mmsi:
                merged = dict(item)
                merged.setdefault("source_layer", "ships")
                return merged
    return dict(entity)


def _identity_block(entity: dict[str, Any], *, is_ship: bool) -> dict[str, Any]:
    block: dict[str, Any] = {
        "label": _pick_str(entity, "label", "callsign", "name", "tracked_name"),
        "callsign": _pick_str(entity, "callsign", "flight", "call"),
        "registration": _pick_str(entity, "registration", "r"),
        "icao24": _pick_str(entity, "icao24"),
        "mmsi": _pick_str(entity, "mmsi"),
        "imo": _pick_str(entity, "imo"),
        "name": _pick_str(entity, "name", "shipName", "tracked_name", "yacht_name"),
        "type": _pick_str(entity, "type", "t", "aircraft_type", "shipType"),
        "owner": _pick_str(entity, "owner", "operator", "alert_operator", "yacht_owner"),
        "source_layer": _pick_str(entity, "source_layer", "layer"),
        "country": _pick_str(entity, "country", "flag"),
    }
    if not is_ship:
        tags = entity.get("alert_tags") or entity.get("intel_tags")
        if tags:
            block["tags"] = tags if isinstance(tags, list) else str(tags)
        for key in (
            "alert_category",
            "alert_operator",
            "alert_color",
            "alert_type",
            "alert_link",
            "alert_wiki",
            "alert_socials",
            "tracked_name",
            "intel_tags",
            "squawk",
        ):
            value = entity.get(key)
            if value not in (None, "", [], {}):
                block[key] = value
    else:
        for key in ("tracked_name", "tracked_category", "yacht_owner", "yacht_name", "yacht_category"):
            value = entity.get(key)
            if value not in (None, ""):
                block[key] = value
    return block


def _position_block(entity: dict[str, Any]) -> dict[str, Any]:
    return {
        "lat": entity.get("lat") or entity.get("latitude"),
        "lng": entity.get("lng") or entity.get("lon") or entity.get("longitude"),
        "alt_ft": entity.get("alt") or entity.get("altitude") or entity.get("alt_baro"),
        "speed_knots": entity.get("speed_knots") or entity.get("speed") or entity.get("gs") or entity.get("sog"),
        "heading_deg": entity.get("heading") or entity.get("true_track") or entity.get("track") or entity.get("course"),
        "on_ground": bool(entity.get("on_ground")) if "on_ground" in entity else None,
    }


def _aircraft_state(entity: dict[str, Any]) -> dict[str, Any]:
    state: dict[str, Any] = {}
    if entity.get("holding") is not None:
        state["holding"] = bool(entity.get("holding"))
    emissions = entity.get("emissions")
    if isinstance(emissions, dict) and emissions:
        state["emissions"] = {
            key: emissions[key]
            for key in (
                "fuel_gph",
                "co2_kg_per_hour",
                "fuel_gallons_burned",
                "co2_kg_emitted",
                "observation_seconds",
            )
            if emissions.get(key) is not None
        }
    return state


def _datalink_block(
    *,
    icao24: str,
    registration: str,
    callsign: str,
    include_messages: bool,
    message_limit: int,
) -> dict[str, Any]:
    try:
        from services.fetchers.airframes import lookup_datalink_messages

        result = lookup_datalink_messages(
            icao24=icao24,
            registration=registration,
            callsign=callsign,
            allow_live=False,
        )
    except Exception:
        return {"configured": False, "messages": [], "hints": [], "hidden_count": 0}

    messages = result.get("messages") or []
    hints = [
        str(msg.get("summary") or "").strip()
        for msg in messages
        if isinstance(msg, dict) and str(msg.get("summary") or "").strip()
    ][:5]
    block: dict[str, Any] = {
        "configured": bool(result.get("configured")),
        "hints": hints,
        "hidden_count": int(result.get("hidden_count") or 0),
        "queued_refresh": bool(result.get("queued_refresh") or result.get("priority_scan")),
    }
    if include_messages:
        block["messages"] = messages[: max(1, min(message_limit, 20))]
    return block


def _nearby_context(
    *,
    lat: float,
    lng: float,
    radius_km: float,
    is_ship: bool,
) -> dict[str, Any]:
    from services.telemetry import _nearby_items_from_layers

    layers = ["correlations", "gps_jamming", "sar_anomalies", "internet_outages"]
    if is_ship:
        layers.append("fishing_activity")
    context = _nearby_items_from_layers(
        lat=lat,
        lng=lng,
        radius_km=radius_km,
        layers=tuple(layers),
        limit_per_layer=5,
    )
    return {layer: items for layer, items in context.items() if items}


def get_entity_profile(
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
    max_trail_points: int = 80,
    include_datalink: bool = True,
    include_datalink_messages: bool = False,
    datalink_message_limit: int = 8,
    include_news: bool = True,
    news_limit: int = 5,
    context_radius_km: float = 120,
    include_nearby_context: bool = True,
) -> dict[str, Any]:
    """One-shot dossier: identity, position, trail, route, enrichment, and context."""
    trail_pack = get_entity_trail(
        query=query,
        entity_type=entity_type,
        callsign=callsign,
        registration=registration,
        icao24=icao24,
        mmsi=mmsi,
        imo=imo,
        name=name,
        owner=owner,
        max_points=max_trail_points,
        include_datalink=False,
    )
    if trail_pack.get("status") == "unresolved":
        return {
            "status": "unresolved",
            "lookup": trail_pack.get("lookup"),
            "recommended_next": [
                "Try registration, ICAO24, MMSI, callsign, or owner.",
                "Use track_entity to get alerts when the entity reappears.",
            ],
        }

    entity = _full_record(trail_pack.get("entity") or {})
    is_ship = trail_pack.get("entity_kind") == "ship"
    identity = _identity_block(entity, is_ship=is_ship)
    position = _position_block(entity)

    profile: dict[str, Any] = {
        "status": trail_pack.get("status"),
        "entity_kind": trail_pack.get("entity_kind"),
        "lookup": trail_pack.get("lookup"),
        "identity": identity,
        "position": position,
        "trail": trail_pack.get("trail") or [],
        "route": trail_pack.get("route") or {},
        "movement": trail_pack.get("movement") or {},
        "notes": trail_pack.get("notes") or [],
    }

    if not is_ship:
        aircraft_state = _aircraft_state(entity)
        if aircraft_state:
            profile["aircraft_state"] = aircraft_state
        if include_datalink:
            profile["datalink"] = _datalink_block(
                icao24=_pick_str(entity, "icao24") or icao24,
                registration=_pick_str(entity, "registration") or registration,
                callsign=_pick_str(entity, "callsign", "flight") or callsign,
                include_messages=include_datalink_messages,
                message_limit=datalink_message_limit,
            )

    lat = position.get("lat")
    lng = position.get("lng")
    if include_nearby_context and lat is not None and lng is not None:
        profile["nearby_context"] = _nearby_context(
            lat=float(lat),
            lng=float(lng),
            radius_km=max(10.0, min(float(context_radius_km or 120), 500.0)),
            is_ship=is_ship,
        )

    if include_news:
        news_query = (
            _pick_str(entity, "alert_operator", "owner", "operator", "tracked_name", "name")
            or _pick_str(entity, "registration", "callsign")
            or query
        )
        if news_query:
            profile["related_news"] = search_news(query=news_query, limit=max(1, min(news_limit, 15)))

    profile["recommended_next"] = [
        "Use correlate_entity for nearby-event evidence packs.",
        "Use track_entity for forward monitoring without re-querying.",
        "Use get_entity_trail when you only need movement history.",
    ]
    if not profile.get("route"):
        profile["recommended_next"].insert(
            0,
            "Route unknown — check datalink hints or wait for callsign route database match.",
        )
    return profile
