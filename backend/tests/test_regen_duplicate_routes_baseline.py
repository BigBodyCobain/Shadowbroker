from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

# The regenerator lives at the repository root (``scripts/``), not under
# ``backend/scripts``. When pytest's rootdir is ``backend`` the repo root is not
# on sys.path, so add it before importing (matches the documented invocation
# ``python -m scripts.regen_duplicate_routes_baseline`` run from the repo root).
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.regen_duplicate_routes_baseline import (  # noqa: E402
    build_baseline_payload,
    collect_duplicate_routes,
    write_baseline,
)


def _route(path: str, methods: set[str], module: str):
    def endpoint():
        return None

    endpoint.__module__ = module
    return SimpleNamespace(path=path, methods=methods, endpoint=endpoint)


def test_collect_duplicate_routes_matches_ci_guard_shape():
    routes = [
        _route("/api/layers", {"POST"}, "routers.data"),
        _route("/api/layers", {"POST"}, "main"),
        _route("/api/health", {"GET", "HEAD"}, "routers.health"),
        _route("/api/health", {"GET", "HEAD"}, "main"),
        _route("/api/only-once", {"GET"}, "routers.example"),
        SimpleNamespace(path=None, methods={"GET"}, endpoint=lambda: None),
    ]

    assert collect_duplicate_routes(routes) == {
        "GET /api/health": ["main", "routers.health"],
        "POST /api/layers": ["main", "routers.data"],
    }


def test_build_baseline_payload_is_deterministic():
    payload = build_baseline_payload(
        {
            "POST /z": ["routers.z", "main"],
            "GET /a": ["routers.a", "main"],
        }
    )

    assert list(payload["duplicates"]) == ["GET /a", "POST /z"]
    assert payload["duplicates"]["GET /a"] == ["main", "routers.a"]
    assert payload["_meta"]["issue"] == "#239"
    assert payload["_meta"]["generated_with"] == (
        "python -m scripts.regen_duplicate_routes_baseline"
    )


def test_write_baseline_emits_stable_json(tmp_path):
    output = tmp_path / "duplicate_routes_baseline.json"
    duplicates = {"POST /api/layers": ["routers.data", "main"]}

    payload = write_baseline(output, duplicates=duplicates)

    assert json.loads(output.read_text(encoding="utf-8")) == payload
    assert output.read_text(encoding="utf-8").endswith("\n")
    assert payload["duplicates"] == {
        "POST /api/layers": ["main", "routers.data"]
    }
