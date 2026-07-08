from __future__ import annotations

import os
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse

import requests
import yaml
from defusedxml import ElementTree as ET


REGISTRY_RELATIVE_PATH = Path("docs/business-intel/southeast-nc-source-registry.yaml")
CONFIG_REGISTRY_PATH = Path(__file__).resolve().parents[1] / "config" / "southeast-nc-source-registry.yaml"

_ALLOWED_HOST_SUFFIXES = (
    "nhcgov.com",
    "carolinabeach.org",
    "carolinabeach.gov",
    "townofwrightsvillebeach.com",
    "google.com",
    "googleusercontent.com",
    "arcgis.com",
    "brunswickcountync.gov",
)

_KML_NS = {"kml": "http://www.opengis.net/kml/2.2"}
_WEB_MERCATOR_WKIDS = {3857, 102100, 102113}
_WEB_MERCATOR_RADIUS = 6378137.0
_WEB_MERCATOR_MAX = 20037508.342789244


@dataclass(frozen=True)
class PermitSource:
    id: str
    name: str
    category: str
    access_method: str
    url: str
    enabled: bool
    jurisdiction_id: str
    jurisdiction_name: str
    field_map: dict[str, str]
    lead_categories: list[str]
    attribution: str
    terms_reviewed: bool
    commercial_use: str
    notes: list[str]


def registry_path() -> Path:
    configured = os.environ.get("LOCAL_PERMIT_SOURCE_REGISTRY", "").strip()
    if configured:
        return Path(configured)

    cwd_candidate = Path.cwd() / REGISTRY_RELATIVE_PATH
    if cwd_candidate.exists():
        return cwd_candidate

    repo_candidate = Path(__file__).resolve().parents[2] / REGISTRY_RELATIVE_PATH
    if repo_candidate.exists():
        return repo_candidate

    return CONFIG_REGISTRY_PATH


def load_source_registry(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    source_path = Path(path) if path else registry_path()
    with source_path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise ValueError("source registry must be a YAML object")
    return payload


def list_permit_sources(*, enabled_only: bool = False, path: str | os.PathLike[str] | None = None) -> list[dict[str, Any]]:
    registry = load_source_registry(path)
    sources = []
    for source in _flatten_sources(registry):
        if enabled_only and not source.enabled:
            continue
        sources.append(_source_public_view(source))
    return sources


def preview_permit_sources(
    *,
    source_id: str | None = None,
    jurisdiction_id: str | None = None,
    limit: int = 25,
    path: str | os.PathLike[str] | None = None,
    timeout: float = 12.0,
) -> dict[str, Any]:
    registry = load_source_registry(path)
    selected = []
    for source in _flatten_sources(registry):
        if not source.enabled:
            continue
        if source.category not in {"permits", "permits_delta"}:
            continue
        if source_id and source.id != source_id:
            continue
        if jurisdiction_id and source.jurisdiction_id != jurisdiction_id:
            continue
        selected.append(source)

    bounded_limit = max(1, min(100, int(limit or 25)))
    source_results = []
    records: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    started = time.time()

    for source in selected:
        remaining = max(1, bounded_limit - len(records))
        try:
            source_records = _preview_source(source, limit=remaining, timeout=timeout)
            source_results.append(
                {
                    "id": source.id,
                    "name": source.name,
                    "jurisdiction_id": source.jurisdiction_id,
                    "count": len(source_records),
                    "access_method": source.access_method,
                    "attribution": source.attribution,
                }
            )
            records.extend(source_records)
        except Exception as exc:
            errors.append({"source_id": source.id, "detail": f"{type(exc).__name__}: {exc}"})
        if len(records) >= bounded_limit:
            break

    return {
        "query": {
            "source_id": source_id or "",
            "jurisdiction_id": jurisdiction_id or "",
            "limit": bounded_limit,
            "generated_at": int(time.time()),
        },
        "summary": {
            "selected_sources": len(selected),
            "queried_sources": len(source_results),
            "returned": len(records[:bounded_limit]),
            "errors": len(errors),
            "elapsed_ms": round((time.time() - started) * 1000),
        },
        "sources": source_results,
        "records": records[:bounded_limit],
        "errors": errors,
    }


def normalize_arcgis_feature(source: PermitSource, feature: dict[str, Any]) -> dict[str, Any]:
    attrs = feature.get("attributes") if isinstance(feature, dict) else {}
    attrs = attrs if isinstance(attrs, dict) else {}
    geometry = feature.get("geometry") if isinstance(feature, dict) else {}
    geometry = geometry if isinstance(geometry, dict) else {}
    return _normalize_attributes(source, attrs, geometry=geometry)


def normalize_kml_placemark(source: PermitSource, placemark: ET.Element) -> dict[str, Any]:
    def text(path: str) -> str:
        node = placemark.find(path, _KML_NS)
        return _clean_text(node.text if node is not None else "")

    extended: dict[str, str] = {}
    for data in placemark.findall(".//kml:ExtendedData/kml:Data", _KML_NS):
        name = str(data.attrib.get("name") or "").strip()
        value = data.find("kml:value", _KML_NS)
        if name and value is not None:
            extended[_normalize_key(name)] = _clean_text(value.text)

    coords = text(".//kml:Point/kml:coordinates")
    lng, lat = _parse_kml_point(coords)
    attrs = {
        "Placemark.name": text("kml:name"),
        "ExtendedData.Address": _first_extended(extended, "address"),
        "ExtendedData.Approval_Date": _first_extended(extended, "approval_date", "approval date"),
        "ExtendedData.Status": _first_extended(extended, "status"),
        "ExtendedData.Permit_Type": _first_extended(extended, "permit_type", "permit type"),
        "ExtendedData.Project_Description": _first_extended(
            extended,
            "project_description",
            "project description",
            "project description ",
        ),
        "ExtendedData.Final_Inspection_Date": _first_extended(
            extended,
            "final_inspection_date",
            "final inspection date",
        ),
    }
    return _normalize_attributes(source, attrs, geometry={"x": lng, "y": lat})


def _flatten_sources(registry: dict[str, Any]) -> list[PermitSource]:
    flattened = []
    for jurisdiction in registry.get("jurisdictions") or []:
        if not isinstance(jurisdiction, dict):
            continue
        jurisdiction_id = str(jurisdiction.get("id") or "").strip()
        jurisdiction_name = str(jurisdiction.get("name") or jurisdiction_id).strip()
        for source in jurisdiction.get("sources") or []:
            if not isinstance(source, dict):
                continue
            if source.get("layers") and source.get("access_method") == "arcgis_webmap_cityworks_layers":
                flattened.extend(_sources_from_layers(source, jurisdiction_id, jurisdiction_name))
                continue
            flattened.append(_source_from_dict(source, jurisdiction_id, jurisdiction_name))
    return [source for source in flattened if source.id and source.url]


def _sources_from_layers(source: dict[str, Any], jurisdiction_id: str, jurisdiction_name: str) -> list[PermitSource]:
    sources = []
    common_field_map = dict(source.get("common_field_map") or {})
    for layer in source.get("layers") or []:
        if not isinstance(layer, dict):
            continue
        item = {
            **source,
            "id": layer.get("id") or source.get("id"),
            "name": layer.get("title") or source.get("name"),
            "url": layer.get("url") or "",
            "field_map": {**common_field_map, **dict(layer.get("field_map") or {})},
            "lead_categories": layer.get("lead_categories") or source.get("lead_categories") or [],
            "layers": [],
        }
        sources.append(_source_from_dict(item, jurisdiction_id, jurisdiction_name))
    return sources


def _source_from_dict(source: dict[str, Any], jurisdiction_id: str, jurisdiction_name: str) -> PermitSource:
    return PermitSource(
        id=str(source.get("id") or "").strip(),
        name=str(source.get("name") or source.get("title") or "").strip(),
        category=str(source.get("category") or "").strip(),
        access_method=str(source.get("access_method") or "").strip(),
        url=str(source.get("url") or source.get("app_url") or "").strip(),
        enabled=bool(source.get("enabled", False)),
        jurisdiction_id=jurisdiction_id,
        jurisdiction_name=jurisdiction_name,
        field_map={str(k): str(v) for k, v in dict(source.get("field_map") or {}).items()},
        lead_categories=[str(item) for item in source.get("lead_categories") or []],
        attribution=str(source.get("attribution") or "").strip(),
        terms_reviewed=bool(source.get("terms_reviewed", False)),
        commercial_use=str(source.get("commercial_use") or "").strip(),
        notes=[str(item) for item in source.get("notes") or []],
    )


def _source_public_view(source: PermitSource) -> dict[str, Any]:
    return {
        "id": source.id,
        "name": source.name,
        "category": source.category,
        "access_method": source.access_method,
        "enabled": source.enabled,
        "jurisdiction_id": source.jurisdiction_id,
        "jurisdiction_name": source.jurisdiction_name,
        "lead_categories": source.lead_categories,
        "attribution": source.attribution,
        "terms_reviewed": source.terms_reviewed,
        "commercial_use": source.commercial_use,
        "notes": source.notes[:4],
    }


def _preview_source(source: PermitSource, *, limit: int, timeout: float) -> list[dict[str, Any]]:
    if source.access_method in {"arcgis_feature_server", "arcgis_map_server_layer"} or "FeatureServer" in source.url:
        return _preview_arcgis(source, limit=limit, timeout=timeout)
    if source.access_method == "google_my_maps_kml":
        return _preview_kml(source, limit=limit, timeout=timeout)
    return []


def _preview_arcgis(source: PermitSource, *, limit: int, timeout: float) -> list[dict[str, Any]]:
    _assert_allowed_url(source.url)
    query_url = _arcgis_query_url(source.url)
    params = {
        "f": "json",
        "where": "1=1",
        "outFields": "*",
        "returnGeometry": "true",
        "resultRecordCount": max(1, min(100, limit)),
        "orderByFields": _arcgis_order_field(source),
    }
    params = {key: value for key, value in params.items() if value}
    response = requests.get(query_url, params=params, timeout=timeout, headers={"User-Agent": "operator-local-permit-preview"})
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict) and payload.get("error"):
        raise ValueError(str(payload["error"]))
    features = payload.get("features") if isinstance(payload, dict) else []
    return [normalize_arcgis_feature(source, feature) for feature in features[:limit] if isinstance(feature, dict)]


def _preview_kml(source: PermitSource, *, limit: int, timeout: float) -> list[dict[str, Any]]:
    _assert_allowed_url(source.url)
    response = requests.get(source.url, timeout=timeout, headers={"User-Agent": "operator-local-permit-preview"})
    response.raise_for_status()
    root = ET.fromstring(response.content)
    records = []
    for placemark in root.findall(".//kml:Placemark", _KML_NS):
        record = normalize_kml_placemark(source, placemark)
        if record.get("address") or record.get("permit_number") or record.get("description"):
            records.append(record)
        if len(records) >= limit:
            break
    return records


def _normalize_attributes(source: PermitSource, attrs: dict[str, Any], *, geometry: dict[str, Any]) -> dict[str, Any]:
    def mapped(name: str, *fallbacks: str) -> Any:
        field = source.field_map.get(name)
        if field and field in attrs:
            return attrs.get(field)
        for fallback in fallbacks:
            if fallback in attrs:
                return attrs.get(fallback)
        return None

    x, y = _geometry_lon_lat(geometry)
    label = _clean_text(
        mapped("permit_number", "CASE_NUMBER", "PermitNumber", "PERMIT_NUMBER", "Placemark.name")
        or mapped("permit_tag", "CASE_NAME")
        or source.name
    )
    permit_type = _clean_text(
        mapped("permit_type", "CASE_TYPE_DESC", "PermitType", "PERMIT_TYPE", "ExtendedData.Permit_Type")
        or mapped("project_type", "ProjectType")
        or source.category
    )
    description = _clean_text(
        mapped("description", "PROJECT_DESC", "Description", "DESCRIPTION", "ExtendedData.Project_Description")
        or mapped("project", "PROJECT")
        or mapped("permit_type_description", "CASE_TYPE_DESC")
        or ""
    )
    status = _clean_text(
        mapped(
            "status",
            "CASE_STATUS",
            "PermitStatus",
            "PERMIT_STATUS",
            "ExtendedData.Status",
            "PemitProjectStatus",
            "PermitProjectStatus",
        )
        or ""
    )
    address = _clean_text(
        mapped("address", "Location", "ParcelAddress", "ExtendedData.Address")
        or _address_from_parts(attrs)
    )
    lead_category, score = _classify_lead(source, f"{source.name} {permit_type} {description} {label}")
    return {
        "id": f"{source.id}:{label}",
        "source_id": source.id,
        "source_name": source.name,
        "jurisdiction_id": source.jurisdiction_id,
        "jurisdiction_name": source.jurisdiction_name,
        "label": label,
        "permit_number": label,
        "permit_type": permit_type,
        "status": status,
        "address": address,
        "description": description,
        "contractor": _clean_text(mapped("contractor", "BUSINESS_NAME", "SubContractor", "GENERAL_CONTRACTOR") or ""),
        "parcel_id": _clean_text(mapped("parcel_id", "PID", "ParcelID") or ""),
        "issued_at": _clean_text(mapped("issued_at", "DateIssued", "ISSUE_DATE") or ""),
        "accepted_at": _clean_text(mapped("accepted_at", "DATE_ACCEPTED") or ""),
        "finaled_at": _clean_text(mapped("finaled_at", "FINALED_DATE", "ExtendedData.Final_Inspection_Date") or ""),
        "valuation": _to_float(mapped("valuation", "VALUATION", "EstimatedRetailValue", "PermitAmount")),
        "lat": y,
        "lng": x,
        "lead_category": lead_category,
        "score": score,
        "lead_categories": source.lead_categories,
        "attribution": source.attribution,
    }


def _classify_lead(source: PermitSource, text: str) -> tuple[str, int]:
    haystack = text.lower()
    keyword_scores = [
        ("pool", ("pool", "swimming", "spa"), 94),
        ("fence", ("fence", "gate", "barrier"), 90),
        ("coastal_docks_bulkheads", ("dock", "bulkhead", "pier", "boatlift", "piling", "cama"), 88),
        ("new_home", ("new construction", "new residential", "single family", "new dwelling"), 84),
        ("hardscape", ("driveway", "hardscape", "patio", "sidewalk"), 78),
        ("sitework", ("fill", "grade", "clear", "grading", "stormwater", "drainage"), 76),
        ("remodel_addition", ("addition", "renovation", "repair", "remodel", "alteration"), 74),
    ]
    for category, keywords, score in keyword_scores:
        if any(keyword in haystack for keyword in keywords):
            return category, score
    if source.lead_categories:
        return source.lead_categories[0], 60
    return "permit", 50


def _arcgis_query_url(url: str) -> str:
    clean = url.rstrip("/")
    if clean.lower().endswith("/query"):
        return clean
    return f"{clean}/query"


def _arcgis_order_field(source: PermitSource) -> str:
    for field in ("issued_at", "accepted_at", "applied_at"):
        mapped = source.field_map.get(field)
        if mapped:
            return f"{mapped} DESC"
    return ""


def _assert_allowed_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("only https permit source URLs are allowed")
    host = (parsed.hostname or "").lower()
    if not any(host == suffix or host.endswith(f".{suffix}") for suffix in _ALLOWED_HOST_SUFFIXES):
        raise ValueError(f"permit source host not allowed: {host}")


def _parse_kml_point(value: str) -> tuple[float | None, float | None]:
    first = value.split()[0] if value else ""
    parts = first.split(",")
    if len(parts) < 2:
        return None, None
    return _to_float(parts[0]), _to_float(parts[1])


def _geometry_lon_lat(geometry: dict[str, Any]) -> tuple[float | None, float | None]:
    x = _to_float(_first_present(geometry.get("x"), geometry.get("longitude"), geometry.get("lon")))
    y = _to_float(_first_present(geometry.get("y"), geometry.get("latitude"), geometry.get("lat")))
    if x is None or y is None:
        return x, y

    spatial_reference = geometry.get("spatialReference")
    wkid = None
    if isinstance(spatial_reference, dict):
        wkid = _to_int(spatial_reference.get("latestWkid") or spatial_reference.get("wkid"))

    looks_projected = abs(x) > 180 or abs(y) > 90
    if wkid in _WEB_MERCATOR_WKIDS or looks_projected:
        return _web_mercator_to_lon_lat(x, y)
    return x, y


def _web_mercator_to_lon_lat(x: float, y: float) -> tuple[float | None, float | None]:
    if abs(x) > _WEB_MERCATOR_MAX * 1.5 or abs(y) > _WEB_MERCATOR_MAX * 1.5:
        return None, None
    clamped_y = max(-_WEB_MERCATOR_MAX, min(_WEB_MERCATOR_MAX, y))
    lon = (x / _WEB_MERCATOR_RADIUS) * (180.0 / math.pi)
    lat = (2.0 * math.atan(math.exp(clamped_y / _WEB_MERCATOR_RADIUS)) - math.pi / 2.0) * (180.0 / math.pi)
    return lon, lat


def _first_extended(values: dict[str, str], *keys: str) -> str:
    for key in keys:
        normalized = _normalize_key(key)
        if values.get(normalized):
            return values[normalized]
    return ""


def _normalize_key(value: str) -> str:
    return "_".join(str(value or "").strip().lower().split())


def _address_from_parts(attrs: dict[str, Any]) -> str:
    parts = [
        attrs.get("NUMBER"),
        attrs.get("DIR"),
        attrs.get("STREET"),
        attrs.get("TYPE"),
        attrs.get("CITY"),
        attrs.get("STATE"),
        attrs.get("ZIPCODE"),
    ]
    return _clean_text(" ".join(str(part or "") for part in parts))


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())


def _to_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result or result in (float("inf"), float("-inf")):
        return None
    return result


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None
