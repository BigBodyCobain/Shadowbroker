"""Heuristics to summarize ACARS/VDL payloads across airlines for dossier display."""

from __future__ import annotations

import re
from typing import Any

# --- shared patterns ---

_ICAO_AIRPORT = re.compile(r"\b([A-Z]{4})\b")
_TAIL = re.compile(r"\b(?:N[0-9A-Z]{3,6}|G-[A-Z]{4,5}|[A-Z]-[A-Z]{4,5}|[A-Z]{2}-[A-Z]{3,4})\b")
# Major carriers — explicit list avoids matching FL280, GS450, etc.
_FLIGHT = re.compile(
    r"\b(?:"
    r"WN|SWA|UA|UAL|AA|AAL|DL|DAL|AS|ASA|B6|JBU|NK|NKS|F9|FFT|G4|HA|HAL|SY|MX|"
    r"FDX|UPS|GTI|ABX|ATN|RCH|CNV|EVAC|SAM|REACH|"
    r"BA|BAW|AF|AFR|LH|DLH|KL|KLM|QF|QFA|EK|UAE|QR|QTR|TK|THY|AC|ACA|WS|WJA|"
    r"FR|RYR|U2|EZY|VS|VIR|NH|ANA|JL|JAL|CX|CPA|SQ|SIA|NZ|ANZ|"
    r"UA|CO|NW|US|HP|TW|VX|AS|QX|OO|YX|MQ|OH|9E|"
    r"JT|JSA|VA|VOZ|NZ|QF|EK|ET|MS|SU|LO|SK|AY|IB|UX|TP|TAP"
    r")\d{1,5}\b",
    re.I,
)
# IATA flight numbers on FI lines and standalone (e.g. UO614, CX889).
_FI_FLIGHT = re.compile(r"\b([A-Z]{2,3}\d{1,4})\b")
_NON_FLIGHT_TOKENS = frozenset(
    {"FL", "FT", "GS", "KT", "RW", "NM", "TD", "TO", "ON", "IN", "OF", "AT", "DA", "AA", "AD"}
)
_FI_BLOCK = re.compile(
    r"FI\s+([A-Z0-9]{2,5}\d{1,5})"
    r"(?:/AN\s+([A-Z0-9\-]+))?"
    r"(?:/DA\s+([A-Z]{4}))?"
    r"(?:/(?:AA|AD|DS)\s+([A-Z]{4}))?",
    re.I,
)
_AC_TYPE = re.compile(
    r"\b(?:B\d{3,4}(?:-\d{3}|MAX|ER|LR|F)?|A\d{3,4}(?:-\d{3}|NEO|LR)?|"
    r"E\d{3}|MD-\d{2}|DC-\d{2}|B77[0-9LWR]?|B78[79]|A35[09]|A33[0-9]|CRJ\d{2,3}|E\d{3})\b",
    re.I,
)

# --- message family patterns ---

_TRACK_HEADER = re.compile(
    r"^\+\+86501,([^,]+),([^,]+),(\d{6}),([^,]+),([A-Z]{4}),([A-Z]{4})",
    re.I,
)
_POS_HEADER = re.compile(r"^POS(N?\d{4,5}[NS]?\d{4,5}[EW]?)", re.I)
_POS_COORDS = re.compile(r"^N?(\d{4,5})([NS])(\d{4,6})([EW])", re.I)
_WAYPOINT = re.compile(
    r"^(?:N)?(\d{1,2}\d{2}\.\d),W(\d{1,3}\d{2}\.\d),(\d{6}),(\d+),",
    re.I,
)
_PERF_HEADER = re.compile(
    r"^[\w]+,(\d+),([^,]+),(\d{6}),([^,]+),([A-Z]{4}),([A-Z]{4})",
    re.I,
)
_PHASE_SNAPSHOT = re.compile(
    r"^(\d{2}\.\d{2}\.\d{2}),(CL|CR|DE|TO|LD|ER|GND),[^,]*,[^,]*,[^,]*,[^,]*,[^,]*,[^,]*,"
    r"N(\d+)\.(\d+),W(\d+)\.(\d+)",
    re.I,
)
_TRAJECTORY_HEADER = re.compile(r"^76401\s*$", re.I)
_TRAJECTORY_ROUTE = re.compile(r"^02E24([A-Z]{4})([A-Z]{4})\s*$", re.I)
_COMPRESSED_WP = re.compile(r"^N(\d{5})W(\d{5})", re.I)
_FPN = re.compile(r"^FPN/?", re.I)
_OOOI_TIMES = re.compile(r"\b(OUT|OFF|ON|IN)\s*(\d{4,6})\b", re.I)
_OOOI_STATUS = re.compile(r"\b(OUT|OFF|ON|IN)\s*,\s*(LO|CL|ON|OF|CLOS)\b", re.I)
_ETA = re.compile(r"\bETA\s+(\d{3,4}Z?)\b", re.I)
_DEP_ARR = re.compile(r"^(DEP|ARR|DLA|ALR)\b", re.I)
_WX = re.compile(r"^(?:WXR?\d*|WX\s|MET\b|/WX\b)", re.I)
_REQ = re.compile(r"^(?:REQ|REQUEST)\b", re.I)
_LDR = re.compile(r"^LDR\d+", re.I)
_PIREP = re.compile(r"^#(?:CFB|DFB)", re.I)
_ATN = re.compile(r"^USADCXA\.AT1\.", re.I)
_CPDLC = re.compile(r"^(?:DM-|UM-|AT1\.|ATC\s)", re.I)
_ENG = re.compile(r"^(?:ENG\d|/ENG|OILTEMP|EGT\b)", re.I)
_DOOR = re.compile(r"^(?:DOOR|CABIN|SMOKE)\b", re.I)
_VDL_FRAME = re.compile(r"^[0-9A-F]{6,8}[A-Z]?\s*$", re.I)
_FRAGMENT = re.compile(r"^[,0\s]+(?:,\d{5,8},\d{5,8},\d{5,8})*$", re.I)
_GARBLED_VDL = re.compile(r"[)Z][A-Z0-9,\-:]{20,}")
_MOSTLY_OPAQUE = re.compile(r"^[0-9A-Fa-f\s.\-+/,]{40,}$")
_FREE_TEXT_POS = re.compile(
    r"^POS\s+N?(\d{1,2}\.\d+)\s+([NS])\s+W?(\d{1,3}\.\d+)\s+([EW])\s+FL(\d{3})",
    re.I,
)
_CLIMB_REQ = re.compile(r"\b(?:CLIMB|DESCEND|REQUEST)\s+(?:FL)?(\d{2,3})\b", re.I)

_LABEL_HINTS: dict[str, str] = {
    "00": "out (gate)",
    "01": "off (takeoff)",
    "02": "on (landing)",
    "03": "in (gate)",
    "10": "position",
    "15": "waypoint",
    "20": "position",
    "40": "ops / clearance",
    "44": "OOOI + position",
    "80": "weather",
    "81": "wind",
    "B1": "engine 1",
    "B2": "engine 2",
    "B3": "engine 3",
    "B4": "engine 4",
    "M1": "maintenance",
    "M2": "maintenance",
    "M3": "maintenance",
    "M4": "maintenance",
    "Q0": "position / OOOI",
    "H1": "terminal",
    "D0": "ATC clearance",
    "S1": "system status",
    "SA": "system status",
    "SB": "system status",
    "4T": "met report",
    "5Z": "free text",
}


def _result(
    summary: str,
    *,
    kind: str,
    readable: bool = True,
    hidden: bool = False,
) -> dict[str, Any]:
    return {
        "summary": summary,
        "kind": kind,
        "readable": readable,
        "hidden": hidden,
    }


def _phase_name(code: str) -> str:
    return {
        "CL": "climb",
        "CR": "cruise",
        "DE": "descent",
        "ER": "en route",
        "TO": "takeoff",
        "LD": "landed",
        "ON": "on ground",
        "OF": "off block",
        "GND": "on ground",
        "LO": "level",
    }.get(code.upper(), code.upper() or "unknown")


def _fmt_coords(lat_deg: str, lat_frac: str, lon_deg: str, lon_frac: str) -> str:
    return f"{int(lat_deg)}°{lat_frac}'N {int(lon_deg)}°{lon_frac}'W"


def _parse_pos_coords(token: str) -> str | None:
    token = token.upper().lstrip("POS")
    match = _POS_COORDS.match(token)
    if not match:
        return None
    lat, lat_dir, lon, lon_dir = match.groups()
    lat_v = f"{int(lat[:2])}°{lat[2:]}.{lat[4:] if len(lat) > 4 else '0'}'{lat_dir}"
    lon_v = f"{int(lon[:3])}°{lon[3:]}.{lon[5:] if len(lon) > 5 else '0'}'{lon_dir}"
    return f"{lat_v} {lon_v}"


def _extract_route(raw: str) -> str:
    fi = _FI_BLOCK.search(raw)
    if fi:
        flight, _tail, dep, dest = fi.groups()
        parts = [flight.upper()]
        if dep and dest:
            parts.append(f"{dep}→{dest}")
        elif dep:
            parts.append(f"from {dep}")
        elif dest:
            parts.append(f"to {dest}")
        return " · ".join(parts)

    airports = _ICAO_AIRPORT.findall(raw)
    # Filter duplicates while preserving order
    seen: set[str] = set()
    ordered: list[str] = []
    for apt in airports:
        if apt in seen:
            continue
        seen.add(apt)
        ordered.append(apt)
    if len(ordered) >= 2:
        return f"{ordered[0]}→{ordered[-1]}"
    if ordered:
        return ordered[0]
    return ""


def _extract_flight(raw: str) -> str:
    fi = _FI_BLOCK.search(raw)
    if fi and fi.group(1):
        return fi.group(1).upper()
    for match in _FLIGHT.finditer(raw):
        return match.group(0).upper()
    for match in _FI_FLIGHT.finditer(raw):
        token = match.group(1).upper()
        prefix = re.match(r"^([A-Z]+)", token)
        if prefix and prefix.group(1) not in _NON_FLIGHT_TOKENS:
            return token
    return ""


def _extract_phase_snapshot(raw: str) -> str | None:
    for line in raw.splitlines():
        match = _PHASE_SNAPSHOT.match(line.strip())
        if not match:
            continue
        time_s, phase, lat_d, lat_f, lon_d, lon_f = match.groups()
        coords = _fmt_coords(lat_d, lat_f, lon_d, lon_f)
        return f"{_phase_name(phase)} · {coords} · {time_s}Z"
    return None


def _has_aircraft_context(raw: str) -> bool:
    head = raw[:160].upper()
    if _AC_TYPE.search(head):
        return True
    if _FLIGHT.search(head):
        return True
    if _FI_BLOCK.search(head):
        return True
    return False


def _is_fragment(raw: str) -> bool:
    first = raw.splitlines()[0].strip()
    if _FRAGMENT.match(first):
        return True
    if re.match(r"^[,0]{1,12}$", first):
        return True
    if first.startswith("000000") or first.startswith(",000000"):
        return True
    if re.match(r"^\d{2}\.\d{2}\.\d{2},", first) and not _has_aircraft_context(raw):
        return True
    return False


def _summarize_oooi(raw: str, label: str) -> dict[str, Any] | None:
    times = _OOOI_TIMES.findall(raw)
    statuses = _OOOI_STATUS.findall(raw)
    if not times and not statuses and label not in {"00", "01", "02", "03", "44", "Q0"}:
        return None

    events: list[str] = []
    for event, value in times:
        events.append(f"{event.upper()} {value}")
    for event, status in statuses:
        events.append(f"{event.upper()} ({_phase_name(status)})")

    if label in {"00", "01", "02", "03"} and not events:
        events.append(_LABEL_HINTS[label])

    if not events and "ON  ,LO" not in raw and "OFF,OFF" not in raw:
        return None

    route = _extract_route(raw)
    flight = _extract_flight(raw)
    prefix = "OOOI"
    if label in _LABEL_HINTS:
        prefix = f"OOOI ({_LABEL_HINTS[label]})"
    bits = [prefix]
    if flight:
        bits.append(flight)
    if route:
        bits.append(route)
    if events:
        bits.append(", ".join(events[:4]))
    return _result(" · ".join(bits), kind="oooi")


def _summarize_position(raw: str, first_line: str) -> dict[str, Any] | None:
    upper = first_line.upper()
    pos_token = re.search(r"POSN?\d", raw, re.I)
    if not (upper.startswith("POS") or _POS_HEADER.match(first_line) or pos_token):
        return None

    coord_line = first_line
    if pos_token and not upper.startswith("POS"):
        coord_line = raw[pos_token.start() :].split(",")[0]

    coords = _parse_pos_coords(coord_line)
    free = _FREE_TEXT_POS.match(raw)
    fl = ""
    if free:
        lat, lat_dir, lon, lon_dir, fl = free.groups()
        coords = f"{lat}°{lat_dir} {lon}°{lon_dir}"
        fl = f"FL{fl}"

    route = _extract_route(raw)
    flight = _extract_flight(raw)
    parts = ["Position report"]
    if flight:
        parts.append(flight)
    if route:
        parts.append(route)
    if coords:
        parts.append(coords)
    if fl:
        parts.append(fl)
    elif re.search(r"\bFL?\d{3}\b", raw):
        fl_match = re.search(r"\bFL?(\d{2,3})\b", raw)
        if fl_match:
            parts.append(f"FL{fl_match.group(1)}")
    return _result(" · ".join(parts), kind="position")


def _summarize_performance(raw: str, first_line: str) -> dict[str, Any] | None:
    match = _PERF_HEADER.match(first_line)
    if not match or not _AC_TYPE.search(first_line):
        return None

    _serial, ac_type, _date, flight, dep, dest = match.groups()
    phase_bits = _extract_phase_snapshot(raw) or ""
    extra = f" · {phase_bits}" if phase_bits else ""

    if "FHP" in raw or "SIN," in raw or "SOU," in raw:
        title, kind = "Engine health (FHP)", "engine_health"
    elif "OATTO" in raw or "LPACKCL" in raw or "RPACKCL" in raw:
        title, kind = "Pack temperature", "pack_temp"
    elif "FLAPS" in raw.upper():
        title, kind = "Climb performance", "climb_perf"
    elif "FRE," in raw or "FEX," in raw:
        title, kind = "Fuel/performance snapshot", "fuel_perf"
    else:
        title, kind = "Flight performance", "performance"

    return _result(
        f"{title} · {flight} · {ac_type} · {dep}→{dest}{extra}",
        kind=kind,
    )


def _summarize_by_label(label: str, raw: str, first_line: str) -> dict[str, Any] | None:
    label_u = label.upper()
    hint = _LABEL_HINTS.get(label_u, "")

    if label_u in {"B1", "B2", "B3", "B4"} or _ENG.match(first_line):
        eng = label_u if label_u.startswith("B") else "Engine"
        return _result(f"{eng} data report", kind="engine", readable=bool(hint))

    if label_u.startswith("M") and label_u[1:2].isdigit():
        return _result(f"Maintenance ({hint or 'system report'})", kind="maintenance")

    if label_u in {"80", "81", "4T"} or _WX.match(first_line):
        apt = _ICAO_AIRPORT.search(raw)
        apt_s = f" · {apt.group(1)}" if apt else ""
        return _result(f"Weather report{apt_s}", kind="weather")

    if label_u == "D0" or _REQ.match(first_line) or _CLIMB_REQ.search(raw):
        climb = _CLIMB_REQ.search(raw)
        if climb:
            return _result(f"Altitude request · FL{climb.group(1)}", kind="request")
        return _result("ATC / ops request", kind="request")

    if label_u in {"40", "5Z"} and len(raw) < 200:
        text = raw.replace("\n", " · ")[:140]
        return _result(f"Ops message · {text}", kind="ops")

    return None


def summarize_datalink_message(
    *,
    label: str = "",
    text: str = "",
    source_type: str = "",
) -> dict[str, Any]:
    """Return {summary, kind, readable, hidden} for a cached datalink message."""
    raw = (text or "").strip()
    if not raw:
        return _result("", kind="empty", readable=False, hidden=True)

    first_line = raw.splitlines()[0].strip()
    upper = first_line.upper()
    label_u = label.upper()

    if _is_fragment(raw):
        return _result(
            "Split telemetry fragment (part of a longer VDL message)",
            kind="fragment",
            readable=False,
            hidden=True,
        )

    if _ATN.match(first_line) or _CPDLC.match(first_line):
        tail = _TAIL.search(raw)
        return _result(
            "Datalink protocol / CPDLC header" + (f" · {tail.group(0)}" if tail else ""),
            kind="protocol",
            readable=False,
            hidden=True,
        )

    if label_u == "37" or (_VDL_FRAME.match(first_line) and len(raw) < 160):
        if _GARBLED_VDL.search(raw) or len(raw) < 160:
            return _result("VDL binary frame (undecoded)", kind="vdl_binary", readable=False, hidden=True)

    # --- structured families (order matters) ---

    if _DEP_ARR.match(first_line):
        kind_word = first_line.split()[0].upper()
        route = _extract_route(raw)
        flight = _extract_flight(raw)
        title = {"DEP": "Departure", "ARR": "Arrival", "DLA": "Delay", "ALR": "Alert"}.get(
            kind_word, kind_word
        )
        bits = [title]
        if flight:
            bits.append(flight)
        if route:
            bits.append(route)
        return _result(" · ".join(bits), kind=kind_word.lower())

    oooi = _summarize_oooi(raw, label_u)
    if oooi:
        return oooi

    match = _TRACK_HEADER.match(first_line)
    if match:
        tail, ac_type, _date, flight, dep, dest = match.groups()
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        waypoint_lines = [line for line in lines if _WAYPOINT.match(line.lstrip("N"))]
        phase = ""
        if waypoint_lines:
            parts = waypoint_lines[-1].rstrip(",").split(",")
            if len(parts) >= 8:
                phase = _phase_name(parts[7])
        wp_count = len(waypoint_lines) or max(0, len(lines) - 2)
        summary = (
            f"Track report · {flight} · {tail} ({ac_type}) · {dep}→{dest}"
            + (f" · {wp_count} waypoint(s)" + (f" · {phase}" if phase else ""))
        )
        return _result(summary, kind="track")

    pos = _summarize_position(raw, first_line)
    if pos:
        return pos

    if _FPN.match(first_line):
        route = _extract_route(raw)
        flight = _extract_flight(raw)
        bits = ["Flight plan"]
        if flight:
            bits.append(flight)
        if route:
            bits.append(route)
        return _result(" · ".join(bits), kind="flight_plan")

    if _PIREP.match(first_line):
        return _result("Pilot report (PIREP)", kind="pirep")

    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if _TRAJECTORY_HEADER.match(first_line) or (len(lines) >= 2 and _TRAJECTORY_ROUTE.match(lines[1])):
        route = ""
        route_match = next((m for line in lines if (m := _TRAJECTORY_ROUTE.match(line))), None)
        if route_match:
            route = f" · {route_match.group(1)}→{route_match.group(2)}"
        wp_count = sum(1 for line in lines if _COMPRESSED_WP.match(line))
        return _result(
            f"Trajectory / ADS report{route}" + (f" · {wp_count} point(s)" if wp_count else ""),
            kind="trajectory",
        )

    perf = _summarize_performance(raw, first_line)
    if perf:
        return perf

    if _LDR.match(first_line):
        route = _extract_route(raw)
        return _result(f"Load report · {route}" if route else "Load report", kind="load")

    if _WX.match(first_line):
        route = _extract_route(raw)
        return _result(f"Weather request · {route or 'en route'}", kind="weather")

    if _DOOR.match(first_line):
        return _result("Cabin / door advisory", kind="cabin")

    if _WAYPOINT.match(first_line.lstrip("N")):
        parts = first_line.lstrip("N").rstrip(",").split(",")
        if len(parts) >= 4:
            lat, lon, _t, alt = parts[0], parts[1], parts[2], parts[3]
            phase = _phase_name(parts[7]) if len(parts) >= 8 else ""
            summary = f"Waypoint · {lat},{lon} · alt {alt} ft" + (f" · {phase}" if phase else "")
            return _result(summary, kind="waypoint")

    label_summary = _summarize_by_label(label_u, raw, first_line)
    if label_summary:
        return label_summary

    flight = _extract_flight(raw)
    route = _extract_route(raw)
    if flight and route:
        return _result(f"Datalink · {flight} · {route}", kind="flight")

    eta = _ETA.search(raw)
    if eta and flight:
        return _result(f"ETA update · {flight} · {eta.group(1)}", kind="eta")

    if len(raw) < 100 and not _MOSTLY_OPAQUE.match(raw) and not _GARBLED_VDL.search(raw):
        clean = raw.replace("\n", " · ")
        if label_u in _LABEL_HINTS:
            return _result(f"{_LABEL_HINTS[label_u].title()} · {clean}", kind="short")
        return _result(clean, kind="short")

    digit_ratio = sum(ch.isdigit() for ch in raw) / max(len(raw), 1)
    if digit_ratio > 0.55 or _MOSTLY_OPAQUE.match(raw.replace(" ", "")) or _GARBLED_VDL.search(raw):
        return _result(
            "Binary / proprietary telemetry (undecoded)",
            kind="vdl_binary",
            readable=False,
            hidden=True,
        )

    if label_u in _LABEL_HINTS:
        return _result(
            f"{_LABEL_HINTS[label_u].title()} message",
            kind=label_u.lower(),
            readable=False,
            hidden=False,
        )

    return _result(
        first_line[:100] + ("…" if len(first_line) > 100 else ""),
        kind="raw",
        readable=False,
        hidden=False,
    )


def prepare_datalink_display(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Attach summaries and filter noise for dossier display."""
    enriched: list[dict[str, Any]] = []
    hidden_count = 0
    seen_summaries: set[str] = set()

    for message in messages:
        meta = summarize_datalink_message(
            label=str(message.get("label") or ""),
            text=str(message.get("text") or ""),
            source_type=str(message.get("source_type") or ""),
        )
        item = {**message, **meta}
        if item.get("hidden"):
            hidden_count += 1
            continue

        # Drop back-to-back duplicate summaries (common with multi-part VDL)
        sig = f"{item.get('kind')}|{item.get('summary')}"
        if sig in seen_summaries and item.get("kind") not in {"short", "ops", "request"}:
            hidden_count += 1
            continue
        seen_summaries.add(sig)

        enriched.append(item)

    return {
        "messages": enriched,
        "hidden_count": hidden_count,
        "total_count": len(messages),
    }


def attach_summaries(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return prepare_datalink_display(messages)["messages"]
