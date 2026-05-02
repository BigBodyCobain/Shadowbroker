"""Satellite tracking — CelesTrak/TLE fetch, SGP4 propagation, intel classification.

CelesTrak Fair Use Policy (https://celestrak.org/NORAD/elements/):
  - Do NOT request the same data more than once every 24 hours
  - Use If-Modified-Since headers for conditional requests
  - No parallel/concurrent connections — one request at a time
  - Set a descriptive User-Agent

Analysis features (derived from cached TLEs — no extra network requests):
  - Maneuver detection: TLE-to-TLE comparison per satellite
  - Decay anomaly: mean-motion change rate monitoring
  - Overflight counting: 24h ground-track sampling for a bounding box
"""

import math
import time
import json
import re
import logging
import requests
from pathlib import Path
from datetime import datetime, timedelta
from sgp4.api import Satrec, WGS72, jday
from services.network_utils import fetch_with_curl
from services.fetchers._store import latest_data, _data_lock, _mark_fresh

logger = logging.getLogger("services.data_fetcher")


def _gmst(jd_ut1):
    """Greenwich Mean Sidereal Time in radians from Julian Date."""
    t = (jd_ut1 - 2451545.0) / 36525.0
    gmst_sec = (
        67310.54841 + (876600.0 * 3600 + 8640184.812866) * t + 0.093104 * t * t - 6.2e-6 * t * t * t
    )
    gmst_rad = (gmst_sec % 86400) / 86400.0 * 2 * math.pi
    return gmst_rad


# Satellite GP data cache
# CelesTrak fair use: fetch at most once per 24 hours (86400s).
# SGP4 propagation runs every 60s using cached TLEs — positions stay live.
_CELESTRAK_FETCH_INTERVAL = 86400  # 24 hours
_sat_gp_cache = {"data": None, "last_fetch": 0, "source": "none", "last_modified": None}
_sat_classified_cache = {"data": None, "gp_fetch_ts": 0}
_SAT_CACHE_PATH = Path(__file__).parent.parent.parent / "data" / "sat_gp_cache.json"
_SAT_CACHE_META_PATH = Path(__file__).parent.parent.parent / "data" / "sat_gp_cache_meta.json"

# ── Historical TLE storage for maneuver & decay detection ───────────────────
# Stores the previous TLE snapshot keyed by NORAD_CAT_ID.
# Populated when a fresh CelesTrak fetch replaces cached data.
# Persisted to disk so analysis survives restarts.
_SAT_HISTORY_PATH = Path(__file__).parent.parent.parent / "data" / "sat_tle_history.json"
_tle_history: dict[int, dict] = {}  # {norad_id: {elements + "epoch_ts"}}


def _load_tle_history():
    """Load previous TLE snapshot from disk."""
    global _tle_history
    try:
        if _SAT_HISTORY_PATH.exists():
            with open(_SAT_HISTORY_PATH, "r") as f:
                raw = json.load(f)
            _tle_history = {int(k): v for k, v in raw.items()}
            logger.info(f"Satellites: Loaded TLE history for {len(_tle_history)} objects")
    except (IOError, OSError, json.JSONDecodeError, ValueError, KeyError) as e:
        logger.warning(f"Satellites: Failed to load TLE history: {e}")
        _tle_history = {}


def _save_tle_history():
    """Persist current TLE snapshot as history for next comparison."""
    try:
        _SAT_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_SAT_HISTORY_PATH, "w") as f:
            json.dump(_tle_history, f)
    except (IOError, OSError) as e:
        logger.warning(f"Satellites: Failed to save TLE history: {e}")


def _snapshot_current_tles(gp_data):
    """Capture orbital elements from current GP data as the new 'previous' snapshot.

    Called once per CelesTrak fetch (every 24h). The old snapshot becomes
    the comparison baseline for maneuver/decay detection.
    """
    global _tle_history
    new_snapshot = {}
    for sat in gp_data:
        norad_id = sat.get("NORAD_CAT_ID")
        if norad_id is None:
            continue
        epoch_str = sat.get("EPOCH", "")
        try:
            epoch_dt = datetime.strptime(epoch_str[:19], "%Y-%m-%dT%H:%M:%S")
            epoch_ts = epoch_dt.timestamp()
        except (ValueError, TypeError):
            epoch_ts = 0
        new_snapshot[int(norad_id)] = {
            "MEAN_MOTION": sat.get("MEAN_MOTION"),
            "ECCENTRICITY": sat.get("ECCENTRICITY"),
            "INCLINATION": sat.get("INCLINATION"),
            "RA_OF_ASC_NODE": sat.get("RA_OF_ASC_NODE"),
            "BSTAR": sat.get("BSTAR"),
            "epoch_ts": epoch_ts,
        }
    _tle_history = new_snapshot
    _save_tle_history()


def _load_sat_cache():
    """Load satellite GP data from local disk cache."""
    try:
        if _SAT_CACHE_PATH.exists():
            import os

            age_hours = (time.time() - os.path.getmtime(str(_SAT_CACHE_PATH))) / 3600
            if age_hours < 48:
                with open(_SAT_CACHE_PATH, "r") as f:
                    data = json.load(f)
                if isinstance(data, list) and len(data) > 10:
                    logger.info(
                        f"Satellites: Loaded {len(data)} records from disk cache ({age_hours:.1f}h old)"
                    )
                    # Restore last_modified from metadata
                    _load_cache_meta()
                    return data
            else:
                logger.info(f"Satellites: Disk cache is {age_hours:.0f}h old, will try fresh fetch")
    except (IOError, OSError, json.JSONDecodeError, ValueError, KeyError) as e:
        logger.warning(f"Satellites: Failed to load disk cache: {e}")
    return None


def _save_sat_cache(data):
    """Save satellite GP data to local disk cache."""
    try:
        _SAT_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_SAT_CACHE_PATH, "w") as f:
            json.dump(data, f)
        _save_cache_meta()
        logger.info(f"Satellites: Saved {len(data)} records to disk cache")
    except (IOError, OSError) as e:
        logger.warning(f"Satellites: Failed to save disk cache: {e}")


def _load_cache_meta():
    """Load cache metadata (Last-Modified timestamp) from disk."""
    try:
        if _SAT_CACHE_META_PATH.exists():
            with open(_SAT_CACHE_META_PATH, "r") as f:
                meta = json.load(f)
            _sat_gp_cache["last_modified"] = meta.get("last_modified")
    except (IOError, OSError, json.JSONDecodeError, ValueError, KeyError):
        pass


def _save_cache_meta():
    """Save cache metadata to disk."""
    try:
        with open(_SAT_CACHE_META_PATH, "w") as f:
            json.dump({"last_modified": _sat_gp_cache.get("last_modified")}, f)
    except (IOError, OSError):
        pass


# Satellite intelligence classification database
# Matched by substring against OBJECT_NAME (case-insensitive).
# Order matters — first match wins, so specific names go before generic prefixes.
_SAT_INTEL_DB = [
    # ── USA Keyhole / Reconnaissance ────────────────────────────────────────
    ("USA 224", {"country": "USA", "mission": "military_recon", "sat_type": "KH-11 Reconnaissance", "wiki": "https://en.wikipedia.org/wiki/KH-11_KENNEN"}),
    ("USA 245", {"country": "USA", "mission": "military_recon", "sat_type": "KH-11 Reconnaissance", "wiki": "https://en.wikipedia.org/wiki/KH-11_KENNEN"}),
    ("USA 290", {"country": "USA", "mission": "military_recon", "sat_type": "KH-11 Reconnaissance", "wiki": "https://en.wikipedia.org/wiki/KH-11_KENNEN"}),
    ("USA 314", {"country": "USA", "mission": "military_recon", "sat_type": "KH-11 Reconnaissance", "wiki": "https://en.wikipedia.org/wiki/KH-11_KENNEN"}),
    ("USA 338", {"country": "USA", "mission": "military_recon", "sat_type": "Keyhole Successor", "wiki": "https://en.wikipedia.org/wiki/KH-11_KENNEN"}),
    # ── USA SIGINT / NRO ────────────────────────────────────────────────────
    ("NROL", {"country": "USA", "mission": "sigint", "sat_type": "Classified NRO", "wiki": "https://en.wikipedia.org/wiki/National_Reconnaissance_Office"}),
    ("MENTOR", {"country": "USA", "mission": "sigint", "sat_type": "SIGINT / ELINT (Orion)", "wiki": "https://en.wikipedia.org/wiki/Mentor_(satellite)"}),
    ("TRUMPET", {"country": "USA", "mission": "sigint", "sat_type": "SIGINT (HEO)", "wiki": "https://en.wikipedia.org/wiki/Trumpet_(satellite)"}),
    ("INTRUDER", {"country": "USA", "mission": "sigint", "sat_type": "Naval SIGINT (NOSS)", "wiki": "https://en.wikipedia.org/wiki/Naval_Ocean_Surveillance_System"}),
    # ── USA Early Warning / Missile Defense ─────────────────────────────────
    ("SBIRS", {"country": "USA", "mission": "early_warning", "sat_type": "Missile Warning", "wiki": "https://en.wikipedia.org/wiki/Space-Based_Infrared_System"}),
    ("DSP", {"country": "USA", "mission": "early_warning", "sat_type": "Defense Support Program", "wiki": "https://en.wikipedia.org/wiki/Defense_Support_Program"}),
    # ── USA Communications (Military) ───────────────────────────────────────
    ("MUOS", {"country": "USA", "mission": "military_comms", "sat_type": "Mobile User Objective System", "wiki": "https://en.wikipedia.org/wiki/Mobile_User_Objective_System"}),
    ("AEHF", {"country": "USA", "mission": "military_comms", "sat_type": "Advanced EHF", "wiki": "https://en.wikipedia.org/wiki/Advanced_Extremely_High_Frequency"}),
    ("WGS", {"country": "USA", "mission": "military_comms", "sat_type": "Wideband Global SATCOM", "wiki": "https://en.wikipedia.org/wiki/Wideband_Global_SATCOM"}),
    ("MILSTAR", {"country": "USA", "mission": "military_comms", "sat_type": "Milstar Secure Comms", "wiki": "https://en.wikipedia.org/wiki/Milstar"}),
    # ── USA Navigation ──────────────────────────────────────────────────────
    ("NAVSTAR", {"country": "USA", "mission": "navigation", "sat_type": "GPS", "wiki": "https://en.wikipedia.org/wiki/GPS_satellite_blocks"}),
    # ── Russia Reconnaissance ───────────────────────────────────────────────
    ("TOPAZ", {"country": "Russia", "mission": "military_recon", "sat_type": "Optical Reconnaissance", "wiki": "https://en.wikipedia.org/wiki/Persona_(satellite)"}),
    ("PERSONA", {"country": "Russia", "mission": "military_recon", "sat_type": "Optical Reconnaissance", "wiki": "https://en.wikipedia.org/wiki/Persona_(satellite)"}),
    ("KONDOR", {"country": "Russia", "mission": "military_sar", "sat_type": "SAR Reconnaissance", "wiki": "https://en.wikipedia.org/wiki/Kondor_(satellite)"}),
    ("BARS-M", {"country": "Russia", "mission": "military_recon", "sat_type": "Mapping Reconnaissance", "wiki": "https://en.wikipedia.org/wiki/Bars-M"}),
    ("RAZDAN", {"country": "Russia", "mission": "military_recon", "sat_type": "Optical Reconnaissance", "wiki": "https://en.wikipedia.org/wiki/Razdan_(satellite)"}),
    ("LOTOS", {"country": "Russia", "mission": "sigint", "sat_type": "ELINT (Lotos-S)", "wiki": "https://en.wikipedia.org/wiki/Lotos-S"}),
    ("PION", {"country": "Russia", "mission": "sigint", "sat_type": "Naval SIGINT/Radar", "wiki": "https://en.wikipedia.org/wiki/Pion-NKS"}),
    ("LUCH", {"country": "Russia", "mission": "sigint", "sat_type": "Relay / SIGINT", "wiki": "https://en.wikipedia.org/wiki/Luch_(satellite)"}),
    # ── Russia Early Warning & Navigation ───────────────────────────────────
    ("TUNDRA", {"country": "Russia", "mission": "early_warning", "sat_type": "Missile Warning (EKS)", "wiki": "https://en.wikipedia.org/wiki/Tundra_(satellite)"}),
    ("GLONASS", {"country": "Russia", "mission": "navigation", "sat_type": "GLONASS", "wiki": "https://en.wikipedia.org/wiki/GLONASS"}),
    # ── China Military / Intel ──────────────────────────────────────────────
    ("YAOGAN", {"country": "China", "mission": "military_recon", "sat_type": "Remote Sensing / ELINT", "wiki": "https://en.wikipedia.org/wiki/Yaogan"}),
    ("GAOFEN", {"country": "China", "mission": "military_recon", "sat_type": "High-Res Imaging", "wiki": "https://en.wikipedia.org/wiki/Gaofen"}),
    ("JILIN", {"country": "China", "mission": "commercial_imaging", "sat_type": "Video / Imaging", "wiki": "https://en.wikipedia.org/wiki/Jilin-1"}),
    ("SHIJIAN", {"country": "China", "mission": "sigint", "sat_type": "ELINT / Tech Demo", "wiki": "https://en.wikipedia.org/wiki/Shijian"}),
    ("TONGXIN JISHU SHIYAN", {"country": "China", "mission": "military_comms", "sat_type": "Military Comms Test", "wiki": "https://en.wikipedia.org/wiki/Tongxin_Jishu_Shiyan"}),
    ("BEIDOU", {"country": "China", "mission": "navigation", "sat_type": "BeiDou", "wiki": "https://en.wikipedia.org/wiki/BeiDou"}),
    ("TIANGONG", {"country": "China", "mission": "space_station", "sat_type": "Space Station", "wiki": "https://en.wikipedia.org/wiki/Tiangong_space_station"}),
    # ── Allied Military / Intel ─────────────────────────────────────────────
    ("OFEK", {"country": "Israel", "mission": "military_recon", "sat_type": "Reconnaissance", "wiki": "https://en.wikipedia.org/wiki/Ofeq"}),
    ("EROS", {"country": "Israel", "mission": "commercial_imaging", "sat_type": "High-Res Imaging", "wiki": "https://en.wikipedia.org/wiki/EROS_(satellite)"}),
    ("CSO", {"country": "France", "mission": "military_recon", "sat_type": "Optical Reconnaissance", "wiki": "https://en.wikipedia.org/wiki/CSO_(satellite)"}),
    ("HELIOS", {"country": "France", "mission": "military_recon", "sat_type": "Optical Reconnaissance", "wiki": "https://en.wikipedia.org/wiki/Helios_(satellite)"}),
    ("CERES", {"country": "France", "mission": "sigint", "sat_type": "ELINT Constellation", "wiki": "https://en.wikipedia.org/wiki/CERES_(satellite)"}),
    ("IGS", {"country": "Japan", "mission": "military_recon", "sat_type": "Intelligence Gathering", "wiki": "https://en.wikipedia.org/wiki/Information_Gathering_Satellite"}),
    ("KOMPSAT", {"country": "South Korea", "mission": "military_recon", "sat_type": "Multi-Purpose Satellite", "wiki": "https://en.wikipedia.org/wiki/KOMPSAT"}),
    ("SAR-LUPE", {"country": "Germany", "mission": "military_sar", "sat_type": "SAR Reconnaissance", "wiki": "https://en.wikipedia.org/wiki/SAR-Lupe"}),
    ("SARAH", {"country": "Germany", "mission": "military_sar", "sat_type": "SAR Successor (SARah)", "wiki": "https://en.wikipedia.org/wiki/SARah"}),
    # ── Commercial SAR ──────────────────────────────────────────────────────
    ("CAPELLA", {"country": "USA", "mission": "sar", "sat_type": "SAR Imaging", "wiki": "https://en.wikipedia.org/wiki/Capella_Space"}),
    ("ICEYE", {"country": "Finland", "mission": "sar", "sat_type": "SAR Microsatellite", "wiki": "https://en.wikipedia.org/wiki/ICEYE"}),
    ("COSMO-SKYMED", {"country": "Italy", "mission": "sar", "sat_type": "SAR Constellation", "wiki": "https://en.wikipedia.org/wiki/COSMO-SkyMed"}),
    ("TANDEM", {"country": "Germany", "mission": "sar", "sat_type": "SAR Interferometry", "wiki": "https://en.wikipedia.org/wiki/TanDEM-X"}),
    ("PAZ", {"country": "Spain", "mission": "sar", "sat_type": "SAR Imaging", "wiki": "https://en.wikipedia.org/wiki/PAZ_(satellite)"}),
    ("UMBRA", {"country": "USA", "mission": "sar", "sat_type": "SAR Microsatellite", "wiki": "https://en.wikipedia.org/wiki/Umbra_(company)"}),
    # ── Commercial Optical Imaging ──────────────────────────────────────────
    ("WORLDVIEW", {"country": "USA", "mission": "commercial_imaging", "sat_type": "Maxar High-Res", "wiki": "https://en.wikipedia.org/wiki/WorldView-3"}),
    ("GEOEYE", {"country": "USA", "mission": "commercial_imaging", "sat_type": "Maxar Imaging", "wiki": "https://en.wikipedia.org/wiki/GeoEye-1"}),
    ("LEGION", {"country": "USA", "mission": "commercial_imaging", "sat_type": "Maxar Legion", "wiki": "https://en.wikipedia.org/wiki/WorldView_Legion"}),
    ("PLEIADES", {"country": "France", "mission": "commercial_imaging", "sat_type": "Airbus Imaging", "wiki": "https://en.wikipedia.org/wiki/Pl%C3%A9iades_(satellite)"}),
    ("SPOT", {"country": "France", "mission": "commercial_imaging", "sat_type": "Airbus Medium-Res", "wiki": "https://en.wikipedia.org/wiki/SPOT_(satellite)"}),
    ("SKYSAT", {"country": "USA", "mission": "commercial_imaging", "sat_type": "Planet Video", "wiki": "https://en.wikipedia.org/wiki/SkySat"}),
    ("BLACKSKY", {"country": "USA", "mission": "commercial_imaging", "sat_type": "BlackSky Imaging", "wiki": "https://en.wikipedia.org/wiki/BlackSky"}),
    # ── Starlink (separate category) ────────────────────────────────────────
    ("STARLINK", {"country": "USA", "mission": "starlink", "sat_type": "Starlink Mega-Constellation", "wiki": "https://en.wikipedia.org/wiki/Starlink"}),
    # ── Other Constellations ────────────────────────────────────────────────
    ("ONEWEB", {"country": "UK", "mission": "constellation", "sat_type": "OneWeb LEO Broadband", "wiki": "https://en.wikipedia.org/wiki/OneWeb"}),
    ("GALILEO", {"country": "EU", "mission": "navigation", "sat_type": "Galileo", "wiki": "https://en.wikipedia.org/wiki/Galileo_(satellite_navigation)"}),
    # ── Space Stations ──────────────────────────────────────────────────────
    ("ISS", {"country": "Intl", "mission": "space_station", "sat_type": "Space Station", "wiki": "https://en.wikipedia.org/wiki/International_Space_Station"}),
    # ── Generic fallback patterns (last resort) ─────────────────────────────
    ("PLANET", {"country": "USA", "mission": "commercial_imaging", "sat_type": "PlanetScope", "wiki": "https://en.wikipedia.org/wiki/Planet_Labs"}),
]

# CelesTrak SATCAT owner codes → country mapping for satellites not matched by name.
# Used as a secondary classifier alongside name-pattern matching.
_OWNER_CODE_MAP = {
    "US": "USA", "CIS": "Russia", "PRC": "China", "ISS": "Intl",
    "FR": "France", "UK": "UK", "GER": "Germany", "JPN": "Japan",
    "IND": "India", "ISRA": "Israel", "IT": "Italy", "KOR": "South Korea",
    "ESA": "EU", "NATO": "NATO", "TURK": "Turkey", "UAE": "UAE",
    "AUS": "Australia", "CA": "Canada", "SPN": "Spain", "FIN": "Finland",
    "BRAZ": "Brazil", "IRAN": "Iran", "NKOR": "North Korea",
}

# ── Maneuver detection thresholds (per Lemmens & Krag 2014, Kim et al. 2021) ─
# These are above TLE fitting noise but low enough to catch real maneuvers.
_MANEUVER_THRESHOLDS = {
    "period_min": 0.1,        # minutes — above TLE noise (~0.01–0.05 min)
    "inclination_deg": 0.05,  # degrees — above J2 secular drift (~0.001°/day)
    "eccentricity": 0.005,    # above TLE fitting noise (~0.0001–0.001)
    "raan_residual_deg": 0.5, # degrees — only after J2 correction (Vallado §9.4)
}

# ── Decay anomaly threshold ─────────────────────────────────────────────────
# Flag if mean motion change rate exceeds this (rev/day per day).
# Normal drag-induced decay is ~0.001 rev/day/day for LEO.
_DECAY_MM_RATE_THRESHOLD = 0.01  # rev/day per day


def _j2_raan_rate(inclination_deg, mean_motion_revday):
    """Expected RAAN precession rate due to J2 (Vallado §9.4).

    Returns degrees/day. Negative for prograde orbits.
    """
    J2 = 1.08263e-3
    Re = 6378.137  # km
    mu = 398600.4418  # km^3/s^2
    n_rad_s = mean_motion_revday * 2 * math.pi / 86400.0
    if n_rad_s <= 0:
        return 0.0
    a = (mu / (n_rad_s ** 2)) ** (1.0 / 3.0)  # semi-major axis in km
    if a <= Re:
        return 0.0
    cos_i = math.cos(math.radians(inclination_deg))
    raan_rate = -1.5 * n_rad_s * J2 * (Re / a) ** 2 * cos_i
    return math.degrees(raan_rate) * 86400.0 / (2 * math.pi)  # deg/day


def detect_maneuvers(current_gp_data):
    """Compare current TLEs against stored history to detect orbital maneuvers.

    Returns list of maneuver alert dicts. Only runs when _tle_history is populated
    (i.e., after the second CelesTrak fetch or from persisted history).

    Thresholds from Lemmens & Krag (2014), Kim et al. (2021).
    """
    if not _tle_history:
        return []

    alerts = []
    for sat in current_gp_data:
        norad_id = sat.get("NORAD_CAT_ID")
        if norad_id is None:
            continue
        norad_id = int(norad_id)
        prev = _tle_history.get(norad_id)
        if prev is None:
            continue

        cur_mm = sat.get("MEAN_MOTION")
        cur_inc = sat.get("INCLINATION")
        cur_ecc = sat.get("ECCENTRICITY")
        cur_raan = sat.get("RA_OF_ASC_NODE")
        prev_mm = prev.get("MEAN_MOTION")
        prev_inc = prev.get("INCLINATION")
        prev_ecc = prev.get("ECCENTRICITY")
        prev_raan = prev.get("RA_OF_ASC_NODE")

        if any(v is None for v in (cur_mm, cur_inc, cur_ecc, cur_raan,
                                    prev_mm, prev_inc, prev_ecc, prev_raan)):
            continue

        # Convert mean motion (rev/day) to period (minutes)
        cur_period = 1440.0 / cur_mm if cur_mm > 0 else 0
        prev_period = 1440.0 / prev_mm if prev_mm > 0 else 0

        reasons = []
        t = _MANEUVER_THRESHOLDS

        delta_period = abs(cur_period - prev_period)
        if delta_period > t["period_min"]:
            reasons.append(f"period Δ{delta_period:+.3f} min")

        delta_inc = abs(cur_inc - prev_inc)
        if delta_inc > t["inclination_deg"]:
            reasons.append(f"inclination Δ{delta_inc:+.4f}°")

        delta_ecc = abs(cur_ecc - prev_ecc)
        if delta_ecc > t["eccentricity"]:
            reasons.append(f"eccentricity Δ{delta_ecc:+.6f}")

        # RAAN with J2 correction — only flag residual beyond expected precession
        epoch_str = sat.get("EPOCH", "")
        try:
            epoch_dt = datetime.strptime(epoch_str[:19], "%Y-%m-%dT%H:%M:%S")
            epoch_ts = epoch_dt.timestamp()
        except (ValueError, TypeError):
            epoch_ts = 0
        prev_epoch_ts = prev.get("epoch_ts", 0)
        dt_days = (epoch_ts - prev_epoch_ts) / 86400.0 if (epoch_ts and prev_epoch_ts) else 1.0
        if dt_days > 0:
            expected_raan_drift = _j2_raan_rate(cur_inc, cur_mm) * dt_days
            actual_raan_change = cur_raan - prev_raan
            # Normalize to [-180, 180]
            actual_raan_change = (actual_raan_change + 180) % 360 - 180
            raan_residual = abs(actual_raan_change - expected_raan_drift)
            if raan_residual > t["raan_residual_deg"]:
                reasons.append(f"RAAN residual {raan_residual:.3f}° (J2-corrected)")

        if reasons:
            alerts.append({
                "norad_id": norad_id,
                "name": sat.get("OBJECT_NAME", "UNKNOWN"),
                "type": "maneuver",
                "reasons": reasons,
                "epoch": sat.get("EPOCH", ""),
                "delta_period_min": round(delta_period, 4),
                "delta_inclination_deg": round(delta_inc, 5),
                "delta_eccentricity": round(delta_ecc, 7),
            })

    logger.info(f"Satellites: Maneuver scan — {len(alerts)} detections from {len(current_gp_data)} objects")
    return alerts


def detect_decay_anomalies(current_gp_data):
    """Flag satellites with abnormal mean-motion change rates (possible decay).

    A rapidly increasing mean motion indicates orbital decay — the satellite
    is losing altitude. Normal LEO drag is ~0.001 rev/day/day.
    """
    if not _tle_history:
        return []

    alerts = []
    for sat in current_gp_data:
        norad_id = sat.get("NORAD_CAT_ID")
        if norad_id is None:
            continue
        norad_id = int(norad_id)
        prev = _tle_history.get(norad_id)
        if prev is None:
            continue

        cur_mm = sat.get("MEAN_MOTION")
        prev_mm = prev.get("MEAN_MOTION")
        if cur_mm is None or prev_mm is None:
            continue

        epoch_str = sat.get("EPOCH", "")
        try:
            epoch_dt = datetime.strptime(epoch_str[:19], "%Y-%m-%dT%H:%M:%S")
            epoch_ts = epoch_dt.timestamp()
        except (ValueError, TypeError):
            continue
        prev_epoch_ts = prev.get("epoch_ts", 0)
        dt_days = (epoch_ts - prev_epoch_ts) / 86400.0 if (epoch_ts and prev_epoch_ts) else 0
        if dt_days < 0.5:
            continue  # Need at least 12h between TLEs for meaningful comparison

        mm_rate = (cur_mm - prev_mm) / dt_days  # rev/day per day
        if abs(mm_rate) > _DECAY_MM_RATE_THRESHOLD:
            cur_alt_km = (8681663.7 / (cur_mm ** (2.0 / 3.0))) - 6371.0 if cur_mm > 0 else 0
            alerts.append({
                "norad_id": norad_id,
                "name": sat.get("OBJECT_NAME", "UNKNOWN"),
                "type": "decay_anomaly",
                "mm_rate": round(mm_rate, 6),
                "current_mm": round(cur_mm, 4),
                "approx_alt_km": round(cur_alt_km, 1),
                "epoch": sat.get("EPOCH", ""),
                "dt_days": round(dt_days, 2),
            })

    logger.info(f"Satellites: Decay scan — {len(alerts)} anomalies detected")
    return alerts


def compute_overflights(gp_data, bbox, hours=24, step_minutes=10):
    """Count unique satellites whose ground track enters a bounding box.

    Args:
        gp_data: Full GP catalog (list of dicts with orbital elements).
        bbox: Dict with keys 's', 'w', 'n', 'e' (degrees).
        hours: Look-back window (default 24h).
        step_minutes: Sampling interval (default 10 min).

    Returns dict with total count and per-mission breakdown.
    Uses SGP4 propagation — CPU cost is ~O(catalog_size × timesteps).
    Only propagates satellites that could plausibly overfly the bbox latitude range.
    """
    if not gp_data or not bbox:
        return {"total": 0, "by_mission": {}, "satellites": []}

    south, west = bbox["s"], bbox["w"]
    north, east = bbox["n"], bbox["e"]
    now = datetime.utcnow()
    steps = int(hours * 60 / step_minutes)

    # Pre-filter: only propagate sats whose inclination allows them to reach bbox latitude
    max_lat = max(abs(south), abs(north))
    candidates = [s for s in gp_data if s.get("INCLINATION") is not None
                  and s.get("INCLINATION") >= max_lat * 0.8]  # 20% margin

    seen_ids = set()
    results = []
    by_mission = {}

    for s in candidates:
        norad_id = s.get("NORAD_CAT_ID")
        mean_motion = s.get("MEAN_MOTION")
        ecc = s.get("ECCENTRICITY")
        incl = s.get("INCLINATION")
        raan = s.get("RA_OF_ASC_NODE")
        argp = s.get("ARG_OF_PERICENTER")
        ma = s.get("MEAN_ANOMALY")
        bstar = s.get("BSTAR", 0)
        epoch_str = s.get("EPOCH", "")

        if any(v is None for v in (mean_motion, ecc, incl, raan, argp, ma, epoch_str)):
            continue

        try:
            epoch_dt = datetime.strptime(epoch_str[:19], "%Y-%m-%dT%H:%M:%S")
            epoch_jd, epoch_fr = jday(
                epoch_dt.year, epoch_dt.month, epoch_dt.day,
                epoch_dt.hour, epoch_dt.minute, epoch_dt.second,
            )
            sat_obj = Satrec()
            sat_obj.sgp4init(
                WGS72, "i", norad_id or 0,
                (epoch_jd + epoch_fr) - 2433281.5,
                bstar, 0.0, 0.0, ecc,
                math.radians(argp), math.radians(incl), math.radians(ma),
                mean_motion * 2 * math.pi / 1440.0, math.radians(raan),
            )
        except (ValueError, TypeError):
            continue

        for step in range(steps):
            t = now - timedelta(minutes=step * step_minutes)
            jd_t, fr_t = jday(t.year, t.month, t.day, t.hour, t.minute, t.second)
            e, r, _ = sat_obj.sgp4(jd_t, fr_t)
            if e != 0:
                continue
            x, y, z = r
            gmst = _gmst(jd_t + fr_t)
            lng_rad = math.atan2(y, x) - gmst
            lat_deg = math.degrees(math.atan2(z, math.sqrt(x * x + y * y)))
            lng_deg = math.degrees(lng_rad) % 360
            if lng_deg > 180:
                lng_deg -= 360

            # Check bounding box (handles antimeridian crossing)
            lat_in = south <= lat_deg <= north
            if west <= east:
                lng_in = west <= lng_deg <= east
            else:
                lng_in = lng_deg >= west or lng_deg <= east

            if lat_in and lng_in and norad_id not in seen_ids:
                seen_ids.add(norad_id)
                name = s.get("OBJECT_NAME", "UNKNOWN")
                # Classify for mission breakdown
                mission = "unknown"
                for key, meta in _SAT_INTEL_DB:
                    if key.upper() in name.upper():
                        mission = meta.get("mission", "unknown")
                        break
                by_mission[mission] = by_mission.get(mission, 0) + 1
                results.append({"norad_id": norad_id, "name": name, "mission": mission})
                break  # Already counted this sat, move to next

    return {"total": len(results), "by_mission": by_mission, "satellites": results}


def _parse_tle_to_gp(name, norad_id, line1, line2):
    """Convert TLE two-line element to CelesTrak GP-style dict."""
    try:
        incl = float(line2[8:16].strip())
        raan = float(line2[17:25].strip())
        ecc = float("0." + line2[26:33].strip())
        argp = float(line2[34:42].strip())
        ma = float(line2[43:51].strip())
        mm = float(line2[52:63].strip())
        bstar_str = line1[53:61].strip()
        if bstar_str:
            mantissa = float(bstar_str[:-2]) / 1e5
            exponent = int(bstar_str[-2:])
            bstar = mantissa * (10**exponent)
        else:
            bstar = 0.0
        epoch_yr = int(line1[18:20])
        epoch_day = float(line1[20:32].strip())
        year = 2000 + epoch_yr if epoch_yr < 57 else 1900 + epoch_yr
        epoch_dt = datetime(year, 1, 1) + timedelta(days=epoch_day - 1)
        return {
            "OBJECT_NAME": name,
            "NORAD_CAT_ID": norad_id,
            "MEAN_MOTION": mm,
            "ECCENTRICITY": ecc,
            "INCLINATION": incl,
            "RA_OF_ASC_NODE": raan,
            "ARG_OF_PERICENTER": argp,
            "MEAN_ANOMALY": ma,
            "BSTAR": bstar,
            "EPOCH": epoch_dt.strftime("%Y-%m-%dT%H:%M:%S"),
        }
    except (ValueError, TypeError, IndexError, KeyError):
        return None


def _fetch_satellites_from_tle_api():
    """Fallback: fetch satellite TLEs from tle.ivanstanojevic.me when CelesTrak is blocked."""
    search_terms = set()
    for key, _ in _SAT_INTEL_DB:
        term = key.split()[0] if len(key.split()) > 1 and key.split()[0] in ("USA", "NROL") else key
        search_terms.add(term)

    all_results = []
    seen_ids = set()
    for term in search_terms:
        try:
            url = f"https://tle.ivanstanojevic.me/api/tle/?search={term}&page_size=100&format=json"
            response = fetch_with_curl(url, timeout=8)
            if response.status_code != 200:
                continue
            data = response.json()
            for member in data.get("member", []):
                gp = _parse_tle_to_gp(
                    member.get("name", "UNKNOWN"),
                    member.get("satelliteId"),
                    member.get("line1", ""),
                    member.get("line2", ""),
                )
                if gp:
                    sat_id = gp.get("NORAD_CAT_ID")
                    if sat_id not in seen_ids:
                        seen_ids.add(sat_id)
                        all_results.append(gp)
            time.sleep(1)  # Polite delay between requests
        except (
            requests.RequestException,
            ConnectionError,
            TimeoutError,
            ValueError,
            KeyError,
            json.JSONDecodeError,
            OSError,
        ) as e:
            logger.debug(f"TLE fallback search '{term}' failed: {e}")

    return all_results


def fetch_satellites():
    from services.fetchers._store import is_any_active

    if not is_any_active("satellites"):
        return
    sats = []
    maneuver_alerts = []
    decay_alerts = []
    starlink_summary = {}
    data = None
    classified = None
    try:
        now_ts = time.time()

        # On first call, load TLE history from disk for maneuver detection
        if not _tle_history:
            _load_tle_history()

        # On first call, try disk cache before hitting CelesTrak
        if _sat_gp_cache["data"] is None:
            disk_data = _load_sat_cache()
            if disk_data:
                import os

                cache_mtime = (
                    os.path.getmtime(str(_SAT_CACHE_PATH)) if _SAT_CACHE_PATH.exists() else 0
                )
                _sat_gp_cache["data"] = disk_data
                _sat_gp_cache["last_fetch"] = cache_mtime  # real fetch time so 24h check works
                _sat_gp_cache["source"] = "disk_cache"
                logger.info(
                    f"Satellites: Bootstrapped from disk cache ({len(disk_data)} records, "
                    f"{(now_ts - cache_mtime) / 3600:.1f}h old)"
                )

        if (
            _sat_gp_cache["data"] is None
            or (now_ts - _sat_gp_cache["last_fetch"]) > _CELESTRAK_FETCH_INTERVAL
        ):
            gp_urls = [
                "https://celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=json",
                "https://celestrak.com/NORAD/elements/gp.php?GROUP=active&FORMAT=json",
            ]
            # Build conditional request headers (CelesTrak fair use)
            headers = {}
            if _sat_gp_cache.get("last_modified"):
                headers["If-Modified-Since"] = _sat_gp_cache["last_modified"]

            for url in gp_urls:
                try:
                    response = fetch_with_curl(url, timeout=15, headers=headers)
                    if response.status_code == 304:
                        # Data unchanged — reset timer without re-downloading
                        _sat_gp_cache["last_fetch"] = now_ts
                        logger.info(
                            f"Satellites: CelesTrak returned 304 Not Modified (data unchanged)"
                        )
                        break
                    if response.status_code == 200:
                        gp_data = response.json()
                        if isinstance(gp_data, list) and len(gp_data) > 100:
                            _sat_gp_cache["data"] = gp_data
                            _sat_gp_cache["last_fetch"] = now_ts
                            _sat_gp_cache["source"] = "celestrak"
                            # Store Last-Modified header for future conditional requests
                            if hasattr(response, "headers"):
                                lm = response.headers.get("Last-Modified")
                                if lm:
                                    _sat_gp_cache["last_modified"] = lm
                            _save_sat_cache(gp_data)
                            # Snapshot current TLEs as history before overwriting
                            # (the old _tle_history becomes the comparison baseline)
                            _snapshot_current_tles(gp_data)
                            logger.info(
                                f"Satellites: Downloaded {len(gp_data)} GP records from CelesTrak"
                            )
                            break
                except (
                    requests.RequestException,
                    ConnectionError,
                    TimeoutError,
                    ValueError,
                    KeyError,
                    json.JSONDecodeError,
                    OSError,
                ) as e:
                    logger.warning(f"Satellites: Failed to fetch from {url}: {e}")
                    continue

            if _sat_gp_cache["data"] is None:
                logger.info("Satellites: CelesTrak unreachable, trying TLE fallback API...")
                try:
                    fallback_data = _fetch_satellites_from_tle_api()
                    if fallback_data and len(fallback_data) > 10:
                        _sat_gp_cache["data"] = fallback_data
                        _sat_gp_cache["last_fetch"] = now_ts
                        _sat_gp_cache["source"] = "tle_api"
                        _save_sat_cache(fallback_data)
                        logger.info(
                            f"Satellites: Got {len(fallback_data)} records from TLE fallback API"
                        )
                except (
                    requests.RequestException,
                    ConnectionError,
                    TimeoutError,
                    ValueError,
                    KeyError,
                    OSError,
                ) as e:
                    logger.error(f"Satellites: TLE fallback also failed: {e}")

            if _sat_gp_cache["data"] is None:
                disk_data = _load_sat_cache()
                if disk_data:
                    _sat_gp_cache["data"] = disk_data
                    _sat_gp_cache["last_fetch"] = now_ts - (_CELESTRAK_FETCH_INTERVAL - 300)
                    _sat_gp_cache["source"] = "disk_cache"

        data = _sat_gp_cache["data"]
        if not data:
            logger.warning("No satellite GP data available from any source")
            with _data_lock:
                latest_data["satellites"] = sats
            return

        if (
            _sat_classified_cache["gp_fetch_ts"] == _sat_gp_cache["last_fetch"]
            and _sat_classified_cache["data"]
        ):
            classified = _sat_classified_cache["data"]
            starlink_summary = _sat_classified_cache.get("starlink_summary", {})
            logger.info(
                f"Satellites: Using cached classification ({len(classified)} sats, TLEs unchanged)"
            )
        else:
            classified = []
            starlink_count = 0
            starlink_shells = {}  # inclination shell → count
            for sat in data:
                name = sat.get("OBJECT_NAME", "UNKNOWN").upper()
                intel = None
                for key, meta in _SAT_INTEL_DB:
                    if key.upper() in name:
                        intel = dict(meta)
                        break
                if not intel:
                    # Secondary classification via SATCAT owner code
                    owner = sat.get("OWNER", sat.get("OBJECT_OWNER", ""))
                    if owner in _OWNER_CODE_MAP:
                        intel = {"country": _OWNER_CODE_MAP[owner], "mission": "general", "sat_type": "Unclassified"}
                if not intel:
                    continue

                # Starlink: count and summarize but don't propagate individually
                # (6000+ sats would be too expensive to position every 60s)
                if intel.get("mission") == "starlink":
                    starlink_count += 1
                    inc = sat.get("INCLINATION")
                    if inc is not None:
                        shell_key = f"{round(inc, 0):.0f}°"
                        starlink_shells[shell_key] = starlink_shells.get(shell_key, 0) + 1
                    continue  # Skip individual propagation

                entry = {
                    "id": sat.get("NORAD_CAT_ID"),
                    "name": sat.get("OBJECT_NAME", "UNKNOWN"),
                    "MEAN_MOTION": sat.get("MEAN_MOTION"),
                    "ECCENTRICITY": sat.get("ECCENTRICITY"),
                    "INCLINATION": sat.get("INCLINATION"),
                    "RA_OF_ASC_NODE": sat.get("RA_OF_ASC_NODE"),
                    "ARG_OF_PERICENTER": sat.get("ARG_OF_PERICENTER"),
                    "MEAN_ANOMALY": sat.get("MEAN_ANOMALY"),
                    "BSTAR": sat.get("BSTAR"),
                    "EPOCH": sat.get("EPOCH"),
                }
                entry.update(intel)
                classified.append(entry)

            starlink_summary = {
                "total": starlink_count,
                "shells": starlink_shells,
            }
            _sat_classified_cache["data"] = classified
            _sat_classified_cache["starlink_summary"] = starlink_summary
            _sat_classified_cache["gp_fetch_ts"] = _sat_gp_cache["last_fetch"]
            logger.info(
                f"Satellites: {len(classified)} intel-classified, "
                f"{starlink_count} Starlink (summarized), "
                f"out of {len(data)} total in catalog"
            )

        all_sats = classified

        # ── Run analysis detectors against the full GP catalog ──────────────
        # These use cached TLEs only — no extra network requests.
        maneuver_alerts = []
        decay_alerts = []
        try:
            maneuver_alerts = detect_maneuvers(data)
        except (ValueError, TypeError, KeyError, ZeroDivisionError) as e:
            logger.error(f"Satellites: Maneuver detection error: {e}")
        try:
            decay_alerts = detect_decay_anomalies(data)
        except (ValueError, TypeError, KeyError, ZeroDivisionError) as e:
            logger.error(f"Satellites: Decay detection error: {e}")

        now = datetime.utcnow()
        jd, fr = jday(
            now.year, now.month, now.day, now.hour, now.minute, now.second + now.microsecond / 1e6
        )

        for s in all_sats:
            try:
                mean_motion = s.get("MEAN_MOTION")
                ecc = s.get("ECCENTRICITY")
                incl = s.get("INCLINATION")
                raan = s.get("RA_OF_ASC_NODE")
                argp = s.get("ARG_OF_PERICENTER")
                ma = s.get("MEAN_ANOMALY")
                bstar = s.get("BSTAR", 0)
                epoch_str = s.get("EPOCH")
                norad_id = s.get("id", 0)

                if mean_motion is None or ecc is None or incl is None:
                    continue

                epoch_dt = datetime.strptime(epoch_str[:19], "%Y-%m-%dT%H:%M:%S")
                epoch_jd, epoch_fr = jday(
                    epoch_dt.year,
                    epoch_dt.month,
                    epoch_dt.day,
                    epoch_dt.hour,
                    epoch_dt.minute,
                    epoch_dt.second,
                )

                sat_obj = Satrec()
                sat_obj.sgp4init(
                    WGS72,
                    "i",
                    norad_id,
                    (epoch_jd + epoch_fr) - 2433281.5,
                    bstar,
                    0.0,
                    0.0,
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

                s["lat"] = round(math.degrees(lat_rad), 4)
                lng_deg = math.degrees(lng_rad) % 360
                s["lng"] = round(lng_deg - 360 if lng_deg > 180 else lng_deg, 4)
                s["alt_km"] = round(alt_km, 1)

                vx, vy, vz = v
                omega_e = 7.2921159e-5
                vx_g = vx + omega_e * y
                vy_g = vy - omega_e * x
                vz_g = vz
                cos_lat = math.cos(lat_rad)
                sin_lat = math.sin(lat_rad)
                cos_lng = math.cos(lng_rad + gmst)
                sin_lng = math.sin(lng_rad + gmst)
                v_east = -sin_lng * vx_g + cos_lng * vy_g
                v_north = -sin_lat * cos_lng * vx_g - sin_lat * sin_lng * vy_g + cos_lat * vz_g
                ground_speed_kms = math.sqrt(v_east**2 + v_north**2)
                s["speed_knots"] = round(ground_speed_kms * 1943.84, 1)
                heading_rad = math.atan2(v_east, v_north)
                s["heading"] = round(math.degrees(heading_rad) % 360, 1)
                sat_name = s.get("name", "")
                usa_match = re.search(r"USA[\s\-]*(\d+)", sat_name)
                if usa_match:
                    s["wiki"] = f"https://en.wikipedia.org/wiki/USA-{usa_match.group(1)}"
                for k in (
                    "MEAN_MOTION",
                    "ECCENTRICITY",
                    "INCLINATION",
                    "RA_OF_ASC_NODE",
                    "ARG_OF_PERICENTER",
                    "MEAN_ANOMALY",
                    "BSTAR",
                    "EPOCH",
                    "tle1",
                    "tle2",
                ):
                    s.pop(k, None)
                sats.append(s)
            except (ValueError, TypeError, KeyError, AttributeError, ZeroDivisionError):
                continue

        logger.info(f"Satellites: {len(classified)} classified, {len(sats)} positioned")
    except (
        requests.RequestException,
        ConnectionError,
        TimeoutError,
        ValueError,
        KeyError,
        json.JSONDecodeError,
        OSError,
    ) as e:
        logger.error(f"Error fetching satellites: {e}")
    if sats:
        with _data_lock:
            latest_data["satellites"] = sats
            latest_data["satellite_source"] = _sat_gp_cache.get("source", "none")
            latest_data["satellite_analysis"] = {
                "maneuvers": maneuver_alerts,
                "decay_anomalies": decay_alerts,
                "starlink": starlink_summary,
                "catalog_size": len(data) if data else 0,
                "classified_count": len(classified) if classified else 0,
            }
        _mark_fresh("satellites")
    else:
        with _data_lock:
            if not latest_data.get("satellites"):
                latest_data["satellites"] = []
                latest_data["satellite_source"] = "none"
