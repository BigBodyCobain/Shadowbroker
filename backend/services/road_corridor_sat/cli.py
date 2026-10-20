"""CLI for manual road corridor analysis runs."""
from __future__ import annotations

import argparse
import logging
import sys

from .config import optional_deps_available, road_corridor_sat_enabled
from .credentials import sentinel_credentials_configured
from .pipeline import analyze_preset
from .presets import CORRIDOR_PRESETS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Sentinel-2 road corridor truck trend analysis")
    parser.add_argument("--preset", required=True, help="Preset id (e.g. laredo_i35)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    if not optional_deps_available():
        print(
            "Install optional deps: uv sync --extra road-corridor "
            "(geopandas, osmnx, rasterio, sentinelhub, scikit-learn, imageio)",
            file=sys.stderr,
        )
        return 2
    if not road_corridor_sat_enabled() and not args.verbose:
        print("Note: ROAD_CORRIDOR_SAT_ENABLED is off — CLI still runs for manual analysis.")
    if not sentinel_credentials_configured():
        print("Set SENTINEL_CLIENT_ID and SENTINEL_CLIENT_SECRET first.", file=sys.stderr)
        return 2

    valid = {p["id"] for p in CORRIDOR_PRESETS}
    if args.preset not in valid:
        print(f"Unknown preset {args.preset!r}. Choose from: {', '.join(sorted(valid))}", file=sys.stderr)
        return 2

    def progress(msg: str, pct: int | None = None) -> None:
        suffix = f" ({pct}%)" if pct is not None else ""
        print(f"{msg}{suffix}")

    result = analyze_preset(args.preset, progress_cb=progress)
    print(
        f"Done: {result.get('total_detections', 0)} detections across "
        f"{len(result.get('daily_counts') or [])} days — status={result.get('status')}"
    )
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
