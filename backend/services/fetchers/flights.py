"""Commercial flight fetching — ADS-B, OpenSky, supplemental sources, routes,
trail accumulation, GPS jamming detection, and holding pattern detection."""

import copy
import re
import os
import time
import math
import json
import logging
import threading
import concurrent.futures
import random
import requests
from datetime import datetime
from services.network_utils import fetch_with_curl
from services.fetchers._store import latest_data, _data_lock, _mark_fresh
from services.fetchers.plane_alert import enrich_with_plane_alert, enrich_with_tracked_names
from services.fetchers.emissions import get_emissions_info
from services.fetchers.retry import with_retry
from services.fetchers.route_database import lookup_route
from services.fetchers.aircraft_database import lookup_aircraft_type
from services.constants import GPS_JAMMING_NACP_THRESHOLD, GPS_JAMMING_MIN_RATIO, GPS_JAMMING_MIN_AIRCRAFT

logger = logging.getLogger("services.data_fetcher")

# Pre-compiled regex patterns for airline code extraction (used in hot loop)
_RE_AIRLINE_CODE_1 = re.compile(r"^([A-Z]{3})\d")
_RE_AIRLINE_CODE_2 = re.compile(r"^([A-Z]{3})[A-Z\d]")


# ---------------------------------------------------------------------------
# OpenSky Network API Client (OAuth2)
# ---------------------------------------------------------------------------
class OpenSkyClient:
    def __init__(self, client_id, client_secret):
        self.client_id = client_id
        self.client_secret = client_secret
        self.token = None
        self.expires_at = 0

    def get_token(self):
        if self.token and time.time() < self.expires_at - 60:
            return self.token
        url = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        try:
            r = requests.post(url, data=data, timeout=10)
            if r.status_code == 200:
                res = r.json()
                self.token = res.get("access_token")
                self.expires_at = time.time() + res.get("expires_in", 1800)
                logger.info("OpenSky OAuth2 token refreshed.")
                return self.token
            else:
                logger.error(f"OpenSky Auth Failed: {r.status_code} {r.text}")
        except (
            requests.RequestException,
            ConnectionError,
            TimeoutError,
            ValueError,
            KeyError,
        ) as e:
            logger.error(f"OpenSky Auth Exception: {e}")
        return None


opensky_client = OpenSkyClient(
    client_id=os.environ.get("OPENSKY_CLIENT_ID", ""),
    client_secret=os.environ.get("OPENSKY_CLIENT_SECRET", ""),
)

# Throttling and caching for OpenSky (400 req/day limit)
last_opensky_fetch = 0
cached_opensky_flights = []
_opensky_cache_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Supplemental ADS-B sources for blind-spot gap-filling
# ---------------------------------------------------------------------------
_BLIND_SPOT_REGIONS = [
    {"name": "Yekaterinburg", "lat": 56.8, "lon": 60.6, "radius_nm": 250},
    {"name": "Novosibirsk", "lat": 55.0, "lon": 82.9, "radius_nm": 250},
    {"name": "Krasnoyarsk", "lat": 56.0, "lon": 92.9, "radius_nm": 250},
    {"name": "Vladivostok", "lat": 43.1, "lon": 131.9, "radius_nm": 250},
    {"name": "Urumqi", "lat": 43.8, "lon": 87.6, "radius_nm": 250},
    {"name": "Chengdu", "lat": 30.6, "lon": 104.1, "radius_nm": 250},
    {"name": "Lagos-Accra", "lat": 6.5, "lon": 3.4, "radius_nm": 250},
    {"name": "Addis Ababa", "lat": 9.0, "lon": 38.7, "radius_nm": 250},
]
# The blind-spot supplement previously burst several airplanes.live point
# queries in parallel and triggered repeated 429s in real startup logs, so we
# keep it on a long cache interval and pace each regional point query serially.
_SUPPLEMENTAL_FETCH_INTERVAL = 1800
_AIRPLANES_LIVE_DELAY_SECONDS = 1.2
_AIRPLANES_LIVE_DELAY_JITTER_SECONDS = 0.4
last_supplemental_fetch = 0
cached_supplemental_flights = []
_supplemental_cache_lock = threading.Lock()

# Helicopter type codes (backend classification)
_HELI_TYPES_BACKEND = {
    "R22",
    "R44",
    "R66",
    "B06",
    "B06T",
    "B204",
    "B205",
    "B206",
    "B212",
    "B222",
    "B230",
    "B407",
    "B412",
    "B427",
    "B429",
    "B430",
    "B505",
    "B525",
    "AS32",
    "AS35",
    "AS50",
    "AS55",
    "AS65",
    "EC20",
    "EC25",
    "EC30",
    "EC35",
    "EC45",
    "EC55",
    "EC75",
    "H125",
    "H130",
    "H135",
    "H145",
    "H155",
    "H160",
    "H175",
    "H215",
    "H225",
    "S55",
    "S58",
    "S61",
    "S64",
    "S70",
    "S76",
    "S92",
    "A109",
    "A119",
    "A139",
    "A169",
    "A189",
    "AW09",
    "MD52",
    "MD60",
    "MDHI",
    "MD90",
    "NOTR",
    "B47G",
    "HUEY",
    "GAMA",
    "CABR",
    "EXE",
}

# Private jet ICAO type designator codes
PRIVATE_JET_TYPES = {
    "G150",
    "G200",
    "G280",
    "GLEX",
    "G500",
    "G550",
    "G600",
    "G650",
    "G700",
    "GLF2",
    "GLF3",
    "GLF4",
    "GLF5",
    "GLF6",
    "GL5T",
    "GL7T",
    "GV",
    "GIV",
    "CL30",
    "CL35",
    "CL60",
    "BD70",
    "BD10",
    "GL5T",
    "GL7T",
    "CRJ1",
    "CRJ2",
    "C25A",
    "C25B",
    "C25C",
    "C500",
    "C501",
    "C510",
    "C525",
    "C526",
    "C550",
    "C560",
    "C56X",
    "C680",
    "C68A",
    "C700",
    "C750",
    "FA10",
    "FA20",
    "FA50",
    "FA7X",
    "FA8X",
    "F900",
    "F2TH",
    "ASTR",
    "E35L",
    "E545",
    "E550",
    "E55P",
    "LEGA",
    "PH10",
    "PH30",
    "LJ23",
    "LJ24",
    "LJ25",
    "LJ28",
    "LJ31",
    "LJ35",
    "LJ36",
    "LJ40",
    "LJ45",
    "LJ55",
    "LJ60",
    "LJ70",
    "LJ75",
    "H25A",
    "H25B",
    "H25C",
    "HA4T",
    "BE40",
    "PRM1",
    "HDJT",
    "PC24",
    "EA50",
    "SF50",
    "GALX",
}

# Flight trails state
flight_trails = {}  # {icao_hex: {points: [[lat, lng, alt, ts], ...], last_seen: ts}}
_trails_lock = threading.Lock()
_MAX_TRACKED_TRAILS = 2000

# Route enrichment is now served from services.fetchers.route_database, which
# bulk-loads vrs-standing-data.adsb.lol/routes.csv.gz once per day and looks up
# callsigns from an in-memory index. Replaces the legacy /api/0/routeset POST,
# which was both blocked under the ShadowBroker UA (HTTP 451) and broken
# upstream (returning 201 with empty body even for unblocked clients).


def _fetch_supplemental_sources(seen_hex: set) -> list:
    """Fetch from airplanes.live and adsb.fi to fill blind-spot gaps."""
    global last_supplemental_fetch, cached_supplemental_flights

    now = time.time()
    with _supplemental_cache_lock:
        if now - last_supplemental_fetch < _SUPPLEMENTAL_FETCH_INTERVAL:
            return [
                f
                for f in cached_supplemental_flights
                if f.get("hex", "").lower().strip() not in seen_hex
            ]

    new_supplemental = []
    supplemental_hex = set()

    def _fetch_airplaneslive(region):
        try:
            url = (
                f"https://api.airplanes.live/v2/point/"
                f"{region['lat']}/{region['lon']}/{region['radius_nm']}"
            )
            res = fetch_with_curl(url, timeout=10)
            if res.status_code == 200:
                data = res.json()
                return data.get("ac", [])
        except (
            requests.RequestException,
            ConnectionError,
            TimeoutError,
            ValueError,
            KeyError,
            json.JSONDecodeError,
            OSError,
        ) as e:
            logger.debug(f"airplanes.live {region['name']} failed: {e}")
        return []

    try:
        for idx, region in enumerate(_BLIND_SPOT_REGIONS):
            region_flights = _fetch_airplaneslive(region)
            for f in region_flights:
                h = f.get("hex", "").lower().strip()
                if h and h not in seen_hex and h not in supplemental_hex:
                    f["supplemental_source"] = "airplanes.live"
                    new_supplemental.append(f)
                    supplemental_hex.add(h)
            if idx < len(_BLIND_SPOT_REGIONS) - 1:
                time.sleep(
                    _AIRPLANES_LIVE_DELAY_SECONDS
                    + random.uniform(0.0, _AIRPLANES_LIVE_DELAY_JITTER_SECONDS)
                )
    except (
        requests.RequestException,
        ConnectionError,
        TimeoutError,
        ValueError,
        KeyError,
        OSError,
    ) as e:
        logger.warning(f"airplanes.live supplemental fetch failed: {e}")

    ap_count = len(new_supplemental)

    try:
        for region in _BLIND_SPOT_REGIONS:
            try:
                url = (
                    f"https://opendata.adsb.fi/api/v3/lat/"
                    f"{region['lat']}/lon/{region['lon']}/dist/{region['radius_nm']}"
                )
                res = fetch_with_curl(url, timeout=10)
                if res.status_code == 200:
                    data = res.json()
                    for f in data.get("ac", []):
                        h = f.get("hex", "").lower().strip()
                        if h and h not in seen_hex and h not in supplemental_hex:
                            f["supplemental_source"] = "adsb.fi"
                            new_supplemental.append(f)
                            supplemental_hex.add(h)
            except (
                requests.RequestException,
                ConnectionError,
                TimeoutError,
                ValueError,
                KeyError,
                json.JSONDecodeError,
                OSError,
            ) as e:
                logger.debug(f"adsb.fi {region['name']} failed: {e}")
            time.sleep(1.1)
    except (
        requests.RequestException,
        ConnectionError,
        TimeoutError,
        ValueError,
        KeyError,
        OSError,
    ) as e:
        logger.warning(f"adsb.fi supplemental fetch failed: {e}")

    fi_count = len(new_supplemental) - ap_count

    with _supplemental_cache_lock:
        cached_supplemental_flights = new_supplemental
        last_supplemental_fetch = now
    if new_supplemental:
        _mark_fresh("supplemental_flights")

    logger.info(
        f"Supplemental: +{len(new_supplemental)} new aircraft from blind-spot "
        f"hotspots (airplanes.live: {ap_count}, adsb.fi: {fi_count})"
    )
    return new_supplemental


def _classify_and_publish(all_adsb_flights):
    """Shared pipeline: normalize raw ADS-B data → classify → merge → publish to latest_data.

    Called once immediately after adsb.lol returns (fast path, ~3-5s),
    then again after OpenSky + supplemental gap-fill enrichment.
    """
    flights = []

    if not all_adsb_flights:
        return

    for f in all_adsb_flights:
        try:
            lat = f.get("lat")
            lng = f.get("lon")
            heading = f.get("track") or 0

            if lat is None or lng is None:
                continue

            flight_str = str(f.get("flight", "UNKNOWN")).strip()
            if not flight_str or flight_str == "UNKNOWN":
                flight_str = str(f.get("hex", "Unknown"))

            origin_loc = None
            dest_loc = None
            origin_name = "UNKNOWN"
            dest_name = "UNKNOWN"

            cached_route = lookup_route(flight_str)
            if cached_route:
                origin_name = cached_route["orig_name"]
                dest_name = cached_route["dest_name"]
                origin_loc = cached_route["orig_loc"]
                dest_loc = cached_route["dest_loc"]

            airline_code = ""
            match = _RE_AIRLINE_CODE_1.match(flight_str)
            if not match:
                match = _RE_AIRLINE_CODE_2.match(flight_str)
            if match:
                airline_code = match.group(1)

            alt_raw = f.get("alt_baro")
            alt_value = 0
            if isinstance(alt_raw, (int, float)):
                alt_value = alt_raw * 0.3048

            gs_knots = f.get("gs")
            speed_knots = round(gs_knots, 1) if isinstance(gs_knots, (int, float)) else None

            # OpenSky's /states/all doesn't carry the aircraft type, so its
            # records arrive with t="Unknown". Backfill from the OpenSky
            # aircraft metadata DB by ICAO24 hex so heli classification and
            # downstream emissions enrichment both see a real type code.
            raw_type = str(f.get("t") or "").strip()
            if not raw_type or raw_type.lower() == "unknown":
                looked_up_type = lookup_aircraft_type(f.get("hex", ""))
                if looked_up_type:
                    f["t"] = looked_up_type
                    raw_type = looked_up_type

            model_upper = raw_type.upper()
            if model_upper == "TWR":
                continue

            ac_category = "heli" if model_upper in _HELI_TYPES_BACKEND else "plane"

            flights.append(
                {
                    "callsign": flight_str,
                    "country": f.get("r", "N/A"),
                    "lng": float(lng),
                    "lat": float(lat),
                    "alt": alt_value,
                    "heading": heading,
                    "type": "flight",
                    "origin_loc": origin_loc,
                    "dest_loc": dest_loc,
                    "origin_name": origin_name,
                    "dest_name": dest_name,
                    "registration": f.get("r", "N/A"),
                    "model": f.get("t", "Unknown"),
                    "icao24": f.get("hex", ""),
                    "speed_knots": speed_knots,
                    "squawk": f.get("squawk", ""),
                    "airline_code": airline_code,
                    "aircraft_category": ac_category,
                    "nac_p": f.get("nac_p"),
                }
            )
        except (ValueError, TypeError, KeyError, AttributeError) as loop_e:
            logger.error(f"Flight interpolation error: {loop_e}")
            continue

    # --- Classification ---
    commercial = []
    private_jets = []
    private_ga = []
    tracked = []

    for f in flights:
        enrich_with_plane_alert(f)
        enrich_with_tracked_names(f)
        # Attach fuel-burn / CO2 emissions estimate when model is known.
        # OpenSky's /states/all doesn't carry aircraft type, so OpenSky-sourced
        # flights arrive with model="Unknown". For tracked planes, the
        # Plane-Alert DB has the friendly type name in alert_type, and the
        # emissions aliases table already maps those names to ICAO codes.
        model = f.get("model")
        if not model or model.strip().lower() in {"", "unknown"}:
            model = f.get("alert_type") or ""
        if model:
            emi = get_emissions_info(model)
            if emi:
                f["emissions"] = emi

        callsign = f.get("callsign", "").strip().upper()
        is_commercial_format = bool(re.match(r"^[A-Z]{3}\d{1,4}[A-Z]{0,2}$", callsign))

        if f.get("alert_category"):
            f["type"] = "tracked_flight"
            tracked.append(f)
        elif f.get("airline_code") or is_commercial_format:
            f["type"] = "commercial_flight"
            commercial.append(f)
        elif f.get("model", "").upper() in PRIVATE_JET_TYPES:
            f["type"] = "private_jet"
            private_jets.append(f)
        else:
            f["type"] = "private_ga"
            private_ga.append(f)

    # --- Smart merge: protect against partial API failures ---
    with _data_lock:
        prev_commercial_count = len(latest_data.get("commercial_flights", []))
        prev_private_jets_count = len(latest_data.get("private_jets", []))
        prev_private_flights_count = len(latest_data.get("private_flights", []))
    prev_total = prev_commercial_count + prev_private_jets_count + prev_private_flights_count
    new_total = len(commercial) + len(private_jets) + len(private_ga)

    if new_total == 0:
        logger.warning("No civilian flights found! Skipping overwrite to prevent clearing the map.")
    elif prev_total > 100 and new_total < prev_total * 0.5:
        logger.warning(
            f"Flight count dropped from {prev_total} to {new_total} (>50% loss). Keeping previous data to prevent flicker."
        )
    else:
        _now = time.time()

        def _merge_category(new_list, old_list, max_stale_s=120):
            by_icao = {}
            for f in old_list:
                icao = f.get("icao24", "")
                if icao:
                    f.setdefault("_seen_at", _now)
                    if (_now - f.get("_seen_at", _now)) < max_stale_s:
                        by_icao[icao] = f
            for f in new_list:
                icao = f.get("icao24", "")
                if icao:
                    f["_seen_at"] = _now
                    by_icao[icao] = f
                else:
                    continue
            return list(by_icao.values())

        with _data_lock:
            latest_data["commercial_flights"] = _merge_category(
                commercial, latest_data.get("commercial_flights", [])
            )
            latest_data["private_jets"] = _merge_category(
                private_jets, latest_data.get("private_jets", [])
            )
            latest_data["private_flights"] = _merge_category(
                private_ga, latest_data.get("private_flights", [])
            )

    _mark_fresh("commercial_flights", "private_jets", "private_flights")

    with _data_lock:
        if flights:
            latest_data["flights"] = flights

    # Merge tracked civilian flights with tracked military flights
    # Stale tracked flights (not seen in any ADS-B source for >5 min) are dropped.
    _TRACKED_STALE_S = 300  # 5 minutes
    _merge_ts = time.time()

    with _data_lock:
        existing_tracked = copy.deepcopy(latest_data.get("tracked_flights", []))

    fresh_tracked_map = {}
    for t in tracked:
        icao = t.get("icao24", "").upper()
        if icao:
            t["_seen_at"] = _merge_ts
            fresh_tracked_map[icao] = t

    merged_tracked = []
    seen_icaos = set()
    stale_dropped = 0
    for old_t in existing_tracked:
        icao = old_t.get("icao24", "").upper()
        if icao in fresh_tracked_map:
            fresh = fresh_tracked_map[icao]
            for key in ("alert_category", "alert_operator", "alert_special", "alert_flag"):
                if key in old_t and key not in fresh:
                    fresh[key] = old_t[key]
            merged_tracked.append(fresh)
            seen_icaos.add(icao)
        else:
            # Keep stale entry only if it was seen recently
            age = _merge_ts - old_t.get("_seen_at", 0)
            if age < _TRACKED_STALE_S:
                merged_tracked.append(old_t)
                seen_icaos.add(icao)
            else:
                stale_dropped += 1

    for icao, t in fresh_tracked_map.items():
        if icao not in seen_icaos:
            merged_tracked.append(t)

    with _data_lock:
        latest_data["tracked_flights"] = merged_tracked
    logger.info(
        f"Tracked flights: {len(merged_tracked)} total ({len(fresh_tracked_map)} fresh from civilian, {stale_dropped} stale dropped)"
    )

    # --- Trail Accumulation ---
    _TRAIL_INTERVAL_S = 600  # only record a new trail point every 10 minutes

    def _accumulate_trail(f, now_ts, check_route=True):
        hex_id = f.get("icao24", "").lower()
        if not hex_id:
            return 0, None
        if check_route and f.get("origin_name", "UNKNOWN") != "UNKNOWN":
            f["trail"] = []
            return 0, hex_id
        lat, lng, alt = f.get("lat"), f.get("lng"), f.get("alt", 0)
        if lat is None or lng is None:
            f["trail"] = flight_trails.get(hex_id, {}).get("points", [])
            return 0, hex_id
        point = [round(lat, 5), round(lng, 5), round(alt, 1), round(now_ts)]
        if hex_id not in flight_trails:
            flight_trails[hex_id] = {"points": [], "last_seen": now_ts}
        trail_data = flight_trails[hex_id]
        # Only append a new point if 10 minutes have passed since the last one
        last_point_ts = trail_data["points"][-1][3] if trail_data["points"] else 0
        if now_ts - last_point_ts < _TRAIL_INTERVAL_S:
            trail_data["last_seen"] = now_ts
        elif (
            trail_data["points"]
            and trail_data["points"][-1][0] == point[0]
            and trail_data["points"][-1][1] == point[1]
        ):
            trail_data["last_seen"] = now_ts
        else:
            trail_data["points"].append(point)
            trail_data["last_seen"] = now_ts
        if len(trail_data["points"]) > 200:
            trail_data["points"] = trail_data["points"][-200:]
        f["trail"] = trail_data["points"]
        return 1, hex_id

    now_ts = datetime.utcnow().timestamp()
    with _data_lock:
        military_snapshot = copy.deepcopy(latest_data.get("military_flights", []))
        tracked_snapshot = copy.deepcopy(latest_data.get("tracked_flights", []))
        raw_flights_snapshot = list(latest_data.get("flights", []))

    # Commercial/private: skip trail if route is known (route line replaces trail)
    route_check_lists = [commercial, private_jets, private_ga]
    # Tracked + military: ALWAYS accumulate trails (high-interest flights)
    always_trail_lists = [existing_tracked, military_snapshot]
    seen_hexes = set()
    trail_count = 0
    with _trails_lock:
        for flist in route_check_lists:
            for f in flist:
                count, hex_id = _accumulate_trail(f, now_ts, check_route=True)
                trail_count += count
                if hex_id:
                    seen_hexes.add(hex_id)

        for flist in always_trail_lists:
            for f in flist:
                count, hex_id = _accumulate_trail(f, now_ts, check_route=False)
                trail_count += count
                if hex_id:
                    seen_hexes.add(hex_id)

        tracked_hexes = {t.get("icao24", "").lower() for t in tracked_snapshot}
        stale_keys = []
        for k, v in flight_trails.items():
            cutoff = now_ts - 1800 if k in tracked_hexes else now_ts - 300
            if v["last_seen"] < cutoff:
                stale_keys.append(k)
        for k in stale_keys:
            del flight_trails[k]

        if len(flight_trails) > _MAX_TRACKED_TRAILS:
            sorted_keys = sorted(flight_trails.keys(), key=lambda k: flight_trails[k]["last_seen"])
            evict_count = len(flight_trails) - _MAX_TRACKED_TRAILS
            for k in sorted_keys[:evict_count]:
                del flight_trails[k]

    logger.info(
        f"Trail accumulation: {trail_count} active trails, {len(stale_keys)} pruned, {len(flight_trails)} total"
    )

    # --- GPS Jamming Detection ---
    # Uses NACp (Navigation Accuracy Category – Position) from ADS-B to infer
    # GPS interference zones, similar to GPSJam.org / Flightradar24.
    # NACp < 8 = position accuracy worse than the FAA-mandated 0.05 NM.
    #
    # Denoising (to suppress false positives from old GA transponders):
    # 1. Skip nac_p == 0 ("unknown accuracy") — old transponders that never
    #    computed accuracy, NOT evidence of jamming.  Real jamming shows 1-7.
    # 2. Require minimum aircraft per grid cell for statistical validity.
    # 3. Subtract 1 from degraded count per cell (GPSJam's technique) so a
    #    single quirky transponder can't flag an entire zone.
    # 4. Require the adjusted ratio to exceed the threshold.
    try:
        jamming_grid = {}
        raw_flights = raw_flights_snapshot
        for rf in raw_flights:
            rlat = rf.get("lat")
            rlng = rf.get("lng") or rf.get("lon")
            if rlat is None or rlng is None:
                continue
            nacp = rf.get("nac_p")
            if nacp is None or nacp == 0:
                continue
            grid_key = f"{int(rlat)},{int(rlng)}"
            if grid_key not in jamming_grid:
                jamming_grid[grid_key] = {"degraded": 0, "total": 0}
            jamming_grid[grid_key]["total"] += 1
            if nacp < GPS_JAMMING_NACP_THRESHOLD:
                jamming_grid[grid_key]["degraded"] += 1

        jamming_zones = []
        for gk, counts in jamming_grid.items():
            if counts["total"] < GPS_JAMMING_MIN_AIRCRAFT:
                continue
            adjusted_degraded = max(counts["degraded"] - 1, 0)
            if adjusted_degraded == 0:
                continue
            ratio = adjusted_degraded / counts["total"]
            if ratio > GPS_JAMMING_MIN_RATIO:
                lat_i, lng_i = gk.split(",")
                severity = "low" if ratio < 0.5 else "medium" if ratio < 0.75 else "high"
                jamming_zones.append(
                    {
                        "lat": int(lat_i) + 0.5,
                        "lng": int(lng_i) + 0.5,
                        "severity": severity,
                        "ratio": round(ratio, 2),
                        "degraded": counts["degraded"],
                        "total": counts["total"],
                    }
                )
        with _data_lock:
            latest_data["gps_jamming"] = jamming_zones
        if jamming_zones:
            logger.info(f"GPS Jamming: {len(jamming_zones)} interference zones detected")
    except (ValueError, TypeError, KeyError, ZeroDivisionError) as e:
        logger.error(f"GPS Jamming detection error: {e}")
        with _data_lock:
            latest_data["gps_jamming"] = []

    # --- Holding Pattern Detection ---
    try:
        holding_count = 0
        all_flight_lists = [
            commercial,
            private_jets,
            private_ga,
            tracked_snapshot,
            military_snapshot,
        ]
        with _trails_lock:
            trails_snapshot = {k: v.get("points", [])[:] for k, v in flight_trails.items()}
        for flist in all_flight_lists:
            for f in flist:
                hex_id = f.get("icao24", "").lower()
                trail = trails_snapshot.get(hex_id, [])
                if len(trail) < 6:
                    f["holding"] = False
                    continue
                pts = trail[-8:]
                total_turn = 0.0
                prev_bearing = 0.0
                for i in range(1, len(pts)):
                    lat1, lng1 = math.radians(pts[i - 1][0]), math.radians(pts[i - 1][1])
                    lat2, lng2 = math.radians(pts[i][0]), math.radians(pts[i][1])
                    dlng = lng2 - lng1
                    x = math.sin(dlng) * math.cos(lat2)
                    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(
                        lat2
                    ) * math.cos(dlng)
                    bearing = math.degrees(math.atan2(x, y)) % 360
                    if i > 1:
                        delta = abs(bearing - prev_bearing)
                        if delta > 180:
                            delta = 360 - delta
                        total_turn += delta
                    prev_bearing = bearing
                f["holding"] = total_turn > 300
                if f["holding"]:
                    holding_count += 1
        if holding_count:
            logger.info(f"Holding patterns: {holding_count} aircraft circling")
    except (ValueError, TypeError, KeyError, ZeroDivisionError) as e:
        logger.error(f"Holding pattern detection error: {e}")

    with _data_lock:
        latest_data["last_updated"] = datetime.utcnow().isoformat()


def _fetch_adsb_lol_regions():
    """Fetch all adsb.lol regions in parallel (~3-5s). Returns raw aircraft list."""
    regions = [
        {"lat": 39.8, "lon": -98.5, "dist": 2000},
        {"lat": 50.0, "lon": 15.0, "dist": 2000},
        {"lat": 35.0, "lon": 105.0, "dist": 2000},
        {"lat": -25.0, "lon": 133.0, "dist": 2000},
        {"lat": 0.0, "lon": 20.0, "dist": 2500},
        {"lat": -15.0, "lon": -60.0, "dist": 2000},
    ]

    def _fetch_region(r):
        url = f"https://api.adsb.lol/v2/lat/{r['lat']}/lon/{r['lon']}/dist/{r['dist']}"
        try:
            res = fetch_with_curl(url, timeout=10)
            if res.status_code == 200:
                data = res.json()
                return data.get("ac", [])
        except (
            requests.RequestException,
            ConnectionError,
            TimeoutError,
            ValueError,
            KeyError,
            json.JSONDecodeError,
            OSError,
        ) as e:
            logger.warning(f"Region fetch failed for lat={r['lat']}: {e}")
        return []

    all_flights = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        results = pool.map(_fetch_region, regions)
    for region_flights in results:
        all_flights.extend(region_flights)
    return all_flights


def _enrich_with_opensky_and_supplemental(adsb_flights):
    """Slow enrichment: merge OpenSky gap-fill + supplemental sources, then re-publish.

    Runs in a background thread so the initial adsb.lol data is already visible.
    """
    try:
        seen_hex = set()
        for f in adsb_flights:
            h = f.get("hex")
            if h:
                seen_hex.add(h.lower().strip())

        all_flights = list(adsb_flights)  # copy to avoid mutating the original

        # OpenSky Regional Fallback
        now = time.time()
        global last_opensky_fetch, cached_opensky_flights

        with _opensky_cache_lock:
            _need_opensky = now - last_opensky_fetch > 300
            if not _need_opensky:
                opensky_snapshot = list(cached_opensky_flights)

        if _need_opensky:
            token = opensky_client.get_token()
            if token:
                # One global /states/all query = 4 credits flat per OpenSky
                # docs (https://openskynetwork.github.io/opensky-api/rest.html).
                # At the current 5-minute cadence that's 4 × 288 = 1152
                # credits/day, ~29% of the 4000-credit standard daily quota,
                # and returns every aircraft worldwide in a single call.
                # The previous 3-regional-bbox approach cost 12 credits/cycle
                # AND missed North America, Europe, and Oceania entirely.
                new_opensky_flights = []
                try:
                    os_url = "https://opensky-network.org/api/states/all"
                    headers = {"Authorization": f"Bearer {token}"}
                    os_res = requests.get(os_url, headers=headers, timeout=30)

                    if os_res.status_code == 200:
                        os_data = os_res.json()
                        states = os_data.get("states") or []
                        remaining = os_res.headers.get("X-Rate-Limit-Remaining", "?")
                        logger.info(
                            f"OpenSky: fetched {len(states)} global states "
                            f"(credits remaining: {remaining})"
                        )
                        for s in states:
                            if s[5] is None or s[6] is None:
                                continue
                            new_opensky_flights.append(
                                {
                                    "hex": s[0],
                                    "flight": s[1].strip() if s[1] else "UNKNOWN",
                                    "r": s[2],
                                    "lon": s[5],
                                    "lat": s[6],
                                    "alt_baro": (s[7] * 3.28084) if s[7] else 0,
                                    "track": s[10] or 0,
                                    "gs": (s[9] * 1.94384) if s[9] else 0,
                                    "t": "Unknown",
                                    "is_opensky": True,
                                }
                            )
                    elif os_res.status_code == 429:
                        retry_after = os_res.headers.get("X-Rate-Limit-Retry-After-Seconds", "?")
                        logger.warning(
                            f"OpenSky daily quota exhausted (4000 credits). "
                            f"Retry after {retry_after}s. Serving stale data until reset."
                        )
                    else:
                        logger.warning(
                            f"OpenSky /states/all failed: HTTP {os_res.status_code}"
                        )
                except (
                    requests.RequestException,
                    ConnectionError,
                    TimeoutError,
                    ValueError,
                    KeyError,
                    json.JSONDecodeError,
                    OSError,
                ) as ex:
                    logger.error(f"OpenSky global fetch error: {ex}")

                with _opensky_cache_lock:
                    if new_opensky_flights:
                        cached_opensky_flights = new_opensky_flights
                    last_opensky_fetch = now
                opensky_snapshot = new_opensky_flights or list(cached_opensky_flights)
            else:
                # Token refresh failed — fall back to existing cached data
                with _opensky_cache_lock:
                    opensky_snapshot = list(cached_opensky_flights)

        # Merge OpenSky (dedup by hex)
        for osf in opensky_snapshot:
            h = osf.get("hex")
            if h and h.lower().strip() not in seen_hex:
                all_flights.append(osf)
                seen_hex.add(h.lower().strip())

        # Publish OpenSky-merged data immediately so users see flights even if
        # supplemental gap-fill is slow or rate-limited (airplanes.live can take
        # 100+ seconds when its regional endpoints are throttled).
        if len(all_flights) > len(adsb_flights):
            logger.info(
                f"OpenSky merge: {len(all_flights) - len(adsb_flights)} additional aircraft, "
                "publishing before supplemental gap-fill"
            )
            _classify_and_publish(all_flights)

        # Supplemental gap-fill
        try:
            gap_fill = _fetch_supplemental_sources(seen_hex)
            for f in gap_fill:
                all_flights.append(f)
                h = f.get("hex", "").lower().strip()
                if h:
                    seen_hex.add(h)
            if gap_fill:
                logger.info(f"Gap-fill: added {len(gap_fill)} aircraft to pipeline")
        except (
            requests.RequestException,
            ConnectionError,
            TimeoutError,
            ValueError,
            KeyError,
            OSError,
        ) as e:
            logger.warning(f"Supplemental source fetch failed (non-fatal): {e}")

        # Re-publish with enriched data
        if len(all_flights) > len(adsb_flights):
            logger.info(
                f"Enrichment: {len(all_flights) - len(adsb_flights)} additional aircraft from OpenSky + supplemental"
            )
            _classify_and_publish(all_flights)
    except Exception as e:
        logger.error(f"OpenSky/supplemental enrichment error: {e}")


@with_retry(max_retries=1, base_delay=1)
def fetch_flights():
    """Two-phase flight fetching:
    Phase 1 (fast): Fetch adsb.lol → classify → publish immediately (~3-5s)
    Phase 2 (background): Merge OpenSky + supplemental → re-publish (~15-30s)
    """
    from services.fetchers._store import is_any_active

    if not is_any_active("flights", "private", "jets", "tracked", "gps_jamming"):
        return
    try:
        # Phase 1: adsb.lol — fast, parallel, publish immediately
        adsb_flights = _fetch_adsb_lol_regions()
        if adsb_flights:
            logger.info(f"adsb.lol: {len(adsb_flights)} aircraft — publishing immediately")
            _classify_and_publish(adsb_flights)
        else:
            logger.warning(
                "adsb.lol returned 0 aircraft — relying on OpenSky/supplemental sources"
            )

        # Phase 2: always run — OpenSky is the fallback when adsb.lol blocks us
        # (it has been known to 451 the bulk regional endpoint), and supplemental
        # gap-fill should always run regardless of Phase 1 success.
        threading.Thread(
            target=_enrich_with_opensky_and_supplemental,
            args=(adsb_flights,),
            daemon=True,
        ).start()
    except Exception as e:
        logger.error(f"Error fetching flights: {e}")
