"""Container-aware runtime limits for fleet vs desktop deployments."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any


def _read_first_int(path: Path) -> int | None:
    try:
        raw = path.read_text(encoding="utf-8").strip().split()[0]
        return int(raw)
    except (OSError, ValueError, IndexError):
        return None


def detect_cpu_limit() -> float | None:
    """Effective CPU cores from cgroup quota (Docker ``cpus:``), else host count."""
    cgroup_v2 = Path("/sys/fs/cgroup/cpu.max")
    if cgroup_v2.is_file():
        try:
            parts = cgroup_v2.read_text(encoding="utf-8").strip().split()
            if len(parts) >= 2 and parts[0] != "max":
                quota = int(parts[0])
                period = int(parts[1])
                if quota > 0 and period > 0:
                    return round(quota / period, 3)
        except (OSError, ValueError):
            pass

    cgroup_v1_quota = Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
    cgroup_v1_period = Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us")
    if cgroup_v1_quota.is_file() and cgroup_v1_period.is_file():
        quota = _read_first_int(cgroup_v1_quota)
        period = _read_first_int(cgroup_v1_period)
        if quota is not None and period and quota > 0:
            return round(quota / period, 3)

    try:
        import os as _os

        count = _os.cpu_count()
        return float(count) if count else None
    except Exception:
        return None


def detect_memory_limit_mb() -> int | None:
    cgroup_v2 = Path("/sys/fs/cgroup/memory.max")
    if cgroup_v2.is_file():
        try:
            raw = cgroup_v2.read_text(encoding="utf-8").strip()
            if raw and raw != "max":
                return int(int(raw) / (1024 * 1024))
        except (OSError, ValueError):
            pass

    cgroup_v1 = Path("/sys/fs/cgroup/memory/memory.limit_in_bytes")
    if cgroup_v1.is_file():
        try:
            raw = _read_first_int(cgroup_v1)
            if raw is not None and raw < (1 << 62):
                return int(raw / (1024 * 1024))
        except (OSError, ValueError):
            pass
    return None


def resolve_profile_name() -> str:
    explicit = str(os.environ.get("GT_ANALYTICS_PROFILE", "")).strip().lower()
    if explicit in {"lean", "standard"}:
        return explicit
    cpu = detect_cpu_limit()
    if cpu is not None and cpu <= 1.0:
        return "lean"
    return "standard"


@lru_cache(maxsize=1)
def get_runtime_profile() -> dict[str, Any]:
    cpu_limit = detect_cpu_limit()
    memory_mb = detect_memory_limit_mb()
    profile = resolve_profile_name()
    lean = profile == "lean"
    return {
        "profile": profile,
        "cpu_limit": cpu_limit,
        "memory_limit_mb": memory_mb,
        "gt_analytics": {
            "recommended": not lean,
            "lean_node": lean,
            "warning": (
                "This node is capped at 1 vCPU. Enabling Strategic Risk (Derived OSINT) "
                "may slow Telegram, GDELT, and other OSINT fetches. Set "
                "GT_ANALYTICS_ACK_LOW_CPU=true after enabling GT_ANALYTICS_ENABLED to run "
                "the full engine on lean hardware."
                if lean
                else None
            ),
        },
    }


def clear_runtime_profile_cache() -> None:
    get_runtime_profile.cache_clear()
