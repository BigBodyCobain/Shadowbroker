#!/usr/bin/env python3
"""ShadowBroker public skill: read-only client for the public data feed.

This is the public sibling of ``openclaw-skills/shadowbroker`` (the full
skill that talks to your own ShadowBroker install). It offers the same read
commands and the same answer shapes, but it never contacts a ShadowBroker
backend. It only downloads what the public viewer itself downloads: the map
data files, and, when asked to look at a camera, that camera's current picture.

That makes it safe to hand to anyone and any agent:
  * no API key, token, account or secret is needed or used;
  * every request is a plain HTTPS GET of a published file, with one
    exception you ask for by name: ``camera_snapshot`` downloads one current
    picture from a public camera's own address (see ``sb_camera.py``);
  * there is nothing to send, post, pin or change. Write commands from the
    full skill are refused with a clear message.

Standard library only (Python 3.10+).

    from sb_public import ShadowBrokerPublicClient
    sb = ShadowBrokerPublicClient()
    answer = await sb.ask("where is N189AM")

    python sb_public.py ask "ships near 36.8, -76.3"
    python sb_public.py cmd find_flights '{"callsign": "RCH"}'
    python sb_public.py look --lat 40.758 --lng -73.9855
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import hashlib
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlsplit

try:  # packaged as a module, or run as a plain script next to sb_camera.py
    from . import sb_camera
except ImportError:
    import sb_camera

__all__ = ["ShadowBrokerPublicClient", "PublicSkillError", "READ_COMMANDS", "WRITE_COMMANDS"]

# Set this when the public data feed has its permanent address. Until then
# pass ``base_url`` or set SHADOWBROKER_PUBLIC_URL.
DEFAULT_BASE_URL = ""

SUPPORTED_SCHEMA = 1
MANIFEST_TTL_S = 10.0
USER_AGENT = "shadowbroker-public-skill/1.0"
MAX_FILE_BYTES = 64 * 1024 * 1024

FLIGHT_LAYERS = ("tracked_flights", "military_flights", "private_jets", "private_flights", "commercial_flights")
ENTITY_LAYERS = ("tracked_flights", "military_flights", "private_jets", "ships", "uavs", "satellites")

FLIGHT_LAYER_ALIASES = {
    "tracked": "tracked_flights",
    "military": "military_flights",
    "jets": "private_jets",
    "private": "private_flights",
    "commercial": "commercial_flights",
    "flights": "commercial_flights",
}
ENTITY_LAYER_ALIASES = {
    **FLIGHT_LAYER_ALIASES,
    "aircraft": "tracked_flights",
    "ship": "ships",
    "vessel": "ships",
    "vessels": "ships",
    "maritime": "ships",
    "satellite": "satellites",
    "uav": "uavs",
    "drones": "uavs",
}
LAYER_ALIASES = {
    **ENTITY_LAYER_ALIASES,
    "fishing": "fishing_activity",
    "gfw": "fishing_activity",
    "uap": "uap_sightings",
    "ufo": "uap_sightings",
    "malware": "malware_threats",
    "botnet": "malware_threats",
    "cyber": "cyber_threats",
    "cisa": "cyber_threats",
    "kev": "cyber_threats",
    "scm": "scm_suppliers",
    "suppliers": "scm_suppliers",
    "fires": "firms_fires",
    "quakes": "earthquakes",
    "cameras": "cctv",
    "receivers": "kiwisdr",
}

# The read commands this skill answers, named as in the full skill.
READ_COMMANDS = frozenset({
    "ask",
    "route_query",
    "run_playbook",
    "channel_status",
    "get_summary",
    "what_changed",
    "get_layer_slice",
    "find_flights",
    "find_ships",
    "find_entity",
    "entities_near",
    "search_news",
    "brief_area",
    "get_correlations",
    "get_sigint_totals",
    "find_cameras",
    "camera_snapshot",
})

# Commands of the full skill that need your own ShadowBroker install.
WRITE_COMMANDS = frozenset({
    "place_pin", "place_pins_batch", "delete_pin", "inject_data", "create_layer", "update_layer",
    "delete_layer", "refresh_feed", "take_snapshot", "add_watch", "track_entity", "watch_area",
    "remove_watch", "clear_watches", "show_satellite", "show_sentinel", "place_analysis_zone",
    "delete_analysis_zone", "clear_analysis_zones", "ensure_infonet_ready", "join_infonet_swarm",
    "post_gate_message", "post_to_gate", "cast_vote", "send_dm", "send_encrypted_dm", "osint_sweep",
    "sar_aoi_add", "sar_aoi_remove", "sar_pin_from_anomaly", "sar_focus_aoi", "sar_watch_anomaly",
    "gt_analyze", "timemachine_playback",
})

RE_N_NUMBER = re.compile(r"\bN\d{1,5}[A-Z]{0,2}\b", re.I)
RE_CALLSIGN = re.compile(r"\b[A-Z]{2,4}\d{1,4}[A-Z]?\b")
RE_MMSI = re.compile(r"\b\d{9}\b")
RE_RADIUS = re.compile(
    r"(?:within|inside|in a radius of|radius of|radius)?\s*(\d+(?:\.\d+)?)\s*"
    r"(km|kilomet(?:er|re)s?|mi|miles?|nm|nmi|nautical miles?)\b(?:\s+(?:of|from|around))?",
    re.I,
)
CAMERA_WORDS = ("camera", "cctv", "webcam", "traffic cam")
LOOK_WORDS = ("look at", "look", "see", "show me", "snapshot", "picture", "photo", "image", "view", "watch")
RE_LATLNG = re.compile(r"(-?\d{1,2}(?:\.\d+)?)\s*[, ]\s*(-?\d{1,3}(?:\.\d+)?)")


class PublicSkillError(RuntimeError):
    """The public skill cannot do this (or the public feed is unreachable)."""


# ── Small helpers (same behaviour as the app's telemetry search) ───────────

def _norm_text(value: Any) -> str:
    return str(value or "").strip().lower()


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


def _matches_query(candidate: dict[str, Any], query: str, fields: tuple[str, ...]) -> bool:
    normalized = _norm_text(query)
    if not normalized:
        return True
    haystack = " ".join(_norm_text(candidate.get(field)) for field in fields)
    if normalized in haystack:
        return True
    tokens = _query_tokens(normalized)
    return bool(tokens) and all(token in haystack for token in tokens)


def _text_matches_query(query: str, text: Any) -> bool:
    normalized_query = _norm_text(query)
    normalized_text = _norm_text(text)
    if not normalized_query:
        return True
    if normalized_query in normalized_text:
        return True
    tokens = _query_tokens(normalized_query)
    return bool(tokens) and all(token in normalized_text for token in tokens)


def _extract_coords(candidate: dict[str, Any]) -> tuple[float | None, float | None]:
    lat = _coerce_float(candidate.get("lat") or candidate.get("latitude") or candidate.get("y"))
    lng = _coerce_float(
        candidate.get("lng") or candidate.get("lon") or candidate.get("longitude") or candidate.get("x")
    )
    geometry = candidate.get("geometry")
    if (lat is None or lng is None) and isinstance(geometry, dict):
        coords = geometry.get("coordinates") or []
        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
            lng = lng if lng is not None else _coerce_float(coords[0])
            lat = lat if lat is not None else _coerce_float(coords[1])
    if lat is None or lng is None:
        coords = candidate.get("coords")
        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
            lat = lat if lat is not None else _coerce_float(coords[0])
            lng = lng if lng is not None else _coerce_float(coords[1])
    return lat, lng


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _resolve_layers(requested: Any, aliases: dict[str, str], default: tuple[str, ...]) -> list[str]:
    if not isinstance(requested, (list, tuple)) or not requested:
        return list(default)
    out: list[str] = []
    for name in requested:
        key = str(name or "").strip().lower().replace("-", "_").replace(" ", "_")
        resolved = aliases.get(key, key)
        if resolved and resolved not in out:
            out.append(resolved)
    return out or list(default)


def _unwrap_items(value: Any) -> list[Any]:
    """A layer is usually a list; a few are objects holding one."""
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("features", "items", "results", "vessels", "posts", "threats", "suppliers", "events"):
            inner = value.get(key)
            if isinstance(inner, list):
                return inner
    return []


def _record_count(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        inner = _unwrap_items(value)
        return len(inner) if inner else (1 if value else 0)
    return 0


def lookup_key(value: Any) -> str:
    """Normalise an identifier (callsign, tail, MMSI, name) for exact lookup."""
    return re.sub(r"[^a-z0-9]+", "", _norm_text(value))


def lookup_shard(key: str, shards: int = 16) -> str:
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return format(int(digest[:8], 16) % shards, "x")


def _feet(metres: Any) -> int | None:
    """The feed stores aircraft altitude in metres; pilots and trackers use feet."""
    value = _coerce_float(metres)
    return None if value is None else round(value / 0.3048)


def project_flight(layer: str, flight: dict[str, Any]) -> dict[str, Any]:
    return {
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
        # Extras beyond the app's own result shape, with explicit units.
        "model": flight.get("model") or "",
        "speed_knots": flight.get("speed_knots"),
        "altitude_ft": _feet(flight.get("alt")),
    }


def project_ship(ship: dict[str, Any]) -> dict[str, Any]:
    return {
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


# ── The feed ───────────────────────────────────────────────────────────────

class PublicFeed:
    """Reads the published data files. GET only, one host, nothing else."""

    def __init__(self, base_url: str, timeout: float = 30.0):
        base = (base_url or "").strip().rstrip("/")
        if not base:
            raise PublicSkillError(
                "No public feed address. Set SHADOWBROKER_PUBLIC_URL to the ShadowBroker public data address."
            )
        parts = urlsplit(base)
        local = parts.hostname in ("127.0.0.1", "localhost", "::1")
        if parts.scheme != "https" and not (parts.scheme == "http" and local):
            raise PublicSkillError("The public feed address must be https.")
        if parts.username or parts.password or parts.query:
            raise PublicSkillError("The public feed address must not carry credentials or a query.")
        self.base = base
        self.local = local
        self.timeout = timeout
        self._manifest: dict[str, Any] | None = None
        self._manifest_at = 0.0
        self._files: dict[str, tuple[str, Any]] = {}  # path -> (version, parsed)

    def _get(self, rel: str, version: str | None = None) -> Any:
        if not re.fullmatch(r"[A-Za-z0-9_\-./]+", rel) or ".." in rel:
            raise PublicSkillError("Refusing an unexpected file path from the feed.")
        url = f"{self.base}/{rel}" + (f"?v={version}" if version else "")
        request = urllib.request.Request(
            url, headers={"Accept": "application/json", "Accept-Encoding": "gzip", "User-Agent": USER_AGENT}
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310 - https GET
                raw = response.read(MAX_FILE_BYTES + 1)
                if len(raw) > MAX_FILE_BYTES:
                    raise PublicSkillError(f"{rel} is larger than expected.")
                if response.headers.get("Content-Encoding", "").lower() == "gzip":
                    raw = gzip.decompress(raw)
        except urllib.error.HTTPError as exc:
            raise PublicSkillError(f"The public feed returned HTTP {exc.code} for {rel}.") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise PublicSkillError(f"The public feed is unreachable: {exc}") from exc
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError as exc:
            raise PublicSkillError(f"{rel} is not valid JSON.") from exc

    def manifest(self, force: bool = False) -> dict[str, Any]:
        now = time.monotonic()
        if force or self._manifest is None or now - self._manifest_at > MANIFEST_TTL_S:
            data = self._get("manifest.json")
            if not isinstance(data, dict) or data.get("schema") != SUPPORTED_SCHEMA:
                raise PublicSkillError("The public feed uses a data format this skill does not understand.")
            self._manifest, self._manifest_at = data, now
        return self._manifest

    def _file(self, ref: dict[str, Any]) -> Any:
        path, version = str(ref.get("f", "")), str(ref.get("v", ""))
        cached = self._files.get(path)
        if cached and cached[0] == version:
            return cached[1]
        data = self._get(path, version)
        self._files[path] = (version, data)
        return data

    def layer(self, key: str) -> Any:
        """One data layer, or None if the feed does not publish it."""
        manifest = self.manifest()
        own = (manifest.get("keys") or {}).get(key)
        if own:
            return self._file(own)
        for bundle_ref in (manifest.get("bundles") or {}).values():
            bundle = self._file(bundle_ref)
            if isinstance(bundle, dict) and key in bundle:
                return bundle[key]
        return None

    def layer_names(self) -> list[str]:
        manifest = self.manifest()
        names = list((manifest.get("keys") or {}).keys())
        for bundle_ref in (manifest.get("bundles") or {}).values():
            bundle = self._file(bundle_ref)
            if isinstance(bundle, dict):
                names.extend(k for k in bundle if k not in names)
        return sorted(names)

    def lookup(self, identifier: str) -> list[dict[str, Any]] | None:
        """Exact identifier lookup through the feed's index. None = no index."""
        index = self.manifest().get("index") or {}
        shards = int(index.get("shards") or 0)
        key = lookup_key(identifier)
        if not shards or not key:
            return None
        shard = lookup_shard(key, shards)
        ref = (index.get("files") or {}).get(shard)
        if not ref:
            return None
        rows = self._file(ref)
        return [dict(row) for row in (rows.get(key) or [])] if isinstance(rows, dict) else None

    def version(self) -> int:
        return int(self.manifest().get("seq") or 0)


# ── The client ─────────────────────────────────────────────────────────────

class ShadowBrokerPublicClient:
    """Read-only ShadowBroker client over the public data feed.

    Method and command names follow the full skill's ``ShadowBrokerClient``
    so prompts and code written for one carry over to the other.
    """

    def __init__(self, base_url: str | None = None, timeout: float = 30.0):
        self.feed = PublicFeed(
            base_url or os.environ.get("SHADOWBROKER_PUBLIC_URL", "") or DEFAULT_BASE_URL, timeout=timeout
        )

    # -- command plumbing ---------------------------------------------------

    def command(self, cmd: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run one command synchronously. Returns ``{"ok": bool, "data"|"detail": ...}``."""
        name = str(cmd or "").strip().lower()
        params = dict(args or {})
        if name in WRITE_COMMANDS:
            return {
                "ok": False,
                "detail": (
                    f"'{name}' is not available in the public skill. It changes or sends something, "
                    "which needs your own ShadowBroker install and the full 'shadowbroker' skill."
                ),
                "public_skill": True,
            }
        handler = getattr(self, f"_cmd_{name}", None)
        if name not in READ_COMMANDS or handler is None:
            return {
                "ok": False,
                "detail": f"Unknown or unsupported command '{name}' in the public skill.",
                "supported": sorted(READ_COMMANDS),
                "public_skill": True,
            }
        try:
            return handler(params)
        except PublicSkillError as exc:
            return {"ok": False, "detail": str(exc), "public_skill": True}

    async def send_command(self, cmd: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        return await asyncio.to_thread(self.command, cmd, args)

    async def send_batch(self, batch: list[dict[str, Any]]) -> dict[str, Any]:
        results = []
        for item in batch or []:
            result = await self.send_command(str(item.get("cmd", "")), item.get("args") or {})
            results.append({"cmd": item.get("cmd"), **result})
        return {"ok": True, "results": results}

    async def ask(self, text: str, lat: float | None = None, lng: float | None = None,
                  radius_km: float = 50) -> dict[str, Any]:
        return await self.send_command("ask", {"text": text, "lat": lat, "lng": lng, "radius_km": radius_km})

    async def run_playbook(self, name: str, **args: Any) -> dict[str, Any]:
        return await self.send_command("run_playbook", {"name": name, **args})

    async def channel_status(self) -> dict[str, Any]:
        return await self.send_command("channel_status")

    async def get_summary(self) -> dict[str, Any]:
        return await self.send_command("get_summary")

    async def get_layer_slice(self, layers: list[str], limit_per_layer: int | None = None) -> dict[str, Any]:
        return await self.send_command("get_layer_slice", {"layers": layers, "limit_per_layer": limit_per_layer})

    async def get_near_me(self, lat: float, lng: float, radius_miles: float = 100) -> dict[str, Any]:
        return await self.send_command(
            "entities_near", {"lat": lat, "lng": lng, "radius_km": radius_miles * 1.609344, "limit": 100}
        )

    async def get_news_near(self, lat: float, lng: float, radius: float = 500) -> dict[str, Any]:
        return await self.send_command("brief_area", {"lat": lat, "lng": lng, "radius_km": radius})

    async def find_cameras(self, lat: float | None = None, lng: float | None = None, radius_km: float = 5,
                           query: str = "", limit: int = 10) -> dict[str, Any]:
        return await self.send_command(
            "find_cameras", {"lat": lat, "lng": lng, "radius_km": radius_km, "query": query, "limit": limit}
        )

    async def camera_snapshot(self, camera_id: str = "", lat: float | None = None, lng: float | None = None,
                              **options: Any) -> dict[str, Any]:
        return await self.send_command("camera_snapshot", {"id": camera_id, "lat": lat, "lng": lng, **options})

    def __getattr__(self, name: str) -> Any:
        if name in WRITE_COMMANDS:
            async def refused(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
                return self.command(name)
            return refused
        raise AttributeError(name)

    # -- reads --------------------------------------------------------------

    def _version(self) -> int:
        return self.feed.version()

    def _cmd_channel_status(self, _args: dict[str, Any]) -> dict[str, Any]:
        manifest = self.feed.manifest(force=True)
        generated = str(manifest.get("generated_at") or "")
        age_s: float | None = None
        try:
            stamp = time.strptime(generated, "%Y-%m-%dT%H:%M:%SZ")
            age_s = max(0.0, time.time() - (time.mktime(stamp) - time.timezone))
        except (TypeError, ValueError):
            age_s = None
        return {
            "ok": True,
            "data": {
                "mode": "public_feed",
                "read_only": True,
                "generated_at": generated,
                "age_seconds": None if age_s is None else round(age_s),
                "stale": bool(age_s is not None and age_s > 300),
                "cadence": manifest.get("cadence") or {},
                "lookup_index": bool((manifest.get("index") or {}).get("shards")),
                "version": int(manifest.get("seq") or 0),
            },
        }

    def _cmd_get_summary(self, _args: dict[str, Any]) -> dict[str, Any]:
        names = self.feed.layer_names()
        manifest = self.feed.manifest()
        heavy = manifest.get("keys") or {}
        counts: dict[str, int] = {}
        for name in names:
            if name in heavy and "count" in heavy[name]:
                counts[name] = int(heavy[name]["count"])  # no download needed
            else:
                counts[name] = _record_count(self.feed.layer(name))
        data = {
            "counts": counts,
            "available_layers": names,
            "non_empty_layers": [n for n in names if counts.get(n, 0) > 0],
            "layer_aliases": dict(LAYER_ALIASES),
            "last_updated": manifest.get("generated_at"),
            "version": self._version(),
        }
        return {"ok": True, "data": data, "version": data["version"]}

    def _cmd_what_changed(self, args: dict[str, Any]) -> dict[str, Any]:
        layers = args.get("layers")
        if isinstance(layers, (list, tuple)) and layers:
            return self._cmd_get_layer_slice(args)
        return self._cmd_get_summary(args)

    def _cmd_get_layer_slice(self, args: dict[str, Any]) -> dict[str, Any]:
        requested = args.get("layers")
        if not isinstance(requested, (list, tuple)) or not requested:
            return {"ok": False, "detail": "layers required, e.g. ['ships', 'earthquakes']"}
        limit = args.get("limit_per_layer")
        try:
            limit = int(limit) if limit not in (None, "") else None
        except (TypeError, ValueError):
            limit = None
        out: dict[str, Any] = {}
        missing: list[str] = []
        for layer in _resolve_layers(requested, LAYER_ALIASES, ()):
            value = self.feed.layer(layer)
            if value is None:
                missing.append(layer)
                continue
            if limit and isinstance(value, list):
                value = value[:limit]
            out[layer] = value
        return {"ok": True, "data": {"layers": out, "not_published": missing, "version": self._version()}}

    def _cmd_find_flights(self, args: dict[str, Any]) -> dict[str, Any]:
        layers = _resolve_layers(args.get("categories"), FLIGHT_LAYER_ALIASES, FLIGHT_LAYERS)
        limit = _coerce_limit(args.get("limit", 25))
        query = _norm_text(args.get("query"))
        callsign = _norm_text(args.get("callsign"))
        registration = _norm_text(args.get("registration"))
        icao24 = _norm_text(args.get("icao24"))
        owner = _norm_text(args.get("owner"))
        out: list[dict[str, Any]] = []
        for layer in layers:
            for flight in _unwrap_items(self.feed.layer(layer)):
                if not isinstance(flight, dict):
                    continue
                f_callsign = _norm_text(flight.get("callsign") or flight.get("flight") or flight.get("call"))
                f_registration = _norm_text(flight.get("registration") or flight.get("r"))
                f_owner = _norm_text(flight.get("owner") or flight.get("operator") or flight.get("alert_operator"))
                if callsign and callsign not in f_callsign:
                    continue
                if registration and registration not in f_registration:
                    continue
                if icao24 and icao24 != _norm_text(flight.get("icao24")):
                    continue
                if owner and owner not in f_owner:
                    continue
                if query and not _matches_query(
                    flight,
                    query,
                    ("callsign", "flight", "call", "registration", "r", "icao24", "owner", "operator",
                     "alert_operator", "type", "t", "aircraft_type"),
                ):
                    continue
                out.append(project_flight(layer, flight))
                if len(out) >= limit:
                    return {"ok": True, "data": {"results": out, "version": self._version(), "truncated": True}}
        return {"ok": True, "data": {"results": out, "version": self._version(), "truncated": False}}

    def _cmd_find_ships(self, args: dict[str, Any]) -> dict[str, Any]:
        limit = _coerce_limit(args.get("limit", 25))
        query = _norm_text(args.get("query"))
        mmsi = _norm_text(args.get("mmsi"))
        imo = _norm_text(args.get("imo"))
        name = _norm_text(args.get("name"))
        out: list[dict[str, Any]] = []
        for ship in _unwrap_items(self.feed.layer("ships")):
            if not isinstance(ship, dict):
                continue
            if mmsi and mmsi != _norm_text(ship.get("mmsi")):
                continue
            if imo and imo != _norm_text(ship.get("imo")):
                continue
            if name and name not in _norm_text(ship.get("name") or ship.get("shipName")):
                continue
            if query and not _matches_query(
                ship,
                query,
                ("name", "shipName", "mmsi", "imo", "callsign", "shipType", "type", "yacht_owner",
                 "yacht_name", "yacht_category", "owner"),
            ):
                continue
            out.append(project_ship(ship))
            if len(out) >= limit:
                return {"ok": True, "data": {"results": out, "version": self._version(), "truncated": True}}
        return {"ok": True, "data": {"results": out, "version": self._version(), "truncated": False}}

    def _cmd_find_entity(self, args: dict[str, Any]) -> dict[str, Any]:
        """Exact-first resolver for an aircraft or ship, like the full skill's find_entity."""
        entity_type = _norm_text(args.get("entity_type") or args.get("type"))
        limit = _coerce_limit(args.get("limit", 10), default=10, maximum=50)
        identifiers = [
            args.get(k) for k in ("icao24", "registration", "tail_number", "callsign", "mmsi", "imo", "name")
        ]
        query = str(args.get("query") or "").strip()
        owner = str(args.get("owner") or args.get("operator") or "").strip()
        exact_terms = [str(v).strip() for v in identifiers if str(v or "").strip()]
        # A bare query may itself be an identifier or a full name ("EVER GIVEN").
        index_terms = list(exact_terms)
        if query and query not in index_terms:
            index_terms.append(query)
        if query and not exact_terms and len(_query_tokens(query)) == 1:
            exact_terms.append(query)

        results: list[dict[str, Any]] = []
        seen: set[str] = set()

        def add(row: dict[str, Any], match: str) -> None:
            # Index rows omit empty fields; give every result the full shape.
            row = {**(project_flight("", {}) if "source_layer" in row else project_ship({})), **row}
            key = str(row.get("icao24") or row.get("mmsi") or row.get("callsign") or row.get("name") or "")
            tag = f"{row.get('source_layer', 'ships')}:{key}"
            if not key or tag in seen:
                return
            seen.add(tag)
            kind = "ship" if "mmsi" in row else "aircraft"
            if entity_type in ("ship", "aircraft") and kind != entity_type:
                return
            results.append({"entity_type": kind, "match": match, **row})

        # 1. The feed's exact-identifier index: one small file, no layer download.
        for term in index_terms:
            rows = self.feed.lookup(term)
            for row in rows or []:
                add(row, "exact")

        # 2. Exact match by scanning the layers.
        if not results:
            for term in exact_terms:
                key = lookup_key(term)
                if entity_type != "ship":
                    for row in self._cmd_find_flights({"query": term, "limit": 100})["data"]["results"]:
                        if key in (lookup_key(row["callsign"]), lookup_key(row["registration"]),
                                   lookup_key(row["icao24"])):
                            add(row, "exact")
                if entity_type != "aircraft":
                    for row in self._cmd_find_ships({"query": term, "limit": 100})["data"]["results"]:
                        if key in (lookup_key(row["mmsi"]), lookup_key(row["imo"]), lookup_key(row["name"]),
                                   lookup_key(row["tracked_name"])):
                            add(row, "exact")

        # 3. Owner / name search.
        text = owner or query
        if text and (not results or owner):
            if entity_type != "ship":
                flight_args = {"owner": owner, "limit": limit} if owner else {"query": text, "limit": limit}
                for row in self._cmd_find_flights(flight_args)["data"]["results"]:
                    add(row, "owner" if owner else "text")
            if entity_type != "aircraft":
                for row in self._cmd_find_ships({"query": text, "limit": limit})["data"]["results"]:
                    add(row, "owner" if owner else "text")

        results = results[:limit]
        return {
            "ok": True,
            "data": {
                "results": results,
                "best_match": results[0] if results else None,
                "resolved": bool(results),
                "version": self._version(),
            },
        }

    def _cmd_entities_near(self, args: dict[str, Any]) -> dict[str, Any]:
        lat, lng = _coerce_float(args.get("lat")), _coerce_float(
            args.get("lng") if args.get("lng") is not None else args.get("lon")
        )
        if lat is None or lng is None:
            return {"ok": False, "detail": "lat and lng required"}
        radius = _coerce_float(args.get("radius_km"))
        radius = max(1.0, min(5000.0, 50.0 if radius is None else radius))
        limit = _coerce_limit(args.get("limit", 25))
        layers = _resolve_layers(args.get("entity_types"), LAYER_ALIASES, ENTITY_LAYERS)
        out: list[dict[str, Any]] = []
        for layer in layers:
            for item in _unwrap_items(self.feed.layer(layer)):
                if not isinstance(item, dict):
                    continue
                props = item.get("properties") if isinstance(item.get("properties"), dict) else {}
                item_lat, item_lng = _extract_coords(item)
                if item_lat is None or item_lng is None:
                    continue
                distance = _haversine_km(lat, lng, item_lat, item_lng)
                if distance > radius:
                    continue
                out.append({
                    "source_layer": layer,
                    "label": item.get("callsign") or item.get("flight") or item.get("name")
                    or item.get("shipName") or item.get("title") or props.get("name") or item.get("id")
                    or item.get("norad_id") or "",
                    "lat": item_lat,
                    "lng": item_lng,
                    "distance_km": round(distance, 2),
                    "type": item.get("type") or item.get("shipType") or item.get("category")
                    or item.get("t") or "",
                    "id": item.get("icao24") or item.get("mmsi") or item.get("id") or item.get("norad_id") or "",
                })
        out.sort(key=lambda entry: entry.get("distance_km", 0))
        truncated = len(out) > limit
        return {"ok": True, "data": {"results": out[:limit], "version": self._version(), "truncated": truncated,
                                     "total": len(out), "radius_km": radius}}

    def _cmd_search_news(self, args: dict[str, Any]) -> dict[str, Any]:
        query = _norm_text(args.get("query"))
        limit = _coerce_limit(args.get("limit", 10), default=10, maximum=50)
        out: list[dict[str, Any]] = []
        if not query:
            return {"ok": True, "data": {"results": [], "version": self._version(), "truncated": False}}
        for article in _unwrap_items(self.feed.layer("news")):
            if not isinstance(article, dict):
                continue
            text = " ".join(_norm_text(article.get(k)) for k in ("title", "summary", "description", "source"))
            if not _text_matches_query(query, text):
                continue
            coords = article.get("coords") if isinstance(article.get("coords"), (list, tuple)) else [None, None]
            out.append({
                "source_layer": "news",
                "title": article.get("title") or "",
                "source": article.get("source") or "",
                "url": article.get("link") or article.get("url") or "",
                "published": article.get("published") or "",
                "risk_score": article.get("risk_score"),
                "lat": coords[0] if len(coords) >= 2 else None,
                "lng": coords[1] if len(coords) >= 2 else None,
            })
        if args.get("include_gdelt", True):
            for feature in _unwrap_items(self.feed.layer("gdelt")):
                props = feature.get("properties") if isinstance(feature, dict) else None
                if not isinstance(props, dict):
                    continue
                headlines = [h for h in (props.get("_headlines_list") or []) if isinstance(h, str)]
                urls = props.get("_urls_list") or []
                # Prefer the headline that actually mentions the topic.
                hit = next((i for i, h in enumerate(headlines) if _text_matches_query(query, h)), None)
                if hit is None and not _text_matches_query(query, props.get("name")):
                    continue
                pick = hit if hit is not None else 0
                url = urls[pick] if pick < len(urls) and isinstance(urls[pick], str) else ""
                lat, lng = _extract_coords(feature)
                out.append({
                    "source_layer": "gdelt",
                    "match": "headline" if hit is not None else "location",
                    "title": (headlines[pick] if headlines else props.get("name")) or "",
                    "source": (urlsplit(url).hostname or "").removeprefix("www.") or "GDELT",
                    "url": url,
                    "published": str(props.get("event_date") or ""),
                    "location": props.get("name") or "",
                    "event_count": props.get("count"),
                    "lat": lat,
                    "lng": lng,
                })
        truncated = len(out) > limit
        return {"ok": True, "data": {"results": out[:limit], "version": self._version(), "truncated": truncated}}

    def _cmd_brief_area(self, args: dict[str, Any]) -> dict[str, Any]:
        lat, lng = _coerce_float(args.get("lat")), _coerce_float(
            args.get("lng") if args.get("lng") is not None else args.get("lon")
        )
        if lat is None or lng is None:
            return {"ok": False, "detail": "lat and lng required"}
        radius_km = _coerce_float(args.get("radius_km")) or 50.0
        nearby = self._cmd_entities_near({
            "lat": lat, "lng": lng, "radius_km": radius_km,
            "entity_types": args.get("entity_types"), "limit": args.get("limit", 25),
        })["data"]
        topic = str(args.get("query") or args.get("topic") or "").strip()
        news = (self._cmd_search_news({"query": topic, "limit": 10})["data"]
                if topic else {"results": [], "truncated": False})
        context = self._cmd_entities_near({
            "lat": lat, "lng": lng, "radius_km": max(radius_km, 250.0),
            "entity_types": ["earthquakes", "weather_alerts", "internet_outages", "firms_fires", "gdelt", "news"],
            "limit": args.get("context_limit", 15),
        })["data"]
        return {
            "ok": True,
            "data": {
                "center": {"lat": lat, "lng": lng},
                "radius_km": radius_km,
                "nearby": nearby,
                "topic_news": news,
                "context": context,
            },
        }

    def _cmd_get_correlations(self, _args: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "data": {"correlations": self.feed.layer("correlations") or [], "version": self._version()}}

    def _cmd_get_sigint_totals(self, _args: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "data": self.feed.layer("sigint_totals") or {}}

    # -- routing ------------------------------------------------------------

    def _cameras(self) -> list[Any]:
        cameras = self.feed.layer("cctv")
        if not isinstance(cameras, list):
            raise PublicSkillError("The public feed does not publish cameras right now.")
        return cameras

    def _cmd_find_cameras(self, args: dict[str, Any]) -> dict[str, Any]:
        lng = args.get("lng") if args.get("lng") is not None else args.get("lon")
        if _coerce_float(args.get("lat")) is None and _coerce_float(lng) is None and not _norm_text(args.get("query")):
            return {"ok": False, "detail": "lat and lng, or a query, required"}
        found = sb_camera.search_cameras(
            self._cameras(), lat=args.get("lat"), lng=lng, radius_km=args.get("radius_km"),
            query=args.get("query"), media_type=args.get("media_type"), limit=args.get("limit", 10),
        )
        return {"ok": True, "data": {**found, "version": self._version()}}

    def _cmd_camera_snapshot(self, args: dict[str, Any]) -> dict[str, Any]:
        lng = args.get("lng") if args.get("lng") is not None else args.get("lon")
        try:
            camera = sb_camera.pick_camera(
                self._cameras(), camera_id=args.get("id") or args.get("camera_id"), lat=args.get("lat"), lng=lng,
                radius_km=args.get("radius_km"), query=args.get("query"),
            )
            shot = sb_camera.take_snapshot(
                camera, out_dir=args.get("out_dir"), inline=bool(args.get("inline")),
                frame=args.get("frame", True) is not False, allow_local=self.feed.local,
            )
        except sb_camera.CameraError as exc:
            return {"ok": False, "detail": str(exc), "public_skill": True}
        return {"ok": True, "data": {**shot, "version": self._version()}}

    def _cmd_route_query(self, args: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "data": route_query(
            str(args.get("text") or args.get("query") or ""),
            lat=_coerce_float(args.get("lat")),
            lng=_coerce_float(args.get("lng")),
            radius_km=_coerce_float(args.get("radius_km")) or 50.0,
        )}

    def _cmd_ask(self, args: dict[str, Any]) -> dict[str, Any]:
        """Route a plain-language question to the best read command and run it."""
        plan = self._cmd_route_query(args)["data"]
        recommended = plan["recommended"]
        result = self.command(recommended["cmd"], recommended["args"])
        return {"ok": bool(result.get("ok")), "data": {"route": plan, "result": result}}

    def _cmd_run_playbook(self, args: dict[str, Any]) -> dict[str, Any]:
        name = _norm_text(args.get("name") or args.get("playbook"))
        batches: dict[str, tuple[str, list[dict[str, Any]]]] = {
            "status_check": ("Feed health + layer counts", [
                {"cmd": "channel_status", "args": {}},
                {"cmd": "get_summary", "args": {}},
            ]),
            "hot_snapshot": ("Summary plus the notable movers", [
                {"cmd": "get_summary", "args": {}},
                {"cmd": "get_layer_slice",
                 "args": {"layers": ["tracked_flights", "military_flights", "earthquakes", "news"],
                          "limit_per_layer": 15}},
            ]),
            "morning_brief": ("Morning digest layers", [
                {"cmd": "get_summary", "args": {}},
                {"cmd": "get_layer_slice",
                 "args": {"layers": ["news", "gdelt", "earthquakes", "military_flights"], "limit_per_layer": 15}},
            ]),
        }
        if name == "area_brief":
            if args.get("lat") is None or args.get("lng") is None:
                return {"ok": False, "detail": "area_brief requires lat and lng"}
            description = "Brief an area of interest"
            batch = [{"cmd": "brief_area", "args": {k: args.get(k) for k in ("lat", "lng", "radius_km", "query")
                                                   if args.get(k) is not None}}]
        elif name in ("track_snapshot", "jet_recon"):
            query = str(args.get("query") or args.get("registration") or args.get("owner") or "").strip()
            if not query:
                return {"ok": False, "detail": f"{name} requires query"}
            description = "Resolve an aircraft or ship to its current position"
            batch = [{"cmd": "find_entity", "args": {"query": query, "entity_type": args.get("entity_type", ""),
                                                    "owner": args.get("owner", ""), "fallback_search": True}}]
        elif name in batches:
            description, batch = batches[name]
        else:
            known = sorted(list(batches) + ["area_brief", "track_snapshot", "jet_recon"])
            return {"ok": False, "detail": f"unknown playbook: {name}", "known": known}
        results = [{"cmd": item["cmd"], **self.command(item["cmd"], item["args"])} for item in batch]
        return {"ok": True, "data": {"playbook": name, "description": description, "results": results}}


def _news_query(text: str) -> str:
    cleaned = text
    for prefix in ("news about", "news on", "headlines about", "headlines on", "latest on", "search news for"):
        if cleaned.lower().startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
    return cleaned.strip(" ?.")


def route_query(text: str, lat: float | None = None, lng: float | None = None,
                radius_km: float = 50) -> dict[str, Any]:
    """Map a plain-language question to a read command (no LLM), like the app's router."""
    raw = str(text or "").strip()
    lowered = raw.lower()

    def plan(intent: str, cmd: str, args: dict[str, Any], alternates: list[dict[str, Any]] | None = None):
        return {"intent": intent, "recommended": {"cmd": cmd, "args": args}, "alternates": alternates or []}

    stated = RE_RADIUS.search(raw)
    if stated:
        unit = stated.group(2).lower()
        scale = 1.609344 if unit.startswith("mi") else 1.852 if unit in ("nm", "nmi") or unit.startswith("naut") else 1.0
        radius_km = round(float(stated.group(1)) * scale, 2)
        raw = (raw[:stated.start()] + " near " + raw[stated.end():]).strip()
        lowered = raw.lower()

    coords = RE_LATLNG.search(raw)
    if coords and lat is None and lng is None:
        guess_lat, guess_lng = float(coords.group(1)), float(coords.group(2))
        if -90 <= guess_lat <= 90 and -180 <= guess_lng <= 180:
            lat, lng = guess_lat, guess_lng

    if not raw and lat is not None and lng is not None:
        return plan("area_brief", "brief_area", {"lat": lat, "lng": lng, "radius_km": radius_km})
    if not raw:
        return plan("discovery", "get_summary", {}, [{"cmd": "channel_status", "args": {}}])

    mmsi = RE_MMSI.search(raw)
    if mmsi and any(k in lowered for k in ("mmsi", "ship", "vessel", "yacht", "boat", "maritime")):
        return plan("maritime_identifier", "find_entity", {"mmsi": mmsi.group(0), "entity_type": "ship"})

    n_number = RE_N_NUMBER.search(raw)
    if n_number:
        reg = n_number.group(0).upper()
        return plan("tail_number", "find_entity", {"registration": reg, "entity_type": "aircraft"},
                    [{"cmd": "find_flights", "args": {"registration": reg}}])

    if lat is not None and lng is not None and any(
        k in lowered for k in ("near", "around", "within", "radius", "brief", "close to", "at ", *CAMERA_WORDS)
    ):
        types = None
        if any(k in lowered for k in ("ship", "vessel", "boat", "maritime")):
            types = ["ships"]
        elif any(k in lowered for k in ("plane", "flight", "aircraft", "jet")):
            types = ["tracked_flights", "military_flights", "private_jets", "private_flights", "commercial_flights"]
        elif any(k in lowered for k in CAMERA_WORDS):
            look = any(k in lowered for k in LOOK_WORDS)
            return plan("camera_look" if look else "camera_search",
                        "camera_snapshot" if look else "find_cameras",
                        {"lat": lat, "lng": lng, "radius_km": min(radius_km, 25.0)},
                        [{"cmd": "find_cameras", "args": {"lat": lat, "lng": lng, "radius_km": radius_km}}])
        if types:
            return plan("nearby_entities", "entities_near",
                        {"lat": lat, "lng": lng, "radius_km": radius_km, "entity_types": types})
        return plan("area_brief", "brief_area", {"lat": lat, "lng": lng, "radius_km": radius_km})

    if any(k in lowered for k in CAMERA_WORDS):
        subject = re.sub(r"[^a-z0-9 ]+", " ", lowered)
        for word in (*CAMERA_WORDS, *LOOK_WORDS, "cameras", "cams", "find", "list", "the", "a", "of", "on", "in",
                     "at", "near", "around", "from", "any", "me", "what", "is", "are", "there", "live", "traffic"):
            subject = re.sub(rf"\b{re.escape(word)}\b", " ", subject)
        return plan("camera_search", "find_cameras", {"query": " ".join(subject.split()), "limit": 10})

    if any(k in lowered for k in ("news", "headline", "headlines", "gdelt", "happening")):
        return plan("news_search", "search_news", {"query": _news_query(raw), "limit": 10})

    if any(k in lowered for k in ("summary", "status", "layers populated", "what data", "what changed", "updates")):
        return plan("discovery", "get_summary", {}, [{"cmd": "channel_status", "args": {}}])

    for token in re.findall(r"\b[A-Z0-9]{2,8}\b", raw):
        if RE_CALLSIGN.fullmatch(token):
            return plan("callsign", "find_entity", {"callsign": token, "entity_type": "aircraft"},
                        [{"cmd": "find_flights", "args": {"callsign": token}}])

    entity_type = ""
    if any(k in lowered for k in ("ship", "vessel", "yacht", "boat", "maritime", "carrier")):
        entity_type = "ship"
    elif any(k in lowered for k in ("jet", "plane", "flight", "aircraft", "helicopter", "tail")):
        entity_type = "aircraft"
    subject = raw
    for phrase in ("where is", "where's", "find", "track", "locate", "show me", "the", "jet", "yacht", "plane",
                   "flight", "ship", "vessel", "boat", "aircraft", "right now", "now", "currently", "at"):
        subject = re.sub(rf"\b{re.escape(phrase)}\b", " ", subject, flags=re.I)
    subject = re.sub(r"[?'’]s\b|[?.!]", " ", subject)
    subject = " ".join(subject.split())
    args: dict[str, Any] = {"query": subject or raw, "fallback_search": True}
    if entity_type:
        args["entity_type"] = entity_type
    return plan("entity_lookup", "find_entity", args,
                [{"cmd": "search_news", "args": {"query": subject or raw, "limit": 10}}])


# ── Command line ───────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Query the ShadowBroker public feed (read-only).")
    parser.add_argument("--url", default=None, help="public feed address (or set SHADOWBROKER_PUBLIC_URL)")
    sub = parser.add_subparsers(dest="mode", required=True)
    ask = sub.add_parser("ask", help='plain-language question, e.g. ask "where is N189AM"')
    ask.add_argument("text")
    ask.add_argument("--lat", type=float)
    ask.add_argument("--lng", type=float)
    ask.add_argument("--radius-km", type=float, default=50)
    cmd = sub.add_parser("cmd", help="run one command with JSON args")
    cmd.add_argument("name")
    cmd.add_argument("args", nargs="?", default="{}")
    sub.add_parser("status", help="feed health")
    look = sub.add_parser("look", help="save a current picture from a camera: --id, or --lat/--lng for the nearest")
    look.add_argument("--id", default="")
    look.add_argument("--lat", type=float)
    look.add_argument("--lng", type=float)
    look.add_argument("--radius-km", type=float, default=5)
    look.add_argument("--out-dir", default=None)
    options = parser.parse_args(argv)
    try:
        client = ShadowBrokerPublicClient(base_url=options.url)
        if options.mode == "ask":
            result = client.command(
                "ask", {"text": options.text, "lat": options.lat, "lng": options.lng, "radius_km": options.radius_km}
            )
        elif options.mode == "status":
            result = client.command("channel_status")
        elif options.mode == "look":
            result = client.command("camera_snapshot", {
                "id": options.id, "lat": options.lat, "lng": options.lng, "radius_km": options.radius_km,
                "out_dir": options.out_dir,
            })
        else:
            result = client.command(options.name, json.loads(options.args))
    except PublicSkillError as exc:
        result = {"ok": False, "detail": str(exc), "public_skill": True}
    except ValueError as exc:
        result = {"ok": False, "detail": f"bad JSON args: {exc}"}
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
