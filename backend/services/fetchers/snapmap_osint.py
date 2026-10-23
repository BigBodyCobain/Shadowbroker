"""Snap Map OSINT — public-activity density over operator-defined watch zones.

What this layer does
--------------------
For each watch zone (AOI) configured by the operator, the fetcher asks the
public Snap Map web endpoint (the same one map.snapchat.com uses) how many
public snaps were posted around that point, compares the last-hour count with
a rolling baseline for the same hour of the week, and flags anomalies
("activity spike at 03:00 near site X").

Design rules (privacy by design — do not relax without a legal review)
---------------------------------------------------------------------
* Zone-centric, never person-centric: there is no search by account, no
  profile lookup, no face or identity processing.
* No user identifiers are kept. Only snap id, timestamp, media type, media URL
  and the locality title Snap itself shows are retained, in memory, for the
  most recent items of a zone. The SQLite store only holds aggregate counts.
* Minimum zone radius 500 m (no "single building" surveillance), max 85 km
  (upstream limit), max 40 zones, minimum scan interval 10 minutes.
* Media archiving is OFF by default. When enabled, only zones in alert are
  archived and files are purged after a retention window.

Reliability rating (A/B/C), consistent with OSINT source grading
-----------------------------------------------------------------
* C — Snap Map signal alone (density anomaly or normal reading).
* B — anomaly corroborated by at least one independent Shadowbroker layer
  (Telegram OSINT, news, GDELT, FIRMS fires) near the zone in the same window.
* A — never automatic: set by an analyst through the confirm endpoint after
  manual verification.

Upstream notes
--------------
Endpoints are undocumented (``ms.sc-jpl.com/web/getLatestTileSet`` and
``/web/getPlaylist``) and may change or rate-limit without notice; automated
access is not permitted by Snap's terms. Keep the scan cadence conservative.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from services.fetchers._store import _data_lock, _mark_fresh, is_any_active, latest_data
from services.network_utils import fetch_with_curl, outbound_user_agent

logger = logging.getLogger(__name__)

API_HOST = os.environ.get("SNAPMAP_API_HOST", "https://ms.sc-jpl.com").rstrip("/")

MIN_RADIUS_M = 500
MAX_RADIUS_M = 85_000
MAX_ZONES = 40
MIN_INTERVAL_MINUTES = 10
MEDIA_PER_ZONE = 12
READINGS_RETENTION_DAYS = 35
BASELINE_DAYS = 28
MIN_BASELINE_SAMPLES = 6
CORROBORATION_WINDOW_H = 6
CORROBORATION_EXTRA_KM = 10.0

SNAP_MEDIA_HOST_SUFFIXES = (".sc-cdn.net",)

_DATA_DIR = Path(os.environ.get("SB_DATA_DIR", str(Path(__file__).resolve().parents[2] / "data")))
if not _DATA_DIR.is_absolute():
    _DATA_DIR = Path(__file__).resolve().parents[2] / _DATA_DIR

_DEFAULT_SECURITY_KEYWORDS = (
    # FR
    "incendie", "explosion", "manifestation", "manif", "émeute", "emeute", "police",
    "gendarmerie", "pompiers", "attentat", "fusillade", "évacuation", "evacuation",
    "accident", "drone", "alerte", "bouclage", "barrage",
    # EN
    "fire", "explosion", "protest", "riot", "police", "shooting", "evacuation",
    "attack", "drone", "lockdown", "blast", "smoke",
)

_db_lock = threading.Lock()

_EMPTY_PAYLOAD: dict[str, Any] = {
    "zones": [],
    "alerts": [],
    "total_zones": 0,
    "anomalies": 0,
    "timestamp": None,
}


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
def snapmap_osint_enabled() -> bool:
    return str(os.environ.get("SNAPMAP_OSINT_ENABLED", "true")).strip().lower() not in {
        "0", "false", "no", "off", "",
    }


def scan_interval_minutes() -> int:
    try:
        value = int(os.environ.get("SNAPMAP_OSINT_INTERVAL_MINUTES", "15"))
    except ValueError:
        value = 15
    return max(MIN_INTERVAL_MINUTES, value)


def archive_media_enabled() -> bool:
    return str(os.environ.get("SNAPMAP_ARCHIVE_MEDIA", "false")).strip().lower() in {"1", "true", "yes", "on"}


def archive_retention_hours() -> int:
    try:
        return max(1, int(os.environ.get("SNAPMAP_ARCHIVE_RETENTION_HOURS", "72")))
    except ValueError:
        return 72


def zones_file() -> Path:
    raw = os.environ.get("SNAPMAP_ZONES_FILE", "").strip()
    return Path(raw) if raw else _DATA_DIR / "snapmap_zones.json"


def db_path() -> Path:
    raw = os.environ.get("SNAPMAP_DB_PATH", "").strip()
    return Path(raw) if raw else _DATA_DIR / "snapmap_osint.db"


def archive_dir() -> Path:
    return _DATA_DIR / "snapmap_archive"


def snap_media_host_allowed(hostname: str | None) -> bool:
    host = str(hostname or "").strip().lower()
    return bool(host) and any(host.endswith(suffix) for suffix in SNAP_MEDIA_HOST_SUFFIXES)


_SLUG_RE = re.compile(r"[^a-z0-9_-]+")


def normalize_zone(raw: dict[str, Any], index: int = 0) -> dict[str, Any] | None:
    """Validate one zone and enforce guardrails. Returns None if unusable."""
    try:
        lat = float(raw.get("lat"))
        lon = float(raw.get("lon", raw.get("lng")))
    except (TypeError, ValueError):
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    if abs(lat) < 1e-6 and abs(lon) < 1e-6:
        return None
    try:
        radius = int(float(raw.get("radius_m", 2000)))
    except (TypeError, ValueError):
        radius = 2000
    radius = max(MIN_RADIUS_M, min(MAX_RADIUS_M, radius))

    label = str(raw.get("label") or f"Zone {index + 1}").strip()[:80]
    zone_id = _SLUG_RE.sub("-", str(raw.get("id") or label).strip().lower()).strip("-")[:48] or f"zone-{index + 1}"
    keywords = raw.get("keywords") or []
    if isinstance(keywords, str):
        keywords = [k for k in keywords.split(",")]
    keywords = [str(k).strip().lower() for k in keywords if str(k).strip()][:30]

    return {
        "id": zone_id,
        "label": label,
        "lat": round(lat, 6),
        "lng": round(lon, 6),
        "radius_m": radius,
        "category": str(raw.get("category") or "veille").strip()[:40],
        "keywords": keywords,
    }


def normalize_zones(raw_list: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    zones: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, raw in enumerate(raw_list or []):
        if not isinstance(raw, dict):
            continue
        zone = normalize_zone(raw, i)
        if not zone or zone["id"] in seen:
            continue
        seen.add(zone["id"])
        zones.append(zone)
        if len(zones) >= MAX_ZONES:
            break
    return zones


def load_zones() -> list[dict[str, Any]]:
    path = zones_file()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Snap Map zones file unreadable (%s): %s", path, exc)
        return []
    if isinstance(data, dict):
        data = data.get("zones", [])
    return normalize_zones(data if isinstance(data, list) else [])


def save_zones(raw_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    zones = normalize_zones(raw_list)
    path = zones_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"zones": zones}, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return zones


# ---------------------------------------------------------------------------
# SQLite store — aggregate counts and alerts only (no media, no identifiers)
# ---------------------------------------------------------------------------
def _connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS readings (
            zone_id TEXT NOT NULL,
            ts REAL NOT NULL,
            hour_of_week INTEGER NOT NULL,
            count_24h INTEGER NOT NULL,
            count_1h INTEGER NOT NULL
        )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_readings_zone_ts ON readings(zone_id, ts)")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            zone_id TEXT NOT NULL,
            label TEXT NOT NULL,
            ts REAL NOT NULL,
            level TEXT NOT NULL,
            z REAL NOT NULL,
            count_1h INTEGER NOT NULL,
            baseline_mean REAL,
            reliability TEXT NOT NULL,
            corroboration TEXT NOT NULL DEFAULT '[]',
            confirmed INTEGER NOT NULL DEFAULT 0,
            analyst_note TEXT
        )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_alerts_ts ON alerts(ts)")
    return conn


def _hour_of_week(ts: float) -> int:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.weekday() * 24 + dt.hour


def record_reading(zone_id: str, ts: float, count_24h: int, count_1h: int) -> None:
    with _db_lock, _connect() as conn:
        conn.execute(
            "INSERT INTO readings(zone_id, ts, hour_of_week, count_24h, count_1h) VALUES (?,?,?,?,?)",
            (zone_id, ts, _hour_of_week(ts), int(count_24h), int(count_1h)),
        )


def purge_old_rows(now: float | None = None) -> None:
    now = now or time.time()
    with _db_lock, _connect() as conn:
        conn.execute("DELETE FROM readings WHERE ts < ?", (now - READINGS_RETENTION_DAYS * 86400,))
        conn.execute("DELETE FROM alerts WHERE ts < ?", (now - READINGS_RETENTION_DAYS * 86400,))


def compute_baseline(zone_id: str, now: float) -> tuple[float | None, float | None, int]:
    """Mean/std of last-hour counts for the same hour-of-week (±1h), last 28 days.

    Falls back to every reading of the last 7 days while the zone warms up.
    Returns (mean, std, n_samples); mean is None when samples are insufficient.
    """
    how = _hour_of_week(now)
    buckets = {(how - 1) % 168, how, (how + 1) % 168}
    with _db_lock, _connect() as conn:
        rows = conn.execute(
            "SELECT count_1h, hour_of_week FROM readings WHERE zone_id = ? AND ts >= ? AND ts < ?",
            (zone_id, now - BASELINE_DAYS * 86400, now - 60),
        ).fetchall()
        seasonal = [r[0] for r in rows if r[1] in buckets]
        if len(seasonal) < MIN_BASELINE_SAMPLES:
            recent = conn.execute(
                "SELECT count_1h FROM readings WHERE zone_id = ? AND ts >= ? AND ts < ?",
                (zone_id, now - 7 * 86400, now - 60),
            ).fetchall()
            samples = [r[0] for r in recent]
        else:
            samples = seasonal
    if len(samples) < MIN_BASELINE_SAMPLES:
        return None, None, len(samples)
    mean = sum(samples) / len(samples)
    var = sum((s - mean) ** 2 for s in samples) / max(1, len(samples) - 1)
    return mean, math.sqrt(var), len(samples)


def score_anomaly(count_1h: int, mean: float | None, std: float | None) -> tuple[float, str]:
    """Robust z-score with a Poisson floor so quiet zones don't alert on +2 snaps."""
    if mean is None:
        return 0.0, "warmup"
    spread = max(std or 0.0, math.sqrt(max(mean, 0.0)), 1.0)
    z = (count_1h - mean) / spread
    if count_1h < 5:  # absolute floor: a handful of snaps is never an "event"
        return round(z, 2), "normal"
    if z >= 4:
        return round(z, 2), "critical"
    if z >= 3:
        return round(z, 2), "high"
    if z >= 2:
        return round(z, 2), "elevated"
    return round(z, 2), "normal"


_LEVEL_RANK = {"normal": 0, "elevated": 1, "high": 2, "critical": 3}
ALERT_DEDUP_SECONDS = 3600


def record_alert(zone: dict[str, Any], ts: float, level: str, z: float, count_1h: int,
                 mean: float | None, reliability: str, corroboration: list[dict[str, Any]]) -> int:
    """Insert an alert, or fold it into the zone's open alert from the last hour.

    A zone that stays hot only creates a new alert when its level escalates;
    otherwise the open alert is refreshed (count, z, and C→B upgrade if
    corroboration arrived). Analyst-confirmed alerts are never downgraded.
    """
    with _db_lock, _connect() as conn:
        open_row = conn.execute(
            """SELECT id, level, reliability, confirmed FROM alerts
               WHERE zone_id = ? AND ts >= ? ORDER BY ts DESC LIMIT 1""",
            (zone["id"], ts - ALERT_DEDUP_SECONDS),
        ).fetchone()
        if open_row and _LEVEL_RANK.get(level, 0) <= _LEVEL_RANK.get(open_row[1], 0):
            alert_id, _lvl, old_rel, confirmed = open_row
            new_rel = old_rel if (confirmed or old_rel == "B") else reliability
            conn.execute(
                """UPDATE alerts SET z = MAX(z, ?), count_1h = MAX(count_1h, ?), reliability = ?,
                          corroboration = CASE WHEN ? != '[]' THEN ? ELSE corroboration END
                   WHERE id = ?""",
                (z, count_1h, new_rel, json.dumps(corroboration, ensure_ascii=False),
                 json.dumps(corroboration, ensure_ascii=False), alert_id),
            )
            return int(alert_id)
        cur = conn.execute(
            """INSERT INTO alerts(zone_id, label, ts, level, z, count_1h, baseline_mean, reliability, corroboration)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (zone["id"], zone["label"], ts, level, z, count_1h, mean, reliability,
             json.dumps(corroboration, ensure_ascii=False)),
        )
        return int(cur.lastrowid)


def list_alerts(limit: int = 50) -> list[dict[str, Any]]:
    with _db_lock, _connect() as conn:
        rows = conn.execute(
            """SELECT id, zone_id, label, ts, level, z, count_1h, baseline_mean, reliability,
                      corroboration, confirmed, analyst_note
               FROM alerts ORDER BY ts DESC LIMIT ?""",
            (max(1, min(500, limit)),),
        ).fetchall()
    out = []
    for r in rows:
        out.append({
            "id": r[0], "zone_id": r[1], "label": r[2],
            "time": datetime.fromtimestamp(r[3], tz=timezone.utc).isoformat(),
            "level": r[4], "z": r[5], "count_1h": r[6], "baseline_mean": r[7],
            "reliability": r[8], "corroboration": json.loads(r[9] or "[]"),
            "confirmed": bool(r[10]), "analyst_note": r[11],
        })
    return out


def confirm_alert(alert_id: int, note: str = "") -> dict[str, Any] | None:
    """Analyst confirmation after manual verification — the only path to an A rating."""
    with _db_lock, _connect() as conn:
        cur = conn.execute(
            "UPDATE alerts SET confirmed = 1, reliability = 'A', analyst_note = ? WHERE id = ?",
            (str(note or "")[:500], int(alert_id)),
        )
        if cur.rowcount == 0:
            return None
    for alert in list_alerts(500):
        if alert["id"] == int(alert_id):
            return alert
    return None


# ---------------------------------------------------------------------------
# Upstream (Snap Map web endpoints)
# ---------------------------------------------------------------------------
class SnapmapRateLimited(RuntimeError):
    pass


def _headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": "https://map.snapchat.com",
        "Referer": "https://map.snapchat.com/",
        "User-Agent": (
            f"Mozilla/5.0 (compatible; {outbound_user_agent('snapmap-osint')}) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
    }


def _post_json(path: str, body: dict[str, Any]) -> Any:
    resp = fetch_with_curl(f"{API_HOST}{path}", method="POST", json_data=body, timeout=20, headers=_headers())
    if resp is None:
        raise RuntimeError("no response")
    text = (resp.text or "").strip()
    if resp.status_code == 429 or text.lower().startswith("too many requests"):
        raise SnapmapRateLimited(path)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}")
    return json.loads(text)


def fetch_heat_epoch() -> Any:
    data = _post_json("/web/getLatestTileSet", {})
    for entry in (data or {}).get("tileSetInfos", []):
        ident = entry.get("id") or {}
        if ident.get("type") == "HEAT":
            return ident.get("epoch")
    raise RuntimeError("HEAT tileset epoch not found")


def _zoom_for_radius(radius_m: int) -> int:
    if radius_m <= 1500:
        return 14
    if radius_m <= 5000:
        return 12
    if radius_m <= 20000:
        return 10
    return 8


def fetch_zone_elements(zone: dict[str, Any], epoch: Any) -> list[dict[str, Any]]:
    body = {
        "requestGeoPoint": {"lat": zone["lat"], "lon": zone["lng"]},
        "zoomLevel": _zoom_for_radius(zone["radius_m"]),
        "tileSetId": {"flavor": "default", "epoch": epoch, "type": 1},
        "radiusMeters": zone["radius_m"],
        "maximumFuzzRadius": 0,
    }
    data = _post_json("/web/getPlaylist", body)
    return list(((data or {}).get("manifest") or {}).get("elements") or [])


def parse_element(el: dict[str, Any]) -> dict[str, Any] | None:
    """Keep only non-identifying fields. Anything else in the element is dropped."""
    snap_id = str(el.get("id") or "").strip()
    info = el.get("snapInfo") or {}
    try:
        ts = int(el.get("timestamp")) / 1000.0
    except (TypeError, ValueError):
        return None
    if not snap_id or ts <= 0:
        return None
    media = info.get("streamingMediaInfo") or {}
    url = media.get("mediaUrl") or media.get("previewUrl")
    media_type = "video" if info.get("snapMediaType") else "image"
    locality = (
        (info.get("title") or {}).get("fallback")
        or (info.get("localitySubtitle") or {}).get("fallback")
        or ""
    )
    return {
        "id": snap_id[:64],
        "ts": ts,
        "time": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
        "type": media_type,
        "url": url if isinstance(url, str) else None,
        "locality": str(locality)[:120],
    }


# ---------------------------------------------------------------------------
# Filters and corroboration
# ---------------------------------------------------------------------------
def keyword_hits(items: list[dict[str, Any]], zone_keywords: list[str]) -> list[str]:
    vocab = set(zone_keywords) | set(_DEFAULT_SECURITY_KEYWORDS)
    hits: set[str] = set()
    for item in items:
        text = str(item.get("locality") or "").lower()
        for kw in vocab:
            if kw and kw in text:
                hits.add(kw)
    return sorted(hits)


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _item_coords(item: Any) -> tuple[float, float] | None:
    if not isinstance(item, dict):
        return None
    try:
        coords = item.get("coords")
        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
            return float(coords[0]), float(coords[1])
        for la, lo in (("lat", "lng"), ("lat", "lon"), ("latitude", "longitude")):
            if item.get(la) is not None and item.get(lo) is not None:
                return float(item[la]), float(item[lo])
        geom = item.get("geometry") or {}
        gc = geom.get("coordinates") if isinstance(geom, dict) else None
        if isinstance(gc, (list, tuple)) and len(gc) >= 2 and not isinstance(gc[0], (list, tuple)):
            return float(gc[1]), float(gc[0])
    except (TypeError, ValueError):
        return None
    return None


def _item_time(item: dict[str, Any]) -> float | None:
    props = item.get("properties") if isinstance(item.get("properties"), dict) else {}
    for key in ("published", "pubDate", "timestamp", "time", "date"):
        raw = item.get(key) or props.get(key)
        if not raw:
            continue
        if isinstance(raw, (int, float)):
            return float(raw) / (1000.0 if raw > 1e12 else 1.0)
        try:
            return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
    return None


def _item_title(item: dict[str, Any]) -> str:
    props = item.get("properties") if isinstance(item.get("properties"), dict) else {}
    return str(item.get("title") or props.get("title") or props.get("name") or item.get("name") or "")[:140]


def find_corroboration(zone: dict[str, Any], snapshot: dict[str, Any], now: float) -> list[dict[str, Any]]:
    """Independent signals from other layers near the zone, within the time window."""
    max_km = zone["radius_m"] / 1000.0 + CORROBORATION_EXTRA_KM
    window_start = now - CORROBORATION_WINDOW_H * 3600
    sources: list[tuple[str, list[Any], bool]] = [
        ("telegram_osint", list((snapshot.get("telegram_osint") or {}).get("posts") or []), True),
        ("news", list(snapshot.get("news") or []), True),
        ("gdelt", list(snapshot.get("gdelt") or []), False),
        ("firms_fires", list(snapshot.get("firms_fires") or []), False),
    ]
    found: list[dict[str, Any]] = []
    for layer, items, needs_time in sources:
        best: dict[str, Any] | None = None
        for item in items:
            coords = _item_coords(item)
            if not coords:
                continue
            dist = _haversine_km(zone["lat"], zone["lng"], coords[0], coords[1])
            if dist > max_km:
                continue
            ts = _item_time(item) if isinstance(item, dict) else None
            if needs_time and (ts is None or ts < window_start):
                continue
            if ts is not None and ts < window_start:
                continue
            if best is None or dist < best["distance_km"]:
                best = {"layer": layer, "title": _item_title(item), "distance_km": round(dist, 1)}
        if best:
            found.append(best)
    return found


def rate_reliability(level: str, corroboration: list[dict[str, Any]]) -> str:
    if level in {"elevated", "high", "critical"} and corroboration:
        return "B"
    return "C"


# ---------------------------------------------------------------------------
# Optional media archive (OFF by default)
# ---------------------------------------------------------------------------
def _archive_media(zone_id: str, items: list[dict[str, Any]]) -> None:
    from urllib.parse import urlparse

    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    target = archive_dir() / zone_id / day
    target.mkdir(parents=True, exist_ok=True)
    for item in items:
        url = item.get("url")
        if not url or not snap_media_host_allowed(urlparse(url).hostname):
            continue
        ext = "mp4" if item.get("type") == "video" else "jpg"
        path = target / f"{item['id']}.{ext}"
        if path.exists():
            continue
        try:
            resp = fetch_with_curl(url, timeout=30, headers={"User-Agent": _headers()["User-Agent"]})
            if resp is not None and resp.status_code == 200 and resp.content:
                path.write_bytes(resp.content)
        except Exception as exc:  # archive is best-effort
            logger.debug("Snap Map archive download failed for %s: %s", item["id"], exc)


def purge_archive(now: float | None = None) -> int:
    root = archive_dir()
    if not root.exists():
        return 0
    cutoff = (now or time.time()) - archive_retention_hours() * 3600
    removed = 0
    for path in root.rglob("*"):
        if path.is_file() and path.stat().st_mtime < cutoff:
            path.unlink(missing_ok=True)
            removed += 1
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    return removed


# ---------------------------------------------------------------------------
# Main fetch
# ---------------------------------------------------------------------------
def _zone_skeleton(zone: dict[str, Any]) -> dict[str, Any]:
    return {
        **{k: zone[k] for k in ("id", "label", "lat", "lng", "radius_m", "category")},
        "count_24h": 0, "count_1h": 0, "baseline_mean": None, "baseline_std": None,
        "baseline_samples": 0, "z": 0.0, "level": "unknown", "reliability": "C",
        "corroboration": [], "keyword_hits": [], "media": [], "status": "pending", "last_scan": None,
    }


def scan_zone(zone: dict[str, Any], epoch: Any, snapshot: dict[str, Any], now: float) -> dict[str, Any]:
    out = _zone_skeleton(zone)
    elements = fetch_zone_elements(zone, epoch)
    items = [p for p in (parse_element(e) for e in elements) if p]
    items = [i for i in items if i["ts"] >= now - 86400]
    items.sort(key=lambda i: i["ts"], reverse=True)

    count_24h = len(items)
    count_1h = sum(1 for i in items if i["ts"] >= now - 3600)
    mean, std, n = compute_baseline(zone["id"], now)
    z, level = score_anomaly(count_1h, mean, std)
    record_reading(zone["id"], now, count_24h, count_1h)

    corroboration = find_corroboration(zone, snapshot, now) if level not in {"normal", "warmup"} else []
    reliability = rate_reliability(level, corroboration)
    media = [{k: i[k] for k in ("id", "time", "type", "url", "locality")} for i in items[:MEDIA_PER_ZONE]]

    out.update({
        "count_24h": count_24h,
        "count_1h": count_1h,
        "baseline_mean": round(mean, 2) if mean is not None else None,
        "baseline_std": round(std, 2) if std is not None else None,
        "baseline_samples": n,
        "z": z,
        "level": level,
        "reliability": reliability,
        "corroboration": corroboration,
        "keyword_hits": keyword_hits(items, zone.get("keywords") or []),
        "media": media,
        "status": "warmup" if level == "warmup" else "ok",
        "last_scan": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
    })

    if level in {"elevated", "high", "critical"}:
        out["alert_id"] = record_alert(zone, now, level, z, count_1h, mean, reliability, corroboration)
        if archive_media_enabled():
            _archive_media(zone["id"], items[:MEDIA_PER_ZONE])
    return out


def fetch_snapmap_osint(*, sleep_between_zones: float = 2.0) -> dict[str, Any]:
    if not is_any_active("snapmap_osint"):
        return latest_data.get("snapmap_osint") or dict(_EMPTY_PAYLOAD)

    if not snapmap_osint_enabled():
        payload = {**_EMPTY_PAYLOAD, "disabled": True}
        with _data_lock:
            latest_data["snapmap_osint"] = payload
        _mark_fresh("snapmap_osint")
        return payload

    zones = load_zones()
    now = time.time()
    with _data_lock:
        snapshot = {
            "telegram_osint": latest_data.get("telegram_osint"),
            "news": latest_data.get("news"),
            "gdelt": latest_data.get("gdelt"),
            "firms_fires": latest_data.get("firms_fires"),
        }
        prior = {z.get("id"): z for z in (latest_data.get("snapmap_osint") or {}).get("zones") or []}

    results: list[dict[str, Any]] = []
    error: str | None = None
    epoch = None
    if zones:
        try:
            epoch = fetch_heat_epoch()
        except SnapmapRateLimited:
            error = "rate_limited"
        except Exception as exc:
            error = f"epoch: {exc}"

    for idx, zone in enumerate(zones):
        if epoch is None:
            stale = dict(prior.get(zone["id"]) or _zone_skeleton(zone))
            stale["status"] = "error"
            results.append(stale)
            continue
        try:
            results.append(scan_zone(zone, epoch, snapshot, now))
        except SnapmapRateLimited:
            error = "rate_limited"
            logger.warning("Snap Map rate limit hit; stopping this cycle after %s zones", idx)
            epoch = None  # remaining zones keep their last reading
            stale = dict(prior.get(zone["id"]) or _zone_skeleton(zone))
            stale["status"] = "error"
            results.append(stale)
        except Exception as exc:
            logger.warning("Snap Map zone %s failed: %s", zone["id"], exc)
            stale = dict(prior.get(zone["id"]) or _zone_skeleton(zone))
            stale["status"] = "error"
            results.append(stale)
        if sleep_between_zones and idx < len(zones) - 1:
            time.sleep(sleep_between_zones)

    try:
        purge_old_rows(now)
        if archive_media_enabled():
            purge_archive(now)
    except Exception as exc:
        logger.debug("Snap Map purge failed: %s", exc)

    try:
        alerts = list_alerts(50)
    except Exception:
        alerts = []

    payload = {
        "zones": results,
        "alerts": alerts,
        "total_zones": len(results),
        "anomalies": sum(1 for r in results if r.get("level") in {"elevated", "high", "critical"}),
        "timestamp": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
        "interval_minutes": scan_interval_minutes(),
        "archive_media": archive_media_enabled(),
        "error": error,
        "source": "Snap Map (public snaps, unofficial endpoint)",
    }
    with _data_lock:
        latest_data["snapmap_osint"] = payload
    _mark_fresh("snapmap_osint")
    logger.info(
        "Snap Map OSINT: %s zones scanned, %s anomalies%s",
        len(results), payload["anomalies"], f" ({error})" if error else "",
    )
    return payload
