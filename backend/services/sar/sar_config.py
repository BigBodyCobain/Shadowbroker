"""SAR layer configuration helpers.

Reads settings from the existing pydantic Settings object so the SAR layer
participates in the same two-step opt-in pattern the rest of the mesh uses
for risky toggles.

A small runtime credentials store lives alongside this module so the user
can enable Mode B from the frontend without editing .env files.  The
runtime store wins over the pydantic Settings snapshot — the env values
are the fallback, not the primary source, once a runtime override exists.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_RUNTIME_LOCK = threading.Lock()
_RUNTIME_FILE = Path(__file__).resolve().parents[2] / "data" / "sar_runtime.json"
_RUNTIME_CACHE: dict[str, Any] | None = None


def _load_runtime() -> dict[str, Any]:
    """Read the runtime credentials store.  Cached in-memory."""
    global _RUNTIME_CACHE
    if _RUNTIME_CACHE is not None:
        return _RUNTIME_CACHE
    if not _RUNTIME_FILE.exists():
        _RUNTIME_CACHE = {}
        return _RUNTIME_CACHE
    try:
        _RUNTIME_CACHE = json.loads(_RUNTIME_FILE.read_text(encoding="utf-8"))
        if not isinstance(_RUNTIME_CACHE, dict):
            _RUNTIME_CACHE = {}
    except (OSError, ValueError) as exc:
        logger.warning("SAR runtime store unreadable: %s", exc)
        _RUNTIME_CACHE = {}
    return _RUNTIME_CACHE


def _save_runtime(data: dict[str, Any]) -> None:
    global _RUNTIME_CACHE
    with _RUNTIME_LOCK:
        _RUNTIME_FILE.parent.mkdir(parents=True, exist_ok=True)
        _RUNTIME_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        _RUNTIME_CACHE = dict(data)


def set_runtime_credentials(
    *,
    earthdata_user: str = "",
    earthdata_token: str = "",
    copernicus_user: str = "",
    copernicus_token: str = "",
    mode_b_opt_in: bool = True,
) -> dict[str, Any]:
    """Persist runtime SAR credentials + the two-step opt-in flags.

    Setting ``mode_b_opt_in=True`` flips both MESH_SAR_PRODUCTS_FETCH and
    MESH_SAR_PRODUCTS_FETCH_ACKNOWLEDGE in the runtime store.  A caller
    that wants to revert to Mode A only can pass ``mode_b_opt_in=False``.
    """
    current = dict(_load_runtime())
    if earthdata_user:
        current["MESH_SAR_EARTHDATA_USER"] = earthdata_user.strip()
    if earthdata_token:
        current["MESH_SAR_EARTHDATA_TOKEN"] = earthdata_token.strip()
    if copernicus_user:
        current["MESH_SAR_COPERNICUS_USER"] = copernicus_user.strip()
    if copernicus_token:
        current["MESH_SAR_COPERNICUS_TOKEN"] = copernicus_token.strip()
    if mode_b_opt_in:
        current["MESH_SAR_PRODUCTS_FETCH"] = "allow"
        current["MESH_SAR_PRODUCTS_FETCH_ACKNOWLEDGE"] = True
    else:
        current["MESH_SAR_PRODUCTS_FETCH"] = "block"
        current["MESH_SAR_PRODUCTS_FETCH_ACKNOWLEDGE"] = False
    current["updated_at"] = int(time.time())
    _save_runtime(current)
    return current


def clear_runtime_credentials() -> None:
    """Wipe the runtime store and revert to Mode A."""
    _save_runtime({"updated_at": int(time.time())})


def _settings() -> Any:
    try:
        from services.config import get_settings
        return get_settings()
    except Exception:
        return None


def _flag(name: str, default: bool = False) -> bool:
    # Runtime store wins — set via the Settings → SAR panel in the app.
    runtime = _load_runtime()
    if name in runtime:
        raw = runtime[name]
        if isinstance(raw, bool):
            return raw
        raw_s = str(raw).strip().lower()
        if raw_s in {"1", "true", "yes", "on", "allow", "enable", "enabled"}:
            return True
        if raw_s in {"0", "false", "no", "off", "block", "disable", "disabled"}:
            return False
    s = _settings()
    if s is not None and hasattr(s, name):
        try:
            return bool(getattr(s, name))
        except Exception:
            pass
    raw = os.environ.get(name, "").strip().lower()
    if raw in {"1", "true", "yes", "on", "allow", "enable", "enabled"}:
        return True
    if raw in {"0", "false", "no", "off", "block", "disable", "disabled"}:
        return False
    return default


def _str(name: str, default: str = "") -> str:
    runtime = _load_runtime()
    if runtime.get(name):
        return str(runtime[name])
    s = _settings()
    if s is not None and hasattr(s, name):
        try:
            value = getattr(s, name)
            if value:
                return str(value)
        except Exception:
            pass
    return os.environ.get(name, default) or default


# ---------------------------------------------------------------------------
# Mode A — catalog ingest
# ---------------------------------------------------------------------------

def catalog_enabled() -> bool:
    """Mode A is on by default — only metadata, free, no account."""
    return _flag("MESH_SAR_CATALOG_ENABLED", default=True)


# ---------------------------------------------------------------------------
# Mode B — pre-processed anomaly ingest (two-step opt-in)
# ---------------------------------------------------------------------------

def products_fetch_enabled() -> bool:
    """Mode B requires two-step opt-in (matches MESH_PRIVATE_CLEARNET_FALLBACK pattern).

    Both flags must be affirmative — a single flag is not enough.  This
    is the same pattern the audit identified as load-bearing for risky
    toggles in the rest of the codebase.
    """
    raw = _str("MESH_SAR_PRODUCTS_FETCH", default="block").strip().lower()
    if raw not in {"allow", "enable", "enabled", "true", "on", "1"}:
        return False
    return _flag("MESH_SAR_PRODUCTS_FETCH_ACKNOWLEDGE", default=False)


def products_fetch_status() -> dict[str, Any]:
    """Structured status used by the router for the 'how to enable' UX."""
    raw = _str("MESH_SAR_PRODUCTS_FETCH", default="block").strip().lower()
    fetch_set = raw in {"allow", "enable", "enabled", "true", "on", "1"}
    ack_set = _flag("MESH_SAR_PRODUCTS_FETCH_ACKNOWLEDGE", default=False)
    enabled = fetch_set and ack_set
    return {
        "enabled": enabled,
        "fetch_flag_set": fetch_set,
        "acknowledge_flag_set": ack_set,
        "earthdata_token_set": bool(earthdata_token()),
        "earthdata_user_set": bool(earthdata_user()),
        "missing": _missing_for_products(fetch_set, ack_set),
        "help": {
            "summary": (
                "SAR ground-change alerts (Mode B) need two opt-in flags and a "
                "free NASA Earthdata Login.  Everything is free."
            ),
            "steps": [
                {
                    "step": 1,
                    "label": "Create a free NASA Earthdata Login",
                    "url": "https://urs.earthdata.nasa.gov/users/new",
                    "why": "Used to fetch OPERA pre-processed SAR products and (optionally) HyP3 jobs.",
                },
                {
                    "step": 2,
                    "label": "Generate an Earthdata user token",
                    "url": "https://urs.earthdata.nasa.gov/profile",
                    "why": "Bearer token used in the Authorization header (no password is stored).",
                },
                {
                    "step": 3,
                    "label": "Enable Mode B in Settings → SAR → Ground-Change Alerts",
                    "url": "/settings/sar",
                    "why": "Sets MESH_SAR_PRODUCTS_FETCH=allow and MESH_SAR_PRODUCTS_FETCH_ACKNOWLEDGE=true.",
                },
                {
                    "step": 4,
                    "label": "Optional: Copernicus Data Space account (EU coverage)",
                    "url": "https://dataspace.copernicus.eu/",
                    "why": "Used for European Ground Motion Service (EGMS) deformation maps over EU AOIs.",
                },
            ],
            "providers": [
                {
                    "name": "NASA OPERA",
                    "needs_account": True,
                    "signup_url": "https://urs.earthdata.nasa.gov/users/new",
                    "products": ["DSWx (water)", "DIST-ALERT (vegetation)", "DISP (deformation)"],
                },
                {
                    "name": "Copernicus EGMS",
                    "needs_account": True,
                    "signup_url": "https://dataspace.copernicus.eu/",
                    "products": ["EU ground motion velocity (mm/yr)"],
                },
                {
                    "name": "Global Flood Monitoring (GFM)",
                    "needs_account": False,
                    "signup_url": "https://global-flood.emergency.copernicus.eu/",
                    "products": ["Daily Sentinel-1 flood polygons"],
                },
                {
                    "name": "Copernicus EMS Rapid Mapping",
                    "needs_account": False,
                    "signup_url": "https://emergency.copernicus.eu/mapping/",
                    "products": ["Disaster damage GeoJSON"],
                },
                {
                    "name": "UNOSAT",
                    "needs_account": False,
                    "signup_url": "https://unosat.org/",
                    "products": ["UN damage assessments"],
                },
            ],
        },
    }


def _missing_for_products(fetch_set: bool, ack_set: bool) -> list[str]:
    missing: list[str] = []
    if not fetch_set:
        missing.append("MESH_SAR_PRODUCTS_FETCH=allow")
    if not ack_set:
        missing.append("MESH_SAR_PRODUCTS_FETCH_ACKNOWLEDGE=true")
    if not earthdata_token():
        missing.append("MESH_SAR_EARTHDATA_TOKEN (free from urs.earthdata.nasa.gov)")
    return missing


# ---------------------------------------------------------------------------
# Credentials (only used in Mode B; Mode A needs nothing)
# ---------------------------------------------------------------------------

def earthdata_user() -> str:
    return _str("MESH_SAR_EARTHDATA_USER", default="")


def earthdata_token() -> str:
    return _str("MESH_SAR_EARTHDATA_TOKEN", default="")


def copernicus_user() -> str:
    return _str("MESH_SAR_COPERNICUS_USER", default="")


def copernicus_token() -> str:
    return _str("MESH_SAR_COPERNICUS_TOKEN", default="")


# ---------------------------------------------------------------------------
# OpenClaw integration toggle
# ---------------------------------------------------------------------------

def openclaw_enabled() -> bool:
    return _flag("MESH_SAR_OPENCLAW_ENABLED", default=True)


# ---------------------------------------------------------------------------
# Mesh signing tier gate
# ---------------------------------------------------------------------------

def require_private_tier_for_publish() -> bool:
    """If true, SAR anomalies are only emitted as signed mesh events when
    the local node is at private_transitional or higher.  Default: True.
    """
    return _flag("MESH_SAR_REQUIRE_PRIVATE_TIER", default=True)
