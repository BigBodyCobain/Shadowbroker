"""
Emergent Intelligence — Cross-layer correlation engine.

Scans co-located events across multiple data layers and emits composite
alerts that no single source could generate alone.

Correlation types:
  - RF Anomaly:          GPS jamming + internet outage (both required)
  - Military Buildup:    Military flights + naval vessels + GDELT conflict events
  - Infrastructure Cascade: Internet outage + KiwiSDR offline in same zone
  - Possible Contradiction: Official denial/statement + infrastructure disruption
                            in same region — hypothesis generator, NOT verdict
"""

import logging
import math
import re
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
# Possible Contradiction: official denial/statement + infra disruption
#
# This is a HYPOTHESIS GENERATOR, not a verdict engine.  It says "LOOK HERE"
# when an official statement (denial, clarification, refusal) co-locates with
# infrastructure disruption (internet outage, sigint change).  The human or
# higher-order reasoning decides what actually happened.
#
# Context ratings:
#   STRONG   — denial + outage + prediction market movement in same region
#   MODERATE — denial + outage (no market signal)
#   WEAK     — denial + minor outage or distant co-location
#   DETECTION_GAP — denial found but NO telemetry to verify (equally valuable)
# ---------------------------------------------------------------------------

# Denial / official-statement patterns in headlines and URL slugs
_DENIAL_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r"\bden(?:y|ies|ied|ial)\b",
        r"\brefut(?:e[ds]?|ing)\b",
        r"\breject(?:s|ed|ing)?\b",
        r"\bclarif(?:y|ies|ied|ication)\b",
        r"\bdismiss(?:es|ed|ing)?\b",
        r"\bno\s+attack\b",
        r"\bdid\s+not\s+(?:attack|strike|bomb|target|order|invade|kill)\b",
        r"\bnever\s+(?:attack|strike|bomb|target|order|invade|happen)\b",
        r"\bfalse\s+(?:report|claim|allegation|rumor|narrative)\b",
        r"\bmisinformation\b",
        r"\bdisinformation\b",
        r"\bpropaganda\b",
        r"\b(?:army|military|government|ministry|official)\s+(?:says|clarifies|denies|refutes)\b",
        r"\brumor[s]?\b.*\buntrue\b",
        r"\bcategorically\b",
        r"\bbaseless\b",
    ]
]

# Broader cell radius for sparse telemetry regions (Africa, Central Asia, etc.)
# These regions have fewer IODA/RIPE probes so outage data is sparser
_SPARSE_REGIONS_LAT_RANGES = [
    (-35, 37),   # Africa roughly
    (25, 50),    # Central Asia band (when lng 40-90)
]


def _is_sparse_region(lat: float, lng: float) -> bool:
    """Check if coordinates fall in a region with sparse telemetry coverage."""
    # Africa
    if -35 <= lat <= 37 and -20 <= lng <= 55:
        return True
    # Central Asia
    if 25 <= lat <= 50 and 40 <= lng <= 90:
        return True
    # South America interior
    if -55 <= lat <= 12 and -80 <= lng <= -35:
        return True
    return False


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _matches_denial(text: str) -> bool:
    """Check if text matches any denial/official-statement pattern."""
    return any(p.search(text) for p in _DENIAL_PATTERNS)


def _detect_contradictions(data: dict) -> list[dict]:
    """Detect possible contradictions between official statements and telemetry.

    Scans GDELT headlines for denial language, then checks whether internet
    outages or other infrastructure disruptions exist in the same geographic
    region.  Scores confidence and lists alternative explanations.
    """
    gdelt = data.get("gdelt") or []
    internet_outages = data.get("internet_outages") or []
    news = data.get("news") or []
    prediction_markets = data.get("prediction_markets") or []

    # ── Step 1: Find GDELT events with denial/official-statement language ──
    denial_events: list[dict] = []

    # GDELT comes as GeoJSON features
    gdelt_features = gdelt
    if isinstance(gdelt, dict):
        gdelt_features = gdelt.get("features", [])

    for feature in gdelt_features:
        # Handle both GeoJSON features and flat dicts
        if "properties" in feature and "geometry" in feature:
            props = feature.get("properties", {})
            geom = feature.get("geometry", {})
            coords = geom.get("coordinates", [])
            if len(coords) >= 2:
                lng, lat = float(coords[0]), float(coords[1])
            else:
                continue
            headlines = props.get("_headlines_list", [])
            urls = props.get("_urls_list", [])
            name = props.get("name", "")
            count = props.get("count", 1)
        else:
            lat = feature.get("lat") or feature.get("actionGeo_Lat")
            lng = feature.get("lng") or feature.get("lon") or feature.get("actionGeo_Long")
            if lat is None or lng is None:
                continue
            lat, lng = float(lat), float(lng)
            headlines = [feature.get("title", "")]
            urls = [feature.get("sourceurl", "")]
            name = feature.get("name", "")
            count = 1

        # Check all headlines + URL slugs for denial patterns
        all_text = " ".join(str(h) for h in headlines if h)
        all_text += " " + " ".join(str(u) for u in urls if u)

        if _matches_denial(all_text):
            denial_events.append({
                "lat": lat,
                "lng": lng,
                "headlines": [h for h in headlines if h][:5],
                "urls": [u for u in urls if u][:3],
                "location_name": name,
                "event_count": count,
            })

    # Also scan news articles for denial language
    for article in news:
        title = str(article.get("title", "") or "")
        desc = str(article.get("description", "") or article.get("summary", "") or "")
        if not _matches_denial(title + " " + desc):
            continue
        # News articles often lack coordinates — try to match to GDELT locations
        # For now, only include if we have coordinates
        lat = article.get("lat") or article.get("latitude")
        lng = article.get("lng") or article.get("lon") or article.get("longitude")
        if lat is not None and lng is not None:
            denial_events.append({
                "lat": float(lat),
                "lng": float(lng),
                "headlines": [title],
                "urls": [article.get("url") or article.get("link") or ""],
                "location_name": "",
                "event_count": 1,
            })

    if not denial_events:
        return []

    # ── Step 2: Cross-reference with internet outages ──
    alerts: list[dict] = []

    for denial in denial_events:
        d_lat, d_lng = denial["lat"], denial["lng"]
        sparse = _is_sparse_region(d_lat, d_lng)
        search_radius_km = 1500.0 if sparse else 500.0

        # Find nearby outages
        nearby_outages: list[dict] = []
        for outage in internet_outages:
            o_lat = outage.get("lat") or outage.get("latitude")
            o_lng = outage.get("lng") or outage.get("lon") or outage.get("longitude")
            if o_lat is None or o_lng is None:
                continue
            try:
                dist = _haversine_km(d_lat, d_lng, float(o_lat), float(o_lng))
            except (ValueError, TypeError):
                continue
            if dist <= search_radius_km:
                nearby_outages.append({
                    "region": outage.get("region_name") or outage.get("country_name", ""),
                    "severity": _outage_pct(outage),
                    "distance_km": round(dist, 0),
                    "level": outage.get("level", ""),
                })

        # ── Step 3: Check prediction markets for related movements ──
        denial_text = " ".join(denial["headlines"]).lower()
        related_markets: list[dict] = []
        for market in prediction_markets:
            m_title = str(market.get("title", "") or market.get("question", "") or "").lower()
            # Look for keyword overlap between denial and market
            denial_words = set(re.findall(r"[a-z]{4,}", denial_text))
            market_words = set(re.findall(r"[a-z]{4,}", m_title))
            overlap = denial_words & market_words - {"that", "this", "with", "from", "have", "been", "were", "will", "says", "said"}
            if len(overlap) >= 2:
                prob = market.get("probability") or market.get("lastTradePrice") or market.get("yes_price")
                if prob is not None:
                    related_markets.append({
                        "title": market.get("title") or market.get("question"),
                        "probability": float(prob),
                    })

        # ── Step 4: Score confidence and assign context rating ──
        indicators = 1  # denial itself
        drivers: list[str] = []

        # Primary driver: the denial headline
        headline_display = denial["headlines"][0] if denial["headlines"] else "Official statement"
        if len(headline_display) > 80:
            headline_display = headline_display[:77] + "..."
        drivers.append(f'"{headline_display}"')

        # Outage co-location
        has_outage = False
        if nearby_outages:
            best_outage = max(nearby_outages, key=lambda o: o["severity"])
            if best_outage["severity"] >= 10:
                indicators += 1
                has_outage = True
                drivers.append(
                    f"Internet outage {best_outage['severity']:.0f}% "
                    f"({best_outage['region']}, {best_outage['distance_km']:.0f}km away)"
                )
            elif best_outage["severity"] > 0:
                indicators += 0.5  # minor outage, partial indicator
                has_outage = True
                drivers.append(
                    f"Minor outage ({best_outage['region']}, "
                    f"{best_outage['distance_km']:.0f}km away)"
                )

        # Prediction market signal
        has_market = False
        if related_markets:
            indicators += 1
            has_market = True
            top_market = related_markets[0]
            drivers.append(
                f"Market: \"{top_market['title'][:50]}\" "
                f"at {top_market['probability']:.0%}"
            )

        # Multiple denial sources strengthen the signal
        if denial["event_count"] > 1:
            indicators += 0.5
            drivers.append(f"{denial['event_count']} sources reporting")

        # Context rating
        if has_outage and has_market:
            context = "STRONG"
        elif has_outage:
            context = "MODERATE"
        elif has_market:
            context = "WEAK"  # market signal without infra disruption
        else:
            context = "DETECTION_GAP"

        # Severity mapping
        if context == "STRONG":
            sev = "high"
        elif context == "MODERATE":
            sev = "medium"
        else:
            sev = "low"

        # Alternative explanations (always present — this is a hypothesis generator)
        alternatives: list[str] = []
        if has_outage:
            alternatives.append("Routine infrastructure maintenance or cable damage")
            alternatives.append("Weather-related outage coinciding with news cycle")
        if not has_outage and context == "DETECTION_GAP":
            alternatives.append("Statement may be truthful — no contradicting telemetry found")
            alternatives.append("Telemetry coverage gap in this region")
        alternatives.append("Denial may be responding to social media rumors, not real events")

        lat_c, lng_c = _cell_center(_cell_key(d_lat, d_lng))
        alerts.append({
            "lat": lat_c,
            "lng": lng_c,
            "type": "contradiction",
            "severity": sev,
            "score": _severity_score(sev),
            "drivers": drivers[:4],
            "cell_size": _CELL_SIZE,
            "context": context,
            "alternatives": alternatives[:3],
            "location_name": denial.get("location_name", ""),
            "headlines": denial["headlines"][:3],
            "related_markets": related_markets[:3],
            "nearby_outages": nearby_outages[:5],
        })

    # Deduplicate: keep highest-scored alert per cell
    seen_cells: dict[str, dict] = {}
    for alert in alerts:
        key = _cell_key(alert["lat"], alert["lng"])
        if key not in seen_cells or alert["score"] > seen_cells[key]["score"]:
            seen_cells[key] = alert

    result = list(seen_cells.values())
    if result:
        by_context = defaultdict(int)
        for a in result:
            by_context[a["context"]] += 1
        logger.info(
            "Contradictions: %d possible (%s)",
            len(result),
            ", ".join(f"{v} {k}" for k, v in sorted(by_context.items())),
        )

    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Correlation → Pin bridge
# ---------------------------------------------------------------------------

# Types and their pin categories
_CORR_PIN_CATEGORIES = {
    "rf_anomaly": "anomaly",
    "military_buildup": "military",
    "infra_cascade": "infrastructure",
    "contradiction": "research",
}

# Deduplicate: don't re-pin the same cell within this window (seconds).
_CORR_PIN_DEDUP_WINDOW = 600  # 10 minutes
_recent_corr_pins: dict[str, float] = {}


def _auto_pin_correlations(alerts: list[dict]) -> int:
    """Create AI Intel pins for high-severity correlation alerts.

    Only pins alerts with severity >= medium.  Uses cell-key dedup so the
    same grid cell doesn't get re-pinned every fetch cycle.

    Returns the number of pins created this cycle.
    """
    import time as _time

    now = _time.time()

    # Evict stale dedup entries
    expired = [k for k, ts in _recent_corr_pins.items() if now - ts > _CORR_PIN_DEDUP_WINDOW]
    for k in expired:
        _recent_corr_pins.pop(k, None)

    created = 0
    for alert in alerts:
        sev = alert.get("severity", "low")
        if sev == "low":
            continue  # Don't pin low-severity noise

        lat = alert.get("lat")
        lng = alert.get("lng")
        if lat is None or lng is None:
            continue

        # Dedup key: type + cell
        dedup_key = f"{alert['type']}:{_cell_key(lat, lng)}"
        if dedup_key in _recent_corr_pins:
            continue

        category = _CORR_PIN_CATEGORIES.get(alert["type"], "anomaly")
        drivers = alert.get("drivers", [])
        atype = alert["type"]

        if atype == "contradiction":
            ctx = alert.get("context", "")
            label = f"[{ctx}] Possible Contradiction"
            parts = list(drivers)
            if alert.get("alternatives"):
                parts.append("Alternatives: " + "; ".join(alert["alternatives"][:2]))
            description = " | ".join(parts) if parts else "Narrative contradiction detected"
        else:
            label = f"[{sev.upper()}] {atype.replace('_', ' ').title()}"
            description = "; ".join(drivers) if drivers else "Multi-layer correlation alert"

        try:
            from services.ai_pin_store import create_pin

            meta = {
                "correlation_type": atype,
                "severity": sev,
                "drivers": drivers,
                "cell_size": alert.get("cell_size", _CELL_SIZE),
            }
            # Add contradiction-specific metadata
            if atype == "contradiction":
                meta["context_rating"] = alert.get("context", "")
                meta["alternatives"] = alert.get("alternatives", [])
                meta["headlines"] = alert.get("headlines", [])
                meta["location_name"] = alert.get("location_name", "")
                if alert.get("related_markets"):
                    meta["related_markets"] = alert["related_markets"]

            create_pin(
                lat=lat,
                lng=lng,
                label=label,
                category=category,
                description=description,
                source="correlation_engine",
                confidence=alert.get("score", 60) / 100.0,
                ttl_hours=2.0,  # Auto-expire correlation pins after 2 hours
                metadata=meta,
            )
            _recent_corr_pins[dedup_key] = now
            created += 1
        except Exception as exc:
            logger.warning("Failed to auto-pin correlation: %s", exc)

    if created:
        logger.info("Correlation engine auto-pinned %d alerts", created)
    return created


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

    # Contradiction detection removed from automated engine — too many false
    # positives from regex headline matching.  Contradiction/analysis alerts are
    # now placed by OpenClaw agents via place_analysis_zone, which lets an LLM
    # reason about the evidence rather than pattern-matching keywords.
    try:
        from services.analysis_zone_store import get_live_zones
        alerts.extend(get_live_zones())
    except Exception as e:
        logger.error("Analysis zone merge error: %s", e)

    rf = sum(1 for a in alerts if a["type"] == "rf_anomaly")
    mil = sum(1 for a in alerts if a["type"] == "military_buildup")
    infra = sum(1 for a in alerts if a["type"] == "infra_cascade")
    contra = sum(1 for a in alerts if a["type"] == "contradiction")
    if alerts:
        logger.info(
            "Correlations: %d alerts (%d rf, %d mil, %d infra, %d contra)",
            len(alerts), rf, mil, infra, contra,
        )

    # Correlation alerts are returned in the correlations data feed only.
    # They are NOT auto-pinned to AI Intel — that layer is reserved for
    # user / OpenClaw pins.  Correlations are visualised via the dedicated
    # correlations overlay on the map.

    return alerts
