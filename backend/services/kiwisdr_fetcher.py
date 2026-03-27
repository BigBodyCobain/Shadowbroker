"""
KiwiSDR public receiver list fetcher.
Scrapes the kiwisdr.com public page for active SDR receivers worldwide.
Data is embedded as HTML comments inside each entry div.
"""

import re
import logging
import requests
from cachetools import TTLCache, cached

logger = logging.getLogger(__name__)

kiwisdr_cache = TTLCache(maxsize=1, ttl=600)  # 10-minute cache


def _parse_comment(html: str, field: str) -> str:
    """Extract a field value from HTML comment like <!-- field=value -->"""
    m = re.search(rf"<!--\s*{field}=(.*?)\s*-->", html)
    return m.group(1).strip() if m else ""


def _parse_gps(html: str):
    """Extract lat/lon from <!-- gps=(lat, lon) --> comment."""
    m = re.search(r"<!--\s*gps=\(([^,]+),\s*([^)]+)\)\s*-->", html)
    if m:
        try:
            return float(m.group(1)), float(m.group(2))
        except ValueError:
            return None, None
    return None, None


@cached(kiwisdr_cache)
def fetch_kiwisdr_nodes() -> list[dict]:
    """Fetch and parse the KiwiSDR public receiver list."""
    from services.network_utils import fetch_with_curl

    try:
        res = fetch_with_curl("http://kiwisdr.com/.public/", timeout=20)
        if not res or res.status_code != 200:
            logger.error(f"KiwiSDR fetch failed: HTTP {res.status_code if res else 'no response'}")
            return []

        html = res.text
        # Split by entry divs
        entries = re.findall(r"<div class='cl-entry[^']*'>(.*?)</div>\s*</div>", html, re.DOTALL)

        nodes = []
        for entry in entries:
            lat, lon = _parse_gps(entry)
            if lat is None or lon is None:
                continue
            if abs(lat) > 90 or abs(lon) > 180:
                continue

            offline = _parse_comment(entry, "offline")
            if offline == "yes":
                continue

            name = _parse_comment(entry, "name") or "Unknown SDR"
            users_str = _parse_comment(entry, "users")
            users_max_str = _parse_comment(entry, "users_max")
            bands = _parse_comment(entry, "bands")
            antenna = _parse_comment(entry, "antenna")
            location = _parse_comment(entry, "loc")

            # Extract the URL from the href
            url_match = re.search(r"href='(https?://[^']+)'", entry)
            url = url_match.group(1) if url_match else ""

            try:
                users = int(users_str) if users_str else 0
            except ValueError:
                users = 0
            try:
                users_max = int(users_max_str) if users_max_str else 0
            except ValueError:
                users_max = 0

            nodes.append(
                {
                    "name": name[:120],  # Truncate long names
                    "lat": round(lat, 5),
                    "lon": round(lon, 5),
                    "url": url,
                    "users": users,
                    "users_max": users_max,
                    "bands": bands,
                    "antenna": antenna[:200] if antenna else "",
                    "location": location[:100] if location else "",
                }
            )

        logger.info(f"KiwiSDR: parsed {len(nodes)} online receivers")
        return nodes

    except (requests.RequestException, ConnectionError, TimeoutError, ValueError, KeyError) as e:
        logger.error(f"KiwiSDR fetch exception: {e}")
        return []
