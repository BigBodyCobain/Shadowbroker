import json
from services.fetchers import geo


def test_find_nearest_airport_from_fixture():
    from pathlib import Path

    fixture = Path(__file__).resolve().parent / "fixtures" / "airports.json"
    with open(fixture, "r", encoding="utf-8") as f:
        airports = json.load(f)

    geo.cached_airports = airports

    # Near Denver
    result = geo.find_nearest_airport(39.74, -104.99, max_distance_nm=200)
    assert result is not None
    assert result["iata"] == "DEN"

    # Far away (middle of the ocean)
    result_far = geo.find_nearest_airport(0.0, -140.0, max_distance_nm=50)
    assert result_far is None
