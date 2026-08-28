"""Tests for Osiris-ported security and sanctions modules."""
from __future__ import annotations

import pytest

from services.sanctions import ofac
from services.sanctions.ofac import norm_name, search_sanctions
from services.ssrf_guard import validate_domain, validate_host

SDN_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<sdnList xmlns="https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/XML">
  <publshInformation><Publish_Date>08/26/2026</Publish_Date><Record_Count>1</Record_Count></publshInformation>
  <sdnEntry>
    <uid>36</uid><firstName>Example</firstName><lastName>Entity</lastName><sdnType>Entity</sdnType>
    <programList><program>TEST</program></programList>
    <akaList><aka><firstName>Alias</firstName><lastName>Name</lastName></aka></akaList>
    <addressList><address><country>Kazakhstan</country></address></addressList>
    <idList><id><idType>Passport</idType><idNumber>SECRET-123</idNumber></id></idList>
    <remarks>provider-only remarks</remarks>
  </sdnEntry>
</sdnList>"""


def test_ssrf_blocks_localhost():
    result = validate_host("localhost")
    assert result["ok"] is False


def test_ssrf_blocks_private_ip():
    result = validate_host("192.168.1.1")
    assert result["ok"] is False


def test_ssrf_blocks_metadata_endpoint():
    result = validate_host("metadata.google.internal")
    assert result["ok"] is False


def test_validate_domain_rejects_garbage():
    assert validate_domain("not a domain") is False
    assert validate_domain("example.com") is True


def test_norm_name_strips_punctuation():
    assert norm_name("ACME, Inc.") == norm_name("acme inc")


def test_search_sanctions_requires_min_length():
    assert search_sanctions("ab") == []


def test_official_ofac_xml_is_minimized_for_search_index():
    entries = ofac._parse_sdn_xml(SDN_XML)

    assert [entry.to_dict() for entry in entries] == [
        {
            "id": "36",
            "schema": "LegalEntity",
            "name": "Example Entity",
            "aliases": ["Alias Name"],
            "countries": ["Kazakhstan"],
            "programs": ["TEST"],
            "sanctions": "TEST",
            "first_seen": "2026-08-26T00:00:00+00:00",
            "last_seen": "2026-08-26T00:00:00+00:00",
        }
    ]
    assert "SECRET-123" not in str(entries[0].to_dict())
    assert "remarks" not in str(entries[0].to_dict())


def test_qazpipe_mode_does_not_call_local_ofac_collector(monkeypatch):
    monkeypatch.setenv(
        "SHADOW_LAYER_SOURCE_MODES",
        '{"risk_reference_public":"qazpipe"}',
    )
    monkeypatch.setattr(
        ofac,
        "_load_primary_list",
        lambda: pytest.fail("local OFAC collector must remain off after cutover"),
    )
    monkeypatch.setattr(
        "services.qazlake_shadow_feed._items_by_family",
        lambda: {
            "risk_reference_public": {
                "sanctions": [
                    {
                        "id": "36",
                        "name": "Example Entity",
                        "schema": "LegalEntity",
                        "programs": ["TEST"],
                    }
                ]
            }
        },
    )

    assert ofac._load_list()["entries"][0].id == "36"


@pytest.mark.parametrize("query", ["127.0.0.1", "10.0.0.1"])
def test_sweep_init_rejects_private(query: str):
    from services.osint.lookups import sweep_init

    with pytest.raises(ValueError, match="Private|reserved|Invalid"):
        sweep_init(query, 24)
