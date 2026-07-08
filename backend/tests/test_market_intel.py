import pytest

from services.market_intel import build_market_intel


@pytest.fixture(autouse=True)
def _suppress_background_services():
    yield


def test_market_intel_redacts_operator_input_and_scores_demand():
    result = build_market_intel(
        text=(
            "Need same-day HVAC repair near Ridgewood. Quote was $850 and two shops are booked today. "
            "Contact 215-555-1212 or operator@example.com @locallead"
        ),
        market="home_services",
        objective="demand",
        source_label="authorized_notes",
        fuse_local=False,
    )

    first = result["action_queue"][0]
    assert first["category"] == "demand"
    assert first["grade"] in {"watch", "strong", "alpha"}
    assert "[phone]" in first["detail"]
    assert "[email]" in first["detail"]
    assert "[handle]" in first["detail"]
    assert result["privacy"]["redacted"] == 3
    assert result["summary"]["opportunities"] == 1


def test_market_intel_fuses_local_hazards_as_operational_risk():
    data = {
        "weather_alerts": [
            {
                "event": "Flood Warning",
                "severity": "Severe",
                "headline": "Flood Warning for test county",
                "lat": 40.02,
                "lng": -75.01,
            }
        ],
        "power_plants": [
            {
                "name": "North Substation",
                "operator": "Utility",
                "lat": 40.03,
                "lng": -75.03,
            }
        ],
    }

    result = build_market_intel(
        text="",
        market="logistics",
        objective="operations",
        lat=40.0,
        lng=-75.0,
        radius_km=25,
        fuse_local=True,
        data=data,
        freshness={},
    )

    assert result["query"]["fused_local"] is True
    assert result["summary"]["risks"] >= 1
    assert any(item["source"] == "shadowbroker:weather_alerts" for item in result["action_queue"])
