"""
SatNOGS ground station + observation fetcher.
Queries the SatNOGS Network API for online ground stations and recent
satellite observations. No API key required for read-only access.
"""

import logging
import requests
from cachetools import TTLCache, cached

logger = logging.getLogger(__name__)

_station_cache = TTLCache(maxsize=1, ttl=600)  # 10-minute cache
_obs_cache = TTLCache(maxsize=1, ttl=300)  # 5-minute cache


@cached(_station_cache)
def fetch_satnogs_stations() -> list[dict]:
    """Fetch online SatNOGS ground stations (status=2 = online)."""
    try:
        resp = requests.get(
            "https://network.satnogs.org/api/stations/",
            params={"format": "json", "status": 2},
            timeout=20,
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        stations = []
        for s in resp.json():
            lat, lng = s.get("lat"), s.get("lng")
            if lat is None or lng is None:
                continue
            try:
                lat, lng = float(lat), float(lng)
            except (ValueError, TypeError):
                continue
            if abs(lat) > 90 or abs(lng) > 180:
                continue

            antennas = s.get("antenna") or []
            antenna_str = ", ".join(
                a.get("antenna_type", "") for a in antennas if a.get("antenna_type")
            )

            stations.append(
                {
                    "id": s.get("id"),
                    "name": (s.get("name") or "Unknown")[:120],
                    "lat": round(lat, 5),
                    "lng": round(lng, 5),
                    "altitude": s.get("altitude"),
                    "antenna": antenna_str[:200],
                    "observations": s.get("observations", 0),
                    "status": s.get("status"),
                    "last_seen": s.get("last_seen"),
                }
            )
        logger.info(f"SatNOGS: fetched {len(stations)} online stations")
        return stations
    except (requests.RequestException, ConnectionError, TimeoutError, ValueError, KeyError) as e:
        logger.error(f"SatNOGS stations error: {e}")
        return []


@cached(_obs_cache)
def fetch_satnogs_observations() -> list[dict]:
    """Fetch recent good observations (first page, ~25 results)."""
    try:
        resp = requests.get(
            "https://network.satnogs.org/api/observations/",
            params={"format": "json", "status": "good"},
            timeout=20,
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        obs = []
        for o in resp.json():
            lat = o.get("station_lat")
            lng = o.get("station_lng")
            if lat is None or lng is None:
                continue
            try:
                lat, lng = float(lat), float(lng)
            except (ValueError, TypeError):
                continue

            # Satellite name from TLE line 0, or fall back to NORAD ID
            tle0 = (o.get("tle0") or "").strip()
            sat_name = tle0 if tle0 else f"NORAD {o.get('norad_cat_id', '?')}"

            obs.append(
                {
                    "id": o.get("id"),
                    "satellite_name": sat_name[:80],
                    "norad_id": o.get("norad_cat_id"),
                    "station_name": (o.get("station_name") or "Unknown")[:80],
                    "lat": round(lat, 5),
                    "lng": round(lng, 5),
                    "start": o.get("start"),
                    "end": o.get("end"),
                    "frequency": o.get("transmitter_downlink_low"),
                    "mode": o.get("transmitter_mode"),
                    "waterfall": o.get("waterfall"),
                    "audio": o.get("archive_url") or o.get("payload"),
                    "status": o.get("vetted_status"),
                }
            )
        logger.info(f"SatNOGS: fetched {len(obs)} recent observations")
        return obs
    except (requests.RequestException, ConnectionError, TimeoutError, ValueError, KeyError) as e:
        logger.error(f"SatNOGS observations error: {e}")
        return []
