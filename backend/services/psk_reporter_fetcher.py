"""
PSK Reporter fetcher — pulls recent digital mode signal reports (FT8, WSPR, etc.)
from the global PSK Reporter network.  No API key required.

Docs: https://pskreporter.info/pskdev.html
"""

import logging
import xml.etree.ElementTree as ET

import requests
from cachetools import TTLCache, cached

logger = logging.getLogger(__name__)

_cache = TTLCache(maxsize=1, ttl=600)  # 10-minute cache

_ENDPOINT = "https://retrieve.pskreporter.info/query"


def maidenhead_to_latlon(locator: str) -> tuple[float, float] | None:
    """Convert a 4-or-6 character Maidenhead grid locator to (lat, lon)."""
    loc = locator.strip().upper()
    if len(loc) < 4:
        return None
    try:
        lon = (ord(loc[0]) - ord("A")) * 20 - 180
        lat = (ord(loc[1]) - ord("A")) * 10 - 90
        lon += int(loc[2]) * 2
        lat += int(loc[3])
        if len(loc) >= 6:
            lon += (ord(loc[4]) - ord("A")) * (2 / 24)
            lat += (ord(loc[5]) - ord("A")) * (1 / 24)
            # center of sub-square
            lon += 1 / 24
            lat += 1 / 48
        else:
            # center of grid square
            lon += 1
            lat += 0.5
        if abs(lat) > 90 or abs(lon) > 180:
            return None
        return round(lat, 4), round(lon, 4)
    except (IndexError, ValueError):
        return None


@cached(_cache)
def fetch_psk_reporter_spots() -> list[dict]:
    """Fetch recent FT8 reception reports from PSK Reporter."""
    try:
        resp = requests.get(
            _ENDPOINT,
            params={
                "mode": "FT8",
                "flowStartSeconds": -900,  # last 15 minutes
                "rronly": 1,               # reception reports only
                "noactive": 1,             # exclude active monitor noise
                "rptlimit": 5000,          # cap payload size
            },
            timeout=30,
            headers={"Accept": "application/xml"},
        )
        resp.raise_for_status()

        root = ET.fromstring(resp.content)

        # PSK Reporter XML uses namespaces
        ns = ""
        if root.tag.startswith("{"):
            ns = root.tag.split("}")[0] + "}"

        spots: list[dict] = []
        for rec in root.iter(f"{ns}receptionReport"):
            receiver_loc = rec.get("receiverLocator", "")
            sender_loc = rec.get("senderLocator", "")

            # Prefer receiver location (where the signal was heard)
            loc_str = receiver_loc or sender_loc
            if not loc_str:
                continue
            coords = maidenhead_to_latlon(loc_str)
            if coords is None:
                continue
            lat, lon = coords

            try:
                freq = int(rec.get("frequency", "0"))
            except (ValueError, TypeError):
                freq = 0

            try:
                snr = int(rec.get("sNR", "0"))
            except (ValueError, TypeError):
                snr = 0

            spots.append({
                "lat": lat,
                "lon": lon,
                "sender": (rec.get("senderCallsign") or "")[:20],
                "receiver": (rec.get("receiverCallsign") or "")[:20],
                "frequency": freq,
                "mode": (rec.get("mode") or "FT8")[:10],
                "snr": snr,
                "time": rec.get("flowStartSeconds", ""),
            })

        logger.info("PSK Reporter: fetched %d spots", len(spots))
        return spots

    except (requests.RequestException, ET.ParseError, Exception) as e:
        logger.error("PSK Reporter fetch error: %s", e)
        return []
