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
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from services.network_utils import fetch_with_curl

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------
# Carrier registry: hull number → metadata + fallback position
# -----------------------------------------------------------------
CARRIER_REGISTRY: Dict[str, dict] = {
    # Fallback positions sourced from USNI News Fleet & Marine Tracker (Mar 9, 2026)
    # https://news.usni.org/2026/03/09/usni-news-fleet-and-marine-tracker-march-9-2026
    # --- Bremerton, WA (Naval Base Kitsap) ---
    # Distinct pier positions along Sinclair Inlet so carriers don't stack
    "CVN-68": {
        "name": "USS Nimitz (CVN-68)",
        "wiki": "https://en.wikipedia.org/wiki/USS_Nimitz",
        "homeport": "Bremerton, WA",
        "homeport_lat": 47.5535,
        "homeport_lng": -122.6400,
        "fallback_lat": 47.5535,
        "fallback_lng": -122.6400,
        "fallback_heading": 90,
        "fallback_desc": "Bremerton, WA (Maintenance)",
    },
    "CVN-76": {
        "name": "USS Ronald Reagan (CVN-76)",
        "wiki": "https://en.wikipedia.org/wiki/USS_Ronald_Reagan",
        "homeport": "Bremerton, WA",
        "homeport_lat": 47.5580,
        "homeport_lng": -122.6360,
        "fallback_lat": 47.5580,
        "fallback_lng": -122.6360,
        "fallback_heading": 90,
        "fallback_desc": "Bremerton, WA (Decommissioning)",
    },
    # --- Norfolk, VA (Naval Station Norfolk) ---
    # Piers run N-S along Willoughby Bay; each carrier gets a distinct berth
    "CVN-69": {
        "name": "USS Dwight D. Eisenhower (CVN-69)",
        "wiki": "https://en.wikipedia.org/wiki/USS_Dwight_D._Eisenhower",
        "homeport": "Norfolk, VA",
        "homeport_lat": 36.9465,
        "homeport_lng": -76.3265,
        "fallback_lat": 36.9465,
        "fallback_lng": -76.3265,
        "fallback_heading": 0,
        "fallback_desc": "Norfolk, VA (Post-deployment maintenance)",
    },
    "CVN-78": {
        "name": "USS Gerald R. Ford (CVN-78)",
        "wiki": "https://en.wikipedia.org/wiki/USS_Gerald_R._Ford",
        "homeport": "Norfolk, VA",
        "homeport_lat": 36.9505,
        "homeport_lng": -76.3250,
        "fallback_lat": 18.0,
        "fallback_lng": 39.5,
        "fallback_heading": 0,
        "fallback_desc": "Red Sea — Operation Epic Fury (USNI Mar 9)",
    },
    "CVN-74": {
        "name": "USS John C. Stennis (CVN-74)",
        "wiki": "https://en.wikipedia.org/wiki/USS_John_C._Stennis",
        "homeport": "Norfolk, VA",
        "homeport_lat": 36.9540,
        "homeport_lng": -76.3235,
        "fallback_lat": 36.98,
        "fallback_lng": -76.43,
        "fallback_heading": 0,
        "fallback_desc": "Newport News, VA (RCOH refueling overhaul)",
    },
    "CVN-75": {
        "name": "USS Harry S. Truman (CVN-75)",
        "wiki": "https://en.wikipedia.org/wiki/USS_Harry_S._Truman",
        "homeport": "Norfolk, VA",
        "homeport_lat": 36.9580,
        "homeport_lng": -76.3220,
        "fallback_lat": 36.0,
        "fallback_lng": 15.0,
        "fallback_heading": 0,
        "fallback_desc": "Mediterranean Sea deployment (USNI Mar 9)",
    },
    "CVN-77": {
        "name": "USS George H.W. Bush (CVN-77)",
        "wiki": "https://en.wikipedia.org/wiki/USS_George_H.W._Bush",
        "homeport": "Norfolk, VA",
        "homeport_lat": 36.9620,
        "homeport_lng": -76.3210,
        "fallback_lat": 36.5,
        "fallback_lng": -74.0,
        "fallback_heading": 0,
        "fallback_desc": "Atlantic — Pre-deployment workups (USNI Mar 9)",
    },
    # --- San Diego, CA (Naval Base San Diego) ---
    # Carrier piers along the east shore of San Diego Bay, spread N-S
    "CVN-70": {
        "name": "USS Carl Vinson (CVN-70)",
        "wiki": "https://en.wikipedia.org/wiki/USS_Carl_Vinson",
        "homeport": "San Diego, CA",
        "homeport_lat": 32.6840,
        "homeport_lng": -117.1290,
        "fallback_lat": 32.6840,
        "fallback_lng": -117.1290,
        "fallback_heading": 180,
        "fallback_desc": "San Diego, CA (Homeport)",
    },
    "CVN-71": {
        "name": "USS Theodore Roosevelt (CVN-71)",
        "wiki": "https://en.wikipedia.org/wiki/USS_Theodore_Roosevelt_(CVN-71)",
        "homeport": "San Diego, CA",
        "homeport_lat": 32.6885,
        "homeport_lng": -117.1280,
        "fallback_lat": 32.6885,
        "fallback_lng": -117.1280,
        "fallback_heading": 180,
        "fallback_desc": "San Diego, CA (Maintenance)",
    },
    "CVN-72": {
        "name": "USS Abraham Lincoln (CVN-72)",
        "wiki": "https://en.wikipedia.org/wiki/USS_Abraham_Lincoln_(CVN-72)",
        "homeport": "San Diego, CA",
        "homeport_lat": 32.6925,
        "homeport_lng": -117.1275,
        "fallback_lat": 20.0,
        "fallback_lng": 64.0,
        "fallback_heading": 0,
        "fallback_desc": "Arabian Sea — Operation Epic Fury (USNI Mar 9)",
    },
    # --- Yokosuka, Japan (CFAY) ---
    "CVN-73": {
        "name": "USS George Washington (CVN-73)",
        "wiki": "https://en.wikipedia.org/wiki/USS_George_Washington_(CVN-73)",
        "homeport": "Yokosuka, Japan",
        "homeport_lat": 35.2830,
        "homeport_lng": 139.6700,
        "fallback_lat": 35.2830,
        "fallback_lng": 139.6700,
        "fallback_heading": 180,
        "fallback_desc": "Yokosuka, Japan (Forward deployed)",
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
_last_gdelt_fetch_at = 0.0
_cached_gdelt_articles: List[dict] = []
_GDELT_FETCH_INTERVAL_SECONDS = 1800
_GDELT_REQUEST_DELAY_SECONDS = 1.25
_GDELT_REQUEST_JITTER_SECONDS = 0.35


def _load_cache() -> Dict[str, dict]:
    """Load cached carrier positions from disk."""
    try:
        if CACHE_FILE.exists():
            data = json.loads(CACHE_FILE.read_text())
            logger.info(f"Carrier cache loaded: {len(data)} carriers from {CACHE_FILE}")
            return data
    except (IOError, OSError, json.JSONDecodeError, ValueError) as e:
        logger.warning(f"Failed to load carrier cache: {e}")
    return {}


def _save_cache(positions: Dict[str, dict]):
    """Persist carrier positions to disk."""
    try:
        CACHE_FILE.write_text(json.dumps(positions, indent=2))
        logger.info(f"Carrier cache saved: {len(positions)} carriers")
    except (IOError, OSError) as e:
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
    global _last_gdelt_fetch_at, _cached_gdelt_articles

    now = time.time()
    if _cached_gdelt_articles and (now - _last_gdelt_fetch_at) < _GDELT_FETCH_INTERVAL_SECONDS:
        logger.info("Carrier OSINT: using cached GDELT article set to avoid startup bursts")
        return list(_cached_gdelt_articles)

    results = []
    search_terms = [
        "aircraft+carrier+deployed",
        "carrier+strike+group+navy",
        "USS+Nimitz+carrier",
        "USS+Ford+carrier",
        "USS+Eisenhower+carrier",
        "USS+Vinson+carrier",
        "USS+Roosevelt+carrier+navy",
        "USS+Lincoln+carrier",
        "USS+Truman+carrier",
        "USS+Reagan+carrier",
        "USS+Washington+carrier+navy",
        "USS+Bush+carrier",
        "USS+Stennis+carrier",
    ]

    for idx, term in enumerate(search_terms):
        try:
            url = f"https://api.gdeltproject.org/api/v2/doc/doc?query={term}&mode=artlist&maxrecords=5&format=json&timespan=14d"
            raw = fetch_with_curl(url, timeout=8)
            if getattr(raw, "status_code", 500) == 429:
                logger.warning(
                    "GDELT returned 429 for '%s'; preserving cached carrier OSINT results",
                    term,
                )
                continue
            if not raw or not hasattr(raw, "text"):
                continue
            data = raw.json()
            articles = data.get("articles", [])
            for art in articles:
                title = art.get("title", "")
                url = art.get("url", "")
                results.append({"title": title, "url": url})
        except (ConnectionError, TimeoutError, ValueError, KeyError, OSError) as e:
            logger.debug(f"GDELT search failed for '{term}': {e}")
            continue
        if idx < len(search_terms) - 1:
            time.sleep(
                _GDELT_REQUEST_DELAY_SECONDS
                + random.uniform(0.0, _GDELT_REQUEST_JITTER_SECONDS)
            )

    _cached_gdelt_articles = list(results)
    _last_gdelt_fetch_at = time.time()
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
                "source": "GDELT News API",
                "source_url": article.get("url", "https://api.gdeltproject.org"),
                "updated": datetime.now(timezone.utc).isoformat(),
            }
            logger.info(
                f"Carrier update: {CARRIER_REGISTRY[hull]['name']} → {coords} (from: {title[:80]})"
            )

    return updates


def _load_carrier_fallbacks() -> Dict[str, dict]:
    """Build carrier positions from static fallbacks + disk cache (instant, no network)."""
    positions: Dict[str, dict] = {}
    for hull, info in CARRIER_REGISTRY.items():
        positions[hull] = {
            "name": info["name"],
            "lat": info["fallback_lat"],
            "lng": info["fallback_lng"],
            "heading": info["fallback_heading"],
            "desc": info["fallback_desc"],
            "wiki": info["wiki"],
            "source": "USNI News Fleet & Marine Tracker",
            "source_url": "https://news.usni.org/category/fleet-tracker",
            "updated": datetime.now(timezone.utc).isoformat(),
        }

    # Overlay cached positions from previous runs (may have GDELT data)
    cached = _load_cache()
    for hull, cached_pos in cached.items():
        if hull in positions:
            if cached_pos.get("source", "").startswith("GDELT") or cached_pos.get(
                "source", ""
            ).startswith("News"):
                positions[hull].update(
                    {
                        "lat": cached_pos["lat"],
                        "lng": cached_pos["lng"],
                        "desc": cached_pos.get("desc", positions[hull]["desc"]),
                        "source": cached_pos.get("source", "Cached OSINT"),
                        "updated": cached_pos.get("updated", ""),
                    }
                )
    return positions


def update_carrier_positions():
    """Main update function — called on startup and every 12h.

    Phase 1 (instant): publish fallback + cached positions so the map has carriers immediately.
    Phase 2 (slow):    query GDELT for fresh OSINT positions and update in-place.
    """
    global _last_update

    # --- Phase 1: instant fallback + cache ---
    positions = _load_carrier_fallbacks()

    with _positions_lock:
        # Only overwrite if positions are currently empty (first startup).
        # If we already have data from a previous cycle, keep it while GDELT runs.
        if not _carrier_positions:
            _carrier_positions.update(positions)
            _last_update = datetime.now(timezone.utc)
    logger.info(
        f"Carrier tracker: {len(positions)} carriers loaded from fallback/cache (GDELT enrichment starting...)"
    )

    # --- Phase 2: slow GDELT enrichment ---
    try:
        articles = _fetch_gdelt_carrier_news()
        news_positions = _parse_carrier_positions_from_news(articles)
        for hull, pos in news_positions.items():
            if hull in positions:
                positions[hull].update(pos)
                logger.info(f"Carrier OSINT: updated {CARRIER_REGISTRY[hull]['name']} from news")
    except (ValueError, KeyError, json.JSONDecodeError, OSError) as e:
        logger.warning(f"GDELT carrier fetch failed: {e}")

    # Save and update the global state with enriched positions
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


def _deconflict_positions(result: List[dict]) -> List[dict]:
    """Offset carriers that share identical coordinates so they don't stack.

    At port: offset along the pier axis (~500m / 0.004° apart).
    At sea: offset perpendicular to each other (~0.08° / ~9km apart)
    so they're visibly separate but clearly operating together.
    """
    # Group by rounded lat/lng (within ~0.01° ≈ 1km = same spot)
    from collections import defaultdict

    groups: dict[str, list[int]] = defaultdict(list)
    for i, c in enumerate(result):
        key = f"{round(c['lat'], 2)},{round(c['lng'], 2)}"
        groups[key].append(i)

    for indices in groups.values():
        if len(indices) < 2:
            continue
        n = len(indices)
        # Determine if this is a port (near a homeport) or at sea
        sample = result[indices[0]]
        at_port = any(
            abs(sample["lat"] - info.get("homeport_lat", 0)) < 0.05
            and abs(sample["lng"] - info.get("homeport_lng", 0)) < 0.05
            for info in CARRIER_REGISTRY.values()
        )

        if at_port:
            # Use each carrier's distinct homeport pier coordinates
            for idx in indices:
                carrier = result[idx]
                hull = None
                for h, info in CARRIER_REGISTRY.items():
                    if info["name"] == carrier["name"]:
                        hull = h
                        break
                if hull:
                    info = CARRIER_REGISTRY[hull]
                    carrier["lat"] = info["homeport_lat"]
                    carrier["lng"] = info["homeport_lng"]
        else:
            # At sea: spread in a line perpendicular to travel (~0.08° apart)
            spacing = 0.08  # ~9km — close enough to see they're together
            start_offset = -(n - 1) * spacing / 2
            for j, idx in enumerate(indices):
                result[idx]["lng"] += start_offset + j * spacing

    return result


def get_carrier_positions() -> List[dict]:
    """Return current carrier positions for the data pipeline."""
    with _positions_lock:
        result = []
        for hull, pos in _carrier_positions.items():
            info = CARRIER_REGISTRY.get(hull, {})
            result.append(
                {
                    "name": pos.get("name", info.get("name", hull)),
                    "type": "carrier",
                    "lat": pos["lat"],
                    "lng": pos["lng"],
                    "heading": None,  # Heading unknown for carriers — OSINT cannot determine true heading
                    "sog": 0,
                    "cog": 0,
                    "country": "United States",
                    "desc": pos.get("desc", ""),
                    "wiki": pos.get("wiki", info.get("wiki", "")),
                    "estimated": True,
                    "source": pos.get("source", "OSINT estimated position"),
                    "source_url": pos.get(
                        "source_url", "https://news.usni.org/category/fleet-tracker"
                    ),
                    "last_osint_update": pos.get("updated", ""),
                }
            )
        return _deconflict_positions(result)


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
        logger.info(
            f"Carrier tracker: next update at {next_run.isoformat()} ({wait_seconds/3600:.1f}h)"
        )

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
    _scheduler_thread = threading.Thread(
        target=_scheduler_loop, daemon=True, name="carrier-tracker"
    )
    _scheduler_thread.start()
    logger.info("Carrier tracker started")


def stop_carrier_tracker():
    """Stop the carrier tracker background thread."""
    _scheduler_stop.set()
    if _scheduler_thread:
        _scheduler_thread.join(timeout=5)
    logger.info("Carrier tracker stopped")
