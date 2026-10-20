"""SSRF guard for operator-initiated recon (ported from Osiris ssrf-guard.ts)."""
from __future__ import annotations

import ipaddress
import re
import socket
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

_IPV4_BLOCKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
]

_NAME_BLOCKLIST = (
    re.compile(r"^localhost$", re.I),
    re.compile(r"\.localhost$", re.I),
    re.compile(r"^host\.docker\.internal$", re.I),
    re.compile(r"\.local$", re.I),
    re.compile(r"\.internal$", re.I),
    re.compile(r"^metadata\.google\.internal$", re.I),
)

_HOSTNAME_RE = re.compile(
    r"^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?)*$"
)


def _ipv4_blocked(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    if not isinstance(addr, ipaddress.IPv4Address):
        return False
    return any(addr in net for net in _IPV4_BLOCKS)


def _ip_blocked(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    if isinstance(addr, ipaddress.IPv4Address):
        return _ipv4_blocked(ip)
    return (
        addr.is_loopback
        or addr.is_private
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


def validate_host(host: str) -> dict[str, Any]:
    trimmed = (host or "").strip()
    if not trimmed:
        return {"ok": False, "reason": "empty host"}
    bracketed = trimmed.strip("[]")
    lower = trimmed.lower()
    if any(p.search(lower) for p in _NAME_BLOCKLIST):
        return {"ok": False, "reason": "hostname matches reserved name pattern"}

    try:
        ipaddress.ip_address(bracketed)
        is_literal = True
    except ValueError:
        is_literal = False

    if is_literal:
        if _ip_blocked(bracketed):
            return {"ok": False, "reason": "IP in reserved range"}
        return {"ok": True, "resolved": [bracketed]}

    if not _HOSTNAME_RE.match(trimmed):
        return {"ok": False, "reason": "invalid hostname syntax"}

    try:
        infos = socket.getaddrinfo(trimmed, None, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        return {"ok": False, "reason": f"DNS lookup failed: {exc}"}
    if not infos:
        return {"ok": False, "reason": "hostname has no A/AAAA records"}

    resolved: list[str] = []
    for info in infos:
        addr = info[4][0]
        if _ip_blocked(addr):
            return {"ok": False, "reason": f"hostname resolves to reserved IP {addr}"}
        resolved.append(addr)
    return {"ok": True, "resolved": resolved}


def safe_get(
    url: str,
    *,
    timeout: float = 8.0,
    headers: dict[str, str] | None = None,
    max_redirects: int = 3,
) -> requests.Response:
    current = url
    for _ in range(max_redirects + 1):
        parsed = urlparse(current)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"blocked protocol {parsed.scheme}")
        check = validate_host(parsed.hostname or "")
        if not check.get("ok"):
            raise ValueError(f"blocked target — {check.get('reason')}")
        res = requests.get(
            current,
            timeout=timeout,
            headers=headers or {},
            allow_redirects=False,
        )
        if 300 <= res.status_code < 400:
            loc = res.headers.get("location")
            if not loc:
                return res
            current = urljoin(current, loc)
            continue
        return res
    raise ValueError("too many redirects")


def validate_domain(domain: str) -> bool:
    return bool(re.match(r"^[a-zA-Z0-9][a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", domain or ""))
