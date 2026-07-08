import pytest

from services.business_intel import business_dashboard, build_business_graph, score_business_intel


@pytest.fixture(autouse=True)
def _suppress_background_services():
    yield


def test_business_intel_discards_raw_notes_and_stores_sanitized_signal():
    result = score_business_intel(
        text="Need emergency roof repair near West Chester today. Budget $1200. Call 610-555-0100 or lead@example.com.",
        market="home_services",
        objective="demand",
        source_label="nextdoor_export",
        persist=True,
        fuse_local=False,
    )

    first = result["action_queue"][0]
    assert first["category"] == "demand"
    assert "[phone]" in first["detail"]
    assert "[email]" in first["detail"]
    assert "610-555-0100" not in first["detail"]
    assert "lead@example.com" not in first["detail"]
    assert result["stored_signal_count"] >= 1
    assert result["graph"]["nodes"]
    assert result["graph"]["links"]


def test_business_dashboard_derives_live_events_and_graph_feeds():
    data = {
        "news": [
            {
                "id": "n1",
                "title": "Storm disrupts deliveries",
                "summary": "Several deliveries delayed near test market",
                "source": "TestWire",
                "risk_score": 0.7,
                "lat": 40.0,
                "lng": -75.0,
            }
        ],
        "gdelt": [
            {
                "geometry": {"coordinates": [-75.1, 40.1]},
                "properties": {
                    "name": "Local contractor demand",
                    "count": 15,
                    "_headlines_list": ["Contractors booked out across county"],
                },
            }
        ],
        "weather_alerts": [{"event": "Flood Warning", "lat": 40.05, "lng": -75.05}],
        "commercial_flights": [{"lat": 40.0, "lng": -75.0}],
        "sigint": [{"lat": 40.0, "lng": -75.0}],
    }

    result = business_dashboard(data=data, freshness={}, limit=20)

    assert result["live_event_count"] >= 3
    assert result["summary"]["total"] >= 3
    node_ids = {node["id"] for node in result["graph"]["nodes"]}
    assert "feed:commercial_flights" in node_ids
    assert "feed:sigint" in node_ids


def test_business_graph_connects_signal_category_and_source():
    graph = build_business_graph(
        [
            {
                "id": "s1",
                "label": "Demand signal",
                "category": "demand",
                "source": "authorized_notes",
                "score": 88,
                "grade": "strong",
            }
        ],
        data={},
    )

    node_ids = {node["id"] for node in graph["nodes"]}
    assert "signal:s1" in node_ids
    assert "category:demand" in node_ids
    assert "source:authorized_notes" in node_ids
    assert any(link["source"] == "signal:s1" and link["target"] == "category:demand" for link in graph["links"])
