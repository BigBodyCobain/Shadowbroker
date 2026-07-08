from __future__ import annotations

import textwrap

import pytest

from services.local_permits import (
    PermitSource,
    list_permit_sources,
    normalize_arcgis_feature,
    normalize_kml_placemark,
    preview_permit_sources,
)


@pytest.fixture(autouse=True)
def _suppress_background_services():
    yield


def test_list_permit_sources_expands_carolina_beach_layers():
    sources = list_permit_sources(enabled_only=True)
    ids = {source["id"] for source in sources}

    assert "cb-residential-fence-permits" in ids
    assert "cb-residential-swimming-pool-permits" in ids
    assert "wrightsville-beach-permit-map-kml" in ids


def test_normalize_arcgis_feature_scores_pool_lead():
    source = PermitSource(
        id="cb-residential-swimming-pool-permits",
        name="Residential Swimming Pool Permits",
        category="permits",
        access_method="arcgis_feature_server",
        url="https://cw.carolinabeach.org/Cityworks/gis/1/1045/rest/services/cw/FeatureServer/5",
        enabled=True,
        jurisdiction_id="nc-carolina-beach-wrightsville-beach",
        jurisdiction_name="Carolina Beach / Wrightsville Beach",
        field_map={
            "permit_number": "CASE_NUMBER",
            "permit_type": "CASE_TYPE_DESC",
            "description": "PROJECT_DESC",
            "address": "Location",
            "contractor": "BUSINESS_NAME",
            "accepted_at": "DATE_ACCEPTED",
        },
        lead_categories=["pool", "fence"],
        attribution="Town of Carolina Beach",
        terms_reviewed=False,
        commercial_use="review_required",
        notes=[],
    )

    record = normalize_arcgis_feature(
        source,
        {
            "attributes": {
                "CASE_NUMBER": "CB-123",
                "CASE_TYPE_DESC": "Residential Swimming Pool",
                "PROJECT_DESC": "Install new backyard swimming pool",
                "Location": "100 Test Ave",
                "BUSINESS_NAME": "Pool Co",
            },
            "geometry": {"x": -77.9, "y": 34.04},
        },
    )

    assert record["permit_number"] == "CB-123"
    assert record["lead_category"] == "pool"
    assert record["score"] >= 90
    assert record["lat"] == 34.04
    assert record["lng"] == -77.9


def test_normalize_arcgis_feature_converts_web_mercator_geometry():
    source = PermitSource(
        id="cb-residential-swimming-pool-permits",
        name="Residential Swimming Pool Permits",
        category="permits",
        access_method="arcgis_feature_server",
        url="https://cw.carolinabeach.org/Cityworks/gis/1/1045/rest/services/cw/FeatureServer/5",
        enabled=True,
        jurisdiction_id="nc-carolina-beach-wrightsville-beach",
        jurisdiction_name="Carolina Beach / Wrightsville Beach",
        field_map={"permit_number": "CASE_NUMBER", "address": "Location"},
        lead_categories=["pool", "fence"],
        attribution="Town of Carolina Beach",
        terms_reviewed=False,
        commercial_use="review_required",
        notes=[],
    )

    record = normalize_arcgis_feature(
        source,
        {
            "attributes": {"CASE_NUMBER": "RES26-278", "Location": "1306 MACKEREL LN"},
            "geometry": {"x": -8672060.79, "y": 4031632.9, "spatialReference": {"wkid": 102100}},
        },
    )

    assert record["lead_category"] == "pool"
    assert record["score"] >= 90
    assert round(record["lat"], 4) == 34.0211
    assert round(record["lng"], 4) == -77.9024


def test_normalize_kml_placemark_scores_waterfront_work():
    from defusedxml import ElementTree as ET

    source = PermitSource(
        id="wrightsville-beach-permit-map-kml",
        name="Wrightsville Beach Permit Map",
        category="permits",
        access_method="google_my_maps_kml",
        url="https://www.google.com/maps/d/kml?mid=abc&forcekml=1",
        enabled=True,
        jurisdiction_id="nc-carolina-beach-wrightsville-beach",
        jurisdiction_name="Carolina Beach / Wrightsville Beach",
        field_map={
            "permit_number": "Placemark.name",
            "address": "ExtendedData.Address",
            "permit_type": "ExtendedData.Permit_Type",
            "description": "ExtendedData.Project_Description",
        },
        lead_categories=[],
        attribution="Town of Wrightsville Beach",
        terms_reviewed=False,
        commercial_use="review_required",
        notes=[],
    )
    xml = """
    <Placemark xmlns="http://www.opengis.net/kml/2.2">
      <name>9320</name>
      <ExtendedData>
        <Data name="Address"><value>714 S. Lumina Ave.</value></Data>
        <Data name="Permit Type"><value>Piers, Docks, Bulkheads</value></Data>
        <Data name="Project Description "><value>Replace broken guide piling and install boatlift</value></Data>
      </ExtendedData>
      <Point><coordinates>-77.807271,34.193537,0</coordinates></Point>
    </Placemark>
    """

    record = normalize_kml_placemark(source, ET.fromstring(xml))

    assert record["permit_number"] == "9320"
    assert record["lead_category"] == "coastal_docks_bulkheads"
    assert record["address"] == "714 S. Lumina Ave."


def test_preview_permit_sources_uses_arcgis_query(monkeypatch, tmp_path):
    registry = tmp_path / "registry.yaml"
    registry.write_text(
        textwrap.dedent(
            """
            jurisdictions:
              - id: test-market
                name: Test Market
                sources:
                  - id: test-permits
                    name: Test Permits
                    category: permits
                    access_method: arcgis_feature_server
                    url: https://example.nhcgov.com/server/rest/services/Test/FeatureServer/0
                    enabled: true
                    field_map:
                      permit_number: CASE_NUMBER
                      permit_type: CASE_TYPE_DESC
                      description: PROJECT_DESC
            """
        ).strip(),
        encoding="utf-8",
    )

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "features": [
                    {
                        "attributes": {
                            "CASE_NUMBER": "P-1",
                            "CASE_TYPE_DESC": "Fence",
                            "PROJECT_DESC": "Install fence",
                        },
                        "geometry": {"x": -77.9, "y": 34.0},
                    }
                ]
            }

    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr("services.local_permits.requests.get", fake_get)

    result = preview_permit_sources(source_id="test-permits", path=registry)

    assert calls[0][0].endswith("/query")
    assert result["summary"]["returned"] == 1
    assert result["records"][0]["lead_category"] == "fence"
