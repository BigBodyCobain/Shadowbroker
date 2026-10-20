"""Configuration for Strategic Risk Analytics (feature-flagged)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any


def _env_bool(name: str, default: bool = False) -> bool:
    raw = str(os.environ.get(name, "")).strip().lower()
    if not raw:
        return default
    return raw not in {"0", "false", "no", "off"}


def _env_float(name: str, default: float) -> float:
    raw = str(os.environ.get(name, "")).strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = str(os.environ.get(name, "")).strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _parse_signal_weights(raw: str) -> dict[str, float]:
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return {str(k): float(v) for k, v in parsed.items()}
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    weights: dict[str, float] = {}
    for part in raw.split(","):
        piece = part.strip()
        if not piece or "=" not in piece:
            continue
        key, value = piece.split("=", 1)
        try:
            weights[key.strip()] = float(value.strip())
        except ValueError:
            continue
    return weights


def resolve_gt_profile() -> str:
    from services.runtime_profile import resolve_profile_name

    return resolve_profile_name()


def gt_analytics_ack_low_cpu() -> bool:
    return _env_bool("GT_ANALYTICS_ACK_LOW_CPU", default=False)


def gt_engine_operational() -> bool:
    """Full GT engine (scheduled ingest, heatmap, Louvain) — not watchdog-only."""
    if not get_gt_settings().enabled:
        return False
    if resolve_gt_profile() == "lean" and not gt_analytics_ack_low_cpu():
        return False
    return True


def gt_scheduled_ingest_enabled() -> bool:
    return gt_engine_operational()


def gt_louvain_enabled() -> bool:
    return gt_engine_operational()


@dataclass(frozen=True)
class GTAnalyticsSettings:
    enabled: bool = False
    profile: str = "standard"
    base_prior: float = 0.15
    evidence_cap: float = 3.0
    evidence_scale: float = 5.0
    min_prob: float = 0.01
    max_prob: float = 0.99
    high_risk_threshold: float = 0.6
    max_history_per_region: int = 200
    max_heatmap_features: int = 500
    louvain_min_weight: float = 0.5
    louvain_interval_minutes: int = 30
    signal_weight_overrides: dict[str, float] = field(default_factory=dict)
    watched_channels: tuple[str, ...] = ()


@lru_cache(maxsize=1)
def get_gt_settings() -> GTAnalyticsSettings:
    channels_raw = str(os.environ.get("GT_ANALYTICS_WATCHED_CHANNELS", "")).strip()
    channels = tuple(
        part.strip().lstrip("@")
        for part in channels_raw.split(",")
        if part.strip()
    )
    profile = resolve_gt_profile()
    lean = profile == "lean"
    return GTAnalyticsSettings(
        enabled=_env_bool("GT_ANALYTICS_ENABLED", default=False),
        profile=profile,
        base_prior=_env_float("GT_ANALYTICS_BASE_PRIOR", 0.15),
        evidence_cap=_env_float("GT_ANALYTICS_EVIDENCE_CAP", 3.0),
        evidence_scale=_env_float("GT_ANALYTICS_EVIDENCE_SCALE", 5.0),
        min_prob=_env_float("GT_ANALYTICS_MIN_PROB", 0.01),
        max_prob=_env_float("GT_ANALYTICS_MAX_PROB", 0.99),
        high_risk_threshold=_env_float("GT_ANALYTICS_HIGH_RISK_THRESHOLD", 0.6),
        max_history_per_region=_env_int("GT_ANALYTICS_MAX_HISTORY", 200),
        max_heatmap_features=_env_int(
            "GT_ANALYTICS_MAX_HEATMAP_FEATURES",
            50 if lean else 500,
        ),
        louvain_min_weight=_env_float("GT_ANALYTICS_LOUVAIN_MIN_WEIGHT", 0.5),
        louvain_interval_minutes=max(5, _env_int("GT_ANALYTICS_LOUVAIN_INTERVAL_MINUTES", 30)),
        signal_weight_overrides=_parse_signal_weights(
            str(os.environ.get("GT_ANALYTICS_SIGNAL_WEIGHTS", ""))
        ),
        watched_channels=channels,
    )


def gt_analytics_enabled() -> bool:
    return get_gt_settings().enabled


def gt_analytics_status() -> dict[str, Any]:
    settings = get_gt_settings()
    from services.runtime_profile import get_runtime_profile

    runtime = get_runtime_profile()
    operational = gt_engine_operational()
    return {
        "enabled": settings.enabled,
        "operational": operational,
        "profile": settings.profile,
        "ack_low_cpu": gt_analytics_ack_low_cpu(),
        "recommended": bool(runtime.get("gt_analytics", {}).get("recommended")),
        "lean_node": bool(runtime.get("gt_analytics", {}).get("lean_node")),
        "warning": runtime.get("gt_analytics", {}).get("warning"),
        "experimental": True,
    }