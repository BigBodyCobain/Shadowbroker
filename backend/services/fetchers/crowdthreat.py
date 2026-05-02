"""CrowdThreat fetcher — crowdsourced global threat intelligence.

Polls verified threat reports from CrowdThreat's public API and normalises
them into map-ready records with category-based icon IDs.

No API key required — the /threats endpoint is unauthenticated.
"""

import logging

from services.network_utils import fetch_with_curl
from services.fetchers._store import latest_data, _data_lock, _mark_fresh, is_any_active
from services.fetchers.retry import with_retry

logger = logging.getLogger("services.data_fetcher")

_CT_BASE = "https://backend.crowdthreat.world"

# CrowdThreat category_id → icon ID used on the MapLibre layer
_CATEGORY_ICON = {
    1: "ct-security",       # Security & Conflict  (red)
    2: "ct-crime",          # Crime & Safety        (blue)
    3: "ct-aviation",       # Aviation              (green)
    4: "ct-maritime",       # Maritime              (teal)
    5: "ct-infrastructure", # Industrial & Infra    (orange)
    6: "ct-special",        # Special Threats        (purple)
    7: "ct-social",         # Social & Political    (pink)
    8: "ct-other",          # Other                 (gray)
}

_CATEGORY_COLOUR = {
    1: "#ef4444",  # red
    2: "#3b82f6",  # blue
    3: "#22c55e",  # green
    4: "#14b8a6",  # teal
    5: "#f97316",  # orange
    6: "#a855f7",  # purple
    7: "#ec4899",  # pink
    8: "#6b7280",  # gray
}


@with_retry(max_retries=2, base_delay=5)
def fetch_crowdthreat():
    """Fetch verified threat reports from CrowdThreat public API."""
    if not is_any_active("crowdthreat"):
        return

    try:
        resp = fetch_with_curl(f"{_CT_BASE}/threats", timeout=20)
        if not resp or resp.status_code != 200:
            logger.warning("CrowdThreat API returned %s", getattr(resp, "status_code", "None"))
            return

        payload = resp.json()
        raw_threats = payload.get("data", {}).get("threats", [])
        if not raw_threats:
            logger.debug("CrowdThreat returned 0 threats")
            return

    except Exception as e:
        logger.error("CrowdThreat fetch error: %s", e)
        return

    processed = []
    for t in raw_threats:
        loc = t.get("location") or {}
        lng_lat = loc.get("lng_lat")
        if not lng_lat or len(lng_lat) < 2:
            continue
        try:
            lng = float(lng_lat[0])
            lat = float(lng_lat[1])
        except (TypeError, ValueError):
            continue

        cat = t.get("category") or {}
        cat_id = cat.get("id", 8)
        subcat = t.get("subcategory") or {}
        threat_type = t.get("type") or {}
        dates = t.get("dates") or {}
        occurred = dates.get("occurred") or {}
        reported = dates.get("reported") or {}

        # Extract all available detail from the API response
        summary = (t.get("summary") or t.get("description") or "").strip()
        verification = (t.get("verification_status") or t.get("status") or "").strip()
        country_obj = loc.get("country") or {}
        country = country_obj.get("name", "") if isinstance(country_obj, dict) else str(country_obj or "")
        media = t.get("media") or t.get("images") or t.get("attachments") or []
        source_url = t.get("source_url") or t.get("url") or t.get("link") or ""
        severity = t.get("severity") or t.get("severity_level") or t.get("risk_level") or ""
        votes = t.get("votes") or t.get("upvotes") or 0
        reporter = t.get("user") or t.get("reporter") or {}
        reporter_name = reporter.get("name", "") if isinstance(reporter, dict) else ""

        processed.append({
            "id": t.get("id"),
            "title": t.get("title", ""),
            "summary": summary[:500] if summary else "",
            "lat": lat,
            "lng": lng,
            "address": loc.get("name", ""),
            "city": loc.get("city", ""),
            "country": country,
            "category": cat.get("name", "Other"),
            "category_id": cat_id,
            "category_colour": _CATEGORY_COLOUR.get(cat_id, "#6b7280"),
            "subcategory": subcat.get("name", ""),
            "threat_type": threat_type.get("name", ""),
            "icon_id": _CATEGORY_ICON.get(cat_id, "ct-other"),
            "occurred": occurred.get("raw", ""),
            "occurred_iso": occurred.get("iso", ""),
            "timeago": occurred.get("timeago", ""),
            "reported": reported.get("raw", ""),
            "verification": verification,
            "severity": str(severity),
            "source_url": source_url,
            "media_urls": [m.get("url") or m for m in media[:3]] if isinstance(media, list) else [],
            "votes": int(votes) if votes else 0,
            "reporter": reporter_name,
            "source": "CrowdThreat",
        })

    logger.info("CrowdThreat: fetched %d verified threats", len(processed))

    with _data_lock:
        latest_data["crowdthreat"] = processed
    _mark_fresh("crowdthreat")
