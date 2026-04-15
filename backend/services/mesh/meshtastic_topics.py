"""Helpers for Meshtastic MQTT roots, topic parsing, and subscriptions."""

from __future__ import annotations

import re
from typing import Iterable

# Official/default region roots we actively watch on the public broker.
DEFAULT_ROOTS: tuple[str, ...] = (
    "US",
    "EU_868",
    "EU_433",
    "CN",
    "JP",
    "KR",
    "TW",
    "RU",
    "IN",
    "ANZ",
    "ANZ_433",
    "NZ_865",
    "TH",
    "UA_868",
    "UA_433",
    "MY_433",
    "MY_919",
    "SG_923",
    "LORA_24",
)

# Legacy/community roots still seen in the wild on public/community brokers.
COMMUNITY_ROOTS: tuple[str, ...] = (
    "EU",
    "AU",
    "UA",
    "BR",
    "AF",
    "ME",
    "SEA",
    "SA",
    "PL",
)

_ROOT_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_+\-]+$")
_TOPIC_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_+\-#]+$")


def _dedupe(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            out.append(value)
            seen.add(value)
    return out


def _split_config_values(raw: str) -> list[str]:
    if not raw:
        return []
    normalized = raw.replace("\n", ",").replace(";", ",")
    return [item.strip() for item in normalized.split(",") if item.strip()]


def normalize_root(value: str) -> str | None:
    """Normalize a Meshtastic root like `PL` or `US/rob/snd`."""

    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.startswith("msh/"):
        raw = raw[4:]
    raw = raw.strip("/")
    if raw.endswith("/#"):
        raw = raw[:-2].rstrip("/")
    if not raw:
        return None
    parts = [part for part in raw.split("/") if part]
    if not parts:
        return None
    if any(part in {"+", "#"} for part in parts):
        return None
    if any(not _ROOT_SEGMENT_RE.match(part) for part in parts):
        return None
    return "/".join(parts)


def normalize_topic_filter(value: str) -> str | None:
    """Normalize a full MQTT subscription filter."""

    raw = str(value or "").strip()
    if not raw:
        return None
    if not raw.startswith("msh/"):
        root = normalize_root(raw)
        return f"msh/{root}/#" if root else None
    raw = raw.strip("/")
    parts = [part for part in raw.split("/") if part]
    if not parts or parts[0] != "msh":
        return None
    if any(part != "+" and not _TOPIC_SEGMENT_RE.match(part) for part in parts[1:]):
        return None
    return "/".join(parts)


def build_subscription_topics(
    extra_roots: str = "",
    extra_topics: str = "",
    include_defaults: bool = True,
) -> list[str]:
    roots: list[str] = []
    if include_defaults:
        roots.extend(DEFAULT_ROOTS)
        roots.extend(COMMUNITY_ROOTS)
    roots.extend(root for root in (normalize_root(item) for item in _split_config_values(extra_roots)) if root)

    topics = [f"msh/{root}/#" for root in _dedupe(roots)]
    topics.extend(
        topic
        for topic in (
            normalize_topic_filter(item) for item in _split_config_values(extra_topics)
        )
        if topic
    )
    return _dedupe(topics)


def known_roots(extra_roots: str = "", include_defaults: bool = True) -> list[str]:
    topics = build_subscription_topics(extra_roots=extra_roots, include_defaults=include_defaults)
    roots: list[str] = []
    for topic in topics:
        if not topic.startswith("msh/") or not topic.endswith("/#"):
            continue
        root = normalize_root(topic[4:-2])
        if root:
            roots.append(root)
    return _dedupe(roots)


def parse_topic_metadata(topic: str) -> dict[str, str]:
    """Extract region/root/channel metadata from a Meshtastic MQTT topic."""

    parts = [part for part in str(topic or "").strip("/").split("/") if part]
    if not parts or parts[0] != "msh":
        return {"region": "?", "root": "?", "channel": "LongFast", "mode": "", "version": ""}

    mode_idx = -1
    for idx in range(1, len(parts)):
        if parts[idx] in {"e", "c", "json"}:
            mode_idx = idx
            break

    version = ""
    root_parts = parts[1:]
    channel = "LongFast"
    mode = ""
    if mode_idx != -1:
        mode = parts[mode_idx]
        maybe_version_idx = mode_idx - 1
        if maybe_version_idx >= 1 and parts[maybe_version_idx].isdigit():
            version = parts[maybe_version_idx]
            root_parts = parts[1:maybe_version_idx]
        else:
            root_parts = parts[1:mode_idx]
        if len(parts) > mode_idx + 1:
            channel = parts[mode_idx + 1]

    root = "/".join(root_parts) if root_parts else "?"
    region = root_parts[0] if root_parts else "?"
    return {
        "region": region,
        "root": root,
        "channel": channel or "LongFast",
        "mode": mode,
        "version": version,
    }
