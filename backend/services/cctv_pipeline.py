import os
import sqlite3
import requests
import re
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
                        cam.get("media_url"),
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

    URL = "https://511ga.org/List/GetData/Cameras"
    BASE_URL = "https://511ga.org"
    PAGE_SIZE = 500

    def fetch_data(self) -> List[Dict[str, Any]]:
        cameras = []
        start = 0
        draw = 1
        while True:
            resp = fetch_with_curl(
                self.URL,
                method="POST",
                json_data={"draw": draw, "start": start, "length": self.PAGE_SIZE},
                timeout=30,
                headers={
                    "Accept": "application/json",
                    "Referer": "https://511ga.org/cctv",
                    "Origin": "https://511ga.org",
                },
            )
            if not resp or resp.status_code != 200:
                logger.error(
                    "Georgia CCTV fetch failed: HTTP %s",
                    resp.status_code if resp else "no response",
                )
                break
            data = resp.json()
            rows = data.get("data") or []
            if not rows:
                break
            for row in rows:
                site_id = row.get("id") or row.get("DT_RowId")
                location = row.get("location") or row.get("roadway") or "GA Camera"
                lat_lng = row.get("latLng") or {}
                geography = lat_lng.get("geography") if isinstance(lat_lng, dict) else {}
                lat, lon = _parse_wkt_point(geography.get("wellKnownText") if isinstance(geography, dict) else "")
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
                media_url = _normalize_cctv_media_url(
                    urljoin(self.BASE_URL, str(image.get("imageUrl") or "").strip())
                )
                cameras.append(
                    {
                        "id": f"GDOT-{site_id}",
                        "source_agency": "Georgia DOT",
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
            if not total and len(rows) < self.PAGE_SIZE:
                break
        return cameras


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
# DGT Spain — National Road Cameras
# ---------------------------------------------------------------------------
# Image URL pattern confirmed working: infocar.dgt.es/etraffic/data/camaras/{id}.jpg
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

    def fetch_data(self) -> List[Dict[str, Any]]:
        cameras = []
        probe_headers = {
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Referer": "https://infocar.dgt.es/",
        }
        for cam_id, lat, lon, description in self.KNOWN_CAMERAS:
            media_url = f"https://infocar.dgt.es/etraffic/data/camaras/{cam_id}.jpg"
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
    import xml.etree.ElementTree as ET
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


class MadridCityIngestor(BaseCCTVIngestor):
    """Madrid City Hall traffic cameras from datos.madrid.es KML feed."""

    KML_URL = "http://datos.madrid.es/egob/catalogo/202088-0-trafico-camaras.kml"

    def fetch_data(self) -> List[Dict[str, Any]]:
        import xml.etree.ElementTree as ET

        try:
            response = fetch_with_curl(self.KML_URL, timeout=20)
            response.raise_for_status()
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


def run_all_ingestors():
    """Run all CCTV ingestors synchronously. Used for first-run DB seeding."""
    ingestors = [
        TFLJamCamIngestor(),
        LTASingaporeIngestor(),
        AustinTXIngestor(),
        NYCDOTIngestor(),
        CaltransIngestor(),
        ColoradoDOTIngestor(),
        WSDOTIngestor(),
        GeorgiaDOTIngestor(),
        IllinoisDOTIngestor(),
        MichiganDOTIngestor(),
        WindyWebcamsIngestor(),
        OSMTrafficCameraIngestor(),
        DGTNationalIngestor(),
        MadridCityIngestor(),
    ]
    for ing in ingestors:
        try:
            ing.ingest()
        except Exception as e:
            logger.warning(f"Ingestor {ing.__class__.__name__} failed during seed: {e}")


def get_all_cameras() -> List[Dict[str, Any]]:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM cameras")
    rows = cursor.fetchall()
    conn.close()
    cameras = []
    for row in rows:
        cam = dict(row)
        cam["media_type"] = str(cam.get("media_type") or _detect_media_type(cam.get("media_url", "")) or "image")
        cameras.append(cam)
    return cameras
