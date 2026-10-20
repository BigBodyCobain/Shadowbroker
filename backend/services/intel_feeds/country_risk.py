"""Country risk index (static scores + USGS quake enrichment)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from services.network_utils import fetch_with_curl

RISK_FACTORS: dict[str, dict[str, Any]] = {
    "UA": {"base": 85, "tags": ["active_conflict", "infrastructure_damage"]},
    "RU": {"base": 72, "tags": ["sanctions", "military_mobilization"]},
    "IL": {"base": 78, "tags": ["active_conflict", "regional_instability"]},
    "PS": {"base": 90, "tags": ["active_conflict", "humanitarian_crisis"]},
    "SY": {"base": 82, "tags": ["post_conflict", "infrastructure_damage"]},
    "YE": {"base": 88, "tags": ["active_conflict", "humanitarian_crisis"]},
    "MM": {"base": 76, "tags": ["civil_unrest", "military_junta"]},
    "SD": {"base": 84, "tags": ["active_conflict", "humanitarian_crisis"]},
    "AF": {"base": 80, "tags": ["post_conflict", "governance_collapse"]},
    "KP": {"base": 70, "tags": ["nuclear_risk", "isolation"]},
    "IR": {"base": 68, "tags": ["sanctions", "nuclear_program", "regional_proxy"]},
    "CN": {"base": 35, "tags": ["strategic_competition", "taiwan_tensions"]},
    "TW": {"base": 45, "tags": ["invasion_risk", "semiconductor_dependency"]},
    "VE": {"base": 60, "tags": ["economic_collapse", "political_instability"]},
    "HT": {"base": 85, "tags": ["gang_violence", "governance_collapse"]},
    "LB": {"base": 65, "tags": ["economic_crisis", "political_deadlock"]},
    "PK": {"base": 55, "tags": ["terrorism", "political_instability"]},
    "SO": {"base": 82, "tags": ["terrorism", "state_fragility"]},
    "LY": {"base": 72, "tags": ["divided_government", "militia_control"]},
    "ET": {"base": 62, "tags": ["ethnic_tensions", "regional_conflicts"]},
}

EXCHANGES = [
    {"name": "NYSE", "tz": "America/New_York", "open": 9.5, "close": 16, "country": "US"},
    {"name": "NASDAQ", "tz": "America/New_York", "open": 9.5, "close": 16, "country": "US"},
    {"name": "LSE", "tz": "Europe/London", "open": 8, "close": 16.5, "country": "GB"},
    {"name": "TSE", "tz": "Asia/Tokyo", "open": 9, "close": 15, "country": "JP"},
    {"name": "SSE", "tz": "Asia/Shanghai", "open": 9.5, "close": 15, "country": "CN"},
    {"name": "HKEX", "tz": "Asia/Hong_Kong", "open": 9.5, "close": 16, "country": "HK"},
    {"name": "FRA", "tz": "Europe/Berlin", "open": 8, "close": 20, "country": "DE"},
    {"name": "TSX", "tz": "America/Toronto", "open": 9.5, "close": 16, "country": "CA"},
    {"name": "MOEX", "tz": "Europe/Moscow", "open": 10, "close": 18.5, "country": "RU"},
]


def _exchange_open(ex: dict[str, Any]) -> bool:
    try:
        now = datetime.now(ZoneInfo(ex["tz"]))
        if now.weekday() >= 5:
            return False
        decimal = now.hour + now.minute / 60
        return ex["open"] <= decimal < ex["close"]
    except Exception:
        return False


def build_country_risk_payload() -> dict[str, Any]:
    quake_risks: dict[str, float] = {}
    try:
        resp = fetch_with_curl(
            "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.geojson",
            timeout=5,
        )
        if resp.status_code == 200:
            for f in resp.json().get("features") or []:
                place = (f.get("properties") or {}).get("place") or ""
                mag = (f.get("properties") or {}).get("mag") or 0
                for code in RISK_FACTORS:
                    if code.lower() in place.lower():
                        quake_risks[code] = quake_risks.get(code, 0) + mag
    except Exception:
        pass

    countries = []
    for code, data in RISK_FACTORS.items():
        base = data["base"]
        score = min(100, base + quake_risks.get(code, 0))
        countries.append(
            {
                "code": code,
                "risk_score": score,
                "risk_level": "CRITICAL" if base >= 80 else "HIGH" if base >= 60 else "ELEVATED" if base >= 40 else "LOW",
                "tags": data["tags"],
            }
        )
    countries.sort(key=lambda c: c["risk_score"], reverse=True)
    exchanges = [{"name": e["name"], "country": e["country"], "open": _exchange_open(e)} for e in EXCHANGES]
    return {
        "countries": countries,
        "exchanges": exchanges,
        "open_exchanges": sum(1 for e in exchanges if e["open"]),
        "total_exchanges": len(exchanges),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
