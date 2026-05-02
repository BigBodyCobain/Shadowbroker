"""ShadowBroker autonomous monitoring agent — heartbeat & anomaly detection.

Runs on OpenClaw's scheduling system. On each heartbeat:
  1. Pull telemetry from ShadowBroker
  2. Run anomaly detection (new military activity, geofence breaches, etc.)
  3. Take time-machine snapshots at configured intervals
  4. Send alerts via the configured channel (Discord, Telegram, etc.)

Usage (in OpenClaw skill config):
    heartbeat_interval: 60  # seconds
    heartbeat_handler: sb_monitor.heartbeat
"""

import time
import json
import math
import os
from typing import Any, Optional
from sb_signatures import sig


# ---------------------------------------------------------------------------
# Persistent state (survives across heartbeats via OpenClaw memory)
# ---------------------------------------------------------------------------

class MonitorState:
    """Track state between heartbeats for anomaly detection."""

    def __init__(self):
        self.last_mil_count: int = 0
        self.last_ship_count: int = 0
        self.last_quake_count: int = 0
        self.last_liveuamap_count: int = 0
        self.last_crowdthreat_count: int = 0
        self.last_uap_count: int = 0
        self.last_fire_count: int = 0
        self.last_jamming_count: int = 0
        self.last_wastewater_alert_count: int = 0
        self.last_check: float = 0
        self.geofences: list[dict] = []
        self.known_entities: set[str] = set()
        self.timemachine_config: dict = {
            "preset": "active",
            "high_freq": {
                "interval_minutes": 15,
                "layers": [
                    "military_flights", "ships", "satellites",
                    "tracked_flights", "private_jets",
                    "liveuamap", "gps_jamming",
                ],
                "last_snapshot": 0,
            },
            "standard": {
                "interval_minutes": 120,
                "layers": [
                    "gdelt", "news", "earthquakes", "weather_alerts",
                    "sigint", "correlations", "crowdthreat",
                    "prediction_markets", "firms_fires",
                    "uap_sightings", "wastewater", "air_quality",
                    "volcanoes", "cctv",
                ],
                "last_snapshot": 0,
            },
        }
        self.snapshots: list[dict] = []  # [{timestamp, profile, data}]
        self.max_snapshots: int = 672  # 7 days @ 15min

    def to_dict(self) -> dict:
        return {
            "last_mil_count": self.last_mil_count,
            "last_ship_count": self.last_ship_count,
            "last_quake_count": self.last_quake_count,
            "last_liveuamap_count": self.last_liveuamap_count,
            "last_crowdthreat_count": self.last_crowdthreat_count,
            "last_uap_count": self.last_uap_count,
            "last_fire_count": self.last_fire_count,
            "last_jamming_count": self.last_jamming_count,
            "last_wastewater_alert_count": self.last_wastewater_alert_count,
            "last_check": self.last_check,
            "geofences": self.geofences,
            "known_entities": list(self.known_entities),
            "timemachine_config": self.timemachine_config,
            "snapshot_count": len(self.snapshots),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MonitorState":
        state = cls()
        state.last_mil_count = data.get("last_mil_count", 0)
        state.last_ship_count = data.get("last_ship_count", 0)
        state.last_quake_count = data.get("last_quake_count", 0)
        state.last_liveuamap_count = data.get("last_liveuamap_count", 0)
        state.last_crowdthreat_count = data.get("last_crowdthreat_count", 0)
        state.last_uap_count = data.get("last_uap_count", 0)
        state.last_fire_count = data.get("last_fire_count", 0)
        state.last_jamming_count = data.get("last_jamming_count", 0)
        state.last_wastewater_alert_count = data.get("last_wastewater_alert_count", 0)
        state.last_check = data.get("last_check", 0)
        state.geofences = data.get("geofences", [])
        state.known_entities = set(data.get("known_entities", []))
        state.timemachine_config = data.get("timemachine_config", state.timemachine_config)
        return state


# Global state instance
_state = MonitorState()


# ---------------------------------------------------------------------------
# Anomaly detection
# ---------------------------------------------------------------------------

def detect_anomalies(current_data: dict, state: MonitorState) -> list[dict]:
    """Compare current telemetry against previous state, flag anomalies."""
    alerts = []
    now = time.time()

    # ── Military flight count spike ──
    mil = current_data.get("military_flights", [])
    mil_count = len(mil)
    if state.last_mil_count > 0:
        increase = mil_count - state.last_mil_count
        pct = (increase / max(state.last_mil_count, 1)) * 100
        if pct > 25 and increase >= 3:
            alerts.append({
                "type": "military_surge",
                "description": f"Military aircraft count surged {increase} "
                               f"({pct:.0f}%) in the last check",
                "count": mil_count,
                "previous": state.last_mil_count,
                "severity": "high" if pct > 50 else "medium",
            })
    state.last_mil_count = mil_count

    # ── Ship count change ──
    ships = current_data.get("ships", [])
    state.last_ship_count = len(ships)

    # ── Earthquake detection ──
    quakes = current_data.get("earthquakes", [])
    quake_count = len(quakes)
    if quake_count > state.last_quake_count:
        new_quakes = quake_count - state.last_quake_count
        for q in quakes[:new_quakes]:
            mag = q.get("magnitude", 0)
            if mag >= 5.0:
                alerts.append({
                    "type": "significant_earthquake",
                    "description": f"M{mag} earthquake detected: {q.get('place', 'Unknown')}",
                    "magnitude": mag,
                    "lat": q.get("lat"),
                    "lng": q.get("lng"),
                    "severity": "critical" if mag >= 7.0 else "high",
                })
    state.last_quake_count = quake_count

    # ── New military callsigns ──
    current_callsigns = {f.get("callsign", "") for f in mil if f.get("callsign")}
    new_mil = current_callsigns - state.known_entities
    if len(new_mil) >= 3:
        alerts.append({
            "type": "new_military_activity",
            "description": f"{len(new_mil)} new military callsigns appeared",
            "callsigns": list(new_mil)[:10],
            "severity": "medium",
        })
    state.known_entities = current_callsigns

    # ── LiveUAMap conflict event surge ──
    liveuamap = current_data.get("liveuamap", [])
    lua_count = len(liveuamap)
    if state.last_liveuamap_count > 0:
        increase = lua_count - state.last_liveuamap_count
        if increase >= 5:
            # Find the most common region in new events
            regions = {}
            for ev in liveuamap[:increase]:
                r = ev.get("region", "Unknown")
                regions[r] = regions.get(r, 0) + 1
            hottest = max(regions, key=regions.get) if regions else "Unknown"
            alerts.append({
                "type": "conflict_surge",
                "description": f"{increase} new conflict events detected "
                               f"(hottest region: {hottest})",
                "count": lua_count,
                "previous": state.last_liveuamap_count,
                "top_region": hottest,
                "severity": "high" if increase >= 10 else "medium",
            })
    state.last_liveuamap_count = lua_count

    # ── CrowdThreat spike ──
    crowd = current_data.get("crowdthreat", [])
    ct_count = len(crowd)
    if state.last_crowdthreat_count > 0:
        increase = ct_count - state.last_crowdthreat_count
        if increase >= 3:
            high_sev = [t for t in crowd[:increase]
                        if str(t.get("severity", "")).lower() in ("high", "critical")]
            alerts.append({
                "type": "crowdthreat_spike",
                "description": f"{increase} new crowd-sourced threats reported"
                               f"{f' ({len(high_sev)} high/critical)' if high_sev else ''}",
                "count": ct_count,
                "previous": state.last_crowdthreat_count,
                "severity": "high" if high_sev else "medium",
            })
    state.last_crowdthreat_count = ct_count

    # ── UAP sighting spike ──
    uap = current_data.get("uap_sightings", [])
    uap_count = len(uap)
    if uap_count > state.last_uap_count:
        increase = uap_count - state.last_uap_count
        if increase >= 3:
            alerts.append({
                "type": "uap_cluster",
                "description": f"{increase} new UAP/UFO sightings reported",
                "count": uap_count,
                "previous": state.last_uap_count,
                "severity": "medium",
            })
    state.last_uap_count = uap_count

    # ── FIRMS fire hotspot surge ──
    fires = current_data.get("firms_fires", [])
    fire_count = len(fires)
    if state.last_fire_count > 0:
        increase = fire_count - state.last_fire_count
        pct = (increase / max(state.last_fire_count, 1)) * 100
        if pct > 30 and increase >= 10:
            alerts.append({
                "type": "fire_surge",
                "description": f"Fire hotspots surged by {increase} ({pct:.0f}%)",
                "count": fire_count,
                "previous": state.last_fire_count,
                "severity": "high" if increase >= 50 else "medium",
            })
    state.last_fire_count = fire_count

    # ── GPS jamming zone changes ──
    jamming = current_data.get("gps_jamming", [])
    jam_count = len(jamming)
    if jam_count > state.last_jamming_count and state.last_jamming_count > 0:
        increase = jam_count - state.last_jamming_count
        if increase >= 1:
            alerts.append({
                "type": "gps_jamming_new",
                "description": f"{increase} new GPS jamming zone(s) detected",
                "count": jam_count,
                "previous": state.last_jamming_count,
                "severity": "high",
            })
    state.last_jamming_count = jam_count

    # ── Wastewater pathogen alerts ──
    ww = current_data.get("wastewater", [])
    ww_alert_count = sum(1 for w in ww if w.get("alert"))
    if ww_alert_count > state.last_wastewater_alert_count:
        increase = ww_alert_count - state.last_wastewater_alert_count
        if increase >= 1:
            alert_plants = [w.get("name", "Unknown") for w in ww if w.get("alert")]
            alerts.append({
                "type": "wastewater_pathogen_alert",
                "description": f"{increase} new wastewater pathogen alert(s): "
                               f"{', '.join(alert_plants[:3])}",
                "count": ww_alert_count,
                "previous": state.last_wastewater_alert_count,
                "plants": alert_plants[:5],
                "severity": "high" if increase >= 3 else "medium",
            })
    state.last_wastewater_alert_count = ww_alert_count

    state.last_check = now
    return alerts


# ---------------------------------------------------------------------------
# Geofence checking
# ---------------------------------------------------------------------------

def _haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in miles."""
    R = 3958.8
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(dlng / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def check_geofences(data: dict, state: MonitorState) -> list[dict]:
    """Check all entities against active geofence zones."""
    breaches = []

    for fence in state.geofences:
        center_lat = fence["lat"]
        center_lng = fence["lng"]
        radius = fence["radius_miles"]
        name = fence.get("name", "Unnamed Zone")
        layers = fence.get("layers", [
            "military_flights", "ships", "liveuamap", "crowdthreat",
            "uap_sightings", "sigint", "gps_jamming",
        ])

        for layer_key in layers:
            entities = data.get(layer_key, [])
            for entity in entities:
                e_lat = entity.get("lat")
                e_lng = entity.get("lon") or entity.get("lng")
                if e_lat is None or e_lng is None:
                    continue

                try:
                    dist = _haversine_miles(
                        center_lat, center_lng,
                        float(e_lat), float(e_lng),
                    )
                except (ValueError, TypeError):
                    continue

                if dist <= radius:
                    entity_id = (
                        entity.get("callsign") or
                        entity.get("name") or
                        entity.get("mmsi") or
                        "Unknown"
                    )
                    breaches.append({
                        "zone": name,
                        "entity": entity_id,
                        "layer": layer_key,
                        "distance_miles": round(dist, 1),
                        "lat": float(e_lat),
                        "lng": float(e_lng),
                        "heading": entity.get("heading"),
                        "speed": entity.get("speed"),
                    })

    return breaches


# ---------------------------------------------------------------------------
# Time Machine — snapshot management
# ---------------------------------------------------------------------------

def should_take_snapshot(profile: str, state: MonitorState) -> bool:
    """Check if it's time for a snapshot based on the configured interval."""
    config = state.timemachine_config.get(profile, {})
    interval = config.get("interval_minutes", 60) * 60  # convert to seconds
    last = config.get("last_snapshot", 0)
    return (time.time() - last) >= interval


def take_snapshot(data: dict, profile: str, state: MonitorState) -> dict:
    """Take a time-machine snapshot of selected layers."""
    config = state.timemachine_config.get(profile, {})
    layers = config.get("layers", [])

    snapshot_data = {}
    for layer in layers:
        layer_data = data.get(layer, [])
        # Only store essentials (positions/identifiers, not full payloads)
        if isinstance(layer_data, list):
            snapshot_data[layer] = len(layer_data)
            # Store first N entity positions for spatial queries
            snapshot_data[f"{layer}_positions"] = [
                {
                    "lat": item.get("lat"),
                    "lng": item.get("lon") or item.get("lng"),
                    "id": (item.get("callsign") or item.get("name") or
                           item.get("mmsi") or item.get("id", "")),
                    "alt": item.get("altitude"),
                    "speed": item.get("speed"),
                    "heading": item.get("heading"),
                }
                for item in layer_data[:200]
                if item.get("lat") is not None
            ]

    snapshot = {
        "timestamp": time.time(),
        "profile": profile,
        "data": snapshot_data,
    }

    # Add to snapshots, enforce max
    state.snapshots.append(snapshot)
    if len(state.snapshots) > state.max_snapshots:
        state.snapshots = state.snapshots[-state.max_snapshots:]

    config["last_snapshot"] = time.time()
    return snapshot


def query_snapshots(
    state: MonitorState,
    hours_ago: float = 0,
    layer: str = "",
) -> list[dict]:
    """Query historical snapshots by time offset and optional layer."""
    if not state.snapshots:
        return []

    target_time = time.time() - (hours_ago * 3600) if hours_ago > 0 else 0

    results = []
    for snap in state.snapshots:
        # Time filter
        if hours_ago > 0:
            # Find nearest to target time
            diff = abs(snap["timestamp"] - target_time)
            if diff > 1800:  # Within 30 min window
                continue

        if layer:
            if layer in snap.get("data", {}):
                results.append(snap)
        else:
            results.append(snap)

    return results


# ---------------------------------------------------------------------------
# Main heartbeat handler
# ---------------------------------------------------------------------------

async def heartbeat(sb_client) -> list[str]:
    """Main heartbeat function — called periodically by OpenClaw scheduler.

    Returns a list of alert messages to send to the user.
    """
    global _state
    messages = []

    try:
        # 1. Pull fresh telemetry (fast + slow merged for full visibility)
        data = await sb_client.get_full_telemetry()

        # 2. Run anomaly detection
        anomalies = detect_anomalies(data, _state)
        for anomaly in anomalies:
            severity = anomaly.get("severity", "medium")
            if severity == "critical":
                prefix = sig("threat")
            elif severity == "high":
                prefix = sig("warning")
            else:
                prefix = sig("anomaly")

            msg = f"{prefix}\n⚡ {anomaly['type'].replace('_', ' ').title()}\n\n"
            msg += f"📄 {anomaly['description']}\n"
            if anomaly.get("lat") and anomaly.get("lng"):
                msg += f"📍 {anomaly['lat']:.4f}°, {anomaly['lng']:.4f}°\n"
            messages.append(msg)

        # 3. Check geofences
        breaches = check_geofences(data, _state)
        for breach in breaches:
            msg = f"{sig('warning')}\n"
            msg += f"⚡ GEOFENCE BREACH: {breach['zone']}\n\n"
            msg += f"🏷️ Entity: {breach['entity']}\n"
            msg += f"📍 Position: {breach['lat']:.4f}°, {breach['lng']:.4f}°\n"
            msg += f"📏 Distance from center: {breach['distance_miles']}mi\n"
            if breach.get("heading"):
                msg += f"🧭 Heading: {breach['heading']}°\n"
            if breach.get("speed"):
                msg += f"⚡ Speed: {breach['speed']}\n"
            messages.append(msg)

        # 4. Time Machine snapshots
        for profile in ["high_freq", "standard"]:
            if should_take_snapshot(profile, _state):
                take_snapshot(data, profile, _state)

    except Exception as e:
        messages.append(f"{sig('error')}\nHeartbeat failed: {e}")

    return messages


# ---------------------------------------------------------------------------
# Geofence management
# ---------------------------------------------------------------------------

def add_geofence(
    name: str,
    lat: float,
    lng: float,
    radius_miles: float,
    layers: Optional[list[str]] = None,
) -> dict:
    """Add a new geofence zone."""
    fence = {
        "name": name,
        "lat": lat,
        "lng": lng,
        "radius_miles": radius_miles,
        "layers": layers or [
            "military_flights", "ships", "liveuamap", "crowdthreat",
            "uap_sightings", "sigint", "gps_jamming",
        ],
        "created_at": time.time(),
    }
    _state.geofences.append(fence)
    return fence


def remove_geofence(name: str) -> bool:
    """Remove a geofence by name."""
    before = len(_state.geofences)
    _state.geofences = [f for f in _state.geofences if f.get("name") != name]
    return len(_state.geofences) < before


def list_geofences() -> list[dict]:
    """List all active geofences."""
    return list(_state.geofences)


# ---------------------------------------------------------------------------
# Custom Feed Scheduler (Power-Up #5)
# ---------------------------------------------------------------------------

class CustomFeed:
    """A user-defined data source that auto-polls and injects into SB layers."""

    def __init__(
        self,
        name: str,
        url: str,
        target_layer: str,
        poll_minutes: int = 15,
        feed_type: str = "auto",  # "rss", "json", "auto"
        transform: str = "",      # jsonpath-like selector for the data array
    ):
        self.name = name
        self.url = url
        self.target_layer = target_layer
        self.poll_minutes = poll_minutes
        self.feed_type = feed_type
        self.transform = transform
        self.last_poll: float = 0
        self.last_count: int = 0
        self.last_error: str = ""
        self.enabled: bool = True

    def should_poll(self) -> bool:
        return self.enabled and (time.time() - self.last_poll) >= (self.poll_minutes * 60)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "url": self.url,
            "target_layer": self.target_layer,
            "poll_minutes": self.poll_minutes,
            "feed_type": self.feed_type,
            "transform": self.transform,
            "last_poll": self.last_poll,
            "last_count": self.last_count,
            "last_error": self.last_error,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CustomFeed":
        feed = cls(
            name=data["name"],
            url=data["url"],
            target_layer=data["target_layer"],
            poll_minutes=data.get("poll_minutes", 15),
            feed_type=data.get("feed_type", "auto"),
            transform=data.get("transform", ""),
        )
        feed.last_poll = data.get("last_poll", 0)
        feed.last_count = data.get("last_count", 0)
        feed.last_error = data.get("last_error", "")
        feed.enabled = data.get("enabled", True)
        return feed


# Custom feeds registry
_custom_feeds: list[CustomFeed] = []


def add_custom_feed(
    name: str,
    url: str,
    target_layer: str,
    poll_minutes: int = 15,
    feed_type: str = "auto",
    transform: str = "",
) -> dict:
    """Register a new custom data feed source.

    Args:
        name: Display name for the feed
        url: URL to poll (RSS, JSON API, etc.)
        target_layer: ShadowBroker layer to inject into (cctv, ships, news, etc.)
        poll_minutes: How often to poll (default 15 min)
        feed_type: "rss", "json", or "auto" (auto-detect)
        transform: JSONPath-like selector for the data array inside JSON responses

    Returns:
        Feed configuration dict
    """
    feed = CustomFeed(name, url, target_layer, poll_minutes, feed_type, transform)
    _custom_feeds.append(feed)
    return feed.to_dict()


def remove_custom_feed(name: str) -> bool:
    """Remove a custom feed by name."""
    global _custom_feeds
    before = len(_custom_feeds)
    _custom_feeds = [f for f in _custom_feeds if f.name != name]
    return len(_custom_feeds) < before


def list_custom_feeds() -> list[dict]:
    """List all registered custom feeds."""
    return [f.to_dict() for f in _custom_feeds]


def toggle_custom_feed(name: str, enabled: bool) -> bool:
    """Enable/disable a custom feed."""
    for f in _custom_feeds:
        if f.name == name:
            f.enabled = enabled
            return True
    return False


async def poll_custom_feeds(sb_client) -> list[str]:
    """Poll all custom feeds that are due and inject data into SB layers.

    Returns list of status messages.
    """
    messages = []

    for feed in _custom_feeds:
        if not feed.should_poll():
            continue

        try:
            items = await _fetch_feed(feed)
            if items:
                result = await sb_client.inject_data(
                    layer=feed.target_layer,
                    items=items,
                    mode="replace",  # replace previous injections from this feed
                )
                feed.last_count = len(items)
                feed.last_error = ""
                messages.append(
                    f"{sig('update')}\n"
                    f"📡 Feed '{feed.name}' polled: {len(items)} items → {feed.target_layer}"
                )
            feed.last_poll = time.time()

        except Exception as e:
            feed.last_error = str(e)
            messages.append(
                f"{sig('warning')}\n"
                f"Feed '{feed.name}' poll failed: {e}"
            )

    return messages


async def _fetch_feed(feed: CustomFeed) -> list[dict]:
    """Fetch and parse a custom feed URL. Returns normalized items."""
    try:
        import httpx
    except ImportError:
        return []

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(feed.url, headers={
            "User-Agent": "ShadowBroker-OSINT/1.0 (custom-feed)",
        })
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")

        # Detect feed type
        feed_type = feed.feed_type
        if feed_type == "auto":
            if "xml" in content_type or "rss" in content_type or "atom" in content_type:
                feed_type = "rss"
            else:
                feed_type = "json"

        if feed_type == "rss":
            return _parse_rss(resp.text, feed)
        else:
            return _parse_json(resp.json(), feed)


def _parse_rss(xml_text: str, feed: CustomFeed) -> list[dict]:
    """Parse an RSS/Atom feed into normalized items."""
    import xml.etree.ElementTree as ET

    items = []
    try:
        root = ET.fromstring(xml_text)

        # RSS 2.0
        for item in root.findall(".//item"):
            title = item.findtext("title", "")
            link = item.findtext("link", "")
            desc = item.findtext("description", "")

            # Try to extract coordinates from georss:point or geo:lat/geo:long
            lat = None
            lng = None
            for ns in ["", "{http://www.georss.org/georss}", "{http://www.w3.org/2003/01/geo/wgs84_pos#}"]:
                point = item.findtext(f"{ns}point")
                if point:
                    parts = point.strip().split()
                    if len(parts) == 2:
                        lat, lng = float(parts[0]), float(parts[1])
                        break
                lat_el = item.findtext(f"{ns}lat")
                lng_el = item.findtext(f"{ns}long") or item.findtext(f"{ns}lng")
                if lat_el and lng_el:
                    lat, lng = float(lat_el), float(lng_el)
                    break

            entry = {
                "title": title,
                "link": link,
                "summary": desc[:200] if desc else "",
                "source": feed.name,
                "_source": f"user:feed:{feed.name}",
            }
            if lat is not None and lng is not None:
                entry["lat"] = lat
                entry["lng"] = lng
            items.append(entry)

        # Atom
        if not items:
            for entry_el in root.findall(".//{http://www.w3.org/2005/Atom}entry"):
                title = entry_el.findtext("{http://www.w3.org/2005/Atom}title", "")
                link_el = entry_el.find("{http://www.w3.org/2005/Atom}link")
                link = link_el.get("href", "") if link_el is not None else ""
                items.append({
                    "title": title,
                    "link": link,
                    "source": feed.name,
                    "_source": f"user:feed:{feed.name}",
                })

    except ET.ParseError:
        pass

    return items[:100]  # cap at 100


def _parse_json(data: Any, feed: CustomFeed) -> list[dict]:
    """Parse a JSON API response into normalized items."""
    # Apply transform path if specified
    items = data
    if feed.transform:
        for key in feed.transform.split("."):
            if isinstance(items, dict):
                items = items.get(key, [])
            elif isinstance(items, list) and key.isdigit():
                idx = int(key)
                items = items[idx] if idx < len(items) else []
            else:
                break

    if not isinstance(items, list):
        items = [items] if isinstance(items, dict) else []

    # Tag each item
    normalized = []
    for item in items[:100]:
        if isinstance(item, dict):
            item["_source"] = f"user:feed:{feed.name}"
            normalized.append(item)

    return normalized


# ---------------------------------------------------------------------------
# Enhanced heartbeat (now includes custom feeds)
# ---------------------------------------------------------------------------

async def heartbeat_with_feeds(sb_client) -> list[str]:
    """Enhanced heartbeat that includes custom feed polling.

    Call this instead of heartbeat() if custom feeds are configured.
    """
    messages = await heartbeat(sb_client)

    # Poll custom feeds
    feed_messages = await poll_custom_feeds(sb_client)
    messages.extend(feed_messages)

    return messages

