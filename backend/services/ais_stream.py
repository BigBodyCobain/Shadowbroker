"""
AIS Stream WebSocket client for real-time maritime vessel tracking.
Connects to aisstream.io and maintains a live dictionary of global vessel positions.
"""

import asyncio
import json
import logging
import threading
import time
from datetime import datetime, timezone
import os

logger = logging.getLogger(__name__)

AIS_WS_URL = "wss://stream.aisstream.io/v0/stream"
API_KEY = os.environ.get("AIS_API_KEY", "")


# AIS vessel type code classification
# See: https://coast.noaa.gov/data/marinecadastre/ais/VesselTypeCodes2018.pdf
def classify_vessel(ais_type: int, mmsi: int) -> str:
    """Classify a vessel by its AIS type code into a rendering category."""
    if 80 <= ais_type <= 89:
        return "tanker"  # Oil/Chemical/Gas tankers → RED
    if 70 <= ais_type <= 79:
        return "cargo"  # Cargo ships, container vessels → RED
    if 60 <= ais_type <= 69:
        return "passenger"  # Cruise ships, ferries → GRAY
    if ais_type in (36, 37):
        return "yacht"  # Sailing/Pleasure craft → DARK BLUE
    if ais_type == 35:
        return "military_vessel"  # Military → YELLOW
    # MMSI-based military detection: military MMSIs often start with certain prefixes
    mmsi_str = str(mmsi)
    if mmsi_str.startswith("3380") or mmsi_str.startswith("3381"):
        return "military_vessel"  # US Navy
    if ais_type in (30, 31, 32, 33, 34):
        return "other"  # Fishing, towing, dredging, diving, etc.
    if ais_type in (50, 51, 52, 53, 54, 55, 56, 57, 58, 59):
        return "other"  # Pilot, SAR, tug, port tender, etc.
    return "unknown"  # Not yet classified — will update when ShipStaticData arrives


# MMSI Maritime Identification Digit (MID) → Country mapping
# First 3 digits of MMSI (for 9-digit MMSIs) encode the flag state
MID_COUNTRY = {
    201: "Albania",
    202: "Andorra",
    203: "Austria",
    204: "Portugal",
    205: "Belgium",
    206: "Belarus",
    207: "Bulgaria",
    208: "Vatican",
    209: "Cyprus",
    210: "Cyprus",
    211: "Germany",
    212: "Cyprus",
    213: "Georgia",
    214: "Moldova",
    215: "Malta",
    216: "Armenia",
    218: "Germany",
    219: "Denmark",
    220: "Denmark",
    224: "Spain",
    225: "Spain",
    226: "France",
    227: "France",
    228: "France",
    229: "Malta",
    230: "Finland",
    231: "Faroe Islands",
    232: "United Kingdom",
    233: "United Kingdom",
    234: "United Kingdom",
    235: "United Kingdom",
    236: "Gibraltar",
    237: "Greece",
    238: "Croatia",
    239: "Greece",
    240: "Greece",
    241: "Greece",
    242: "Morocco",
    243: "Hungary",
    244: "Netherlands",
    245: "Netherlands",
    246: "Netherlands",
    247: "Italy",
    248: "Malta",
    249: "Malta",
    250: "Ireland",
    251: "Iceland",
    252: "Liechtenstein",
    253: "Luxembourg",
    254: "Monaco",
    255: "Portugal",
    256: "Malta",
    257: "Norway",
    258: "Norway",
    259: "Norway",
    261: "Poland",
    263: "Portugal",
    264: "Romania",
    265: "Sweden",
    266: "Sweden",
    267: "Slovakia",
    268: "San Marino",
    269: "Switzerland",
    270: "Czech Republic",
    271: "Turkey",
    272: "Ukraine",
    273: "Russia",
    274: "North Macedonia",
    275: "Latvia",
    276: "Estonia",
    277: "Lithuania",
    278: "Slovenia",
    301: "Anguilla",
    303: "Alaska",
    304: "Antigua",
    305: "Antigua",
    306: "Netherlands Antilles",
    307: "Aruba",
    308: "Bahamas",
    309: "Bahamas",
    310: "Bermuda",
    311: "Bahamas",
    312: "Belize",
    314: "Barbados",
    316: "Canada",
    319: "Cayman Islands",
    321: "Costa Rica",
    323: "Cuba",
    325: "Dominica",
    327: "Dominican Republic",
    329: "Guadeloupe",
    330: "Grenada",
    331: "Greenland",
    332: "Guatemala",
    334: "Honduras",
    336: "Haiti",
    338: "United States",
    339: "Jamaica",
    341: "Saint Kitts",
    343: "Saint Lucia",
    345: "Mexico",
    347: "Martinique",
    348: "Montserrat",
    350: "Nicaragua",
    351: "Panama",
    352: "Panama",
    353: "Panama",
    354: "Panama",
    355: "Panama",
    356: "Panama",
    357: "Panama",
    358: "Puerto Rico",
    359: "El Salvador",
    361: "Saint Pierre",
    362: "Trinidad",
    364: "Turks and Caicos",
    366: "United States",
    367: "United States",
    368: "United States",
    369: "United States",
    370: "Panama",
    371: "Panama",
    372: "Panama",
    373: "Panama",
    374: "Panama",
    375: "Saint Vincent",
    376: "Saint Vincent",
    377: "Saint Vincent",
    378: "British Virgin Islands",
    379: "US Virgin Islands",
    401: "Afghanistan",
    403: "Saudi Arabia",
    405: "Bangladesh",
    408: "Bahrain",
    410: "Bhutan",
    412: "China",
    413: "China",
    414: "China",
    416: "Taiwan",
    417: "Sri Lanka",
    419: "India",
    422: "Iran",
    423: "Azerbaijan",
    425: "Iraq",
    428: "Israel",
    431: "Japan",
    432: "Japan",
    434: "Turkmenistan",
    436: "Kazakhstan",
    437: "Uzbekistan",
    438: "Jordan",
    440: "South Korea",
    441: "South Korea",
    443: "Palestine",
    445: "North Korea",
    447: "Kuwait",
    450: "Lebanon",
    451: "Kyrgyzstan",
    453: "Macao",
    455: "Maldives",
    457: "Mongolia",
    459: "Nepal",
    461: "Oman",
    463: "Pakistan",
    466: "Qatar",
    468: "Syria",
    470: "UAE",
    472: "Tajikistan",
    473: "Yemen",
    475: "Tonga",
    477: "Hong Kong",
    478: "Bosnia",
    501: "Antarctica",
    503: "Australia",
    506: "Myanmar",
    508: "Brunei",
    510: "Micronesia",
    511: "Palau",
    512: "New Zealand",
    514: "Cambodia",
    515: "Cambodia",
    516: "Christmas Island",
    518: "Cook Islands",
    520: "Fiji",
    523: "Cocos Islands",
    525: "Indonesia",
    529: "Kiribati",
    531: "Laos",
    533: "Malaysia",
    536: "Northern Mariana Islands",
    538: "Marshall Islands",
    540: "New Caledonia",
    542: "Niue",
    544: "Nauru",
    546: "French Polynesia",
    548: "Philippines",
    553: "Papua New Guinea",
    555: "Pitcairn",
    557: "Solomon Islands",
    559: "American Samoa",
    561: "Samoa",
    563: "Singapore",
    564: "Singapore",
    565: "Singapore",
    566: "Singapore",
    567: "Thailand",
    570: "Tonga",
    572: "Tuvalu",
    574: "Vietnam",
    576: "Vanuatu",
    577: "Vanuatu",
    578: "Wallis and Futuna",
    601: "South Africa",
    603: "Angola",
    605: "Algeria",
    607: "Benin",
    609: "Botswana",
    610: "Burundi",
    611: "Cameroon",
    612: "Cape Verde",
    613: "Central African Republic",
    615: "Congo",
    616: "Comoros",
    617: "DR Congo",
    618: "Ivory Coast",
    619: "Djibouti",
    620: "Egypt",
    621: "Equatorial Guinea",
    622: "Ethiopia",
    624: "Eritrea",
    625: "Gabon",
    626: "Gambia",
    627: "Ghana",
    629: "Guinea",
    630: "Guinea-Bissau",
    631: "Kenya",
    632: "Lesotho",
    633: "Liberia",
    634: "Liberia",
    635: "Liberia",
    636: "Liberia",
    637: "Libya",
    642: "Madagascar",
    644: "Malawi",
    645: "Mali",
    647: "Mauritania",
    649: "Mauritius",
    650: "Mozambique",
    654: "Namibia",
    655: "Niger",
    656: "Nigeria",
    657: "Guinea",
    659: "Rwanda",
    660: "Senegal",
    661: "Sierra Leone",
    662: "Somalia",
    663: "South Africa",
    664: "Sudan",
    667: "Tanzania",
    668: "Togo",
    669: "Tunisia",
    670: "Uganda",
    671: "Egypt",
    672: "Tanzania",
    674: "Zambia",
    675: "Zimbabwe",
    676: "Comoros",
    677: "Tanzania",
}


def get_country_from_mmsi(mmsi: int) -> str:
    """Look up flag state from MMSI Maritime Identification Digit."""
    mmsi_str = str(mmsi)
    if len(mmsi_str) == 9:
        mid = int(mmsi_str[:3])
        return MID_COUNTRY.get(mid, "UNKNOWN")
    return "UNKNOWN"


# Global vessel store: MMSI → vessel dict
_vessels: dict[int, dict] = {}
_vessels_lock = threading.Lock()
_ws_thread: threading.Thread | None = None
_ws_running = False
_proxy_process = None

import os

CACHE_FILE = os.path.join(os.path.dirname(__file__), "ais_cache.json")


def _save_cache():
    """Save vessel data to disk for persistence across restarts."""
    try:
        with _vessels_lock:
            # Convert int keys to strings for JSON
            data = {str(k): v for k, v in _vessels.items()}
        with open(CACHE_FILE, "w") as f:
            json.dump(data, f)
        logger.info(f"AIS cache saved: {len(data)} vessels")
    except (IOError, OSError) as e:
        logger.error(f"Failed to save AIS cache: {e}")


def _load_cache():
    """Load vessel data from disk on startup."""
    global _vessels
    if not os.path.exists(CACHE_FILE):
        return
    try:
        with open(CACHE_FILE, "r") as f:
            data = json.load(f)
        now = time.time()
        stale_cutoff = now - 3600  # Accept vessels up to 1 hour old on restart
        loaded = 0
        with _vessels_lock:
            for k, v in data.items():
                if v.get("_updated", 0) > stale_cutoff:
                    _vessels[int(k)] = v
                    loaded += 1
        logger.info(f"AIS cache loaded: {loaded} vessels from disk")
    except (IOError, OSError, json.JSONDecodeError, ValueError) as e:
        logger.error(f"Failed to load AIS cache: {e}")


def prune_stale_vessels():
    """Remove vessels not updated in the last 15 minutes. Safe to call from a scheduler."""
    now = time.time()
    stale_cutoff = now - 900
    with _vessels_lock:
        stale_keys = [k for k, v in _vessels.items() if v.get("_updated", 0) < stale_cutoff]
        for k in stale_keys:
            del _vessels[k]
    if stale_keys:
        logger.info(f"AIS pruned {len(stale_keys)} stale vessels")


def get_ais_vessels() -> list[dict]:
    """Return a snapshot of tracked AIS vessels, pruning stale."""
    prune_stale_vessels()

    with _vessels_lock:
        result = []
        for mmsi, v in _vessels.items():
            v_type = v.get("type", "unknown")
            # Skip vessels without valid position
            if not v.get("lat") or not v.get("lng"):
                continue

            # Sanitize speed: AIS 102.3 kn = "speed not available"
            sog = v.get("sog", 0)
            if sog >= 102.2:
                sog = 0

            result.append(
                {
                    "mmsi": mmsi,
                    "name": v.get("name", "UNKNOWN"),
                    "type": v_type,
                    "lat": round(v.get("lat", 0), 5),
                    "lng": round(v.get("lng", 0), 5),
                    "heading": v.get("heading", 0),
                    "sog": round(sog, 1),
                    "cog": round(v.get("cog", 0), 1),
                    "callsign": v.get("callsign", ""),
                    "destination": v.get("destination", "") or "UNKNOWN",
                    "imo": v.get("imo", 0),
                    "country": get_country_from_mmsi(mmsi),
                }
            )
        return result


def ingest_ais_catcher(msgs: list[dict]) -> int:
    """Ingest decoded AIS messages from AIS-catcher HTTP feed.
    Returns number of vessels updated."""
    count = 0
    now = time.time()
    with _vessels_lock:
        for msg in msgs:
            mmsi = msg.get("mmsi")
            if not mmsi or not isinstance(mmsi, int):
                continue

            vessel = _vessels.setdefault(mmsi, {"mmsi": mmsi})
            msg_type = msg.get("type", 0)

            # Position reports (types 1, 2, 3 = Class A; 18, 19 = Class B)
            if msg_type in (1, 2, 3, 18, 19):
                lat = msg.get("lat")
                lon = msg.get("lon")
                if lat is not None and lon is not None and lat != 91.0 and lon != 181.0:
                    vessel["lat"] = lat
                    vessel["lng"] = lon
                    # AIS raw value 1023 (102.3 kn) = "speed not available"
                    raw_speed = msg.get("speed", 0)
                    vessel["sog"] = 0 if raw_speed >= 102.2 else raw_speed
                    vessel["cog"] = msg.get("course", 0)
                    heading = msg.get("heading", 511)
                    vessel["heading"] = heading if heading != 511 else vessel.get("cog", 0)
                    vessel["_updated"] = now
                    if msg.get("shipname"):
                        vessel["name"] = msg["shipname"].strip()
                    count += 1

            # Static data (type 5 = Class A static; 24 = Class B static)
            elif msg_type in (5, 24):
                if msg.get("shipname"):
                    vessel["name"] = msg["shipname"].strip()
                if msg.get("callsign"):
                    vessel["callsign"] = msg["callsign"].strip()
                if msg.get("imo"):
                    vessel["imo"] = msg["imo"]
                if msg.get("destination"):
                    vessel["destination"] = msg["destination"].strip().replace("@", "")
                ship_type = msg.get("shiptype", 0)
                if ship_type:
                    vessel["ais_type_code"] = ship_type
                    vessel["type"] = classify_vessel(ship_type, mmsi)
                vessel["_updated"] = now

            # Ensure country is set from MMSI MID
            if "country" not in vessel:
                vessel["country"] = get_country_from_mmsi(mmsi)

            # Ensure name exists
            if "name" not in vessel:
                vessel["name"] = msg.get("shipname", "UNKNOWN") or "UNKNOWN"

    return count


def _ais_stream_loop():
    """Main loop: spawn node proxy and process messages from stdout."""
    global _proxy_process
    import subprocess
    import os

    proxy_script = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ais_proxy.js")
    backoff = 1  # Exponential backoff starting at 1 second

    if not API_KEY:
        logger.info("AIS_API_KEY not set — ship tracking disabled. Set AIS_API_KEY to enable.")
        return

    while _ws_running:
        try:
            logger.info("Starting Node.js AIS Stream Proxy...")
            proxy_env = os.environ.copy()
            proxy_env["AIS_API_KEY"] = API_KEY
            process = subprocess.Popen(
                ["node", proxy_script],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                env=proxy_env,
            )
            with _vessels_lock:
                _proxy_process = process

            # Drain stderr in a background thread to prevent deadlock
            import threading

            def _drain_stderr():
                for errline in iter(process.stderr.readline, ""):
                    errline = errline.strip()
                    if errline:
                        logger.warning(f"AIS proxy stderr: {errline}")

            threading.Thread(target=_drain_stderr, daemon=True).start()

            logger.info("AIS Stream proxy started — receiving vessel data")

            msg_count = 0
            ok_streak = 0  # Track consecutive successful messages for backoff reset
            last_log_time = time.time()
            for raw_msg in iter(process.stdout.readline, ""):
                if not _ws_running:
                    process.terminate()
                    break

                raw_msg = raw_msg.strip()
                if not raw_msg:
                    continue

                try:
                    data = json.loads(raw_msg)
                except json.JSONDecodeError:
                    continue

                if "error" in data:
                    logger.error(f"AIS Stream error: {data['error']}")
                    continue

                msg_type = data.get("MessageType", "")
                metadata = data.get("MetaData", {})
                message = data.get("Message", {})

                mmsi = metadata.get("MMSI", 0)
                if not mmsi:
                    continue

                with _vessels_lock:
                    if mmsi not in _vessels:
                        _vessels[mmsi] = {"_updated": time.time()}
                    vessel = _vessels[mmsi]

                # Update position from PositionReport or StandardClassBPositionReport
                if msg_type in ("PositionReport", "StandardClassBPositionReport"):
                    report = message.get(msg_type, {})
                    lat = report.get("Latitude", metadata.get("latitude", 0))
                    lng = report.get("Longitude", metadata.get("longitude", 0))

                    # Skip invalid positions
                    if lat == 0 and lng == 0:
                        continue
                    if abs(lat) > 90 or abs(lng) > 180:
                        continue

                    with _vessels_lock:
                        vessel["lat"] = lat
                        vessel["lng"] = lng
                        # AIS raw value 1023 (102.3 kn) = "speed not available"
                        raw_sog = report.get("Sog", 0)
                        vessel["sog"] = 0 if raw_sog >= 102.2 else raw_sog
                        vessel["cog"] = report.get("Cog", 0)
                        heading = report.get("TrueHeading", 511)
                        vessel["heading"] = heading if heading != 511 else report.get("Cog", 0)
                        vessel["_updated"] = time.time()
                        # Use metadata name if we don't have one yet
                        if not vessel.get("name") or vessel["name"] == "UNKNOWN":
                            vessel["name"] = (
                                metadata.get("ShipName", "UNKNOWN").strip() or "UNKNOWN"
                            )

                # Update static data from ShipStaticData
                elif msg_type == "ShipStaticData":
                    static = message.get("ShipStaticData", {})
                    ais_type = static.get("Type", 0)

                    with _vessels_lock:
                        vessel["name"] = (
                            static.get("Name", "") or metadata.get("ShipName", "UNKNOWN")
                        ).strip() or "UNKNOWN"
                        vessel["callsign"] = (static.get("CallSign", "") or "").strip()
                        vessel["imo"] = static.get("ImoNumber", 0)
                        vessel["destination"] = (
                            (static.get("Destination", "") or "").strip().replace("@", "")
                        )
                        vessel["ais_type_code"] = ais_type
                        vessel["type"] = classify_vessel(ais_type, mmsi)
                        vessel["_updated"] = time.time()

                msg_count += 1
                ok_streak += 1

                # Reset backoff after 200 consecutive successful messages
                if ok_streak >= 200 and backoff > 1:
                    backoff = 1
                    ok_streak = 0

                # Periodic logging + cache save (time-based instead of count-based to avoid lock in hot loop)
                now = time.time()
                if now - last_log_time >= 60:
                    with _vessels_lock:
                        count = len(_vessels)
                    logger.info(
                        f"AIS Stream: processed {msg_count} messages, tracking {count} vessels"
                    )
                    _save_cache()
                    last_log_time = now

        except (ConnectionError, TimeoutError, OSError, ValueError, KeyError) as e:
            logger.error(f"AIS proxy connection error: {e}")
            if _ws_running:
                logger.info(f"Restarting AIS proxy in {backoff}s (exponential backoff)...")
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)  # Double up to 60s max
            continue


def _run_ais_loop():
    """Thread target: run the AIS loop."""
    global _ws_running, _ws_thread, _proxy_process
    try:
        _ais_stream_loop()
    except Exception as e:
        logger.error(f"AIS Stream thread crashed: {e}")
    finally:
        with _vessels_lock:
            _ws_running = False
            _ws_thread = None
            _proxy_process = None


def start_ais_stream():
    """Start the AIS WebSocket stream in a background thread."""
    global _ws_thread, _ws_running
    with _vessels_lock:
        if _ws_running:
            logger.info("AIS Stream already running")
            return
        _ws_running = True
        existing_thread = _ws_thread
    if existing_thread and existing_thread.is_alive():
        logger.info("AIS Stream already running")
        return

    # Load cached vessel data from disk
    _load_cache()

    _ws_thread = threading.Thread(target=_run_ais_loop, daemon=True, name="ais-stream")
    _ws_thread.start()
    logger.info("AIS Stream background thread started")


def stop_ais_stream():
    """Stop the AIS WebSocket stream and save cache."""
    global _ws_running, _ws_thread, _proxy_process
    with _vessels_lock:
        _ws_running = False
        _ws_thread = None
        proc = _proxy_process
        _proxy_process = None

    if proc and proc.stdin:
        try:
            proc.stdin.close()
        except Exception:
            pass

    _save_cache()  # Save on shutdown
    logger.info("AIS Stream stopping...")


def update_ais_bbox(south: float, west: float, north: float, east: float):
    """Dynamically update the AIS stream bounding box via proxy stdin."""
    with _vessels_lock:
        proc = _proxy_process
    if not proc or not proc.stdin:
        return

    try:
        cmd = json.dumps({"type": "update_bbox", "bboxes": [[[south, west], [north, east]]]})
        proc.stdin.write(cmd + "\n")
        proc.stdin.flush()
        logger.info(
            f"Updated AIS bounding box to: S:{south:.2f} W:{west:.2f} N:{north:.2f} E:{east:.2f}"
        )
    except Exception as e:
        logger.error(f"Failed to update AIS bbox: {e}")
