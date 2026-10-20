"""OFAC SDN index via OpenSanctions (adapted from Osiris sanctions.ts)."""
from __future__ import annotations

import csv
import io
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from services.network_utils import fetch_with_curl

logger = logging.getLogger(__name__)

SDN_CSV_URL = "https://data.opensanctions.org/datasets/latest/us_ofac_sdn/targets.simple.csv"
TTL_S = 24 * 60 * 60

_lock = threading.Lock()
_cache: dict[str, Any] | None = None
_cache_at: float = 0.0
_inflight: threading.Event | None = None


@dataclass
class SanctionEntry:
    id: str
    schema: str
    name: str
    aliases: list[str] = field(default_factory=list)
    countries: list[str] = field(default_factory=list)
    programs: list[str] = field(default_factory=list)
    sanctions: str = ""
    first_seen: str | None = None
    last_seen: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "schema": self.schema,
            "name": self.name,
            "aliases": self.aliases,
            "countries": self.countries,
            "programs": self.programs,
            "sanctions": self.sanctions,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
        }


def norm_name(s: str) -> str:
    s = re.sub(r"[^\w\s]+", " ", s.lower(), flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip()


def _split_semi(val: str) -> list[str]:
    return [x.strip() for x in (val or "").split(";") if x.strip()]


def _load_list() -> dict[str, Any]:
    global _cache, _cache_at
    with _lock:
        if _cache and (time.time() - _cache_at) < TTL_S:
            return _cache

    try:
        resp = fetch_with_curl(SDN_CSV_URL, timeout=45, headers={"Accept": "text/csv"})
        if resp.status_code != 200:
            raise RuntimeError(f"OpenSanctions HTTP {resp.status_code}")
        text = resp.text
        reader = csv.DictReader(io.StringIO(text))
        entries: list[SanctionEntry] = []
        by_norm: dict[str, list[SanctionEntry]] = {}
        for row in reader:
            name = (row.get("name") or "").strip()
            if not name:
                continue
            entry = SanctionEntry(
                id=row.get("id") or "",
                schema=row.get("schema") or "LegalEntity",
                name=name,
                aliases=_split_semi(row.get("aliases") or ""),
                countries=_split_semi(row.get("countries") or ""),
                programs=_split_semi(row.get("program_ids") or ""),
                sanctions=row.get("sanctions") or "",
                first_seen=row.get("first_seen") or None,
                last_seen=row.get("last_seen") or None,
            )
            entries.append(entry)
            for key in {norm_name(name), *(norm_name(a) for a in entry.aliases)}:
                if not key:
                    continue
                by_norm.setdefault(key, []).append(entry)
        loaded = {"entries": entries, "by_norm": by_norm, "fetched_at": time.time()}
        with _lock:
            _cache = loaded
            _cache_at = time.time()
        logger.info("OFAC SDN index loaded: %s entries", len(entries))
        return loaded
    except Exception as exc:
        logger.error("OFAC SDN load failed: %s", exc)
        with _lock:
            if _cache:
                return _cache
        raise


def match_exact(query: str) -> list[dict[str, Any]]:
    if not query or len(query) < 3:
        return []
    data = _load_list()
    hits = data["by_norm"].get(norm_name(query), [])
    return [e.to_dict() for e in hits]


def search_sanctions(query: str, *, schema: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    if not query or len(query) < 4:
        return []
    data = _load_list()
    q = norm_name(query)
    exact_name: list[SanctionEntry] = []
    exact_alias: list[SanctionEntry] = []
    sub_name: list[SanctionEntry] = []
    sub_alias: list[SanctionEntry] = []
    seen: set[str] = set()

    def push(bucket: list[SanctionEntry], entry: SanctionEntry) -> None:
        if entry.id in seen:
            return
        if schema and entry.schema != schema:
            return
        seen.add(entry.id)
        bucket.append(entry)

    for entry in data["entries"]:
        name_norm = norm_name(entry.name)
        if name_norm == q:
            push(exact_name, entry)
        elif any(norm_name(a) == q for a in entry.aliases):
            push(exact_alias, entry)
        elif q in name_norm:
            push(sub_name, entry)
        elif any(q in norm_name(a) for a in entry.aliases):
            push(sub_alias, entry)
        if len(seen) >= limit * 4:
            break

    ordered = exact_name + exact_alias + sub_name + sub_alias
    return [e.to_dict() for e in ordered[:limit]]


def index_size() -> int:
    return len(_load_list()["entries"])
