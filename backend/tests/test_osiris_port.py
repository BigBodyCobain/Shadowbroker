"""Tests for Osiris-ported security and sanctions modules."""
from __future__ import annotations

import pytest

from services.ssrf_guard import validate_host, validate_domain
from services.sanctions.ofac import norm_name, search_sanctions


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


@pytest.mark.parametrize("query", ["127.0.0.1", "10.0.0.1"])
def test_sweep_init_rejects_private(query: str):
    from services.osint.lookups import sweep_init

    with pytest.raises(ValueError, match="Private|reserved|Invalid"):
        sweep_init(query, 24)
