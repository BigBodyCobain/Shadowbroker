"""S2 truck motion detection core (DrishX / Fisser et al. 2022 — see third_party/drishx/NOTICE.md)."""
from __future__ import annotations

import logging
import os
import pickle
import time
from pathlib import Path

import imageio.v3 as imageio
import numpy as np
import requests
from requests.adapters import HTTPAdapter
from shapely.geometry import LineString
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

SECONDS_OFFSET_B02_B04 = 1.01

OVERPASS_MIRRORS = [
    "https://lz4.overpass-api.de/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]

_session = requests.Session()
_retry = Retry(
    total=2,
    backoff_factor=1.0,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET", "POST"],
)
_adapter = HTTPAdapter(max_retries=_retry)
_session.mount("http://", _adapter)
_session.mount("https://", _adapter)


def _configure_osmnx(data_dir: str) -> None:
    import osmnx as ox

    ox.settings.requests_session = _session
    ox.settings.requests_timeout = 30
    ox.settings.overpass_rate_limit = False
    ox.settings.max_query_area_size = 1_000_000_000_000
    ox.settings.log_console = False
    ox.settings.use_cache = True
    ox.settings.cache_folder = os.path.join(data_dir, "osm_cache")


def _default_rf_model_path() -> str:
    return str(Path(__file__).resolve().parents[2] / "data" / "drishx" / "rf_model.pickle")


# ─────────────────────────────────────────────────────────────────────────────
# Helper math — mirrors S2TD.array_utils.math
# ─────────────────────────────────────────────────────────────────────────────

def normalized_ratio(a, b):
    """(a - b) / (a + b), safe division."""
    denom = a + b
    with np.errstate(divide="ignore", invalid="ignore"):
        result = np.where(denom != 0, (a - b) / denom, 0.0)
    return result.astype(np.float32)


def rescale_s2(bands):
    """Rescale Sentinel-2 L2A reflectance values (typically 0–10000 int) to 0–1 float."""
    bands = bands.astype(np.float32)
    if np.nanmax(bands) > 10:  # likely DN scale
        bands /= 10000.0
    return bands


# ─────────────────────────────────────────────────────────────────────────────
# Array subset — exact replica of S2TD.pick_arr_subset
# ─────────────────────────────────────────────────────────────────────────────

def pick_arr_subset(arr, y, x, size):
    """Pick a size×size window centred on (y, x) from a 2D or 3D array."""
    size_low = size // 2
    size_up = size // 2
    if size_low + size_up < size:
        size_up += 1
    ymin = max(0, y - size_low)
    ymax = max(0, y + size_up)
    xmin = max(0, x - size_low)
    xmax = max(0, x + size_up)
    if arr.ndim == 2:
        return arr[ymin:ymax, xmin:xmax]
    elif arr.ndim == 3:
        return arr[:, ymin:ymax, xmin:xmax]
    return arr


# ─────────────────────────────────────────────────────────────────────────────
# Feature stack — exact 7 features as in S2TD._build_feature_stack (Table 1)
# ─────────────────────────────────────────────────────────────────────────────

def build_feature_stack(data):
    """
    Build the 7-feature stack from Sentinel-2 bands.

    Input `data` shape: (H, W, 5) with channels [B04(R), B03(G), B02(B), B08(NIR), CLM].

    Feature order (Table 1, Fisser et al. 2022):
        0: variance of (B04, B03, B02)
        1: normalized_ratio(B04, B02)  — red / blue
        2: normalized_ratio(B03, B02)  — green / blue
        3: B04 - mean(B04)
        4: B03 - mean(B03)
        5: B02 - mean(B02)
        6: B08 - mean(B08)
    """
    R = data[:, :, 0].astype(np.float32)    # B04
    G = data[:, :, 1].astype(np.float32)    # B03
    B = data[:, :, 2].astype(np.float32)    # B02
    NIR = data[:, :, 3].astype(np.float32)  # B08
    CLM = data[:, :, 4]

    # Rescale if needed
    bands = np.stack([R, G, B, NIR], axis=0)
    bands = rescale_s2(bands)
    R, G, B, NIR = bands[0], bands[1], bands[2], bands[3]

    # Cloud mask → NaN
    cloud = CLM > 0
    R[cloud] = np.nan
    G[cloud] = np.nan
    B[cloud] = np.nan
    NIR[cloud] = np.nan

    H, W = R.shape
    fs = np.zeros((7, H, W), dtype=np.float32)

    # Check for any valid data to avoid "Mean of empty slice" warnings
    if np.any(~cloud):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            # Feature 0: variance of visible bands
            fs[0] = np.nanvar(np.stack([R, G, B], axis=0), axis=0, ddof=0)

            # Features 1–2: normalized ratios
            fs[1] = normalized_ratio(R, B)
            fs[2] = normalized_ratio(G, B)

            # Features 3–6: mean-centered bands
            fs[3] = R - np.nanmean(R)
            fs[4] = G - np.nanmean(G)
            fs[5] = B - np.nanmean(B)
            fs[6] = NIR - np.nanmean(NIR)
    else:
        # All pixels are cloud-masked
        fs.fill(np.nan)

    # Ensure NaN consistency
    nan_mask = np.isnan(fs[3])
    fs[:, nan_mask] = np.nan

    return {
        "feature_stack": fs,
        "bands": {"R": R, "G": G, "B": B, "NIR": NIR},
        "cloud_mask": cloud,
    }


# ─────────────────────────────────────────────────────────────────────────────
# RF Model loading
# ─────────────────────────────────────────────────────────────────────────────

# Path to the trained Random Forest model from S2TruckDetect
RF_MODEL_PATH = _default_rf_model_path()
_rf_model = None


def load_rf_model(path=None):
    """Load the trained RF model from pickle. Returns None if not found."""
    global _rf_model
    p = path or RF_MODEL_PATH
    if _rf_model is not None:
        return _rf_model
    if os.path.isfile(p):
        try:
            _rf_model = pickle.load(open(p, "rb"))
            logger.info(f"Loaded trained RF model from {p}")
            return _rf_model
        except Exception as e:
            logger.error(f"Failed to load RF model from {p}: {e}")
    else:
        logger.warning(f"RF model not found at {p} — will use proxy classifier (lower accuracy)")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Classification — real RF (preferred) or proxy fallback
# ─────────────────────────────────────────────────────────────────────────────

def rf_classify(feature_stack, road_mask, rf_model):
    """
    Classify pixels using the trained Random Forest model.
    Exact replica of S2TD._predict + _postprocess_prediction.

    :param feature_stack: (7, H, W) feature array
    :param road_mask: (H, W) binary road mask
    :param rf_model: trained sklearn RandomForestClassifier
    :return: (probabilities (4, H, W), prediction (H, W) int8)
    """
    H, W = feature_stack.shape[1], feature_stack.shape[2]

    # Reshape to (n_pixels, 7) for sklearn
    vars_reshaped = []
    for band_idx in range(feature_stack.shape[0]):
        vars_reshaped.append(feature_stack[band_idx].flatten())
    vars_reshaped = np.array(vars_reshaped).swapaxes(0, 1)  # (n_pixels, 7)

    # Build NaN mask — exclude NaN and Inf pixels
    nan_mask_flat = np.zeros_like(vars_reshaped)
    for var_idx in range(vars_reshaped.shape[1]):
        nan_mask_flat[:, var_idx] = ~np.isnan(vars_reshaped[:, var_idx])
    not_nan = (np.nanmin(nan_mask_flat, axis=1).astype(bool)
               & np.min(np.isfinite(vars_reshaped), axis=1).astype(bool))

    # Run RF predict_proba on valid pixels only
    if not np.any(not_nan):
        # Graceful return if no valid pixels found (e.g., all cloud masked)
        probabilities_shaped = np.zeros((4, H, W), dtype=np.float32)
        classification = np.zeros((H, W), dtype=np.int8)
        return probabilities_shaped, classification

    predictions_flat = rf_model.predict_proba(vars_reshaped[not_nan])

    # Map probabilities back to spatial grid
    n_classes = predictions_flat.shape[1] 
    probabilities_shaped = np.zeros((n_classes, H * W), dtype=np.float32)
    for idx in range(n_classes):
        probabilities_shaped[idx, not_nan] = predictions_flat[:, idx]

    probabilities_shaped = probabilities_shaped.reshape((n_classes, H, W))

    # Zero out NaN positions
    nan_2d = np.isnan(feature_stack[0])
    probabilities_shaped[:, nan_2d] = 0

    # Post-process: suppress low-confidence background (exact S2TD logic)
    probabilities_shaped[1][probabilities_shaped[1] < 0.75] = 0

    classification = np.nanargmax(probabilities_shaped, axis=0).astype(np.int8) + 1
    classification[np.max(probabilities_shaped, axis=0) == 0] = 0
    classification[nan_2d] = 0

    # Apply road mask
    rm = road_mask.astype(bool)
    classification[~rm] = 0

    return probabilities_shaped, classification


def proxy_classify(feature_stack, road_mask):
    """
    Heuristic proxy when RF model is unavailable. Lower accuracy.

    Produces:
        probabilities: (4, H, W) — class probs for [background, blue, green, red]
        prediction:    (H, W)    — int8 labels {0=nan, 1=background, 2=blue, 3=green, 4=red}
    """
    fs = feature_stack  # (7, H, W)
    H, W = fs.shape[1], fs.shape[2]
    probs = np.zeros((4, H, W), dtype=np.float32)

    centered_R = fs[3]
    centered_G = fs[4]
    centered_B = fs[5]
    var_feat = fs[0]
    nratio_rb = fs[1]
    nratio_gb = fs[2]

    rm = road_mask.astype(bool)
    nan_mask = np.isnan(centered_R)

    blue_score = np.clip(-nratio_rb * 2 + centered_B * 5 + var_feat * 10, 0, None)
    blue_score[~rm | nan_mask] = 0

    green_score = np.clip(nratio_gb * 2 + centered_G * 5 + var_feat * 10, 0, None)
    green_score[~rm | nan_mask] = 0

    red_score = np.clip(nratio_rb * 2 + centered_R * 5 + var_feat * 10, 0, None)
    red_score[~rm | nan_mask] = 0

    total = blue_score + green_score + red_score + 1e-8
    probs[1] = blue_score / total
    probs[2] = green_score / total
    probs[3] = red_score / total
    probs[0] = 1.0 - np.max(probs[1:], axis=0)

    probs[0][probs[0] < 0.75] = 0

    classification = np.nanargmax(probs, axis=0).astype(np.int8) + 1
    classification[np.max(probs, axis=0) == 0] = 0
    classification[nan_mask] = 0
    classification[~rm] = 0

    return probs, classification


def classify(feature_stack, road_mask, rf_model=None):
    """
    Unified classifier entry point.
    Uses trained RF if model is provided, otherwise falls back to proxy.
    """
    if rf_model is not None:
        logger.debug("Using trained RF model for classification")
        return rf_classify(feature_stack, road_mask, rf_model)
    else:
        logger.debug("Using proxy classifier (no RF model loaded)")
        return proxy_classify(feature_stack, road_mask)


# ─────────────────────────────────────────────────────────────────────────────
# Object extraction — faithful port of S2TD ObjectExtractor
# ─────────────────────────────────────────────────────────────────────────────

class ObjectExtractor:
    """
    Extracts truck objects from the RF prediction raster using recursive
    neighbourhood clustering, matching the S2TD reference implementation.
    """

    def __init__(self, probabilities, lat_arr, lon_arr):
        """
        :param probabilities: (4, H, W) class probabilities
        :param lat_arr: 1-D array of latitude per row
        :param lon_arr: 1-D array of longitude per column
        """
        self.probabilities = probabilities
        self.lat = lat_arr
        self.lon = lon_arr

    def extract(self, predictions_arr):
        """Main extraction loop over all blue (class 2) seed pixels."""
        preds = predictions_arr.copy()
        probs = self.probabilities.copy()

        preds[preds == 1] = 0  # zero out background
        blue_ys, blue_xs = np.where(preds == 2)
        detections = []
        sub_size = 9

        for i in range(len(blue_ys)):
            y_blue, x_blue = int(blue_ys[i]), int(blue_xs[i])
            if preds[y_blue, x_blue] == 0:
                continue

            subset_9 = pick_arr_subset(preds, y_blue, x_blue, sub_size).copy()
            subset_3 = pick_arr_subset(preds, y_blue, x_blue, 3).copy()
            subset_9_probs = pick_arr_subset(probs, y_blue, x_blue, sub_size).copy()

            half_idx_y = y_blue if subset_9.shape[0] < sub_size else subset_9.shape[0] // 2
            half_idx_x = x_blue if subset_9.shape[1] < sub_size else subset_9.shape[1] // 2
            try:
                current_value = subset_9[half_idx_y, half_idx_x]
            except IndexError:
                half_idx_y, half_idx_x = sub_size // 2, sub_size // 2
                current_value = subset_9[half_idx_y, half_idx_x]

            new_value = 100
            if not all(v in subset_9 for v in [2, 3, 4]):
                continue

            cluster, seen_idx, seen_vals, _ = self._cluster_array(
                arr=subset_9, probs=subset_9_probs,
                point=[half_idx_y, half_idx_x],
                new_value=new_value, current_value=current_value,
                yet_seen_indices=[], yet_seen_values=[],
                skipped_one=False,
            )

            if np.count_nonzero(cluster == new_value) < 3:
                continue

            det = self._postprocess_cluster(
                cluster, preds, probs, subset_3,
                y_blue, x_blue,
                half_idx_y, half_idx_x,
                new_value,
            )
            if det is not None:
                preds = det["updated_preds"]
                detections.append(det["detection"])

        return detections

    def _cluster_array(self, arr, probs, point, new_value, current_value,
                       yet_seen_indices, yet_seen_values, skipped_one):
        """Recursive neighbourhood clustering — matches S2TD._cluster_array."""
        if len(yet_seen_indices) == 0:
            yet_seen_indices.append(point)
            yet_seen_values.append(current_value)

        arr_mod = arr.copy()
        arr_mod[point[0], point[1]] = 0

        window_3x3 = pick_arr_subset(arr_mod, point[0], point[1], 3).copy()
        if window_3x3.shape[0] >= 2 and window_3x3.shape[1] >= 2:
            cy = min(1, window_3x3.shape[0] - 1)
            cx = min(1, window_3x3.shape[1] - 1)
            if window_3x3[cy, cx] == 2:
                window_3x3[window_3x3 == 4] = 1  # eliminate reds near blue

        y, x = point[0], point[1]
        window_3x3_probs = pick_arr_subset(probs, y, x, 3)

        windows = [window_3x3]
        windows_probs = [window_3x3_probs]
        if current_value == 4 or skipped_one:
            windows = windows[0:1]

        ys, xs = np.array([], dtype=int), np.array([], dtype=int)
        window_idx = 0
        offset_y, offset_x = 0, 0

        while len(ys) == 0 and window_idx < len(windows):
            window = windows[window_idx]
            window_p = windows_probs[window_idx]
            offset_y = window.shape[0] // 2
            offset_x = window.shape[1] // 2

            go_next = (current_value + 1) in window or current_value == 2
            target_value = current_value + 1 if go_next else current_value
            match = window == target_value
            if np.count_nonzero(match) == 0:
                target_value = current_value
                match = window == target_value

            ys_found, xs_found = np.where(match)

            # Probability-based tie-breaking
            if len(ys_found) > 1 and window_p.ndim == 3 and window_p.shape[0] > (target_value - 1):
                wp_target = window_p[target_value - 1] * match
                max_prob_mask = (wp_target == np.max(wp_target))
                ys_found, xs_found = np.where(max_prob_mask)

            ys, xs = ys_found, xs_found
            window_idx += 1

        ymin_w = max(0, point[0] - offset_y)
        xmin_w = max(0, point[1] - offset_x)

        for y_local, x_local in zip(ys, xs):
            ny, nx = ymin_w + int(y_local), xmin_w + int(x_local)
            if [ny, nx] in yet_seen_indices:
                continue
            if ny < 0 or ny >= arr.shape[0] or nx < 0 or nx >= arr.shape[1]:
                continue
            try:
                cv = arr[ny, nx]
            except IndexError:
                continue

            # Red already seen but this is green or blue → skip
            if 4 in yet_seen_values and cv <= 3:
                continue

            arr_mod[ny, nx] = new_value
            yet_seen_indices.append([ny, nx])
            yet_seen_values.append(cv)

            # Guard: avoid picking many more reds than blues and greens
            n_blue = sum(1 for v in yet_seen_values if v == 2)
            n_green = sum(1 for v in yet_seen_values if v == 3)
            n_red = sum(1 for v in yet_seen_values if v == 4)
            if n_red > n_blue and n_red > n_green:
                break

            arr_mod, yet_seen_indices, yet_seen_values, skipped_one = self._cluster_array(
                arr_mod, probs, [ny, nx], new_value, cv,
                yet_seen_indices, yet_seen_values, skipped_one,
            )

        arr_mod[point[0], point[1]] = new_value
        return arr_mod, yet_seen_indices, yet_seen_values, skipped_one

    def _postprocess_cluster(self, cluster, preds_copy, probs, subset_3,
                             y_blue, x_blue, half_idx_y, half_idx_x,
                             new_value):
        """Validate cluster and produce a detection dict — mirrors S2TD._postprocess_cluster."""
        # Add neighbouring blues from the 3×3 window
        ys_ba, xs_ba = np.where(subset_3 == 2)
        ys_ba = ys_ba + half_idx_y - 1
        xs_ba = xs_ba + half_idx_x - 1
        for yb, xb in zip(ys_ba, xs_ba):
            yb_c = int(np.clip(yb, 0, cluster.shape[0] - 1))
            xb_c = int(np.clip(xb, 0, cluster.shape[1] - 1))
            cluster[yb_c, xb_c] = new_value

        cluster[cluster != new_value] = 0
        cys, cxs = np.where(cluster == new_value)
        if len(cys) == 0:
            return None

        # Map subset coords back to full array
        ymin_sub = int(np.clip(y_blue - half_idx_y, 0, np.inf))
        xmin_sub = int(np.clip(x_blue - half_idx_x, 0, np.inf))
        cys_full = cys + ymin_sub
        cxs_full = cxs + xmin_sub

        ymin = int(np.min(cys_full))
        xmin = int(np.min(cxs_full))
        ymax = int(np.max(cys_full)) + 1  # +1: box extends to upper bound of pixel
        xmax = int(np.max(cxs_full)) + 1

        H, W = preds_copy.shape
        ymin, ymax = max(0, ymin), min(H, ymax)
        xmin, xmax = max(0, xmin), min(W, xmax)

        box_preds = preds_copy[ymin:ymax, xmin:xmax].copy()
        box_probs = probs[1:, ymin:ymax, xmin:xmax].copy()  # classes 2,3,4 → indices 0,1,2

        # Spectral probability scores (exact S2TD logic)
        max_probs = []
        for cls_offset, cls_val in enumerate([2, 3, 4]):
            mask = (box_preds == cls_val)
            vals = box_probs[cls_offset] * mask
            mp = float(np.nanmax(vals)) if np.any(mask) else 0.0
            max_probs.append(mp)

        mean_max_spectral_probability = float(np.nanmean(max_probs))
        mean_spectral_probability = float(np.nanmean(np.nanmax(box_probs, axis=0)))

        # Validation checks
        all_given = all(v in box_preds for v in [2, 3, 4])
        large_enough = box_preds.shape[0] > 2 or box_preds.shape[1] > 2
        too_large = box_preds.shape[0] > 5 or box_preds.shape[1] > 5

        if too_large or not all_given or not large_enough:
            return None

        # Score: TWO terms — matches reference
        score = mean_max_spectral_probability + mean_spectral_probability
        if score <= 1.2:
            return None

        # Direction (blue → red vector)
        by, bx = np.where(box_preds == 2)
        ry, rx = np.where(box_preds == 4)
        blue_idx = np.array([by[0], bx[0]], dtype=np.int8)
        red_idx = np.array([ry[0], rx[0]], dtype=np.int8)
        vector = (blue_idx - red_idx) * np.array([1, -1], dtype=np.int8)
        heading = float(np.degrees(np.arctan2(vector[1], vector[0])) % 360)

        # Speed
        diameter = max(box_preds.shape) * 10 - 10
        speed_kmh = float(np.sqrt(diameter * 20) / SECONDS_OFFSET_B02_B04 * 3.6)

        # Geo-coordinates (centre of detection box)
        lat_centre = float((self.lat[ymin] + self.lat[min(ymax, len(self.lat) - 1)]) / 2)
        lon_centre = float((self.lon[xmin] + self.lon[min(xmax, len(self.lon) - 1)]) / 2)

        # Zero out detected pixels to prevent re-detection
        preds_copy[ymin:ymax, xmin:xmax] *= np.zeros_like(box_preds)
        # Also zero 3×3 around blue pixels
        blue_in_box = np.where(box_preds == 2)
        for yb, xb in zip(blue_in_box[0], blue_in_box[1]):
            y0, y1 = max(0, ymin + yb - 1), min(H, ymin + yb + 2)
            x0, x1 = max(0, xmin + xb - 1), min(W, xmin + xb + 2)
            preds_copy[y0:y1, x0:x1] *= (preds_copy[y0:y1, x0:x1] != 2).astype(np.int8)

        crop_id = f"truck_{int(time.time() * 1000)}_{ymin}_{xmin}.png"

        return {
            "updated_preds": preds_copy,
            "detection": {
                "lat": lat_centre,
                "lon": lon_centre,
                "confidence": float(min(score / 2.4, 1.0)),
                "s_score": round(score, 3),
                "speed_kmh": round(speed_kmh, 1),
                "heading": round(heading, 1),
                "heading_desc": self._direction_to_compass(heading),
                "id": crop_id,
                "image_url": f"/detections/{crop_id}",
                "box_shape": list(box_preds.shape),
                "max_probs": {"blue": max_probs[0], "green": max_probs[1], "red": max_probs[2]},
            },
        }

    @staticmethod
    def _direction_to_compass(deg):
        bins = np.arange(0, 359, 45, dtype=np.float32)
        labels = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
        return labels[int(np.argmin(np.abs(bins - deg)))]


# ─────────────────────────────────────────────────────────────────────────────
# ARGUS Engine
# ─────────────────────────────────────────────────────────────────────────────

class S2TruckEngine:
    def __init__(self, *, cache_dir: str, detection_dir: str, rf_model_path: str | None = None):
        self.cache_dir = cache_dir
        self.detection_dir = detection_dir
        os.makedirs(self.detection_dir, exist_ok=True)
        _configure_osmnx(cache_dir)
        self.rf_model = load_rf_model(rf_model_path)

    def fetch_roads(self, bbox_coords, progress_cb=None):
        """Fetch major roads with automatic mirror rotation and fallbacks."""
        import geopandas as gpd
        import osmnx as ox

        def log(msg, level="info", pct=None):
            if level == "info":
                logger.info(msg)
            elif level == "warn":
                logger.warning(msg)
            if progress_cb:
                progress_cb(msg, pct)

        min_lat, min_lon, max_lat, max_lon = bbox_coords
        center_lat = (min_lat + max_lat) / 2
        center_lon = (min_lon + max_lon) / 2

        lat_span = (max_lat - min_lat) * 111000
        lon_span = (max_lon - min_lon) * 111000 * np.cos(np.radians(center_lat))
        dist_m = int(max(lat_span, lon_span) * 0.6) + 1000

        log(f"Starting road discovery (ROI: {center_lat:.4f}, {center_lon:.4f})", pct=5)

        for i, mirror in enumerate(OVERPASS_MIRRORS):
            log(f"Trying mirror {i+1}/{len(OVERPASS_MIRRORS)}: {mirror}", pct=10 + i * 5)
            ox.settings.overpass_url = mirror
            try:
                graph = ox.graph_from_point(
                    (center_lat, center_lon), dist=dist_m,
                    network_type="drive", simplify=True,
                    retain_all=False, truncate_by_edge=True,
                )
                roads = ox.graph_to_gdfs(graph, nodes=False)
                major_types = [
                    "motorway", "trunk", "primary", "secondary",
                    "motorway_link", "trunk_link", "primary_link",
                ]
                roads = roads[roads["highway"].isin(major_types)].copy()
                if not roads.empty:
                    logger.info(f"Fetched {len(roads)} major roads from {mirror}")
                    return roads
            except Exception as e:
                logger.warning(f"Mirror {mirror} failed: {e}")
                time.sleep(1)

        # Raw Overpass fallback
        logger.warning("All mirrors failed. Trying raw Overpass query.")
        try:
            query = f"""
            [out:json][timeout:60];
            (way["highway"~"motorway|trunk|primary"]({min_lat},{min_lon},{max_lat},{max_lon}););
            out body; >; out skel qt;
            """
            resp = requests.post(OVERPASS_MIRRORS[0], data={"data": query}, timeout=60)
            if resp.status_code == 200:
                data = resp.json()
                nodes = {n["id"]: (n["lon"], n["lat"]) for n in data["elements"] if n["type"] == "node"}
                ways = []
                for w in data["elements"]:
                    if w["type"] == "way" and "nodes" in w:
                        coords = [nodes[nid] for nid in w["nodes"] if nid in nodes]
                        if len(coords) > 1:
                            ways.append({"geometry": LineString(coords), "highway": w["tags"].get("highway")})
                if ways:
                    roads = gpd.GeoDataFrame(ways, crs="EPSG:4326")
                    logger.info(f"Raw fallback: {len(roads)} roads")
                    return roads
        except Exception as e:
            logger.error(f"Raw fallback failed: {e}")

        return gpd.GeoDataFrame()

    def detect_trucks(self, data, bbox_coords, timestamp, road_mask):
        """
        Detect trucks using corrected Fisser et al. methodology.

        :param data: (H, W, 5) array — [B04, B03, B02, B08, CLM]
        :param bbox_coords: [min_lat, min_lon, max_lat, max_lon]
        :param timestamp: str ISO timestamp
        :param road_mask: (H, W) binary mask of road pixels
        :return: list of detection dicts
        """
        min_lat, min_lon, max_lat, max_lon = bbox_coords
        H, W = data.shape[:2]

        # 1. Build feature stack (corrected order)
        feat = build_feature_stack(data)
        feature_stack = feat["feature_stack"]

        # 2. Classify (real RF if loaded, proxy fallback otherwise)
        probs, prediction = classify(feature_stack, road_mask, self.rf_model)

        # 3. Lat/lon arrays for geo-referencing
        lat_arr = np.linspace(max_lat, min_lat, H)  # top to bottom
        lon_arr = np.linspace(min_lon, max_lon, W)  # left to right

        # 4. Object extraction (corrected)
        extractor = ObjectExtractor(probs, lat_arr, lon_arr)
        detections = extractor.extract(prediction)

        # 5. Add timestamp and save crops
        for det in detections:
            det["timestamp"] = timestamp
            try:
                self._save_crop(data, det, H, W, min_lat, min_lon, max_lat, max_lon)
            except Exception as e:
                logger.warning(f"Could not save crop for {det['id']}: {e}")

        return detections

    def _save_crop(self, data, det, H, W, min_lat, min_lon, max_lat, max_lon):
        """Save a 20×20 RGB crop centred on the detection."""
        cy = int((max_lat - det["lat"]) / (max_lat - min_lat + 1e-9) * H)
        cx = int((det["lon"] - min_lon) / (max_lon - min_lon + 1e-9) * W)
        cy, cx = int(np.clip(cy, 0, H - 1)), int(np.clip(cx, 0, W - 1))

        y0, y1 = max(0, cy - 10), min(H, cy + 10)
        x0, x1 = max(0, cx - 10), min(W, cx + 10)

        rgb = data[y0:y1, x0:x1, :3].astype(np.float32)
        rgb = rescale_s2(rgb)
        rgb = (np.clip(rgb, 0, 0.3) / 0.3 * 255).astype(np.uint8)

        path = os.path.join(self.detection_dir, det["id"])
        imageio.imwrite(path, rgb)
