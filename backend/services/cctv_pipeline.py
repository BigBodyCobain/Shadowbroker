import json
import os
import sqlite3
import requests
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse, quote
from services.network_utils import fetch_with_curl
import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "cctv.db"

_KNOWN_CCTV_MEDIA_HOST_ALIASES = {
    # Trusted upstream occasionally publishes a typo for this Georgia camera
    # host. Normalize it at ingest so the proxy and client stay consistent.
    "navigatos-c2c.dot.ga.gov": "navigator-c2c.dot.ga.gov",
    # TravelIQ staging hosts occasionally appear in 511 catalog metadata.
    "on.stage.traveliq.co": "511on.ca",
    "ab.stage.traveliq.co": "511.alberta.ca",
}

_POINT_WKT_RE = re.compile(
    r"POINT\s*\(\s*([-+]?\d+(?:\.\d+)?)\s+([-+]?\d+(?:\.\d+)?)\s*\)",
    re.IGNORECASE,
)


def _normalize_cctv_media_url(raw_url: str) -> str:
    candidate = str(raw_url or "").strip()
    if not candidate:
        return ""
    parsed = urlparse(candidate)
    host = str(parsed.hostname or "").strip().lower()
    replacement = _KNOWN_CCTV_MEDIA_HOST_ALIASES.get(host)
    if not replacement:
        return candidate
    netloc = replacement
    if parsed.port:
        netloc = f"{replacement}:{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc))


def _ensure_https_url(raw_url: str) -> str:
    """Upgrade http:// media/catalog URLs to https:// at ingest time."""
    candidate = _normalize_cctv_media_url(str(raw_url or "").strip())
    if not candidate:
        return ""
    parsed = urlparse(candidate)
    if parsed.scheme.lower() == "http":
        return urlunparse(parsed._replace(scheme="https"))
    return candidate


def _looks_like_direct_cctv_media_url(url: str) -> bool:
    candidate = str(url or "").strip().lower()
    if not candidate.startswith(("http://", "https://")):
        return False
    parsed = urlparse(candidate)
    path = str(parsed.path or "").lower()
    if any(path.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".webm", ".m3u8", ".mjpg", ".mjpeg")):
        return True
    return any(token in candidate for token in ("snapshot", "/image/", "playlist.m3u8", "mjpg", "mjpeg"))


def _extract_direct_cctv_media_from_tags(tags: Dict[str, Any]) -> tuple[str, str]:
    for key in ("camera:url", "camera:image", "image", "url", "website"):
        raw = _normalize_cctv_media_url(str(tags.get(key) or "").strip())
        if not raw:
            continue
        if key in {"url", "website"} and not _looks_like_direct_cctv_media_url(raw):
            continue
        media_type = _detect_media_type(raw)
        if key in {"camera:image", "image"} and media_type == "image":
            return raw, "image"
        if media_type in {"video", "hls", "mjpeg"} or _looks_like_direct_cctv_media_url(raw):
            return raw, media_type or "image"
    return "", "image"


def _media_url_reachable(url: str, *, timeout: int = 8, headers: Dict[str, str] | None = None) -> bool:
    candidate = _normalize_cctv_media_url(str(url or "").strip())
    if not candidate:
        return False
    try:
        resp = fetch_with_curl(candidate, timeout=timeout, headers=headers or {})
    except Exception as exc:
        logger.debug(f"CCTV media probe failed for {candidate}: {exc}")
        return False
    return bool(resp and int(getattr(resp, "status_code", 500) or 500) < 400)


def _parse_wkt_point(raw_point: str) -> tuple[float | None, float | None]:
    candidate = str(raw_point or "").strip()
    if not candidate:
        return None, None
    match = _POINT_WKT_RE.search(candidate)
    if not match:
        return None, None
    try:
        lon = float(match.group(1))
        lat = float(match.group(2))
    except (TypeError, ValueError):
        return None, None
    return lat, lon


def _fetch_traveliq_v2_cameras(
    *,
    api_url: str,
    base_url: str,
    id_prefix: str,
    source_agency: str,
) -> List[Dict[str, Any]]:
    """Parse TravelIQ-style GET /api/v2/get/cameras feeds (Ontario, Alberta)."""
    resp = fetch_with_curl(
        api_url,
        timeout=30,
        headers={"Accept": "application/json"},
    )
    if not resp or resp.status_code != 200:
        logger.error(
            "%s CCTV fetch failed: HTTP %s",
            source_agency,
            resp.status_code if resp else "no response",
        )
        return []

    data = resp.json()
    if not isinstance(data, list):
        return []

    cameras: List[Dict[str, Any]] = []
    for cam in data:
        if not isinstance(cam, dict):
            continue
        try:
            lat = float(cam.get("Latitude"))
            lon = float(cam.get("Longitude"))
        except (TypeError, ValueError):
            continue

        site_id = cam.get("Id")
        location = str(cam.get("Location") or cam.get("Roadway") or "Camera")[:120]
        views = cam.get("Views") or []
        if not views:
            continue

        for view in views:
            if not isinstance(view, dict):
                continue
            status = str(view.get("Status") or "enabled").strip().lower()
            if status and status not in {"enabled", "active"}:
                continue
            media_url = _ensure_https_url(
                urljoin(base_url, str(view.get("Url") or "").strip())
            )
            if not media_url:
                continue
            view_id = view.get("Id") or site_id
            if site_id is None or view_id is None:
                continue
            label = str(view.get("Description") or location or "Camera")[:120]
            cameras.append(
                {
                    "id": f"{id_prefix}-{site_id}-{view_id}",
                    "source_agency": source_agency,
                    "lat": lat,
                    "lon": lon,
                    "direction_facing": label,
                    "media_url": media_url,
                    "media_type": "image",
                    "refresh_rate_seconds": 60,
                }
            )
    return cameras


def _fetch_511_datatables_cameras(
    *,
    list_url: str,
    base_url: str,
    id_prefix: str,
    source_agency: str,
    referer: str,
    page_size: int = 500,
    query_in_url: bool = False,
) -> List[Dict[str, Any]]:
    """Parse 511 DataTables POST /List/GetData/Cameras feeds (Georgia, Florida).

    With query_in_url the page is requested as GET ?query=<json>&lang=en, the
    form drivenc.gov answers (its POST returns no rows, and it caps pages at 100).
    """
    cameras: List[Dict[str, Any]] = []
    start = 0
    draw = 1
    while True:
        if query_in_url:
            query = json.dumps({
                "columns": [{"data": None, "name": ""}, {"name": "sortOrder", "s": True},
                            {"name": "roadway", "s": True}, {"data": 3, "name": ""}],
                "order": [{"column": 1, "dir": "asc"}],
                "start": start, "length": page_size, "search": {"value": ""},
            }, separators=(",", ":"))
            resp = fetch_with_curl(
                f"{list_url}?query={quote(query, safe='')}&lang=en",
                timeout=30,
                headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest", "Referer": referer},
            )
        else:
            resp = fetch_with_curl(
                list_url,
                method="POST",
                json_data={"draw": draw, "start": start, "length": page_size},
                timeout=30,
                headers={
                    "Accept": "application/json",
                    "Referer": referer,
                    "Origin": base_url.rstrip("/"),
                },
            )
        if not resp or resp.status_code != 200:
            logger.error(
                "%s CCTV fetch failed: HTTP %s",
                source_agency,
                resp.status_code if resp else "no response",
            )
            break

        data = resp.json()
        rows = data.get("data") or []
        if not rows:
            break

        for row in rows:
            if not isinstance(row, dict):
                continue
            site_id = row.get("id") or row.get("DT_RowId")
            location = row.get("location") or row.get("roadway") or source_agency
            lat_lng = row.get("latLng") or {}
            geography = lat_lng.get("geography") if isinstance(lat_lng, dict) else {}
            lat, lon = _parse_wkt_point(
                geography.get("wellKnownText") if isinstance(geography, dict) else ""
            )
            images = row.get("images") or []
            image = next(
                (
                    candidate
                    for candidate in images
                    if str(candidate.get("imageUrl") or "").strip()
                    and not bool(candidate.get("blocked"))
                ),
                None,
            )
            if not (site_id and image and lat is not None and lon is not None):
                continue
            media_url = _ensure_https_url(
                urljoin(base_url, str(image.get("imageUrl") or "").strip())
            )
            if not media_url:
                continue
            cameras.append(
                {
                    "id": f"{id_prefix}-{site_id}",
                    "source_agency": source_agency,
                    "lat": lat,
                    "lon": lon,
                    "direction_facing": str(location)[:120],
                    "media_url": media_url,
                    "media_type": "image",
                    "refresh_rate_seconds": 60,
                }
            )

        start += len(rows)
        draw += 1
        total = int(data.get("recordsTotal") or 0)
        if total and start >= total:
            break
        if not total and len(rows) < page_size:
            break
    return cameras


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS cameras (
            id TEXT PRIMARY KEY,
            source_agency TEXT,
            lat REAL,
            lon REAL,
            direction_facing TEXT,
            media_url TEXT,
            media_type TEXT,
            refresh_rate_seconds INTEGER,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """
    )
    cursor.execute("PRAGMA table_info(cameras)")
    columns = {str(row[1]) for row in cursor.fetchall()}
    if "media_type" not in columns:
        cursor.execute("ALTER TABLE cameras ADD COLUMN media_type TEXT")
    conn.commit()
    conn.close()


class BaseCCTVIngestor(ABC):
    @abstractmethod
    def fetch_data(self) -> List[Dict[str, Any]]:
        pass

    def ingest(self):
        # Ingestors may run independently (including from worker threads), so
        # make sure a fresh checkout has both the directory and schema ready.
        init_db()
        conn = sqlite3.connect(str(DB_PATH))
        try:
            cameras = self.fetch_data()
            cursor = conn.cursor()
            source_prefixes = {
                str(cam.get("id") or "").split("-", 1)[0]
                for cam in cameras
                if str(cam.get("id") or "").strip()
            }
            if cameras and len(source_prefixes) == 1:
                prefix = next(iter(source_prefixes))
                cursor.execute("DELETE FROM cameras WHERE id LIKE ?", (f"{prefix}-%",))
            for cam in cameras:
                cursor.execute(
                    """
                    INSERT INTO cameras
                    (
                        id,
                        source_agency,
                        lat,
                        lon,
                        direction_facing,
                        media_url,
                        media_type,
                        refresh_rate_seconds
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                    source_agency=excluded.source_agency,
                    lat=excluded.lat,
                    lon=excluded.lon,
                    direction_facing=excluded.direction_facing,
                    media_url=excluded.media_url,
                    media_type=excluded.media_type,
                    refresh_rate_seconds=excluded.refresh_rate_seconds,
                    last_updated=CURRENT_TIMESTAMP
                """,
                    (
                        cam.get("id"),
                        cam.get("source_agency"),
                        cam.get("lat"),
                        cam.get("lon"),
                        cam.get("direction_facing", "Unknown"),
                        _ensure_https_url(cam.get("media_url", "")),
                        cam.get("media_type", _detect_media_type(cam.get("media_url", ""))),
                        cam.get("refresh_rate_seconds", 60),
                    ),
                )
            conn.commit()
            logger.info(
                f"Successfully ingested {len(cameras)} cameras from {self.__class__.__name__}"
            )
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error(f"Failed to ingest cameras in {self.__class__.__name__}: {e}")
        finally:
            conn.close()


class TFLJamCamIngestor(BaseCCTVIngestor):
    def fetch_data(self) -> List[Dict[str, Any]]:
        # Transport for London Open Data API
        url = "https://api.tfl.gov.uk/Place/Type/JamCam"
        response = fetch_with_curl(url, timeout=15)
        response.raise_for_status()

        data = response.json()
        cameras = []
        for item in data:
            # TfL returns URLs without protocols sometimes or with a base path
            vid_url = None
            img_url = None

            for prop in item.get("additionalProperties", []):
                if prop.get("key") == "videoUrl":
                    vid_url = prop.get("value")
                elif prop.get("key") == "imageUrl":
                    img_url = prop.get("value")

            media = vid_url if vid_url else img_url
            if media:
                cameras.append(
                    {
                        "id": f"TFL-{item.get('id')}",
                        "source_agency": "TfL",
                        "lat": item.get("lat"),
                        "lon": item.get("lon"),
                        "direction_facing": item.get("commonName", "Unknown"),
                        "media_url": media,
                        "media_type": "video" if vid_url else "image",
                        "refresh_rate_seconds": 15,
                    }
                )
        return cameras


class LTASingaporeIngestor(BaseCCTVIngestor):
    def fetch_data(self) -> List[Dict[str, Any]]:
        # Singapore Land Transport Authority (LTA) Traffic Images API
        url = "https://api.data.gov.sg/v1/transport/traffic-images"
        response = fetch_with_curl(url, timeout=15)
        response.raise_for_status()

        data = response.json()
        cameras = []
        if "items" in data and len(data["items"]) > 0:
            for item in data["items"][0].get("cameras", []):
                loc = item.get("location", {})
                if "latitude" in loc and "longitude" in loc and "image" in item:
                    cameras.append(
                        {
                            "id": f"SGP-{item.get('camera_id', 'UNK')}",
                            "source_agency": "Singapore LTA",
                            "lat": loc.get("latitude"),
                            "lon": loc.get("longitude"),
                            "direction_facing": f"Camera {item.get('camera_id')}",
                            "media_url": item.get("image"),
                            "media_type": "image",
                            "refresh_rate_seconds": 60,
                        }
                    )
        return cameras


class AustinTXIngestor(BaseCCTVIngestor):
    def fetch_data(self) -> List[Dict[str, Any]]:
        # City of Austin Traffic Cameras Open Data
        url = "https://data.austintexas.gov/resource/b4k4-adkb.json?$limit=2000"
        response = fetch_with_curl(url, timeout=15)
        response.raise_for_status()

        data = response.json()
        cameras = []
        for item in data:
            cam_id = item.get("camera_id")
            if not cam_id:
                continue
            status = str(item.get("camera_status") or "").strip().upper()
            if status and status != "TURNED_ON":
                continue

            loc = item.get("location", {})
            coords = loc.get("coordinates", [])
            screenshot = _normalize_cctv_media_url(str(item.get("screenshot_address") or "").strip())
            if not screenshot:
                screenshot = f"https://cctv.austinmobility.io/image/{cam_id}.jpg"

            # coords is usually [lon, lat]
            if len(coords) == 2:
                cameras.append(
                    {
                        "id": f"ATX-{cam_id}",
                        "source_agency": "Austin TxDOT",
                        "lat": coords[1],
                        "lon": coords[0],
                        "direction_facing": item.get("location_name", "Austin TX Camera"),
                        "media_url": screenshot,
                        "media_type": "image",
                        "refresh_rate_seconds": 60,
                    }
                )
        return cameras


class NYCDOTIngestor(BaseCCTVIngestor):
    def fetch_data(self) -> List[Dict[str, Any]]:
        url = "https://webcams.nyctmc.org/api/cameras"
        response = fetch_with_curl(url, timeout=15)
        response.raise_for_status()

        data = response.json()
        cameras = []
        for item in data:
            cam_id = item.get("id")
            if not cam_id:
                continue

            lat = item.get("latitude")
            lon = item.get("longitude")
            if lat and lon:
                cameras.append(
                    {
                        "id": f"NYC-{cam_id}",
                        "source_agency": "NYC DOT",
                        "lat": lat,
                        "lon": lon,
                        "direction_facing": item.get("name", "NYC Camera"),
                        "media_url": f"https://webcams.nyctmc.org/api/cameras/{cam_id}/image",
                        "media_type": "image",
                        "refresh_rate_seconds": 30,
                    }
                )
        return cameras


class CaltransIngestor(BaseCCTVIngestor):
    """Caltrans highway cameras across all 12 California districts."""

    DISTRICTS = list(range(1, 13))
    BASE_URL = "https://cwwp2.dot.ca.gov/data/d{d}/cctv/cctvStatusD{d:02d}.json"

    def fetch_data(self) -> List[Dict[str, Any]]:
        cameras = []
        for district in self.DISTRICTS:
            try:
                url = self.BASE_URL.format(d=district)
                resp = fetch_with_curl(url, timeout=15)
                if not resp or resp.status_code != 200:
                    continue
                data = resp.json()
                entries = data.get("data", data)
                if not isinstance(entries, list):
                    continue

                for wrapper in entries:
                    entry = wrapper.get("cctv", wrapper) if isinstance(wrapper, dict) else None
                    if not isinstance(entry, dict):
                        continue

                    loc = entry.get("location", {})
                    lat_s = loc.get("latitude")
                    lon_s = loc.get("longitude")
                    if not lat_s or not lon_s:
                        continue
                    try:
                        lat, lon = float(lat_s), float(lon_s)
                    except (ValueError, TypeError):
                        continue
                    if abs(lat) > 90 or abs(lon) > 180:
                        continue

                    if entry.get("inService") == "false":
                        continue

                    img_data = entry.get("imageData", {})
                    streaming = str(img_data.get("streamingVideoURL") or "").strip()
                    streaming = urljoin(url, streaming) if streaming else ""
                    static_image = str(img_data.get("static", {}).get("currentImageURL") or "").strip()
                    static_image = urljoin(url, static_image) if static_image else ""
                    streaming_type = _detect_media_type(streaming)
                    if static_image:
                        media = static_image
                        media_type = "image"
                    elif streaming and streaming_type in {"video", "hls", "mjpeg"}:
                        media = streaming
                        media_type = streaming_type
                    else:
                        media = streaming
                        media_type = streaming_type or "image"
                    if not media:
                        continue

                    idx = entry.get("index", len(cameras))
                    cameras.append(
                        {
                            "id": f"CAL-D{district:02d}-{idx}",
                            "source_agency": f"Caltrans D{district:02d}",
                            "lat": lat,
                            "lon": lon,
                            "direction_facing": (
                                loc.get("locationName")
                                or loc.get("nearbyPlace")
                                or f"CA-{loc.get('route', '?')}"
                            )[:120],
                            "media_url": media,
                            "media_type": media_type,
                            "refresh_rate_seconds": 60,
                        }
                    )
            except Exception as e:
                logger.warning(f"Caltrans D{district:02d} fetch error: {e}")
        return cameras


class WSDOTIngestor(BaseCCTVIngestor):
    """Washington State DOT cameras via ArcGIS REST (1,500+ cameras)."""

    URL = (
        "https://www.wsdot.wa.gov/arcgis/rest/services/Production/"
        "WSDOTTrafficCameras/MapServer/0/query"
    )

    def fetch_data(self) -> List[Dict[str, Any]]:
        resp = fetch_with_curl(
            self.URL + "?where=1%3D1"
            "&outFields=CameraID,CameraTitl,ImageURL,CameraOwne"
            "&outSR=4326&f=json",
            timeout=25,
        )
        if not resp or resp.status_code != 200:
            logger.error(f"WSDOT fetch failed: HTTP {resp.status_code if resp else 'no response'}")
            return []
        data = resp.json()
        cameras = []
        for feat in data.get("features", []):
            attrs = feat.get("attributes", {})
            geom = feat.get("geometry", {})
            cam_id = attrs.get("CameraID")
            lat = geom.get("y")
            lon = geom.get("x")
            img = attrs.get("ImageURL")
            if not (cam_id and lat and lon and img):
                continue
            try:
                lat, lon = float(lat), float(lon)
            except (ValueError, TypeError):
                continue
            # WSDOT's layer also carries ~66 Oregon ODOT cameras around
            # Portland. OregonTripCheckIngestor reads ODOT's own statewide
            # list, which has the same spots, so skip them here.
            host = str(urlparse(str(img)).hostname or "").lower()
            if host == "tripcheck.com" or host.endswith(".tripcheck.com"):
                continue
            cameras.append(
                {
                    "id": f"WSDOT-{cam_id}",
                    "source_agency": (attrs.get("CameraOwne") or "WSDOT")[:60],
                    "lat": lat,
                    "lon": lon,
                    "direction_facing": (attrs.get("CameraTitl") or "WA Camera")[:120],
                    "media_url": img,
                    "media_type": "image",
                    "refresh_rate_seconds": 120,
                }
            )
        return cameras


class GeorgiaDOTIngestor(BaseCCTVIngestor):
    """Georgia cameras via the public 511GA list feed."""

    def fetch_data(self) -> List[Dict[str, Any]]:
        return _fetch_511_datatables_cameras(
            list_url="https://511ga.org/List/GetData/Cameras",
            base_url="https://511ga.org",
            id_prefix="GDOT",
            source_agency="Georgia DOT",
            referer="https://511ga.org/cctv",
        )


class IllinoisDOTIngestor(BaseCCTVIngestor):
    """Illinois DOT cameras via ArcGIS FeatureServer (3,400+ cameras)."""

    URL = (
        "https://services2.arcgis.com/aIrBD8yn1TDTEXoz/arcgis/rest/services/"
        "TrafficCamerasTM_Public/FeatureServer/0/query"
    )

    def fetch_data(self) -> List[Dict[str, Any]]:
        resp = fetch_with_curl(
            self.URL + "?where=1%3D1"
            "&outFields=CameraLocation,CameraDirection,SnapShot"
            "&outSR=4326&f=json",
            timeout=30,
        )
        if not resp or resp.status_code != 200:
            return []
        data = resp.json()
        cameras = []
        for feat in data.get("features", []):
            attrs = feat.get("attributes", {})
            geom = feat.get("geometry", {})
            lat = geom.get("y")
            lon = geom.get("x")
            img = attrs.get("SnapShot") or ""
            if not (lat and lon and img):
                continue
            try:
                lat, lon = float(lat), float(lon)
            except (ValueError, TypeError):
                continue
            cameras.append({
                "id": f"IDOT-{len(cameras)}",
                "source_agency": "Illinois DOT",
                "lat": lat, "lon": lon,
                "direction_facing": (
                    attrs.get("CameraLocation") or attrs.get("CameraDirection") or "IL Camera"
                )[:120],
                "media_url": img,
                "media_type": "image",
                "refresh_rate_seconds": 120,
            })
        return cameras


class MichiganDOTIngestor(BaseCCTVIngestor):
    """Michigan DOT cameras (775+ cameras). Parses HTML-embedded JSON."""

    URL = "https://mdotjboss.state.mi.us/MiDrive/camera/list"

    def fetch_data(self) -> List[Dict[str, Any]]:
        import re
        resp = fetch_with_curl(self.URL, timeout=20)
        if not resp or resp.status_code != 200:
            return []
        data = resp.json()
        cameras = []
        for cam in data:
            county = cam.get("county", "")
            m = re.search(r"lat=([\d.-]+)&lon=([\d.-]+)", county)
            if not m:
                continue
            try:
                lat, lon = float(m.group(1)), float(m.group(2))
            except (ValueError, TypeError):
                continue
            img_m = re.search(r'src="([^"]+)"', cam.get("image", ""))
            if not img_m:
                continue
            id_m = re.search(r"id=(\d+)", county)
            cam_id = id_m.group(1) if id_m else str(len(cameras))
            media_url = urljoin(self.URL, img_m.group(1))
            cameras.append({
                "id": f"MDOT-{cam_id}",
                "source_agency": "Michigan DOT",
                "lat": lat, "lon": lon,
                "direction_facing": (
                    f"{cam.get('route', '')} {cam.get('location', '')}".strip() or "MI Camera"
                )[:120],
                "media_url": media_url,
                "media_type": "image",
                "refresh_rate_seconds": 120,
            })
        return cameras


class WindyWebcamsIngestor(BaseCCTVIngestor):
    """Windy Webcams API v3 — global cameras. Requires WINDY_API_KEY env var."""

    BASE = "https://api.windy.com/webcams/api/v3/webcams"

    def fetch_data(self) -> List[Dict[str, Any]]:
        api_key = os.environ.get("WINDY_API_KEY", "")
        if not api_key:
            return []

        cameras = []
        offset = 0
        limit = 50
        max_cameras = 1000  # Free tier offset cap

        while offset < max_cameras:
            try:
                resp = requests.get(
                    self.BASE,
                    params={"limit": limit, "offset": offset, "include": "location,images"},
                    headers={
                        "X-WINDY-API-KEY": api_key,
                        "Accept": "application/json",
                    },
                    timeout=20,
                )
                if resp.status_code != 200:
                    break
                data = resp.json()
                webcams = data.get("webcams", [])
                if not webcams:
                    break

                for wc in webcams:
                    loc = wc.get("location", {})
                    lat = loc.get("latitude")
                    lon = loc.get("longitude")
                    if lat is None or lon is None:
                        continue
                    try:
                        lat, lon = float(lat), float(lon)
                    except (ValueError, TypeError):
                        continue

                    images = wc.get("images", {})
                    current = images.get("current", {})
                    img_url = current.get("preview") or current.get("thumbnail") or ""

                    city = loc.get("city") or loc.get("country") or "Global"
                    cameras.append(
                        {
                            "id": f"WINDY-{wc.get('webcamId', offset)}",
                            "source_agency": f"Windy: {city}"[:60],
                            "lat": lat,
                            "lon": lon,
                            "direction_facing": (wc.get("title") or "Webcam")[:120],
                            "media_url": img_url,
                            "media_type": "image",
                            "refresh_rate_seconds": 600,
                        }
                    )
                offset += limit
            except Exception as e:
                logger.warning(f"Windy webcams fetch error at offset {offset}: {e}")
                break
        return cameras


class ColoradoDOTIngestor(BaseCCTVIngestor):
    """Colorado DOT cameras via the official COtrip camera service."""

    URL = "https://cotg.carsprogram.org/cameras_v1/api/cameras"

    def fetch_data(self) -> List[Dict[str, Any]]:
        resp = fetch_with_curl(
            self.URL,
            timeout=25,
            headers={"Accept": "application/json"},
        )
        if not resp or resp.status_code != 200:
            logger.warning(f"Colorado DOT camera fetch failed: HTTP {resp.status_code if resp else 'no response'}")
            return []
        data = resp.json()
        cameras = []
        for item in data if isinstance(data, list) else []:
            if item.get("public") is False or item.get("active") is False:
                continue
            loc = item.get("location", {})
            lat = loc.get("latitude")
            lon = loc.get("longitude")
            if lat is None or lon is None:
                continue
            try:
                lat, lon = float(lat), float(lon)
            except (ValueError, TypeError):
                continue

            media_url = ""
            media_type = "image"
            for view in item.get("views") or []:
                preview_url = _normalize_cctv_media_url(str(view.get("videoPreviewUrl") or "").strip())
                if preview_url:
                    media_url = preview_url
                    media_type = "image"
                    break
            if not media_url:
                for view in item.get("views") or []:
                    stream_url = _normalize_cctv_media_url(str(view.get("url") or "").strip())
                    stream_type = _detect_media_type(stream_url)
                    if stream_url and stream_type in {"video", "hls", "mjpeg"}:
                        media_url = stream_url
                        media_type = stream_type
                        break
            if not media_url:
                continue

            owner = item.get("cameraOwner", {})
            cameras.append(
                {
                    "id": f"CODOT-{item.get('id')}",
                    "source_agency": str(owner.get("name") or "Colorado DOT")[:60],
                    "lat": lat,
                    "lon": lon,
                    "direction_facing": str(item.get("name") or loc.get("routeId") or "Colorado Camera")[:120],
                    "media_url": media_url,
                    "media_type": media_type,
                    "refresh_rate_seconds": 30 if media_type in {"video", "hls"} else 60,
                }
            )
        return cameras


class OSMTrafficCameraIngestor(BaseCCTVIngestor):
    """Traffic cameras from OpenStreetMap/Overpass with direct public media URLs."""

    URL = "https://overpass-api.de/api/interpreter"
    QUERY = """
[out:json][timeout:30];
(
  node["camera:type"="traffic_monitoring"]["camera:url"];
  node["camera:type"="traffic_monitoring"]["camera:image"];
  node["camera:type"="traffic_monitoring"]["image"];
  node["camera:type"="traffic_monitoring"]["url"];
  node["surveillance:type"="traffic_monitoring"]["camera:url"];
  node["surveillance:type"="traffic_monitoring"]["camera:image"];
  node["surveillance:type"="traffic_monitoring"]["image"];
  node["surveillance:type"="traffic_monitoring"]["url"];
  node["man_made"="surveillance"]["camera:type"="traffic_monitoring"]["camera:url"];
  node["man_made"="surveillance"]["camera:type"="traffic_monitoring"]["camera:image"];
  node["man_made"="surveillance"]["camera:type"="traffic_monitoring"]["image"];
  node["man_made"="surveillance"]["camera:type"="traffic_monitoring"]["url"];
);
out body;
""".strip()

    def fetch_data(self) -> List[Dict[str, Any]]:
        query = quote(self.QUERY, safe="")
        resp = fetch_with_curl(
            f"{self.URL}?data={query}",
            timeout=35,
            headers={"Accept": "application/json"},
        )
        if not resp or resp.status_code != 200:
            logger.warning(f"OSM camera fetch failed: HTTP {resp.status_code if resp else 'no response'}")
            return []
        data = resp.json()
        cameras = []
        for item in data.get("elements", []) if isinstance(data, dict) else []:
            lat = item.get("lat")
            lon = item.get("lon")
            tags = item.get("tags", {}) if isinstance(item.get("tags"), dict) else {}
            if lat is None or lon is None:
                continue
            try:
                lat, lon = float(lat), float(lon)
            except (ValueError, TypeError):
                continue

            media_url, media_type = _extract_direct_cctv_media_from_tags(tags)
            if not media_url:
                continue

            direction = (
                tags.get("camera:direction")
                or tags.get("direction")
                or tags.get("surveillance:direction")
                or tags.get("name")
                or "OSM Traffic Camera"
            )
            operator = tags.get("operator") or tags.get("network") or tags.get("brand") or "OpenStreetMap"
            cameras.append(
                {
                    "id": f"OSM-{item.get('id')}",
                    "source_agency": str(operator)[:60],
                    "lat": lat,
                    "lon": lon,
                    "direction_facing": str(direction)[:120],
                    "media_url": media_url,
                    "media_type": media_type or "image",
                    "refresh_rate_seconds": 300,
                }
            )
        return cameras


# ---------------------------------------------------------------------------
# ALPR / Surveillance Camera Locations (OSM Overpass)
# ---------------------------------------------------------------------------
# Queries OpenStreetMap for ALPR/LPR tagged surveillance cameras.
# These cameras rarely have public media URLs — this ingestor captures
# their LOCATIONS for situational awareness (density heatmap, blind-spot
# analysis).  No plate-read data is fetched — only publicly-mapped positions.


class OSMALPRCameraIngestor(BaseCCTVIngestor):
    """ALPR / license-plate reader camera locations from OpenStreetMap.

    Searches for nodes tagged with surveillance:type=ALPR or
    man_made=surveillance + camera:type values indicating plate readers.
    Only geolocations are ingested — no live feeds or detection data.
    """

    URL = "https://overpass-api.de/api/interpreter"
    QUERY = """
[out:json][timeout:45];
(
  node["surveillance:type"="ALPR"];
  node["surveillance:type"="alpr"];
  node["surveillance:type"="LPR"];
  node["surveillance:type"="lpr"];
  node["man_made"="surveillance"]["camera:type"="ALPR"];
  node["man_made"="surveillance"]["camera:type"="alpr"];
  node["man_made"="surveillance"]["camera:type"="LPR"];
  node["man_made"="surveillance"]["camera:type"="lpr"];
  node["man_made"="surveillance"]["description"~"[Ll]icense [Pp]late"];
  node["man_made"="surveillance"]["description"~"ALPR"];
  node["man_made"="surveillance"]["description"~"Flock"];
);
out body;
""".strip()

    def fetch_data(self) -> List[Dict[str, Any]]:
        query = quote(self.QUERY, safe="")
        resp = fetch_with_curl(
            f"{self.URL}?data={query}",
            timeout=50,
            headers={"Accept": "application/json"},
        )
        if not resp or resp.status_code != 200:
            logger.warning(
                "OSM ALPR camera fetch failed: HTTP %s",
                resp.status_code if resp else "no response",
            )
            return []
        data = resp.json()
        cameras = []
        for item in data.get("elements", []) if isinstance(data, dict) else []:
            lat = item.get("lat")
            lon = item.get("lon")
            if lat is None or lon is None:
                continue
            try:
                lat, lon = float(lat), float(lon)
            except (ValueError, TypeError):
                continue

            tags = item.get("tags", {}) if isinstance(item.get("tags"), dict) else {}

            # Extract what we can from tags
            operator = (
                tags.get("operator")
                or tags.get("brand")
                or tags.get("network")
                or "Unknown"
            )
            description = (
                tags.get("description")
                or tags.get("name")
                or tags.get("surveillance:type", "ALPR")
            )
            direction = (
                tags.get("camera:direction")
                or tags.get("direction")
                or tags.get("surveillance:direction")
                or "Unknown"
            )

            # ALPR cameras typically have no public media URL — use a
            # placeholder so the pin renders but no proxy attempt is made.
            cameras.append(
                {
                    "id": f"ALPR-{item.get('id')}",
                    "source_agency": str(operator)[:60],
                    "lat": lat,
                    "lon": lon,
                    "direction_facing": f"ALPR: {str(description)[:100]} ({str(direction)[:30]})",
                    "media_url": "",
                    "media_type": "none",
                    "refresh_rate_seconds": 0,
                }
            )
        logger.info("OSM ALPR ingestor found %d cameras", len(cameras))
        return cameras


# ---------------------------------------------------------------------------
# DGT Spain — National Road Cameras
# ---------------------------------------------------------------------------
# Image URL pattern confirmed working: etraffic.dgt.es/camarasEtraffic/{id}.jpg
# (DGT migrated 2026: old infocar.dgt.es/etraffic/data/camaras path now 302->etrafficWEB)
# Source: DGT (Dirección General de Tráfico) — public open data (Ley 37/2007).
# Author credit: Alborz Nazari (github.com/AlborzNazari) — PR #91

class DGTNationalIngestor(BaseCCTVIngestor):
    """DGT national road cameras — 20 seed cameras across Spanish motorways."""

    KNOWN_CAMERAS = [
        (1398, 36.7213, -4.4214, "MA-19 Málaga"),
        (1001, 40.4168, -3.7038, "A-6 Madrid"),
        (1002, 40.4500, -3.6800, "A-2 Madrid"),
        (1003, 40.3800, -3.7200, "A-4 Madrid"),
        (1004, 40.4200, -3.8100, "A-5 Madrid"),
        (1005, 40.4600, -3.6600, "M-30 Madrid"),
        (1010, 41.3888,  2.1590, "AP-7 Barcelona"),
        (1011, 41.4100,  2.1800, "A-2 Barcelona"),
        (1020, 37.3891, -5.9845, "A-4 Sevilla"),
        (1021, 37.4000, -6.0000, "A-49 Sevilla"),
        (1030, 39.4699, -0.3763, "V-30 Valencia"),
        (1031, 39.4800, -0.3900, "A-3 Valencia"),
        (1040, 43.2630, -2.9350, "A-8 Bilbao"),
        (1050, 42.8782, -8.5448, "AG-55 Santiago"),
        (1060, 41.6488, -0.8891, "A-2 Zaragoza"),
        (1070, 37.9922, -1.1307, "A-30 Murcia"),
        (1080, 36.5271, -6.2886, "A-4 Cádiz"),
        (1090, 43.3623, -8.4115, "A-6 A Coruña"),
        (1100, 38.9942, -1.8585, "A-31 Albacete"),
        (1110, 39.8628, -4.0273, "A-4 Toledo"),
    ]

    CATALOG_URL = "https://www.dgt.es/.content/.assets/json/camaras.json"

    def fetch_data(self) -> List[Dict[str, Any]]:
        cameras = self._fetch_catalog()
        if cameras:
            logger.info(f"DGTNationalIngestor: loaded {len(cameras)} cameras from the DGT catalog")
            return cameras
        return self._fetch_seed_cameras()

    def _fetch_catalog(self) -> List[Dict[str, Any]]:
        """Full national list (~1,900 cameras) from the JSON behind dgt.es's camera map."""
        try:
            resp = fetch_with_curl(self.CATALOG_URL, timeout=30, headers={"Accept": "application/json"})
            if not resp or resp.status_code != 200:
                logger.warning("DGT camera catalog unavailable (HTTP %s); using seed list",
                               resp.status_code if resp else "no response")
                return []
            data = resp.json()
        except Exception as exc:
            logger.warning(f"DGT camera catalog fetch failed ({exc}); using seed list")
            return []
        rows = data.get("camaras") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            return []
        cameras: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            cam_id = str(row.get("id") or "").strip()
            media_url = _ensure_https_url(str(row.get("imagen") or "").strip())
            try:
                lat = float(row.get("latitud"))
                lon = float(row.get("longitud"))
            except (TypeError, ValueError):
                continue
            if not cam_id or not media_url:
                continue
            road = str(row.get("carretera") or "").strip()
            pk = str(row.get("pk") or "").strip()
            label = f"{road} km {pk}" if road and pk else (road or "DGT camera")
            cameras.append({
                "id": f"DGT-{cam_id}",
                "source_agency": "DGT Spain",
                "lat": lat,
                "lon": lon,
                "direction_facing": label[:120],
                "media_url": media_url,
                "media_type": "image",
                "refresh_rate_seconds": 300,
            })
        return cameras

    def _fetch_seed_cameras(self) -> List[Dict[str, Any]]:
        cameras = []
        probe_headers = {
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Referer": "https://etraffic.dgt.es/",
        }
        for cam_id, lat, lon, description in self.KNOWN_CAMERAS:
            media_url = f"https://etraffic.dgt.es/camarasEtraffic/{cam_id}.jpg"
            if not _media_url_reachable(media_url, timeout=6, headers=probe_headers):
                continue
            cameras.append({
                "id": f"DGT-{cam_id}",
                "source_agency": "DGT Spain",
                "lat": lat,
                "lon": lon,
                "direction_facing": description,
                "media_url": media_url,
                "media_type": "image",
                "refresh_rate_seconds": 300,
            })
        logger.info(f"DGTNationalIngestor: loaded {len(cameras)} cameras")
        return cameras


# ---------------------------------------------------------------------------
# Madrid City Hall — KML open data (~357 cameras)
# ---------------------------------------------------------------------------
# Published on datos.madrid.es — free reuse with attribution,
# Licence: Madrid Open Data (EU PSI Directive 2019/1024).
# Author credit: Alborz Nazari (github.com/AlborzNazari) — PR #91

_KML_NS = {"kml": "http://www.opengis.net/kml/2.2"}


def _find_kml_element(element, tag):
    """Find first descendant matching tag, ignoring XML namespace prefix."""
    import defusedxml.ElementTree as ET
    el = element.find(f".//{tag}")
    if el is not None:
        return el
    for child in element.iter():
        if child.tag.endswith(f"}}{tag}") or child.tag == tag:
            return child
    return None


def _extract_img_src(html_fragment: str):
    """Extract src URL from an <img> tag or bare .jpg URL in an HTML fragment."""
    import re
    match = re.search(r'src=["\']([^"\']+)["\']', html_fragment, re.IGNORECASE)
    if match:
        return match.group(1)
    match = re.search(r'https?://\S+\.jpg', html_fragment, re.IGNORECASE)
    if match:
        return match.group(0)
    return None


class AsfinagIngestor(BaseCCTVIngestor):
    """Austria ASFINAG motorway webcams (Osiris port)."""

    API_URL = "https://odo.asfinag.at/odo/rest/sec/resource/001/json/webcams?language=atDE"
    HEADERS = {
        "User-Agent": "Shadowbroker-CCTV/1.0",
        "Accept": "application/json",
        "Referer": "https://www.asfinag.at/",
        "Authorization": "Basic bWFwX3dpZGdldDp0ZWdkaXc=",
    }

    def fetch_data(self) -> List[Dict[str, Any]]:
        try:
            response = fetch_with_curl(self.API_URL, timeout=15, headers=self.HEADERS)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            logger.error("AsfinagIngestor: fetch failed: %s", exc)
            return []
        if not isinstance(payload, list):
            return []
        cameras: List[Dict[str, Any]] = []
        for cam in payload:
            cam_id = cam.get("wcs_id")
            lat = cam.get("wgs84_lat")
            lon = cam.get("wgs84_lon")
            image_url = cam.get("url_campic")
            if not cam_id or lat is None or lon is None or not image_url:
                continue
            if str(cam_id).startswith("Utinform"):
                continue
            label = cam.get("position_txt") or cam.get("direction_txt") or "ASFINAG Webcam"
            secure_url = _ensure_https_url(image_url)
            if not secure_url:
                continue
            cameras.append(
                {
                    "id": f"ASFINAG-{cam_id}",
                    "source_agency": "ASFINAG Austria",
                    "lat": float(lat),
                    "lon": float(lon),
                    "direction_facing": label,
                    "media_url": secure_url,
                    "media_type": "image",
                    "refresh_rate_seconds": 300,
                }
            )
        logger.info("AsfinagIngestor: parsed %s cameras", len(cameras))
        return cameras


class MadridCityIngestor(BaseCCTVIngestor):
    """Madrid City Hall traffic cameras from datos.madrid.es KML feed."""

    KML_URL = "https://datos.madrid.es/egob/catalogo/202088-0-trafico-camaras.kml"

    def _fetch_kml(self):
        response = fetch_with_curl(self.KML_URL, timeout=20)
        response.raise_for_status()
        return response

    def fetch_data(self) -> List[Dict[str, Any]]:
        import defusedxml.ElementTree as ET

        try:
            response = self._fetch_kml()
        except Exception as e:
            logger.error(f"MadridCityIngestor: failed to fetch KML: {e}")
            return []

        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as e:
            logger.error(f"MadridCityIngestor: failed to parse KML: {e}")
            return []

        cameras = []
        placemarks = root.findall(".//kml:Placemark", _KML_NS)
        if not placemarks:
            placemarks = [el for el in root.iter() if el.tag.endswith("Placemark")]

        for i, placemark in enumerate(placemarks):
            try:
                name_el = _find_kml_element(placemark, "name")
                name = name_el.text.strip() if name_el is not None and name_el.text else f"Madrid Camera {i}"

                coords_el = _find_kml_element(placemark, "coordinates")
                if coords_el is None or not coords_el.text:
                    continue

                parts = coords_el.text.strip().split(",")
                if len(parts) < 2:
                    continue
                lon = float(parts[0])
                lat = float(parts[1])

                desc_el = _find_kml_element(placemark, "description")
                image_url = None
                if desc_el is not None and desc_el.text:
                    image_url = _extract_img_src(desc_el.text)

                if not image_url:
                    continue
                image_url = _ensure_https_url(image_url)
                if not image_url:
                    continue

                cameras.append({
                    "id": f"MAD-{i:04d}",
                    "source_agency": "Madrid City Hall",
                    "lat": lat,
                    "lon": lon,
                    "direction_facing": name,
                    "media_url": image_url,
                    "media_type": "image",
                    "refresh_rate_seconds": 600,
                })
            except (ValueError, TypeError, IndexError) as e:
                logger.debug(f"MadridCityIngestor: skipping malformed placemark: {e}")
                continue

        logger.info(f"MadridCityIngestor: parsed {len(cameras)} cameras")
        return cameras


class IBI511Ingestor(BaseCCTVIngestor):
    """Any 511 site on the IBI/TravelIQ web stack (POST /List/GetData/Cameras).

    The same DataTables list feed Georgia and Florida use is served by dozens
    of state and provincial 511 sites; each only needs its base URL.
    """

    def __init__(self, base_url: str, id_prefix: str, source_agency: str, referer_path: str = "/cctv",
                 query_in_url: bool = False):
        self.base_url = base_url.rstrip("/")
        self.id_prefix = id_prefix
        self.source_agency = source_agency
        self.referer_path = referer_path
        self.query_in_url = query_in_url

    def fetch_data(self) -> List[Dict[str, Any]]:
        return _fetch_511_datatables_cameras(
            list_url=f"{self.base_url}/List/GetData/Cameras",
            base_url=self.base_url,
            id_prefix=self.id_prefix,
            source_agency=self.source_agency,
            referer=f"{self.base_url}{self.referer_path}",
            **({"query_in_url": True, "page_size": 100} if self.query_in_url else {}),
        )


class Ontario511Ingestor(IBI511Ingestor):
    """Ontario highway cameras via the 511on.ca list feed (~936 sites).

    The old TravelIQ GET /api/v2/get/cameras endpoint now answers HTTP 400.
    """

    def __init__(self):
        super().__init__("https://511on.ca", "ON511", "511 Ontario")


class Alberta511Ingestor(IBI511Ingestor):
    """Alberta highway cameras via the 511 Alberta list feed (~348 sites).

    The old TravelIQ GET /api/v2/get/cameras endpoint now answers HTTP 400.
    """

    def __init__(self):
        super().__init__("https://511.alberta.ca", "AB511", "511 Alberta")


# (scheduler key, base URL, id prefix, source label). Each base was checked live
# on 2026-11-15 and returned cameras with loadable snapshot images. Endpoints
# found via the MIT-licensed OSIRIS project (github.com/simplifaisoul/osiris);
# Pennsylvania and Wisconsin were found by probing the same stack.
IBI511_SITES: List[tuple[str, str, str, str]] = [
    ("cctv_ak511", "https://511.alaska.gov", "AK511", "Alaska 511"),
    ("cctv_az511", "https://az511.gov", "AZ511", "Arizona 511"),
    ("cctv_id511", "https://511.idaho.gov", "ID511", "Idaho 511"),
    ("cctv_la511", "https://511la.org", "LA511", "Louisiana 511"),
    ("cctv_nv511", "https://www.nvroads.com", "NV511", "Nevada NVRoads"),
    ("cctv_ut511", "https://prod-ut.ibi511.com", "UT511", "Utah UDOT"),
    ("cctv_pa511", "https://511pa.com", "PA511", "Pennsylvania 511"),
    ("cctv_wi511", "https://511wi.gov", "WI511", "Wisconsin 511"),
    ("cctv_mb511", "https://www.manitoba511.ca", "MB511", "Manitoba 511"),
    ("cctv_nb511", "https://511.gnb.ca", "NB511", "New Brunswick 511"),
    ("cctv_ns511", "https://511.novascotia.ca", "NS511", "Nova Scotia 511"),
    ("cctv_nl511", "https://511nl.ca", "NL511", "Newfoundland and Labrador 511"),
    ("cctv_yt511", "https://511yukon.ca", "YT511", "Yukon 511"),
    ("cctv_neng511", "https://newengland511.org", "NENG511", "New England 511 (VT, NH, ME)"),
    ("cctv_sk511", "https://hotline.gov.sk.ca", "SK511", "Saskatchewan Highway Hotline"),
    ("cctv_pe511", "https://511.gov.pe.ca", "PE511", "PEI 511"),
]


class Florida511Ingestor(BaseCCTVIngestor):
    """Florida cameras via FL511 DataTables feed (~4,800 sites)."""

    def fetch_data(self) -> List[Dict[str, Any]]:
        return _fetch_511_datatables_cameras(
            list_url="https://fl511.com/List/GetData/Cameras",
            base_url="https://fl511.com",
            id_prefix="FL511",
            source_agency="Florida 511",
            referer="https://fl511.com/",
        )


class AustraliaLiveTrafficIngestor(BaseCCTVIngestor):
    """NSW / Australia live traffic cameras via Transport for NSW JSON feed."""

    URL = "https://www.livetraffic.com/datajson/all-feeds-web.json"

    def fetch_data(self) -> List[Dict[str, Any]]:
        resp = fetch_with_curl(self.URL, timeout=35, headers={"Accept": "application/json"})
        if not resp or resp.status_code != 200:
            logger.error(
                "Australia Live Traffic CCTV fetch failed: HTTP %s",
                resp.status_code if resp else "no response",
            )
            return []

        data = resp.json()
        if not isinstance(data, list):
            return []

        cameras: List[Dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict) or item.get("eventType") != "liveCams":
                continue
            geometry = item.get("geometry") if isinstance(item.get("geometry"), dict) else {}
            coords = geometry.get("coordinates") if isinstance(geometry.get("coordinates"), list) else []
            if len(coords) < 2:
                continue
            try:
                lon = float(coords[0])
                lat = float(coords[1])
            except (TypeError, ValueError):
                continue

            props = item.get("properties") if isinstance(item.get("properties"), dict) else {}
            media_url = _ensure_https_url(str(props.get("href") or "").strip())
            if not media_url:
                continue

            cam_id = str(item.get("path") or props.get("id") or len(cameras)).strip("/")
            label = str(props.get("title") or props.get("headline") or "Australia Camera")[:120]
            cameras.append(
                {
                    "id": f"AUS-{cam_id}",
                    "source_agency": "NSW Live Traffic",
                    "lat": lat,
                    "lon": lon,
                    "direction_facing": label,
                    "media_url": media_url,
                    "media_type": "image",
                    "refresh_rate_seconds": 120,
                }
            )
        logger.info("AustraliaLiveTrafficIngestor: parsed %s cameras", len(cameras))
        return cameras


class NetherlandsRWSIngestor(BaseCCTVIngestor):
    """Netherlands Rijkswaterstaat cameras.

    Primary: api.rwsverkeersinfo.nl/api/cameras/ (the RWS traffic-info site's
    feed). Its frames live on stream.inmoves.nl, which answers 401 without a
    Referer, so the media proxy sends one. Fallback: the legacy
    opendata.ndw.nu/cameras.json feed, which NDW has retired.
    """

    RWS_URL = "https://api.rwsverkeersinfo.nl/api/cameras/"
    URL = "https://opendata.ndw.nu/cameras.json"

    def fetch_data(self) -> List[Dict[str, Any]]:
        cameras = self._fetch_rws()
        if cameras:
            logger.info("NetherlandsRWSIngestor: parsed %s cameras from rwsverkeersinfo", len(cameras))
            return cameras
        return self._fetch_legacy_ndw()

    def _fetch_rws(self) -> List[Dict[str, Any]]:
        try:
            resp = fetch_with_curl(self.RWS_URL, timeout=25, headers={"Accept": "application/json"})
            if not resp or resp.status_code != 200:
                return []
            data = resp.json()
        except Exception as exc:
            logger.warning(f"Netherlands rwsverkeersinfo camera fetch failed: {exc}")
            return []
        if not isinstance(data, list):
            return []
        cameras: List[Dict[str, Any]] = []
        for cam in data:
            if not isinstance(cam, dict):
                continue
            media_url = _ensure_https_url(str(cam.get("static_url") or "").strip())
            try:
                lat_f = float(cam.get("latitude"))
                lon_f = float(cam.get("longitude"))
            except (TypeError, ValueError):
                continue
            if cam.get("id") is None or not media_url:
                continue
            road = str(cam.get("road") or "").strip()
            near = str(cam.get("near") or "").strip()
            label = " near ".join(p for p in (road, near) if p) or "Netherlands camera"
            cameras.append({
                "id": f"NLRWS-{cam.get('id')}",
                "source_agency": "Rijkswaterstaat",
                "lat": lat_f,
                "lon": lon_f,
                "direction_facing": label[:120],
                "media_url": media_url,
                "media_type": "image",
                "refresh_rate_seconds": 120,
            })
        return cameras

    def _fetch_legacy_ndw(self) -> List[Dict[str, Any]]:
        resp = fetch_with_curl(self.URL, timeout=25, headers={"Accept": "application/json"})
        if not resp or resp.status_code != 200:
            logger.warning(
                "Netherlands RWS cameras.json unavailable (HTTP %s) — "
                "NDW retired this open-data endpoint; no cameras ingested",
                resp.status_code if resp else "no response",
            )
            return []

        data = resp.json()
        if not isinstance(data, list):
            return []

        cameras: List[Dict[str, Any]] = []
        for i, cam in enumerate(data):
            if not isinstance(cam, dict):
                continue
            lat = cam.get("lat") if cam.get("lat") is not None else cam.get("latitude")
            lon = cam.get("lng") if cam.get("lng") is not None else cam.get("longitude")
            media_url = _ensure_https_url(
                str(cam.get("imageUrl") or cam.get("feed_url") or cam.get("url") or "").strip()
            )
            if lat is None or lon is None or not media_url:
                continue
            try:
                lat_f, lon_f = float(lat), float(lon)
            except (TypeError, ValueError):
                continue
            cameras.append(
                {
                    "id": f"NLRWS-{cam.get('id') or i}",
                    "source_agency": "Rijkswaterstaat",
                    "lat": lat_f,
                    "lon": lon_f,
                    "direction_facing": str(cam.get("name") or "Netherlands Camera")[:120],
                    "media_url": media_url,
                    "media_type": "image",
                    "refresh_rate_seconds": 120,
                }
            )
        logger.info("NetherlandsRWSIngestor: parsed %s cameras", len(cameras))
        return cameras


# ---------------------------------------------------------------------------
# State DOT and international feeds, batch two. Endpoints found via the
# MIT-licensed OSIRIS project (github.com/simplifaisoul/osiris); each was
# checked live on 2026-11-15 and its sample images or HLS segments loaded.
# ---------------------------------------------------------------------------


def _lat_lon_in(lat, lon, bounds) -> tuple[float, float] | None:
    """(lat, lon) as floats if both parse and fall inside (south, north, west, east)."""
    try:
        lat_f, lon_f = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    south, north, west, east = bounds
    if not (south <= lat_f <= north and west <= lon_f <= east):
        return None  # also rejects NaN
    return lat_f, lon_f


def _get_feed_json(url: str, *, timeout: int = 20, headers: dict | None = None,
                   method: str = "GET", json_data=None):
    resp = fetch_with_curl(url, method=method, json_data=json_data, timeout=timeout, headers=headers or {})
    if resp is None or getattr(resp, "status_code", 0) != 200:
        logger.warning("CCTV feed %s returned HTTP %s", url, getattr(resp, "status_code", None))
        return None
    try:
        return resp.json()
    except Exception:
        logger.warning("CCTV feed %s did not return JSON", url)
        return None


def _get_feed_xml(url: str, *, timeout: int = 20):
    import defusedxml.ElementTree as ET

    resp = fetch_with_curl(url, timeout=timeout, headers={"Accept": "application/xml,text/xml"})
    if resp is None or getattr(resp, "status_code", 0) != 200:
        logger.warning("CCTV feed %s returned HTTP %s", url, getattr(resp, "status_code", None))
        return None
    try:
        return ET.fromstring(resp.content)
    except ET.ParseError as e:
        logger.warning("CCTV feed %s is not valid XML: %s", url, e)
        return None


def _https_url_on(raw, domain: str, path_pattern: str) -> str:
    """The URL if it is https on `domain` (or a subdomain) and its path matches, else ''."""
    parsed = urlparse(str(raw or "").strip())
    host = str(parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (host == domain or host.endswith(f".{domain}")):
        return ""
    if not re.search(path_pattern, parsed.path or "", re.IGNORECASE):
        return ""
    # Some feeds spell out :443; the URL is the same without it.
    return urlunparse(parsed._replace(netloc=host))


class MarylandCHARTIngestor(BaseCCTVIngestor):
    """Maryland SHA CHART cameras (~550 live HLS streams).

    CHART's official export lists each camera with the streaming server it
    lives on; the player plays https://{cctvIp}/rtplive/{id}/playlist.m3u8.
    """

    FEED_URL = "https://chartexp1.sha.maryland.gov/CHARTExportClientService/getCameraMapDataJSON.do"
    BOUNDS = (37.85, 39.8, -79.55, -74.95)

    def fetch_data(self) -> List[Dict[str, Any]]:
        data = _get_feed_json(self.FEED_URL)
        rows = data.get("data") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            return []
        cameras: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            cam_id = str(row.get("id") or "").strip().lower()
            host = str(row.get("cctvIp") or "").strip().lower()
            if not re.fullmatch(r"[0-9a-f]{16,64}", cam_id) or cam_id in seen:
                continue
            if not re.fullmatch(r"[a-z0-9-]+\.sha\.maryland\.gov", host):
                continue
            coords = _lat_lon_in(row.get("lat"), row.get("lon"), self.BOUNDS)
            if not coords:
                continue
            seen.add(cam_id)
            name = str(row.get("name") or "").strip()
            if not name or name.isdigit():
                name = str(row.get("description") or "").strip() or name or "Maryland CHART camera"
            cameras.append({
                "id": f"MDCHART-{cam_id}",
                "source_agency": "Maryland CHART",
                "lat": coords[0],
                "lon": coords[1],
                "direction_facing": name[:120],
                "media_url": f"https://{host}/rtplive/{cam_id}/playlist.m3u8",
                "media_type": "hls",
                "refresh_rate_seconds": 30,
            })
        logger.info("MarylandCHARTIngestor: parsed %s cameras", len(cameras))
        return cameras


class IterisCamerasIngestor(BaseCCTVIngestor):
    """511 maps built by Iteris (Virginia, South Carolina): one GeoJSON camera layer.

    Each feature has a snapshot and an HLS stream. The snapshot is used: it
    refreshes about once a minute, while some VDOT stream servers timed out
    in testing.
    """

    def __init__(self, feed_url: str, id_prefix: str, source_agency: str, media_domain: str, bounds):
        self.feed_url = feed_url
        self.id_prefix = id_prefix
        self.source_agency = source_agency
        self.media_domain = media_domain
        self.bounds = bounds

    def fetch_data(self) -> List[Dict[str, Any]]:
        data = _get_feed_json(self.feed_url, timeout=30)
        features = data.get("features") if isinstance(data, dict) else None
        if not isinstance(features, list):
            return []
        cameras: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for feature in features:
            props = feature.get("properties") if isinstance(feature, dict) else None
            if not isinstance(props, dict):
                continue
            # The agency's own flags: switched off or marked as a problem stream.
            if props.get("active") is False or props.get("problem_stream") is True:
                continue
            cam_id = str(props.get("id") or "").strip()
            if not re.fullmatch(r"[\w-]+", cam_id) or cam_id in seen:
                continue
            geometry = feature.get("geometry") or {}
            coords_raw = geometry.get("coordinates") if geometry.get("type") == "Point" else None
            if not isinstance(coords_raw, list) or len(coords_raw) < 2:
                continue
            coords = _lat_lon_in(coords_raw[1], coords_raw[0], self.bounds)
            snapshot = _https_url_on(props.get("image_url"), self.media_domain, r"\.(png|jpe?g)$")
            if not coords or not snapshot:
                continue
            seen.add(cam_id)
            label = str(props.get("description") or props.get("route") or "").strip() or f"{self.source_agency} camera"
            jurisdiction = str(props.get("jurisdiction") or "").strip()
            if jurisdiction:
                label = f"{label} ({jurisdiction})"
            cameras.append({
                "id": f"{self.id_prefix}-{cam_id}",
                "source_agency": self.source_agency,
                "lat": coords[0],
                "lon": coords[1],
                "direction_facing": label[:120],
                "media_url": snapshot,
                "media_type": "image",
                "refresh_rate_seconds": 60,
            })
        logger.info("IterisCamerasIngestor[%s]: parsed %s cameras", self.id_prefix, len(cameras))
        return cameras


class DelDOTIngestor(BaseCCTVIngestor):
    """Delaware DelDOT TMC cameras (~360 live HLS streams on video.deldot.gov)."""

    FEED_URL = "https://tmc.deldot.gov/json/videocamera.json"
    BOUNDS = (38.4, 39.9, -75.85, -74.95)

    def fetch_data(self) -> List[Dict[str, Any]]:
        data = _get_feed_json(self.FEED_URL)
        rows = data.get("videoCameras") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            return []
        cameras: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, dict) or row.get("enabled") is False or row.get("status") != "Active":
                continue
            cam_id = str(row.get("id") or "").strip()
            if not re.fullmatch(r"[\w-]+", cam_id) or cam_id in seen:
                continue
            coords = _lat_lon_in(row.get("lat"), row.get("lon"), self.BOUNDS)
            stream = _https_url_on((row.get("urls") or {}).get("m3u8s"), "video.deldot.gov", r"\.m3u8$")
            if not coords or not stream:
                continue
            seen.add(cam_id)
            title = str(row.get("title") or "").strip() or f"DelDOT camera {cam_id}"
            county = str(row.get("county") or "").strip()
            cameras.append({
                "id": f"DELDOT-{cam_id}",
                "source_agency": "DelDOT",
                "lat": coords[0],
                "lon": coords[1],
                "direction_facing": (f"{title} ({county} County)" if county else title)[:120],
                "media_url": stream,
                "media_type": "hls",
                "refresh_rate_seconds": 30,
            })
        logger.info("DelDOTIngestor: parsed %s cameras", len(cameras))
        return cameras


TXDOT_DISTRICTS: Dict[str, str] = {
    "ABL": "Abilene", "AMA": "Amarillo", "ATL": "Atlanta", "AUS": "Austin",
    "BMT": "Beaumont", "BWD": "Brownwood", "BRY": "Bryan", "CHS": "Childress",
    "CRP": "Corpus Christi", "DAL": "Dallas", "ELP": "El Paso", "FTW": "Fort Worth",
    "HOU": "Houston", "LRD": "Laredo", "LBB": "Lubbock", "LFK": "Lufkin",
    "ODA": "Odessa", "PAR": "Paris", "PHR": "Pharr", "SJT": "San Angelo",
    "SAT": "San Antonio", "TYL": "Tyler", "WAC": "Waco", "WFS": "Wichita Falls", "YKM": "Yoakum",
}
TXDOT_ITS_BASE = "https://its.txdot.gov/its/DistrictIts/"
TXDOT_SNAPSHOT_PATH = "/its/DistrictIts/GetCctvSnapshotByIcdId"


def txdot_snapshot_url(district: str, icd_id: str) -> str:
    """TxDOT's snapshot endpoint answers JSON with a base64 JPEG; the media proxy decodes it."""
    return f"{TXDOT_ITS_BASE}GetCctvSnapshotByIcdId?districtCode={quote(district, safe='')}&icdId={quote(icd_id, safe='')}"


class TxDOTIngestor(BaseCCTVIngestor):
    """Texas DOT cameras across all 25 districts (~2,500 with snapshots).

    Same public inventory its.txdot.gov's district camera pages read.
    """

    BOUNDS = (25.8, 36.6, -106.7, -93.4)

    def fetch_data(self) -> List[Dict[str, Any]]:
        cameras: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for district, district_name in TXDOT_DISTRICTS.items():
            data = _get_feed_json(f"{TXDOT_ITS_BASE}GetCctvStatusListByDistrict?districtCode={district}", timeout=15)
            groups = data.get("roadwayCctvStatuses") if isinstance(data, dict) else None
            if not isinstance(groups, dict):
                continue
            for rows in groups.values():
                for row in rows if isinstance(rows, list) else []:
                    if not isinstance(row, dict) or row.get("hasSnapshot") is not True:
                        continue
                    if row.get("statusDescription") in ("Device Error", "Device Offline"):
                        continue
                    icd_id = str(row.get("icd_Id") or "").strip()
                    if not icd_id or len(icd_id) > 256 or re.search(r"[\x00-\x1f]", icd_id):
                        continue
                    cam_key = f"TXDOT-{district}-{re.sub(r'[^A-Za-z0-9]+', '_', icd_id).strip('_')}"
                    coords = _lat_lon_in(row.get("latitude"), row.get("longitude"), self.BOUNDS)
                    if not coords or cam_key in seen:
                        continue
                    seen.add(cam_key)
                    name = str(row.get("name") or "").strip() or icd_id
                    cameras.append({
                        "id": cam_key,
                        "source_agency": "TxDOT",
                        "lat": coords[0],
                        "lon": coords[1],
                        "direction_facing": f"{name} ({district_name})"[:120],
                        "media_url": txdot_snapshot_url(district, icd_id),
                        "media_type": "image",
                        "refresh_rate_seconds": 60,
                    })
        logger.info("TxDOTIngestor: parsed %s cameras", len(cameras))
        return cameras


_CARS511_QUERY = """query MapFeatures($input: MapFeaturesArgs!) {
  mapFeaturesQuery(input: $input) {
    mapFeatures {
      title
      uri
      features { geometry }
      __typename
      ... on Camera { active views(limit: 1) { category ... on CameraView { url } } }
    }
    error { message }
  }
}"""


class CARS511Ingestor(BaseCCTVIngestor):
    """511 sites on the CARS program platform (Indiana, Iowa, Nebraska, Kansas).

    One GraphQL map query covers the whole state; zoom 16 makes the server
    return cameras rather than clusters. Each camera's still image is used.
    """

    def __init__(self, base_url: str, id_prefix: str, source_agency: str, bounds):
        self.base_url = base_url.rstrip("/")
        self.id_prefix = id_prefix
        self.source_agency = source_agency
        self.bounds = bounds

    def fetch_data(self) -> List[Dict[str, Any]]:
        south, north, west, east = self.bounds
        payload = {
            "query": _CARS511_QUERY,
            "variables": {"input": {
                "north": north, "south": south, "east": east, "west": west,
                "zoom": 16, "layerSlugs": ["normalCameras"], "nonClusterableUris": None,
            }},
        }
        data = _get_feed_json(
            f"{self.base_url}/api/graphql", method="POST", json_data=payload, timeout=40,
            headers={"Accept": "application/json", "Referer": f"{self.base_url}/"},
        )
        features = (((data or {}).get("data") or {}).get("mapFeaturesQuery") or {}).get("mapFeatures")
        if not isinstance(features, list):
            return []
        cameras: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for feat in features:
            if not isinstance(feat, dict) or feat.get("__typename") != "Camera" or feat.get("active") is False:
                continue
            match = re.search(r"camera/(\d+)", str(feat.get("uri") or ""))
            if not match or match.group(1) in seen:
                continue
            views = feat.get("views") or [{}]
            # Cameras that are down carry a relative "camera closed" icon instead.
            still = str((views[0] or {}).get("url") or "").strip().split("?", 1)[0]
            if not still.startswith("https://"):
                continue
            geometry = ((feat.get("features") or [{}])[0] or {}).get("geometry") or {}
            coords_raw = geometry.get("coordinates")
            if not isinstance(coords_raw, list) or len(coords_raw) < 2:
                continue
            coords = _lat_lon_in(coords_raw[1], coords_raw[0], self.bounds)
            if not coords:
                continue
            seen.add(match.group(1))
            cameras.append({
                "id": f"{self.id_prefix}-{match.group(1)}",
                "source_agency": self.source_agency,
                "lat": coords[0],
                "lon": coords[1],
                "direction_facing": (str(feat.get("title") or "").strip() or f"{self.source_agency} camera")[:120],
                "media_url": still,
                "media_type": "image",
                "refresh_rate_seconds": 60,
            })
        logger.info("CARS511Ingestor[%s]: parsed %s cameras", self.id_prefix, len(cameras))
        return cameras


# (scheduler key, base URL, id prefix, source label, (south, north, west, east)).
# Massachusetts (mass511.com) runs the same platform but most of its stills
# were a "temporarily unavailable" placeholder on 2026-11-15, so it is left out.
CARS511_SITES: List[tuple[str, str, str, str, tuple]] = [
    ("cctv_in511", "https://511in.org", "INDOT", "Indiana INDOT", (37.7, 41.9, -88.2, -84.6)),
    ("cctv_ia511", "https://511ia.org", "IADOT", "Iowa DOT", (40.3, 43.6, -96.7, -90.1)),
    ("cctv_ne511", "https://511.nebraska.gov", "NEDOT", "Nebraska 511", (39.9, 43.1, -104.1, -95.3)),
    ("cctv_ks511", "https://www.kandrive.gov", "KSDOT", "Kansas KanDrive", (36.9, 40.1, -102.1, -94.5)),
]


class FintrafficWeathercamIngestor(BaseCCTVIngestor):
    """Finland's road weather cameras from Fintraffic Digitraffic (~800 stations).

    A station has several presets (directions); the first collected one is used.
    """

    FEED_URL = "https://tie.digitraffic.fi/api/weathercam/v1/stations"
    BOUNDS = (59.0, 70.2, 19.0, 31.7)

    def fetch_data(self) -> List[Dict[str, Any]]:
        # Digitraffic asks clients to identify themselves with this header.
        data = _get_feed_json(self.FEED_URL, headers={"Digitraffic-User": "ShadowBroker"})
        features = data.get("features") if isinstance(data, dict) else None
        if not isinstance(features, list):
            return []
        cameras: List[Dict[str, Any]] = []
        for feature in features:
            props = feature.get("properties") if isinstance(feature, dict) else None
            if not isinstance(props, dict) or str(props.get("collectionStatus") or "").startswith("REMOVED"):
                continue
            coords_raw = (feature.get("geometry") or {}).get("coordinates")
            if not isinstance(coords_raw, list) or len(coords_raw) < 2:
                continue
            coords = _lat_lon_in(coords_raw[1], coords_raw[0], self.BOUNDS)
            presets = [p for p in props.get("presets") or [] if isinstance(p, dict) and p.get("inCollection") is not False]
            preset_id = str((presets[0] if presets else {}).get("id") or "")
            station_id = str(props.get("id") or feature.get("id") or "")
            if not coords or not re.fullmatch(r"[A-Z0-9]+", preset_id) or not station_id:
                continue
            cameras.append({
                "id": f"FINTRAFFIC-{station_id}",
                "source_agency": "Fintraffic",
                "lat": coords[0],
                "lon": coords[1],
                "direction_facing": (str(props.get("name") or "").replace("_", " ").strip() or "Finland weathercam")[:120],
                "media_url": f"https://weathercam.digitraffic.fi/{preset_id}.jpg",
                "media_type": "image",
                "refresh_rate_seconds": 600,
            })
        logger.info("FintrafficWeathercamIngestor: parsed %s cameras", len(cameras))
        return cameras


def _xml_children(element) -> Dict[str, Any]:
    """Direct children by local tag name (first wins)."""
    out: Dict[str, Any] = {}
    for child in list(element):
        out.setdefault(str(child.tag).rsplit("}", 1)[-1], child)
    return out


def _xml_text(children: Dict[str, Any], name: str) -> str:
    node = children.get(name)
    return (node.text or "").strip() if node is not None else ""


class HongKongTDIngestor(BaseCCTVIngestor):
    """Hong Kong Transport Department traffic snapshots (~1,000 cameras, data.gov.hk)."""

    FEED_URL = "https://static.data.gov.hk/td/traffic-snapshot-images/code/Traffic_Camera_Locations_En.xml"
    BOUNDS = (22.1, 22.6, 113.8, 114.5)

    def fetch_data(self) -> List[Dict[str, Any]]:
        root = _get_feed_xml(self.FEED_URL)
        if root is None:
            return []
        cameras: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for image in root.iter():
            if str(image.tag).rsplit("}", 1)[-1] != "image":
                continue
            kids = _xml_children(image)
            key = _xml_text(kids, "key")
            url = _https_url_on(_xml_text(kids, "url"), "tdcctv.data.one.gov.hk", r"\.jpe?g$")
            coords = _lat_lon_in(_xml_text(kids, "latitude"), _xml_text(kids, "longitude"), self.BOUNDS)
            if not re.fullmatch(r"[A-Za-z0-9]+", key) or key in seen or not url or not coords:
                continue
            seen.add(key)
            name = re.sub(r"\s*\[[^\]]*\]\s*$", "", _xml_text(kids, "description")) or f"HK camera {key}"
            district = _xml_text(kids, "district")
            cameras.append({
                "id": f"HKTD-{key}",
                "source_agency": "Hong Kong Transport Dept",
                "lat": coords[0],
                "lon": coords[1],
                "direction_facing": (f"{name} ({district})" if district else name)[:120],
                "media_url": url,
                "media_type": "image",
                "refresh_rate_seconds": 120,
            })
        logger.info("HongKongTDIngestor: parsed %s cameras", len(cameras))
        return cameras


class QueenslandTrafficIngestor(BaseCCTVIngestor):
    """Queensland QLDTraffic road and flood cameras (~260)."""

    FEEDS = (
        ("traffic", "https://data.qldtraffic.qld.gov.au/webcameras.geojson", "QLDTraffic"),
        ("flood", "https://data.qldtraffic.qld.gov.au/floodcameras.geojson", "QLDTraffic flood camera"),
    )
    BOUNDS = (-29.3, -9.0, 137.9, 154.0)

    def fetch_data(self) -> List[Dict[str, Any]]:
        cameras: List[Dict[str, Any]] = []
        for kind, url, agency in self.FEEDS:
            data = _get_feed_json(url, headers={"Accept": "application/geo+json, application/json"})
            features = data.get("features") if isinstance(data, dict) else None
            for feature in features if isinstance(features, list) else []:
                props = feature.get("properties") if isinstance(feature, dict) else None
                if not isinstance(props, dict) or props.get("id") is None:
                    continue
                coords_raw = (feature.get("geometry") or {}).get("coordinates")
                if not isinstance(coords_raw, list) or len(coords_raw) < 2:
                    continue
                coords = _lat_lon_in(coords_raw[1], coords_raw[0], self.BOUNDS)
                image = _https_url_on(props.get("image_url"), "qldtraffic.qld.gov.au", r"\.jpe?g$")
                if not coords or not image:
                    continue
                label = str(props.get("description") or "").strip() or f"Queensland {kind} camera"
                cameras.append({
                    "id": f"QLD-{kind}-{props['id']}",
                    "source_agency": agency,
                    "lat": coords[0],
                    "lon": coords[1],
                    "direction_facing": label[:120],
                    "media_url": image,
                    "media_type": "image",
                    "refresh_rate_seconds": 120,
                })
        logger.info("QueenslandTrafficIngestor: parsed %s cameras", len(cameras))
        return cameras


class NZTAIngestor(BaseCCTVIngestor):
    """New Zealand Transport Agency highway cameras (~300, trafficnz.info)."""

    FEED_URL = "https://trafficnz.info/service/traffic/rest/4/cameras/all"
    BASE = "https://trafficnz.info"
    BOUNDS = (-47.5, -34.0, 166.0, 179.0)

    def fetch_data(self) -> List[Dict[str, Any]]:
        root = _get_feed_xml(self.FEED_URL, timeout=30)
        if root is None:
            return []
        cameras: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for camera in root.iter():
            if str(camera.tag).rsplit("}", 1)[-1] != "camera":
                continue
            kids = _xml_children(camera)
            cam_id = _xml_text(kids, "id")
            image_path = _xml_text(kids, "imageUrl")
            if not cam_id.isdigit() or cam_id in seen or not re.fullmatch(r"/camera/\d+\.jpg", image_path):
                continue
            if _xml_text(kids, "offline") == "true" or _xml_text(kids, "underMaintenance") == "true":
                continue
            coords = _lat_lon_in(_xml_text(kids, "latitude"), _xml_text(kids, "longitude"), self.BOUNDS)
            if not coords:
                continue
            seen.add(cam_id)
            name = _xml_text(kids, "name") or _xml_text(kids, "description") or f"NZTA camera {cam_id}"
            direction = _xml_text(kids, "direction")
            if direction and direction != "NA":
                name = f"{name} ({direction})"
            cameras.append({
                "id": f"NZTA-{cam_id}",
                "source_agency": "NZ Transport Agency",
                "lat": coords[0],
                "lon": coords[1],
                "direction_facing": name[:120],
                "media_url": f"{self.BASE}{image_path}",
                "media_type": "image",
                "refresh_rate_seconds": 120,
            })
        logger.info("NZTAIngestor: parsed %s cameras", len(cameras))
        return cameras


# ---------------------------------------------------------------------------
# Third batch: Europe, Asia-Pacific and the last North American feeds. Found
# via the MIT-licensed OSIRIS project (github.com/simplifaisoul/osiris) and
# checked live on 2026-11-15.
# ---------------------------------------------------------------------------

_FRAME_MAX_AGE_S = 6 * 3600


def _get_feed_text(url: str, *, timeout: int = 20, headers: dict | None = None) -> str:
    resp = fetch_with_curl(url, timeout=timeout, headers=headers or {})
    if resp is None or getattr(resp, "status_code", 0) != 200:
        logger.warning("CCTV feed %s returned HTTP %s", url, getattr(resp, "status_code", None))
        return ""
    return resp.text or ""


def _frame_is_fresh(url: str, max_age_s: int = _FRAME_MAX_AGE_S, headers: dict | None = None) -> bool:
    """Whether a frame answers and was modified within max_age_s.

    Only the headers are read (an MJPEG stream never ends). A frame without a
    Last-Modified header counts as fresh.
    """
    from email.utils import parsedate_to_datetime
    import time

    from services.network_utils import default_user_agent

    try:
        resp = requests.get(
            url,
            headers={"User-Agent": default_user_agent(), "Range": "bytes=0-0", **(headers or {})},
            timeout=(3, 6),
            stream=True,
        )
    except requests.RequestException:
        return False
    try:
        if resp.status_code not in (200, 206):
            return False
        modified = resp.headers.get("Last-Modified")
        if not modified:
            return True
        try:
            return time.time() - parsedate_to_datetime(modified).timestamp() <= max_age_s
        except (TypeError, ValueError):
            return True
    finally:
        resp.close()


def _keep_fresh_frames(cameras: List[Dict[str, Any]], workers: int = 8) -> List[Dict[str, Any]]:
    """Drop cameras whose frame does not answer or stopped updating hours ago."""
    from concurrent.futures import ThreadPoolExecutor

    if not cameras:
        return []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        fresh = list(pool.map(lambda cam: _frame_is_fresh(cam["media_url"]), cameras))
    return [cam for cam, ok in zip(cameras, fresh) if ok]


class IcelandVegagerdinIngestor(BaseCCTVIngestor):
    """Iceland's road cameras from Vegagerðin's open API (~500 stills)."""

    FEED_URL = "https://gagnaveita.vegagerdin.is/api/vefmyndavelar2014_1"
    BOUNDS = (63.2, 66.7, -24.6, -13.4)

    def fetch_data(self) -> List[Dict[str, Any]]:
        data = _get_feed_json(self.FEED_URL)
        if not isinstance(data, list):
            return []
        cameras: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for row in data:
            if not isinstance(row, dict):
                continue
            coords = _lat_lon_in(row.get("Breidd"), row.get("Lengd"), self.BOUNDS)
            media = _https_url_on(row.get("Slod"), "vegagerdin.is", r"^/vgdata/vefmyndavelar/[\w.-]+\.jpg$")
            if not coords or not media:
                continue
            # A station (Maelist_nr) can carry several cameras; the file name is unique.
            cam_id = f"ISVEG-{media.rsplit('/', 1)[-1][:-4]}"
            if cam_id in seen:
                continue
            seen.add(cam_id)
            place = str(row.get("Myndavel") or "").strip()
            view = str(row.get("Skyring") or "").strip()
            label = view if place and view.startswith(place) else " - ".join(p for p in (place, view) if p)
            cameras.append({
                "id": cam_id,
                "source_agency": "Vegagerðin (Iceland)",
                "lat": coords[0],
                "lon": coords[1],
                "direction_facing": (label or "Iceland road camera")[:120],
                "media_url": media,
                "media_type": "image",
                "refresh_rate_seconds": 300,
            })
        logger.info("IcelandVegagerdinIngestor: parsed %s cameras", len(cameras))
        return cameras


class TaiwanTHBIngestor(BaseCCTVIngestor):
    """Taiwan Highway Bureau provincial-highway cameras (~2,200 snapshots)."""

    FEED_URL = "https://thbapp.thb.gov.tw/services/cctv/thb"
    BOUNDS = (21.8, 25.4, 119.9, 122.1)

    def fetch_data(self) -> List[Dict[str, Any]]:
        data = _get_feed_json(self.FEED_URL, timeout=30, headers={"Accept": "application/json"})
        if not isinstance(data, list):
            return []
        cameras: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for row in data:
            if not isinstance(row, dict):
                continue
            cam_id = str(row.get("id") or "").strip()
            coords = _lat_lon_in(row.get("gisy"), row.get("gisx"), self.BOUNDS)
            # Each camera's own server (cctv-ssNN.thb.gov.tw/<stake>) serves /snapshot.
            base = _https_url_on(row.get("html"), "thb.gov.tw", r"^/[^/]+$")
            if not re.fullmatch(r"[\w-]{1,64}", cam_id) or cam_id in seen or not coords or not base:
                continue
            seen.add(cam_id)
            cameras.append({
                "id": f"TWTHB-{cam_id}",
                "source_agency": "Taiwan Highway Bureau",
                "lat": coords[0],
                "lon": coords[1],
                "direction_facing": (str(row.get("stakenumber") or "").strip() or "Taiwan highway camera")[:120],
                "media_url": f"{base}/snapshot",
                "media_type": "image",
                "refresh_rate_seconds": 60,
            })
        logger.info("TaiwanTHBIngestor: parsed %s cameras", len(cameras))
        return cameras


class LithuaniaViaLietuvaIngestor(BaseCCTVIngestor):
    """Lithuania's national-road cameras from Via Lietuva / eismoinfo.lt (~300).

    The camera table has names and the newest frame's time; the VKR map layer
    (with lks=false, so WGS84) has the positions. They are joined on id.
    """

    LAYER_URL = "https://eismoinfo.lt/eismoinfo-backend/layer-static-features/VKR?lks=false"
    TABLE_URL = "https://eismoinfo.lt/eismoinfo-backend/camera-info-table"
    IMAGE_URL = "https://eismoinfo.lt/eismoinfo-backend/image-provider/camera/last?id={id}"
    BOUNDS = (53.8, 56.5, 20.9, 26.9)

    def fetch_data(self) -> List[Dict[str, Any]]:
        import time

        layers = _get_feed_json(self.LAYER_URL, headers={"Accept": "application/json"})
        table = _get_feed_json(self.TABLE_URL, headers={"Accept": "application/json"})
        if not isinstance(layers, list) or not isinstance(table, list):
            return []
        points: Dict[str, tuple[float, float]] = {}
        for layer in layers:
            for feature in (layer.get("features") or []) if isinstance(layer, dict) else []:
                if not isinstance(feature, dict):
                    continue
                first = (feature.get("points") or [{}])[0]
                point = first.get("point") if isinstance(first, dict) else None
                coords = _lat_lon_in(point[0], point[1], self.BOUNDS) if isinstance(point, list) and len(point) >= 2 else None
                if coords:
                    points[str(feature.get("id"))] = coords
        now_ms = time.time() * 1000
        cameras: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for row in table:
            if not isinstance(row, dict):
                continue
            cam_id = str(row.get("id") or "")
            coords = points.get(cam_id)
            if not cam_id.isdigit() or cam_id in seen or not coords:
                continue
            # A camera whose newest frame is hours old has stopped publishing.
            frame_ms = row.get("date") if isinstance(row.get("date"), (int, float)) else 0
            if now_ms - frame_ms > _FRAME_MAX_AGE_S * 1000:
                continue
            seen.add(cam_id)
            name = str(row.get("name") or "").strip() or f"Via Lietuva camera {cam_id}"
            road = str(row.get("roadName") or "").strip()
            cameras.append({
                "id": f"LTVIA-{cam_id}",
                "source_agency": "Via Lietuva",
                "lat": coords[0],
                "lon": coords[1],
                "direction_facing": (f"{name} ({road})" if road else name)[:120],
                "media_url": self.IMAGE_URL.format(id=cam_id),
                "media_type": "image",
                "refresh_rate_seconds": 600,
            })
        logger.info("LithuaniaViaLietuvaIngestor: parsed %s cameras", len(cameras))
        return cameras


def _utm30n_to_lat_lon(easting: float, northing: float) -> tuple[float, float]:
    """UTM zone 30N (ETRS89 / GRS80) easting and northing to latitude and longitude."""
    import math

    a, f, k0 = 6378137.0, 1 / 298.257222101, 0.9996
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    mu = northing / k0 / (a * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256))
    phi = (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu)
           + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
           + (151 * e1 ** 3 / 96) * math.sin(6 * mu) + (1097 * e1 ** 4 / 512) * math.sin(8 * mu))
    sin, cos = math.sin(phi), math.cos(phi)
    t, c = math.tan(phi) ** 2, ep2 * cos ** 2
    n = a / math.sqrt(1 - e2 * sin ** 2)
    r = a * (1 - e2) / (1 - e2 * sin ** 2) ** 1.5
    d = (easting - 500000) / (n * k0)
    lat = phi - (n * math.tan(phi) / r) * (
        d ** 2 / 2 - (5 + 3 * t + 10 * c - 4 * c ** 2 - 9 * ep2) * d ** 4 / 24
        + (61 + 90 * t + 298 * c + 45 * t ** 2 - 252 * ep2 - 3 * c ** 2) * d ** 6 / 720)
    lon = (d - (1 + 2 * t + c) * d ** 3 / 6
           + (5 - 2 * c + 28 * t - 3 * c ** 2 + 8 * ep2 + 24 * t ** 2) * d ** 5 / 120) / cos
    return math.degrees(lat), -3 + math.degrees(lon)


class BizkaiaTrafficIngestor(BaseCCTVIngestor):
    """Bizkaia (Basque Country) road cameras from Open Data Euskadi (~60 stills).

    The API lists 489 cameras from seven operators; only the Diputación Foral
    de Bizkaia's (sourceId 2) carry an image URL anyone can load. Their
    positions come as UTM 30N metres in the latitude/longitude fields.
    """

    API_URL = "https://api.euskadi.eus/traffic/v1.0/cameras"
    BOUNDS = (42.4, 43.6, -3.6, -1.6)

    def fetch_data(self) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        page, pages = 1, 1
        while page <= min(pages, 100):
            data = _get_feed_json(f"{self.API_URL}?_page={page}", headers={"Accept": "application/json"})
            if not isinstance(data, dict):
                break
            rows.extend(r for r in data.get("cameras") or [] if isinstance(r, dict))
            try:
                pages = int(data.get("totalPages") or 1)
            except (TypeError, ValueError):
                pages = 1
            page += 1
        cameras: List[Dict[str, Any]] = []
        for row in rows:
            cam_id = str(row.get("cameraId") or "").strip()
            match = re.search(r"/camaras/(cam\d+\.jpg)", str(row.get("urlImage") or ""), re.IGNORECASE)
            host = str(urlparse(str(row.get("urlImage") or "").strip()).hostname or "").lower()
            if row.get("sourceId") != "2" or not cam_id.isdigit() or not match:
                continue
            if host not in ("bizkaimove.com", "www.bizkaimove.com", "bizkaimove.eus", "www.bizkaimove.eus"):
                continue
            try:
                lat, lon = float(row.get("latitude")), float(row.get("longitude"))
            except (TypeError, ValueError):
                continue
            if abs(lat) > 90:
                lat, lon = _utm30n_to_lat_lon(lon, lat)
            coords = _lat_lon_in(lat, lon, self.BOUNDS)
            if not coords:
                continue
            name = re.sub(r"^CCTV\s*\d+\s*-\s*", "", str(row.get("cameraName") or ""), flags=re.IGNORECASE).strip()
            road = re.sub(r"\s*-\s*", "-", str(row.get("road") or "")).strip()
            label = f"{road} - {name}" if road and name and road not in name else (name or road)
            cameras.append({
                "id": f"BIZKAIA-{cam_id}",
                "source_agency": "Bizkaimove (Bizkaia)",
                "lat": coords[0],
                "lon": coords[1],
                "direction_facing": (label or f"Bizkaia camera {cam_id}")[:120],
                # bizkaimove.com redirects here; the same frame over https.
                "media_url": f"https://www.bizkaimove.eus/camaras/{match.group(1).lower()}",
                "media_type": "image",
                "refresh_rate_seconds": 300,
            })
        cameras = _keep_fresh_frames(cameras)
        logger.info("BizkaiaTrafficIngestor: parsed %s publishing cameras", len(cameras))
        return cameras


_FRANCE_BOUNDS = (41.3, 51.2, -5.3, 9.7)


class DIRCentreEstIngestor(BaseCCTVIngestor):
    """DIR Centre-Est national-road cameras around Lyon, Grenoble and Saint-Étienne.

    The map page declares its cameras inline; each uploads a 25-second clip
    every five minutes to /streams/last/nce.<id>.mp4.
    """

    BASE = "https://www.webcams-dir.centre-est.developpement-durable.gouv.fr"
    _CAMERA = re.compile(
        r'\{id:\s*(\d+),\s*latitude:\s*(-?[\d.]+),\s*longitude:\s*(-?[\d.]+),[^{}]*?'
        r'description:"([^"]*)",\s*direction:"([^"]*)"\}'
    )

    def fetch_data(self) -> List[Dict[str, Any]]:
        html = _get_feed_text(f"{self.BASE}/")
        cameras: List[Dict[str, Any]] = []
        for cam_id, lat, lon, description, direction in self._CAMERA.findall(html):
            coords = _lat_lon_in(lat, lon, _FRANCE_BOUNDS)
            if not coords:
                continue
            label = f"{description} ({direction})" if direction else description
            cameras.append({
                "id": f"DIRCE-{cam_id}",
                "source_agency": "DIR Centre-Est",
                "lat": coords[0],
                "lon": coords[1],
                "direction_facing": (label.strip() or "DIR Centre-Est camera")[:120],
                "media_url": f"{self.BASE}/streams/last/nce.{cam_id}.mp4",
                "media_type": "video",
                "refresh_rate_seconds": 300,
            })
        logger.info("DIRCentreEstIngestor: parsed %s cameras", len(cameras))
        return cameras


class DIREstIngestor(BaseCCTVIngestor):
    """DIR Est national-road cameras in Lorraine, Alsace and Franche-Comté.

    The map page declares its cameras inline; etat:0 marks one switched off.
    """

    BASE = "https://webcam.dir-est.fr"
    _CAMERA = re.compile(
        r'\{nom:"([^"]*)",\s*x\s*:\s*(-?[\d.]+)\s*,\s*y\s*:\s*(-?[\d.]+)\s*,\s*'
        r'add:"chargerFenetreModale\((\d+)\)",\s*etat:(\d)\}'
    )

    def fetch_data(self) -> List[Dict[str, Any]]:
        html = _get_feed_text(f"{self.BASE}/")
        cameras: List[Dict[str, Any]] = []
        for name, lon, lat, cam_id, state in self._CAMERA.findall(html):
            coords = _lat_lon_in(lat, lon, _FRANCE_BOUNDS)
            if state != "1" or not coords:
                continue
            cameras.append({
                "id": f"DIREST-{cam_id}",
                "source_agency": "DIR Est",
                "lat": coords[0],
                "lon": coords[1],
                "direction_facing": (name.strip() or "DIR Est camera")[:120],
                "media_url": f"{self.BASE}/lastimg/{cam_id}",
                "media_type": "image",
                "refresh_rate_seconds": 300,
            })
        logger.info("DIREstIngestor: parsed %s cameras", len(cameras))
        return cameras


class LyonCriterIngestor(BaseCCTVIngestor):
    """Métropole de Lyon Criter traffic cameras (open data WFS, stills every minute)."""

    FEED_URL = (
        "https://data.grandlyon.com/geoserver/metropole-de-lyon/ows?SERVICE=WFS&VERSION=2.0.0"
        "&request=GetFeature&typename=metropole-de-lyon:pvo_patrimoine_voirie.pvocameracriter"
        "&outputFormat=application/json&SRSNAME=EPSG:4326"
    )

    def fetch_data(self) -> List[Dict[str, Any]]:
        data = _get_feed_json(self.FEED_URL)
        features = data.get("features") if isinstance(data, dict) else None
        cameras: List[Dict[str, Any]] = []
        for feature in features if isinstance(features, list) else []:
            props = feature.get("properties") if isinstance(feature, dict) else None
            coords_raw = (feature.get("geometry") or {}).get("coordinates") if isinstance(feature, dict) else None
            if not isinstance(props, dict) or not isinstance(coords_raw, list) or len(coords_raw) < 2:
                continue
            coords = _lat_lon_in(coords_raw[1], coords_raw[0], _FRANCE_BOUNDS)
            media = _https_url_on(props.get("url"), "download.data.grandlyon.com", r"\.jpe?g$")
            cam_id = str(props.get("identifiant") or "")
            if not coords or not media or not cam_id.isdigit():
                continue
            where = str(props.get("libellelong") or "").strip()
            towards = str(props.get("nom") or "").strip()
            cameras.append({
                "id": f"LYON-{cam_id}",
                "source_agency": "Métropole de Lyon",
                "lat": coords[0],
                "lon": coords[1],
                "direction_facing": ((f"{where} (towards {towards})" if towards else where) or "Lyon traffic camera")[:120],
                "media_url": media,
                "media_type": "image",
                "refresh_rate_seconds": 60,
            })
        # No freshness filter here: frames are rewritten every minute and about
        # 3% of requests fail mid-rewrite, so a filter would drop working cameras.
        logger.info("LyonCriterIngestor: parsed %s cameras", len(cameras))
        return cameras


# (scheduler key, host, id prefix, département, {media kind: newest-frame file}).
# French départements running Logipro's Inforoute site; the webcam layer is one
# POST (action 383). Only file names checked against live frames are listed.
# Moselle's local stills are time-stamped (no fixed name), so only its MJPEG
# encoders are used.
INFOROUTE_SITES: List[tuple[str, str, str, str, Dict[str, str]]] = [
    ("cctv_inforoute06", "www.inforoutes06.fr", "INFOROUTE06", "Alpes-Maritimes", {"DEFILEMENT_IMAGE": "snap5.jpg"}),
    ("cctv_inforoute67", "inforoute.alsace.eu", "INFOROUTE67", "Alsace", {"IMAGE": "lastimage.jpeg"}),
    ("cctv_inforoute21", "www.inforoute21.fr", "INFOROUTE21", "Côte-d'Or", {"VIDEO": "lastimage.mp4"}),
    ("cctv_inforoute11", "www.inforoute11.fr", "INFOROUTE11", "Aude", {"IMAGE": "last_image.jpeg"}),
    ("cctv_inforoute57", "www.inforoute57.fr", "INFOROUTE57", "Moselle", {}),
]


class InforouteIngestor(BaseCCTVIngestor):
    """One French département's Inforoute road cameras."""

    def __init__(self, host: str, id_prefix: str, department: str, files: Dict[str, str]):
        self.host = host
        self.id_prefix = id_prefix
        self.department = department
        self.files = files

    def _media(self, props: Dict[str, Any]) -> tuple[str, str]:
        if props.get("config") == "animation":
            url = str(props.get("url_distant") or "")
            return (url, "mjpeg") if re.fullmatch(r"https://[\w.-]+(:\d+)?/stream\d+\.cgi", url) else ("", "")
        folder = str(props.get("url_dossier") or "")
        file_name = self.files.get(str(props.get("type_media") or ""))
        if props.get("config") != "local" or not file_name or not folder.startswith(f"https://{self.host}/"):
            return "", ""
        url = folder.rstrip("/") + "/" + file_name
        return url, "video" if file_name.endswith(".mp4") else "image"

    def fetch_data(self) -> List[Dict[str, Any]]:
        from services.network_utils import default_user_agent

        try:
            resp = requests.post(
                f"https://{self.host}/mod_turbolead/mod/inforoute/index.php",
                data={"action": "383"},
                headers={"User-Agent": default_user_agent(), "Accept": "application/json"},
                timeout=(3, 20),
            )
            data = resp.json() if resp.status_code == 200 else None
        except (requests.RequestException, ValueError) as e:
            logger.warning("Inforoute %s fetch failed: %s", self.host, e)
            return []
        features = data.get("features") if isinstance(data, dict) else None
        cameras: List[Dict[str, Any]] = []
        for feature in features if isinstance(features, list) else []:
            props = feature.get("properties") if isinstance(feature, dict) else None
            coords_raw = (feature.get("geometry") or {}).get("coordinates") if isinstance(feature, dict) else None
            if not isinstance(props, dict) or not isinstance(coords_raw, list) or len(coords_raw) < 2:
                continue
            cam_id = str(props.get("id_webcam") or "")
            coords = _lat_lon_in(coords_raw[1], coords_raw[0], _FRANCE_BOUNDS)
            media, media_type = self._media(props)
            if not cam_id.isdigit() or props.get("actif") == "0" or not coords or not media:
                continue
            cameras.append({
                "id": f"{self.id_prefix}-{cam_id}",
                "source_agency": f"Inforoute {self.department}",
                "lat": coords[0],
                "lon": coords[1],
                "direction_facing": (str(props.get("titre") or "").strip() or f"{self.department} camera")[:120],
                "media_url": media,
                "media_type": media_type,
                "refresh_rate_seconds": 300,
            })
        # Stills that stopped updating stay on the server under the same name,
        # and Moselle's encoders refuse connections when off.
        cameras = _keep_fresh_frames(cameras)
        logger.info("InforouteIngestor %s: parsed %s publishing cameras", self.host, len(cameras))
        return cameras


class APRRIngestor(BaseCCTVIngestor):
    """APRR / AREA motorway cameras (France, ~100 live 25-second clips).

    voyage.aprr.fr lists positions in one call and each camera's name and
    Viewsurf video in another; the details are kept for a day. Each Viewsurf
    address redirects to that camera's newest clip, or to an "unavailable"
    clip when the camera is down, which is checked on every run.
    """

    BASE = "https://voyage.aprr.fr"
    _details: Dict[str, tuple[float, Dict[str, Any]]] = {}
    _DETAILS_TTL_S = 24 * 3600

    def _detail(self, poi_id: str) -> Dict[str, Any] | None:
        import time

        cached = self._details.get(poi_id)
        if cached and time.time() - cached[0] < self._DETAILS_TTL_S:
            return cached[1]
        data = _get_feed_json(f"{self.BASE}/api/aprr/pois/popin/webcam/{poi_id}", headers={"Accept": "application/json"})
        row = data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else None
        detail = row.get("data") if row else None
        if isinstance(detail, dict):
            self._details[poi_id] = (time.time(), detail)
            return detail
        return None

    @staticmethod
    def _is_live(media_url: str) -> bool:
        from services.network_utils import default_user_agent
        from services.ssrf_guard import validate_host

        parsed = urlparse(media_url)
        if parsed.scheme not in ("http", "https"):
            return False
        host_check = validate_host(parsed.hostname or "")
        if not host_check.get("ok"):
            return False
        try:
            resp = requests.get(media_url, headers={"User-Agent": default_user_agent()},
                                allow_redirects=False, timeout=(3, 8))
        except requests.RequestException:
            return False
        location = resp.headers.get("Location", "")
        resp.close()
        host = str(urlparse(location).hostname or "").lower()
        return resp.status_code in (301, 302, 303, 307) and host.endswith("viewsurf.com") and "indisponibilite" not in location

    def fetch_data(self) -> List[Dict[str, Any]]:
        from concurrent.futures import ThreadPoolExecutor

        pois = _get_feed_json(f"{self.BASE}/api/aprr/pois/webcam", headers={"Accept": "application/json"})
        if not isinstance(pois, list):
            return []
        pois = [p for p in pois if isinstance(p, dict) and str(p.get("id") or "").isdigit()]
        with ThreadPoolExecutor(max_workers=4) as pool:
            details = list(pool.map(lambda p: self._detail(str(p["id"])), pois))
        cameras: List[Dict[str, Any]] = []
        for poi, detail in zip(pois, details):
            coords_raw = poi.get("coords") or {}
            coords = _lat_lon_in(coords_raw.get("lat"), coords_raw.get("lon"), _FRANCE_BOUNDS)
            video_id = re.search(r"[?&]id=(\d+)", str((detail or {}).get("video") or ""))
            title = str((detail or {}).get("title") or "").strip()
            if not coords or not video_id or not title:
                continue
            tags = [t.strip() for t in str(detail.get("tags") or "").split("|") if t.strip()]
            heading = next((t for t in tags if re.match(r"sens\b", t, re.IGNORECASE)), "")
            road = tags[0] if tags else ""
            label = f"{title} ({heading})" if heading else title
            cameras.append({
                "id": f"APRR-{poi['id']}",
                "source_agency": "APRR",
                "lat": coords[0],
                "lon": coords[1],
                "direction_facing": (f"{road} - {label}" if road and road not in label else label)[:120],
                "media_url": f"https://gieat.viewsurf.com/?id={video_id.group(1)}&action=mediaRedirect",
                "media_type": "video",
                "refresh_rate_seconds": 300,
            })
        with ThreadPoolExecutor(max_workers=4) as pool:
            live = list(pool.map(lambda cam: self._is_live(cam["media_url"]), cameras))
        cameras = [cam for cam, ok in zip(cameras, live) if ok]
        logger.info("APRRIngestor: parsed %s live cameras", len(cameras))
        return cameras


class AutostradeIngestor(BaseCCTVIngestor):
    """Autostrade per l'Italia motorway cameras (~970 short MP4 clips).

    Each clip is re-recorded every few minutes at the same address. A camera
    whose last clip is over a day old has stopped recording.
    """

    FEED_URL = "https://viabilita.autostrade.it/json/webcams.json"
    VIDEO_BASE = "https://video.autostrade.it/video-mp4_hq/"
    BOUNDS = (36.0, 47.5, 6.5, 18.6)
    _CLIP = re.compile(r"[a-z0-9]{2,8}/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}-\d{1,4}\.mp4")

    @staticmethod
    def _clip_time(day, clock) -> float | None:
        from datetime import datetime, timezone

        try:
            # Italian local time read as UTC: an hour or two is nothing against a day.
            return datetime.strptime(f"{day} {clock}", "%d-%m-%Y %H:%M").replace(tzinfo=timezone.utc).timestamp()
        except (TypeError, ValueError):
            return None

    def fetch_data(self) -> List[Dict[str, Any]]:
        import time

        data = _get_feed_json(self.FEED_URL, timeout=30, headers={"Accept": "application/json"})
        webcams = data.get("webcams") if isinstance(data, dict) else None
        now = time.time()
        cameras: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for row in webcams if isinstance(webcams, list) else []:
            if not isinstance(row, dict):
                continue
            cam_id = str(row.get("c_tel") or "")
            clip = ((row.get("frames") or {}).get("V") or {}).get("t_url") if isinstance(row.get("frames"), dict) else None
            coords = _lat_lon_in(row.get("n_crd_lat"), row.get("n_crd_lon"), self.BOUNDS)
            stamp = self._clip_time(row.get("t_day"), row.get("t_time"))
            if not cam_id.isdigit() or cam_id in seen or not coords or not isinstance(clip, str):
                continue
            if not self._CLIP.fullmatch(clip) or stamp is None or now - stamp > 24 * 3600:
                continue
            seen.add(cam_id)
            road = re.sub(r"\s+", " ", re.sub(r"[︀-️]", "", str(row.get("t_des_str") or ""))).strip() or "Autostrade"
            where = re.sub(r"\s+", " ", str(row.get("t_des") or "")).strip()
            cameras.append({
                "id": f"ASPI-{cam_id}",
                "source_agency": "Autostrade per l'Italia",
                "lat": coords[0],
                "lon": coords[1],
                "direction_facing": (f"{road.split(' ')[0]} {where}" if where else road)[:120],
                "media_url": f"{self.VIDEO_BASE}{clip}",
                "media_type": "video",
                "refresh_rate_seconds": 300,
            })
        logger.info("AutostradeIngestor: parsed %s cameras", len(cameras))
        return cameras


class EdmontonTrafficIngestor(BaseCCTVIngestor):
    """City of Edmonton traffic cameras (~58 live HLS streams).

    The stream codes rotate, so they are read from the city's GetCameras page
    method on every run.
    """

    API_URL = "https://edmontontrafficcam.com/Default.aspx/GetCameras"
    BOUNDS = (53.3, 53.8, -114.0, -113.2)

    def fetch_data(self) -> List[Dict[str, Any]]:
        data = _get_feed_json(self.API_URL, method="POST", json_data={}, headers={"Accept": "application/json"})
        rows = data.get("d") if isinstance(data, dict) else None
        cameras: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict) or str(row.get("Status")) != "1":
                continue
            code = str(row.get("Code") or "")
            host = str(row.get("MMSUrl") or "").strip().lower()
            stream = str(row.get("StreamCode") or "").strip()
            forge = row.get("Forge")
            coords = _lat_lon_in(row.get("Latitude"), row.get("Longitude"), self.BOUNDS)
            if not code.isdigit() or code in seen or not coords:
                continue
            if not re.fullmatch(r"[a-z0-9-]+\.winkcdn\.com", host) or not isinstance(forge, int) or not re.fullmatch(r"[\w-]+", stream):
                continue
            seen.add(code)
            roads = " & ".join(r for r in (str(row.get("PrimaryRoad") or "").strip(), str(row.get("SecondaryRoad") or "").strip()) if r)
            cameras.append({
                "id": f"YEG-{code}",
                "source_agency": "City of Edmonton",
                "lat": coords[0],
                "lon": coords[1],
                "direction_facing": (roads or f"Edmonton camera {code}")[:120],
                "media_url": f"https://{host}/{forge}/public/hls/{stream}.m3u8",
                "media_type": "hls",
                "refresh_rate_seconds": 60,
            })
        logger.info("EdmontonTrafficIngestor: parsed %s cameras", len(cameras))
        return cameras


class OregonTripCheckIngestor(BaseCCTVIngestor):
    """Oregon ODOT TripCheck road cameras statewide (~1,150 stills).

    TripCheck also shows Washington's cameras around Vancouver and
    California's south of the 42nd parallel. WSDOT and Caltrans are ingested
    from their own feeds, so those are skipped here.
    """

    FEED_URL = "https://www.tripcheck.com/Scripts/map/data/cctvinventory.js"
    IMAGE_BASE = "https://tripcheck.com/RoadCams/cams/"
    BOUNDS = (42.0, 46.3, -124.6, -116.4)
    _WASHINGTON = re.compile(r"\bWashington\s+-\s+", re.IGNORECASE)  # "I-5 Washington - Vancouver at 29th"

    def fetch_data(self) -> List[Dict[str, Any]]:
        # TripCheck answers 406 to a JSON Accept header; the body is JSON anyway.
        text = _get_feed_text(self.FEED_URL, timeout=30, headers={"Accept": "*/*"})
        try:
            data = json.loads(text) if text else None
        except ValueError:
            logger.warning("TripCheck inventory is not JSON")
            return []
        features = data.get("features") if isinstance(data, dict) else None
        cameras: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for feature in features if isinstance(features, list) else []:
            attrs = feature.get("attributes") if isinstance(feature, dict) else None
            if not isinstance(attrs, dict):
                continue
            cam_id = str(attrs.get("cameraId") or "")
            filename = str(attrs.get("filename") or "").strip()
            coords = _lat_lon_in(attrs.get("latitude"), attrs.get("longitude"), self.BOUNDS)
            # Names carry spaces and "@" ("I-5@Goshen_pid1504.jpg"); quoted, they load.
            if not cam_id.isdigit() or cam_id in seen or not coords:
                continue
            if not re.fullmatch(r"[^/\\?#\x00-\x1f]+\.jpe?g", filename, re.IGNORECASE):
                continue
            title = str(attrs.get("title") or attrs.get("route") or "").strip()
            if self._WASHINGTON.search(title):
                continue
            seen.add(cam_id)
            cameras.append({
                "id": f"TRIPCHECK-{cam_id}",
                "source_agency": "Oregon ODOT TripCheck",
                "lat": coords[0],
                "lon": coords[1],
                "direction_facing": (title or f"ODOT camera {cam_id}")[:120],
                "media_url": f"{self.IMAGE_BASE}{quote(filename)}",
                "media_type": "image",
                "refresh_rate_seconds": 300,
            })
        logger.info("OregonTripCheckIngestor: parsed %s cameras", len(cameras))
        return cameras


# Batch four (2026-11-18): more open feeds found in OSIRIS
# (github.com/simplifaisoul/osiris, MIT). All keyless.


class Minnesota511xIngestor(BaseCCTVIngestor):
    """Minnesota MnDOT cameras from the 511 map's camera API (~1,500).

    About 1,250 carry a live HLS stream on video.dot.state.mn.us; the rest are
    stills on public.carsprogram.org. A camera with several views uses its
    first working one.
    """

    API_URL = "https://api-511x-mn.carsprogram.org/cameras/map-features"
    BOUNDS = (43.3, 49.5, -97.4, -89.3)
    _HLS = re.compile(r"https://video\.dot\.state\.mn\.us/public/[\w.-]+/playlist\.m3u8")
    _STILL = re.compile(r"https://public\.carsprogram\.org/cameras/MN/[\w.-]+")

    def fetch_data(self) -> List[Dict[str, Any]]:
        data = _get_feed_json(self.API_URL, timeout=40, headers={"Accept": "application/json"})
        features = data.get("features") if isinstance(data, dict) else None
        cameras: List[Dict[str, Any]] = []
        seen: set[int] = set()
        for feat in features if isinstance(features, list) else []:
            props = (feat.get("properties") if isinstance(feat, dict) else None) or {}
            cam_id = props.get("id")
            if not isinstance(cam_id, int) or isinstance(cam_id, bool) or cam_id in seen:
                continue
            if props.get("public") is False:
                continue
            coords_raw = (feat.get("geometry") or {}).get("coordinates")
            if not isinstance(coords_raw, list) or len(coords_raw) < 2:
                continue
            coords = _lat_lon_in(coords_raw[1], coords_raw[0], self.BOUNDS)
            if not coords:
                continue
            media = None
            for view in props.get("views") or []:
                if not isinstance(view, dict) or view.get("broken"):
                    continue
                url = str(view.get("url") or "")
                if view.get("type") == "WMP" and self._HLS.fullmatch(url):
                    media = (url, "hls")
                    break
                if view.get("type") == "STILL_IMAGE" and self._STILL.fullmatch(url):
                    media = (url, "image")
                    break
            if not media:
                continue
            seen.add(cam_id)
            cameras.append({
                "id": f"MN511-{cam_id}",
                "source_agency": "Minnesota MnDOT",
                "lat": coords[0],
                "lon": coords[1],
                "direction_facing": (str(props.get("name") or "").strip() or f"MnDOT camera {cam_id}")[:120],
                "media_url": media[0],
                "media_type": media[1],
                "refresh_rate_seconds": 60,
            })
        logger.info("Minnesota511xIngestor: parsed %s cameras", len(cameras))
        return cameras


class DriveBCIngestor(BaseCCTVIngestor):
    """British Columbia highway cameras from DriveBC (~1,050 stills).

    Cameras DriveBC marks as off or stale are skipped. The www host and the
    trailing slash both matter: the bare host redirects and then answers 404.
    """

    API_URL = "https://www.drivebc.ca/api/webcams/"
    IMAGE_URL = "https://www.drivebc.ca/images/{id}.jpg"
    BOUNDS = (48.2, 60.1, -139.2, -114.0)

    def fetch_data(self) -> List[Dict[str, Any]]:
        rows = _get_feed_json(self.API_URL, timeout=30, headers={"Accept": "application/json"})
        cameras: List[Dict[str, Any]] = []
        seen: set[int] = set()
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            cam_id = row.get("id")
            if not isinstance(cam_id, int) or isinstance(cam_id, bool) or cam_id in seen:
                continue
            if row.get("is_on") is False or row.get("should_appear") is False or row.get("marked_stale"):
                continue
            coords_raw = (row.get("location") or {}).get("coordinates")
            if not isinstance(coords_raw, list) or len(coords_raw) < 2:
                continue
            coords = _lat_lon_in(coords_raw[1], coords_raw[0], self.BOUNDS)
            if not coords:
                continue
            seen.add(cam_id)
            title = str(row.get("caption") or row.get("name") or "").strip()
            cameras.append({
                "id": f"DRIVEBC-{cam_id}",
                "source_agency": "DriveBC",
                "lat": coords[0],
                "lon": coords[1],
                "direction_facing": (title or f"DriveBC camera {cam_id}")[:120],
                "media_url": self.IMAGE_URL.format(id=cam_id),
                "media_type": "image",
                "refresh_rate_seconds": 120,
            })
        logger.info("DriveBCIngestor: parsed %s cameras", len(cameras))
        return cameras


class TorontoRescuIngestor(BaseCCTVIngestor):
    """City of Toronto traffic cameras from the open-data portal (~340 stills)."""

    API_URL = ("https://ckan0.cf.opendata.inter.prod-toronto.ca/dataset/a3309088-5fd4-4d34-8297-77c8301840ac"
               "/resource/4a568300-c7f8-496d-b150-dff6f5dc6d4f/download/traffic-camera-list-4326.geojson")
    BOUNDS = (43.5, 43.9, -79.7, -79.0)
    _IMAGE = re.compile(r"https://opendata\.toronto\.ca/transportation/tmc/rescucameraimages/CameraImages/loc\d+\.jpg")

    def fetch_data(self) -> List[Dict[str, Any]]:
        data = _get_feed_json(self.API_URL, timeout=30, headers={"Accept": "application/geo+json,application/json"})
        features = data.get("features") if isinstance(data, dict) else None
        cameras: List[Dict[str, Any]] = []
        seen: set[int] = set()
        for feat in features if isinstance(features, list) else []:
            props = (feat.get("properties") if isinstance(feat, dict) else None) or {}
            rec_id = props.get("REC_ID")
            image = str(props.get("IMAGEURL") or "")
            if not isinstance(rec_id, int) or isinstance(rec_id, bool) or rec_id in seen:
                continue
            if not self._IMAGE.fullmatch(image):
                continue
            coords_raw = (feat.get("geometry") or {}).get("coordinates")
            if isinstance(coords_raw, list) and coords_raw and isinstance(coords_raw[0], list):
                coords_raw = coords_raw[0]  # MultiPoint with one point
            if not isinstance(coords_raw, list) or len(coords_raw) < 2:
                continue
            coords = _lat_lon_in(coords_raw[1], coords_raw[0], self.BOUNDS)
            if not coords:
                continue
            seen.add(rec_id)
            roads = " / ".join(r for r in (str(props.get("MAINROAD") or "").strip(),
                                           str(props.get("CROSSROAD") or "").strip()) if r)
            cameras.append({
                "id": f"TORONTO-{rec_id}",
                "source_agency": "City of Toronto",
                "lat": coords[0],
                "lon": coords[1],
                "direction_facing": (roads or f"Toronto camera {rec_id}")[:120],
                "media_url": image,
                "media_type": "image",
                "refresh_rate_seconds": 120,
            })
        logger.info("TorontoRescuIngestor: parsed %s cameras", len(cameras))
        return cameras


class OttawaTrafficIngestor(BaseCCTVIngestor):
    """City of Ottawa traffic cameras (~400 stills).

    The list also carries about 30 MTO highway cameras; 511 Ontario already
    supplies those, so only the city's own are taken.
    """

    API_URL = "https://traffic.ottawa.ca/beta/camera_list"
    IMAGE_URL = "https://traffic.ottawa.ca/map/camera?id={number}"
    BOUNDS = (44.9, 45.6, -76.4, -75.2)

    def fetch_data(self) -> List[Dict[str, Any]]:
        rows = _get_feed_json(self.API_URL, timeout=30, headers={"Accept": "application/json"})
        cameras: List[Dict[str, Any]] = []
        seen: set[int] = set()
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict) or str(row.get("type") or "").upper() != "CITY":
                continue
            number = row.get("number")
            if not isinstance(number, int) or isinstance(number, bool) or number in seen:
                continue
            coords = _lat_lon_in(row.get("latitude"), row.get("longitude"), self.BOUNDS)
            if not coords:
                continue
            seen.add(number)
            cameras.append({
                "id": f"OTTAWA-{number}",
                "source_agency": "City of Ottawa",
                "lat": coords[0],
                "lon": coords[1],
                "direction_facing": (str(row.get("description") or "").strip() or f"Ottawa camera {number}")[:120],
                "media_url": self.IMAGE_URL.format(number=number),
                "media_type": "image",
                "refresh_rate_seconds": 60,
            })
        logger.info("OttawaTrafficIngestor: parsed %s cameras", len(cameras))
        return cameras


class Quebec511Ingestor(BaseCCTVIngestor):
    """Québec 511 cameras from the Transports Québec WFS layer (~680).

    Each camera serves a short MP4 clip. The clip host answers 403 without a
    Québec 511 Referer, which the media proxy adds.
    """

    API_URL = ("https://ws.mapserver.transports.gouv.qc.ca/swtq?service=wfs&version=2.0.0&request=getfeature"
               "&typename=ms:infos_cameras&outfile=Camera&srsname=EPSG:4326&outputformat=geojson")
    CLIP_URL = "https://www.quebec511.info/Carte/Fenetres/camera.ashx?id={id}&format=mp4"
    BOUNDS = (44.9, 63.0, -80.0, -57.0)

    def fetch_data(self) -> List[Dict[str, Any]]:
        data = _get_feed_json(self.API_URL, timeout=30, headers={"Accept": "application/geo+json,application/json"})
        features = data.get("features") if isinstance(data, dict) else None
        cameras: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for feat in features if isinstance(features, list) else []:
            props = (feat.get("properties") if isinstance(feat, dict) else None) or {}
            cam_id = str(props.get("IDEcamera") or "").strip()
            if not re.fullmatch(r"\d{1,7}", cam_id) or cam_id in seen:
                continue
            coords_raw = (feat.get("geometry") or {}).get("coordinates")
            if not isinstance(coords_raw, list) or len(coords_raw) < 2:
                continue
            coords = _lat_lon_in(coords_raw[1], coords_raw[0], self.BOUNDS)
            if not coords:
                continue
            seen.add(cam_id)
            title = str(props.get("DescriptionLocalisationEn") or props.get("DescriptionLocalisationFr") or "").strip()
            cameras.append({
                "id": f"QC511-{cam_id}",
                "source_agency": "Québec 511",
                "lat": coords[0],
                "lon": coords[1],
                "direction_facing": (title or f"Québec 511 camera {cam_id}")[:120],
                "media_url": self.CLIP_URL.format(id=cam_id),
                "media_type": "video",
                "refresh_rate_seconds": 120,
            })
        logger.info("Quebec511Ingestor: parsed %s cameras", len(cameras))
        return cameras


class CalgaryTrafficIngestor(BaseCCTVIngestor):
    """City of Calgary traffic cameras from the open-data portal (~220 stills)."""

    API_URL = "https://data.calgary.ca/resource/k7p9-kppz.json?$limit=2000"
    BOUNDS = (50.8, 51.3, -114.4, -113.8)
    _IMAGE = re.compile(r"https://trafficcam\.calgary\.ca/loc(\d+)\.jpg")

    def fetch_data(self) -> List[Dict[str, Any]]:
        rows = _get_feed_json(self.API_URL, timeout=30, headers={"Accept": "application/json"})
        cameras: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            image = str((row.get("camera_url") or {}).get("url") or "").strip()
            match = self._IMAGE.fullmatch(image)
            if not match or match.group(1) in seen:
                continue
            coords_raw = (row.get("point") or {}).get("coordinates")
            if not isinstance(coords_raw, list) or len(coords_raw) < 2:
                continue
            coords = _lat_lon_in(coords_raw[1], coords_raw[0], self.BOUNDS)
            if not coords:
                continue
            seen.add(match.group(1))
            cameras.append({
                "id": f"YYC-{match.group(1)}",
                "source_agency": "City of Calgary",
                "lat": coords[0],
                "lon": coords[1],
                "direction_facing": (str(row.get("camera_location") or "").strip()
                                     or f"Calgary camera {match.group(1)}")[:120],
                "media_url": image,
                "media_type": "image",
                "refresh_rate_seconds": 60,
            })
        logger.info("CalgaryTrafficIngestor: parsed %s cameras", len(cameras))
        return cameras


class EstoniaTarkTeeIngestor(BaseCCTVIngestor):
    """Estonia's road-weather-station cameras (Transpordiamet, Tark Tee map, ~180).

    Each new picture gets a new file name (``94/94_202611190616.jpg``) about
    every ten minutes, so the link stored here is the newest picture at ingest
    time and is replaced on the next ingest cycle. A camera whose newest
    picture is over three hours old has stopped and is skipped.
    """

    API_URL = ("https://www.tarktee.ee/tarktee/rest/services/tram/road_cameras/MapServer/0/query"
               "?where=1%3D1&outFields=site_name,image_path,image_time&outSR=4326&f=json")
    IMAGE_BASE = "https://www.tarktee.ee/images/"
    BOUNDS = (57.4, 59.9, 21.6, 28.3)
    STALE_SECONDS = 3 * 3600
    _PATH = re.compile(r"([1-9]\d{0,5})/\1_\d{12}\.jpg")

    def fetch_data(self, now: float | None = None) -> List[Dict[str, Any]]:
        now_ms = (time.time() if now is None else now) * 1000
        data = _get_feed_json(self.API_URL, timeout=30, headers={"Accept": "application/json"})
        features = data.get("features") if isinstance(data, dict) else None
        cameras: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for feat in features if isinstance(features, list) else []:
            if not isinstance(feat, dict):
                continue
            attrs = feat.get("attributes") or {}
            match = self._PATH.fullmatch(str(attrs.get("image_path") or ""))
            if not match or match.group(1) in seen:
                continue
            taken = attrs.get("image_time")
            if not isinstance(taken, (int, float)) or now_ms - taken > self.STALE_SECONDS * 1000:
                continue
            geometry = feat.get("geometry") or {}
            coords = _lat_lon_in(geometry.get("y"), geometry.get("x"), self.BOUNDS)
            if not coords:
                continue
            seen.add(match.group(1))
            site = str(attrs.get("site_name") or "").strip()
            cameras.append({
                "id": f"EETARK-{match.group(1)}",
                "source_agency": "Estonia Transpordiamet",
                "lat": coords[0],
                "lon": coords[1],
                "direction_facing": (f"{site} road camera" if site else f"Estonia camera {match.group(1)}")[:120],
                "media_url": self.IMAGE_BASE + match.group(0),
                "media_type": "image",
                "refresh_rate_seconds": 600,
            })
        logger.info("EstoniaTarkTeeIngestor: parsed %s cameras", len(cameras))
        return cameras


def _detect_media_type(url: str) -> str:
    """Detect the media type from a camera URL for proper frontend rendering."""
    if not url:
        return "image"
    url_lower = url.lower()
    if any(ext in url_lower for ext in [".mp4", ".webm", ".ogg"]):
        return "video"
    if any(kw in url_lower for kw in [".mjpg", ".mjpeg", "mjpg", "axis-cgi/mjpg", "mode=motion"]):
        return "mjpeg"
    if ".m3u8" in url_lower or "hls" in url_lower:
        return "hls"
    if any(kw in url_lower for kw in ["embed", "maps/embed", "iframe"]):
        return "embed"
    if "mapbox.com" in url_lower or "satellite" in url_lower:
        return "satellite"
    return "image"


def scheduled_cctv_ingestors() -> List[tuple["BaseCCTVIngestor", str]]:
    """Canonical list of CCTV ingestors for startup, scheduler, and DB seeding."""
    return [
        (TFLJamCamIngestor(), "cctv_tfl"),
        (LTASingaporeIngestor(), "cctv_lta"),
        (AustinTXIngestor(), "cctv_atx"),
        (NYCDOTIngestor(), "cctv_nyc"),
        (CaltransIngestor(), "cctv_caltrans"),
        (ColoradoDOTIngestor(), "cctv_codot"),
        (WSDOTIngestor(), "cctv_wsdot"),
        (GeorgiaDOTIngestor(), "cctv_gdot"),
        (IllinoisDOTIngestor(), "cctv_idot"),
        (MichiganDOTIngestor(), "cctv_mdot"),
        (WindyWebcamsIngestor(), "cctv_windy"),
        (DGTNationalIngestor(), "cctv_dgt"),
        (MadridCityIngestor(), "cctv_madrid"),
        (OSMTrafficCameraIngestor(), "cctv_osm"),
        (AsfinagIngestor(), "cctv_asfinag"),
        (OSMALPRCameraIngestor(), "cctv_osm_alpr"),
        (Ontario511Ingestor(), "cctv_on511"),
        (Alberta511Ingestor(), "cctv_ab511"),
        (Florida511Ingestor(), "cctv_fl511"),
        (AustraliaLiveTrafficIngestor(), "cctv_australia"),
        (NetherlandsRWSIngestor(), "cctv_nl_rws"),
        *[
            (IBI511Ingestor(base, prefix, agency), key)
            for key, base, prefix, agency in IBI511_SITES
        ],
        (MarylandCHARTIngestor(), "cctv_md_chart"),
        (IterisCamerasIngestor(
            "https://511.vdot.virginia.gov/services/511/map/layers/map/cams",
            "VDOT", "Virginia VDOT", "vdotcameras.com", (36.4, 39.6, -83.8, -75.1),
        ), "cctv_va_vdot"),
        (IterisCamerasIngestor(
            "https://sc.cdn.iteris-atis.com/geojson/icons/metadata/icons.cameras.geojson",
            "SCDOT", "South Carolina SCDOT", "skyvdn.com", (31.9, 35.3, -83.5, -78.4),
        ), "cctv_sc_scdot"),
        (DelDOTIngestor(), "cctv_de_deldot"),
        (TxDOTIngestor(), "cctv_txdot"),
        *[
            (CARS511Ingestor(base, prefix, agency, bounds), key)
            for key, base, prefix, agency, bounds in CARS511_SITES
        ],
        (FintrafficWeathercamIngestor(), "cctv_fintraffic"),
        (HongKongTDIngestor(), "cctv_hk_td"),
        (QueenslandTrafficIngestor(), "cctv_qld"),
        (NZTAIngestor(), "cctv_nzta"),
        (IBI511Ingestor("https://www.drivenc.gov", "NCDOT", "NCDOT DriveNC", query_in_url=True), "cctv_nc511"),
        (IcelandVegagerdinIngestor(), "cctv_is_vegagerdin"),
        (TaiwanTHBIngestor(), "cctv_tw_thb"),
        (LithuaniaViaLietuvaIngestor(), "cctv_lt_via"),
        (BizkaiaTrafficIngestor(), "cctv_bizkaia"),
        (DIRCentreEstIngestor(), "cctv_fr_dirce"),
        (DIREstIngestor(), "cctv_fr_direst"),
        (LyonCriterIngestor(), "cctv_fr_lyon"),
        *[
            (InforouteIngestor(host, prefix, department, files), key)
            for key, host, prefix, department, files in INFOROUTE_SITES
        ],
        (APRRIngestor(), "cctv_fr_aprr"),
        (AutostradeIngestor(), "cctv_it_aspi"),
        (EdmontonTrafficIngestor(), "cctv_yeg"),
        (OregonTripCheckIngestor(), "cctv_or_tripcheck"),
        (Minnesota511xIngestor(), "cctv_mn511"),
        (DriveBCIngestor(), "cctv_drivebc"),
        (TorontoRescuIngestor(), "cctv_toronto"),
        (OttawaTrafficIngestor(), "cctv_ottawa"),
        (Quebec511Ingestor(), "cctv_qc511"),
        (CalgaryTrafficIngestor(), "cctv_yyc"),
        (EstoniaTarkTeeIngestor(), "cctv_ee_tarktee"),
    ]


def run_all_ingestors():
    """Run all CCTV ingestors synchronously. Used for first-run DB seeding."""
    for ingestor, _name in scheduled_cctv_ingestors():
        try:
            ingestor.ingest()
        except Exception as e:
            logger.warning(f"Ingestor {ingestor.__class__.__name__} failed during seed: {e}")


# Columns the map / live-data path actually needs — skip refresh_rate / timestamps.
_CAMERA_SELECT_COLS = (
    "id",
    "source_agency",
    "lat",
    "lon",
    "direction_facing",
    "media_url",
    "media_type",
)


def get_camera_count() -> int:
    """Cheap total for UI badges without loading the full table."""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        row = conn.execute("SELECT COUNT(*) FROM cameras").fetchone()
        return int(row[0] if row else 0)
    finally:
        conn.close()


def get_all_cameras(
    *,
    south: float | None = None,
    west: float | None = None,
    north: float | None = None,
    east: float | None = None,
) -> List[Dict[str, Any]]:
    """Load map-facing camera rows (full catalog; viewport args ignored)."""
    cols = ", ".join(_CAMERA_SELECT_COLS)
    sql = f"SELECT {cols} FROM cameras"

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(sql).fetchall()
    finally:
        conn.close()

    cameras = []
    for row in rows:
        cam = {k: row[k] for k in _CAMERA_SELECT_COLS}
        cam["media_type"] = str(
            cam.get("media_type") or _detect_media_type(cam.get("media_url", "")) or "image"
        )
        cameras.append(cam)
    return cameras
