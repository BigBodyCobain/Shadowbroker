"""Operator opt-in for Polymarket/Kalshi outbound fetches (Global Threat Intercept)."""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_OPT_IN_FILE = Path(__file__).resolve().parent.parent / "data" / "prediction_markets_opt_in.json"
_OPT_IN_LOCK = threading.Lock()


def _env_flag(name: str) -> str:
    return str(os.getenv(name, "")).strip().lower()


def get_prediction_markets_ui_opt_in() -> bool:
    if not _OPT_IN_FILE.exists():
        return False
    try:
        payload = json.loads(_OPT_IN_FILE.read_text(encoding="utf-8"))
        return bool(payload.get("opted_in"))
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        logger.warning("Prediction markets opt-in file unreadable: %s", exc)
        return False


def set_prediction_markets_ui_opt_in(opted_in: bool) -> None:
    _OPT_IN_FILE.parent.mkdir(parents=True, exist_ok=True)
    with _OPT_IN_LOCK:
        _OPT_IN_FILE.write_text(
            json.dumps({"opted_in": bool(opted_in)}, indent=2),
            encoding="utf-8",
        )


def prediction_markets_env_forced_on() -> bool:
    return _env_flag("PREDICTION_MARKETS_ENABLED") in {"1", "true", "yes", "on"}


def prediction_markets_env_forced_off() -> bool:
    return _env_flag("PREDICTION_MARKETS_ENABLED") in {"0", "false", "no", "off"}


def prediction_markets_fetch_enabled() -> bool:
    """True when UI opt-in or env enables Polymarket/Kalshi pulls."""
    if get_prediction_markets_ui_opt_in():
        return True
    return prediction_markets_env_forced_on()


def prediction_markets_status() -> dict[str, Any]:
    ui_opted_in = get_prediction_markets_ui_opt_in()
    env_on = prediction_markets_env_forced_on()
    env_off = prediction_markets_env_forced_off()
    env_override = None
    if env_on:
        env_override = "on"
    elif env_off:
        env_override = "off"
    return {
        "enabled": prediction_markets_fetch_enabled(),
        "ui_opted_in": ui_opted_in,
        "env_override": env_override,
        "jitter": {
            "scheduler_interval_minutes": int(
                os.environ.get("PREDICTION_MARKETS_INTERVAL_MINUTES", "7")
            ),
            "scheduler_jitter_seconds": int(
                os.environ.get("PREDICTION_MARKETS_SCHEDULER_JITTER_S", "240")
            ),
            "pre_fetch_jitter_seconds": float(
                os.environ.get("PREDICTION_MARKETS_PRE_FETCH_JITTER_S", "90")
            ),
        },
    }
