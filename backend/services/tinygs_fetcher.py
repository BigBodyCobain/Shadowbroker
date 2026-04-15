"""
TinyGS LoRa satellite tracker — SGP4 orbit propagation + TinyGS telemetry.

Primary position source: CelesTrak TLEs propagated via SGP4 (always available).
Secondary validation: TinyGS API confirms satellite is actively transmitting LoRa
and provides modulation/frequency/status metadata.

CelesTrak Fair Use: TLEs fetched at most once per 24 hours, cached to disk.
TinyGS: polled every 5 minutes (their server has limited capacity).
"""

import json
import logging
import math
import time
from datetime import datetime
from pathlib import Path

import requests
from sgp4.api import Satrec, WGS72, jday

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CelesTrak TLE cache (24-hour refresh, disk-backed)
# ---------------------------------------------------------------------------
_CELESTRAK_FETCH_INTERVAL = 86400  # 24 hours
_TLE_CACHE_PATH = Path(__file__).parent.parent / "data" / "tinygs_tle_cache.json"
_tle_cache: dict = {"data": None, "last_fetch": 0.0}

# TinyGS API telemetry cache
_TINYGS_FETCH_INTERVAL = 300  # 5 minutes
_tinygs_telemetry: dict[str, dict] = {}  # name_key → {modulation, frequency, status}
_tinygs_last_fetch: float = 0.0
_tinygs_known_names: set[str] = set()  # names seen from TinyGS API

# Final result cache
_last_result: list[dict] = []

# CelesTrak GP groups containing LoRa / amateur cubesats
_CELESTRAK_GROUPS = ["amateur", "cubesat"]
_CELESTRAK_BASE = "https://celestrak.org/NORAD/elements/gp.php"


def _gmst(jd_ut1: float) -> float:
    """Greenwich Mean Sidereal Time in radians from Julian Date."""
    t = (jd_ut1 - 2451545.0) / 36525.0
    gmst_sec = (
        67310.54841
        + (876600.0 * 3600 + 8640184.812866) * t
        + 0.093104 * t * t
        - 6.2e-6 * t * t * t
    )
    return (gmst_sec % 86400) / 86400.0 * 2 * math.pi


# ---------------------------------------------------------------------------
# CelesTrak TLE fetch + disk cache
# ---------------------------------------------------------------------------


def _load_tle_cache() -> list[dict] | None:
    """Load TLE data from disk cache."""
    try:
        if _TLE_CACHE_PATH.exists():
            import os

            age = time.time() - os.path.getmtime(str(_TLE_CACHE_PATH))
            if age < _CELESTRAK_FETCH_INTERVAL * 2:  # accept up to 48h old cache
                data = json.loads(_TLE_CACHE_PATH.read_text(encoding="utf-8"))
                if isinstance(data, list) and len(data) > 0:
                    return data
    except (IOError, json.JSONDecodeError, ValueError) as e:
        logger.warning("TinyGS TLE: disk cache load failed: %s", e)
    return None


def _save_tle_cache(data: list[dict]) -> None:
    """Save TLE data to disk cache."""
    try:
        _TLE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _TLE_CACHE_PATH.write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
    except (IOError, OSError) as e:
        logger.warning("TinyGS TLE: disk cache save failed: %s", e)


def _fetch_celestrak_tles() -> list[dict]:
    """Fetch GP data from CelesTrak for amateur + cubesat groups."""
    global _tle_cache

    now = time.time()

    # Return memory cache if fresh
    if _tle_cache["data"] and now - _tle_cache["last_fetch"] < _CELESTRAK_FETCH_INTERVAL:
        return _tle_cache["data"]

    # Try disk cache first
    if not _tle_cache["data"]:
        disk = _load_tle_cache()
        if disk:
            _tle_cache["data"] = disk
            _tle_cache["last_fetch"] = now - _CELESTRAK_FETCH_INTERVAL + 3600  # re-check in 1h
            logger.info("TinyGS TLE: loaded %d elements from disk cache", len(disk))

    # Fetch fresh from CelesTrak
    all_sats: dict[int, dict] = {}  # keyed by NORAD_CAT_ID to deduplicate
    for group in _CELESTRAK_GROUPS:
        try:
            resp = requests.get(
                _CELESTRAK_BASE,
                params={"GROUP": group, "FORMAT": "json"},
                timeout=20,
                headers={
                    "User-Agent": "ShadowBroker-OSINT/1.0 (CelesTrak fair-use)",
                    "Accept": "application/json",
                },
            )
            resp.raise_for_status()
            for s in resp.json():
                norad_id = s.get("NORAD_CAT_ID")
                if norad_id:
                    all_sats[norad_id] = s
            logger.info("TinyGS TLE: fetched %s group (%d sats)", group, len(resp.json()))
        except (requests.RequestException, ValueError, KeyError) as e:
            logger.warning("TinyGS TLE: CelesTrak %s fetch failed: %s", group, e)

    if all_sats:
        result = list(all_sats.values())
        _tle_cache["data"] = result
        _tle_cache["last_fetch"] = now
        _save_tle_cache(result)
        logger.info("TinyGS TLE: cached %d total orbital elements", len(result))
        return result

    # Fall back to whatever we have
    return _tle_cache["data"] or []


# ---------------------------------------------------------------------------
# SGP4 propagation
# ---------------------------------------------------------------------------


def _propagate_all(gp_data: list[dict]) -> dict[int, dict]:
    """Propagate all satellites to current time via SGP4.

    Returns dict keyed by NORAD_CAT_ID with position/velocity data.
    """
    now = datetime.utcnow()
    jd, fr = jday(
        now.year, now.month, now.day,
        now.hour, now.minute,
        now.second + now.microsecond / 1e6,
    )

    results: dict[int, dict] = {}
    for s in gp_data:
        try:
            norad_id = s.get("NORAD_CAT_ID", 0)
            mean_motion = s.get("MEAN_MOTION")
            ecc = s.get("ECCENTRICITY")
            incl = s.get("INCLINATION")
            raan = s.get("RA_OF_ASC_NODE")
            argp = s.get("ARG_OF_PERICENTER")
            ma = s.get("MEAN_ANOMALY")
            bstar = s.get("BSTAR", 0)
            epoch_str = s.get("EPOCH")
            obj_name = s.get("OBJECT_NAME", "")

            if mean_motion is None or ecc is None or incl is None or not epoch_str:
                continue

            epoch_dt = datetime.strptime(epoch_str[:19], "%Y-%m-%dT%H:%M:%S")
            epoch_jd, epoch_fr = jday(
                epoch_dt.year, epoch_dt.month, epoch_dt.day,
                epoch_dt.hour, epoch_dt.minute, epoch_dt.second,
            )

            sat_obj = Satrec()
            sat_obj.sgp4init(
                WGS72, "i", norad_id,
                (epoch_jd + epoch_fr) - 2433281.5,
                bstar, 0.0, 0.0,
                ecc,
                math.radians(argp),
                math.radians(incl),
                math.radians(ma),
                mean_motion * 2 * math.pi / 1440.0,
                math.radians(raan),
            )

            e, r, v = sat_obj.sgp4(jd, fr)
            if e != 0:
                continue

            x, y, z = r
            gmst = _gmst(jd + fr)
            lng_rad = math.atan2(y, x) - gmst
            lat_rad = math.atan2(z, math.sqrt(x * x + y * y))
            alt_km = math.sqrt(x * x + y * y + z * z) - 6371.0

            lat = math.degrees(lat_rad)
            lng_deg = math.degrees(lng_rad) % 360
            lng = lng_deg - 360 if lng_deg > 180 else lng_deg

            # Ground-relative velocity for heading/speed
            vx, vy, vz = v
            omega_e = 7.2921159e-5
            vx_g = vx + omega_e * y
            vy_g = vy - omega_e * x
            cos_lat = math.cos(lat_rad)
            sin_lat = math.sin(lat_rad)
            cos_lng = math.cos(lng_rad + gmst)
            sin_lng = math.sin(lng_rad + gmst)
            v_east = -sin_lng * vx_g + cos_lng * vy_g
            v_north = -sin_lat * cos_lng * vx_g - sin_lat * sin_lng * vy_g + cos_lat * vz
            ground_speed_kms = math.sqrt(v_east**2 + v_north**2)
            speed_knots = ground_speed_kms * 1943.84
            heading = math.degrees(math.atan2(v_east, v_north)) % 360

            results[norad_id] = {
                "name": obj_name,
                "lat": round(lat, 4),
                "lng": round(lng, 4),
                "alt_km": round(alt_km, 1),
                "heading": round(heading, 1),
                "speed_knots": round(speed_knots, 0),
                "norad_id": norad_id,
            }
        except (ValueError, TypeError, KeyError, OverflowError):
            continue

    return results


# ---------------------------------------------------------------------------
# TinyGS API telemetry fetch
# ---------------------------------------------------------------------------


def _name_key(name: str) -> str:
    """Normalise a satellite name for fuzzy matching."""
    return name.upper().replace("-", "").replace("_", "").replace(" ", "")


def _fetch_tinygs_telemetry() -> None:
    """Fetch active satellite list from TinyGS for telemetry metadata."""
    global _tinygs_last_fetch, _tinygs_telemetry, _tinygs_known_names

    now = time.time()
    if now - _tinygs_last_fetch < _TINYGS_FETCH_INTERVAL:
        return

    try:
        resp = requests.get(
            "https://api.tinygs.com/v1/satellitesWorldmap",
            timeout=15,
            headers={
                "Accept": "application/json",
                "User-Agent": "ShadowBroker-OSINT/1.0",
            },
        )
        resp.raise_for_status()
        new_telemetry: dict[str, dict] = {}
        names: set[str] = set()
        for s in resp.json():
            display_name = (s.get("displayName") or s.get("name") or "")[:80]
            if not display_name:
                continue
            key = _name_key(display_name)
            names.add(key)
            tags = s.get("tags") or {}
            new_telemetry[key] = {
                "display_name": display_name,
                "status": s.get("status", ""),
                "modulation": ", ".join(tags.get("modulation", [])),
                "frequency": ", ".join(str(f) for f in tags.get("frequency", [])),
            }
        _tinygs_telemetry = new_telemetry
        _tinygs_known_names = names
        _tinygs_last_fetch = now
        logger.info("TinyGS telemetry: fetched %d active satellites", len(new_telemetry))
    except (requests.RequestException, ConnectionError, TimeoutError, ValueError, KeyError) as e:
        logger.warning("TinyGS telemetry fetch failed (SGP4 still active): %s", e)
        # Keep existing telemetry — don't clear on failure


# ---------------------------------------------------------------------------
# Merge SGP4 positions + TinyGS telemetry
# ---------------------------------------------------------------------------


def _match_name(celestrak_name: str) -> dict | None:
    """Try to match a CelesTrak object name to TinyGS telemetry."""
    key = _name_key(celestrak_name)
    # Exact match
    if key in _tinygs_telemetry:
        return _tinygs_telemetry[key]
    # Substring match — CelesTrak name contains TinyGS name or vice versa
    for tgs_key, tgs_data in _tinygs_telemetry.items():
        if tgs_key in key or key in tgs_key:
            return tgs_data
    return None


def fetch_tinygs_satellites() -> list[dict]:
    """Fetch LoRa satellite positions via SGP4 + TinyGS telemetry merge.

    1. Propagate cached CelesTrak TLEs via SGP4 (instant, no network needed)
    2. Attempt TinyGS API for telemetry (modulation, frequency, status)
    3. Merge: SGP4 provides position, TinyGS provides metadata
    4. Filter to only satellites known to TinyGS (if we have TinyGS data)
    """
    global _last_result

    # Step 1: Get TLE data (from cache or CelesTrak)
    gp_data = _fetch_celestrak_tles()
    if not gp_data:
        logger.warning("TinyGS: no TLE data available")
        return _last_result or []

    # Step 2: Try to fetch TinyGS telemetry (non-blocking, uses cache)
    _fetch_tinygs_telemetry()

    # Step 3: Propagate all satellites via SGP4
    propagated = _propagate_all(gp_data)
    if not propagated:
        logger.warning("TinyGS: SGP4 propagation returned no results")
        return _last_result or []

    # Step 4: Merge and filter
    sats: list[dict] = []
    have_tinygs = bool(_tinygs_known_names)

    for norad_id, pos in propagated.items():
        celestrak_name = pos["name"]
        telemetry = _match_name(celestrak_name)

        # If we have TinyGS data, only show satellites that TinyGS knows about
        # (filters out non-LoRa amateur/cubesats from the CelesTrak groups)
        if have_tinygs and telemetry is None:
            continue

        entry = {
            "name": telemetry["display_name"] if telemetry else celestrak_name,
            "lat": pos["lat"],
            "lng": pos["lng"],
            "heading": pos["heading"],
            "speed_knots": pos["speed_knots"],
            "alt_km": pos["alt_km"],
            "status": telemetry.get("status", "") if telemetry else "",
            "modulation": telemetry.get("modulation", "") if telemetry else "",
            "frequency": telemetry.get("frequency", "") if telemetry else "",
            "sgp4_propagated": True,
            "tinygs_confirmed": telemetry is not None,
        }
        sats.append(entry)

    # If we have no TinyGS data at all (API never responded), show all propagated
    # sats from the amateur group only (smaller, more relevant set)
    if not have_tinygs and not sats:
        for norad_id, pos in propagated.items():
            sats.append({
                "name": pos["name"],
                "lat": pos["lat"],
                "lng": pos["lng"],
                "heading": pos["heading"],
                "speed_knots": pos["speed_knots"],
                "alt_km": pos["alt_km"],
                "status": "",
                "modulation": "",
                "frequency": "",
                "sgp4_propagated": True,
                "tinygs_confirmed": False,
            })

    _last_result = sats
    logger.info(
        "TinyGS: %d satellites (SGP4 propagated, %d TinyGS confirmed)",
        len(sats),
        sum(1 for s in sats if s.get("tinygs_confirmed")),
    )
    return sats
