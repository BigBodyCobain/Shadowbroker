"""
Carrier Strike Group OSINT Tracker
===================================
Scrapes multiple OSINT sources to maintain current estimated positions
for US Navy Carrier Strike Groups. Updates on startup + 00:00 & 12:00 UTC.

Sources:
  1. GDELT News API — recent carrier movement headlines
  2. WikiVoyage / public port-call databases
  3. Fallback — last-known or static OSINT estimates
"""

import re
import json
import time
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from services.network_utils import fetch_with_curl

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------
# Carrier registry: hull number → metadata + fallback position
# -----------------------------------------------------------------
CARRIER_REGISTRY: Dict[str, dict] = {
    "CVN-68": {
        "name": "USS Nimitz (CVN-68)",
        "wiki": "https://en.wikipedia.org/wiki/USS_Nimitz",
        "homeport": "Bremerton, WA",
        "homeport_lat": 47.56, "homeport_lng": -122.63,
        "fallback_lat": 21.35, "fallback_lng": -157.95,
        "fallback_heading": 270,
        "fallback_desc": "Pacific Fleet / Pearl Harbor"
    },
    "CVN-69": {
        "name": "USS Dwight D. Eisenhower (CVN-69)",
        "wiki": "https://en.wikipedia.org/wiki/USS_Dwight_D._Eisenhower",
        "homeport": "Norfolk, VA",
        "homeport_lat": 36.95, "homeport_lng": -76.33,
        "fallback_lat": 18.0, "fallback_lng": 39.5,
        "fallback_heading": 120,
        "fallback_desc": "Red Sea / CENTCOM AOR"
    },
    "CVN-78": {
        "name": "USS Gerald R. Ford (CVN-78)",
        "wiki": "https://en.wikipedia.org/wiki/USS_Gerald_R._Ford",
        "homeport": "Norfolk, VA",
        "homeport_lat": 36.95, "homeport_lng": -76.33,
        "fallback_lat": 34.0, "fallback_lng": 25.0,
        "fallback_heading": 90,
        "fallback_desc": "Eastern Mediterranean deterrence"
    },
    "CVN-70": {
        "name": "USS Carl Vinson (CVN-70)",
        "wiki": "https://en.wikipedia.org/wiki/USS_Carl_Vinson",
        "homeport": "San Diego, CA",
        "homeport_lat": 32.68, "homeport_lng": -117.15,
        "fallback_lat": 15.0, "fallback_lng": 115.0,
        "fallback_heading": 45,
        "fallback_desc": "South China Sea patrol"
    },
    "CVN-71": {
        "name": "USS Theodore Roosevelt (CVN-71)",
        "wiki": "https://en.wikipedia.org/wiki/USS_Theodore_Roosevelt_(CVN-71)",
        "homeport": "San Diego, CA",
        "homeport_lat": 32.68, "homeport_lng": -117.15,
        "fallback_lat": 22.0, "fallback_lng": 122.0,
        "fallback_heading": 300,
        "fallback_desc": "Philippine Sea / Taiwan Strait"
    },
    "CVN-72": {
        "name": "USS Abraham Lincoln (CVN-72)",
        "wiki": "https://en.wikipedia.org/wiki/USS_Abraham_Lincoln_(CVN-72)",
        "homeport": "San Diego, CA",
        "homeport_lat": 32.68, "homeport_lng": -117.15,
        "fallback_lat": 21.0, "fallback_lng": -158.0,
        "fallback_heading": 270,
        "fallback_desc": "Pacific deployment"
    },
    "CVN-73": {
        "name": "USS George Washington (CVN-73)",
        "wiki": "https://en.wikipedia.org/wiki/USS_George_Washington_(CVN-73)",
        "homeport": "Yokosuka, Japan",
        "homeport_lat": 35.28, "homeport_lng": 139.67,
        "fallback_lat": 35.0, "fallback_lng": 139.0,
        "fallback_heading": 0,
        "fallback_desc": "Yokosuka, Japan (Forward deployed)"
    },
    "CVN-74": {
        "name": "USS John C. Stennis (CVN-74)",
        "wiki": "https://en.wikipedia.org/wiki/USS_John_C._Stennis",
        "homeport": "Norfolk, VA",
        "homeport_lat": 36.95, "homeport_lng": -76.33,
        "fallback_lat": 36.95, "fallback_lng": -76.33,
        "fallback_heading": 0,
        "fallback_desc": "RCOH / Norfolk (maintenance)"
    },
    "CVN-75": {
        "name": "USS Harry S. Truman (CVN-75)",
        "wiki": "https://en.wikipedia.org/wiki/USS_Harry_S._Truman",
        "homeport": "Norfolk, VA",
        "homeport_lat": 36.95, "homeport_lng": -76.33,
        "fallback_lat": 36.0, "fallback_lng": 15.0,
        "fallback_heading": 90,
        "fallback_desc": "Mediterranean deployment"
    },
    "CVN-76": {
        "name": "USS Ronald Reagan (CVN-76)",
        "wiki": "https://en.wikipedia.org/wiki/USS_Ronald_Reagan",
        "homeport": "Bremerton, WA",
        "homeport_lat": 47.56, "homeport_lng": -122.63,
        "fallback_lat": 47.56, "fallback_lng": -122.63,
        "fallback_heading": 0,
        "fallback_desc": "Bremerton, WA (Homeport)"
    },
    "CVN-77": {
        "name": "USS George H.W. Bush (CVN-77)",
        "wiki": "https://en.wikipedia.org/wiki/USS_George_H.W._Bush",
        "homeport": "Norfolk, VA",
        "homeport_lat": 36.95, "homeport_lng": -76.33,
        "fallback_lat": 36.95, "fallback_lng": -76.33,
        "fallback_heading": 0,
        "fallback_desc": "Norfolk, VA (Homeport)"
    },
}

# -----------------------------------------------------------------
# Region → approximate center coordinates
# Used to map textual geographic descriptions to lat/lng
# -----------------------------------------------------------------
REGION_COORDS: Dict[str, tuple] = {
    # Oceans & Seas
    "eastern mediterranean": (34.0, 25.0),
    "mediterranean": (36.0, 15.0),
    "western mediterranean": (37.0, 2.0),
    "red sea": (18.0, 39.5),
    "arabian sea": (16.0, 64.0),
    "persian gulf": (26.5, 51.5),
    "gulf of oman": (24.5, 58.5),
    "north arabian sea": (20.0, 64.0),
    "south china sea": (15.0, 115.0),
    "east china sea": (28.0, 125.0),
    "philippine sea": (20.0, 130.0),
    "sea of japan": (40.0, 135.0),
    "taiwan strait": (24.0, 119.5),
    "western pacific": (20.0, 140.0),
    "pacific": (20.0, -150.0),
    "indian ocean": (-5.0, 70.0),
    "north atlantic": (40.0, -40.0),
    "atlantic": (30.0, -50.0),
    "gulf of aden": (12.5, 45.0),
    "horn of africa": (10.0, 50.0),
    "strait of hormuz": (26.5, 56.3),
    "bab el-mandeb": (12.6, 43.3),
    "suez canal": (30.5, 32.3),
    "baltic sea": (57.0, 18.0),
    "north sea": (56.0, 3.0),
    "black sea": (43.0, 34.0),
    "south atlantic": (-20.0, -20.0),
    "coral sea": (-18.0, 155.0),
    "gulf of mexico": (25.0, -90.0),
    "caribbean": (15.0, -75.0),

    # Specific bases / ports
    "norfolk": (36.95, -76.33),
    "san diego": (32.68, -117.15),
    "yokosuka": (35.28, 139.67),
    "pearl harbor": (21.35, -157.95),
    "guam": (13.45, 144.79),
    "bahrain": (26.23, 50.55),
    "rota": (36.62, -6.35),
    "naples": (40.85, 14.27),
    "bremerton": (47.56, -122.63),
    "puget sound": (47.56, -122.63),
    "newport news": (36.98, -76.43),

    # Areas of operation
    "centcom": (25.0, 55.0),
    "indopacom": (20.0, 130.0),
    "eucom": (48.0, 15.0),
    "southcom": (10.0, -80.0),
    "5th fleet": (25.0, 55.0),
    "6th fleet": (36.0, 15.0),
    "7th fleet": (25.0, 130.0),
    "3rd fleet": (30.0, -130.0),
    "2nd fleet": (35.0, -60.0),
}

# -----------------------------------------------------------------
# Cache file for persisting positions between restarts
# -----------------------------------------------------------------
CACHE_FILE = Path(__file__).parent.parent / "carrier_cache.json"

_carrier_positions: Dict[str, dict] = {}
_positions_lock = threading.Lock()
_last_update: Optional[datetime] = None


def _load_cache() -> Dict[str, dict]:
    """Load cached carrier positions from disk."""
    try:
        if CACHE_FILE.exists():
            data = json.loads(CACHE_FILE.read_text())
            logger.info(f"Carrier cache loaded: {len(data)} carriers from {CACHE_FILE}")
            return data
    except Exception as e:
        logger.warning(f"Failed to load carrier cache: {e}")
    return {}


def _save_cache(positions: Dict[str, dict]):
    """Persist carrier positions to disk."""
    try:
        CACHE_FILE.write_text(json.dumps(positions, indent=2))
        logger.info(f"Carrier cache saved: {len(positions)} carriers")
    except Exception as e:
        logger.warning(f"Failed to save carrier cache: {e}")


def _match_region(text: str) -> Optional[tuple]:
    """Match a text string against known regions, return (lat, lng) or None."""
    text_lower = text.lower()
    for region, coords in sorted(REGION_COORDS.items(), key=lambda x: -len(x[0])):
        if region in text_lower:
            return coords
    return None


def _match_carrier(text: str) -> Optional[str]:
    """Match a text string against known carrier names/hull numbers."""
    text_lower = text.lower()
    for hull, info in CARRIER_REGISTRY.items():
        hull_check = hull.lower().replace("-", "")
        name_parts = info["name"].lower()
        # Match hull number (e.g., "CVN-78", "CVN78")
        if hull.lower() in text_lower or hull_check in text_lower.replace("-", ""):
            return hull
        # Match ship name (e.g., "Ford", "Eisenhower", "Vinson")
        ship_name = name_parts.split("(")[0].strip()
        last_name = ship_name.split()[-1] if ship_name else ""
        if last_name and len(last_name) > 3 and last_name in text_lower:
            return hull
    return None


def _fetch_gdelt_carrier_news() -> List[dict]:
    """Search GDELT for recent carrier movement news."""
    results = []
    search_terms = [
        "aircraft+carrier+deployed",
        "carrier+strike+group+navy",
        "USS+Nimitz+carrier", "USS+Ford+carrier", "USS+Eisenhower+carrier",
        "USS+Vinson+carrier", "USS+Roosevelt+carrier+navy",
        "USS+Lincoln+carrier", "USS+Truman+carrier",
        "USS+Reagan+carrier", "USS+Washington+carrier+navy",
        "USS+Bush+carrier", "USS+Stennis+carrier",
    ]

    for term in search_terms:
        try:
            url = f"https://api.gdeltproject.org/api/v2/doc/doc?query={term}&mode=artlist&maxrecords=5&format=json&timespan=14d"
            raw = fetch_with_curl(url, timeout=8)
            if not raw:
                continue
            data = json.loads(raw)
            articles = data.get("articles", [])
            for art in articles:
                title = art.get("title", "")
                url = art.get("url", "")
                results.append({"title": title, "url": url})
        except Exception as e:
            logger.debug(f"GDELT search failed for '{term}': {e}")
            continue

    logger.info(f"Carrier OSINT: found {len(results)} GDELT articles")
    return results


def _parse_carrier_positions_from_news(articles: List[dict]) -> Dict[str, dict]:
    """Parse carrier positions from news article titles and descriptions."""
    updates: Dict[str, dict] = {}

    for article in articles:
        title = article.get("title", "")

        # Try to match a carrier from the title
        hull = _match_carrier(title)
        if not hull:
            continue

        # Try to match a region from the title
        coords = _match_region(title)
        if not coords:
            continue

        # Only update if we haven't seen this carrier yet (first match wins — most recent)
        if hull not in updates:
            updates[hull] = {
                "lat": coords[0],
                "lng": coords[1],
                "desc": title[:100],
                "source": "GDELT OSINT",
                "updated": datetime.now(timezone.utc).isoformat()
            }
            logger.info(f"Carrier update: {CARRIER_REGISTRY[hull]['name']} → {coords} (from: {title[:80]})")

    return updates


def update_carrier_positions():
    """Main update function — called on startup and every 12h."""
    global _last_update

    logger.info("Carrier tracker: updating positions from OSINT sources...")

    # Start with fallback positions
    positions: Dict[str, dict] = {}
    for hull, info in CARRIER_REGISTRY.items():
        positions[hull] = {
            "name": info["name"],
            "lat": info["fallback_lat"],
            "lng": info["fallback_lng"],
            "heading": info["fallback_heading"],
            "desc": info["fallback_desc"],
            "wiki": info["wiki"],
            "source": "Static OSINT estimate",
            "updated": datetime.now(timezone.utc).isoformat()
        }

    # Load cached positions (may have better data from previous runs)
    cached = _load_cache()
    for hull, cached_pos in cached.items():
        if hull in positions:
            # Only use cache if it has a real OSINT source (not just static)
            if cached_pos.get("source", "").startswith("GDELT") or cached_pos.get("source", "").startswith("News"):
                positions[hull].update({
                    "lat": cached_pos["lat"],
                    "lng": cached_pos["lng"],
                    "desc": cached_pos.get("desc", positions[hull]["desc"]),
                    "source": cached_pos.get("source", "Cached OSINT"),
                    "updated": cached_pos.get("updated", "")
                })

    # Try GDELT news for fresh positions
    try:
        articles = _fetch_gdelt_carrier_news()
        news_positions = _parse_carrier_positions_from_news(articles)
        for hull, pos in news_positions.items():
            if hull in positions:
                positions[hull].update(pos)
                logger.info(f"Carrier OSINT: updated {CARRIER_REGISTRY[hull]['name']} from news")
    except Exception as e:
        logger.warning(f"GDELT carrier fetch failed: {e}")

    # Save and update the global state
    with _positions_lock:
        _carrier_positions.clear()
        _carrier_positions.update(positions)
        _last_update = datetime.now(timezone.utc)

    _save_cache(positions)

    sources = {}
    for p in positions.values():
        src = p.get("source", "unknown")
        sources[src] = sources.get(src, 0) + 1
    logger.info(f"Carrier tracker: {len(positions)} carriers updated. Sources: {sources}")


def get_carrier_positions() -> List[dict]:
    """Return current carrier positions for the data pipeline."""
    with _positions_lock:
        result = []
        for hull, pos in _carrier_positions.items():
            info = CARRIER_REGISTRY.get(hull, {})
            result.append({
                "name": pos.get("name", info.get("name", hull)),
                "type": "carrier",
                "lat": pos["lat"],
                "lng": pos["lng"],
                "heading": pos.get("heading", 0),
                "sog": 0,
                "cog": 0,
                "country": "United States",
                "desc": pos.get("desc", ""),
                "wiki": pos.get("wiki", info.get("wiki", "")),
                "estimated": True,
                "source": pos.get("source", "OSINT estimated position"),
                "last_osint_update": pos.get("updated", "")
            })
        return result


# -----------------------------------------------------------------
# Scheduler: runs at startup, then at 00:00 and 12:00 UTC daily
# -----------------------------------------------------------------
_scheduler_thread: Optional[threading.Thread] = None
_scheduler_stop = threading.Event()


def _scheduler_loop():
    """Background thread that triggers updates at 00:00 and 12:00 UTC."""
    # Initial update on startup
    try:
        update_carrier_positions()
    except Exception as e:
        logger.error(f"Carrier tracker initial update failed: {e}")

    while not _scheduler_stop.is_set():
        now = datetime.now(timezone.utc)
        # Next target: 00:00 or 12:00 UTC, whichever is sooner
        hour = now.hour
        if hour < 12:
            next_hour = 12
        else:
            next_hour = 24  # midnight = next day 00:00

        next_run = now.replace(hour=next_hour % 24, minute=0, second=0, microsecond=0)
        if next_hour == 24:
            from datetime import timedelta
            next_run = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

        wait_seconds = (next_run - now).total_seconds()
        logger.info(f"Carrier tracker: next update at {next_run.isoformat()} ({wait_seconds/3600:.1f}h)")

        # Wait until next scheduled time, or until stop event
        if _scheduler_stop.wait(timeout=wait_seconds):
            break  # Stop event was set

        try:
            update_carrier_positions()
        except Exception as e:
            logger.error(f"Carrier tracker scheduled update failed: {e}")


def start_carrier_tracker():
    """Start the carrier tracker background thread."""
    global _scheduler_thread
    if _scheduler_thread and _scheduler_thread.is_alive():
        return
    _scheduler_stop.clear()
    _scheduler_thread = threading.Thread(target=_scheduler_loop, daemon=True, name="carrier-tracker")
    _scheduler_thread.start()
    logger.info("Carrier tracker started")


def stop_carrier_tracker():
    """Stop the carrier tracker background thread."""
    _scheduler_stop.set()
    if _scheduler_thread:
        _scheduler_thread.join(timeout=5)
    logger.info("Carrier tracker stopped")
