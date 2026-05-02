"""Pre-processed SAR product clients (Mode B).

These clients pull *already-computed* SAR products from third parties.
There is no local DSP, no GPU, no scene download — just metadata-and-result
JSON over HTTPS.

Providers (all free):

* **NASA OPERA via ASF** — DSWx (water), DIST-ALERT (vegetation), DISP (deformation).
  Needs a free Earthdata bearer token.
* **Copernicus EGMS** — EU ground motion velocity (mm/yr).
* **Global Flood Monitoring (GFM)** — Daily Sentinel-1 flood polygons.
* **Copernicus EMS Rapid Mapping** — Active disaster damage GeoJSON.
* **UNOSAT Live** — UN damage assessments.

Each ``fetch_*_for_aoi`` returns a list of ``SarAnomaly`` ready to be
written into ``latest_data["sar_anomalies"]``.

Network failures, missing tokens, and unavailable providers are all
handled by returning an empty list and logging at debug level.  This
keeps the fetcher loop resilient — one provider being down never blocks
the others.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from services.network_utils import fetch_with_curl
from services.sar.sar_aoi import SarAoi, bbox_for_aoi, point_in_aoi
from services.sar.sar_config import (
    copernicus_token,
    earthdata_token,
)
from services.sar.sar_normalize import (
    SarAnomaly,
    evidence_hash_for_payload,
    make_anomaly_id,
    now_epoch,
)

logger = logging.getLogger(__name__)

CMR_GRANULES_URL = "https://cmr.earthdata.nasa.gov/search/granules.json"
EMS_ACTIVATIONS_URL = (
    "https://rapidmapping.emergency.copernicus.eu/backend/dashboard-api/public-activations-info/"
)
UNOSAT_HDX_SEARCH_URL = "https://data.humdata.org/api/3/action/package_search"
# GFM is only accessible via openEO (OIDC auth + Python client library),
# not a simple REST endpoint.  Tracked in _gfm_hint_once.
_GFM_DISABLED_HINT_LOGGED = False


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def _iso_utc(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_epoch(value: Any) -> int:
    if value is None:
        return now_epoch()
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value)
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            return int(datetime.strptime(s[: len(fmt) + 2 if "Z" in fmt else len(fmt)], fmt).timestamp())
        except (ValueError, TypeError):
            continue
    try:
        return int(datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").timestamp())
    except (ValueError, TypeError):
        return now_epoch()


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# NASA OPERA (DSWx + DIST-ALERT) via NASA CMR
# ---------------------------------------------------------------------------
# CMR is the public, unauthenticated granule search.  Token only needed if
# we want to download the products themselves; metadata is open.  DSWx-S1,
# DSWx-HLS, and DIST-ALERT are accessible here; DISP-S1 is not yet seeded
# into CMR for arbitrary AOIs so we skip it.

OPERA_SHORTNAMES = (
    ("OPERA_L3_DSWX-S1_V1", "surface_water_change", "OPERA-DSWx-S1", "Sentinel-1 surface water extent"),
    ("OPERA_L3_DSWX-HLS_V1", "surface_water_change", "OPERA-DSWx-HLS", "HLS surface water extent"),
    ("OPERA_L3_DIST-ALERT-HLS_V1", "vegetation_disturbance", "OPERA-DIST-ALERT", "Vegetation/land-surface disturbance alert"),
)


def fetch_opera_for_aoi(aoi: SarAoi, lookback_days: int = 7) -> list[SarAnomaly]:
    """Fetch OPERA pre-processed products covering this AOI via NASA CMR.

    CMR granule search is public — no token required for metadata.  The
    Earthdata token is only used (when present) to authenticate against
    PO.DAAC / LP DAAC if the browse URL is later fetched.
    """
    end = datetime.utcnow()
    start = end - timedelta(days=lookback_days)
    min_lon, min_lat, max_lon, max_lat = bbox_for_aoi(aoi)
    bbox = f"{min_lon},{min_lat},{max_lon},{max_lat}"
    temporal = f"{_iso_utc(start)},{_iso_utc(end)}"
    token = earthdata_token()
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    out: list[SarAnomaly] = []
    for short_name, kind, solver, summary in OPERA_SHORTNAMES:
        params = {
            "short_name": short_name,
            "bounding_box": bbox,
            "temporal": temporal,
            "page_size": "20",
            "sort_key": "-start_date",
        }
        qs = "&".join(f"{k}={_url_encode(v)}" for k, v in params.items())
        url = f"{CMR_GRANULES_URL}?{qs}"
        try:
            resp = fetch_with_curl(url, timeout=20, headers=headers)
        except (ConnectionError, TimeoutError, OSError) as exc:
            logger.debug("OPERA %s for %s failed: %s", short_name, aoi.id, exc)
            continue
        if resp.status_code != 200:
            logger.debug("OPERA %s for %s → HTTP %s", short_name, aoi.id, resp.status_code)
            continue
        try:
            body = resp.json()
        except (ValueError, KeyError):
            continue
        entries = body.get("feed", {}).get("entry", []) if isinstance(body, dict) else []
        if not isinstance(entries, list):
            continue
        for item in entries:
            anomaly = _opera_cmr_item_to_anomaly(item, aoi, kind, solver, summary)
            if anomaly is not None:
                out.append(anomaly)
    return out


def _opera_cmr_item_to_anomaly(
    item: dict[str, Any],
    aoi: SarAoi,
    kind: str,
    solver: str,
    summary: str,
) -> SarAnomaly | None:
    """Convert a CMR granule entry into an SarAnomaly."""
    raw_id = str(item.get("id") or item.get("producer_granule_id") or item.get("title") or "")
    if not raw_id:
        return None
    # CMR provides bounding box as "s w n e" strings in the 'boxes' field;
    # extract the centre as a fallback for display.
    lat, lon = aoi.center_lat, aoi.center_lon
    boxes = item.get("boxes")
    if isinstance(boxes, list) and boxes:
        parts = str(boxes[0]).split()
        if len(parts) >= 4:
            try:
                s, w, n, e = (float(p) for p in parts[:4])
                lat = (s + n) / 2
                lon = (w + e) / 2
            except (TypeError, ValueError):
                pass
    when = _parse_epoch(item.get("time_start") or item.get("updated"))
    # Preferred browse image for the anomaly link, else the producer URL.
    prov_url = ""
    for link in item.get("links") or []:
        if not isinstance(link, dict):
            continue
        rel = str(link.get("rel", ""))
        if "browse" in rel.lower() or "data#" in rel:
            prov_url = str(link.get("href") or "")
            if prov_url:
                break
    if not prov_url and item.get("links"):
        first = item["links"][0] if isinstance(item["links"][0], dict) else {}
        prov_url = str(first.get("href") or "")
    payload = {"raw_id": raw_id, "dataset": solver, "time": item.get("time_start")}
    return SarAnomaly(
        anomaly_id=make_anomaly_id(solver, raw_id, lat, lon),
        kind=kind,
        lat=lat,
        lon=lon,
        magnitude=0.0,
        magnitude_unit="",
        confidence=0.8,
        first_seen=when,
        last_seen=when,
        aoi_id=aoi.id,
        scene_count=1,
        solver=solver,
        source_constellation="Sentinel-1" if "S1" in solver else "HLS",
        provenance_url=prov_url,
        category=aoi.category,
        title=f"{solver}: {summary}",
        summary=summary,
        evidence_hash=evidence_hash_for_payload(payload),
        extras={"raw_id": raw_id, "dataset": solver, "cmr_id": str(item.get("id", ""))},
    )


# ---------------------------------------------------------------------------
# Copernicus EGMS (EU only)
# ---------------------------------------------------------------------------

def fetch_egms_for_aoi(aoi: SarAoi) -> list[SarAnomaly]:
    """Pull EGMS deformation products if a Copernicus token is configured.

    EGMS only covers Europe, so AOIs outside that bbox return [] without
    a network call.
    """
    if not copernicus_token():
        logger.debug("EGMS: skipping AOI %s — no Copernicus token", aoi.id)
        return []
    if not _aoi_in_europe(aoi):
        return []
    # EGMS download API requires per-product manifests; for v1 we emit a
    # single anomaly that points to the EGMS portal so users get a
    # direct link.  Real product ingestion can come later.
    payload = {"provider": "EGMS", "aoi": aoi.id}
    url = f"https://egms.land.copernicus.eu/insar-api/?aoi={aoi.id}"
    return [
        SarAnomaly(
            anomaly_id=make_anomaly_id("EGMS", aoi.id, aoi.center_lat, aoi.center_lon),
            kind="ground_deformation",
            lat=aoi.center_lat,
            lon=aoi.center_lon,
            magnitude=0.0,
            magnitude_unit="mm/yr",
            confidence=0.7,
            first_seen=now_epoch(),
            last_seen=now_epoch(),
            aoi_id=aoi.id,
            scene_count=0,
            solver="EGMS",
            source_constellation="Sentinel-1",
            provenance_url=url,
            category=aoi.category,
            title=f"EGMS coverage available for {aoi.name}",
            summary=(
                "European Ground Motion Service has InSAR-derived deformation "
                "velocity for this AOI.  Open the provenance URL to view the map."
            ),
            evidence_hash=evidence_hash_for_payload(payload),
            extras={"egms_aoi": aoi.id},
        )
    ]


def _aoi_in_europe(aoi: SarAoi) -> bool:
    return -25 <= aoi.center_lon <= 45 and 34 <= aoi.center_lat <= 72


# ---------------------------------------------------------------------------
# Global Flood Monitoring (GFM) — daily Sentinel-1 flood polygons
# ---------------------------------------------------------------------------

def fetch_gfm_for_aoi(aoi: SarAoi, lookback_days: int = 7) -> list[SarAnomaly]:
    """GFM — disabled: requires openEO client + OIDC auth, not plain REST.

    Copernicus GFM does not expose a plain public REST endpoint; the only
    supported programmatic access is via the openEO Python client with
    OIDC auth against openeo.cloud.  That is a full integration (Python
    library, OIDC token refresh, collection loading) and is deliberately
    not attempted here — fetching it on every cycle with a guessed URL
    just burned time and polluted logs.  Flood coverage comes from OPERA
    DSWx-S1 (NASA CMR) which is already integrated above.
    """
    global _GFM_DISABLED_HINT_LOGGED
    if not _GFM_DISABLED_HINT_LOGGED:
        _GFM_DISABLED_HINT_LOGGED = True
        logger.info(
            "SAR GFM provider disabled — requires openEO client + OIDC auth. "
            "Flood detection falls back to OPERA DSWx-S1 via NASA CMR."
        )
    return []


# ---------------------------------------------------------------------------
# Copernicus EMS Rapid Mapping (active disaster activations)
# ---------------------------------------------------------------------------

_EMS_CACHE: dict[str, Any] = {"fetched_at": 0, "activations": []}
_EMS_CACHE_TTL_S = 900  # 15 minutes — activation list rarely changes


def _fetch_ems_activations() -> list[dict[str, Any]]:
    """Fetch (and cache) the EMS rapid-mapping activation list.

    The dashboard API is paginated; we pull the first 200 results sorted
    by activation time.  Result is cached for ~15 minutes so every AOI
    call in the same cycle shares one network round-trip.
    """
    import time as _time
    now = int(_time.time())
    if now - int(_EMS_CACHE.get("fetched_at", 0)) < _EMS_CACHE_TTL_S:
        return list(_EMS_CACHE.get("activations", []))

    url = f"{EMS_ACTIVATIONS_URL}?limit=200&offset=0"
    try:
        resp = fetch_with_curl(url, timeout=20)
    except (ConnectionError, TimeoutError, OSError) as exc:
        logger.debug("EMS activation list fetch failed: %s", exc)
        return list(_EMS_CACHE.get("activations", []))
    if resp.status_code != 200:
        logger.debug("EMS activation list → HTTP %s", resp.status_code)
        return list(_EMS_CACHE.get("activations", []))
    try:
        body = resp.json()
    except (ValueError, KeyError):
        return list(_EMS_CACHE.get("activations", []))
    results = body.get("results") if isinstance(body, dict) else None
    if not isinstance(results, list):
        return []
    _EMS_CACHE["fetched_at"] = now
    _EMS_CACHE["activations"] = results
    return results


def _parse_centroid_wkt(wkt: str) -> tuple[float, float] | None:
    """Parse 'POINT (lon lat)' into (lat, lon)."""
    if not wkt or not isinstance(wkt, str):
        return None
    s = wkt.strip()
    if not s.upper().startswith("POINT"):
        return None
    try:
        body = s[s.index("(") + 1 : s.rindex(")")]
        parts = body.split()
        if len(parts) < 2:
            return None
        return (float(parts[1]), float(parts[0]))
    except (ValueError, IndexError):
        return None


def fetch_ems_for_aoi(aoi: SarAoi, lookback_days: int = 30) -> list[SarAnomaly]:
    """Pull recent EMS rapid-mapping activations near the AOI.

    Uses the new Copernicus EMS Rapid Mapping dashboard API which returns
    activations with a ``centroid`` WKT point, ISO ``eventTime``,
    ``category``, and ``code``.  Result is filtered to activations whose
    centroid lies within the AOI radius and within the lookback window.
    """
    activations = _fetch_ems_activations()
    if not activations:
        return []
    cutoff = now_epoch() - lookback_days * 86400
    out: list[SarAnomaly] = []
    for item in activations:
        if not isinstance(item, dict):
            continue
        coords = _parse_centroid_wkt(str(item.get("centroid", "")))
        if not coords:
            continue
        lat, lon = coords
        if not point_in_aoi(lat, lon, aoi):
            continue
        when = _parse_epoch(item.get("eventTime") or item.get("activationTime"))
        if when < cutoff:
            continue
        code = str(item.get("code") or "")
        name = str(item.get("name") or f"EMS activation {code}")
        category = str(item.get("category") or "").lower()
        countries = item.get("countries") or []
        country_str = ", ".join(countries) if isinstance(countries, list) else ""
        payload = {"raw": item, "provider": "EMS"}
        out.append(
            SarAnomaly(
                anomaly_id=make_anomaly_id("EMS", code, lat, lon),
                kind="damage_assessment" if "damage" not in category else category.replace(" ", "_"),
                lat=lat,
                lon=lon,
                magnitude=_safe_float(item.get("n_products")),
                magnitude_unit="products",
                confidence=0.95,
                first_seen=when,
                last_seen=_parse_epoch(item.get("lastUpdate") or item.get("activationTime")),
                aoi_id=aoi.id,
                scene_count=int(item.get("n_aois") or 0),
                solver="EMS",
                source_constellation="multi",
                provenance_url=f"https://rapidmapping.emergency.copernicus.eu/activation/{code}",
                category=aoi.category,
                title=name,
                summary=(
                    f"Copernicus EMS {category or 'activation'} {code} "
                    f"({country_str})." if country_str else
                    f"Copernicus EMS {category or 'activation'} {code}."
                ),
                evidence_hash=evidence_hash_for_payload(payload),
                extras={"code": code, "countries": list(countries) if isinstance(countries, list) else []},
            )
        )
    return out


# ---------------------------------------------------------------------------
# UNOSAT
# ---------------------------------------------------------------------------

# UNOSAT publishes through the Humanitarian Data Exchange (HDX) using a
# standard CKAN API.  Country-level filtering is possible via the
# package metadata so we can match AOIs by ISO-3166 country name or
# bounding box when present.
_UNOSAT_CACHE: dict[str, Any] = {"fetched_at": 0, "packages": []}
_UNOSAT_CACHE_TTL_S = 1800  # 30 min — UNOSAT publishes infrequently

# AOI → list of country names UNOSAT uses on HDX.  Kept deliberately small;
# expand as new AOIs are added.  If the AOI id isn't in this map, UNOSAT
# falls back to country-agnostic match (spatial is not exposed by HDX).
_AOI_COUNTRY_HINTS: dict[str, tuple[str, ...]] = {
    "kyiv_metro": ("Ukraine",),
    "gaza_strip": ("State of Palestine", "Palestine", "Israel"),
    "taiwan_strait": ("Taiwan (Province of China)", "Taiwan"),
    "san_andreas_central": ("United States of America", "United States"),
    "three_gorges_dam": ("China",),
}


def _fetch_unosat_packages() -> list[dict[str, Any]]:
    """Fetch (and cache) recent UNOSAT packages from HDX."""
    import time as _time
    now = int(_time.time())
    if now - int(_UNOSAT_CACHE.get("fetched_at", 0)) < _UNOSAT_CACHE_TTL_S:
        return list(_UNOSAT_CACHE.get("packages", []))

    url = (
        f"{UNOSAT_HDX_SEARCH_URL}?q=organization:unosat&rows=50&sort=metadata_modified+desc"
    )
    # HDX CKAN returns 406 without explicit Accept + a browser-ish UA.
    hdx_headers = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (compatible; ShadowBroker-SAR/1.0)",
    }
    try:
        resp = fetch_with_curl(url, timeout=20, headers=hdx_headers)
    except (ConnectionError, TimeoutError, OSError) as exc:
        logger.debug("UNOSAT HDX fetch failed: %s", exc)
        return list(_UNOSAT_CACHE.get("packages", []))
    if resp.status_code != 200:
        return list(_UNOSAT_CACHE.get("packages", []))
    try:
        body = resp.json()
    except (ValueError, KeyError):
        return list(_UNOSAT_CACHE.get("packages", []))
    result = body.get("result") if isinstance(body, dict) else None
    if not isinstance(result, dict):
        return []
    packages = result.get("results")
    if not isinstance(packages, list):
        return []
    _UNOSAT_CACHE["fetched_at"] = now
    _UNOSAT_CACHE["packages"] = packages
    return packages


def _package_countries(pkg: dict[str, Any]) -> list[str]:
    """Extract country names from an HDX package."""
    # HDX encodes countries as a group list, plus 'solr_additions' JSON string.
    out: list[str] = []
    for group in pkg.get("groups") or []:
        if isinstance(group, dict):
            name = group.get("display_name") or group.get("title") or group.get("name")
            if name:
                out.append(str(name))
    # solr_additions is a JSON string like '{"countries": ["Mozambique"]}'
    solr = pkg.get("solr_additions")
    if isinstance(solr, str) and solr:
        try:
            import json as _json
            parsed = _json.loads(solr)
            for c in parsed.get("countries", []):
                if c and c not in out:
                    out.append(str(c))
        except (ValueError, TypeError):
            pass
    return out


def fetch_unosat_for_aoi(aoi: SarAoi, lookback_days: int = 30) -> list[SarAnomaly]:
    """Pull UNOSAT damage assessments for this AOI from HDX CKAN.

    HDX doesn't expose precise coordinates, so we filter by country name
    using ``_AOI_COUNTRY_HINTS``.  AOIs without a country hint get no
    UNOSAT data — this is intentional; false-positive country matches
    would be worse than silence.
    """
    hints = _AOI_COUNTRY_HINTS.get(aoi.id)
    if not hints:
        return []
    packages = _fetch_unosat_packages()
    if not packages:
        return []
    cutoff = now_epoch() - lookback_days * 86400
    out: list[SarAnomaly] = []
    for pkg in packages:
        if not isinstance(pkg, dict):
            continue
        countries = _package_countries(pkg)
        if not any(h in countries for h in hints):
            continue
        when = _parse_epoch(pkg.get("metadata_modified") or pkg.get("metadata_created"))
        if when < cutoff:
            continue
        product_id = str(pkg.get("id") or pkg.get("name") or "")
        title = str(pkg.get("title") or "UNOSAT damage assessment")
        notes = str(pkg.get("notes") or "")[:400]
        payload = {"raw_id": product_id, "provider": "UNOSAT", "countries": countries}
        out.append(
            SarAnomaly(
                anomaly_id=make_anomaly_id("UNOSAT", product_id, aoi.center_lat, aoi.center_lon),
                kind="damage_assessment",
                lat=aoi.center_lat,
                lon=aoi.center_lon,
                magnitude=0.0,
                magnitude_unit="",
                confidence=0.9,
                first_seen=when,
                last_seen=when,
                aoi_id=aoi.id,
                scene_count=0,
                solver="UNOSAT",
                source_constellation="multi",
                provenance_url=f"https://data.humdata.org/dataset/{pkg.get('name', '')}",
                category=aoi.category,
                title=title,
                summary=notes or "UNOSAT satellite analysis published via HDX.",
                evidence_hash=evidence_hash_for_payload(payload),
                extras={"hdx_id": product_id, "countries": countries},
            )
        )
    return out


# ---------------------------------------------------------------------------
# Shared low-level utilities
# ---------------------------------------------------------------------------

def _url_encode(value: str) -> str:
    safe = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~()")
    out: list[str] = []
    for ch in str(value):
        if ch in safe:
            out.append(ch)
        elif ch == " ":
            out.append("%20")
        else:
            out.append("".join(f"%{b:02X}" for b in ch.encode("utf-8")))
    return "".join(out)
