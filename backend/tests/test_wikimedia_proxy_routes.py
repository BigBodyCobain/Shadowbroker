"""Backend Wikimedia proxy routes (#360)."""
from __future__ import annotations

from unittest.mock import patch

import pytest


def test_wikipedia_summary_route_returns_payload(client):
    sample = {
        "title": "Paris",
        "description": "capital",
        "extract": "Paris is the capital of France.",
        "thumbnail": "https://example.org/t.jpg",
        "type": "standard",
    }
    with patch(
        "services.region_dossier.fetch_wikipedia_page_summary",
        return_value=sample,
    ):
        r = client.get("/api/wikipedia/summary", params={"title": "Paris"})
    assert r.status_code == 200
    assert r.json()["title"] == "Paris"


def test_wikidata_sparql_route_returns_bindings(client):
    bindings = [{"x": {"value": "1"}}]
    with patch(
        "services.region_dossier.fetch_wikidata_sparql_bindings",
        return_value=bindings,
    ):
        r = client.post("/api/wikidata/sparql", json={"query": "SELECT ?x WHERE {}"})
    assert r.status_code == 200
    assert r.json()["bindings"] == bindings
