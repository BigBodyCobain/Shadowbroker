from unittest.mock import patch


def test_geocode_search_proxy(client):
    with patch("main.search_geocode") as mock_search:
        mock_search.return_value = [{"label": "Denver, CO, USA", "lat": 39.7392, "lng": -104.9903}]
        r = client.get("/api/geocode/search?q=denver&limit=1")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] == 1
        assert data["results"][0]["label"] == "Denver, CO, USA"


def test_geocode_reverse_proxy(client):
    with patch("main.reverse_geocode") as mock_reverse:
        mock_reverse.return_value = {"label": "Boulder, CO, USA"}
        r = client.get("/api/geocode/reverse?lat=40.01499&lng=-105.27055")
        assert r.status_code == 200
        data = r.json()
        assert data["label"] == "Boulder, CO, USA"
