from unittest.mock import patch


def test_geocode_search_proxy(client):
    with patch("services.geocode.search_geocode") as mock_search:
        mock_search.return_value = [{"label": "Denver, CO, USA", "lat": 39.7392, "lng": -104.9903}]
        r = client.get("/api/geocode/search?q=denver&limit=1")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] == 1
        assert data["results"][0]["label"] == "Denver, CO, USA"


def test_geocode_reverse_proxy(client):
    with patch("services.geocode.reverse_geocode") as mock_reverse:
        mock_reverse.return_value = {"label": "Boulder, CO, USA"}
        r = client.get("/api/geocode/reverse?lat=40.01499&lng=-105.27055")
        assert r.status_code == 200
        data = r.json()
        assert data["label"] == "Boulder, CO, USA"


def test_geocode_search_passes_through_extent_fields(client):
    with patch("services.geocode.search_geocode") as mock_search:
        mock_search.return_value = [
            {
                "label": "Monaco",
                "lat": 43.7311,
                "lng": 7.4197,
                "bbox": ["43.5165358", "43.7519173", "7.4090279", "7.5329917"],
                "place_rank": 4,
                "addresstype": "country",
            }
        ]
        r = client.get("/api/geocode/search?q=monaco&limit=1")
        assert r.status_code == 200
        result = r.json()["results"][0]
        assert result["bbox"] == [
            "43.5165358",
            "43.7519173",
            "7.4090279",
            "7.5329917",
        ]
        assert result["place_rank"] == 4


def test_geocode_search_tolerates_missing_extent_fields(client):
    """local_only results and older cache entries carry no extent data."""
    with patch("services.geocode.search_geocode") as mock_search:
        mock_search.return_value = [{"label": "Denver", "lat": 39.7392, "lng": -104.9903}]
        r = client.get("/api/geocode/search?q=denver&limit=1")
        assert r.status_code == 200
        assert "bbox" not in r.json()["results"][0]
