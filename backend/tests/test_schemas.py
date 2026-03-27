"""Tests for Pydantic response schemas."""

import pytest
from pydantic import ValidationError
from services.schemas import HealthResponse, RefreshResponse, AisFeedResponse, RouteResponse


class TestHealthResponse:
    def test_valid_health_response(self):
        data = {
            "status": "ok",
            "last_updated": "2024-01-01T00:00:00",
            "sources": {"flights": 150, "ships": 42},
            "freshness": {"flights": "2024-01-01T00:00:00", "ships": "2024-01-01T00:00:00"},
            "uptime_seconds": 3600,
        }
        resp = HealthResponse(**data)
        assert resp.status == "ok"
        assert resp.sources["flights"] == 150
        assert resp.uptime_seconds == 3600

    def test_health_response_optional_last_updated(self):
        data = {"status": "ok", "sources": {}, "freshness": {}, "uptime_seconds": 0}
        resp = HealthResponse(**data)
        assert resp.last_updated is None

    def test_health_response_missing_required_field(self):
        with pytest.raises(ValidationError):
            HealthResponse(status="ok")  # Missing sources, freshness, uptime_seconds


class TestRefreshResponse:
    def test_valid_refresh(self):
        resp = RefreshResponse(status="refreshing")
        assert resp.status == "refreshing"

    def test_missing_status(self):
        with pytest.raises(ValidationError):
            RefreshResponse()


class TestAisFeedResponse:
    def test_valid_ais_feed(self):
        resp = AisFeedResponse(status="ok", ingested=42)
        assert resp.ingested == 42

    def test_default_ingested_zero(self):
        resp = AisFeedResponse(status="ok")
        assert resp.ingested == 0


class TestRouteResponse:
    def test_valid_route(self):
        resp = RouteResponse(
            orig_loc=[40.6413, -73.7781],
            dest_loc=[51.4700, -0.4543],
            origin_name="JFK",
            dest_name="LHR",
        )
        assert resp.origin_name == "JFK"
        assert len(resp.orig_loc) == 2

    def test_all_optional(self):
        resp = RouteResponse()
        assert resp.orig_loc is None
        assert resp.dest_loc is None
        assert resp.origin_name is None
        assert resp.dest_name is None
