"""Plane-Alert DB — load and enrich aircraft with tracked metadata."""

import os
import json
import logging

logger = logging.getLogger("services.data_fetcher")

# Exact category -> color mapping for all 53 known categories.
# O(1) dict lookup — no keyword scanning, no false positives.
_CATEGORY_COLOR: dict[str, str] = {
    # YELLOW — Military / Intelligence / Defense
    "USAF": "yellow",
    "Other Air Forces": "yellow",
    "Toy Soldiers": "yellow",
    "Oxcart": "yellow",
    "United States Navy": "yellow",
    "GAF": "yellow",
    "Hired Gun": "yellow",
    "United States Marine Corps": "yellow",
    "Gunship": "yellow",
    "RAF": "yellow",
    "Other Navies": "yellow",
    "Special Forces": "yellow",
    "Zoomies": "yellow",
    "Royal Navy Fleet Air Arm": "yellow",
    "Army Air Corps": "yellow",
    "Aerobatic Teams": "yellow",
    "UAV": "yellow",
    "Ukraine": "yellow",
    "Nuclear": "yellow",
    # LIME — Emergency / Medical / Rescue / Fire
    "Flying Doctors": "#32cd32",
    "Aerial Firefighter": "#32cd32",
    "Coastguard": "#32cd32",
    # BLUE — Government / Law Enforcement / Civil
    "Police Forces": "blue",
    "Governments": "blue",
    "Quango": "blue",
    "UK National Police Air Service": "blue",
    "CAP": "blue",
    # BLACK — Privacy / PIA
    "PIA": "black",
    # RED — Dictator / Oligarch
    "Dictator Alert": "red",
    "Da Comrade": "red",
    "Oligarch": "red",
    # HOT PINK — High Value Assets / VIP / Celebrity
    "Head of State": "#ff1493",
    "Royal Aircraft": "#ff1493",
    "Don't you know who I am?": "#ff1493",
    "As Seen on TV": "#ff1493",
    "Bizjets": "#ff1493",
    "Vanity Plate": "#ff1493",
    "Football": "#ff1493",
    # ORANGE — Joe Cool
    "Joe Cool": "orange",
    # WHITE — Climate Crisis
    "Climate Crisis": "white",
    # PURPLE — General Tracked / Other Notable
    "Historic": "purple",
    "Jump Johnny Jump": "purple",
    "Ptolemy would be proud": "purple",
    "Distinctive": "purple",
    "Dogs with Jobs": "purple",
    "You came here in that thing?": "purple",
    "Big Hello": "purple",
    "Watch Me Fly": "purple",
    "Perfectly Serviceable Aircraft": "purple",
    "Jesus he Knows me": "purple",
    "Gas Bags": "purple",
    "Radiohead": "purple",
}


def _category_to_color(cat: str) -> str:
    """O(1) exact lookup. Unknown categories default to purple."""
    return _CATEGORY_COLOR.get(cat, "purple")


_PLANE_ALERT_DB: dict = {}

# ---------------------------------------------------------------------------
# POTUS Fleet — override colors and operator names for presidential aircraft.
# ---------------------------------------------------------------------------
_POTUS_FLEET: dict[str, dict] = {
    "ADFDF8": {
        "color": "#ff1493",
        "operator": "Air Force One (82-8000)",
        "category": "Head of State",
        "wiki": "Air_Force_One",
        "fleet": "AF1",
    },
    "ADFDF9": {
        "color": "#ff1493",
        "operator": "Air Force One (92-9000)",
        "category": "Head of State",
        "wiki": "Air_Force_One",
        "fleet": "AF1",
    },
    "ADFEB7": {
        "color": "blue",
        "operator": "Air Force Two (98-0001)",
        "category": "Governments",
        "wiki": "Air_Force_Two",
        "fleet": "AF2",
    },
    "ADFEB8": {
        "color": "blue",
        "operator": "Air Force Two (98-0002)",
        "category": "Governments",
        "wiki": "Air_Force_Two",
        "fleet": "AF2",
    },
    "ADFEB9": {
        "color": "blue",
        "operator": "Air Force Two (99-0003)",
        "category": "Governments",
        "wiki": "Air_Force_Two",
        "fleet": "AF2",
    },
    "ADFEBA": {
        "color": "blue",
        "operator": "Air Force Two (99-0004)",
        "category": "Governments",
        "wiki": "Air_Force_Two",
        "fleet": "AF2",
    },
    "AE4AE6": {
        "color": "blue",
        "operator": "Air Force Two (09-0015)",
        "category": "Governments",
        "wiki": "Air_Force_Two",
        "fleet": "AF2",
    },
    "AE4AE8": {
        "color": "blue",
        "operator": "Air Force Two (09-0016)",
        "category": "Governments",
        "wiki": "Air_Force_Two",
        "fleet": "AF2",
    },
    "AE4AEA": {
        "color": "blue",
        "operator": "Air Force Two (09-0017)",
        "category": "Governments",
        "wiki": "Air_Force_Two",
        "fleet": "AF2",
    },
    "AE4AEC": {
        "color": "blue",
        "operator": "Air Force Two (19-0018)",
        "category": "Governments",
        "wiki": "Air_Force_Two",
        "fleet": "AF2",
    },
    "AE0865": {
        "color": "#ff1493",
        "operator": "Marine One (VH-3D)",
        "category": "Head of State",
        "wiki": "Marine_One",
        "fleet": "M1",
    },
    "AE5E76": {
        "color": "#ff1493",
        "operator": "Marine One (VH-92A)",
        "category": "Head of State",
        "wiki": "Marine_One",
        "fleet": "M1",
    },
    "AE5E77": {
        "color": "#ff1493",
        "operator": "Marine One (VH-92A)",
        "category": "Head of State",
        "wiki": "Marine_One",
        "fleet": "M1",
    },
    "AE5E79": {
        "color": "#ff1493",
        "operator": "Marine One (VH-92A)",
        "category": "Head of State",
        "wiki": "Marine_One",
        "fleet": "M1",
    },
}


def _load_plane_alert_db():
    """Load plane_alert_db.json (exported from SQLite) into memory."""
    global _PLANE_ALERT_DB
    json_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "data",
        "plane_alert_db.json",
    )
    if not os.path.exists(json_path):
        logger.warning(f"Plane-Alert DB not found at {json_path}")
        return
    try:
        with open(json_path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        for icao_hex, info in raw.items():
            info["color"] = _category_to_color(info.get("category", ""))
            override = _POTUS_FLEET.get(icao_hex)
            if override:
                info["color"] = override["color"]
                info["operator"] = override["operator"]
                info["category"] = override["category"]
                info["wiki"] = override.get("wiki", "")
                info["potus_fleet"] = override.get("fleet", "")
            _PLANE_ALERT_DB[icao_hex] = info
        logger.info(f"Plane-Alert DB loaded: {len(_PLANE_ALERT_DB)} aircraft")
    except (IOError, OSError, json.JSONDecodeError, ValueError, KeyError) as e:
        logger.error(f"Failed to load Plane-Alert DB: {e}")


_load_plane_alert_db()


def enrich_with_plane_alert(flight: dict) -> dict:
    """If flight's icao24 is in the Plane-Alert DB, add alert metadata."""
    icao = flight.get("icao24", "").strip().upper()
    if icao and icao in _PLANE_ALERT_DB:
        info = _PLANE_ALERT_DB[icao]
        flight["alert_category"] = info["category"]
        flight["alert_color"] = info["color"]
        flight["alert_operator"] = info["operator"]
        flight["alert_type"] = info["ac_type"]
        flight["alert_tags"] = info["tags"]
        flight["alert_link"] = info["link"]
        if info.get("wiki"):
            flight["alert_wiki"] = info["wiki"]
        if info.get("potus_fleet"):
            flight["potus_fleet"] = info["potus_fleet"]
        if info["registration"]:
            flight["registration"] = info["registration"]
    return flight


_TRACKED_NAMES_DB: dict = {}


def _load_tracked_names():
    global _TRACKED_NAMES_DB
    json_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "data",
        "tracked_names.json",
    )
    if not os.path.exists(json_path):
        return
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            for name, info in data.get("details", {}).items():
                cat = info.get("category", "Other")
                socials = info.get("socials")
                for reg in info.get("registrations", []):
                    reg_clean = reg.strip().upper()
                    if reg_clean:
                        entry = {"name": name, "category": cat}
                        if socials:
                            entry["socials"] = socials
                        _TRACKED_NAMES_DB[reg_clean] = entry
        logger.info(f"Tracked Names DB loaded: {len(_TRACKED_NAMES_DB)} registrations")
    except (IOError, OSError, json.JSONDecodeError, ValueError, KeyError) as e:
        logger.error(f"Failed to load Tracked Names DB: {e}")


_load_tracked_names()


def enrich_with_tracked_names(flight: dict) -> dict:
    """If flight's registration matches our Excel extraction, tag it as tracked."""
    icao = flight.get("icao24", "").strip().upper()
    if icao in _POTUS_FLEET:
        return flight

    reg = flight.get("registration", "").strip().upper()
    callsign = flight.get("callsign", "").strip().upper()

    match = None
    if reg and reg in _TRACKED_NAMES_DB:
        match = _TRACKED_NAMES_DB[reg]
    elif callsign and callsign in _TRACKED_NAMES_DB:
        match = _TRACKED_NAMES_DB[callsign]

    if match:
        name = match["name"]
        flight["alert_operator"] = name
        flight["alert_category"] = match["category"]
        if match.get("socials"):
            flight["alert_socials"] = match["socials"]

        name_lower = name.lower()
        is_gov = any(
            w in name_lower
            for w in [
                "state of ",
                "government",
                "republic",
                "ministry",
                "department",
                "federal",
                "cia",
            ]
        )
        is_law = any(
            w in name_lower
            for w in [
                "police",
                "marshal",
                "sheriff",
                "douane",
                "customs",
                "patrol",
                "gendarmerie",
                "guardia",
                "law enforcement",
            ]
        )
        is_med = any(
            w in name_lower
            for w in [
                "fire",
                "bomberos",
                "ambulance",
                "paramedic",
                "medevac",
                "rescue",
                "hospital",
                "medical",
                "lifeflight",
            ]
        )

        if is_gov or is_law:
            flight["alert_color"] = "blue"
        elif is_med:
            flight["alert_color"] = "#32cd32"
        elif "alert_color" not in flight:
            flight["alert_color"] = "pink"

    return flight
