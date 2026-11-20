"""US sanctions index via OpenSanctions (adapted from Osiris sanctions.ts).

The SDN alone is not the US list. ``us_sanctions`` adds the trade.gov Consolidated Screening List (BIS Entity List,
Military End User and Unverified lists), the OFAC non-SDN lists, the DoD 1260H Chinese military companies and the
UFLPA Entity List. The FCC Covered List is a separate OpenSanctions dataset, outside ``us_sanctions``; seven of its
13 entities (China Mobile International USA, China Telecom (Americas), Kaspersky Lab, Inc. among them) are on no
other US list there, so it is loaded next to it.
"""
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

SANCTIONS_CSV_URLS = (
    "https://data.opensanctions.org/datasets/latest/us_sanctions/targets.simple.csv",
    "https://data.opensanctions.org/datasets/latest/us_fcc_covered_list/targets.simple.csv",
)
SOURCE_LABEL = "OpenSanctions us_sanctions + us_fcc_covered_list"
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
    datasets: list[str] = field(default_factory=list)
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
            "datasets": self.datasets,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
        }


def norm_name(s: str) -> str:
    s = re.sub(r"[^\w\s]+", " ", s.lower(), flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip()


def _split_semi(val: str) -> list[str]:
    return [x.strip() for x in (val or "").split(";") if x.strip()]


def build_index(texts: list[str]) -> dict[str, Any]:
    """Index OpenSanctions simple CSVs. An entity in several files (same id) is kept once."""
    entries: list[SanctionEntry] = []
    by_id: dict[str, SanctionEntry] = {}
    by_norm: dict[str, list[SanctionEntry]] = {}
    for text in texts:
        for row in csv.DictReader(io.StringIO(text)):
            name = (row.get("name") or "").strip()
            if not name:
                continue
            entity_id = row.get("id") or ""
            datasets = _split_semi(row.get("dataset") or "")
            known = by_id.get(entity_id) if entity_id else None
            if known is not None:
                known.datasets.extend(d for d in datasets if d not in known.datasets)
                continue
            entry = SanctionEntry(
                id=entity_id,
                schema=row.get("schema") or "LegalEntity",
                name=name,
                aliases=_split_semi(row.get("aliases") or ""),
                countries=_split_semi(row.get("countries") or ""),
                programs=_split_semi(row.get("program_ids") or ""),
                sanctions=row.get("sanctions") or "",
                datasets=datasets,
                first_seen=row.get("first_seen") or None,
                last_seen=row.get("last_seen") or None,
            )
            entries.append(entry)
            if entity_id:
                by_id[entity_id] = entry
            for key in {norm_name(name), *(norm_name(a) for a in entry.aliases)}:
                if not key:
                    continue
                by_norm.setdefault(key, []).append(entry)
    return {"entries": entries, "by_norm": by_norm, "fetched_at": time.time()}


def _load_list() -> dict[str, Any]:
    global _cache, _cache_at
    with _lock:
        if _cache and (time.time() - _cache_at) < TTL_S:
            return _cache

    try:
        texts = []
        for url in SANCTIONS_CSV_URLS:
            resp = fetch_with_curl(url, timeout=45, headers={"Accept": "text/csv"})
            if resp.status_code != 200:
                raise RuntimeError(f"OpenSanctions HTTP {resp.status_code} for {url}")
            texts.append(resp.text)
        loaded = build_index(texts)
        with _lock:
            _cache = loaded
            _cache_at = time.time()
        logger.info("US sanctions index loaded: %s entries", len(loaded["entries"]))
        return loaded
    except Exception as exc:
        logger.error("US sanctions load failed: %s", exc)
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
