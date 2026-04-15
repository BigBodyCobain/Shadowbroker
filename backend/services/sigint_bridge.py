"""SIGINT Grid — unified radio intelligence bridge.

Three protocol bridges feeding a shared signal buffer:
  - APRS-IS:     TCP to rotate.aprs2.net:14580 (amateur radio positions/weather)
  - Meshtastic:  MQTT to mqtt.meshtastic.org:1883 (mesh network messages)
  - JS8Call:     TCP to 127.0.0.1:2442 (HF digital mode, local radio only)

Each bridge runs in a daemon thread and pushes parsed signals into a shared
collections.deque (thread-safe, bounded). The SIGINTGrid orchestrator merges
and deduplicates all signals on demand.
"""

import json
import socket
import struct
import threading
import time
import logging
from collections import deque
from datetime import datetime, timezone

from services.config import get_settings
from services.mesh.meshtastic_topics import build_subscription_topics, known_roots, parse_topic_metadata

logger = logging.getLogger("services.sigint")

# Maximum signals retained per bridge (prevents unbounded memory)
_MAX_SIGNALS = 500
# Maximum age of signals before discard (seconds)
_MAX_AGE_S = 600  # 10 minutes


def _is_plausible_land(lat: float, lng: float) -> bool:
    """Reject coordinates that are obviously in the middle of the ocean.

    Uses coarse bounding boxes for major landmasses. Not perfect, but filters
    out the bulk of garbage coordinates from bad GPS / protobuf parsing.
    Radio operators are on land (or near coasts), not mid-ocean.
    """
    # Major landmass bounding boxes (generous margins for coastal/island coverage)
    _LAND_BOXES = [
        # North America (incl. Caribbean, Central America)
        (15, 72, -170, -50),
        # South America
        (-60, 15, -82, -34),
        # Europe
        (35, 72, -12, 45),
        # Africa
        (-36, 38, -18, 52),
        # Asia (incl. Middle East, India, SE Asia)
        (0, 75, 25, 180),
        # Australia / Oceania
        (-50, -8, 110, 180),
        # New Zealand / Pacific islands
        (-48, -10, 165, 180),
        # Japan / Korea / Taiwan
        (20, 46, 124, 146),
        # Indonesia / Philippines
        (-12, 20, 95, 130),
        # UK / Ireland / Iceland
        (50, 67, -25, 2),
        # Alaska
        (51, 72, -180, -130),
        # Hawaii
        (18, 23, -161, -154),
        # Caribbean islands
        (10, 28, -86, -59),
        # Madagascar
        (-26, -12, 43, 51),
    ]
    for min_lat, max_lat, min_lng, max_lng in _LAND_BOXES:
        if min_lat <= lat <= max_lat and min_lng <= lng <= max_lng:
            return True
    return False


# ─── Emergency Lexicon (multilingual SOS/crisis keyword scanner) ──────────────
# Extracted from Pete's universal_translator.py — real Unicode keywords

_EMERGENCY_LEXICON: dict[str, list[str]] = {
    # English
    "en": ["SOS", "MAYDAY", "EMERGENCY", "HELP", "MEDIC", "EVACUAT"],
    # Mandarin (Chinese)
    "zh": ["救命", "求助", "停电", "医生", "地震", "火灾", "爆炸"],
    # Russian
    "ru": ["помощь", "удар", "врач", "эвакуация", "пожар"],
    # Ukrainian
    "uk": ["допомога", "вогонь", "обстріл", "евакуація", "лікар"],
    # Farsi (Persian)
    "fa": ["کمک", "انفجار", "پزشک", "برق", "زلزله"],
    # Arabic
    "ar": ["مساعدة", "طبيب", "قنبلة", "ماء", "إغاثة"],
    # Burmese (Myanmar)
    "my": ["ကူညီပါ", "ဆေးဆရာ", "မီးပျက်"],
    # Hebrew
    "he": ["עזרה", "חובש", "פיצוץ", "אש"],
    # Korean
    "ko": ["도와주세요", "응급", "화재", "지진"],
    # Japanese
    "ja": ["助けて", "緊急", "地震", "火事", "避難"],
}

# Flatten all keywords into a single set for fast scanning
_ALL_EMERGENCY_KEYWORDS: set[str] = set()
for _kws in _EMERGENCY_LEXICON.values():
    for _kw in _kws:
        _ALL_EMERGENCY_KEYWORDS.add(_kw.upper())
        _ALL_EMERGENCY_KEYWORDS.add(_kw)  # keep original case for CJK


def _scan_emergency(text: str) -> str | None:
    """Check if text contains any emergency keyword. Returns matched keyword or None."""
    if not text:
        return None
    text_upper = text.upper()
    for kw in _ALL_EMERGENCY_KEYWORDS:
        if kw in text_upper or kw in text:
            return kw
    return None


# ─── APRS Symbol Decoding ────────────────────────────────────────────────────

# Primary table (/) symbol codes → human-readable labels
_APRS_SYMBOLS: dict[str, str] = {
    "/-": "House/QTH",
    "/!": "Police",
    "/#": "Digipeater",
    "/$": "Phone",
    "/%": "DX Cluster",
    "/&": "HF Gateway",
    "/'": "Aircraft (small)",
    "/(": "Mobile Sat",
    "/)": "Wheelchair",
    "/*": "Snowmobile",
    "/+": "Red Cross",
    "/,": "Boy Scout",
    "/.": "Unknown/X",
    "//": "Red Dot",
    "/:": "Fire",
    "/;": "Campground",
    "/<": "Motorcycle",
    "/=": "Railroad",
    "/>": "Car",
    "/?": "Server/Info",
    "/@": "Hurricane/Tropical",
    "/A": "Aid Station",
    "/E": "Eyeball",
    "/F": "Farm/Tractor",
    "/H": "Hotel",
    "/I": "TCP/IP",
    "/K": "School",
    "/N": "NTS Station",
    "/O": "Balloon",
    "/P": "Police",
    "/R": "RV",
    "/S": "Shuttle",
    "/T": "SSTV",
    "/U": "Bus",
    "/W": "NWS Site",
    "/Y": "Yacht/Sailboat",
    "/[": "Jogger/Human",
    "/\\": "Triangle",
    "/^": "Aircraft (large)",
    "/_": "Weather Station",
    "/a": "Ambulance",
    "/b": "Bicycle",
    "/c": "Incident",
    "/d": "Fire Dept",
    "/e": "Horse",
    "/f": "Fire Truck",
    "/g": "Glider",
    "/h": "Hospital",
    "/i": "IOTA",
    "/j": "Jeep",
    "/k": "Truck",
    "/l": "Laptop",
    "/n": "Node/Relay",
    "/o": "EOC",
    "/p": "Rover/Dog",
    "/r": "Antenna",
    "/s": "Powerboat",
    "/u": "Truck (18-wheel)",
    "/v": "Van",
    "/w": "Water Station",
    "/y": "House+Yagi",
}

# Alternate table (\) — common overrides
_APRS_SYMBOLS_ALT: dict[str, str] = {
    "\\-": "House (HF)",
    "\\>": "Car",
    "\\#": "Digipeater (alt)",
    "\\/": "Red Dot",
    "\\&": "Gateway/Digi",
    "\\^": "Aircraft",
    "\\_": "WX Station",
    "\\k": "SUV",
    "\\n": "Node",
}

# D-Star / DMR gateways use 'D' table prefix
_APRS_DSTAR: dict[str, str] = {
    "D&": "D-Star/DMR Gateway",
    "D#": "D-Star Digipeater",
}


def _decode_aprs_symbol(symbol: str) -> str:
    """Decode APRS symbol table+code into a human-readable station type."""
    if not symbol or len(symbol) < 2:
        return "Station"
    return (
        _APRS_SYMBOLS.get(symbol)
        or _APRS_SYMBOLS_ALT.get(symbol)
        or _APRS_DSTAR.get(symbol)
        or "Station"
    )


def _parse_aprs_comment(comment: str) -> dict:
    """Extract structured metadata from APRS comment field.

    Returns dict with optional keys: frequency, altitude_ft, course, speed_knots, power
    """
    import re

    meta: dict = {}

    # Frequency: e.g., "146.520MHz" or "439.01250MHz"
    freq_match = re.search(r"(\d{2,3}\.\d{2,6})\s*MHz", comment, re.IGNORECASE)
    if freq_match:
        meta["frequency"] = f"{freq_match.group(1)} MHz"

    # Altitude: /A=NNNNNN (in feet)
    alt_match = re.search(r"/A=(\d{6})", comment)
    if alt_match:
        alt = int(alt_match.group(1))
        if alt > 0:
            meta["altitude_ft"] = alt

    # Course/Speed: CCC/SSS at start of comment (course deg / speed knots)
    cs_match = re.match(r"^(\d{3})/(\d{3})", comment)
    if cs_match:
        course = int(cs_match.group(1))
        speed = int(cs_match.group(2))
        if speed > 0:
            meta["course"] = course
            meta["speed_knots"] = speed

    # Battery voltage: "Bat:X.XV" or "XX.XV" at end
    batt_match = re.search(r"Bat[:\s]*(\d+\.\d+)\s*V", comment, re.IGNORECASE)
    if batt_match:
        meta["battery_v"] = float(batt_match.group(1))

    # PHG (Power-Height-Gain-Directivity)
    phg_match = re.search(r"PHG(\d)(\d)(\d)(\d)", comment)
    if phg_match:
        power_code = int(phg_match.group(1))
        power_watts = power_code**2  # APRS PHG power encoding
        meta["power_watts"] = power_watts

    # Clean comment: strip leading course/speed, PHG, /A= cruft
    clean = comment
    clean = re.sub(r"^\d{3}/\d{3}/", "", clean)
    clean = re.sub(r"/A=\d{6}", "", clean)
    clean = re.sub(r"PHG\d{4,}", "", clean)
    clean = clean.strip(" /")
    if clean:
        meta["status"] = clean[:80]

    return meta


# ─── APRS-IS Bridge ─────────────────────────────────────────────────────────


class APRSBridge:
    """Connects to APRS-IS and parses position reports."""

    HOST = "rotate.aprs2.net"
    PORT = 14580
    # Read-only login (no callsign needed for receive-only)
    LOGIN = "user N0CALL pass -1 vers ShadowBroker 1.0 filter r/0/0/25000\r\n"
    CONFIDENCE = 0.7

    def __init__(self):
        self.signals: deque[dict] = deque(maxlen=_MAX_SIGNALS)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="aprs-bridge")
        self._thread.start()
        logger.info("APRS-IS bridge started")

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.is_set():
            try:
                self._connect_and_read()
            except Exception as e:
                logger.warning(f"APRS-IS connection error: {e}")
            if not self._stop.is_set():
                time.sleep(15)  # reconnect delay

    @staticmethod
    def _decode_line(raw_bytes: bytes) -> str:
        """Decode APRS packet bytes trying UTF-8 first, then GBK (Chinese), then latin-1."""
        try:
            return raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            pass
        try:
            return raw_bytes.decode("gbk")
        except UnicodeDecodeError:
            pass
        return raw_bytes.decode("latin-1")  # latin-1 never fails (1:1 byte mapping)

    def _connect_and_read(self):
        with socket.create_connection((self.HOST, self.PORT), timeout=30) as sock:
            sock.settimeout(90)
            # Read server banner
            banner = sock.recv(512).decode("utf-8", errors="replace")
            logger.info(f"APRS-IS: {banner.strip()}")
            # Send login
            sock.sendall(self.LOGIN.encode("ascii"))
            buf = b""
            while not self._stop.is_set():
                try:
                    chunk = sock.recv(4096)
                except socket.timeout:
                    # Send keepalive
                    sock.sendall(b"#keepalive\r\n")
                    continue
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line_bytes, buf = buf.split(b"\n", 1)
                    line_bytes = line_bytes.strip()
                    if not line_bytes or line_bytes.startswith(b"#"):
                        continue
                    line = self._decode_line(line_bytes)
                    self._parse_packet(line)

    def _parse_packet(self, raw: str):
        """Parse an APRS packet and extract position if present."""
        try:
            # Format: CALLSIGN>PATH:PAYLOAD
            if ":" not in raw:
                return
            header, payload = raw.split(":", 1)
            callsign = header.split(">")[0].strip()
            if not callsign or callsign == "N0CALL":
                return

            # Position reports start with ! @ / or =
            if not payload or payload[0] not in "!@/=":
                return

            # Try to extract lat/lng from uncompressed position
            # Format: !DDMM.MMN/DDDMM.MMW...  or similar
            pos = payload[1:]
            lat = self._parse_lat(pos[:8])
            lng = self._parse_lng(pos[9:18])
            if lat is None or lng is None:
                return

            symbol = pos[8] + pos[18] if len(pos) > 18 else ""
            comment = pos[19:].strip() if len(pos) > 19 else ""

            station_type = _decode_aprs_symbol(symbol)
            meta = _parse_aprs_comment(comment)

            sig = {
                "callsign": callsign,
                "lat": lat,
                "lng": lng,
                "source": "aprs",
                "confidence": self.CONFIDENCE,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "raw_message": raw[:200],
                "symbol": symbol,
                "station_type": station_type,
                "comment": comment[:100],
            }
            # Merge parsed metadata into signal
            if meta.get("frequency"):
                sig["frequency"] = meta["frequency"]
            if meta.get("altitude_ft"):
                sig["altitude_ft"] = meta["altitude_ft"]
            if meta.get("speed_knots"):
                sig["speed_knots"] = meta["speed_knots"]
                sig["course"] = meta.get("course", 0)
            if meta.get("battery_v"):
                sig["battery_v"] = meta["battery_v"]
            if meta.get("power_watts"):
                sig["power_watts"] = meta["power_watts"]
            if meta.get("status"):
                sig["status"] = meta["status"]

            # Emergency keyword scan across all text fields
            emergency_kw = _scan_emergency(comment) or _scan_emergency(sig.get("status", ""))
            if emergency_kw:
                sig["emergency"] = True
                sig["emergency_keyword"] = emergency_kw

            self.signals.append(sig)
        except (ValueError, IndexError):
            pass

    @staticmethod
    def _parse_lat(s: str) -> float | None:
        """Parse APRS latitude: DDMM.MMN"""
        try:
            if len(s) < 8:
                return None
            deg = int(s[:2])
            minutes = float(s[2:7])
            direction = s[7].upper()
            lat = deg + minutes / 60.0
            if direction == "S":
                lat = -lat
            if -90 <= lat <= 90:
                return round(lat, 5)
        except (ValueError, IndexError):
            pass
        return None

    @staticmethod
    def _parse_lng(s: str) -> float | None:
        """Parse APRS longitude: DDDMM.MMW"""
        try:
            if len(s) < 9:
                return None
            deg = int(s[:3])
            minutes = float(s[3:8])
            direction = s[8].upper()
            lng = deg + minutes / 60.0
            if direction == "W":
                lng = -lng
            if -180 <= lng <= 180:
                return round(lng, 5)
        except (ValueError, IndexError):
            pass
        return None


# ─── Meshtastic MQTT Bridge ─────────────────────────────────────────────────


class MeshtasticBridge:
    """Connects to Meshtastic public MQTT broker for mesh network messages."""

    HOST = "mqtt.meshtastic.org"
    PORT = 1883
    USER = "meshdev"
    PASS = "large4cats"
    CONFIDENCE = 0.5

    def __init__(self):
        self.signals: deque[dict] = deque(maxlen=_MAX_SIGNALS)
        self.messages: deque[dict] = deque(maxlen=500)
        self._message_dedupe: dict[str, float] = {}
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def _dedupe_message(
        self,
        sender: str,
        channel: str,
        text: str,
        recipient: str = "broadcast",
        root: str = "",
    ) -> bool:
        now = time.time()
        cutoff = now - 120
        for key, ts in list(self._message_dedupe.items()):
            if ts < cutoff:
                del self._message_dedupe[key]
        key = f"{sender}:{recipient}:{root}:{channel}:{text}"
        if key in self._message_dedupe:
            return True
        self._message_dedupe[key] = now
        return False

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="mesh-bridge")
        self._thread.start()
        logger.info("Meshtastic MQTT bridge started")

    def stop(self):
        self._stop.set()

    def _subscription_topics(self) -> list[str]:
        settings = get_settings()
        return build_subscription_topics(
            extra_roots=str(getattr(settings, "MESH_MQTT_EXTRA_ROOTS", "") or ""),
            extra_topics=str(getattr(settings, "MESH_MQTT_EXTRA_TOPICS", "") or ""),
            include_defaults=bool(getattr(settings, "MESH_MQTT_INCLUDE_DEFAULT_ROOTS", True)),
        )

    def _run(self):
        while not self._stop.is_set():
            try:
                self._connect()
            except Exception as e:
                logger.warning(f"Meshtastic MQTT error: {e}")
            if not self._stop.is_set():
                time.sleep(15)

    def _connect(self):
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            logger.error("paho-mqtt not installed — Meshtastic bridge disabled")
            self._stop.set()
            return

        topics = self._subscription_topics()

        def _on_connect(client, userdata, flags, rc):
            if rc == 0:
                logger.info(f"Meshtastic MQTT connected, subscribing to {topics}")
                for topic in topics:
                    client.subscribe(topic, qos=0)
            else:
                logger.error(f"Meshtastic MQTT connection refused: rc={rc}")

        def _on_disconnect(client, userdata, rc):
            if rc != 0:
                logger.warning(f"Meshtastic MQTT disconnected unexpectedly (rc={rc}), will auto-reconnect")
            else:
                logger.info("Meshtastic MQTT disconnected cleanly")

        client = mqtt.Client(client_id="shadowbroker-mesh", protocol=mqtt.MQTTv311)
        client.username_pw_set(self.USER, self.PASS)
        client.on_connect = _on_connect
        client.on_message = self._on_message
        client.on_disconnect = _on_disconnect
        client.reconnect_delay_set(min_delay=1, max_delay=30)

        client.connect(self.HOST, self.PORT, keepalive=30)
        client.loop_start()

        while not self._stop.is_set():
            self._stop.wait(1.0)

        client.loop_stop()
        client.disconnect()

    def _on_message(self, client, userdata, msg):
        """Parse Meshtastic MQTT messages — protobuf + AES decryption."""
        try:
            payload = msg.payload
            topic = msg.topic

            # Try JSON first (some nodes publish JSON on /json/ topics)
            if "/json/" in topic:
                try:
                    data = json.loads(payload)
                    self._ingest_data(data, topic)
                    return
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass

            # Protobuf ServiceEnvelope (the standard format)
            data = self._decode_protobuf(payload, topic)
            if data:
                # Text messages don't have positions — store in message log
                if data.get("portnum") == "TEXT_MESSAGE_APP" and data.get("text"):
                    topic_meta = parse_topic_metadata(topic)
                    recipient = data.get("to", "broadcast")
                    if self._dedupe_message(
                        data.get("from", "???"),
                        topic_meta["channel"],
                        data["text"],
                        recipient,
                        topic_meta["root"],
                    ):
                        return
                    self.messages.appendleft(
                        {
                            "from": data.get("from", "???"),
                            "to": recipient,
                            "text": data["text"],
                            "region": topic_meta["region"],
                            "root": topic_meta["root"],
                            "channel": topic_meta["channel"],
                            "timestamp": datetime.utcnow().isoformat() + "Z",
                        }
                    )
                else:
                    self._ingest_data(data, topic)

        except Exception as e:
            logger.debug(f"Meshtastic parse error: {e}")

    def _decode_protobuf(self, payload: bytes, topic: str) -> dict | None:
        """Decode a Meshtastic ServiceEnvelope protobuf with AES decryption."""
        try:
            from meshtastic import mesh_pb2, mqtt_pb2, portnums_pb2
        except ImportError:
            return None

        try:
            envelope = mqtt_pb2.ServiceEnvelope()
            envelope.ParseFromString(payload)
        except Exception:
            return None

        packet = envelope.packet
        if not packet or not packet.HasField("encrypted"):
            # Already decoded or empty
            if packet and packet.HasField("decoded"):
                return self._extract_from_decoded(packet, topic)
            return None

        # Decrypt with default LongFast PSK (hardcoded 16-byte AES-128 key)
        try:
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

            # Meshtastic default channel key (firmware hardcoded for PSK=0x01)
            default_key = bytes(
                [
                    0xD4,
                    0xF1,
                    0xBB,
                    0x3A,
                    0x20,
                    0x29,
                    0x07,
                    0x59,
                    0xF0,
                    0xBC,
                    0xFF,
                    0xAB,
                    0xCF,
                    0x4E,
                    0x69,
                    0x01,
                ]
            )

            # Nonce: packetId (little-endian u64) + fromNode (little-endian u64) = 16 bytes
            nonce = struct.pack("<QQ", packet.id, getattr(packet, "from"))

            cipher = Cipher(algorithms.AES(default_key), modes.CTR(nonce))
            decryptor = cipher.decryptor()
            decrypted = decryptor.update(packet.encrypted) + decryptor.finalize()

            data_msg = mesh_pb2.Data()
            data_msg.ParseFromString(decrypted)

            return self._extract_from_data(data_msg, packet, topic)
        except Exception as e:
            logger.debug(f"Meshtastic decrypt failed: {e}")
            return None

    def _extract_from_decoded(self, packet, topic: str) -> dict | None:
        """Extract data from an already-decoded MeshPacket."""
        decoded = packet.decoded
        return self._extract_from_data(decoded, packet, topic)

    def _extract_from_data(self, data_msg, packet, topic: str) -> dict | None:
        """Extract position/text from a decoded Data message."""
        try:
            from meshtastic import mesh_pb2, portnums_pb2
        except ImportError:
            return None

        portnum = data_msg.portnum
        from_id = getattr(packet, "from", 0)
        to_id = getattr(packet, "to", 0)
        callsign = f"!{from_id:08x}" if from_id else topic.split("/")[-1]

        result = {"from": callsign}
        if to_id == 0xFFFFFFFF:
            result["to"] = "broadcast"
        elif to_id:
            result["to"] = f"!{to_id:08x}"

        if portnum == portnums_pb2.PortNum.POSITION_APP:
            try:
                pos = mesh_pb2.Position()
                pos.ParseFromString(data_msg.payload)
                if pos.latitude_i and pos.longitude_i:
                    result["latitude_i"] = pos.latitude_i
                    result["longitude_i"] = pos.longitude_i
                    if pos.altitude:
                        result["altitude"] = pos.altitude
                    return result
            except Exception:
                pass

        elif portnum == portnums_pb2.PortNum.TEXT_MESSAGE_APP:
            try:
                text = data_msg.payload.decode("utf-8", errors="replace")
                result["text"] = text
                result["portnum"] = "TEXT_MESSAGE_APP"
                return result
            except Exception:
                pass

        elif portnum == portnums_pb2.PortNum.NODEINFO_APP:
            try:
                user = mesh_pb2.User()
                user.ParseFromString(data_msg.payload)
                if user.long_name:
                    result["long_name"] = user.long_name
                if user.short_name:
                    result["short_name"] = user.short_name
                # No position in nodeinfo
                return None
            except Exception:
                pass

        return None

    def _ingest_data(self, data: dict, topic: str):
        """Process a decoded data dict into a signal entry."""
        lat = data.get("latitude_i") or data.get("lat")
        lng = data.get("longitude_i") or data.get("lng") or data.get("lon")
        if lat is None or lng is None:
            return

        # Meshtastic stores lat/lng as int32 × 1e-7
        if isinstance(lat, int) and abs(lat) > 1000:
            lat = lat / 1e7
        if isinstance(lng, int) and abs(lng) > 1000:
            lng = lng / 1e7

        lat = float(lat)
        lng = float(lng)
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            return
        if lat == 0.0 and lng == 0.0:
            return
        if abs(lat) < 0.1 and abs(lng) < 0.1:
            return
        if not _is_plausible_land(lat, lng):
            return

        callsign = data.get("from", data.get("sender", topic.split("/")[-1]))
        if isinstance(callsign, int):
            callsign = f"!{callsign:08x}"

        topic_meta = parse_topic_metadata(topic)

        text_content = data.get("text", data.get("message", ""))
        sig = {
            "callsign": str(callsign)[:20],
            "lat": round(lat, 5),
            "lng": round(lng, 5),
            "source": "meshtastic",
            "region": topic_meta["region"],
            "root": topic_meta["root"],
            "channel": topic_meta["channel"],
            "confidence": self.CONFIDENCE,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "raw_message": str(data)[:200],
            "snr": data.get("snr"),
            "altitude": data.get("altitude"),
        }
        if text_content:
            sig["status"] = str(text_content)[:200]
            emergency_kw = _scan_emergency(str(text_content))
            if emergency_kw:
                sig["emergency"] = True
                sig["emergency_keyword"] = emergency_kw
        self.signals.append(sig)


# ─── JS8Call Bridge ──────────────────────────────────────────────────────────


class JS8CallBridge:
    """Connects to local JS8Call API for HF digital mode intelligence.

    Requires JS8Call running locally with API enabled on port 2442.
    Gracefully disables itself if not available.
    """

    HOST = "127.0.0.1"
    PORT = 2442
    CONFIDENCE = 0.9

    def __init__(self):
        self.signals: deque[dict] = deque(maxlen=_MAX_SIGNALS)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._available = True

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._available = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="js8-bridge")
        self._thread.start()
        logger.info("JS8Call bridge started (will check for local instance)")

    def stop(self):
        self._stop.set()

    def _run(self):
        failures = 0
        while not self._stop.is_set():
            try:
                self._connect_and_read()
                failures = 0
            except ConnectionRefusedError:
                if self._available:
                    logger.info("JS8Call not running locally — bridge inactive (will retry)")
                    self._available = False
                failures += 1
            except Exception as e:
                logger.warning(f"JS8Call error: {e}")
                failures += 1

            # Exponential backoff: 30s, 60s, 120s, max 300s
            delay = min(30 * (2 ** min(failures, 4)), 300)
            self._stop.wait(delay)

    def _connect_and_read(self):
        with socket.create_connection((self.HOST, self.PORT), timeout=10) as sock:
            sock.settimeout(30)
            if not self._available:
                logger.info("JS8Call detected — bridge active")
                self._available = True
            buf = ""
            while not self._stop.is_set():
                try:
                    data = sock.recv(4096).decode("utf-8", errors="replace")
                except socket.timeout:
                    continue
                if not data:
                    break
                buf += data
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    self._parse_message(line.strip())

    def _parse_message(self, line: str):
        """Parse a JS8Call API JSON message."""
        if not line:
            return
        try:
            msg = json.loads(line)
            msg_type = msg.get("type", "")

            # We care about RX.DIRECTED and RX.ACTIVITY messages
            if msg_type not in ("RX.DIRECTED", "RX.ACTIVITY", "RX.SPOT"):
                return

            params = msg.get("params", {})
            callsign = params.get("FROM", params.get("CALL", ""))
            if not callsign:
                return

            # Grid locator → lat/lng
            grid = params.get("GRID", "")
            lat, lng = self._grid_to_latlon(grid)
            if lat is None:
                return

            freq = params.get("FREQ", params.get("DIAL", 0))
            snr = params.get("SNR")
            text = params.get("TEXT", "")

            self.signals.append(
                {
                    "callsign": callsign[:20],
                    "lat": lat,
                    "lng": lng,
                    "source": "js8call",
                    "confidence": self.CONFIDENCE,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "raw_message": text[:200] if text else line[:200],
                    "frequency": freq,
                    "snr": snr,
                    "grid": grid,
                }
            )
        except (json.JSONDecodeError, KeyError):
            pass

    @staticmethod
    def _grid_to_latlon(grid: str) -> tuple[float | None, float | None]:
        """Convert Maidenhead grid locator to lat/lng (center of grid square)."""
        if not grid or len(grid) < 4:
            return None, None
        try:
            grid = grid.upper()
            lng = (ord(grid[0]) - ord("A")) * 20 - 180
            lat = (ord(grid[1]) - ord("A")) * 10 - 90
            lng += int(grid[2]) * 2
            lat += int(grid[3])
            # Add center offset for 4-char grid
            if len(grid) >= 6:
                lng += (ord(grid[4]) - ord("A")) * (2 / 24)
                lat += (ord(grid[5]) - ord("A")) * (1 / 24)
                lng += 1 / 24
                lat += 1 / 48
            else:
                lng += 1
                lat += 0.5
            if -90 <= lat <= 90 and -180 <= lng <= 180:
                return round(lat, 4), round(lng, 4)
        except (IndexError, ValueError):
            pass
        return None, None


# ─── SIGINT Grid Orchestrator ────────────────────────────────────────────────


class SIGINTGrid:
    """Orchestrates all three SIGINT bridges and provides unified signal access."""

    def __init__(self):
        self.aprs = APRSBridge()
        self.mesh = MeshtasticBridge()
        self.js8 = JS8CallBridge()
        self._started = False

    def start(self):
        """Start all bridges (idempotent)."""
        if self._started:
            return
        self._started = True
        self.aprs.start()
        self.mesh.start()
        self.js8.start()
        logger.info("SIGINT Grid started (APRS + Meshtastic + JS8Call)")

    def stop(self):
        self.aprs.stop()
        self.mesh.stop()
        self.js8.stop()
        self._started = False

    def get_all_signals(self) -> list[dict]:
        """Merge signals from all bridges, deduplicate, and return newest first."""
        now = datetime.now(timezone.utc)
        all_signals = []

        for bridge in (self.aprs, self.mesh, self.js8):
            for sig in list(bridge.signals):
                # Filter stale signals
                try:
                    ts = datetime.fromisoformat(sig["timestamp"])
                    age = (now - ts).total_seconds()
                    if age > _MAX_AGE_S:
                        continue
                except (ValueError, KeyError):
                    continue
                all_signals.append(sig)

        # Deduplicate: keep latest per callsign+source
        seen: dict[str, dict] = {}
        for sig in all_signals:
            key = f"{sig['callsign']}:{sig['source']}"
            if key not in seen or sig["timestamp"] > seen[key]["timestamp"]:
                seen[key] = sig

        result = list(seen.values())
        result.sort(key=lambda x: x["timestamp"], reverse=True)
        return result

    def get_mesh_channel_stats(self, api_nodes: list[dict] | None = None) -> dict:
        """Aggregate Meshtastic channel populations from live MQTT + API nodes.

        Returns {
            "regions": { "US": {"nodes": 1234, "channels": {"LongFast": 45, ...}}, ... },
            "roots": { "US/rob/snd": {"nodes": 12, ...}, ... },
            "total_nodes": N,
            "total_live": N,   # from MQTT (last 10 min)
            "total_api": N,    # from map API
        }
        """
        now = datetime.now(timezone.utc)
        regions: dict[str, dict] = {}
        roots: dict[str, dict] = {}
        seen_callsigns: set[str] = set()
        live_count = 0

        # Live MQTT signals (recent, have region + channel)
        for sig in list(self.mesh.signals):
            try:
                ts = datetime.fromisoformat(sig["timestamp"])
                if (now - ts).total_seconds() > _MAX_AGE_S:
                    continue
            except (ValueError, KeyError):
                continue

            cs = sig.get("callsign", "")
            region = sig.get("region", "?")
            root = sig.get("root", region or "?")
            channel = sig.get("channel", "LongFast")
            if cs in seen_callsigns:
                continue
            seen_callsigns.add(cs)
            live_count += 1

            if region not in regions:
                regions[region] = {"nodes": 0, "live": 0, "channels": {}}
            regions[region]["nodes"] += 1
            regions[region]["live"] += 1
            regions[region]["channels"][channel] = regions[region]["channels"].get(channel, 0) + 1

            if root not in roots:
                roots[root] = {"nodes": 0, "live": 0, "region": region, "channels": {}}
            roots[root]["nodes"] += 1
            roots[root]["live"] += 1
            roots[root]["channels"][channel] = roots[root]["channels"].get(channel, 0) + 1

        # API nodes (global, no channel info but have region from topic/hardware)
        api_count = 0
        if api_nodes:
            for node in api_nodes:
                cs = node.get("callsign", "")
                if cs in seen_callsigns:
                    continue
                seen_callsigns.add(cs)
                api_count += 1
                # API nodes don't have region/channel — count as "MAP" region
                region = "MAP"
                if region not in regions:
                    regions[region] = {"nodes": 0, "live": 0, "channels": {}}
                regions[region]["nodes"] += 1

        # Also count messages per channel from the message log
        channel_msgs: dict[str, int] = {}
        for msg in list(self.mesh.messages):
            ch = msg.get("channel", "LongFast")
            channel_msgs[ch] = channel_msgs.get(ch, 0) + 1

        return {
            "regions": regions,
            "roots": roots,
            "known_roots": known_roots(
                str(getattr(get_settings(), "MESH_MQTT_EXTRA_ROOTS", "") or ""),
                include_defaults=bool(getattr(get_settings(), "MESH_MQTT_INCLUDE_DEFAULT_ROOTS", True)),
            ),
            "channel_messages": channel_msgs,
            "total_nodes": len(seen_callsigns),
            "total_live": live_count,
            "total_api": api_count,
        }

    @property
    def status(self) -> dict:
        """Return bridge status summary."""
        return {
            "aprs": len(self.aprs.signals),
            "meshtastic": len(self.mesh.signals),
            "js8call": len(self.js8.signals),
            "total": len(self.aprs.signals) + len(self.mesh.signals) + len(self.js8.signals),
        }


# ─── APRS-IS Transmit (two-way messaging) ─────────────────────────────────


def send_aprs_message(callsign: str, passcode: str, target: str, message: str) -> dict:
    """Send a text message to a specific callsign via APRS-IS.

    Requires a valid amateur radio callsign and passcode.
    Returns {"ok": True/False, "detail": "..."}.
    """
    if not callsign or not passcode or not target or not message:
        return {"ok": False, "detail": "Missing required fields"}
    if len(message) > 67:
        message = message[:67]

    server = "rotate.aprs2.net"
    port = 14580
    login = f"user {callsign} pass {passcode} vers ShadowBroker 1.0\r\n"
    # APRS message format: SENDER>APRS,TCPIP*::TARGET   :MESSAGE
    # Target must be exactly 9 chars (padded with spaces)
    packet = f"{callsign}>APRS,TCPIP*::{target.ljust(9)}:{message}\r\n"

    try:
        with socket.create_connection((server, port), timeout=10) as sock:
            sock.settimeout(10)
            banner = sock.recv(512).decode("utf-8", errors="replace")
            sock.sendall(login.encode("ascii"))
            response = sock.recv(512).decode("utf-8", errors="replace")
            if "verified" not in response.lower():
                return {"ok": False, "detail": "Login rejected — check callsign/passcode"}
            sock.sendall(packet.encode("utf-8", errors="replace"))
            logger.info(f"APRS TX: {callsign} → {target}: {message}")
            return {"ok": True, "detail": f"Message sent to {target}"}
    except (socket.timeout, ConnectionRefusedError, OSError) as e:
        return {"ok": False, "detail": f"Connection error: {e}"}


# ─── Nearest KiwiSDR finder ───────────────────────────────────────────────


def find_nearest_kiwisdr(
    lat: float, lng: float, kiwisdr_list: list[dict], max_results: int = 3
) -> list[dict]:
    """Find the closest KiwiSDR receivers to a given coordinate.

    Uses simple Euclidean distance (fine for ranking nearby points).
    Returns list of {name, url, distance_deg, bands, location}.
    """
    import math

    results = []
    for sdr in kiwisdr_list:
        slat = sdr.get("lat")
        slng = sdr.get("lon") or sdr.get("lng")
        if slat is None or slng is None:
            continue
        dist = math.sqrt((lat - slat) ** 2 + (lng - slng) ** 2)
        results.append(
            {
                "name": sdr.get("name", "Unknown SDR"),
                "url": sdr.get("url", ""),
                "distance_deg": round(dist, 2),
                "bands": sdr.get("bands", ""),
                "location": sdr.get("location", ""),
                "lat": slat,
                "lon": slng,
            }
        )
    results.sort(key=lambda x: x["distance_deg"])
    return results[:max_results]


# Module-level singleton — bridges start on first fetch
sigint_grid = SIGINTGrid()
