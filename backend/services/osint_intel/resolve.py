"""Entity graph resolver (Python port of Osiris intel/server.js)."""
from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any
from urllib.parse import quote

from services.network_utils import fetch_with_curl
from services.sanctions.ofac import match_exact, search_sanctions

logger = logging.getLogger(__name__)

ALLOWED_TYPES = frozenset({"aircraft", "vessel", "company", "person", "ip", "country"})
_WD_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_WD_LOCK = threading.Lock()
_WD_TTL = 24 * 60 * 60
_WD_UA = "Shadowbroker-Intel/1.0 (ontology engine)"


def _dedup(nodes: list[dict], links: list[dict]) -> dict[str, Any]:
    node_map: dict[str, dict] = {}
    for n in nodes:
        node_map[n["id"]] = n
    seen_links: set[str] = set()
    out_links: list[dict] = []
    for link in links:
        key = f"{link['source']}→{link['target']}→{link['label']}"
        if key in seen_links:
            continue
        seen_links.add(key)
        out_links.append(link)
    return {"nodes": list(node_map.values()), "links": out_links}


def _wd_cache_get(key: str) -> dict[str, Any] | None:
    with _WD_LOCK:
        entry = _WD_CACHE.get(key)
        if not entry:
            return None
        ts, data = entry
        if time.time() - ts > _WD_TTL:
            _WD_CACHE.pop(key, None)
            return None
        return data


def _wd_cache_set(key: str, data: dict[str, Any]) -> None:
    with _WD_LOCK:
        if len(_WD_CACHE) > 5000:
            oldest = next(iter(_WD_CACHE))
            _WD_CACHE.pop(oldest, None)
        _WD_CACHE[key] = (time.time(), data)


def _add_sanctions(id_label: str, root_id: str, nodes: list, links: list) -> None:
    for hit in search_sanctions(id_label, limit=3):
        sid = f"sanction:{hit['id']}"
        nodes.append(
            {
                "id": sid,
                "label": hit["name"],
                "type": "sanction",
                "properties": {"programs": hit.get("programs"), "source": "OFAC SDN"},
            }
        )
        links.append({"source": root_id, "target": sid, "label": "SANCTIONS MATCH"})


def _sparql(query: str) -> list[dict[str, Any]]:
    url = f"https://query.wikidata.org/sparql?query={quote(query)}&format=json"
    resp = fetch_with_curl(url, timeout=10, headers={"User-Agent": _WD_UA, "Accept": "application/sparql-results+json"})
    if resp.status_code != 200:
        return []
    try:
        data = resp.json()
    except Exception:
        return []
    return data.get("results", {}).get("bindings", [])


def _wd_search(label: str) -> str | None:
    url = (
        "https://www.wikidata.org/w/api.php?action=wbsearchentities"
        f"&search={quote(label)}&language=en&limit=1&format=json"
    )
    resp = fetch_with_curl(url, timeout=5, headers={"User-Agent": _WD_UA})
    if resp.status_code != 200:
        return None
    try:
        hits = resp.json().get("search") or []
    except Exception:
        return None
    return hits[0]["id"] if hits else None


def _resolve_ip(id_value: str) -> dict[str, Any]:
    cache_key = f"ip:{id_value}"
    cached = _wd_cache_get(cache_key)
    if cached:
        return cached

    root_id = f"ip:{id_value}"
    nodes: list[dict] = [{"id": root_id, "label": id_value, "type": "ip", "properties": {}}]
    links: list[dict] = []

    geo = fetch_with_curl(
        f"https://ip-api.com/json/{quote(id_value)}"
        "?fields=status,country,countryCode,city,lat,lon,isp,org,as,asname,proxy,hosting,mobile",
        timeout=8,
    )
    if geo.status_code == 200:
        try:
            data = geo.json()
        except Exception:
            data = {}
        if data.get("status") == "success":
            nodes[0]["properties"] = {
                "proxy": bool(data.get("proxy")),
                "hosting": bool(data.get("hosting")),
                "mobile": bool(data.get("mobile")),
                "source": "ip-api.com",
            }
            if data.get("isp"):
                iid = f"company:{data['isp']}"
                nodes.append({"id": iid, "label": data["isp"], "type": "company", "properties": {"role": "ISP"}})
                links.append({"source": root_id, "target": iid, "label": "HOSTED_BY"})
            if data.get("country"):
                cid = f"country:{data['country']}"
                nodes.append(
                    {
                        "id": cid,
                        "label": data["country"],
                        "type": "country",
                        "properties": {"code": data.get("countryCode")},
                    }
                )
                links.append({"source": root_id, "target": cid, "label": "LOCATED_IN"})
            for val in (data.get("isp"), data.get("org"), data.get("asname")):
                if val:
                    for entry in match_exact(val):
                        sid = f"sanction:{entry['id']}"
                        nodes.append({"id": sid, "label": entry["name"], "type": "sanction", "properties": {}})
                        links.append({"source": root_id, "target": sid, "label": "SANCTIONS MATCH"})

    whois = fetch_with_curl(
        f"https://stat.ripe.net/data/whois/data.json?resource={quote(id_value)}",
        timeout=8,
    )
    if whois.status_code == 200:
        try:
            records = whois.json().get("data", {}).get("records") or []
        except Exception:
            records = []
        for record in records:
            for field in record:
                if field.get("key") in ("netname", "NetName"):
                    nid = f"company:{field['value']}"
                    nodes.append({"id": nid, "label": field["value"], "type": "company", "properties": {"role": "Network"}})
                    links.append({"source": root_id, "target": nid, "label": "HOSTED_BY"})

    result = _dedup(nodes, links)
    _wd_cache_set(cache_key, result)
    return result


def _resolve_company(id_value: str) -> dict[str, Any]:
    cache_key = f"company:{id_value}"
    cached = _wd_cache_get(cache_key)
    if cached:
        return cached
    root_id = f"company:{id_value}"
    nodes = [{"id": root_id, "label": id_value, "type": "company", "properties": {}}]
    links: list[dict] = []
    safe = re.sub(r'[^a-zA-Z0-9 \-._]', '', id_value).strip()
    qid = _wd_search(safe)
    filt = f"VALUES ?item {{ wd:{qid} }}" if qid else f'?item rdfs:label "{safe}"@en . ?item wdt:P31/wdt:P279* wd:Q4830453 .'
    rows = _sparql(
        f"""
        SELECT ?countryLabel ?parentLabel ?ceoLabel WHERE {{
          {filt}
          OPTIONAL {{ ?item wdt:P17 ?country . }}
          OPTIONAL {{ ?item wdt:P749 ?parent . }}
          OPTIONAL {{ ?item wdt:P169 ?ceo . }}
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" . }}
        }} LIMIT 10
        """
    )
    for row in rows:
        if row.get("countryLabel", {}).get("value"):
            cid = f"country:{row['countryLabel']['value']}"
            nodes.append({"id": cid, "label": row["countryLabel"]["value"], "type": "country", "properties": {}})
            links.append({"source": root_id, "target": cid, "label": "HEADQUARTERED"})
        if row.get("parentLabel", {}).get("value"):
            pid = f"company:{row['parentLabel']['value']}"
            nodes.append({"id": pid, "label": row["parentLabel"]["value"], "type": "company", "properties": {}})
            links.append({"source": root_id, "target": pid, "label": "PARENT ORG"})
        if row.get("ceoLabel", {}).get("value"):
            pid = f"person:{row['ceoLabel']['value']}"
            nodes.append({"id": pid, "label": row["ceoLabel"]["value"], "type": "person", "properties": {"role": "CEO"}})
            links.append({"source": root_id, "target": pid, "label": "CEO"})
    _add_sanctions(id_value, root_id, nodes, links)
    result = _dedup(nodes, links)
    _wd_cache_set(cache_key, result)
    return result


def _resolve_from_store(entity_type: str, id_value: str, props: dict[str, Any]) -> dict[str, Any]:
    from services.fetchers._store import get_latest_data_subset_refs

    root_id = f"{entity_type}:{id_value}"
    nodes = [{"id": root_id, "label": props.get("label") or id_value, "type": entity_type, "properties": props}]
    links: list[dict] = []
    data = get_latest_data_subset_refs("flights", "ships", "military_flights", "tracked_flights")

    if entity_type == "aircraft":
        icao = (props.get("icao24") or id_value).lower()
        for bucket in ("military_flights", "tracked_flights", "flights"):
            for f in data.get(bucket) or []:
                if str(f.get("icao24", "")).lower() == icao:
                    if f.get("country"):
                        cid = f"country:{f['country']}"
                        nodes.append({"id": cid, "label": f["country"], "type": "country", "properties": {}})
                        links.append({"source": root_id, "target": cid, "label": "REGISTERED_IN"})
                    if f.get("registration"):
                        nodes[0]["properties"]["registration"] = f["registration"]
                    break
    elif entity_type == "vessel":
        mmsi = str(props.get("mmsi") or id_value)
        for ship in data.get("ships") or []:
            if str(ship.get("mmsi")) == mmsi:
                if ship.get("country"):
                    cid = f"country:{ship['country']}"
                    nodes.append({"id": cid, "label": ship["country"], "type": "country", "properties": {}})
                    links.append({"source": root_id, "target": cid, "label": "FLAG"})
                break
    _add_sanctions(id_value, root_id, nodes, links)
    return _dedup(nodes, links)


def resolve_entity(entity_type: str, id_value: str, properties: dict[str, Any] | None = None) -> dict[str, Any]:
    etype = (entity_type or "").lower().strip()
    eid = (id_value or "").strip()
    if etype not in ALLOWED_TYPES:
        raise ValueError(f"Invalid type. Allowed: {', '.join(sorted(ALLOWED_TYPES))}")
    if len(eid) < 2 or len(eid) > 200:
        raise ValueError("Invalid id (2-200 chars)")
    props = properties or {}

    if etype == "ip":
        return _resolve_ip(eid)
    if etype in ("company", "person", "country"):
        if etype == "company":
            return _resolve_company(eid)
        if etype == "person":
            root_id = f"person:{eid}"
            nodes = [{"id": root_id, "label": eid, "type": "person", "properties": {}}]
            links: list[dict] = []
            _add_sanctions(eid, root_id, nodes, links)
            return _dedup(nodes, links)
        root_id = f"country:{eid}"
        nodes = [{"id": root_id, "label": eid, "type": "country", "properties": {}}]
        links = []
        _add_sanctions(eid, root_id, nodes, links)
        return _dedup(nodes, links)
    return _resolve_from_store(etype, eid, props)
