import sqlite3
import requests
from services.network_utils import fetch_with_curl
import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

DB_PATH = "cctv.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
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
    conn.close()

class BaseCCTVIngestor(ABC):
    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH)

    @abstractmethod
    def fetch_data(self) -> List[Dict[str, Any]]:
        pass

    def ingest(self):
        try:
            cameras = self.fetch_data()
            cursor = self.conn.cursor()
            for cam in cameras:
                cursor.execute("""
                    INSERT INTO cameras 
                    (id, source_agency, lat, lon, direction_facing, media_url, refresh_rate_seconds)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                    media_url=excluded.media_url,
                    last_updated=CURRENT_TIMESTAMP
                """, (
                    cam.get("id"),
                    cam.get("source_agency"),
                    cam.get("lat"),
                    cam.get("lon"),
                    cam.get("direction_facing", "Unknown"),
                    cam.get("media_url"),
                    cam.get("refresh_rate_seconds", 60)
                ))
            self.conn.commit()
            logger.info(f"Successfully ingested {len(cameras)} cameras from {self.__class__.__name__}")
        except Exception as e:
            logger.error(f"Failed to ingest cameras in {self.__class__.__name__}: {e}")

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
            
            for prop in item.get('additionalProperties', []):
                if prop.get('key') == 'videoUrl':
                    vid_url = prop.get('value')
                elif prop.get('key') == 'imageUrl':
                    img_url = prop.get('value')
            
            media = vid_url if vid_url else img_url
            if media:
                cameras.append({
                    "id": f"TFL-{item.get('id')}",
                    "source_agency": "TfL",
                    "lat": item.get('lat'),
                    "lon": item.get('lon'),
                    "direction_facing": item.get('commonName', 'Unknown'),
                    "media_url": media,
                    "refresh_rate_seconds": 15
                })
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
                    cameras.append({
                        "id": f"SGP-{item.get('camera_id', 'UNK')}",
                        "source_agency": "Singapore LTA",
                        "lat": loc.get("latitude"),
                        "lon": loc.get("longitude"),
                        "direction_facing": f"Camera {item.get('camera_id')}",
                        "media_url": item.get("image"),
                        "refresh_rate_seconds": 60
                    })
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
            if not cam_id: continue
            
            loc = item.get("location", {})
            coords = loc.get("coordinates", [])
            
            # coords is usually [lon, lat]
            if len(coords) == 2:
                cameras.append({
                    "id": f"ATX-{cam_id}",
                    "source_agency": "Austin TxDOT",
                    "lat": coords[1],
                    "lon": coords[0],
                    "direction_facing": item.get("location_name", "Austin TX Camera"),
                    "media_url": f"https://cctv.austinmobility.io/image/{cam_id}.jpg",
                    "refresh_rate_seconds": 60
                })
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
            if not cam_id: continue
            
            lat = item.get("latitude")
            lon = item.get("longitude")
            if lat and lon:
                cameras.append({
                    "id": f"NYC-{cam_id}",
                    "source_agency": "NYC DOT",
                    "lat": lat,
                    "lon": lon,
                    "direction_facing": item.get("name", "NYC Camera"),
                    "media_url": f"https://webcams.nyctmc.org/api/cameras/{cam_id}/image",
                    "refresh_rate_seconds": 30
                })
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
            ("39.6,-105.1,39.9,-104.8", "Denver")
        ]
        
        query_parts = [f'node["man_made"="surveillance"]({bbox});' for bbox, city in regions]
        query = "".join(query_parts)
        url = f"https://overpass-api.de/api/interpreter?data=[out:json];({query});out%202000;"
        
        try:
            response = fetch_with_curl(url, timeout=15)
            response.raise_for_status()
            data = response.json()
            
            cameras = []
            for item in data.get('elements', []):
                lat = item.get("lat")
                lon = item.get("lon")
                cam_id = item.get("id")
                
                if lat and lon:
                    # Find which city this belongs to
                    source_city = "Global OSINT"
                    for bbox, city in regions:
                        s, w, n, e = map(float, bbox.split(','))
                        if s <= lat <= n and w <= lon <= e:
                            source_city = f"OSINT: {city}"
                            break
                            
                    # Attempt to parse camera direction for a cool realistic bearing angle if OSM mapped it
                    direction_str = item.get("tags", {}).get("camera:direction", "0")
                    try:
                        bearing = int(float(direction_str))
                    except:
                        bearing = 0
                        
                    mapbox_key = "YOUR_MAPBOX_TOKEN_HERE"
                    mapbox_url = f"https://api.mapbox.com/styles/v1/mapbox/satellite-streets-v12/static/{lon},{lat},18,{bearing},60/600x400?access_token={mapbox_key}"
                    
                    cameras.append({
                        "id": f"OSM-{cam_id}",
                        "source_agency": source_city,
                        "lat": lat,
                        "lon": lon,
                        "direction_facing": item.get("tags", {}).get("surveillance:type", "Street Level Camera"),
                        "media_url": mapbox_url,
                        "refresh_rate_seconds": 3600
                    })
            return cameras
        except Exception:
            return []



def _detect_media_type(url: str) -> str:
    """Detect the media type from a camera URL for proper frontend rendering."""
    if not url:
        return "image"
    url_lower = url.lower()
    if any(ext in url_lower for ext in ['.mp4', '.webm', '.ogg']):
        return "video"
    if any(kw in url_lower for kw in ['.mjpg', '.mjpeg', 'mjpg', 'axis-cgi/mjpg', 'mode=motion']):
        return "mjpeg"
    if '.m3u8' in url_lower or 'hls' in url_lower:
        return "hls"
    if any(kw in url_lower for kw in ['embed', 'maps/embed', 'iframe']):
        return "embed"
    if 'mapbox.com' in url_lower or 'satellite' in url_lower:
        return "satellite"
    return "image"

def get_all_cameras() -> List[Dict[str, Any]]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM cameras")
    rows = cursor.fetchall()
    conn.close()
    cameras = []
    for row in rows:
        cam = dict(row)
        cam['media_type'] = _detect_media_type(cam.get('media_url', ''))
        cameras.append(cam)
    return cameras

