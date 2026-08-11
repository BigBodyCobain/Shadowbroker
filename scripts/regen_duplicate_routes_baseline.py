"""Regenerate the tolerated duplicate-route baseline used by issue #239 tests.

Run from the repository root with::

    python -m scripts.regen_duplicate_routes_baseline

The command imports the backend application, inspects FastAPI's registered
routes, and rewrites ``backend/tests/data/duplicate_routes_baseline.json`` in a
deterministic order.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
DEFAULT_BASELINE_PATH = BACKEND_DIR / "tests" / "data" / "duplicate_routes_baseline.json"

_BASELINE_NOTE = (
    "Snapshot of currently-tolerated duplicate route registrations. The test in "
    "test_no_new_duplicate_routes.py fails if any NEW (method, path) duplicate "
    "appears outside this list. Removing entries (by actually deduping) is fine "
    "and the test stays green. New entries here require explicit, reviewed updates."
)


def collect_duplicate_routes(routes: Iterable[Any]) -> dict[str, list[str]]:
    """Return duplicate ``METHOD /path`` registrations and their modules."""
    by_key: dict[str, list[str]] = defaultdict(list)

    for route in routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        endpoint = getattr(route, "endpoint", None)
        if not path or not methods or endpoint is None:
            continue

        module = str(getattr(endpoint, "__module__", "") or "")
        for method in sorted(methods):
            if method in {"HEAD", "OPTIONS"}:
                continue
            by_key[f"{method} {path}"].append(module)

    return {
        key: sorted(modules)
        for key, modules in sorted(by_key.items())
        if len(modules) > 1
    }


def current_duplicates() -> dict[str, list[str]]:
    """Import the backend application and inspect its live route table."""
    backend = str(BACKEND_DIR)
    if backend not in sys.path:
        sys.path.insert(0, backend)

    import main

    return collect_duplicate_routes(main.app.routes)


def build_baseline_payload(duplicates: dict[str, list[str]]) -> dict[str, Any]:
    """Build the canonical JSON payload written by the regeneration command."""
    return {
        "_meta": {
            "issue": "#239",
            "note": _BASELINE_NOTE,
            "generated_with": "python -m scripts.regen_duplicate_routes_baseline",
        },
        "duplicates": {
            key: sorted(modules)
            for key, modules in sorted(duplicates.items())
        },
    }


def write_baseline(
    path: Path = DEFAULT_BASELINE_PATH,
    *,
    duplicates: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Write the baseline and return the payload for callers and tests."""
    payload = build_baseline_payload(
        current_duplicates() if duplicates is None else duplicates
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    payload = write_baseline()
    print(
        f"Wrote {len(payload['duplicates'])} duplicate route entries to "
        f"{DEFAULT_BASELINE_PATH.relative_to(REPO_ROOT)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
