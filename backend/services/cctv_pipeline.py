import logging
import re
import sqlite3
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List

from services.network_utils import fetch_with_curl

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "cctv.db"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(str(DB_PATH))


def init_db():
    conn = _connect()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cameras (
                id TEXT PRIMARY KEY,
                source_agency TEXT,
                lat REAL,
                lon REAL,
                direction_facing TEXT,
                media_url TEXT,
                refresh_rate_seconds INTEGER,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    finally:
        conn.close()


class BaseCCTVIngestor(ABC):
    @abstractmethod
    def fetch_data(self) -> List[Dict[str, Any]]:
        pass

    def ingest(self):
        conn = None
        try:
            init_db()
            cameras = self.fetch_data()
            conn = _connect()
            cursor = conn.cursor()
            for cam in cameras:
                cursor.execute(
                    """
                    INSERT INTO cameras
                    (id, source_agency, lat, lon, direction_facing, media_url, refresh_rate_seconds)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                    media_url=excluded.media_url,
                    last_updated=CURRENT_TIMESTAMP
                """,
                    (
                        cam.get("id"),
                        cam.get("source_agency"),
                        cam.get("lat"),
                        cam.get("lon"),
                        cam.get("direction_facing", "Unknown"),
                        cam.get("media_url"),
                        cam.get("refresh_rate_seconds", 60),
                    ),
                )
            conn.commit()
            logger.info(
                f"Successfully ingested {len(cameras)} cameras from {self.__class__.__name__}"
            )
        except Exception as e:
            try:
                if conn is not None:
                    conn.rollback()
            except Exception:
                pass
            logger.error(f"Failed to ingest cameras in {self.__class__.__name__}: {e}")
        finally:
            if conn is not None:
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

            loc = item.get("location", {})
            coords = loc.get("coordinates", [])

            # coords is usually [lon, lat]
            if len(coords) == 2:
                cameras.append(
                    {
                        "id": f"ATX-{cam_id}",
                        "source_agency": "Austin TxDOT",
                        "lat": coords[1],
                        "lon": coords[0],
                        "direction_facing": item.get(
                            "location_name", "Austin TX Camera"
                        ),
                        "media_url": f"https://cctv.austinmobility.io/image/{cam_id}.jpg",
                        "refresh_rate_seconds": 60,
                    }
                )
        return cameras


class NYCDOTIngestor(BaseCCTVIngestor):
    """Updated NYC DOT Traffic Cameras (2026)"""
    
    def fetch_data(self) -> List[Dict[str, Any]]:
        # Newer public endpoint for NYC traffic cameras
        url = "https://data.cityofnewyork.us/resource/5rzb-5w4u.json?$limit=5000"
        
        try:
            response = fetch_with_curl(url, timeout=20)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            logger.error(f"NYCDOTIngestor: failed to fetch data: {e}")
            return []

        cameras = []
        for item in data:
            cam_id = item.get("id") or item.get("camera_id")
            if not cam_id:
                continue

            lat = item.get("latitude") or item.get("lat")
            lon = item.get("longitude") or item.get("lon")
            if not lat or not lon:
                continue

            # NYC uses a different image endpoint now
            media_url = f"https://webcams.nyctmc.org/api/cameras/{cam_id}/image"
            # Alternative fallback image URL (sometimes more stable)
            # media_url = f"https://nyc3.digitaloceanspaces.com/traffic-cameras/{cam_id}.jpg"

            name = item.get("name") or item.get("location") or f"NYC Camera {cam_id}"

            cameras.append({
                "id": f"NYC-{cam_id}",
                "source_agency": "NYC DOT",
                "lat": float(lat),
                "lon": float(lon),
                "direction_facing": name,
                "media_url": media_url,
                "refresh_rate_seconds": 30,
            })

        logger.info(f"NYCDOTIngestor: parsed {len(cameras)} cameras")
        return cameras


class GlobalOSMCrawlingIngestor(BaseCCTVIngestor):
    def fetch_data(self) -> List[Dict[str, Any]]:
        # This will pull physical street surveillance cameras across all global hotspots
        # using OpenStreetMap Overpass mapping their exact geospatial coordinates to Google Street View
        regions = [
            ("35.6,139.6,35.8,139.8", "Tokyo"),
            ("48.8,2.3,48.9,2.4", "Paris"),
            ("40.6,-74.1,40.8,-73.9", "NYC Expanded"),
            ("34.0,-118.4,34.2,-118.2", "Los Angeles"),
            ("-33.9,151.1,-33.7,151.3", "Sydney"),
            ("52.4,13.3,52.6,13.5", "Berlin"),
            ("25.1,55.2,25.3,55.4", "Dubai"),
            ("19.3,-99.2,19.5,-99.0", "Mexico City"),
            ("-23.6,-46.7,-23.4,-46.5", "Sao Paulo"),
            ("39.6,-105.1,39.9,-104.8", "Denver"),
        ]

        query_parts = [
            f'node["man_made"="surveillance"]({bbox});' for bbox, city in regions
        ]
        query = "".join(query_parts)
        url = f"https://overpass-api.de/api/interpreter?data=[out:json];({query});out%202000;"

        try:
            response = fetch_with_curl(url, timeout=15)
            response.raise_for_status()
            data = response.json()

            cameras = []
            for item in data.get("elements", []):
                lat = item.get("lat")
                lon = item.get("lon")
                cam_id = item.get("id")

                if lat and lon:
                    # Find which city this belongs to
                    source_city = "Global OSINT"
                    for bbox, city in regions:
                        s, w, n, e = map(float, bbox.split(","))
                        if s <= lat <= n and w <= lon <= e:
                            source_city = f"OSINT: {city}"
                            break

                    # Attempt to parse camera direction for a cool realistic bearing angle if OSM mapped it
                    direction_str = item.get("tags", {}).get("camera:direction", "0")
                    try:
                        bearing = int(float(direction_str))
                    except (ValueError, TypeError):
                        bearing = 0

                    mapbox_key = "YOUR_MAPBOX_TOKEN_HERE"
                    mapbox_url = f"https://api.mapbox.com/styles/v1/mapbox/satellite-streets-v12/static/{lon},{lat},18,{bearing},60/600x400?access_token={mapbox_key}"

                    cameras.append(
                        {
                            "id": f"OSM-{cam_id}",
                            "source_agency": source_city,
                            "lat": lat,
                            "lon": lon,
                            "direction_facing": item.get("tags", {}).get(
                                "surveillance:type", "Street Level Camera"
                            ),
                            "media_url": mapbox_url,
                            "refresh_rate_seconds": 3600,
                        }
                    )
            return cameras
        except Exception:
            return []


# ---------------------------------------------------------------------------
# Spain — DGT National Roads (DATEX2 XML, ~1,900 cameras)
# ---------------------------------------------------------------------------
class SpainDGTIngestor(BaseCCTVIngestor):
    # Dirección General de Tráfico — national road cameras via DATEX2 v3 XML.
    # No API key required. Covers all national roads (autopistas, autovías, N-roads)
    # EXCEPT Basque Country and Catalonia.
    # Published under Spain's open data framework (Ley 37/2007, EU PSI Directive 2019/1024).
    DGT_URL = "https://nap.dgt.es/datex2/v3/dgt/DevicePublication/camaras_datex2_v36.xml"

    def fetch_data(self) -> List[Dict[str, Any]]:
        try:
            response = fetch_with_curl(self.DGT_URL, timeout=30)
            response.raise_for_status()
        except Exception as e:
            logger.error(f"SpainDGTIngestor: failed to fetch DATEX2 XML: {e}")
            return []

        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as e:
            logger.error(f"SpainDGTIngestor: failed to parse XML: {e}")
            return []

        cameras = []
        # DGT DATEX2 v3 uses <ns2:device> elements with typeOfDevice=camera.
        # Namespace-agnostic: match local name "device".
        for el in root.iter():
            local = el.tag.split("}")[-1] if "}" in el.tag else el.tag
            if local != "device":
                continue

            try:
                cam_id = el.get("id", "")
                if not cam_id:
                    continue

                # Coordinates are nested: pointLocation > ... > pointCoordinates > latitude/longitude
                lat = self._find_text(el, "latitude")
                lon = self._find_text(el, "longitude")
                if not lat or not lon:
                    continue

                image_url = self._find_text(el, "deviceUrl") or f"https://infocar.dgt.es/etraffic/data/camaras/{cam_id}.jpg"

                road_name = self._find_text(el, "roadName") or ""
                road_dest = self._find_text(el, "roadDestination") or ""
                description = f"{road_name} → {road_dest}".strip(" →") or f"DGT Camera {cam_id}"

                cameras.append({
                    "id": f"DGT-{cam_id}",
                    "source_agency": "DGT Spain",
                    "lat": float(lat),
                    "lon": float(lon),
                    "direction_facing": description,
                    "media_url": image_url,
                    "refresh_rate_seconds": 300,
                })
            except (ValueError, TypeError) as e:
                logger.debug(f"SpainDGTIngestor: skipping malformed record: {e}")
                continue

        logger.info(f"SpainDGTIngestor: parsed {len(cameras)} cameras")
        return cameras

    @staticmethod
    def _find_text(element: ET.Element, tag: str) -> str | None:
        for child in element.iter():
            local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if local.lower() == tag.lower() and child.text:
                return child.text.strip()
        return None


# ---------------------------------------------------------------------------
# Spain — Madrid City Hall (KML, ~200 cameras)
# ---------------------------------------------------------------------------
class MadridCCTVIngestor(BaseCCTVIngestor):
    # Madrid City Hall urban traffic cameras via open data KML.
    # No API key required. Published on datos.madrid.es.
    # Licence: Madrid Open Data (free reuse with attribution).
    MADRID_URL = "http://datos.madrid.es/egob/catalogo/202088-0-trafico-camaras.kml"

    def fetch_data(self) -> List[Dict[str, Any]]:
        try:
            response = fetch_with_curl(self.MADRID_URL, timeout=20)
            response.raise_for_status()
        except Exception as e:
            logger.error(f"MadridCCTVIngestor: failed to fetch KML: {e}")
            return []

        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as e:
            logger.error(f"MadridCCTVIngestor: failed to parse KML: {e}")
            return []

        cameras = []
        # KML namespace varies — try both common ones, then fall back to tag-name search
        placemarks = root.findall(".//{http://www.opengis.net/kml/2.2}Placemark")
        if not placemarks:
            placemarks = root.findall(".//{http://earth.google.com/kml/2.2}Placemark")
        if not placemarks:
            placemarks = [el for el in root.iter() if el.tag.endswith("Placemark")]

        for i, pm in enumerate(placemarks):
            try:
                name = self._find_kml_text(pm, "name") or f"Madrid Camera {i}"
                coords_text = self._find_kml_text(pm, "coordinates")
                if not coords_text:
                    continue

                # KML coordinates: lon,lat,elevation
                parts = coords_text.strip().split(",")
                if len(parts) < 2:
                    continue
                lon, lat = float(parts[0]), float(parts[1])

                # Extract image URL from description CDATA
                desc = self._find_kml_text(pm, "description") or ""
                image_url = self._extract_img_src(desc)
                if not image_url:
                    continue

                cameras.append({
                    "id": f"MAD-{i:04d}",
                    "source_agency": "Madrid City Hall",
                    "lat": lat,
                    "lon": lon,
                    "direction_facing": name,
                    "media_url": image_url,
                    "refresh_rate_seconds": 600,
                })
            except (ValueError, TypeError, IndexError) as e:
                logger.debug(f"MadridCCTVIngestor: skipping malformed placemark: {e}")
                continue

        logger.info(f"MadridCCTVIngestor: parsed {len(cameras)} cameras")
        return cameras

    @staticmethod
    def _find_kml_text(element: ET.Element, tag: str) -> str | None:
        for child in element.iter():
            local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if local == tag and child.text:
                return child.text.strip()
        return None

    @staticmethod
    def _extract_img_src(html_fragment: str) -> str | None:
        match = re.search(r'src=["\']([^"\']+)["\']', html_fragment, re.IGNORECASE)
        if match:
            return match.group(1)
        match = re.search(r'https?://\S+\.jpg', html_fragment, re.IGNORECASE)
        if match:
            return match.group(0)
        return None


# ---------------------------------------------------------------------------
# Spain — Málaga (GeoJSON, ~134 cameras)
# ---------------------------------------------------------------------------
class MalagaCCTVIngestor(BaseCCTVIngestor):
    # Málaga open data — traffic cameras in EPSG:4326 GeoJSON.
    # No API key required. Published on datosabiertos.malaga.eu.
    MALAGA_URL = "https://datosabiertos.malaga.eu/recursos/transporte/trafico/da_camarasTrafico-4326.geojson"

    def fetch_data(self) -> List[Dict[str, Any]]:
        try:
            response = fetch_with_curl(self.MALAGA_URL, timeout=15)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            logger.error(f"MalagaCCTVIngestor: failed to fetch GeoJSON: {e}")
            return []

        cameras = []
        for feature in data.get("features", []):
            try:
                props = feature.get("properties", {})
                geom = feature.get("geometry", {})
                coords = geom.get("coordinates", [])
                if len(coords) < 2:
                    continue

                image_url = props.get("URLIMAGEN") or props.get("urlimagen")
                if not image_url:
                    continue

                cam_id = props.get("NOMBRE") or props.get("nombre") or str(coords)
                description = props.get("DESCRIPCION") or props.get("descripcion") or cam_id

                cameras.append({
                    "id": f"MLG-{cam_id}",
                    "source_agency": "Málaga City",
                    "lat": float(coords[1]),
                    "lon": float(coords[0]),
                    "direction_facing": description,
                    "media_url": image_url,
                    "refresh_rate_seconds": 300,
                })
            except (ValueError, TypeError, IndexError) as e:
                logger.debug(f"MalagaCCTVIngestor: skipping malformed feature: {e}")
                continue

        logger.info(f"MalagaCCTVIngestor: parsed {len(cameras)} cameras")
        return cameras


# ---------------------------------------------------------------------------
# Spain — Vigo (GeoJSON, ~59 cameras)
# ---------------------------------------------------------------------------
class VigoCCTVIngestor(BaseCCTVIngestor):
    # Vigo open data — traffic cameras in GeoJSON.
    # No API key required. Published on datos.vigo.org.
    VIGO_URL = "https://datos.vigo.org/data/trafico/camaras-trafico.geojson"

    def fetch_data(self) -> List[Dict[str, Any]]:
        try:
            response = fetch_with_curl(self.VIGO_URL, timeout=15)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            logger.error(f"VigoCCTVIngestor: failed to fetch GeoJSON: {e}")
            return []

        cameras = []
        for feature in data.get("features", []):
            try:
                props = feature.get("properties", {})
                geom = feature.get("geometry", {})
                coords = geom.get("coordinates", [])
                if len(coords) < 2:
                    continue

                # Vigo uses PHP image endpoints
                image_url = props.get("urlimagen") or props.get("URLIMAGEN") or props.get("url")
                if not image_url:
                    continue

                cam_id = props.get("id") or props.get("nombre") or str(coords)
                description = props.get("nombre") or props.get("descripcion") or f"Vigo Camera {cam_id}"

                cameras.append({
                    "id": f"VGO-{cam_id}",
                    "source_agency": "Vigo City",
                    "lat": float(coords[1]),
                    "lon": float(coords[0]),
                    "direction_facing": description,
                    "media_url": image_url,
                    "refresh_rate_seconds": 300,
                })
            except (ValueError, TypeError, IndexError) as e:
                logger.debug(f"VigoCCTVIngestor: skipping malformed feature: {e}")
                continue

        logger.info(f"VigoCCTVIngestor: parsed {len(cameras)} cameras")
        return cameras


# ---------------------------------------------------------------------------
# Spain — Vitoria-Gasteiz (GeoJSON, ~17 cameras)
# ---------------------------------------------------------------------------
class VitoriaGasteizCCTVIngestor(BaseCCTVIngestor):
    # Vitoria-Gasteiz municipal traffic cameras in GeoJSON.
    # No API key required. Published on vitoria-gasteiz.org.
    VITORIA_URL = "https://www.vitoria-gasteiz.org/c11-01w/cameras?action=list&format=GEOJSON"

    def fetch_data(self) -> List[Dict[str, Any]]:
        try:
            response = fetch_with_curl(self.VITORIA_URL, timeout=15)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            logger.error(f"VitoriaGasteizCCTVIngestor: failed to fetch GeoJSON: {e}")
            return []

        cameras = []
        for feature in data.get("features", []):
            try:
                props = feature.get("properties", {})
                geom = feature.get("geometry", {})
                coords = geom.get("coordinates", [])
                if len(coords) < 2:
                    continue

                image_url = props.get("imagen") or props.get("url")
                if not image_url:
                    continue

                cam_id = props.get("id") or props.get("nombre") or str(coords)
                description = props.get("nombre") or props.get("descripcion") or f"Vitoria Camera {cam_id}"

                cameras.append({
                    "id": f"VIT-{cam_id}",
                    "source_agency": "Vitoria-Gasteiz",
                    "lat": float(coords[1]),
                    "lon": float(coords[0]),
                    "direction_facing": description,
                    "media_url": image_url,
                    "refresh_rate_seconds": 300,
                })
            except (ValueError, TypeError, IndexError) as e:
                logger.debug(f"VitoriaGasteizCCTVIngestor: skipping malformed feature: {e}")
                continue

        logger.info(f"VitoriaGasteizCCTVIngestor: parsed {len(cameras)} cameras")
        return cameras


def _detect_media_type(url: str) -> str:
    """Detect the media type from a camera URL for proper frontend rendering."""
    if not url:
        return "image"
    url_lower = url.lower()
    if any(ext in url_lower for ext in [".mp4", ".webm", ".ogg"]):
        return "video"
    if any(
        kw in url_lower
        for kw in [".mjpg", ".mjpeg", "mjpg", "axis-cgi/mjpg", "mode=motion"]
    ):
        return "mjpeg"
    if ".m3u8" in url_lower or "hls" in url_lower:
        return "hls"
    if any(kw in url_lower for kw in ["embed", "maps/embed", "iframe"]):
        return "embed"
    if "mapbox.com" in url_lower or "satellite" in url_lower:
        return "satellite"
    return "image"


def get_all_cameras() -> List[Dict[str, Any]]:
    init_db()
    conn = _connect()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM cameras")
    rows = cursor.fetchall()
    conn.close()
    cameras = []
    for row in rows:
        cam = dict(row)
        cam["media_type"] = _detect_media_type(cam.get("media_url", ""))
        cameras.append(cam)
    return cameras
