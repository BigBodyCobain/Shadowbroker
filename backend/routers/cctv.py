import logging
from dataclasses import dataclass, field
from fastapi import APIRouter, Request, Query, HTTPException
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
from pydantic import BaseModel
from limiter import limiter
from auth import require_admin

logger = logging.getLogger(__name__)

router = APIRouter()

_CCTV_PROXY_CONNECT_TIMEOUT_S = 2.0

_CCTV_PROXY_ALLOWED_HOSTS = {
    "s3-eu-west-1.amazonaws.com",
    "jamcams.tfl.gov.uk",
    "images.data.gov.sg",
    "cctv.austinmobility.io",
    "webcams.nyctmc.org",
    "cwwp2.dot.ca.gov",
    "wzmedia.dot.ca.gov",
    "images.wsdot.wa.gov",
    "olypen.com",
    "flyykm.com",
    "cam.pangbornairport.com",
    "navigator-c2c.dot.ga.gov",
    "navigator-c2c.ga.gov",
    "navigator-csc.dot.ga.gov",
    "vss1live.dot.ga.gov",
    "vss2live.dot.ga.gov",
    "vss3live.dot.ga.gov",
    "vss4live.dot.ga.gov",
    "vss5live.dot.ga.gov",
    "511ga.org",
    "gettingaroundillinois.com",
    "cctv.travelmidwest.com",
    "mdotjboss.state.mi.us",
    "micamerasimages.net",
    "publicstreamer1.cotrip.org",
    "publicstreamer2.cotrip.org",
    "publicstreamer3.cotrip.org",
    "publicstreamer4.cotrip.org",
    "cocam.carsprogram.org",
    "tripcheck.com",
    "www.tripcheck.com",
    "infocar.dgt.es",
    "etraffic.dgt.es",
    "informo.madrid.es",
    "webcams2.asfinag.at",
    "odo.asfinag.at",
    "www.windy.com",
    "imgproxy.windy.com",
    "www.lakecountypassage.com",
    "webcam.forkswa.com",
    "webcam.sunmountainlodge.com",
    "www.nps.gov",
    "home.lewiscounty.com",
    "www.seattle.gov",
    "511on.ca",
    "511.alberta.ca",
    "fl511.com",
    "www.fl511.com",
    "webcams.transport.nsw.gov.au",
    "www.livetraffic.com",
    "livetraffic.com",
    "opendata.ndw.nu",
}


@dataclass(frozen=True)
class _CCTVProxyProfile:
    name: str
    timeout: tuple = (_CCTV_PROXY_CONNECT_TIMEOUT_S, 8.0)
    cache_seconds: int = 30
    headers: dict = field(default_factory=dict)


def _cctv_host_allowed(hostname) -> bool:
    host = str(hostname or "").strip().lower()
    if not host:
        return False
    for allowed in _CCTV_PROXY_ALLOWED_HOSTS:
        normalized = str(allowed or "").strip().lower()
        if host == normalized or host.endswith(f".{normalized}"):
            return True
    return False


def _proxied_cctv_url(target_url: str) -> str:
    from urllib.parse import quote
    return f"/api/cctv/media?url={quote(target_url, safe='')}"


def _cctv_proxy_profile_for_url(target_url: str) -> _CCTVProxyProfile:
    from urllib.parse import urlparse
    parsed = urlparse(target_url)
    host = str(parsed.hostname or "").strip().lower()
    path = str(parsed.path or "").strip().lower()

    if host in {"jamcams.tfl.gov.uk", "s3-eu-west-1.amazonaws.com"}:
        return _CCTVProxyProfile(name="tfl-jamcam", timeout=(_CCTV_PROXY_CONNECT_TIMEOUT_S, 20.0), cache_seconds=15,
            headers={"Accept": "video/mp4,image/avif,image/webp,image/apng,image/*,*/*;q=0.8", "Referer": "https://tfl.gov.uk/"})
    if host == "images.data.gov.sg":
        return _CCTVProxyProfile(name="lta-singapore", timeout=(_CCTV_PROXY_CONNECT_TIMEOUT_S, 10.0), cache_seconds=30,
            headers={"Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"})
    if host == "cctv.austinmobility.io":
        return _CCTVProxyProfile(name="austin-mobility", timeout=(_CCTV_PROXY_CONNECT_TIMEOUT_S, 8.0), cache_seconds=15,
            headers={"Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                     "Referer": "https://data.mobility.austin.gov/", "Origin": "https://data.mobility.austin.gov"})
    if host == "webcams.nyctmc.org":
        return _CCTVProxyProfile(name="nyc-dot", timeout=(_CCTV_PROXY_CONNECT_TIMEOUT_S, 10.0), cache_seconds=15,
            headers={"Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"})
    if host in {"cwwp2.dot.ca.gov", "wzmedia.dot.ca.gov"}:
        return _CCTVProxyProfile(name="caltrans", timeout=(_CCTV_PROXY_CONNECT_TIMEOUT_S, 15.0), cache_seconds=15,
            headers={"Accept": "application/vnd.apple.mpegurl,application/x-mpegURL,video/*,image/*,*/*;q=0.8",
                     "Referer": "https://cwwp2.dot.ca.gov/"})
    if host in {"images.wsdot.wa.gov", "olypen.com", "flyykm.com", "cam.pangbornairport.com"}:
        return _CCTVProxyProfile(name="wsdot", timeout=(_CCTV_PROXY_CONNECT_TIMEOUT_S, 12.0), cache_seconds=30,
            headers={"Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"})
    if host in {"www.lakecountypassage.com", "webcam.forkswa.com", "webcam.sunmountainlodge.com", "home.lewiscounty.com", "www.seattle.gov"}:
        return _CCTVProxyProfile(name="regional-cctv-image", timeout=(_CCTV_PROXY_CONNECT_TIMEOUT_S, 10.0), cache_seconds=45,
            headers={"Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                     "Referer": f"https://{host}/"})
    if host == "www.nps.gov":
        return _CCTVProxyProfile(name="nps-webcam", timeout=(_CCTV_PROXY_CONNECT_TIMEOUT_S, 10.0), cache_seconds=60,
            headers={"Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                     "Referer": "https://www.nps.gov/"})
    if host in {"navigator-c2c.dot.ga.gov", "navigator-c2c.ga.gov", "navigator-csc.dot.ga.gov"}:
        read_timeout = 18.0 if "/snapshots/" in path else 12.0
        return _CCTVProxyProfile(name="gdot-snapshot", timeout=(_CCTV_PROXY_CONNECT_TIMEOUT_S, read_timeout), cache_seconds=15,
            headers={"Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                     "Referer": "https://navigator-c2c.dot.ga.gov/"})
    if host == "511ga.org":
        return _CCTVProxyProfile(name="gdot-511ga-image", timeout=(_CCTV_PROXY_CONNECT_TIMEOUT_S, 12.0), cache_seconds=15,
            headers={"Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                     "Referer": "https://511ga.org/cctv"})
    if host.startswith("vss") and host.endswith("dot.ga.gov"):
        return _CCTVProxyProfile(name="gdot-hls", timeout=(_CCTV_PROXY_CONNECT_TIMEOUT_S, 20.0), cache_seconds=10,
            headers={"Accept": "application/vnd.apple.mpegurl,application/x-mpegURL,video/*,*/*;q=0.8",
                     "Referer": "https://navigator-c2c.dot.ga.gov/"})
    if host in {"gettingaroundillinois.com", "cctv.travelmidwest.com"}:
        return _CCTVProxyProfile(name="illinois-dot", timeout=(_CCTV_PROXY_CONNECT_TIMEOUT_S, 12.0), cache_seconds=30,
            headers={"Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"})
    if host in {"mdotjboss.state.mi.us", "micamerasimages.net"}:
        return _CCTVProxyProfile(name="michigan-dot", timeout=(_CCTV_PROXY_CONNECT_TIMEOUT_S, 12.0), cache_seconds=30,
            headers={"Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                     "Referer": "https://mdotjboss.state.mi.us/"})
    if host in {"publicstreamer1.cotrip.org", "publicstreamer2.cotrip.org",
                "publicstreamer3.cotrip.org", "publicstreamer4.cotrip.org"}:
        return _CCTVProxyProfile(name="cotrip-hls", timeout=(_CCTV_PROXY_CONNECT_TIMEOUT_S, 20.0), cache_seconds=10,
            headers={"Accept": "application/vnd.apple.mpegurl,application/x-mpegURL,video/*,*/*;q=0.8",
                     "Referer": "https://www.cotrip.org/"})
    if host == "cocam.carsprogram.org":
        return _CCTVProxyProfile(name="cotrip-preview", timeout=(_CCTV_PROXY_CONNECT_TIMEOUT_S, 12.0), cache_seconds=20,
            headers={"Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                     "Referer": "https://www.cotrip.org/"})
    if host in {"tripcheck.com", "www.tripcheck.com"}:
        return _CCTVProxyProfile(name="odot-tripcheck", timeout=(_CCTV_PROXY_CONNECT_TIMEOUT_S, 12.0), cache_seconds=30,
            headers={"Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"})
    if host in {"infocar.dgt.es", "etraffic.dgt.es"}:
        return _CCTVProxyProfile(name="dgt-spain", timeout=(_CCTV_PROXY_CONNECT_TIMEOUT_S, 8.0), cache_seconds=60,
            headers={"Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                     "Referer": "https://etraffic.dgt.es/"})
    if host == "informo.madrid.es":
        return _CCTVProxyProfile(name="madrid-city", timeout=(_CCTV_PROXY_CONNECT_TIMEOUT_S, 12.0), cache_seconds=30,
            headers={"Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                     "Referer": "https://informo.madrid.es/"})
    if host in {"webcams2.asfinag.at", "odo.asfinag.at"}:
        return _CCTVProxyProfile(name="asfinag-austria", timeout=(_CCTV_PROXY_CONNECT_TIMEOUT_S, 15.0), cache_seconds=60,
            headers={"Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                     "Referer": "https://www.asfinag.at/"})
    if host in {"www.windy.com", "imgproxy.windy.com"}:
        return _CCTVProxyProfile(name="windy-webcams", timeout=(_CCTV_PROXY_CONNECT_TIMEOUT_S, 12.0), cache_seconds=60,
            headers={"Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                     "Referer": "https://www.windy.com/"})
    if host == "511on.ca":
        return _CCTVProxyProfile(name="ontario-511", timeout=(_CCTV_PROXY_CONNECT_TIMEOUT_S, 15.0), cache_seconds=30,
            headers={"Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                     "Referer": "https://511on.ca/"})
    if host == "511.alberta.ca":
        return _CCTVProxyProfile(name="alberta-511", timeout=(_CCTV_PROXY_CONNECT_TIMEOUT_S, 15.0), cache_seconds=30,
            headers={"Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                     "Referer": "https://511.alberta.ca/"})
    if host in {"fl511.com", "www.fl511.com"}:
        return _CCTVProxyProfile(name="florida-511", timeout=(_CCTV_PROXY_CONNECT_TIMEOUT_S, 15.0), cache_seconds=30,
            headers={"Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                     "Referer": "https://fl511.com/"})
    if host == "webcams.transport.nsw.gov.au":
        return _CCTVProxyProfile(name="nsw-live-traffic", timeout=(_CCTV_PROXY_CONNECT_TIMEOUT_S, 12.0), cache_seconds=60,
            headers={"Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                     "Referer": "https://www.livetraffic.com/"})
    if host in {"opendata.ndw.nu", "www.ndw.nu"}:
        return _CCTVProxyProfile(name="ndw-netherlands", timeout=(_CCTV_PROXY_CONNECT_TIMEOUT_S, 12.0), cache_seconds=120,
            headers={"Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                     "Referer": "https://www.ndw.nu/"})
    return _CCTVProxyProfile(name="generic-cctv", timeout=(_CCTV_PROXY_CONNECT_TIMEOUT_S, 8.0), cache_seconds=30,
        headers={"Accept": "*/*"})


def _cctv_upstream_headers(request: Request, profile: _CCTVProxyProfile) -> dict:
    # Round 7a: per-install operator handle. Mozilla/5.0 prefix retained
    # because many CCTV endpoints sniff for a browser-like prefix.
    from services.network_utils import outbound_user_agent
    headers = {
        "User-Agent": f"Mozilla/5.0 (compatible; {outbound_user_agent('cctv-proxy')})",
        **profile.headers,
    }
    range_header = request.headers.get("range")
    if range_header:
        headers["Range"] = range_header
    if_none_match = request.headers.get("if-none-match")
    if if_none_match:
        headers["If-None-Match"] = if_none_match
    if_modified_since = request.headers.get("if-modified-since")
    if if_modified_since:
        headers["If-Modified-Since"] = if_modified_since
    return headers


def _cctv_response_headers(resp, cache_seconds: int, include_length: bool = True) -> dict:
    headers = {"Cache-Control": f"public, max-age={cache_seconds}", "Access-Control-Allow-Origin": "*"}
    for key in ("Accept-Ranges", "Content-Range", "ETag", "Last-Modified"):
        value = resp.headers.get(key)
        if value:
            headers[key] = value
    if include_length:
        content_length = resp.headers.get("Content-Length")
        if content_length:
            headers["Content-Length"] = content_length
    return headers


# Maximum number of redirects we'll follow on the CCTV upstream. Each hop is
# re-validated against _cctv_host_allowed() before continuing, so this caps
# the redirect-chain SSRF blast radius.
_CCTV_MAX_REDIRECTS = 5


def _fetch_cctv_upstream_response(request: Request, target_url: str, profile: _CCTVProxyProfile):
    """Fetch an upstream CCTV URL, following redirects manually with host re-validation.

    Why manual redirect following:
      The original code used ``allow_redirects=True``, which only validated
      the initial caller-supplied URL host against the allowlist. An attacker
      could submit an allowed host that 302-redirected to an internal address
      (e.g. ``http://localhost:8000/api/...`` or a private RFC1918 range),
      and the backend would dutifully follow and proxy the response — a
      classic open-redirect-to-SSRF chain.

      With this loop, we re-run ``_cctv_host_allowed()`` on every hop's
      ``Location`` header. A redirect to a host that isn't on the allowlist
      is rejected with 502 rather than silently followed.
    """
    import requests as _req
    from urllib.parse import urlparse, urljoin

    headers = _cctv_upstream_headers(request, profile)
    current_url = target_url
    hops = 0
    try:
        while True:
            resp = _req.get(
                current_url,
                timeout=profile.timeout,
                stream=True,
                allow_redirects=False,
                headers=headers,
            )
            # Redirect handling — re-validate the next-hop host before following.
            if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("Location", "")
                resp.close()
                if hops >= _CCTV_MAX_REDIRECTS:
                    logger.warning(
                        "CCTV upstream redirect chain exceeded limit [%s] %s",
                        profile.name, target_url,
                    )
                    raise HTTPException(status_code=502, detail="Upstream redirect chain too long")
                if not location:
                    raise HTTPException(status_code=502, detail="Upstream redirect missing Location")
                next_url = urljoin(current_url, location)
                next_parsed = urlparse(next_url)
                if next_parsed.scheme not in ("http", "https"):
                    raise HTTPException(status_code=502, detail="Upstream redirect to non-HTTP scheme")
                if not _cctv_host_allowed(next_parsed.hostname):
                    logger.warning(
                        "CCTV upstream redirect to disallowed host [%s] %s -> %s",
                        profile.name, current_url, next_url,
                    )
                    raise HTTPException(status_code=502, detail="Upstream redirect to disallowed host")
                current_url = next_url
                hops += 1
                continue
            break
    except _req.exceptions.Timeout as exc:
        logger.warning("CCTV upstream timeout [%s] %s", profile.name, target_url)
        raise HTTPException(status_code=504, detail="Upstream timeout") from exc
    except _req.exceptions.RequestException as exc:
        logger.warning("CCTV upstream request failure [%s] %s: %s", profile.name, target_url, exc)
        raise HTTPException(status_code=502, detail="Upstream fetch failed") from exc
    if resp.status_code >= 400:
        logger.info("CCTV upstream HTTP %s [%s] %s", resp.status_code, profile.name, target_url)
        resp.close()
        raise HTTPException(status_code=int(resp.status_code), detail=f"Upstream returned {resp.status_code}")
    return resp


def _rewrite_cctv_hls_playlist(base_url: str, body: str) -> str:
    import re
    from urllib.parse import urljoin, urlparse

    def _rewrite_target(target: str) -> str:
        candidate = str(target or "").strip()
        if not candidate or candidate.startswith("data:"):
            return candidate
        absolute = urljoin(base_url, candidate)
        parsed_target = urlparse(absolute)
        if parsed_target.scheme not in ("http", "https"):
            return candidate
        if not _cctv_host_allowed(parsed_target.hostname):
            return candidate
        return _proxied_cctv_url(absolute)

    rewritten_lines: list = []
    for raw_line in body.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            rewritten_lines.append(raw_line)
            continue
        if stripped.startswith("#"):
            rewritten_lines.append(re.sub(r'URI="([^"]+)"',
                lambda match: f'URI="{_rewrite_target(match.group(1))}"', raw_line))
            continue
        rewritten_lines.append(_rewrite_target(stripped))
    return "\n".join(rewritten_lines) + ("\n" if body.endswith("\n") else "")


def _infer_cctv_media_type_from_url(target_url: str, content_type: str) -> str:
    from urllib.parse import urlparse

    clean_type = str(content_type or "").split(";", 1)[0].strip().lower()
    if clean_type and clean_type not in {"application/octet-stream", "binary/octet-stream"}:
        return content_type
    path = str(urlparse(target_url).path or "").lower()
    if path.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if path.endswith(".png"):
        return "image/png"
    if path.endswith(".webp"):
        return "image/webp"
    if path.endswith(".gif"):
        return "image/gif"
    if path.endswith(".mp4"):
        return "video/mp4"
    if path.endswith((".m3u8", ".m3u")):
        return "application/vnd.apple.mpegurl"
    if path.endswith((".mjpg", ".mjpeg")):
        return "multipart/x-mixed-replace"
    return content_type or "application/octet-stream"


def _proxy_cctv_media_response(request: Request, target_url: str):
    from urllib.parse import urlparse
    from fastapi.responses import Response
    parsed = urlparse(target_url)
    profile = _cctv_proxy_profile_for_url(target_url)
    resp = _fetch_cctv_upstream_response(request, target_url, profile)
    content_type = _infer_cctv_media_type_from_url(
        target_url,
        resp.headers.get("Content-Type", "application/octet-stream"),
    )
    is_hls_playlist = (
        ".m3u8" in str(parsed.path or "").lower()
        or "mpegurl" in content_type.lower()
        or "vnd.apple.mpegurl" in content_type.lower()
    )
    if is_hls_playlist:
        body = resp.text
        if "#EXTM3U" in body:
            body = _rewrite_cctv_hls_playlist(target_url, body)
        resp.close()
        return Response(content=body, media_type=content_type,
            headers=_cctv_response_headers(resp, cache_seconds=profile.cache_seconds, include_length=False))
    return StreamingResponse(resp.iter_content(chunk_size=65536), status_code=resp.status_code,
        media_type=content_type,
        headers=_cctv_response_headers(resp, cache_seconds=profile.cache_seconds),
        background=BackgroundTask(resp.close))


@router.get("/api/cctv/media")
@limiter.limit("120/minute")
async def cctv_media_proxy(request: Request, url: str = Query(...)):
    """Proxy CCTV media through the backend to bypass browser CORS restrictions."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if not _cctv_host_allowed(parsed.hostname):
        raise HTTPException(status_code=403, detail="Host not allowed")
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Invalid scheme")
    return _proxy_cctv_media_response(request, url)
