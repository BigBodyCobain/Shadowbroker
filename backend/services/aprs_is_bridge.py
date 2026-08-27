"""Resource-safe APRS-IS receive bridge.

The public APRS-IS network is community infrastructure. Shadowbroker therefore
uses it only when the operator explicitly opts in and supplies a bounded
geographic range. Public APRS-IS hosts never receive an unbounded/full-feed
subscription from this client.
"""

from __future__ import annotations

import logging
import os
import random
import re
import socket
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone

from services.sigint_bridge import _decode_aprs_symbol, _parse_aprs_comment, _scan_emergency

logger = logging.getLogger("services.sigint.aprs")

_TRUE_VALUES = {"1", "true", "yes", "on"}
_PUBLIC_APRS_SUFFIXES = (".aprs2.net", ".aprs-is.net", ".aprs.net")
_PUBLIC_APRS_HOSTS = {"rotate.aprs2.net", "srvr.aprs-is.net", "rotate.aprs.net"}
_DEFAULT_HOST = "rotate.aprs2.net"
_DEFAULT_PORT = 14580
_DEFAULT_RADIUS_KM = 100.0
_MAX_PUBLIC_RADIUS_KM = 500.0
_DEFAULT_MAX_SIGNALS = 5000
_MAX_SIGNAL_CAP = 20000
_SIGNAL_MAX_AGE_S = 600.0
_RECONNECT_BASE_S = 30.0
_RECONNECT_MAX_S = 900.0
_CALLSIGN_RE = re.compile(r"^[A-Z0-9-]{1,9}$")


@dataclass(frozen=True)
class APRSISConfig:
    host: str
    port: int
    login: str
    filter_expr: str
    private_server: bool


def _env_enabled(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUE_VALUES


def _bounded_int(name: str, default: int, low: int, high: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(low, min(value, high))


def aprs_is_enabled() -> bool:
    """Return whether APRS-IS networking is explicitly enabled."""
    return _env_enabled("APRS_IS_ENABLED", False)


def _is_public_aprs_host(host: str) -> bool:
    host = host.strip().lower().rstrip(".")
    return host in _PUBLIC_APRS_HOSTS or host.endswith(_PUBLIC_APRS_SUFFIXES)


def _parse_public_range() -> tuple[float, float, float]:
    lat_raw = (os.getenv("APRS_IS_LAT") or "").strip()
    lon_raw = (os.getenv("APRS_IS_LON") or "").strip()
    if not lat_raw or not lon_raw:
        raise ValueError(
            "APRS_IS_LAT and APRS_IS_LON are required for public APRS-IS; "
            "global/unbounded subscriptions are intentionally unsupported"
        )
    try:
        lat = float(lat_raw)
        lon = float(lon_raw)
    except ValueError as exc:
        raise ValueError("APRS_IS_LAT/APRS_IS_LON must be decimal degrees") from exc
    if not -90.0 <= lat <= 90.0 or not -180.0 <= lon <= 180.0:
        raise ValueError("APRS_IS_LAT/APRS_IS_LON are outside valid coordinate bounds")

    radius_raw = (os.getenv("APRS_IS_RADIUS_KM") or str(_DEFAULT_RADIUS_KM)).strip()
    try:
        radius = float(radius_raw)
    except ValueError as exc:
        raise ValueError("APRS_IS_RADIUS_KM must be numeric") from exc
    if not 1.0 <= radius <= _MAX_PUBLIC_RADIUS_KM:
        raise ValueError(
            f"APRS_IS_RADIUS_KM must be between 1 and {_MAX_PUBLIC_RADIUS_KM:g} km "
            "when using public APRS-IS"
        )
    return lat, lon, radius


def aprs_connection_config() -> APRSISConfig | None:
    """Build the receive configuration, failing closed on unsafe public filters.

    Public APRS-IS requires an explicit geographic center and enforces a 500 km
    maximum range. Operators running their own APRS-IS server may set
    APRS_IS_PRIVATE_SERVER=true; only then may APRS_IS_FILTER be arbitrary or
    blank. The private-server override is rejected for known public APRS hosts.
    """
    if not aprs_is_enabled():
        return None

    host = (os.getenv("APRS_IS_HOST") or _DEFAULT_HOST).strip()
    if not host or any(ch.isspace() for ch in host):
        raise ValueError("APRS_IS_HOST is invalid")
    port = _bounded_int("APRS_IS_PORT", _DEFAULT_PORT, 1, 65535)
    private_server = _env_enabled("APRS_IS_PRIVATE_SERVER", False)

    if private_server:
        if _is_public_aprs_host(host):
            raise ValueError("APRS_IS_PRIVATE_SERVER cannot be used with a public APRS-IS host")
        filter_expr = (os.getenv("APRS_IS_FILTER") or "").strip()
        if "\r" in filter_expr or "\n" in filter_expr:
            raise ValueError("APRS_IS_FILTER cannot contain line breaks")
    else:
        lat, lon, radius = _parse_public_range()
        filter_expr = f"r/{lat:.5f}/{lon:.5f}/{radius:g}"

    callsign = (os.getenv("APRS_IS_CALLSIGN") or "N0CALL").strip().upper()
    if not _CALLSIGN_RE.fullmatch(callsign):
        raise ValueError("APRS_IS_CALLSIGN must be 1-9 APRS-safe characters")

    login = f"user {callsign} pass -1 vers ShadowBroker 1.0"
    if filter_expr:
        login += f" filter {filter_expr}"
    login += "\r\n"
    return APRSISConfig(
        host=host,
        port=port,
        login=login,
        filter_expr=filter_expr,
        private_server=private_server,
    )


class APRSISBridge:
    """Long-lived, bounded, opt-in APRS-IS receive client."""

    CONFIDENCE = 0.7

    def __init__(self) -> None:
        max_signals = _bounded_int(
            "APRS_IS_MAX_SIGNALS",
            _DEFAULT_MAX_SIGNALS,
            100,
            _MAX_SIGNAL_CAP,
        )
        self.signals: deque[dict] = deque(maxlen=max_signals)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._socket_lock = threading.Lock()
        self._socket: socket.socket | None = None
        self._config: APRSISConfig | None = None
        self._connected = False
        self._last_error = ""

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and not self._stop.is_set())

    def status(self) -> dict[str, object]:
        return {
            "enabled": aprs_is_enabled(),
            "running": self.is_running(),
            "connected": self._connected,
            "buffered": len(self.signals),
            "last_error": self._last_error,
            "host": self._config.host if self._config else "",
            "filter": self._config.filter_expr if self._config else "",
        }

    def reconcile(self, layer_enabled: bool) -> None:
        """Match the network bridge to current operator layer/config state."""
        if not layer_enabled:
            self.stop()
            return
        try:
            config = aprs_connection_config()
        except ValueError as exc:
            self._last_error = str(exc)
            self.stop()
            logger.warning("APRS-IS disabled by safety validation: %s", exc)
            return
        if config is None:
            self._last_error = "APRS_IS_ENABLED is false"
            self.stop()
            return

        if self.is_running() and self._config == config:
            return
        if self.is_running() or self._config != config:
            self.stop()
        self._config = config
        self._last_error = ""
        self.start()

    def start(self) -> None:
        if self._config is None:
            try:
                self._config = aprs_connection_config()
            except ValueError as exc:
                self._last_error = str(exc)
                logger.warning("APRS-IS not started: %s", exc)
                return
        if self._config is None:
            return
        if self._thread and self._thread.is_alive():
            if not self._stop.is_set():
                return
            self._thread.join(timeout=2.0)
            if self._thread.is_alive():
                logger.warning("APRS-IS bridge is still stopping; start deferred")
                return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="aprs-safe-bridge")
        self._thread.start()
        logger.info(
            "APRS-IS bridge started on %s:%s with bounded filter %s",
            self._config.host,
            self._config.port,
            self._config.filter_expr or "server-default/private",
        )

    def stop(self) -> None:
        self._stop.set()
        self._connected = False
        with self._socket_lock:
            sock = self._socket
            self._socket = None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)

    @staticmethod
    def _reconnect_delay(failures: int) -> float:
        exponent = max(0, min(failures - 1, 5))
        base = min(_RECONNECT_BASE_S * (2**exponent), _RECONNECT_MAX_S)
        return base * random.uniform(0.85, 1.15)

    def _run(self) -> None:
        failures = 0
        while not self._stop.is_set():
            config = self._config
            if config is None:
                return
            try:
                self._connect_and_read(config)
                if self._stop.is_set():
                    return
                failures += 1
                self._last_error = "connection_closed"
            except Exception as exc:
                if self._stop.is_set():
                    return
                failures += 1
                self._last_error = f"{type(exc).__name__}: {exc}"
                logger.warning("APRS-IS connection error: %s", exc)
            delay = self._reconnect_delay(failures)
            logger.info("APRS-IS reconnect backoff %.0fs after %d failure(s)", delay, failures)
            self._stop.wait(delay)

    def _connect_and_read(self, config: APRSISConfig) -> None:
        sock = socket.create_connection((config.host, config.port), timeout=30)
        with self._socket_lock:
            if self._stop.is_set():
                sock.close()
                return
            self._socket = sock
        try:
            sock.settimeout(30)
            banner = sock.recv(512).decode("utf-8", errors="replace")
            logger.info("APRS-IS: %s", banner.strip())
            sock.sendall(config.login.encode("ascii"))
            self._connected = True
            self._last_error = ""
            buf = b""
            while not self._stop.is_set():
                try:
                    chunk = sock.recv(4096)
                except socket.timeout:
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
                    self._parse_packet(self._decode_line(line_bytes))
        finally:
            self._connected = False
            with self._socket_lock:
                if self._socket is sock:
                    self._socket = None
            try:
                sock.close()
            except OSError:
                pass

    @staticmethod
    def _decode_line(raw_bytes: bytes) -> str:
        try:
            return raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            pass
        try:
            return raw_bytes.decode("gbk")
        except UnicodeDecodeError:
            pass
        return raw_bytes.decode("latin-1")

    def _parse_packet(self, raw: str) -> None:
        try:
            if ":" not in raw:
                return
            header, payload = raw.split(":", 1)
            callsign = header.split(">")[0].strip()
            if not callsign or callsign == "N0CALL" or not payload or payload[0] not in "!@/=":
                return

            pos = payload[1:]
            lat = self._parse_lat(pos[:8])
            lng = self._parse_lng(pos[9:18])
            if lat is None or lng is None:
                return
            symbol = pos[8] + pos[18] if len(pos) > 18 else ""
            comment = pos[19:].strip() if len(pos) > 19 else ""
            meta = _parse_aprs_comment(comment)
            signal = {
                "callsign": callsign,
                "lat": lat,
                "lng": lng,
                "source": "aprs",
                "confidence": self.CONFIDENCE,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "raw_message": raw[:200],
                "symbol": symbol,
                "station_type": _decode_aprs_symbol(symbol),
                "comment": comment[:100],
            }
            for key in (
                "frequency",
                "altitude_ft",
                "speed_knots",
                "battery_v",
                "power_watts",
                "status",
            ):
                if meta.get(key) is not None:
                    signal[key] = meta[key]
            if meta.get("speed_knots"):
                signal["course"] = meta.get("course", 0)
            emergency_kw = _scan_emergency(comment) or _scan_emergency(signal.get("status", ""))
            if emergency_kw:
                signal["emergency"] = True
                signal["emergency_keyword"] = emergency_kw
            self.signals.append(signal)
        except (ValueError, IndexError):
            return

    def get_signals(self) -> list[dict]:
        """Return only recent APRS signals while keeping memory hard-bounded."""
        now = datetime.now(timezone.utc)
        result: list[dict] = []
        for signal in list(self.signals):
            try:
                timestamp = datetime.fromisoformat(str(signal["timestamp"]).replace("Z", "+00:00"))
                if (now - timestamp).total_seconds() > _SIGNAL_MAX_AGE_S:
                    continue
            except (KeyError, TypeError, ValueError):
                continue
            result.append(dict(signal))
        return result

    @staticmethod
    def _parse_lat(value: str) -> float | None:
        try:
            if len(value) < 8:
                return None
            degrees = int(value[:2])
            minutes = float(value[2:7])
            direction = value[7].upper()
            lat = degrees + minutes / 60.0
            if direction == "S":
                lat = -lat
            return round(lat, 5) if -90 <= lat <= 90 else None
        except (ValueError, IndexError):
            return None

    @staticmethod
    def _parse_lng(value: str) -> float | None:
        try:
            if len(value) < 9:
                return None
            degrees = int(value[:3])
            minutes = float(value[3:8])
            direction = value[8].upper()
            lng = degrees + minutes / 60.0
            if direction == "W":
                lng = -lng
            return round(lng, 5) if -180 <= lng <= 180 else None
        except (ValueError, IndexError):
            return None


aprs_is_bridge = APRSISBridge()
