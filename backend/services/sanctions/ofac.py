"""OFAC SDN search index with QazLake cutover support.

Local/compare mode reads the official U.S. Treasury OFAC XML publication.
QazPipe mode reads the protected, provider-neutral QazLake projection and
never silently returns to the local collector when that feed is unavailable.
"""

from __future__ import annotations

import io
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from xml.etree import ElementTree as ET

from services.network_utils import fetch_with_curl, outbound_user_agent

logger = logging.getLogger(__name__)

SDN_XML_URL = (
    "https://sanctionslistservice.ofac.treas.gov/"
    "api/PublicationPreview/exports/SDN.XML"
)
TTL_S = 24 * 60 * 60

_lock = threading.Lock()
_cache: dict[str, Any] | None = None
_cache_at: float = 0.0


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


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(parent: ET.Element, name: str) -> str:
    for child in parent:
        if _local_name(child.tag) == name:
            return str(child.text or "").strip()
    return ""


def _descendant_texts(parent: ET.Element, name: str) -> list[str]:
    return sorted(
        {
            str(child.text or "").strip()
            for child in parent.iter()
            if _local_name(child.tag) == name and str(child.text or "").strip()
        }
    )


def _display_name(parent: ET.Element) -> str:
    return " ".join(
        part
        for part in (_child_text(parent, "firstName"), _child_text(parent, "lastName"))
        if part
    ).strip()


def _schema(listing_type: str) -> str:
    return {
        "Individual": "Person",
        "Entity": "LegalEntity",
        "Vessel": "Vessel",
        "Aircraft": "Airplane",
    }.get(listing_type, listing_type or "LegalEntity")


def _published_at(value: str) -> str:
    return datetime.strptime(value, "%m/%d/%Y").replace(tzinfo=UTC).isoformat()


def _entry_from_xml(entry: ET.Element, *, published_at: str) -> SanctionEntry | None:
    uid = _child_text(entry, "uid")
    name = _display_name(entry)
    if not uid or not name:
        return None
    aliases: set[str] = set()
    for child in entry:
        if _local_name(child.tag) != "akaList":
            continue
        for aka in child:
            alias = _display_name(aka)
            if alias and alias != name:
                aliases.add(alias)
    programs = _descendant_texts(entry, "program")
    return SanctionEntry(
        id=uid,
        schema=_schema(_child_text(entry, "sdnType")),
        name=name,
        aliases=sorted(aliases),
        countries=_descendant_texts(entry, "country"),
        programs=programs,
        sanctions="; ".join(programs),
        first_seen=published_at,
        last_seen=published_at,
    )


def _parse_sdn_xml(content: bytes) -> list[SanctionEntry]:
    published_raw = ""
    entries: list[SanctionEntry] = []
    for _event, element in ET.iterparse(io.BytesIO(content), events=("end",)):
        name = _local_name(element.tag)
        if name == "Publish_Date":
            published_raw = str(element.text or "").strip()
        elif name == "sdnEntry":
            if not published_raw:
                raise ValueError("OFAC SDN XML omits publication date before entries")
            parsed = _entry_from_xml(element, published_at=_published_at(published_raw))
            if parsed is not None:
                entries.append(parsed)
            element.clear()
    if not published_raw or not entries:
        raise ValueError("OFAC SDN XML yielded no valid targets")
    return entries


def _index(entries: list[SanctionEntry], *, fetched_at: float) -> dict[str, Any]:
    by_norm: dict[str, list[SanctionEntry]] = {}
    for entry in entries:
        for key in {norm_name(entry.name), *(norm_name(a) for a in entry.aliases)}:
            if key:
                by_norm.setdefault(key, []).append(entry)
    return {"entries": entries, "by_norm": by_norm, "fetched_at": fetched_at}


def _load_primary_list() -> dict[str, Any]:
    global _cache, _cache_at
    with _lock:
        if _cache and (time.time() - _cache_at) < TTL_S:
            return _cache
    try:
        response = fetch_with_curl(
            SDN_XML_URL,
            timeout=90,
            headers={
                "Accept": "application/xml,text/xml",
                "User-Agent": outbound_user_agent("ofac-sdn"),
            },
        )
        if response.status_code != 200:
            raise RuntimeError(f"OFAC Sanctions List Service HTTP {response.status_code}")
        content = bytes(response.content)
        if not content.lstrip().startswith(b"<?xml"):
            raise ValueError("OFAC Sanctions List Service did not return XML")
        entries = _parse_sdn_xml(content)
        loaded = _index(entries, fetched_at=time.time())
        with _lock:
            _cache = loaded
            _cache_at = time.time()
        logger.info("Official OFAC SDN index loaded: %s entries", len(entries))
        return loaded
    except Exception as exc:
        logger.error("Official OFAC SDN load failed: %s", type(exc).__name__)
        with _lock:
            if _cache:
                return _cache
        raise


def _entry_from_projection(row: dict[str, Any]) -> SanctionEntry | None:
    name = str(row.get("name") or "").strip()
    entry_id = str(row.get("id") or row.get("entity_id") or "").strip()
    if not name or not entry_id:
        return None
    programs = [str(value) for value in row.get("programs") or []]
    return SanctionEntry(
        id=entry_id,
        schema=str(row.get("schema") or "LegalEntity"),
        name=name,
        aliases=[str(value) for value in row.get("aliases") or []],
        countries=[str(value) for value in row.get("countries") or []],
        programs=programs,
        sanctions=str(row.get("sanctions") or "; ".join(programs)),
        first_seen=row.get("first_seen"),
        last_seen=row.get("last_seen"),
    )


def _load_list() -> dict[str, Any]:
    from services.qazlake_shadow_feed import (
        apply_layer_source_modes,
        configured_modes,
    )

    mode = configured_modes().get("risk_reference_public", "local")
    local = (
        _index([], fetched_at=time.time())
        if mode == "qazpipe"
        else _load_primary_list()
    )

    payload = apply_layer_source_modes(
        {"sanctions": [entry.to_dict() for entry in local["entries"]]},
        endpoint="/api/osint/sanctions",
    )
    projected = payload.get("sanctions")
    if not isinstance(projected, list):
        projected = []
    entries = [
        entry
        for row in projected
        if isinstance(row, dict)
        if (entry := _entry_from_projection(row)) is not None
    ]
    return _index(entries, fetched_at=float(local["fetched_at"]))


def match_exact(query: str) -> list[dict[str, Any]]:
    if not query or len(query) < 3:
        return []
    data = _load_list()
    hits = data["by_norm"].get(norm_name(query), [])
    return [e.to_dict() for e in hits]


def search_sanctions(
    query: str, *, schema: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
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
