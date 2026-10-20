#!/usr/bin/env python3
"""Clean submarine cable GeoJSON: drop synthetic corridors and land-crossing segments."""
from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import LineString, shape
from shapely.ops import unary_union

SYNTHETIC = {
    "SEA-ME-WE Corridor",
    "Trans-Atlantic North",
    "Trans-Atlantic South",
    "WACS / SAT-3 Corridor",
    "EASSy / SEACOM",
    "East Asia Corridor",
    "Asia-Australia",
    "Trans-Pacific",
    "South Atlantic",
}

# Drop segments where this much of the path lies on land (110m/50m Natural Earth).
LAND_OVERLAP_MAX = 0.12


def lon_jump(a: list[float], b: list[float]) -> float:
    d = abs(b[0] - a[0])
    return min(d, 360 - d)


def iter_parts(geom: dict) -> list[list[list[float]]]:
    t = geom["type"]
    c = geom["coordinates"]
    if t == "LineString":
        return [c]
    if t == "MultiLineString":
        return c
    return []


def split_at_jumps(coords: list[list[float]], max_jump: float = 90) -> list[list[list[float]]]:
    if len(coords) < 2:
        return [coords] if coords else []
    segments: list[list[list[float]]] = [[coords[0]]]
    for point in coords[1:]:
        prev = segments[-1][-1]
        if lon_jump(prev, point) > max_jump:
            segments.append([point])
        else:
            segments[-1].append(point)
    return [seg for seg in segments if len(seg) >= 2]


def segment_land_overlap(a: list[float], b: list[float], land) -> float:
    line = LineString([a, b])
    if line.length == 0:
        return 0.0
    return float(line.intersection(land).length / line.length)


def filter_land_segments(coords: list[list[float]], land) -> list[list[list[float]]]:
    if len(coords) < 2:
        return []
    parts: list[list[list[float]]] = []
    current = [coords[0]]
    for a, b in zip(coords, coords[1:]):
        if segment_land_overlap(a, b, land) <= LAND_OVERLAP_MAX:
            if current[-1] != a:
                if len(current) >= 2:
                    parts.append(current)
                current = [a]
            current.append(b)
        else:
            if len(current) >= 2:
                parts.append(current)
            current = [b]
    if len(current) >= 2:
        parts.append(current)
    return parts


def parts_to_geometry(parts: list[list[list[float]]]) -> dict | None:
    if not parts:
        return None
    if len(parts) == 1:
        return {"type": "LineString", "coordinates": parts[0]}
    return {"type": "MultiLineString", "coordinates": parts}


def load_land(root: Path):
    data_dir = root / "scripts" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    land_path = data_dir / "ne_50m_land.geojson"
    if not land_path.exists():
        land_path = data_dir / "ne_110m_land.geojson"
    if not land_path.exists():
        import urllib.request

        land_path = data_dir / "ne_110m_land.geojson"
        url = (
            "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
            "master/geojson/ne_110m_land.geojson"
        )
        urllib.request.urlretrieve(url, land_path)
    data = json.loads(land_path.read_text(encoding="utf-8"))
    return unary_union([shape(feat["geometry"]) for feat in data["features"]])


def sanitize(data: dict, land) -> dict:
    by_name: dict[str, dict] = {}
    for feature in data.get("features", []):
        name = str((feature.get("properties") or {}).get("name") or "").strip()
        if not name or name in SYNTHETIC:
            continue
        geom = feature.get("geometry")
        if not geom:
            continue
        split_parts: list[list[list[float]]] = []
        for part in iter_parts(geom):
            for jump_part in split_at_jumps(part):
                split_parts.extend(filter_land_segments(jump_part, land))
        geometry = parts_to_geometry(split_parts)
        if not geometry:
            continue
        cleaned = {
            "type": "Feature",
            "properties": feature.get("properties") or {},
            "geometry": geometry,
        }
        existing = by_name.get(name)
        if not existing:
            by_name[name] = cleaned
            continue
        existing_pts = sum(len(p) for p in iter_parts(existing["geometry"]))
        new_pts = sum(len(p) for p in split_parts)
        if new_pts > existing_pts:
            by_name[name] = cleaned
    return {"type": "FeatureCollection", "features": list(by_name.values())}


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    src = root / "frontend" / "public" / "data" / "submarine-cables.json"
    raw = json.loads(src.read_text(encoding="utf-8"))
    land = load_land(root)
    cleaned = sanitize(raw, land)
    src.write_text(json.dumps(cleaned, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {len(cleaned['features'])} features to {src}")


if __name__ == "__main__":
    main()
