"""ShadowBroker briefing engine — generates formatted intelligence digests.

Produces branded proximity-based briefings, daily digests, and
anomaly alerts that the user receives via Discord/Telegram/console.

Usage:
    from sb_briefing import format_near_me_digest, format_anomaly_alert
    digest = await format_near_me_digest(lat, lng, radius=100)
"""

from typing import Any, Optional
from sb_signatures import sig


# ---------------------------------------------------------------------------
# Proximity digest
# ---------------------------------------------------------------------------

async def format_near_me_digest(
    sb_client,
    lat: float,
    lng: float,
    radius: float = 100,
) -> str:
    """Generate a branded digest of everything near the user."""
    data = await sb_client.get_near_me(lat, lng, radius)

    lines = [
        sig("near_you"),
        f"📍 Location: {lat:.4f}°, {lng:.4f}°",
        f"📏 Radius: {radius} miles",
        "",
    ]

    # Military flights
    mil = data.get("military_flights", [])
    if mil:
        lines.append(f"✈️ Military Aircraft ({len(mil)}):")
        for f in mil[:5]:
            callsign = f.get("callsign", "Unknown")
            alt = f.get("altitude", "?")
            dist = f.get("distance_miles", "?")
            lines.append(f"  • {callsign} — {dist}mi away, FL{alt}")
        if len(mil) > 5:
            lines.append(f"  ... and {len(mil) - 5} more")
        lines.append("")

    # Ships
    ships = data.get("ships", [])
    if ships:
        lines.append(f"🚢 Vessels ({len(ships)}):")
        for s in ships[:5]:
            name = s.get("name", "Unknown")
            flag = s.get("flag", "?")
            dist = s.get("distance_miles", "?")
            lines.append(f"  • {name} ({flag}) — {dist}mi away")
        if len(ships) > 5:
            lines.append(f"  ... and {len(ships) - 5} more")
        lines.append("")

    # Earthquakes
    quakes = data.get("earthquakes", [])
    if quakes:
        lines.append(f"🌍 Recent Earthquakes ({len(quakes)}):")
        for q in quakes[:3]:
            mag = q.get("magnitude", "?")
            place = q.get("place", "Unknown")
            dist = q.get("distance_miles", "?")
            lines.append(f"  • M{mag} — {place} ({dist}mi away)")
        lines.append("")

    # SIGINT
    sigs = data.get("sigint", [])
    if sigs:
        lines.append(f"📻 SIGINT Nodes ({len(sigs)}):")
        for s in sigs[:5]:
            node_type = s.get("type", "unknown")
            dist = s.get("distance_miles", "?")
            lines.append(f"  • {node_type} node — {dist}mi away")
        lines.append("")

    # GDELT
    gdelt = data.get("gdelt", [])
    if gdelt:
        lines.append(f"📰 Conflict Events ({len(gdelt)}):")
        for g in gdelt[:3]:
            name = g.get("name", "Unknown")
            count = g.get("count", 1)
            dist = g.get("distance_miles", "?")
            lines.append(f"  • {name} ({count} events) — {dist}mi away")
        lines.append("")

    # News
    news = data.get("news", [])
    if news:
        lines.append(f"📰 News ({len(news)}):")
        for n in news[:3]:
            title = n.get("title", "Unknown")
            dist = n.get("distance_miles", "?")
            lines.append(f"  • {title[:80]} — {dist}mi")
        lines.append("")

    # LiveUAMap conflict events
    liveuamap = data.get("liveuamap", [])
    if liveuamap:
        lines.append(f"🔴 Live Conflict Events ({len(liveuamap)}):")
        for ev in liveuamap[:5]:
            title = ev.get("title", "Unknown")
            region = ev.get("region", "")
            dist = ev.get("distance_miles", "?")
            desc = ev.get("description", "")
            category = ev.get("category", "")
            lines.append(f"  • {title} — {dist}mi away")
            if region:
                lines.append(f"    📍 Region: {region}")
            if category:
                lines.append(f"    🏷️ Type: {category}")
            if desc:
                lines.append(f"    📄 {desc[:120]}")
        if len(liveuamap) > 5:
            lines.append(f"  ... and {len(liveuamap) - 5} more")
        lines.append("")

    # CrowdThreat
    crowd = data.get("crowdthreat", [])
    if crowd:
        lines.append(f"⚠️ Crowd-Sourced Threats ({len(crowd)}):")
        for t in crowd[:5]:
            title = t.get("title", "Unknown")
            dist = t.get("distance_miles", "?")
            severity = t.get("severity", "")
            category = t.get("category", "")
            summary = t.get("summary", "")
            verification = t.get("verification", "")
            lines.append(f"  • {title} — {dist}mi away")
            if severity:
                lines.append(f"    🔺 Severity: {severity}")
            if category:
                lines.append(f"    🏷️ Category: {category}")
            if verification:
                lines.append(f"    ✅ Status: {verification}")
            if summary:
                lines.append(f"    📄 {summary[:120]}")
        if len(crowd) > 5:
            lines.append(f"  ... and {len(crowd) - 5} more")
        lines.append("")

    # UAP Sightings (NUFORC enriched)
    uap = data.get("uap_sightings", [])
    if uap:
        lines.append(f"👽 UAP/UFO Sightings ({len(uap)}):")
        for u in uap[:5]:
            location = u.get("location") or u.get("city") or u.get("state") or "Unknown"
            dist = u.get("distance_miles", "?")
            shape = u.get("shape", "")
            duration = u.get("duration", "")
            summary = u.get("summary", "")
            lines.append(f"  • {location} — {dist}mi away")
            if shape:
                lines.append(f"    🔮 Shape: {shape}")
            if duration:
                lines.append(f"    ⏱️ Duration: {duration}")
            if summary:
                lines.append(f"    📄 {summary[:120]}")
        if len(uap) > 5:
            lines.append(f"  ... and {len(uap) - 5} more")
        lines.append("")

    # Wastewater pathogen surveillance
    ww = data.get("wastewater", [])
    if ww:
        alert_ww = [w for w in ww if w.get("alert")]
        if alert_ww:
            lines.append(f"🧬 Wastewater Alerts ({len(alert_ww)} of {len(ww)} plants):")
            for w in alert_ww[:5]:
                name = w.get("name", "Unknown Plant")
                dist = w.get("distance_miles", "?")
                pathogen = w.get("pathogen", "")
                lines.append(f"  • {name} — {dist}mi away")
                if pathogen:
                    lines.append(f"    🦠 Pathogen: {pathogen}")
            if len(alert_ww) > 5:
                lines.append(f"  ... and {len(alert_ww) - 5} more")
            lines.append("")

    # FIRMS Fires
    fires = data.get("firms_fires", [])
    if fires:
        lines.append(f"🔥 Active Fires ({len(fires)}):")
        for f in fires[:5]:
            dist = f.get("distance_miles", "?")
            confidence = f.get("confidence", "")
            brightness = f.get("bright_ti4") or f.get("brightness", "")
            lines.append(f"  • Fire hotspot — {dist}mi away (confidence: {confidence})")
            if brightness:
                lines.append(f"    🌡️ Brightness: {brightness}")
        if len(fires) > 5:
            lines.append(f"  ... and {len(fires) - 5} more")
        lines.append("")

    # GPS Jamming
    jamming = data.get("gps_jamming", [])
    if jamming:
        lines.append(f"📡 GPS Jamming Zones ({len(jamming)}):")
        for j in jamming[:3]:
            dist = j.get("distance_miles", "?")
            name = j.get("name") or j.get("region") or "Unknown"
            lines.append(f"  • {name} — {dist}mi away")
        lines.append("")

    # Weather Alerts
    weather = data.get("weather_alerts", [])
    if weather:
        lines.append(f"🌤️ Weather Alerts ({len(weather)}):")
        for wa in weather[:3]:
            event = wa.get("event") or wa.get("headline") or "Alert"
            dist = wa.get("distance_miles", "?")
            severity_w = wa.get("severity", "")
            lines.append(f"  • {event} — {dist}mi away")
            if severity_w:
                lines.append(f"    ⚠️ Severity: {severity_w}")
        lines.append("")

    # Correlations (no distance — system-wide)
    corr = data.get("correlations", [])
    if corr:
        lines.append(f"⚡ Active Correlations ({len(corr)}):")
        for c in corr[:3]:
            ctype = c.get("type", "unknown").replace("_", " ").title()
            severity_c = c.get("severity", "")
            score = c.get("score", "")
            lines.append(f"  • {ctype} — severity: {severity_c}, score: {score}")
        lines.append("")

    has_data = any([mil, ships, quakes, sigs, gdelt, news, liveuamap, crowd,
                    uap, ww, fires, jamming, weather, corr])
    if not has_data:
        lines.append("🟢 All clear — no notable activity within range.")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Anomaly alert
# ---------------------------------------------------------------------------

def format_anomaly_alert(
    anomaly_type: str,
    description: str,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    details: Optional[dict] = None,
) -> str:
    """Format an anomaly detection alert."""
    lines = [
        sig("anomaly"),
        f"⚡ {anomaly_type}",
        "",
        f"📄 {description}",
    ]

    if lat is not None and lng is not None:
        lines.append(f"📍 Location: {lat:.4f}°, {lng:.4f}°")

    if details:
        lines.append("")
        for k, v in details.items():
            lines.append(f"  {k}: {v}")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Satellite imagery brief
# ---------------------------------------------------------------------------

async def format_satellite_brief(
    sb_client,
    place_name: str,
    count: int = 3,
) -> str:
    """Format a satellite imagery briefing for a location."""
    # Geocode the place name
    try:
        geo = await sb_client.geocode(place_name)
    except Exception:
        return f"{sig('error')}\nGeocoding failed for '{place_name}'"
    if not geo:
        return f"{sig('error')}\nCould not geocode '{place_name}'"

    try:
        lat = float(geo[0].get("lat", 0))
        lng = float(geo[0].get("lng", 0) or geo[0].get("lon", 0))
    except (TypeError, ValueError, KeyError):
        return f"{sig('error')}\nInvalid coordinates returned for '{place_name}'"
    display = geo[0].get("display_name", place_name)

    # Fetch imagery
    imagery = await sb_client.get_satellite_images(lat, lng, count)
    scenes = imagery.get("scenes", [])

    lines = [
        sig("satellite"),
        f"📍 Location: {display}",
        f"📐 Coords: {lat:.4f}°, {lng:.4f}°",
        f"🛰️ Source: {imagery.get('source', 'Sentinel-2')}",
        "",
    ]

    if scenes:
        for i, scene in enumerate(scenes, 1):
            lines.append(f"📸 Scene {i}:")
            lines.append(f"  Date: {scene.get('datetime', 'Unknown')}")
            lines.append(f"  Cloud: {scene.get('cloud_cover', '?')}%")
            lines.append(f"  Platform: {scene.get('platform', 'Unknown')}")
            thumb = scene.get("thumbnail_url", "")
            if thumb:
                lines.append(f"  🔗 {thumb}")
            lines.append("")
    else:
        lines.append("⚠️ No recent clear-sky scenes found.")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Research results to pin placer
# ---------------------------------------------------------------------------

async def pin_research_results(
    sb_client,
    results: list[dict],
    category: str = "research",
    auto_pin: bool = True,
) -> str:
    """Take a list of research results with lat/lng and pin them all on the map."""
    if not results:
        return f"{sig('intel')}\nNo results to pin."

    # Place pins in batch
    pins = []
    for r in results:
        lat = r.get("lat")
        lng = r.get("lng")
        label = r.get("label", r.get("name", "Unknown"))
        description = r.get("description", "")
        source_url = r.get("source_url", r.get("url", ""))

        if lat is not None and lng is not None:
            pins.append({
                "lat": float(lat),
                "lng": float(lng),
                "label": label,
                "category": category,
                "description": description,
                "source": "openclaw:research",
                "source_url": source_url,
            })

    if auto_pin and pins:
        await sb_client.place_pins_batch(pins)

    lines = [
        sig("pinning"),
        f"📌 {len(pins)} pins placed on the AI Intel layer",
        "",
    ]
    for p in pins[:10]:
        lines.append(f"  📍 {p['label']} — {p['lat']:.4f}°, {p['lng']:.4f}°")
    if len(pins) > 10:
        lines.append(f"  ... and {len(pins) - 10} more")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# News aggregation
# ---------------------------------------------------------------------------

async def format_news_brief(
    sb_client,
    place_name: str,
    radius: float = 500,
) -> str:
    """Aggregate GDELT + news for a location."""
    try:
        geo = await sb_client.geocode(place_name)
    except Exception:
        return f"{sig('error')}\nGeocoding failed for '{place_name}'"
    if not geo:
        return f"{sig('error')}\nCould not geocode '{place_name}'"

    try:
        lat = float(geo[0].get("lat", 0))
        lng = float(geo[0].get("lng", 0) or geo[0].get("lon", 0))
    except (TypeError, ValueError, KeyError):
        return f"{sig('error')}\nInvalid coordinates returned for '{place_name}'"
    display = geo[0].get("display_name", place_name)

    data = await sb_client.get_news_near(lat, lng, radius)

    lines = [
        sig("news"),
        f"📍 {display}",
        f"📏 Radius: {radius} miles",
        "",
    ]

    gdelt = data.get("gdelt", [])
    if gdelt:
        lines.append(f"🔴 GDELT Conflict Events ({data.get('gdelt_count', len(gdelt))}):")
        for g in gdelt[:5]:
            name = g.get("name", "Unknown")
            count = g.get("count", 1)
            dist = g.get("distance_miles", "?")
            lines.append(f"  • {name} ({count} events) — {dist}mi")
            headlines = g.get("headlines", [])
            for h in headlines[:2]:
                lines.append(f"    📰 {h[:80]}")
            urls = g.get("urls", [])
            for u in urls[:1]:
                lines.append(f"    🔗 {u}")
        lines.append("")

    news = data.get("news", [])
    if news:
        lines.append(f"📰 News ({data.get('news_count', len(news))}):")
        for n in news[:5]:
            title = n.get("title", "Unknown")
            source = n.get("source", "?")
            risk = n.get("risk_score", 0)
            link = n.get("link", "")
            lines.append(f"  • [{source}] {title[:80]}")
            if risk > 50:
                lines.append(f"    ⚠️ Risk: {risk}/100")
            if link:
                lines.append(f"    🔗 {link}")
        lines.append("")

    if not gdelt and not news:
        lines.append("🟢 No notable conflict events or news in this area.")
        lines.append("")

    return "\n".join(lines)
