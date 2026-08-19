"""LiveUAMap provider settings and operator-consent state.

Global Incidents is a broader Shadowbroker feature backed by GDELT regardless
of whether LiveUAMap enrichment is available. The browser provider keeps the
historical platform behavior (automatic on POSIX, opt-in on Windows) while a
configured supported API can satisfy LiveUAMap enrichment without Chromium.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_OPT_IN_FILE = Path(__file__).resolve().parent.parent / "data" / "liveuamap_scraper_opt_in.json"
_OPT_IN_LOCK = threading.Lock()


def _env_flag(name: str) -> str:
    return str(os.getenv(name, "")).strip().lower()


def _valid_https_url(raw: str) -> bool:
    try:
        parsed = urlparse(raw)
    except ValueError:
        return False
    return (
        parsed.scheme.lower() == "https"
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
    )


def liveuamap_requires_ui_opt_in() -> bool:
    """Windows local installs need an explicit choice before browser scraping."""
    return os.name == "nt"


def liveuamap_ui_choice_recorded() -> bool:
    """Whether the operator has already accepted or declined browser contact."""
    return _OPT_IN_FILE.exists()


def get_liveuamap_ui_opt_in() -> bool:
    if not _OPT_IN_FILE.exists():
        return False
    try:
        payload = json.loads(_OPT_IN_FILE.read_text(encoding="utf-8"))
        return bool(payload.get("opted_in"))
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        logger.warning("LiveUAMap opt-in file unreadable: %s", exc)
        return False


def set_liveuamap_ui_opt_in(opted_in: bool) -> None:
    """Persist an explicit browser-provider choice, including a decline."""
    _OPT_IN_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"opted_in": bool(opted_in)}, indent=2)
    with _OPT_IN_LOCK:
        temp_path = _OPT_IN_FILE.with_suffix(_OPT_IN_FILE.suffix + ".tmp")
        temp_path.write_text(payload, encoding="utf-8")
        os.replace(temp_path, _OPT_IN_FILE)


def liveuamap_api_configured() -> bool:
    """Whether an operator supplied a syntactically valid HTTPS API endpoint."""
    url = str(os.getenv("LIVEUAMAP_API_URL", "") or "").strip()
    return bool(url and _valid_https_url(url))


def liveuamap_browser_scraper_enabled() -> bool:
    """Whether the existing Playwright provider may contact LiveUAMap.

    Preserve the established UX on Linux/macOS/Docker: browser enrichment is
    available when Global Incidents is active unless explicitly disabled.
    Windows keeps the existing opt-in boundary. An environment override always
    wins for the browser provider only; it does not disable a configured API.
    """
    setting = _env_flag("SHADOWBROKER_ENABLE_LIVEUAMAP_SCRAPER")
    if setting in {"1", "true", "yes", "on"}:
        return True
    if setting in {"0", "false", "no", "off"}:
        return False
    if not liveuamap_requires_ui_opt_in():
        return True
    return get_liveuamap_ui_opt_in()


def liveuamap_scraper_enabled() -> bool:
    """Historical scheduler gate: whether *any* LiveUAMap provider can run.

    The name is retained for call-site compatibility. Supported API access is
    preferred when configured; otherwise the optional browser provider may run.
    """
    return liveuamap_api_configured() or liveuamap_browser_scraper_enabled()


def liveuamap_scraper_status() -> dict[str, Any]:
    setting = _env_flag("SHADOWBROKER_ENABLE_LIVEUAMAP_SCRAPER")
    env_override = None
    if setting in {"1", "true", "yes", "on"}:
        env_override = "on"
    elif setting in {"0", "false", "no", "off"}:
        env_override = "off"

    ui_opted_in = get_liveuamap_ui_opt_in()
    requires = liveuamap_requires_ui_opt_in()
    api_configured = liveuamap_api_configured()
    browser_enabled = liveuamap_browser_scraper_enabled()
    enrichment_enabled = api_configured or browser_enabled

    if api_configured:
        provider_mode = "api"
    elif browser_enabled:
        provider_mode = "scraper"
    else:
        provider_mode = "gdelt-only"

    return {
        # Existing fields remain stable for current frontends.
        "platform_requires_opt_in": requires,
        "ui_opted_in": ui_opted_in,
        "scraper_enabled": browser_enabled,
        "env_override": env_override,
        # Additive provider/UX diagnostics.
        "ui_choice_recorded": liveuamap_ui_choice_recorded(),
        "api_configured": api_configured,
        "enrichment_enabled": enrichment_enabled,
        "provider_mode": provider_mode,
    }
