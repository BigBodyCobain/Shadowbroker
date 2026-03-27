"""
Emergent Intelligence — Cross-layer correlation engine.

Scans co-located events across multiple data layers and emits composite
alerts that no single source could generate alone.

Correlation types:
  - RF Anomaly:          GPS jamming + internet outage (both required)
  - Military Buildup:    Military flights + naval vessels + GDELT conflict events
  - Infrastructure Cascade: Internet outage + KiwiSDR offline in same zone
"""

import logging
from collections import defaultdict

logger = logging.getLogger(__name__)

# Grid cell size in degrees — 1° ≈ 111 km at equator.
# Tighter than the previous 2° to reduce false co-locations.
_CELL_SIZE = 1

# Quality gates for RF anomaly correlation — only high-confidence inputs.
# GPS jamming + internet outage overlap in a 111km cell is easily a coincidence
# (IODA returns ~100 regional outages; GPS NACp dips are common in busy airspace).
# Only fire when the evidence is strong enough to indicate deliberate RF interference.
_RF_CORR_MIN_GPS_RATIO = 0.60   # Need strong jamming signal, not marginal NACp dips
_RF_CORR_MIN_OUTAGE_PCT = 40    # Need a serious outage, not routine BGP fluctuation
_RF_CORR_MIN_INDICATORS = 3     # Require 3+ corroborating signals (not just GPS+outage)


def _cell_key(lat: float, lng: float) -> str:
    """Convert lat/lng to a grid cell key."""
    clat = int(lat // _CELL_SIZE) * _CELL_SIZE
    clng = int(lng // _CELL_SIZE) * _CELL_SIZE
    return f"{clat},{clng}"


def _cell_center(key: str) -> tuple[float, float]:
    """Get center lat/lng from a cell key."""
    parts = key.split(",")
    return float(parts[0]) + _CELL_SIZE / 2, float(parts[1]) + _CELL_SIZE / 2


def _severity(indicator_count: int) -> str:
    if indicator_count >= 3:
        return "high"
    if indicator_count >= 2:
        return "medium"
    return "low"


def _severity_score(sev: str) -> float:
    return {"high": 90, "medium": 60, "low": 30}.get(sev, 0)


def _outage_pct(outage: dict) -> float:
    """Extract outage severity percentage from an outage dict."""
    return float(outage.get("severity", 0) or outage.get("severity_pct", 0) or 0)


# ---------------------------------------------------------------------------
# RF Anomaly: GPS jamming + internet outage (both must be present)
# ---------------------------------------------------------------------------


def _detect_rf_anomalies(data: dict) -> list[dict]:
    gps_jamming = data.get("gps_jamming") or []
    internet_outages = data.get("internet_outages") or []

    if not gps_jamming:
        return []  # No GPS jamming → no RF anomalies possible

    # Build grid of indicators
    cells: dict[str, dict] = defaultdict(lambda: {
        "gps_jam": False, "gps_ratio": 0.0,
        "outage": False, "outage_pct": 0.0,
    })

    for z in gps_jamming:
        lat, lng = z.get("lat"), z.get("lng")
        if lat is None or lng is None:
            continue
        ratio = z.get("ratio", 0)
        if ratio < _RF_CORR_MIN_GPS_RATIO:
            continue  # Skip marginal jamming zones
        key = _cell_key(lat, lng)
        cells[key]["gps_jam"] = True
        cells[key]["gps_ratio"] = max(cells[key]["gps_ratio"], ratio)

    for o in internet_outages:
        lat = o.get("lat") or o.get("latitude")
        lng = o.get("lng") or o.get("lon") or o.get("longitude")
        if lat is None or lng is None:
            continue
        pct = _outage_pct(o)
        if pct < _RF_CORR_MIN_OUTAGE_PCT:
            continue  # Skip minor outages (ISP maintenance noise)
        key = _cell_key(float(lat), float(lng))
        cells[key]["outage"] = True
        cells[key]["outage_pct"] = max(cells[key]["outage_pct"], pct)

    # PSK Reporter: presence = healthy RF.  Only used as a bonus indicator,
    # NOT as a standalone trigger (absence is normal in most cells).
    psk_reporter = data.get("psk_reporter") or []
    psk_cells: set[str] = set()
    for s in psk_reporter:
        lat, lng = s.get("lat"), s.get("lon")
        if lat is not None and lng is not None:
            psk_cells.add(_cell_key(lat, lng))

    # When PSK data is unavailable, we can't get a 3rd indicator, so require
    # an even higher GPS jamming ratio to compensate (real EW shows 75%+).
    psk_available = len(psk_reporter) > 0

    alerts: list[dict] = []
    for key, c in cells.items():
        # GPS jamming is the anchor — required for every RF anomaly alert
        if not c["gps_jam"]:
            continue
        if not c["outage"]:
            continue  # Both GPS jamming AND outage are always required

        indicators = 2  # GPS jamming + outage
        drivers: list[str] = [f"GPS jamming {int(c['gps_ratio'] * 100)}%"]
        pct = c["outage_pct"]
        drivers.append(f"Internet outage{f' {pct:.0f}%' if pct else ''}")

        # PSK absence confirms RF environment is disrupted
        if psk_available and key not in psk_cells:
            indicators += 1
            drivers.append("No HF digital activity (PSK Reporter)")

        if indicators < _RF_CORR_MIN_INDICATORS:
            # Without PSK data, only allow through if GPS ratio is extreme
            # (75%+ indicates deliberate, sustained jamming — not noise)
            if not psk_available and c["gps_ratio"] >= 0.75 and pct >= 50:
                pass  # Allow this high-confidence 2-indicator alert through
            else:
                continue

        lat, lng = _cell_center(key)
        sev = _severity(indicators)
        alerts.append({
            "lat": lat,
            "lng": lng,
            "type": "rf_anomaly",
            "severity": sev,
            "score": _severity_score(sev),
            "drivers": drivers[:3],
            "cell_size": _CELL_SIZE,
        })

    return alerts


# ---------------------------------------------------------------------------
# Military Buildup: flights + ships + GDELT conflict
# ---------------------------------------------------------------------------


def _detect_military_buildups(data: dict) -> list[dict]:
    mil_flights = data.get("military_flights") or []
    ships = data.get("ships") or []
    gdelt = data.get("gdelt") or []

    cells: dict[str, dict] = defaultdict(lambda: {
        "mil_flights": 0, "mil_ships": 0, "gdelt_events": 0,
    })

    for f in mil_flights:
        lat = f.get("lat") or f.get("latitude")
        lng = f.get("lng") or f.get("lon") or f.get("longitude")
        if lat is None or lng is None:
            continue
        try:
            key = _cell_key(float(lat), float(lng))
            cells[key]["mil_flights"] += 1
        except (ValueError, TypeError):
            continue

    mil_ship_types = {"military_vessel", "military", "warship", "patrol", "destroyer",
                      "frigate", "corvette", "carrier", "submarine", "cruiser"}
    for s in ships:
        stype = (s.get("type") or s.get("ship_type") or "").lower()
        if not any(mt in stype for mt in mil_ship_types):
            continue
        lat = s.get("lat") or s.get("latitude")
        lng = s.get("lng") or s.get("lon") or s.get("longitude")
        if lat is None or lng is None:
            continue
        try:
            key = _cell_key(float(lat), float(lng))
            cells[key]["mil_ships"] += 1
        except (ValueError, TypeError):
            continue

    for g in gdelt:
        lat = g.get("lat") or g.get("latitude") or g.get("actionGeo_Lat")
        lng = g.get("lng") or g.get("lon") or g.get("longitude") or g.get("actionGeo_Long")
        if lat is None or lng is None:
            continue
        try:
            key = _cell_key(float(lat), float(lng))
            cells[key]["gdelt_events"] += 1
        except (ValueError, TypeError):
            continue

    alerts: list[dict] = []
    for key, c in cells.items():
        mil_total = c["mil_flights"] + c["mil_ships"]
        has_gdelt = c["gdelt_events"] > 0

        # Need meaningful military presence AND a conflict indicator
        if mil_total < 3 or not has_gdelt:
            continue

        drivers: list[str] = []
        if c["mil_flights"]:
            drivers.append(f"{c['mil_flights']} military aircraft")
        if c["mil_ships"]:
            drivers.append(f"{c['mil_ships']} military vessels")
        if c["gdelt_events"]:
            drivers.append(f"{c['gdelt_events']} conflict events")

        if mil_total >= 11:
            sev = "high"
        elif mil_total >= 6:
            sev = "medium"
        else:
            sev = "low"

        lat, lng = _cell_center(key)
        alerts.append({
            "lat": lat,
            "lng": lng,
            "type": "military_buildup",
            "severity": sev,
            "score": _severity_score(sev),
            "drivers": drivers[:3],
            "cell_size": _CELL_SIZE,
        })

    return alerts


# ---------------------------------------------------------------------------
# Infrastructure Cascade: outage + KiwiSDR co-location
#
# Power plants are removed from this detector — with 35K plants globally,
# virtually every 2° cell contains one, making every outage a false hit.
# KiwiSDR receivers (~300 worldwide) are sparse enough to be meaningful:
# an outage in the same cell as a KiwiSDR indicates real infrastructure
# disruption affecting radio monitoring capability.
# ---------------------------------------------------------------------------


def _detect_infra_cascades(data: dict) -> list[dict]:
    internet_outages = data.get("internet_outages") or []
    kiwisdr = data.get("kiwisdr") or []

    if not kiwisdr:
        return []

    # Build set of cells with KiwiSDR receivers
    kiwi_cells: set[str] = set()
    for k in kiwisdr:
        lat, lng = k.get("lat"), k.get("lon") or k.get("lng")
        if lat is not None and lng is not None:
            try:
                kiwi_cells.add(_cell_key(float(lat), float(lng)))
            except (ValueError, TypeError):
                pass

    if not kiwi_cells:
        return []

    alerts: list[dict] = []
    for o in internet_outages:
        lat = o.get("lat") or o.get("latitude")
        lng = o.get("lng") or o.get("lon") or o.get("longitude")
        if lat is None or lng is None:
            continue
        try:
            key = _cell_key(float(lat), float(lng))
        except (ValueError, TypeError):
            continue

        if key not in kiwi_cells:
            continue

        pct = _outage_pct(o)
        drivers = [f"Internet outage{f' {pct:.0f}%' if pct else ''}",
                    "KiwiSDR receivers in affected zone"]

        lat_c, lng_c = _cell_center(key)
        alerts.append({
            "lat": lat_c,
            "lng": lng_c,
            "type": "infra_cascade",
            "severity": "medium",
            "score": _severity_score("medium"),
            "drivers": drivers,
            "cell_size": _CELL_SIZE,
        })

    return alerts


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_correlations(data: dict) -> list[dict]:
    """Run all correlation detectors and return merged alert list."""
    alerts: list[dict] = []

    try:
        alerts.extend(_detect_rf_anomalies(data))
    except Exception as e:
        logger.error("Correlation engine RF anomaly error: %s", e)

    try:
        alerts.extend(_detect_military_buildups(data))
    except Exception as e:
        logger.error("Correlation engine military buildup error: %s", e)

    try:
        alerts.extend(_detect_infra_cascades(data))
    except Exception as e:
        logger.error("Correlation engine infra cascade error: %s", e)

    rf = sum(1 for a in alerts if a["type"] == "rf_anomaly")
    mil = sum(1 for a in alerts if a["type"] == "military_buildup")
    infra = sum(1 for a in alerts if a["type"] == "infra_cascade")
    if alerts:
        logger.info(
            "Correlations: %d alerts (%d rf, %d mil, %d infra)",
            len(alerts), rf, mil, infra,
        )

    return alerts
