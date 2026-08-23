"""Regenerate the tolerated duplicate-route baseline for issue #239.

The baseline is a ceiling: it records duplicates already present in the app so
the CI guard can reject new registrations without hiding existing route debt.
Run this only after deliberately reviewing a baseline change.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Iterable


DEFAULT_OUTPUT = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "data"
    / "duplicate_routes_baseline.json"
)


def collect_duplicate_routes(routes: Iterable[object]) -> dict[str, list[str]]:
    """Return duplicate `(method, path)` registrations in CI-guard shape."""
    by_key: dict[str, list[str]] = defaultdict(list)
    for route in routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        endpoint = getattr(route, "endpoint", None)
        if not path or not methods or endpoint is None:
            continue
        module = getattr(endpoint, "__module__", None)
        if not module:
            continue
        for method in methods:
            if method in {"HEAD", "OPTIONS"}:
                continue
            by_key[f"{method} {path}"].append(module)

    return {
        key: sorted(modules)
        for key, modules in sorted(by_key.items())
        if len(modules) > 1
    }


def build_baseline_payload(duplicates: dict[str, list[str]]) -> dict[str, object]:
    """Build a stable, reviewable payload from duplicate-route observations."""
    return {
        "_meta": {
            "issue": "#239",
            "note": (
                "Snapshot of currently-tolerated duplicate route registrations. "
                "The CI guard rejects new or changed duplicate registrations; "
                "remove entries only after the underlying routes are deduped."
            ),
            "generated_with": "python -m scripts.regen_duplicate_routes_baseline",
        },
        "duplicates": {
            key: sorted(modules) for key, modules in sorted(duplicates.items())
        },
    }


def write_baseline(
    output: Path, *, duplicates: dict[str, list[str]]
) -> dict[str, object]:
    """Write a newline-terminated, stable JSON baseline and return its payload."""
    payload = build_baseline_payload(duplicates)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Regenerate the reviewed duplicate FastAPI route baseline."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    import main as application

    payload = write_baseline(
        args.output,
        duplicates=collect_duplicate_routes(application.app.routes),
    )
    print(f"Wrote {len(payload['duplicates'])} duplicate route entries to {args.output}.")


if __name__ == "__main__":
    main()
