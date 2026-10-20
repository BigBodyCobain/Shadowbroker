"""Preset freight / chokepoint corridors for scheduled trend analysis."""
from __future__ import annotations

from typing import TypedDict


class CorridorPreset(TypedDict):
    id: str
    label: str
    bbox: list[float]  # [min_lat, min_lon, max_lat, max_lon]
    country: str
    category: str


# Bboxes are small (~5–10 km) highway segments suitable for 10 m Sentinel-2 analysis.
CORRIDOR_PRESETS: list[CorridorPreset] = [
    {
        "id": "laredo_i35",
        "label": "Laredo I-35 (US–Mexico freight)",
        "bbox": [27.48, -99.58, 27.54, -99.48],
        "country": "USA / Mexico",
        "category": "border_crossing",
    },
    {
        "id": "bandar_abbas_feeder",
        "label": "Bandar Abbas port feeder (Highway 71)",
        "bbox": [27.12, 56.22, 27.22, 56.38],
        "country": "Iran",
        "category": "port_feeder",
    },
    {
        "id": "rotterdam_a15",
        "label": "Rotterdam A15 port feeder",
        "bbox": [51.88, 4.42, 51.96, 4.58],
        "country": "Netherlands",
        "category": "port_feeder",
    },
    {
        "id": "mombasa_nairobi_a109",
        "label": "Mombasa–Nairobi A109 corridor",
        "bbox": [-4.10, 39.55, -1.20, 37.00],
        "country": "Kenya",
        "category": "trade_corridor",
    },
    {
        "id": "braunschweig_a7",
        "label": "Braunschweig A7 (validation)",
        "bbox": [52.25, 10.45, 52.32, 10.55],
        "country": "Germany",
        "category": "validation",
    },
]


def get_preset(preset_id: str) -> CorridorPreset | None:
    for preset in CORRIDOR_PRESETS:
        if preset["id"] == preset_id:
            return preset
    return None
