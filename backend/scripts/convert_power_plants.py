"""Download WRI Global Power Plant Database CSV and convert to compact JSON.

Usage:
    python backend/scripts/convert_power_plants.py

Output:
    backend/data/power_plants.json
"""
import csv
import json
import io
import zipfile
import urllib.request
from pathlib import Path

# WRI Global Power Plant Database v1.3.0 (GitHub release)
CSV_URL = "https://raw.githubusercontent.com/wri/global-power-plant-database/master/output_database/global_power_plant_database.csv"
OUT_PATH = Path(__file__).parent.parent / "data" / "power_plants.json"


def main() -> None:
    print(f"Downloading WRI Global Power Plant Database from GitHub...")
    # Round 7a: release-time data refresher. Uses the per-operator UA if
    # available, otherwise a release-script-specific identifier. This
    # script is run by the maintainer at release time, NOT at runtime,
    # so an aggregate UA is acceptable; we still use the helper so the
    # behavior matches the rest of the project.
    try:
        from services.network_utils import outbound_user_agent
        ua = outbound_user_agent("release-script-power-plants")
    except Exception:
        ua = "operator-release-script (purpose: power-plants)"
    req = urllib.request.Request(CSV_URL, headers={"User-Agent": ua})
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8")

    reader = csv.DictReader(io.StringIO(raw))
    plants: list[dict] = []
    skipped = 0
    for row in reader:
        try:
            lat = float(row["latitude"])
            lng = float(row["longitude"])
        except (ValueError, KeyError):
            skipped += 1
            continue
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            skipped += 1
            continue
        capacity_raw = row.get("capacity_mw", "")
        capacity_mw = float(capacity_raw) if capacity_raw else None
        plants.append({
            "name": row.get("name", "Unknown"),
            "country": row.get("country_long", ""),
            "fuel_type": row.get("primary_fuel", "Unknown"),
            "capacity_mw": capacity_mw,
            "owner": row.get("owner", ""),
            "lat": round(lat, 5),
            "lng": round(lng, 5),
        })

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(plants, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {len(plants)} power plants to {OUT_PATH} (skipped {skipped})")


if __name__ == "__main__":
    main()
