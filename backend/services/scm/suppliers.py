"""SCM supplier risk overlay (Osiris port, uses in-memory dashboard data)."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from services.fetchers._store import _data_lock, _mark_fresh, get_latest_data_subset_refs, is_any_active, latest_data
from services.network_utils import fetch_with_curl

SUPPLIERS: list[dict[str, Any]] = [
    {"id": "sup-tsmc-hsinchu", "name": "TSMC Fab 12 (Tier 1)", "city": "Hsinchu", "country": "Taiwan", "lat": 24.774, "lng": 120.992, "category": "Semiconductor"},
    {"id": "sup-tsmc-tainan", "name": "TSMC Fab 14 (Tier 1)", "city": "Tainan", "country": "Taiwan", "lat": 23.111, "lng": 120.273, "category": "Semiconductor"},
    {"id": "sup-sec-giheung", "name": "Samsung Electronics (Tier 1)", "city": "Giheung", "country": "South Korea", "lat": 37.221, "lng": 127.098, "category": "Semiconductor"},
    {"id": "sup-sk-icheon", "name": "SK Hynix (Tier 1)", "city": "Icheon", "country": "South Korea", "lat": 37.256, "lng": 127.483, "category": "Semiconductor"},
    {"id": "sup-sony-kumamoto", "name": "Sony Semiconductor (Tier 2)", "city": "Kikuyo", "country": "Japan", "lat": 32.883, "lng": 130.825, "category": "Electronics"},
    {"id": "sup-mlcc-murata", "name": "Murata MLCC (Tier 2)", "city": "Izumo", "country": "Japan", "lat": 35.361, "lng": 132.756, "category": "Electronics"},
    {"id": "sup-bosch-stuttgart", "name": "Bosch Auto Parts (Tier 1)", "city": "Stuttgart", "country": "Germany", "lat": 48.815, "lng": 9.176, "category": "Automotive"},
    {"id": "sup-zf-bavaria", "name": "ZF Friedrichshafen (Tier 1)", "city": "Friedrichshafen", "country": "Germany", "lat": 47.662, "lng": 9.489, "category": "Automotive"},
    {"id": "sup-valeo-paris", "name": "Valeo R&D (Tier 2)", "city": "Paris", "country": "France", "lat": 48.878, "lng": 2.308, "category": "Automotive"},
    {"id": "sup-magna-celaya", "name": "Magna Assembly (Tier 2)", "city": "Celaya", "country": "Mexico", "lat": 20.525, "lng": -100.814, "category": "Automotive"},
    {"id": "sup-denso-monterrey", "name": "Denso Corp (Tier 1)", "city": "Monterrey", "country": "Mexico", "lat": 25.772, "lng": -100.174, "category": "Automotive"},
    {"id": "sup-catl-ningde", "name": "CATL Battery HQ (Tier 1)", "city": "Ningde", "country": "China", "lat": 26.666, "lng": 119.544, "category": "Battery"},
    {"id": "sup-byd-shenzhen", "name": "BYD Gigafactory (Tier 1)", "city": "Shenzhen", "country": "China", "lat": 22.684, "lng": 114.341, "category": "Battery"},
    {"id": "sup-panasonic-nevada", "name": "Panasonic Giga (Tier 1)", "city": "Sparks", "country": "US", "lat": 39.539, "lng": -119.439, "category": "Battery"},
]


def _distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    dx = (lng1 - lng2) * math.cos(math.radians((lat1 + lat2) / 2))
    dy = lat1 - lat2
    return math.sqrt(dx * dx + dy * dy) * 111.32


def _seismic_risk_level(distance_km: float, magnitude: float) -> str | None:
    """Meaningful fab impact only — ignore routine micro-quakes (e.g. Taiwan M3.x)."""
    if magnitude < 4.5:
        return None
    if magnitude >= 6.0 and distance_km <= 200:
        return "CRITICAL"
    if magnitude >= 5.5 and distance_km <= 75:
        return "CRITICAL"
    if magnitude >= 5.0 and distance_km <= 100:
        return "HIGH"
    if magnitude >= 4.5 and distance_km <= 40:
        return "HIGH"
    return None


def _apply_seismic_threats(suppliers: list[dict[str, Any]], earthquakes: list[dict[str, Any]]) -> None:
    for sup in suppliers:
        best: tuple[str, float] | None = None
        for eq in earthquakes:
            lat = eq.get("lat")
            lng = eq.get("lng") or eq.get("lon")
            mag = float(eq.get("mag") or eq.get("magnitude") or 0)
            if lat is None or lng is None or mag < 4.5:
                continue
            dist = _distance_km(sup["lat"], sup["lng"], float(lat), float(lng))
            level = _seismic_risk_level(dist, mag)
            if not level:
                continue
            severity = {"HIGH": 1, "CRITICAL": 2}
            if best is None:
                best = (level, mag)
            else:
                cur = severity[level]
                prev = severity[best[0]]
                if cur > prev or (cur == prev and mag > best[1]):
                    best = (level, mag)
        if best:
            level, mag = best
            if sup["risk_level"] == "NORMAL" or (
                level == "CRITICAL" and sup["risk_level"] != "CRITICAL"
            ):
                sup["risk_level"] = level
            elif level == "CRITICAL" and sup["risk_level"] == "HIGH":
                sup["risk_level"] = "CRITICAL"
            sup["active_threats"].append(f"SEISMIC PROXIMITY (M{mag:.1f})")


def build_scm_payload() -> dict[str, Any]:
    suppliers = [{**s, "risk_level": "NORMAL", "active_threats": []} for s in SUPPLIERS]
    refs = get_latest_data_subset_refs("earthquakes", "firms_fires", "gdelt")

    earthquakes = refs.get("earthquakes") or []
    _apply_seismic_threats(suppliers, earthquakes)

    fires = refs.get("firms_fires") or []
    for sup in suppliers:
        count = 0
        for fire in fires:
            lat = fire.get("lat") or fire.get("latitude")
            lng = fire.get("lng") or fire.get("lon") or fire.get("longitude")
            if lat is None or lng is None:
                continue
            if _distance_km(sup["lat"], sup["lng"], float(lat), float(lng)) < 50:
                count += 1
        if count:
            if sup["risk_level"] == "NORMAL":
                sup["risk_level"] = "HIGH"
            sup["active_threats"].append(f"WILDFIRE PROXIMITY ({count} hotspots)")

    conflicts = refs.get("gdelt") or []
    for sup in suppliers:
        for event in conflicts:
            lat = event.get("lat")
            lng = event.get("lng") or event.get("lon")
            if lat is None or lng is None:
                continue
            if _distance_km(sup["lat"], sup["lng"], float(lat), float(lng)) < 100:
                sup["risk_level"] = "CRITICAL"
                sup["active_threats"].append("ARMED CONFLICT / RIOT")
                break

    # USGS fallback if earthquakes empty
    if not earthquakes:
        try:
            resp = fetch_with_curl(
                "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.geojson",
                timeout=5,
            )
            if resp.status_code == 200:
                features = resp.json().get("features") or []
                usgs_quakes = [
                    {
                        "lat": f.get("geometry", {}).get("coordinates", [None, None])[1],
                        "lng": f.get("geometry", {}).get("coordinates", [None, None])[0],
                        "mag": f.get("properties", {}).get("mag") or 0,
                    }
                    for f in features
                    if len(f.get("geometry", {}).get("coordinates") or []) >= 2
                ]
                _apply_seismic_threats(suppliers, usgs_quakes)
        except Exception:
            pass

    critical = sum(1 for s in suppliers if s["risk_level"] == "CRITICAL")
    return {
        "suppliers": suppliers,
        "total": len(suppliers),
        "critical_count": critical,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def fetch_scm_suppliers() -> dict[str, Any]:
    if not is_any_active("scm_suppliers"):
        return latest_data.get("scm_suppliers") or {}
    payload = build_scm_payload()
    with _data_lock:
        latest_data["scm_suppliers"] = payload
    _mark_fresh("scm_suppliers")
    return payload
