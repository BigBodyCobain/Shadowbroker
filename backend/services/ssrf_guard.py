"""SSRF guard for operator-initiated recon (ported from Osiris ssrf-guard.ts)."""
from __future__ import annotations

import ipaddress
import logging
import re
import socket
from typing import Any
from urllib.parse import urljoin, urlparse, urlunsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager

logger = logging.getLogger(__name__)

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


class _PinnedIPAdapter(HTTPAdapter):
    """HTTP adapter that pins DNS to a pre-validated IP while preserving TLS SNI."""

    def __init__(self, *, hostname: str, ip: str, **kwargs: Any) -> None:
        self._hostname = hostname
        self._ip = ip
        super().__init__(**kwargs)

    def init_poolmanager(self, *args: Any, **kwargs: Any) -> None:
        # Preserve certificate hostname validation and SNI for the original hostname.
        kwargs.setdefault("server_hostname", self._hostname)
        kwargs.setdefault("assert_hostname", self._hostname)
        super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args: Any, **kwargs: Any):  # type: ignore[override]
        kwargs.setdefault("server_hostname", self._hostname)
        kwargs.setdefault("assert_hostname", self._hostname)
        return super().proxy_manager_for(*args, **kwargs)

    def send(self, request, stream=False, timeout=None, verify=True, cert=None, proxies=None):  # type: ignore[override]
        parsed = urlparse(request.url)
        # Rewrite the connection target to the validated IP, keep Host header for HTTP.
        netloc = self._ip
        if ":" in netloc and not netloc.startswith("["):
            netloc = f"[{netloc}]"
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"
        request.url = urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))
        request.headers["Host"] = self._hostname
        return super().send(request, stream=stream, timeout=timeout, verify=verify, cert=cert, proxies=proxies)


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
    if addr.ipv4_mapped:
        return _ip_blocked(str(addr.ipv4_mapped))
    return (
        addr.is_loopback
        or addr.is_private
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


def validate_host(host: str) -> dict[str, Any]:
    trimmed = (host or "").strip().rstrip(".")
    if not trimmed:
        return {"ok": False, "reason": "empty host"}
    bracketed = trimmed.strip("[]")
    lower = bracketed.lower()
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
        if addr not in resolved:
            resolved.append(addr)
    return {"ok": True, "resolved": resolved}


def _pick_pinned_ip(resolved: list[str]) -> str:
    # Prefer IPv4 for broad compatibility; all candidates are already validated.
    for addr in resolved:
        try:
            if isinstance(ipaddress.ip_address(addr), ipaddress.IPv4Address):
                return addr
        except ValueError:
            continue
    return resolved[0]


def safe_get(
    url: str,
    *,
    timeout: float = 8.0,
    headers: dict[str, str] | None = None,
    max_redirects: int = 3,
    stream: bool = False,
) -> requests.Response:
    current = url
    session_headers = dict(headers or {})
    for _ in range(max_redirects + 1):
        parsed = urlparse(current)
        host = (parsed.hostname or "").strip().rstrip(".")
        if parsed.scheme not in ("http", "https"):
            logger.warning("ssrf_deny event=blocked_protocol scheme=%s host=%s", parsed.scheme, host)
            raise ValueError(f"blocked protocol {parsed.scheme}")
        if parsed.username or parsed.password:
            logger.warning("ssrf_deny event=blocked_url_credentials host=%s", host)
            raise ValueError("blocked target — URL credentials are not allowed")
        check = validate_host(host)
        if not check.get("ok"):
            logger.warning("ssrf_deny event=blocked_target host=%s reason=%s", host, check.get("reason"))
            raise ValueError(f"blocked target — {check.get('reason')}")

        resolved = list(check.get("resolved") or [])
        pinned_ip = _pick_pinned_ip(resolved)

        with requests.Session() as sess:
            adapter = _PinnedIPAdapter(hostname=host, ip=pinned_ip)
            sess.mount("http://", adapter)
            sess.mount("https://", adapter)
            sess.headers.update(session_headers)
            res = sess.get(
                current,
                timeout=timeout,
                allow_redirects=False,
                verify=True,
            )

        if 300 <= res.status_code < 400:
            loc = res.headers.get("location")
            if not loc:
                return res
            current = urljoin(current, loc)
            continue
        return res

    logger.warning("ssrf_deny event=too_many_redirects host=%s", urlparse(current).hostname or "")
    raise ValueError("too many redirects")


def validate_domain(domain: str) -> bool:
    return bool(re.match(r"^[a-zA-Z0-9][a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", domain or ""))


# Peer URLs are operator/LAN configured, so loopback and RFC1918 peers are
# legitimate (unlike operator-initiated recon targets). Only metadata-style
# names are refused here; link-local IPs are caught by _peer_ip_blocked.
_PEER_METADATA_NAMES = (
    re.compile(r"^metadata$", re.I),
    re.compile(r"^metadata\..*$", re.I),
    re.compile(r"^instance-data$", re.I),
    re.compile(r"^instance-data\..*$", re.I),
)


def _peer_ip_blocked(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr.strip("[]"))
    except ValueError:
        return True
    # Loopback and IPv4 private ranges are valid peer transports; link-local,
    # multicast, reserved, unspecified and IPv6 ULA ranges are not.
    if ip.version == 6 and ip.is_private and not ip.is_loopback:
        return True
    return bool(ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified)


def guard_url_for_peer_request(url: str, *, allow_proxied: bool = False) -> dict[str, Any]:
    """SSRF guard for operator/LAN-configured mesh peer URLs.

    Unlike `validate_host` (built for arbitrary recon targets), this permits
    loopback and private peers because those are legitimate mesh transports.
    It still refuses dangerous schemes, URL credentials, metadata hosts and
    link-local/reserved IPs. When `allow_proxied` is True (SOCKS/Tor),
    resolution happens at the proxy, so local DNS validation is skipped.
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").strip().rstrip(".")
    if parsed.scheme not in ("http", "https"):
        return {"ok": False, "reason": f"blocked protocol {parsed.scheme}"}
    if parsed.username or parsed.password:
        return {"ok": False, "reason": "URL credentials are not allowed"}
    if not host:
        return {"ok": False, "reason": "empty host"}
    lower = host.lower()
    if any(p.search(lower) for p in _PEER_METADATA_NAMES):
        return {"ok": False, "reason": "metadata service hostname"}
    if lower.endswith(".onion"):
        return {"ok": True, "resolved": []}
    if allow_proxied:
        return {"ok": True, "resolved": []}

    bracketed = host.strip("[]")
    try:
        ipaddress.ip_address(bracketed)
        is_literal = True
    except ValueError:
        is_literal = False
    if is_literal:
        if _peer_ip_blocked(bracketed):
            return {"ok": False, "reason": "IP in link-local or reserved range"}
        return {"ok": True, "resolved": [bracketed]}
    if not _HOSTNAME_RE.match(host):
        return {"ok": False, "reason": "invalid hostname syntax"}
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        return {"ok": False, "reason": f"DNS lookup failed: {exc}"}
    resolved: list[str] = []
    for info in infos:
        addr = info[4][0]
        if _peer_ip_blocked(addr):
            return {"ok": False, "reason": f"hostname resolves to reserved IP {addr}"}
        if addr not in resolved:
            resolved.append(addr)
    return {"ok": True, "resolved": resolved}
