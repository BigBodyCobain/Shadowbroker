"""Operator settings for the embedded agent shell (working directory)."""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SETTINGS_FILE = Path(__file__).resolve().parent.parent / "data" / "agent_shell_settings.json"
_LOCK = threading.Lock()


def _default_working_directory() -> str:
    explicit = str(os.environ.get("AGENT_SHELL_DEFAULT_CWD") or "").strip()
    if explicit and os.path.isdir(explicit):
        return explicit
    home = str(os.environ.get("HOME") or "").strip()
    if home and home != "/nonexistent" and os.path.isdir(home):
        return home
    return "/app"


def get_agent_shell_settings() -> dict[str, Any]:
    with _LOCK:
        if not _SETTINGS_FILE.exists():
            return {"working_directory": _default_working_directory()}
        try:
            payload = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("agent_shell_settings_unreadable")
            return {"working_directory": _default_working_directory()}
    cwd = str(payload.get("working_directory") or "").strip() or _default_working_directory()
    return {"working_directory": cwd}


def set_agent_shell_working_directory(path: str) -> dict[str, Any]:
    normalized = str(path or "").strip()
    if not normalized:
        raise ValueError("working_directory_required")
    resolved = os.path.abspath(os.path.expanduser(normalized))
    if not os.path.isdir(resolved):
        raise ValueError("working_directory_not_found")
    with _LOCK:
        _SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _SETTINGS_FILE.write_text(
            json.dumps({"working_directory": resolved}, indent=2) + "\n",
            encoding="utf-8",
        )
    return {"working_directory": resolved}
