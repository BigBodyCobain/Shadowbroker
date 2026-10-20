"""OpenClaw dispatch for the operator recon / OSINT lookup toolkit."""
from __future__ import annotations

from typing import Any

from services.osint import lookups
from services.osint_intel.resolve import ALLOWED_TYPES, resolve_entity

_OSINT_TOOLS: dict[str, str] = {
    "ip": "ip",
    "dns": "domain",
    "whois": "domain",
    "certs": "domain",
    "threats": "query",
    "bgp": "query",
    "sanctions": "query",
    "cve": "cve",
    "mac": "mac",
    "github": "username",
    "leaks": "email",
    "sweep_init": "ip",
}

_ENTITY_SCHEMAS = frozenset({
    "Person",
    "Organization",
    "Company",
    "Vessel",
    "Airplane",
    "LegalEntity",
})


def _require_str(args: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(args.get(key, "") or "").strip()
        if value:
            return value
    joined = "/".join(keys)
    raise ValueError(f"Missing required argument: {joined}")


def run_osint_lookup(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    """Run a passive OSINT lookup (same backends as /api/osint/*)."""
    name = str(tool or "").strip().lower().replace("-", "_")
    if name not in _OSINT_TOOLS:
        allowed = ", ".join(sorted(_OSINT_TOOLS))
        raise ValueError(f"Unknown OSINT tool '{tool}'. Allowed: {allowed}")

    if name == "ip":
        return lookups.lookup_ip(_require_str(args, "ip", "query", "value"))
    if name == "dns":
        return lookups.lookup_dns(_require_str(args, "domain", "query", "value"))
    if name == "whois":
        return lookups.lookup_whois(_require_str(args, "domain", "query", "value"))
    if name == "certs":
        return lookups.lookup_certs(_require_str(args, "domain", "query", "value"))
    if name == "threats":
        query = str(args.get("query", "") or args.get("value", "") or "").strip() or None
        return lookups.lookup_threats(query)
    if name == "bgp":
        return lookups.lookup_bgp(_require_str(args, "query", "asn", "value"))
    if name == "sanctions":
        query = _require_str(args, "query", "name", "value")
        schema = str(args.get("schema", "") or "").strip() or None
        if schema and schema not in _ENTITY_SCHEMAS:
            allowed = ", ".join(sorted(_ENTITY_SCHEMAS))
            raise ValueError(f"Invalid schema. Allowed: {allowed}")
        limit = args.get("limit", 25)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 25
        limit = max(1, min(100, limit))
        return lookups.lookup_sanctions(query, schema=schema, limit=limit)
    if name == "cve":
        return lookups.lookup_cve(_require_str(args, "cve", "query", "value"))
    if name == "mac":
        return lookups.lookup_mac(_require_str(args, "mac", "query", "value"))
    if name == "github":
        return lookups.lookup_github(_require_str(args, "username", "user", "query", "value"))
    if name == "leaks":
        return lookups.lookup_leaks(_require_str(args, "email", "query", "value"))
    if name == "sweep_init":
        ip = _require_str(args, "ip", "query", "value")
        cidr = args.get("cidr", 24)
        try:
            cidr = int(cidr)
        except (TypeError, ValueError):
            cidr = 24
        return lookups.sweep_init(ip, cidr)

    raise ValueError(f"Unhandled OSINT tool: {name}")


def run_osint_sweep(args: dict[str, Any]) -> dict[str, Any]:
    """Run subnet device discovery (Shodan InternetDB proxy). Requires full access tier."""
    ip = _require_str(args, "ip", "query", "value")
    cidr = args.get("cidr", 24)
    try:
        cidr = int(cidr)
    except (TypeError, ValueError):
        cidr = 24
    subnet = lookups.subnet_start_for(ip, cidr)
    scan = lookups.sweep_scan(subnet, cidr)
    init = lookups.sweep_init(ip, cidr)
    return {**init, **scan, "subnet": f"{subnet}/{cidr}"}


def run_entity_expand(args: dict[str, Any]) -> dict[str, Any]:
    """Expand an entity graph node (aircraft, vessel, IP, company, person, country)."""
    entity_type = _require_str(args, "type", "entity_type")
    entity_id = _require_str(args, "id", "entity_id", "query", "value")
    props = {
        "label": entity_id,
        "registration": str(args.get("registration", "") or "").strip() or None,
        "model": str(args.get("model", "") or "").strip() or None,
        "icao24": str(args.get("icao24", "") or "").strip() or None,
    }
    props = {key: value for key, value in props.items() if value is not None}
    return resolve_entity(entity_type, entity_id, props)


def osint_tool_help() -> dict[str, Any]:
    """Discovery metadata for agents."""
    return {
        "tools": sorted(_OSINT_TOOLS),
        "entity_types": sorted(ALLOWED_TYPES),
        "sanctions_schemas": sorted(_ENTITY_SCHEMAS),
        "notes": {
            "osint_lookup": "Passive lookups — same data as the Recon panel /api/osint/* routes.",
            "osint_sweep": "Active subnet scan via Shodan InternetDB — requires full OpenClaw access tier.",
            "entity_expand": "Build a relationship graph around aircraft, vessels, IPs, companies, people, or countries.",
        },
    }
