"""Server-side OSINT lookups (Osiris port, HTTPS outbound only)."""
from __future__ import annotations

import ipaddress
import json
import logging
import re
import socket
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from services.network_utils import fetch_with_curl
from services.sanctions.ofac import match_exact, search_sanctions
from services.ssrf_guard import safe_get, validate_domain, validate_host

logger = logging.getLogger(__name__)

_IPV4_RE = re.compile(r"^(\d{1,3}\.){3}\d{1,3}$")
_IPV6_RE = re.compile(r"^[0-9a-fA-F:]+$")
_CVE_RE = re.compile(r"^CVE-\d{4}-\d{4,}$", re.I)
_ASN_RE = re.compile(r"^(AS)?\d+$", re.I)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_get(url: str, *, timeout: float = 8.0, headers: dict[str, str] | None = None) -> Any:
    resp = fetch_with_curl(url, timeout=timeout, headers=headers or {"Accept": "application/json"})
    if resp.status_code != 200:
        return None
    try:
        return resp.json()
    except Exception:
        return None


def _sanctions_hits(*values: str) -> list[dict[str, Any]] | None:
    hits: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        entries = match_exact(value)
        if entries:
            hits.append({"matched_value": value, "entries": entries})
    return hits or None


def lookup_ip(ip: str) -> dict[str, Any]:
    if not _IPV4_RE.match(ip) and not _IPV6_RE.match(ip):
        raise ValueError("Invalid IP format")
    check = validate_host(ip.strip("[]"))
    if not check.get("ok"):
        raise ValueError(check.get("reason", "blocked IP"))

    results: dict[str, Any] = {"ip": ip, "timestamp": _now_iso()}
    fields = (
        "status,message,continent,country,countryCode,region,regionName,city,zip,"
        "lat,lon,timezone,isp,org,as,asname,mobile,proxy,hosting,query"
    )
    geo = _json_get(f"https://ip-api.com/json/{quote(ip)}?fields={fields}", timeout=5)
    if isinstance(geo, dict) and geo.get("status") == "success":
        results["geo"] = {
            "country": geo.get("country"),
            "country_code": geo.get("countryCode"),
            "region": geo.get("regionName"),
            "city": geo.get("city"),
            "lat": geo.get("lat"),
            "lon": geo.get("lon"),
            "timezone": geo.get("timezone"),
            "isp": geo.get("isp"),
            "org": geo.get("org"),
            "as_number": geo.get("as"),
            "as_name": geo.get("asname"),
            "is_mobile": geo.get("mobile"),
            "is_proxy": geo.get("proxy"),
            "is_hosting": geo.get("hosting"),
        }
        results["reputation"] = {
            "is_proxy": bool(geo.get("proxy")),
            "is_hosting": bool(geo.get("hosting")),
            "is_mobile": bool(geo.get("mobile")),
            "risk_level": "HIGH" if geo.get("proxy") else "MEDIUM" if geo.get("hosting") else "LOW",
        }
        sm = _sanctions_hits(geo.get("org") or "", geo.get("isp") or "", geo.get("asname") or "")
        if sm:
            results["sanctions_match"] = {"source": "OFAC SDN", "hits": sm}
    return results


def lookup_dns(domain: str) -> dict[str, Any]:
    if not validate_domain(domain):
        raise ValueError("Invalid domain format")
    results: dict[str, Any] = {"domain": domain, "records": {}, "timestamp": _now_iso()}
    for rtype in ("A", "AAAA", "MX", "NS", "TXT", "CNAME", "SOA"):
        data = _json_get(
            f"https://dns.google/resolve?name={quote(domain)}&type={rtype}",
            timeout=5,
        )
        answers = []
        if isinstance(data, dict):
            for ans in data.get("Answer") or []:
                answers.append(
                    {
                        "name": ans.get("name"),
                        "type": ans.get("type"),
                        "ttl": ans.get("TTL"),
                        "data": ans.get("data"),
                    }
                )
        results["records"][rtype] = answers
    a_records = results["records"].get("A") or []
    mx_records = results["records"].get("MX") or []
    ns_records = results["records"].get("NS") or []
    results["summary"] = {
        "ip_addresses": [r["data"] for r in a_records if r.get("data")],
        "mail_servers": [r["data"] for r in mx_records if r.get("data")],
        "nameservers": [r["data"] for r in ns_records if r.get("data")],
        "total_records": sum(len(v) for v in results["records"].values()),
    }
    return results


def lookup_whois(domain: str) -> dict[str, Any]:
    if not validate_domain(domain):
        raise ValueError("Invalid domain format")
    results: dict[str, Any] = {"domain": domain, "timestamp": _now_iso()}
    rdap = _json_get(f"https://rdap.org/domain/{quote(domain)}", timeout=8)
    if isinstance(rdap, dict):
        entities = []
        for ent in rdap.get("entities") or []:
            vcard = ent.get("vcardArray")
            name = org = None
            if isinstance(vcard, list) and len(vcard) > 1:
                for row in vcard[1]:
                    if row[0] == "fn":
                        name = row[3]
                    if row[0] == "org":
                        org = row[3]
            if name or org:
                entities.append({"handle": ent.get("handle"), "roles": ent.get("roles"), "name": name, "org": org})
        events = [
            {"action": e.get("eventAction"), "date": e.get("eventDate")}
            for e in (rdap.get("events") or [])
        ]
        results["rdap"] = {
            "handle": rdap.get("handle"),
            "name": rdap.get("ldhName"),
            "status": rdap.get("status"),
            "events": events,
            "nameservers": [ns.get("ldhName") for ns in (rdap.get("nameservers") or [])],
            "entities": entities,
        }
        results["registration"] = next((e["date"] for e in events if e["action"] == "registration"), None)
        results["expiration"] = next((e["date"] for e in events if e["action"] == "expiration"), None)
        results["last_changed"] = next((e["date"] for e in events if e["action"] == "last changed"), None)
        sm = _sanctions_hits(*(e.get("name") or "" for e in entities), *(e.get("org") or "" for e in entities))
        if sm:
            results["sanctions_match"] = {"source": "OFAC SDN", "hits": sm}

    try:
        res = safe_get(f"https://{domain}", timeout=5, headers={"User-Agent": "Shadowbroker-OSINT/1.0"})
        headers = {}
        for h in (
            "server",
            "x-powered-by",
            "x-frame-options",
            "strict-transport-security",
            "content-security-policy",
            "x-content-type-options",
            "x-xss-protection",
            "referrer-policy",
            "permissions-policy",
        ):
            val = res.headers.get(h)
            if val:
                headers[h] = val
        score = sum(
            1
            for k in (
                "strict-transport-security",
                "content-security-policy",
                "x-frame-options",
                "x-content-type-options",
                "referrer-policy",
            )
            if k in headers
        ) + (2 if "strict-transport-security" in headers else 0) + (2 if "content-security-policy" in headers else 0)
        results["http"] = {"status": res.status_code, "headers": headers, "final_url": res.url}
        results["security_score"] = {
            "score": score,
            "max": 7,
            "grade": "A" if score >= 5 else "B" if score >= 3 else "C" if score >= 1 else "F",
        }
    except Exception as exc:
        logger.debug("WHOIS header probe failed for %s: %s", domain, exc)
    return results


def lookup_certs(domain: str) -> dict[str, Any]:
    if not validate_domain(domain):
        raise ValueError("Invalid domain format")
    resp = fetch_with_curl(
        f"https://crt.sh/?q=%25.{quote(domain)}&output=json",
        timeout=10,
        headers={"User-Agent": "Shadowbroker-OSINT/1.0"},
    )
    if resp.status_code != 200:
        return {"domain": domain, "certificates": [], "error": "crt.sh unavailable"}
    try:
        certs = resp.json()
    except Exception:
        certs = []
    seen: set[str] = set()
    subdomains: set[str] = set()
    unique: list[dict[str, Any]] = []
    for cert in (certs or [])[:200]:
        key = f"{cert.get('common_name')}-{cert.get('serial_number')}"
        if key in seen:
            continue
        seen.add(key)
        for name in (cert.get("name_value") or "").split("\n"):
            clean = name.strip().replace("*.", "")
            if clean.endswith(domain):
                subdomains.add(clean)
        unique.append(
            {
                "id": cert.get("id"),
                "issuer": cert.get("issuer_name"),
                "common_name": cert.get("common_name"),
                "not_before": cert.get("not_before"),
                "not_after": cert.get("not_after"),
            }
        )
    return {
        "domain": domain,
        "certificates": unique[:50],
        "subdomains": sorted(subdomains)[:100],
        "total_found": len(certs or []),
        "timestamp": _now_iso(),
    }


def lookup_threats(query: str | None = None) -> dict[str, Any]:
    results: dict[str, Any] = {"timestamp": _now_iso()}
    pulses = _json_get("https://otx.alienvault.com/api/v1/pulses/activity?limit=10", timeout=8)
    if isinstance(pulses, dict):
        results["pulses"] = [
            {
                "name": p.get("name"),
                "description": (p.get("description") or "")[:200],
                "created": p.get("created"),
                "tags": (p.get("tags") or [])[:5],
                "adversary": p.get("adversary"),
                "indicators_count": p.get("indicator_count"),
            }
            for p in (pulses.get("results") or [])[:10]
        ]
    if query:
        if _IPV4_RE.match(query):
            try:
                tor_resp = fetch_with_curl("https://check.torproject.org/torbulkexitlist", timeout=5)
                results["tor_exit_node"] = query in (tor_resp.text or "").splitlines() if tor_resp.status_code == 200 else None
            except Exception:
                results["tor_exit_node"] = None
            otx = _json_get(f"https://otx.alienvault.com/api/v1/indicators/IPv4/{quote(query)}/general", timeout=5)
            if isinstance(otx, dict):
                results["otx"] = {
                    "reputation": otx.get("reputation"),
                    "pulse_count": (otx.get("pulse_info") or {}).get("count", 0),
                    "country": otx.get("country_name"),
                    "asn": otx.get("asn"),
                }
        elif validate_domain(query):
            otx = _json_get(f"https://otx.alienvault.com/api/v1/indicators/domain/{quote(query)}/general", timeout=5)
            if isinstance(otx, dict):
                results["otx"] = {"pulse_count": (otx.get("pulse_info") or {}).get("count", 0)}
    pulse_count = (results.get("otx") or {}).get("pulse_count", 0)
    results["threat_level"] = "HIGH" if pulse_count > 5 else "MEDIUM" if pulse_count > 0 else "LOW"
    return results


def lookup_bgp(query: str) -> dict[str, Any]:
    results: dict[str, Any] = {"query": query, "timestamp": _now_iso()}
    if _IPV4_RE.match(query):
        data = _json_get(f"https://api.bgpview.io/ip/{quote(query)}", timeout=8)
        if isinstance(data, dict) and data.get("status") == "ok":
            results["ip"] = data.get("data")
            results["type"] = "ip"
        return results
    if _ASN_RE.match(query):
        asn_num = re.sub(r"^AS", "", query, flags=re.I)
        asn = _json_get(f"https://api.bgpview.io/asn/{asn_num}", timeout=8)
        prefixes = _json_get(f"https://api.bgpview.io/asn/{asn_num}/prefixes", timeout=8)
        peers = _json_get(f"https://api.bgpview.io/asn/{asn_num}/peers", timeout=8)
        if isinstance(asn, dict) and asn.get("status") == "ok":
            results["asn"] = asn.get("data")
        if isinstance(prefixes, dict) and prefixes.get("status") == "ok":
            pdata = prefixes.get("data") or {}
            results["prefixes"] = {
                "ipv4": (pdata.get("ipv4_prefixes") or [])[:20],
                "ipv6": (pdata.get("ipv6_prefixes") or [])[:10],
                "total_v4": len(pdata.get("ipv4_prefixes") or []),
                "total_v6": len(pdata.get("ipv6_prefixes") or []),
            }
        if isinstance(peers, dict) and peers.get("status") == "ok":
            pdata = peers.get("data") or {}
            results["peers"] = {
                "upstream": (pdata.get("ipv4_peers") or [])[:10],
                "total": len(pdata.get("ipv4_peers") or []),
            }
        results["type"] = "asn"
        return results
    raise ValueError("Unrecognized query format. Use IP address or AS number.")


def lookup_sanctions(query: str, *, schema: str | None = None, limit: int = 25) -> dict[str, Any]:
    matches = search_sanctions(query, schema=schema, limit=limit)
    return {
        "query": query,
        "schema": schema,
        "total": len(matches),
        "matches": matches,
        "source": "OpenSanctions / US OFAC SDN",
        "timestamp": _now_iso(),
    }


def lookup_cve(cve: str) -> dict[str, Any]:
    if not _CVE_RE.match(cve):
        raise ValueError("Invalid CVE format")
    cve_id = cve.upper()
    data = _json_get(f"https://cveawg.mitre.org/api/cve/{quote(cve_id)}", timeout=8)
    if isinstance(data, dict) and data.get("cveMetadata"):
        meta = data["cveMetadata"]
        desc = ""
        for block in (data.get("containers") or {}).get("cna", {}).get("descriptions") or []:
            if block.get("lang") == "en":
                desc = block.get("value") or desc
        return {"id": meta.get("cveId", cve_id), "description": desc or "No description.", "timestamp": _now_iso()}
    fallback = _json_get(f"https://cve.circl.lu/api/cve/{quote(cve_id)}", timeout=8)
    if isinstance(fallback, dict):
        return {
            "id": fallback.get("id", cve_id),
            "description": fallback.get("summary") or "No description.",
            "cvss": fallback.get("cvss"),
            "references": (fallback.get("references") or [])[:5],
            "timestamp": _now_iso(),
        }
    raise ValueError("CVE not found")


def lookup_mac(mac: str) -> dict[str, Any]:
    clean = mac.strip().upper()
    clean = re.sub(r"[^A-F0-9:-]", "", clean)
    data = _json_get(f"https://api.macvendors.com/{quote(clean)}", timeout=8)
    if isinstance(data, dict):
        return {"mac": clean, "vendor": data.get("company") or data.get("organization") or "Not Found"}
    if isinstance(data, str) and data:
        return {"mac": clean, "vendor": data}
    return {"mac": clean, "vendor": "Not Found"}


def lookup_github(username: str) -> dict[str, Any]:
    user = _json_get(f"https://api.github.com/users/{quote(username)}", timeout=8)
    if not isinstance(user, dict) or user.get("message") == "Not Found":
        raise ValueError("GitHub user not found")
    repos = _json_get(f"https://api.github.com/users/{quote(username)}/repos?per_page=10&sort=updated", timeout=8)
    return {
        "username": username,
        "profile": {
            "name": user.get("name"),
            "bio": user.get("bio"),
            "company": user.get("company"),
            "location": user.get("location"),
            "public_repos": user.get("public_repos"),
            "followers": user.get("followers"),
            "created_at": user.get("created_at"),
            "html_url": user.get("html_url"),
        },
        "repos": [
            {"name": r.get("name"), "language": r.get("language"), "stars": r.get("stargazers_count")}
            for r in (repos or [])[:10]
            if isinstance(r, dict)
        ],
        "timestamp": _now_iso(),
    }


def lookup_leaks(email: str) -> dict[str, Any]:
    if "@" not in email or len(email) < 5:
        raise ValueError("Invalid email")
    # HIBP requires API key for v3; use public breach directory style via leak-lookup (rate limited)
    data = _json_get(f"https://leakcheck.io/api/public?check={quote(email)}", timeout=8)
    if isinstance(data, dict):
        return {
            "email": email,
            "found": bool(data.get("found")),
            "sources": data.get("sources") or [],
            "timestamp": _now_iso(),
        }
    return {"email": email, "found": False, "sources": [], "timestamp": _now_iso()}


def sweep_init(ip: str, cidr: int = 24) -> dict[str, Any]:
    try:
        addr = ipaddress.IPv4Address(ip)
    except ValueError as exc:
        raise ValueError("Invalid IPv4 address format") from exc
    if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
        raise ValueError("Private and reserved IP ranges are not allowed")
    if cidr < 24 or cidr > 32:
        raise ValueError("CIDR must be between 24 and 32")

    fields = "status,message,country,countryCode,region,regionName,city,lat,lon,isp,org,as,proxy,hosting"
    geo = _json_get(f"https://ip-api.com/json/{quote(ip)}?fields={fields}", timeout=5)
    if not isinstance(geo, dict) or geo.get("status") != "success":
        raise ValueError(f"Geolocation failed: {(geo or {}).get('message', 'unknown')}")
    return {
        "center": {
            "lat": geo.get("lat"),
            "lng": geo.get("lon"),
            "city": geo.get("city"),
            "region": geo.get("regionName"),
            "country": geo.get("country"),
            "countryCode": geo.get("countryCode"),
            "isp": geo.get("isp"),
            "asn": geo.get("as") or "",
            "org": geo.get("org") or "",
        },
        "target_ip": ip,
        "cidr": cidr,
    }


def _internetdb_lookup(ip: str) -> dict[str, Any] | None:
    try:
        resp = fetch_with_curl(
            f"https://internetdb.shodan.io/{quote(ip)}",
            timeout=4,
            headers={"Accept": "application/json"},
        )
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception:
        return None


def sweep_scan(subnet_start: str, cidr: int, *, max_workers: int = 12) -> dict[str, Any]:
    """Scan a /24-/32 via Shodan InternetDB (server-side proxy)."""
    base = int(ipaddress.IPv4Address(subnet_start))
    host_count = 2 ** (32 - cidr)
    if host_count > 256:
        raise ValueError("Subnet too large")
    ips = [str(ipaddress.IPv4Address(base + i)) for i in range(host_count)]
    devices: list[dict[str, Any]] = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_internetdb_lookup, ip): ip for ip in ips}
        for fut in as_completed(futures):
            ip = futures[fut]
            data = fut.result()
            if not data:
                continue
            devices.append(
                {
                    "ip": data.get("ip") or ip,
                    "ports": data.get("ports") or [],
                    "hostnames": data.get("hostnames") or [],
                    "cpes": data.get("cpes") or [],
                    "vulns": data.get("vulns") or [],
                    "tags": data.get("tags") or [],
                }
            )
    return {
        "devices": devices,
        "summary": {"total_hosts": host_count, "total_responsive": len(devices)},
        "sweep_time_ms": int((time.time() - t0) * 1000),
    }


def subnet_start_for(ip: str, cidr: int) -> str:
    net = ipaddress.IPv4Network(f"{ip}/{cidr}", strict=False)
    return str(net.network_address)
