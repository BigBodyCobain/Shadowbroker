"""Run Sentinel-2 road-corridor truck trend analysis for a bbox preset."""
from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any

from .config import CACHE_DIR, DEFAULT_MAX_FRAMES, DEFAULT_MONTHS, DETECTION_CROP_DIR
from .storage import store_analysis_result

logger = logging.getLogger(__name__)

ProgressCb = Callable[[str, int | None], None]

_EVALSCRIPT = """//VERSION=3
function setup() {
  return {
    input: ["B02", "B03", "B04", "B08", "CLM"],
    output: { id: "default", bands: 5, sampleType: "FLOAT32" }
  };
}
function evaluatePixel(s) {
  return [s.B04, s.B03, s.B02, s.B08, s.CLM];
}"""


def _noop_progress(_msg: str, _pct: int | None = None) -> None:
    return None


def analyze_corridor(
    *,
    preset_id: str,
    label: str,
    bbox: list[float],
    country: str = "",
    category: str = "",
    months: int = DEFAULT_MONTHS,
    max_frames: int = DEFAULT_MAX_FRAMES,
    progress_cb: ProgressCb | None = None,
) -> dict[str, Any]:
    """Synchronously analyze one corridor bbox and persist daily truck-count trends."""
    from rasterio import features as rio_features
    from rasterio import transform as rio_transform
    from sentinelhub import BBox, CRS, DataCollection, MimeType, SentinelHubCatalog, SentinelHubRequest

    from .credentials import build_sh_config
    from .s2_truck_detect import S2TruckEngine

    progress = progress_cb or _noop_progress
    min_lat, min_lon, max_lat, max_lon = bbox
    if abs(max_lat - min_lat) > 0.5 or abs(max_lon - min_lon) > 0.5:
        raise ValueError("AOI too large. Max strategic sector is ~55 km x 55 km.")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    engine = S2TruckEngine(
        cache_dir=str(CACHE_DIR),
        detection_dir=str(DETECTION_CROP_DIR),
    )
    config = build_sh_config()

    progress(f"Road discovery for {label}", 10)
    roads = engine.fetch_roads(bbox)
    if roads.empty:
        return store_analysis_result(
            preset_id,
            label=label,
            bbox=bbox,
            country=country,
            category=category,
            road_count=0,
            frame_count=0,
            detections=[],
            status="error",
            error="No major roads found in AOI.",
        )

    progress(f"Found {len(roads)} road segments — querying Copernicus catalog", 25)
    sh_bbox = BBox(bbox=[min_lon, min_lat, max_lon, max_lat], crs=CRS.WGS84)
    catalog = SentinelHubCatalog(config=config)
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=max(1, months) * 30)
    cdse_collection = DataCollection.SENTINEL2_L2A.define_from(
        "s2l2a",
        service_url=config.sh_base_url,
    )
    search_results = list(
        catalog.search(
            cdse_collection,
            bbox=sh_bbox,
            datetime=(
                f"{start_date.strftime('%Y-%m-%dT00:00:00Z')}/"
                f"{end_date.strftime('%Y-%m-%dT23:59:59Z')}"
            ),
            filter="eo:cloud_cover < 60",
            fields={"include": ["properties.datetime", "id"], "exclude": []},
        )
    )
    unique_scenes: dict[str, Any] = {}
    for res in search_results:
        date_key = res["properties"]["datetime"][:10]
        if date_key not in unique_scenes:
            unique_scenes[date_key] = res
    final_obs = [unique_scenes[d] for d in sorted(unique_scenes.keys(), reverse=True)]
    final_obs = final_obs[: max(1, max_frames)]
    if not final_obs:
        return store_analysis_result(
            preset_id,
            label=label,
            bbox=bbox,
            country=country,
            category=category,
            road_count=len(roads),
            frame_count=0,
            detections=[],
            status="error",
            error=f"No clear imagery found in the last {months} months.",
        )

    def _fetch_frame(idx: int, res_obs: dict[str, Any]):
        try:
            date_str = res_obs["properties"]["datetime"]
            req_sh = SentinelHubRequest(
                evalscript=_EVALSCRIPT,
                input_data=[
                    SentinelHubRequest.input_data(
                        data_collection=cdse_collection,
                        time_interval=(date_str, date_str),
                    )
                ],
                responses=[SentinelHubRequest.output_response("default", MimeType.TIFF)],
                bbox=sh_bbox,
                config=config,
            )
            data_list = req_sh.get_data()
            if not data_list:
                return idx, date_str, None
            return idx, date_str, data_list[0]
        except Exception as exc:
            logger.error("Sentinel frame %s failed: %s", idx, exc)
            return idx, None, None

    progress(f"Seed frame 1/{len(final_obs)}", 35)
    _, seed_ts, seed_data = _fetch_frame(0, final_obs[0])
    if seed_data is None:
        return store_analysis_result(
            preset_id,
            label=label,
            bbox=bbox,
            country=country,
            category=category,
            road_count=len(roads),
            frame_count=0,
            detections=[],
            status="error",
            error="Failed to acquire seed spectral data.",
        )

    roads_buf = roads.to_crs(epsg=3857).buffer(20).to_crs(epsg=4326)
    h, w = seed_data.shape[:2]
    trans = rio_transform.from_bounds(min_lon, min_lat, max_lon, max_lat, w, h)
    road_mask = rio_features.rasterize(
        [(geom.__geo_interface__, 1) for geom in roads_buf.geometry],
        out_shape=(h, w),
        transform=trans,
        fill=0,
        all_touched=True,
    )

    detections: list[dict[str, Any]] = []
    detections.extend(engine.detect_trucks(seed_data, bbox, final_obs[0]["properties"]["datetime"], road_mask))

    if len(final_obs) > 1:
        progress(f"Parallel frames ({len(final_obs) - 1} remaining)", 45)
        with ThreadPoolExecutor(max_workers=3, thread_name_prefix="road-corridor") as executor:
            futures = {
                executor.submit(_fetch_frame, i, final_obs[i]): i for i in range(1, len(final_obs))
            }
            done = 1
            for future in as_completed(futures):
                idx, date_str, frame_data = future.result()
                done += 1
                if frame_data is not None and date_str:
                    detections.extend(engine.detect_trucks(frame_data, bbox, date_str, road_mask))
                progress(f"Frame {done}/{len(final_obs)}", 45 + int((done / len(final_obs)) * 50))

    progress(f"Complete — {len(detections)} truck signatures", 100)
    return store_analysis_result(
        preset_id,
        label=label,
        bbox=bbox,
        country=country,
        category=category,
        road_count=len(roads),
        frame_count=len(final_obs),
        detections=detections,
        status="ok",
    )


def analyze_preset(preset_id: str, progress_cb: ProgressCb | None = None) -> dict[str, Any]:
    from .presets import get_preset

    preset = get_preset(preset_id)
    if preset is None:
        raise KeyError(f"Unknown preset: {preset_id}")
    return analyze_corridor(
        preset_id=preset["id"],
        label=preset["label"],
        bbox=preset["bbox"],
        country=preset["country"],
        category=preset["category"],
        progress_cb=progress_cb,
    )
