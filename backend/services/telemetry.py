"""Telemetry facade — provides cached telemetry snapshots for the command channel.

Wraps services.fetchers._store so the openclaw_channel and watchdog can access
all dashboard data (fast + slow tiers) through a single import.

The data returned includes ALL enrichment — plane_alert tags, tracked names,
alert_category, alert_operator, etc. — because _store holds the post-enrichment
data that the fetchers have already processed.
"""

import math
import re
import threading
from difflib import get_close_matches
from typing import Any

from services.fetchers._store import (
    get_data_version,
    get_layer_versions,
    get_latest_data_subset,
    get_latest_data_subset_refs,
    latest_data,
)


# ---------------------------------------------------------------------------
# Fast-tier: flights, ships, sigint, satellites, CCTV, etc.
# Same keys as /api/live-data/fast
# ---------------------------------------------------------------------------

_FAST_KEYS = (
    "last_updated",
    "commercial_flights",
    "military_flights",
    "private_flights",
    "private_jets",
    "tracked_flights",
    "ships",
    "cctv",
    "uavs",
    "liveuamap",
    "gps_jamming",
    "satellites",
    "satellite_source",
    "satellite_analysis",
    "sigint",
    "sigint_totals",
    "trains",
)

# ---------------------------------------------------------------------------
# Slow-tier: news, prediction markets, GDELT, earthquakes, weather, etc.
# Same keys as /api/live-data/slow
# ---------------------------------------------------------------------------

_SLOW_KEYS = (
    "last_updated",
    "news",
    "stocks",
    "financial_source",
    "oil",
    "weather",
    "traffic",
    "earthquakes",
    "frontlines",
    "gdelt",
    "airports",
    "kiwisdr",
    "satnogs_stations",
    "satnogs_observations",
    "tinygs_satellites",
    "space_weather",
    "internet_outages",
    "firms_fires",
    "datacenters",
    "military_bases",
    "power_plants",
    "viirs_change_nodes",
    "scanners",
    "weather_alerts",
    "ukraine_alerts",
    "air_quality",
    "volcanoes",
    "fishing_activity",
    "psk_reporter",
    "crowdthreat",
    "correlations",
    "prediction_markets",
    "threat_level",
    "trending_markets",
    "uap_sightings",
    "wastewater",
    "sar_scenes",
    "sar_anomalies",
    "sar_aoi_coverage",
)


def get_cached_telemetry() -> dict[str, Any]:
    """Return a deep-copy snapshot of fast-tier telemetry data.

    Includes enriched fields: alert_category, alert_operator, alert_color,
    alert_socials, etc. — all the 'Tracked Aircraft — People' data is here
    in the tracked_flights list.
    """
    return get_latest_data_subset(*_FAST_KEYS)


def get_cached_slow_telemetry() -> dict[str, Any]:
    """Return a deep-copy snapshot of slow-tier telemetry data.

    Includes news, GDELT, prediction markets, earthquakes, weather, etc.
    """
    return get_latest_data_subset(*_SLOW_KEYS)


def get_cached_telemetry_refs() -> dict[str, Any]:
    """Return zero-copy refs to fast-tier telemetry (read-only callers only).

    Callers MUST NOT mutate the returned data.  Safe because writers replace
    top-level values atomically under the data lock.
    """
    return get_latest_data_subset_refs(*_FAST_KEYS)


def get_cached_slow_telemetry_refs() -> dict[str, Any]:
    """Return zero-copy refs to slow-tier telemetry (read-only callers only)."""
    return get_latest_data_subset_refs(*_SLOW_KEYS)


_FLIGHT_LAYER_ALIASES = {
    "commercial": "commercial_flights",
    "commercial_flights": "commercial_flights",
    "private": "private_flights",
    "private_flights": "private_flights",
    "jets": "private_jets",
    "private_jets": "private_jets",
    "military": "military_flights",
    "military_flights": "military_flights",
    "tracked": "tracked_flights",
    "tracked_flights": "tracked_flights",
    "flights": "flights",
}

_ENTITY_LAYER_ALIASES = {
    **_FLIGHT_LAYER_ALIASES,
    "ships": "ships",
    "fishing": "fishing_activity",
    "fishing_activity": "fishing_activity",
    "global_fishing_watch": "fishing_activity",
    "gfw": "fishing_activity",
    "uavs": "uavs",
    "satellites": "satellites",
    "earthquakes": "earthquakes",
    "news": "news",
    "uap": "uap_sightings",
    "ufo": "uap_sightings",
    "uap_sightings": "uap_sightings",
    "wastewater": "wastewater",
    "pins": "pins",
}

_SLICEABLE_LAYERS = tuple(dict.fromkeys(_FAST_KEYS + _SLOW_KEYS))
_LAYER_ALIASES = {
    **{key: key for key in _SLICEABLE_LAYERS},
    **_ENTITY_LAYER_ALIASES,
    "global_incidents": "gdelt",
    "prediction_markets": "prediction_markets",
    "markets": "prediction_markets",
    "weather_alerts": "weather_alerts",
    "internet_outages": "internet_outages",
    "military_bases": "military_bases",
    "power_plants": "power_plants",
    "datacenters": "datacenters",
    "scanners": "scanners",
    "air_quality": "air_quality",
    "volcanoes": "volcanoes",
    "crowdthreat": "crowdthreat",
    "correlations": "correlations",
    "psk_reporter": "psk_reporter",
    "ukraine_alerts": "ukraine_alerts",
    "frontlines": "frontlines",
    # SAR (Synthetic Aperture Radar)
    "sar": "sar_anomalies",
    "sar_scenes": "sar_scenes",
    "sar_anomalies": "sar_anomalies",
    "sar_aoi_coverage": "sar_aoi_coverage",
    "sar_coverage": "sar_aoi_coverage",
    # Satellite analysis (maneuvers, decay, Starlink)
    "satellite_analysis": "satellite_analysis",
}

_UNIVERSAL_SEARCH_DEFAULT_LAYERS = (
    "tracked_flights",
    "military_flights",
    "private_jets",
    "private_flights",
    "commercial_flights",
    "ships",
    "fishing_activity",
    "news",
    "gdelt",
    "crowdthreat",
    "frontlines",
    "liveuamap",
    "uap_sightings",
    "wastewater",
    "prediction_markets",
    "earthquakes",
    "weather_alerts",
    "internet_outages",
    "datacenters",
    "military_bases",
    "power_plants",
    "scanners",
    "air_quality",
    "volcanoes",
    "sigint",
    "cctv",
    "satellites",
    "trains",
    "kiwisdr",
    "satnogs_stations",
    "satnogs_observations",
    "tinygs_satellites",
    "psk_reporter",
    "ukraine_alerts",
)

_GENERIC_QUERY_STOPWORDS = {
    "where",
    "is",
    "the",
    "a",
    "an",
    "of",
    "to",
    "for",
    "at",
    "in",
    "on",
    "right",
    "now",
    "current",
    "currently",
    "latest",
    "recent",
    "show",
    "find",
    "look",
    "lookup",
    "track",
    "tracking",
}

_GENERIC_LAYER_HINTS: dict[str, tuple[str, ...]] = {
    "jet": ("tracked_flights", "private_jets", "private_flights", "military_flights", "commercial_flights"),
    "plane": ("tracked_flights", "private_jets", "private_flights", "military_flights", "commercial_flights"),
    "aircraft": ("tracked_flights", "private_jets", "private_flights", "military_flights", "commercial_flights"),
    "flight": ("tracked_flights", "private_jets", "private_flights", "military_flights", "commercial_flights"),
    "helicopter": ("tracked_flights", "military_flights", "private_flights"),
    "yacht": ("ships", "fishing_activity"),
    "ship": ("ships", "fishing_activity"),
    "boat": ("ships", "fishing_activity"),
    "vessel": ("ships", "fishing_activity"),
    "satellite": ("satellites", "tinygs_satellites", "satnogs_stations", "satnogs_observations"),
    "uap": ("uap_sightings",),
    "ufo": ("uap_sightings",),
    "protest": ("crowdthreat", "gdelt", "news", "frontlines", "liveuamap"),
    "riot": ("crowdthreat", "gdelt", "news", "frontlines", "liveuamap"),
    "event": ("crowdthreat", "gdelt", "news", "frontlines", "liveuamap"),
    "news": ("news", "gdelt", "crowdthreat", "frontlines", "liveuamap"),
    "plant": ("power_plants", "wastewater"),
    "datacenter": ("datacenters",),
    "data": ("datacenters",),
    "base": ("military_bases",),
    "scanner": ("scanners",),
    "camera": ("cctv",),
    "radio": ("sigint", "kiwisdr", "psk_reporter"),
}

_SEARCH_GROUP_BY_LAYER = {
    "tracked_flights": "aircraft",
    "military_flights": "aircraft",
    "private_jets": "aircraft",
    "private_flights": "aircraft",
    "commercial_flights": "aircraft",
    "ships": "maritime",
    "fishing_activity": "maritime",
    "satellites": "space",
    "tinygs_satellites": "space",
    "satnogs_stations": "space",
    "satnogs_observations": "space",
    "uap_sightings": "anomalies",
    "wastewater": "biosurveillance",
    "news": "events",
    "gdelt": "events",
    "crowdthreat": "events",
    "frontlines": "events",
    "liveuamap": "events",
    "prediction_markets": "markets",
    "weather_alerts": "hazards",
    "earthquakes": "hazards",
    "internet_outages": "infrastructure",
    "datacenters": "infrastructure",
    "military_bases": "infrastructure",
    "power_plants": "infrastructure",
    "scanners": "signals",
    "air_quality": "environment",
    "volcanoes": "environment",
    "sigint": "signals",
    "cctv": "surveillance",
    "trains": "transport",
    "kiwisdr": "signals",
    "psk_reporter": "signals",
    "ukraine_alerts": "events",
}

_SEARCH_QUERY_SYNONYMS: dict[str, tuple[str, ...]] = {
    "jets": ("jet",),
    "planes": ("plane", "aircraft"),
    "boats": ("boat", "ship", "vessel"),
    "ships": ("ship", "vessel"),
    "yachts": ("yacht",),
    "ufos": ("ufo", "uap"),
    "protests": ("protest",),
    "riots": ("riot", "protest"),
    "plants": ("plant",),
    "cameras": ("camera",),
    "radios": ("radio",),
}

_SEARCH_INDEX_LOCK = threading.Lock()
# The live index reference — swapped atomically so readers never block.
# Readers grab the reference once; writers build a new dict and swap.
_SEARCH_INDEX_REF: dict[str, Any] = {
    "version": None,
    "docs": [],
    "vocabulary": set(),
    "postings": {},
    "built_at": 0.0,
}
# Minimum seconds between full index rebuilds.  ADS-B / AIS bump the data
# version every few seconds, but the search index doesn't need to be
# perfectly real-time — a 10-second staleness window avoids rebuilding
# 50K+ docs on every single query while keeping results fresh enough.
_SEARCH_INDEX_MIN_AGE: float = 10.0

_UNIVERSAL_SEARCH_SPECS: dict[str, dict[str, Any]] = {
    "tracked_flights": {
        "fields": ("callsign", "flight", "call", "registration", "r", "icao24", "owner", "operator", "alert_operator", "type", "alert_category", "category", "intel_tags", "name"),
        "primary_fields": ("callsign", "registration", "owner", "operator", "alert_operator", "name"),
        "label_fields": ("callsign", "flight", "call", "registration"),
        "summary_fields": ("owner", "operator", "alert_operator", "category", "type", "alert_category", "intel_tags"),
        "type_fields": ("category", "type", "alert_category"),
        "id_fields": ("icao24", "registration"),
        "time_fields": ("last_seen", "updated", "timestamp"),
    },
    "military_flights": {
        "fields": ("callsign", "flight", "call", "registration", "r", "icao24", "owner", "operator", "alert_operator", "type"),
        "primary_fields": ("callsign", "registration", "icao24"),
        "label_fields": ("callsign", "flight", "call", "registration"),
        "summary_fields": ("owner", "operator", "type"),
        "type_fields": ("type",),
        "id_fields": ("icao24", "registration"),
        "time_fields": ("last_seen", "updated", "timestamp"),
    },
    "private_jets": {
        "fields": ("callsign", "registration", "r", "icao24", "owner", "operator", "type"),
        "primary_fields": ("callsign", "registration", "owner"),
        "label_fields": ("callsign", "registration"),
        "summary_fields": ("owner", "operator", "type"),
        "type_fields": ("type",),
        "id_fields": ("icao24", "registration"),
        "time_fields": ("last_seen", "updated", "timestamp"),
    },
    "private_flights": {
        "fields": ("callsign", "registration", "r", "icao24", "owner", "operator", "type"),
        "primary_fields": ("callsign", "registration", "owner"),
        "label_fields": ("callsign", "registration"),
        "summary_fields": ("owner", "operator", "type"),
        "type_fields": ("type",),
        "id_fields": ("icao24", "registration"),
        "time_fields": ("last_seen", "updated", "timestamp"),
    },
    "commercial_flights": {
        "fields": ("callsign", "flight", "call", "registration", "r", "icao24", "operator", "airline", "type"),
        "primary_fields": ("callsign", "registration", "operator", "airline"),
        "label_fields": ("callsign", "flight", "call", "registration"),
        "summary_fields": ("operator", "airline", "type"),
        "type_fields": ("type",),
        "id_fields": ("icao24", "registration"),
        "time_fields": ("last_seen", "updated", "timestamp"),
    },
    "ships": {
        "fields": ("name", "shipName", "mmsi", "imo", "callsign", "shipType", "type", "yacht_owner", "yacht_name", "yacht_category", "owner"),
        "primary_fields": ("name", "shipName", "yacht_owner", "yacht_name", "mmsi", "imo"),
        "label_fields": ("yacht_name", "name", "shipName"),
        "summary_fields": ("yacht_owner", "shipType", "type", "yacht_category", "callsign"),
        "type_fields": ("yacht_category", "shipType", "type"),
        "id_fields": ("mmsi", "imo"),
        "time_fields": ("updated", "timestamp", "last_seen"),
    },
    "fishing_activity": {
        "fields": ("name", "vessel_name", "flag", "type", "id", "vessel_id", "vessel_ssvid", "region", "country"),
        "primary_fields": ("name", "vessel_name", "vessel_ssvid", "vessel_id"),
        "label_fields": ("vessel_name", "name", "id"),
        "summary_fields": ("flag", "type", "region", "country"),
        "type_fields": ("type",),
        "id_fields": ("id", "vessel_ssvid", "vessel_id"),
        "time_fields": ("end", "start", "timestamp"),
    },
    "news": {
        "fields": ("title", "summary", "description", "source"),
        "primary_fields": ("title",),
        "label_fields": ("title",),
        "summary_fields": ("summary", "description", "source"),
        "type_fields": ("source",),
        "id_fields": ("link", "url"),
        "time_fields": ("published", "pub_date", "timestamp"),
    },
    "gdelt": {
        "fields": ("title", "name", "sourceurl", "actor1name", "actor2name"),
        "primary_fields": ("title", "name"),
        "label_fields": ("title", "name"),
        "summary_fields": ("actor1name", "actor2name"),
        "type_fields": ("eventcode", "eventrootcode"),
        "id_fields": ("sourceurl",),
        "time_fields": ("sqldate", "date"),
    },
    "crowdthreat": {
        "fields": ("title", "summary", "description", "category", "city", "state", "region"),
        "primary_fields": ("title", "category", "city", "state"),
        "label_fields": ("title",),
        "summary_fields": ("summary", "description", "category", "city", "state"),
        "type_fields": ("category",),
        "id_fields": ("id", "link", "url"),
        "time_fields": ("date", "timestamp", "created_at", "updated_at"),
    },
    "frontlines": {
        "fields": ("title", "name", "description", "category", "source"),
        "primary_fields": ("title", "name"),
        "label_fields": ("title", "name"),
        "summary_fields": ("description", "category", "source"),
        "type_fields": ("category",),
        "id_fields": ("id", "sourceurl", "url"),
        "time_fields": ("date", "timestamp", "updated_at"),
    },
    "liveuamap": {
        "fields": ("title", "description", "place", "category", "source"),
        "primary_fields": ("title", "place"),
        "label_fields": ("title", "place"),
        "summary_fields": ("description", "category", "source"),
        "type_fields": ("category",),
        "id_fields": ("id", "url", "link"),
        "time_fields": ("time", "date", "timestamp"),
    },
    "uap_sightings": {
        "fields": ("city", "state", "country", "shape", "shape_raw", "summary", "duration"),
        "primary_fields": ("city", "state", "shape", "shape_raw"),
        "label_fields": ("city", "state", "shape_raw"),
        "summary_fields": ("summary", "duration", "country"),
        "type_fields": ("shape", "shape_raw"),
        "id_fields": ("id",),
        "time_fields": ("date_time", "posted"),
    },
    "wastewater": {
        "fields": ("name", "site_name", "city", "state", "pathogen", "status", "signal", "county"),
        "primary_fields": ("name", "site_name", "city", "state", "pathogen"),
        "label_fields": ("name", "site_name"),
        "summary_fields": ("city", "state", "pathogen", "status", "signal"),
        "type_fields": ("pathogen", "status"),
        "id_fields": ("id",),
        "time_fields": ("updated_at", "timestamp", "date"),
    },
    "prediction_markets": {
        "fields": ("title", "question", "category", "status", "source"),
        "primary_fields": ("title", "question"),
        "label_fields": ("title", "question"),
        "summary_fields": ("category", "status", "source"),
        "type_fields": ("category", "status"),
        "id_fields": ("id", "slug"),
        "time_fields": ("end_date", "updated_at", "timestamp"),
    },
    "earthquakes": {
        "fields": ("place", "title", "id", "mag"),
        "primary_fields": ("place", "title"),
        "label_fields": ("place", "title"),
        "summary_fields": ("mag",),
        "type_fields": ("mag",),
        "id_fields": ("id",),
        "time_fields": ("time", "timestamp", "updated"),
    },
    "weather_alerts": {
        "fields": ("event", "headline", "area", "severity", "sender"),
        "primary_fields": ("event", "headline", "area"),
        "label_fields": ("headline", "event", "area"),
        "summary_fields": ("area", "severity", "sender"),
        "type_fields": ("event", "severity"),
        "id_fields": ("id",),
        "time_fields": ("sent", "effective", "onset", "timestamp"),
    },
    "internet_outages": {
        "fields": ("name", "region", "country", "provider", "status"),
        "primary_fields": ("name", "region", "country"),
        "label_fields": ("name", "region"),
        "summary_fields": ("country", "provider", "status"),
        "type_fields": ("status",),
        "id_fields": ("id",),
        "time_fields": ("updated_at", "timestamp", "date"),
    },
    "datacenters": {
        "fields": ("name", "company", "city", "state", "country"),
        "primary_fields": ("name", "company", "city", "state"),
        "label_fields": ("name", "company"),
        "summary_fields": ("city", "state", "country"),
        "type_fields": ("company",),
        "id_fields": ("id",),
        "time_fields": ("updated_at", "timestamp"),
    },
    "military_bases": {
        "fields": ("name", "branch", "country", "state", "city"),
        "primary_fields": ("name", "branch", "city", "state"),
        "label_fields": ("name",),
        "summary_fields": ("branch", "city", "state", "country"),
        "type_fields": ("branch",),
        "id_fields": ("id",),
        "time_fields": ("updated_at", "timestamp"),
    },
    "power_plants": {
        "fields": ("name", "owner", "fuel", "city", "state", "country"),
        "primary_fields": ("name", "owner", "fuel"),
        "label_fields": ("name",),
        "summary_fields": ("owner", "fuel", "city", "state", "country"),
        "type_fields": ("fuel",),
        "id_fields": ("id",),
        "time_fields": ("updated_at", "timestamp"),
    },
    "scanners": {
        "fields": ("name", "county", "state", "city", "agency"),
        "primary_fields": ("name", "county", "state", "city"),
        "label_fields": ("name",),
        "summary_fields": ("agency", "city", "state", "county"),
        "type_fields": ("agency",),
        "id_fields": ("id",),
        "time_fields": ("updated_at", "timestamp"),
    },
    "air_quality": {
        "fields": ("name", "city", "state", "country", "category"),
        "primary_fields": ("name", "city", "state"),
        "label_fields": ("name", "city"),
        "summary_fields": ("category", "state", "country"),
        "type_fields": ("category",),
        "id_fields": ("id",),
        "time_fields": ("updated_at", "timestamp"),
    },
    "volcanoes": {
        "fields": ("name", "country", "region", "status"),
        "primary_fields": ("name", "country", "region"),
        "label_fields": ("name",),
        "summary_fields": ("country", "region", "status"),
        "type_fields": ("status",),
        "id_fields": ("id",),
        "time_fields": ("updated_at", "timestamp"),
    },
    "sigint": {
        "fields": ("call", "callsign", "name", "msg", "message", "symbol_name", "type"),
        "primary_fields": ("call", "callsign", "name"),
        "label_fields": ("call", "callsign", "name"),
        "summary_fields": ("msg", "message", "symbol_name", "type"),
        "type_fields": ("type", "symbol_name"),
        "id_fields": ("id",),
        "time_fields": ("timestamp", "heard_at", "last_seen"),
    },
    "cctv": {
        "fields": ("id", "source_agency", "direction_facing", "location", "name"),
        "primary_fields": ("direction_facing", "location", "source_agency", "name"),
        "label_fields": ("name", "direction_facing", "id"),
        "summary_fields": ("source_agency", "location"),
        "type_fields": ("source_agency",),
        "id_fields": ("id",),
        "time_fields": ("updated_at", "timestamp"),
    },
    "satellites": {
        "fields": ("name", "id", "norad_id", "country", "type"),
        "primary_fields": ("name", "id", "norad_id"),
        "label_fields": ("name", "norad_id", "id"),
        "summary_fields": ("country", "type"),
        "type_fields": ("type",),
        "id_fields": ("norad_id", "id"),
        "time_fields": ("epoch", "updated_at", "timestamp"),
    },
    "trains": {
        "fields": ("name", "train_no", "route", "operator", "status"),
        "primary_fields": ("name", "train_no", "route"),
        "label_fields": ("name", "train_no", "route"),
        "summary_fields": ("operator", "status"),
        "type_fields": ("operator", "status"),
        "id_fields": ("id", "train_no"),
        "time_fields": ("updated_at", "timestamp"),
    },
    "kiwisdr": {
        "fields": ("name", "city", "state", "country", "owner"),
        "primary_fields": ("name", "city", "state", "country"),
        "label_fields": ("name",),
        "summary_fields": ("city", "state", "country", "owner"),
        "type_fields": ("country",),
        "id_fields": ("id", "url"),
        "time_fields": ("updated_at", "timestamp"),
    },
    "satnogs_stations": {
        "fields": ("name", "location", "city", "country", "status"),
        "primary_fields": ("name", "location", "city", "country"),
        "label_fields": ("name",),
        "summary_fields": ("location", "city", "country", "status"),
        "type_fields": ("status",),
        "id_fields": ("id",),
        "time_fields": ("updated_at", "timestamp"),
    },
    "satnogs_observations": {
        "fields": ("satellite", "ground_station", "name", "status"),
        "primary_fields": ("satellite", "ground_station", "name"),
        "label_fields": ("satellite", "name"),
        "summary_fields": ("ground_station", "status"),
        "type_fields": ("status",),
        "id_fields": ("id",),
        "time_fields": ("timestamp", "start", "end"),
    },
    "tinygs_satellites": {
        "fields": ("name", "norad_id", "status", "country"),
        "primary_fields": ("name", "norad_id"),
        "label_fields": ("name", "norad_id"),
        "summary_fields": ("status", "country"),
        "type_fields": ("status",),
        "id_fields": ("norad_id", "id"),
        "time_fields": ("updated_at", "timestamp"),
    },
    "psk_reporter": {
        "fields": ("sender", "receiver", "mode", "band", "country"),
        "primary_fields": ("sender", "receiver"),
        "label_fields": ("sender", "receiver"),
        "summary_fields": ("mode", "band", "country"),
        "type_fields": ("mode", "band"),
        "id_fields": ("id",),
        "time_fields": ("timestamp", "updated_at"),
    },
    "ukraine_alerts": {
        "fields": ("name", "region", "status", "description"),
        "primary_fields": ("name", "region"),
        "label_fields": ("name", "region"),
        "summary_fields": ("status", "description"),
        "type_fields": ("status",),
        "id_fields": ("id",),
        "time_fields": ("updated_at", "timestamp"),
    },
}


def _norm_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _norm_key(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _query_tokens(value: Any) -> list[str]:
    return re.findall(r"[a-z0-9]+", _norm_text(value))


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_limit(value: Any, default: int = 25, maximum: int = 100) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(maximum, parsed))


def _coerce_optional_limit(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return parsed


def _matches_query(candidate: dict[str, Any], query: str, fields: tuple[str, ...]) -> bool:
    normalized = _norm_text(query)
    if not normalized:
        return True
    haystack = " ".join(_norm_text(candidate.get(field)) for field in fields)
    if normalized in haystack:
        return True
    tokens = _query_tokens(normalized)
    return bool(tokens) and all(token in haystack for token in tokens)


def _first_present(candidate: dict[str, Any], fields: tuple[str, ...]) -> Any:
    for field in fields:
        value = candidate.get(field)
        if value not in (None, ""):
            return value
    return None


def _extract_coords(candidate: dict[str, Any]) -> tuple[float | None, float | None]:
    lat = _coerce_float(
        candidate.get("lat")
        or candidate.get("latitude")
        or candidate.get("y")
    )
    lng = _coerce_float(
        candidate.get("lng")
        or candidate.get("lon")
        or candidate.get("longitude")
        or candidate.get("x")
    )
    geometry = candidate.get("geometry")
    if (lat is None or lng is None) and isinstance(geometry, dict):
        coords = geometry.get("coordinates") or []
        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
            lng = lng if lng is not None else _coerce_float(coords[0])
            lat = lat if lat is not None else _coerce_float(coords[1])
    return lat, lng


def _score_text_match(query: str, value: Any, *, exact_weight: int, prefix_weight: int, contains_weight: int) -> int:
    normalized = _norm_text(value)
    if not normalized or not query:
        return 0
    if normalized == query:
        return exact_weight
    if normalized.startswith(query):
        return prefix_weight
    if query in normalized:
        return contains_weight
    tokens = _query_tokens(query)
    if tokens and all(token in normalized for token in tokens):
        return contains_weight
    return 0


def _text_matches_query(query: str, text: Any) -> bool:
    normalized_query = _norm_text(query)
    normalized_text = _norm_text(text)
    if not normalized_query:
        return True
    if normalized_query in normalized_text:
        return True
    tokens = _query_tokens(normalized_query)
    return bool(tokens) and all(token in normalized_text for token in tokens)


def _dedupe_tokens(tokens: list[str]) -> list[str]:
    return list(dict.fromkeys(token for token in tokens if token))


def _iter_searchable_scalars(value: Any, *, depth: int = 0) -> list[str]:
    if depth > 3:
        return []
    if value in (None, "", False):
        return []
    if isinstance(value, dict):
        out: list[str] = []
        for nested in value.values():
            out.extend(_iter_searchable_scalars(nested, depth=depth + 1))
        return out
    if isinstance(value, (list, tuple, set)):
        out: list[str] = []
        for nested in value:
            out.extend(_iter_searchable_scalars(nested, depth=depth + 1))
        return out
    if isinstance(value, (str, int, float)):
        normalized = _norm_text(value)
        return [normalized] if normalized else []
    return []


def _document_text(candidate: dict[str, Any], fields: tuple[str, ...]) -> str:
    parts: list[str] = []
    for value in _iter_searchable_scalars(candidate):
        if value and value not in parts:
            parts.append(value)
    for field in fields:
        value = _norm_text(candidate.get(field))
        if value and value not in parts:
            parts.insert(0, value)
    return " ".join(parts)


def _normalize_search_token(token: str) -> list[str]:
    normalized = _norm_text(token)
    variants = [normalized] if normalized else []
    if normalized.endswith("ies") and len(normalized) > 4:
        variants.append(f"{normalized[:-3]}y")
    elif normalized.endswith("es") and len(normalized) > 4:
        variants.append(normalized[:-2])
    elif normalized.endswith("s") and len(normalized) > 3:
        variants.append(normalized[:-1])
    return _dedupe_tokens(variants)


def _expand_query_terms(tokens: list[str], vocabulary: set[str]) -> list[str]:
    expanded: list[str] = []
    for token in tokens:
        variants = _normalize_search_token(token)
        variants.extend(_SEARCH_QUERY_SYNONYMS.get(token, ()))
        for variant in list(variants):
            if variant in vocabulary:
                expanded.append(variant)
            elif len(variant) >= 4 and vocabulary:
                expanded.extend(get_close_matches(variant, sorted(vocabulary), n=2, cutoff=0.84))
            else:
                expanded.append(variant)
    return _dedupe_tokens(expanded)


def _layer_group(layer: str) -> str:
    return _SEARCH_GROUP_BY_LAYER.get(layer, "other")


def _build_search_document(doc_id: int, layer: str, candidate: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    fields = tuple(spec.get("fields", ()))
    text = _document_text(candidate, fields)
    tokens = _dedupe_tokens(_query_tokens(text))
    return {
        "id": doc_id,
        "layer": layer,
        "group": _layer_group(layer),
        "candidate": candidate,
        "spec": spec,
        "text": text,
        "tokens": tokens,
    }


def _get_search_index() -> dict[str, Any]:
    global _SEARCH_INDEX_REF
    import time as _time

    version = get_data_version()
    # Grab ref once — readers use this snapshot, no lock needed.
    current = _SEARCH_INDEX_REF
    now = _time.monotonic()

    # Fast path: version unchanged OR index is fresh enough (within TTL).
    # ADS-B/AIS bump the version every few seconds, but we don't need to
    # rebuild a 50K-doc inverted index on every tick.
    if current["version"] == version:
        return current
    if current["version"] is not None and (now - current["built_at"]) < _SEARCH_INDEX_MIN_AGE:
        return current

    with _SEARCH_INDEX_LOCK:
        # Double-check under lock (another thread may have rebuilt)
        current = _SEARCH_INDEX_REF
        if current["version"] == version:
            return current
        if current["version"] is not None and (_time.monotonic() - current["built_at"]) < _SEARCH_INDEX_MIN_AGE:
            return current

        layers = [layer for layer in _UNIVERSAL_SEARCH_DEFAULT_LAYERS if layer in _UNIVERSAL_SEARCH_SPECS]
        snap = get_latest_data_subset_refs(*layers)
        docs: list[dict[str, Any]] = []
        postings: dict[str, set[int]] = {}
        vocabulary: set[str] = set()

        for layer in layers:
            spec = _UNIVERSAL_SEARCH_SPECS[layer]
            items = snap.get(layer) or []
            if isinstance(items, dict):
                items = items.get("items", []) or items.get("results", []) or items.get("vessels", [])
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                doc = _build_search_document(len(docs), layer, item, spec)
                if not doc["tokens"]:
                    continue
                docs.append(doc)
                for token in doc["tokens"]:
                    vocabulary.add(token)
                    postings.setdefault(token, set()).add(doc["id"])

        # Atomic swap — readers grabbing _SEARCH_INDEX_REF after this line
        # see the new index; readers who grabbed it before still see the old
        # one (safe, just stale).  No reader ever sees partial state.
        _SEARCH_INDEX_REF = {
            "version": version,
            "docs": docs,
            "vocabulary": vocabulary,
            "postings": postings,
            "built_at": _time.monotonic(),
        }
        return _SEARCH_INDEX_REF


def _parse_search_query(query: str, searchable_layers: list[str]) -> dict[str, Any]:
    normalized = _norm_text(query)
    raw_tokens = _query_tokens(normalized)
    entity_tokens: list[str] = []
    hint_tokens: list[str] = []
    preferred_layers: list[str] = []

    for token in raw_tokens:
        if token in _GENERIC_QUERY_STOPWORDS:
            continue
        hinted_layers = _GENERIC_LAYER_HINTS.get(token)
        if hinted_layers:
            hint_tokens.append(token)
            for layer in hinted_layers:
                if layer in searchable_layers and layer not in preferred_layers:
                    preferred_layers.append(layer)
            continue
        entity_tokens.append(token)

    fallback_tokens = [token for token in raw_tokens if token not in _GENERIC_QUERY_STOPWORDS]
    entity_tokens = _dedupe_tokens(entity_tokens or fallback_tokens or raw_tokens)
    hint_tokens = _dedupe_tokens(hint_tokens)
    anchor_tokens = sorted(
        [token for token in entity_tokens if len(token) >= 3],
        key=lambda token: (-len(token), token),
    )[:3]
    anchor_tokens = _dedupe_tokens(anchor_tokens or entity_tokens[:2] or entity_tokens)

    return {
        "normalized": normalized,
        "raw_tokens": raw_tokens,
        "entity_tokens": entity_tokens,
        "hint_tokens": hint_tokens,
        "anchor_tokens": anchor_tokens,
        "entity_phrase": " ".join(entity_tokens).strip(),
        "preferred_layers": preferred_layers,
    }


def _field_texts(candidate: dict[str, Any], fields: tuple[str, ...]) -> dict[str, str]:
    texts: dict[str, str] = {}
    for field in fields:
        normalized = _norm_text(candidate.get(field))
        if normalized:
            texts[field] = normalized
    return texts


def _match_tokens(tokens: list[str], texts: dict[str, str], *, preferred_fields: tuple[str, ...]) -> tuple[list[str], int]:
    matched: list[str] = []
    score = 0
    for token in tokens:
        token_score = 0
        for field in preferred_fields:
            value = texts.get(field, "")
            if not value:
                continue
            if value == token:
                token_score = max(token_score, 120)
            elif value.startswith(token):
                token_score = max(token_score, 90)
            elif token in value:
                token_score = max(token_score, 70)
        if token_score <= 0:
            for value in texts.values():
                if value == token:
                    token_score = max(token_score, 70)
                elif value.startswith(token):
                    token_score = max(token_score, 50)
                elif token in value:
                    token_score = max(token_score, 35)
        if token_score > 0:
            matched.append(token)
            score += token_score
    return matched, score


def _score_candidate(candidate: dict[str, Any], query_info: dict[str, Any], spec: dict[str, Any], layer: str) -> dict[str, Any] | None:
    fields = tuple(spec.get("fields", ()))
    primary_fields = tuple(spec.get("primary_fields", ()))
    texts = _field_texts(candidate, fields)
    document_text = _document_text(candidate, fields)
    if not texts and not document_text:
        return None

    combined = " ".join([*texts.values(), document_text]).strip()
    entity_tokens = list(query_info.get("entity_tokens") or [])
    hint_tokens = list(query_info.get("hint_tokens") or [])
    anchor_tokens = list(query_info.get("anchor_tokens") or [])
    entity_phrase = str(query_info.get("entity_phrase") or "")
    normalized_query = str(query_info.get("normalized") or "")

    matched_entity_tokens, score = _match_tokens(entity_tokens, texts, preferred_fields=primary_fields)
    document_hits = [token for token in entity_tokens if token in document_text and token not in matched_entity_tokens]
    matched_entity_tokens.extend(document_hits)
    score += 20 * len(document_hits)
    entity_match_count = len(matched_entity_tokens)
    entity_token_count = len(entity_tokens)
    anchor_match_count = sum(1 for token in anchor_tokens if token in document_text)

    if entity_phrase:
        for field in primary_fields:
            value = texts.get(field, "")
            if entity_phrase and entity_phrase in value:
                score += 140
                break
        else:
            if entity_phrase in combined:
                score += 80
    elif normalized_query and normalized_query in combined:
        score += 60

    if entity_token_count:
        if entity_match_count == 0 or (anchor_tokens and anchor_match_count == 0):
            return None
        score += 20 * entity_match_count
        if entity_match_count == entity_token_count:
            score += 40
        else:
            score += 10 * anchor_match_count
    elif normalized_query and normalized_query not in combined and not matched_entity_tokens:
        return None

    matched_hint_tokens: list[str] = []
    if hint_tokens:
        if layer in query_info.get("preferred_layers", []):
            score += 25 + (5 * len(hint_tokens))
            matched_hint_tokens.extend(hint_tokens)
        type_text = " ".join(
            _norm_text(candidate.get(field))
            for field in tuple(spec.get("type_fields", ())) + tuple(spec.get("summary_fields", ()))
        )
        for token in hint_tokens:
            if token in type_text and token not in matched_hint_tokens:
                matched_hint_tokens.append(token)
                score += 15

    matched_tokens = _dedupe_tokens(matched_entity_tokens + matched_hint_tokens)
    confidence = min(0.99, max(0.1, score / 220.0))

    return {
        "score": score,
        "matched_tokens": matched_tokens,
        "confidence": round(confidence, 2),
    }


def _compact_search_result(
    layer: str,
    candidate: dict[str, Any],
    spec: dict[str, Any],
    score: int,
    *,
    matched_tokens: list[str] | None = None,
    confidence: float | None = None,
) -> dict[str, Any]:
    label = _first_present(candidate, tuple(spec.get("label_fields", ()))) or ""
    summary_parts = []
    for field in tuple(spec.get("summary_fields", ())):
        value = candidate.get(field)
        if value in (None, ""):
            continue
        rendered = str(value).strip()
        if rendered and rendered not in summary_parts:
            summary_parts.append(rendered)
        if len(summary_parts) >= 3:
            break
    lat, lng = _extract_coords(candidate)
    time_value = _first_present(candidate, tuple(spec.get("time_fields", ())))
    result = {
        "source_layer": layer,
        "group": _layer_group(layer),
        "label": str(label),
        "summary": " | ".join(summary_parts),
        "type": str(_first_present(candidate, tuple(spec.get("type_fields", ()))) or ""),
        "id": str(_first_present(candidate, tuple(spec.get("id_fields", ()))) or ""),
        "score": score,
    }
    if matched_tokens:
        result["matched_tokens"] = matched_tokens
    if confidence is not None:
        result["confidence"] = confidence
    if lat is not None:
        result["lat"] = lat
    if lng is not None:
        result["lng"] = lng
    if time_value not in (None, ""):
        result["time"] = str(time_value)
    return result


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlng / 2) ** 2
    )
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _resolve_layers(
    requested: list[str] | tuple[str, ...] | None,
    alias_map: dict[str, str],
    defaults: tuple[str, ...],
) -> list[str]:
    if not requested:
        return list(defaults)
    resolved: list[str] = []
    seen: set[str] = set()
    for layer in requested:
        canonical = alias_map.get(_norm_key(layer))
        if canonical and canonical not in seen:
            seen.add(canonical)
            resolved.append(canonical)
    return resolved or list(defaults)


def _available_layer_names() -> list[str]:
    return [key for key in latest_data.keys() if key != "last_updated"]


def get_telemetry_summary() -> dict[str, Any]:
    """Return lightweight counts and discovery metadata for all telemetry layers."""
    version = get_data_version()
    layer_names = _available_layer_names()
    snap = get_latest_data_subset_refs("last_updated", *layer_names)
    counts: dict[str, Any] = {}
    non_empty_layers: list[str] = []

    for layer in layer_names:
        value = snap.get(layer)
        if isinstance(value, list):
            counts[layer] = len(value)
            if value:
                non_empty_layers.append(layer)
        elif isinstance(value, dict):
            counts[layer] = len(value)
            if value:
                non_empty_layers.append(layer)
        elif value is None:
            counts[layer] = 0
        else:
            counts[layer] = 1
            non_empty_layers.append(layer)

    alias_examples = {
        "gfw": "fishing_activity",
        "global_fishing_watch": "fishing_activity",
        "fishing": "fishing_activity",
        "uap": "uap_sightings",
        "ufo": "uap_sightings",
        "tracked": "tracked_flights",
        "military": "military_flights",
        "jets": "private_jets",
    }

    return {
        "counts": counts,
        "available_layers": layer_names,
        "non_empty_layers": non_empty_layers,
        "layer_aliases": alias_examples,
        "last_updated": snap.get("last_updated"),
        "version": version,
    }


def find_flights(
    *,
    query: str = "",
    callsign: str = "",
    registration: str = "",
    icao24: str = "",
    owner: str = "",
    categories: list[str] | tuple[str, ...] | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    """Search flight layers without returning the full telemetry snapshot."""
    layers = _resolve_layers(
        categories,
        _FLIGHT_LAYER_ALIASES,
        ("tracked_flights", "military_flights", "private_jets", "private_flights", "commercial_flights"),
    )
    snap = get_latest_data_subset_refs(*layers)
    out: list[dict[str, Any]] = []
    limit = _coerce_limit(limit)
    query_norm = _norm_text(query)
    callsign_norm = _norm_text(callsign)
    registration_norm = _norm_text(registration)
    icao24_norm = _norm_text(icao24)
    owner_norm = _norm_text(owner)

    for layer in layers:
        items = snap.get(layer) or []
        if not isinstance(items, list):
            continue
        for flight in items:
            if not isinstance(flight, dict):
                continue
            flight_callsign = _norm_text(
                flight.get("callsign") or flight.get("flight") or flight.get("call")
            )
            flight_registration = _norm_text(
                flight.get("registration") or flight.get("r")
            )
            flight_icao24 = _norm_text(flight.get("icao24"))
            flight_owner = _norm_text(
                flight.get("owner")
                or flight.get("operator")
                or flight.get("alert_operator")
            )
            if callsign_norm and callsign_norm not in flight_callsign:
                continue
            if registration_norm and registration_norm not in flight_registration:
                continue
            if icao24_norm and icao24_norm != flight_icao24:
                continue
            if owner_norm and owner_norm not in flight_owner:
                continue
            if query_norm and not _matches_query(
                flight,
                query_norm,
                (
                    "callsign",
                    "flight",
                    "call",
                    "registration",
                    "r",
                    "icao24",
                    "owner",
                    "operator",
                    "alert_operator",
                    "type",
                    "t",
                    "aircraft_type",
                ),
            ):
                continue
            out.append(
                {
                    "source_layer": layer,
                    "callsign": flight.get("callsign") or flight.get("flight") or flight.get("call") or "",
                    "registration": flight.get("registration") or flight.get("r") or "",
                    "icao24": flight.get("icao24") or "",
                    "owner": flight.get("owner") or flight.get("operator") or flight.get("alert_operator") or "",
                    "type": flight.get("type") or flight.get("t") or flight.get("aircraft_type") or "",
                    "lat": flight.get("lat") or flight.get("latitude"),
                    "lng": flight.get("lng") or flight.get("lon") or flight.get("longitude"),
                    "altitude": flight.get("altitude") or flight.get("alt_baro") or flight.get("alt"),
                    "speed": flight.get("speed") or flight.get("gs"),
                    "heading": flight.get("heading") or flight.get("track"),
                    "alert_category": flight.get("alert_category") or "",
                    "alert_operator": flight.get("alert_operator") or "",
                }
            )
            if len(out) >= limit:
                return {"results": out, "version": get_data_version(), "truncated": True}

    return {"results": out, "version": get_data_version(), "truncated": False}


def find_ships(
    *,
    query: str = "",
    mmsi: str = "",
    imo: str = "",
    name: str = "",
    limit: int = 25,
) -> dict[str, Any]:
    """Search ships without returning the entire ship layer."""
    snap = get_latest_data_subset_refs("ships")
    items = snap.get("ships") or []
    out: list[dict[str, Any]] = []
    limit = _coerce_limit(limit)
    query_norm = _norm_text(query)
    mmsi_norm = _norm_text(mmsi)
    imo_norm = _norm_text(imo)
    name_norm = _norm_text(name)
    if isinstance(items, dict):
        items = items.get("vessels", []) or items.get("items", [])

    for ship in items if isinstance(items, list) else []:
        if not isinstance(ship, dict):
            continue
        ship_mmsi = _norm_text(ship.get("mmsi"))
        ship_imo = _norm_text(ship.get("imo"))
        ship_name = _norm_text(ship.get("name") or ship.get("shipName"))
        if mmsi_norm and mmsi_norm != ship_mmsi:
            continue
        if imo_norm and imo_norm != ship_imo:
            continue
        if name_norm and name_norm not in ship_name:
            continue
        if query_norm and not _matches_query(
            ship,
            query_norm,
            (
                "name",
                "shipName",
                "mmsi",
                "imo",
                "callsign",
                "shipType",
                "type",
                "yacht_owner",
                "yacht_name",
                "yacht_category",
                "owner",
            ),
        ):
            continue
        out.append(
            {
                "mmsi": ship.get("mmsi") or "",
                "imo": ship.get("imo") or "",
                "name": ship.get("name") or ship.get("shipName") or "",
                "owner": ship.get("yacht_owner") or ship.get("owner") or "",
                "tracked_name": ship.get("yacht_name") or "",
                "tracked_category": ship.get("yacht_category") or "",
                "callsign": ship.get("callsign") or "",
                "type": ship.get("shipType") or ship.get("type") or "",
                "lat": ship.get("lat") or ship.get("latitude"),
                "lng": ship.get("lng") or ship.get("lon") or ship.get("longitude"),
                "speed": ship.get("speed") or ship.get("sog"),
                "heading": ship.get("heading") or ship.get("course"),
            }
        )
        if len(out) >= limit:
            return {"results": out, "version": get_data_version(), "truncated": True}

    return {"results": out, "version": get_data_version(), "truncated": False}


def _entity_layers_for_type(entity_type: str) -> list[str] | None:
    kind = _norm_key(entity_type)
    if not kind:
        return None
    if kind in {"aircraft", "plane", "flight", "jet", "helicopter"}:
        return ["tracked_flights", "military_flights", "private_jets", "private_flights", "commercial_flights"]
    if kind in {"ship", "ships", "vessel", "boat", "yacht", "maritime"}:
        return ["ships", "fishing_activity"]
    if kind in {"event", "incident", "news", "protest"}:
        return ["news", "gdelt", "crowdthreat", "frontlines", "liveuamap"]
    if kind in {"satellite", "space"}:
        return ["satellites", "tinygs_satellites", "satnogs_observations", "satnogs_stations"]
    if kind in {"signal", "sigint", "radio"}:
        return ["sigint", "kiwisdr", "psk_reporter"]
    canonical = _LAYER_ALIASES.get(kind)
    return [canonical] if canonical else None


def _entity_key(item: dict[str, Any]) -> str:
    layer = str(item.get("source_layer") or item.get("layer") or "")
    ident = str(item.get("id") or item.get("icao24") or item.get("registration") or item.get("mmsi") or item.get("imo") or "")
    label = str(item.get("label") or item.get("callsign") or item.get("name") or "")
    return f"{layer}:{ident or label}".lower()


def _normalize_entity_result(item: dict[str, Any], *, group: str = "") -> dict[str, Any]:
    out = dict(item)
    layer = str(out.get("source_layer") or out.get("layer") or "")
    if layer and "source_layer" not in out:
        out["source_layer"] = layer
    if not group:
        group = str(out.get("group") or _layer_group(layer))
    out["group"] = group or "other"
    if "label" not in out:
        out["label"] = (
            out.get("callsign")
            or out.get("name")
            or out.get("tracked_name")
            or out.get("registration")
            or out.get("mmsi")
            or out.get("id")
            or ""
        )
    if "id" not in out:
        out["id"] = out.get("icao24") or out.get("registration") or out.get("mmsi") or out.get("imo") or ""
    return out


def find_entity(
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
    layers: list[str] | tuple[str, ...] | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Find a named entity across aircraft, maritime, and general telemetry.

    This is an intent-level lookup for agents. It tries high-precision
    aircraft/ship fields first, then falls back to the universal search index.
    """
    effective_query = str(query or name or owner or callsign or registration or icao24 or mmsi or imo or "").strip()
    if not effective_query:
        return {
            "results": [],
            "best_match": None,
            "version": get_data_version(),
            "truncated": False,
            "searched_layers": [],
            "strategy": "empty_query",
        }

    limit = _coerce_limit(limit, default=10, maximum=50)
    requested_layers = list(layers or _entity_layers_for_type(entity_type) or [])
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    strategies: list[str] = []

    aircraft_hint = bool(callsign or registration or icao24) or _norm_key(entity_type) in {
        "aircraft",
        "plane",
        "flight",
        "jet",
        "helicopter",
    }
    maritime_hint = bool(mmsi or imo) or _norm_key(entity_type) in {
        "ship",
        "ships",
        "vessel",
        "boat",
        "yacht",
        "maritime",
    }

    if aircraft_hint or not maritime_hint:
        flight_result = find_flights(
            query=effective_query if not (callsign or registration or icao24 or owner) else "",
            callsign=callsign,
            registration=registration,
            icao24=icao24,
            owner=owner,
            categories=requested_layers or None,
            limit=limit,
        )
        if flight_result.get("results"):
            strategies.append("aircraft_exact_fields")
        for item in flight_result.get("results") or []:
            normalized = _normalize_entity_result(item, group="aircraft")
            normalized.setdefault("score", 1000)
            normalized.setdefault("confidence", 0.99)
            key = _entity_key(normalized)
            if key not in seen:
                seen.add(key)
                results.append(normalized)

    if maritime_hint or not aircraft_hint:
        ship_result = find_ships(
            query=effective_query if not (mmsi or imo or name) else "",
            mmsi=mmsi,
            imo=imo,
            name=name,
            limit=limit,
        )
        if ship_result.get("results"):
            strategies.append("maritime_exact_fields")
        for item in ship_result.get("results") or []:
            normalized = _normalize_entity_result(item, group="maritime")
            normalized.setdefault("score", 1000)
            normalized.setdefault("confidence", 0.99)
            key = _entity_key(normalized)
            if key not in seen:
                seen.add(key)
                results.append(normalized)

    search_layers = requested_layers or _entity_layers_for_type(entity_type)
    search_result = search_telemetry(query=effective_query, layers=search_layers, limit=limit)
    if search_result.get("results"):
        strategies.append("universal_index")
    for item in search_result.get("results") or []:
        normalized = _normalize_entity_result(item)
        key = _entity_key(normalized)
        if key not in seen:
            seen.add(key)
            results.append(normalized)

    results.sort(
        key=lambda item: (
            int(item.get("score", 0) or 0),
            float(item.get("confidence", 0.0) or 0.0),
            bool(item.get("lat") is not None and item.get("lng") is not None),
        ),
        reverse=True,
    )
    truncated = len(results) > limit
    limited = results[:limit]
    return {
        "query": effective_query,
        "entity_type": entity_type or "",
        "best_match": limited[0] if limited else None,
        "results": limited,
        "version": get_data_version(),
        "truncated": truncated,
        "searched_layers": search_result.get("searched_layers", search_layers or []),
        "strategy": "+".join(strategies) if strategies else "no_match",
    }


def _project_context_item(layer: str, item: dict[str, Any], distance_km: float) -> dict[str, Any]:
    label = (
        item.get("label")
        or item.get("callsign")
        or item.get("flight")
        or item.get("name")
        or item.get("shipName")
        or item.get("title")
        or item.get("headline")
        or item.get("event")
        or item.get("place")
        or item.get("id")
        or item.get("anomaly_id")
        or ""
    )
    summary = (
        item.get("summary")
        or item.get("description")
        or item.get("drivers")
        or item.get("area")
        or item.get("source")
        or ""
    )
    if isinstance(summary, list):
        summary = "; ".join(str(part) for part in summary[:4])
    lat, lng = _extract_coords(item)
    return {
        "source_layer": layer,
        "label": label,
        "summary": str(summary or "")[:500],
        "lat": lat,
        "lng": lng,
        "distance_km": round(distance_km, 2),
        "type": item.get("type") or item.get("kind") or item.get("category") or item.get("event") or "",
        "severity": item.get("severity") or item.get("level") or item.get("score") or item.get("risk_score"),
        "id": (
            item.get("id")
            or item.get("anomaly_id")
            or item.get("mmsi")
            or item.get("icao24")
            or item.get("sourceurl")
            or item.get("link")
            or ""
        ),
        "time": item.get("timestamp") or item.get("updated") or item.get("time") or item.get("date") or item.get("published") or "",
    }


def _nearby_items_from_layers(
    *,
    lat: float,
    lng: float,
    radius_km: float,
    layers: tuple[str, ...],
    limit_per_layer: int,
) -> dict[str, list[dict[str, Any]]]:
    snap = get_latest_data_subset_refs(*layers)
    out: dict[str, list[dict[str, Any]]] = {}
    for layer in layers:
        value = snap.get(layer) or []
        if isinstance(value, dict):
            if layer == "gdelt" and isinstance(value.get("features"), list):
                items = value.get("features") or []
            else:
                items = value.get("items") or value.get("features") or value.get("vessels") or []
        else:
            items = value
        if not isinstance(items, list):
            continue
        matches: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            item_lat, item_lng = _extract_coords(item)
            if item_lat is None or item_lng is None:
                continue
            distance = _haversine_km(lat, lng, item_lat, item_lng)
            if distance > radius_km:
                continue
            matches.append(_project_context_item(layer, item, distance))
        matches.sort(key=lambda entry: entry.get("distance_km", 0))
        if matches:
            out[layer] = matches[:limit_per_layer]
    return out


def _entity_same_as_context(entity: dict[str, Any], context: dict[str, Any]) -> bool:
    entity_ids = {
        _norm_key(entity.get("id")),
        _norm_key(entity.get("icao24")),
        _norm_key(entity.get("registration")),
        _norm_key(entity.get("mmsi")),
        _norm_key(entity.get("imo")),
        _norm_key(entity.get("callsign")),
        _norm_key(entity.get("label")),
        _norm_key(entity.get("name")),
    }
    context_ids = {
        _norm_key(context.get("id")),
        _norm_key(context.get("label")),
    }
    entity_ids.discard("")
    context_ids.discard("")
    return bool(entity_ids & context_ids)


def correlate_entity(
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
    radius_km: float = 100,
    limit: int = 10,
) -> dict[str, Any]:
    """Build an evidence pack around a resolved entity.

    This is intentionally not a verdict engine. It resolves the entity, finds
    nearby live context, and labels correlation signals as hypotheses that an
    agent or user can inspect.
    """
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
        limit=5,
    )
    best = lookup.get("best_match") if isinstance(lookup.get("best_match"), dict) else None
    if not best:
        return {
            "status": "unresolved",
            "claim_level": "no_entity_match",
            "lookup": lookup,
            "entity": None,
            "center": None,
            "signals": [],
            "evidence": {},
            "recommended_next": ["Try a callsign, tail number, MMSI, IMO, owner, or exact vessel/aircraft name."],
            "version": get_data_version(),
        }

    lat = _coerce_float(best.get("lat") or best.get("latitude"))
    lng = _coerce_float(best.get("lng") or best.get("lon") or best.get("longitude"))
    if lat is None or lng is None:
        return {
            "status": "resolved_without_current_position",
            "claim_level": "identity_only",
            "lookup": lookup,
            "entity": best,
            "center": None,
            "signals": [],
            "evidence": {},
            "recommended_next": ["Install a track_entity watch so the system can alert when this entity reappears with coordinates."],
            "version": get_data_version(),
        }

    radius = _coerce_float(radius_km)
    if radius is None:
        radius = 100.0
    radius = max(1.0, min(1000.0, radius))
    limit = _coerce_limit(limit, default=10, maximum=50)

    nearby = entities_near(
        lat=lat,
        lng=lng,
        radius_km=radius,
        entity_types=[
            "tracked",
            "military",
            "jets",
            "private",
            "commercial",
            "ships",
            "uavs",
            "satellites",
        ],
        limit=limit + 5,
    )
    proximate_entities = [
        item for item in nearby.get("results", [])
        if not _entity_same_as_context(best, item)
    ][:limit]

    context = _nearby_items_from_layers(
        lat=lat,
        lng=lng,
        radius_km=radius,
        layers=(
            "correlations",
            "sar_anomalies",
            "internet_outages",
            "weather_alerts",
            "earthquakes",
            "gps_jamming",
            "news",
            "gdelt",
            "crowdthreat",
            "frontlines",
            "liveuamap",
            "military_bases",
            "datacenters",
            "power_plants",
        ),
        limit_per_layer=min(limit, 25),
    )

    signals: list[dict[str, Any]] = []
    if context.get("correlations"):
        signals.append({
            "type": "existing_correlation_near_entity",
            "confidence": 0.75,
            "reason": f"{len(context['correlations'])} active correlation alert(s) within {radius:g} km",
            "evidence_layers": ["correlations"],
        })
    if context.get("sar_anomalies"):
        signals.append({
            "type": "sar_anomaly_near_entity",
            "confidence": 0.65,
            "reason": f"{len(context['sar_anomalies'])} SAR anomaly record(s) within {radius:g} km",
            "evidence_layers": ["sar_anomalies"],
        })
    if context.get("internet_outages"):
        signals.append({
            "type": "infrastructure_disruption_near_entity",
            "confidence": 0.6,
            "reason": f"{len(context['internet_outages'])} internet outage record(s) within {radius:g} km",
            "evidence_layers": ["internet_outages"],
        })
    hazard_layers = [layer for layer in ("weather_alerts", "earthquakes", "gps_jamming") if context.get(layer)]
    if hazard_layers:
        signals.append({
            "type": "environment_or_rf_hazard_near_entity",
            "confidence": 0.55,
            "reason": "Environmental or RF hazard context is nearby",
            "evidence_layers": hazard_layers,
        })
    if proximate_entities:
        signals.append({
            "type": "nearby_live_entities",
            "confidence": 0.5,
            "reason": f"{len(proximate_entities)} other live tracked entities within {radius:g} km",
            "evidence_layers": sorted({str(item.get("source_layer") or "") for item in proximate_entities if item.get("source_layer")}),
        })

    event_count = sum(len(context.get(layer, [])) for layer in ("news", "gdelt", "crowdthreat", "frontlines", "liveuamap"))
    if event_count:
        signals.append({
            "type": "nearby_event_reporting",
            "confidence": 0.45,
            "reason": f"{event_count} nearby event/news record(s) within {radius:g} km",
            "evidence_layers": [layer for layer in ("news", "gdelt", "crowdthreat", "frontlines", "liveuamap") if context.get(layer)],
        })

    status = "context_found" if signals else "no_nearby_context"
    return {
        "status": status,
        "claim_level": "evidence_pack_not_verdict",
        "lookup": lookup,
        "entity": best,
        "center": {"lat": lat, "lng": lng},
        "radius_km": radius,
        "signals": signals,
        "evidence": {
            "proximate_entities": proximate_entities,
            "context_layers": context,
        },
        "recommended_next": [
            "Use track_entity to keep monitoring this exact entity.",
            "Use watch_area on the returned center if the area matters more than the entity.",
            "Treat co-location as a lead, not proof of intent or causation.",
        ],
        "version": get_data_version(),
    }


def search_news(
    *,
    query: str,
    limit: int = 10,
    include_gdelt: bool = True,
) -> dict[str, Any]:
    """Search news and event layers server-side and return a compact result set."""
    query_norm = _norm_text(query)
    if not query_norm:
        return {"results": [], "version": get_data_version(), "truncated": False}

    snap = get_latest_data_subset_refs("news", "gdelt", "crowdthreat", "liveuamap", "frontlines")
    out: list[dict[str, Any]] = []
    limit = _coerce_limit(limit, default=10, maximum=50)

    for article in snap.get("news") or []:
        if not isinstance(article, dict):
            continue
        text = " ".join(
            (
                _norm_text(article.get("title")),
                _norm_text(article.get("summary")),
                _norm_text(article.get("description")),
                _norm_text(article.get("source")),
            )
        )
        if not _text_matches_query(query_norm, text):
            continue
        out.append(
            {
                "source_layer": "news",
                "title": article.get("title") or "",
                "summary": article.get("summary") or article.get("description") or "",
                "source": article.get("source") or "",
                "link": article.get("link") or article.get("url") or "",
                "lat": article.get("lat"),
                "lng": article.get("lng"),
                "risk_score": article.get("risk_score"),
            }
        )
        if len(out) >= limit:
            return {"results": out, "version": get_data_version(), "truncated": True}

    if include_gdelt:
        for event in snap.get("gdelt") or []:
            if not isinstance(event, dict):
                continue
            props = event.get("properties") if isinstance(event.get("properties"), dict) else event
            text = " ".join(
                (
                    _norm_text(props.get("title")),
                    _norm_text(props.get("name")),
                    _norm_text(props.get("sourceurl")),
                )
            )
            if not _text_matches_query(query_norm, text):
                continue
            coords = []
            geometry = event.get("geometry")
            if isinstance(geometry, dict):
                coords = geometry.get("coordinates") or []
            out.append(
                {
                    "source_layer": "gdelt",
                    "title": props.get("title") or props.get("name") or "",
                    "summary": "",
                    "source": "GDELT",
                    "link": props.get("sourceurl") or "",
                    "lat": coords[1] if len(coords) >= 2 else None,
                    "lng": coords[0] if len(coords) >= 2 else None,
                    "risk_score": props.get("count"),
                }
            )
            if len(out) >= limit:
                return {"results": out, "version": get_data_version(), "truncated": True}

    for event in snap.get("crowdthreat") or []:
        if not isinstance(event, dict):
            continue
        text = " ".join(
            (
                _norm_text(event.get("title")),
                _norm_text(event.get("summary")),
                _norm_text(event.get("description")),
                _norm_text(event.get("category")),
                _norm_text(event.get("city")),
                _norm_text(event.get("state")),
            )
        )
        if not _text_matches_query(query_norm, text):
            continue
        out.append(
            {
                "source_layer": "crowdthreat",
                "title": event.get("title") or "",
                "summary": event.get("summary") or event.get("description") or "",
                "source": event.get("category") or "CrowdThreat",
                "link": event.get("link") or event.get("url") or "",
                "lat": event.get("lat") or event.get("latitude"),
                "lng": event.get("lng") or event.get("lon") or event.get("longitude"),
                "risk_score": event.get("risk_score") or event.get("severity") or event.get("score"),
            }
        )
        if len(out) >= limit:
            return {"results": out, "version": get_data_version(), "truncated": True}

    for layer in ("liveuamap", "frontlines"):
        for event in snap.get(layer) or []:
            if not isinstance(event, dict):
                continue
            text = " ".join(
                (
                    _norm_text(event.get("title")),
                    _norm_text(event.get("name")),
                    _norm_text(event.get("description")),
                    _norm_text(event.get("category")),
                    _norm_text(event.get("place")),
                )
            )
            if not _text_matches_query(query_norm, text):
                continue
            lat, lng = _extract_coords(event)
            out.append(
                {
                    "source_layer": layer,
                    "title": event.get("title") or event.get("name") or "",
                    "summary": event.get("description") or "",
                    "source": event.get("category") or layer,
                    "link": event.get("link") or event.get("url") or "",
                    "lat": lat,
                    "lng": lng,
                    "risk_score": event.get("severity") or event.get("score"),
                }
            )
            if len(out) >= limit:
                return {"results": out, "version": get_data_version(), "truncated": True}

    return {"results": out, "version": get_data_version(), "truncated": False}


def search_telemetry(
    *,
    query: str,
    layers: list[str] | tuple[str, ...] | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    """Search compactly across the telemetry store without pulling whole layers."""
    query_norm = _norm_text(query)
    if not query_norm:
        return {"results": [], "version": get_data_version(), "truncated": False, "searched_layers": []}

    requested_layers = _resolve_layers(
        layers,
        _LAYER_ALIASES,
        _UNIVERSAL_SEARCH_DEFAULT_LAYERS,
    )
    searchable_layers = [
        layer for layer in requested_layers
        if layer in _UNIVERSAL_SEARCH_SPECS
    ]
    if not searchable_layers:
        searchable_layers = [layer for layer in _UNIVERSAL_SEARCH_DEFAULT_LAYERS if layer in _UNIVERSAL_SEARCH_SPECS]
    query_info = _parse_search_query(query_norm, searchable_layers)
    preferred_layers = list(query_info.get("preferred_layers") or [])
    if preferred_layers:
        searchable_layers = preferred_layers + [layer for layer in searchable_layers if layer not in preferred_layers]
    search_index = _get_search_index()
    docs = list(search_index.get("docs") or [])
    postings = dict(search_index.get("postings") or {})
    vocabulary = set(search_index.get("vocabulary") or set())
    layer_set = set(searchable_layers)
    query_info["entity_tokens"] = _expand_query_terms(list(query_info.get("entity_tokens") or []), vocabulary)
    query_info["anchor_tokens"] = _expand_query_terms(list(query_info.get("anchor_tokens") or []), vocabulary)
    limit = _coerce_limit(limit, default=25, maximum=100)
    out: list[dict[str, Any]] = []
    candidate_ids: set[int] = set()
    anchor_tokens = list(query_info.get("anchor_tokens") or [])
    entity_tokens = list(query_info.get("entity_tokens") or [])
    for token in anchor_tokens + entity_tokens:
        candidate_ids.update(postings.get(token, set()))
    if not candidate_ids:
        candidate_ids = {
            int(doc["id"])
            for doc in docs
            if doc.get("layer") in layer_set
        }

    for doc_id in candidate_ids:
        if doc_id >= len(docs):
            continue
        doc = docs[doc_id]
        layer = str(doc.get("layer") or "")
        if layer not in layer_set:
            continue
        item = doc.get("candidate")
        spec = doc.get("spec")
        if not isinstance(item, dict) or not isinstance(spec, dict):
            continue
        match = _score_candidate(item, query_info, spec, layer)
        if not match:
            continue
        out.append(
            _compact_search_result(
                layer,
                item,
                spec,
                int(match["score"]),
                matched_tokens=list(match.get("matched_tokens") or []),
                confidence=float(match.get("confidence", 0.0) or 0.0),
            )
        )

    out.sort(
        key=lambda result: (
            int(result.get("score", 0) or 0),
            float(result.get("confidence", 0.0) or 0.0),
            str(result.get("time", "")),
            str(result.get("label", "")),
        ),
        reverse=True,
    )
    truncated = len(out) > limit
    limited = out[:limit]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for result in limited:
        grouped.setdefault(str(result.get("group") or "other"), []).append(result)
    return {
        "results": limited,
        "groups": [
            {
                "group": group,
                "count": len(results),
                "results": results,
            }
            for group, results in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0]))
        ],
        "version": get_data_version(),
        "truncated": truncated,
        "searched_layers": searchable_layers,
    }


def get_layer_slice(
    *,
    layers: list[str] | tuple[str, ...],
    limit_per_layer: int | None = None,
    since_version: int | None = None,
    since_layer_versions: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Return only the requested top-level telemetry layers, optionally version-gated.

    Two incremental modes (``since_layer_versions`` takes precedence):

    1. **Global** (``since_version``): cheap all-or-nothing check against a
       single monotonic counter.  Almost never returns "no change" because
       *any* layer update bumps the counter.

    2. **Per-layer** (``since_layer_versions``): the agent sends a dict of
       ``{layer_name: version}`` representing the versions it already holds.
       Only layers whose server-side version is *newer* than the agent's
       version are serialized and returned.  Layers the agent is already
       current on are omitted entirely — zero serialization, zero transfer.
       This is the preferred mode for SSE-connected agents.
    """
    current_version = get_data_version()
    current_layer_versions = get_layer_versions()
    limit_per_layer = _coerce_optional_limit(limit_per_layer)
    available_layers = set(_available_layer_names())
    requested: list[str] = []
    seen: set[str] = set()
    for layer in layers or []:
        canonical = _LAYER_ALIASES.get(_norm_key(layer), _norm_key(layer))
        if canonical in available_layers and canonical not in seen:
            seen.add(canonical)
            requested.append(canonical)

    # --- Per-layer incremental (preferred) ---
    if since_layer_versions is not None and isinstance(since_layer_versions, dict):
        # Determine which requested layers actually changed
        stale_layers: list[str] = []
        for layer in requested:
            agent_ver = since_layer_versions.get(layer)
            server_ver = current_layer_versions.get(layer, 0)
            if agent_ver is None or int(agent_ver) < server_ver:
                stale_layers.append(layer)

        if not stale_layers:
            return {
                "version": current_version,
                "layer_versions": {l: current_layer_versions.get(l, 0) for l in requested},
                "changed": False,
                "layers": {},
                "requested_layers": requested,
                "missing_layers": [],
                "truncated": {},
            }
        # Only serialize the stale layers
        requested_to_serialize = stale_layers
    else:
        # --- Global incremental (legacy fallback) ---
        if since_version is not None:
            try:
                requested_version = int(since_version)
            except (TypeError, ValueError):
                requested_version = -1
            if requested_version == current_version:
                return {
                    "version": current_version,
                    "layer_versions": {l: current_layer_versions.get(l, 0) for l in requested},
                    "changed": False,
                    "layers": {},
                    "requested_layers": requested,
                    "missing_layers": [],
                    "truncated": {},
                }
        requested_to_serialize = requested

    if not requested:
        return {
            "version": current_version,
            "layer_versions": current_layer_versions,
            "changed": True,
            "layers": {},
            "requested_layers": [],
            "missing_layers": list(layers or []),
            "available_layers": sorted(available_layers),
            "truncated": {},
        }

    snap = get_latest_data_subset_refs(*requested_to_serialize)
    result: dict[str, Any] = {}
    truncated: dict[str, int] = {}
    for layer in requested_to_serialize:
        value = snap.get(layer)
        if isinstance(value, list):
            if limit_per_layer is None:
                result[layer] = list(value)
            else:
                result[layer] = list(value[:limit_per_layer])
                if len(value) > limit_per_layer:
                    truncated[layer] = len(value) - limit_per_layer
            continue
        if isinstance(value, dict):
            compact: dict[str, Any] = {}
            for key, item in value.items():
                if isinstance(item, list):
                    if limit_per_layer is None:
                        compact[key] = list(item)
                    else:
                        compact[key] = list(item[:limit_per_layer])
                        if len(item) > limit_per_layer:
                            truncated[f"{layer}.{key}"] = len(item) - limit_per_layer
                else:
                    compact[key] = item
            result[layer] = compact
            continue
        result[layer] = value

    missing = [
        layer for layer in layers or []
        if _LAYER_ALIASES.get(_norm_key(layer), _norm_key(layer)) not in requested
    ]
    return {
        "version": current_version,
        "layer_versions": {l: current_layer_versions.get(l, 0) for l in requested},
        "changed": True,
        "layers": result,
        "requested_layers": requested,
        "missing_layers": missing,
        "available_layers": sorted(available_layers),
        "truncated": truncated,
    }


def entities_near(
    *,
    lat: float,
    lng: float,
    radius_km: float = 50,
    entity_types: list[str] | tuple[str, ...] | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    """Return a compact proximity search across selected telemetry layers."""
    center_lat = _coerce_float(lat)
    center_lng = _coerce_float(lng)
    radius = _coerce_float(radius_km)
    if center_lat is None or center_lng is None:
        return {"results": [], "version": get_data_version(), "truncated": False}
    if radius is None:
        radius = 50.0
    radius = max(1.0, min(5000.0, radius))
    limit = _coerce_limit(limit)
    layers = _resolve_layers(
        entity_types,
        _ENTITY_LAYER_ALIASES,
        ("tracked_flights", "military_flights", "private_jets", "ships", "uavs", "satellites"),
    )
    snap = get_latest_data_subset_refs(*layers)
    out: list[dict[str, Any]] = []

    for layer in layers:
        items = snap.get(layer) or []
        if isinstance(items, dict):
            items = items.get("vessels", []) or items.get("items", [])
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            item_lat = _coerce_float(item.get("lat") or item.get("latitude"))
            item_lng = _coerce_float(item.get("lng") or item.get("lon") or item.get("longitude"))
            if item_lat is None or item_lng is None:
                continue
            distance = _haversine_km(center_lat, center_lng, item_lat, item_lng)
            if distance > radius:
                continue
            out.append(
                {
                    "source_layer": layer,
                    "label": item.get("callsign")
                    or item.get("flight")
                    or item.get("name")
                    or item.get("shipName")
                    or item.get("title")
                    or item.get("id")
                    or item.get("norad_id")
                    or "",
                    "lat": item_lat,
                    "lng": item_lng,
                    "distance_km": round(distance, 2),
                    "type": item.get("type")
                    or item.get("shipType")
                    or item.get("category")
                    or item.get("t")
                    or "",
                    "id": item.get("icao24")
                    or item.get("mmsi")
                    or item.get("id")
                    or item.get("norad_id")
                    or "",
                }
            )
            if len(out) >= limit:
                out.sort(key=lambda entry: entry.get("distance_km", 0))
                return {"results": out, "version": get_data_version(), "truncated": True}

    out.sort(key=lambda entry: entry.get("distance_km", 0))
    return {"results": out, "version": get_data_version(), "truncated": False}
