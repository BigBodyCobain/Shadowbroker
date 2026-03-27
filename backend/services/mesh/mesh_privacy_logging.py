"""Helpers for privacy-aware operational logging.

These helpers keep logs useful for debugging classes of failures without
recording stable private-plane identifiers verbatim.
"""

from __future__ import annotations

import hashlib


def privacy_log_label(value: str, *, label: str = "") -> str:
    raw = str(value or "").strip()
    if not raw:
        return f"{label}#none" if label else ""
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    if not label:
        return digest
    return f"{label}#{digest}"
