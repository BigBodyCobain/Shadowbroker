from types import SimpleNamespace


def test_fetch_fishing_activity_paginates(monkeypatch):
    from services.fetchers import geo
    from services.fetchers._store import latest_data

    original = list(latest_data.get("fishing_activity") or [])
    requests: list[str] = []

    def fake_fetch(url, timeout=30, headers=None):
        requests.append(url)
        if "offset=0" in url:
            payload = {
                "entries": [
                    {
                        "id": "evt-1",
                        "position": {"lat": 10.0, "lon": 20.0},
                        "event": {"duration": 3600},
                        "vessel": {"id": "v-1", "ssvid": "ssvid-1", "name": "Alpha", "flag": "PA"},
                    },
                    {
                        "id": "evt-2",
                        "position": {"lat": 11.0, "lon": 21.0},
                        "event": {"duration": 7200},
                        "vessel": {"id": "v-2", "ssvid": "ssvid-2", "name": "Bravo", "flag": "US"},
                    },
                ],
                "nextOffset": 2,
            }
        elif "offset=2" in url:
            payload = {
                "entries": [
                    {
                        "id": "evt-3",
                        "position": {"lat": 12.0, "lon": 22.0},
                        "event": {"duration": 1800},
                        "vessel": {"id": "v-3", "ssvid": "ssvid-3", "name": "Charlie", "flag": "GB"},
                    }
                ]
            }
        else:
            payload = {"entries": []}
        return SimpleNamespace(status_code=200, json=lambda: payload)

    monkeypatch.setenv("GFW_API_TOKEN", "test-token")
    monkeypatch.setenv("GFW_EVENTS_PAGE_SIZE", "2")
    monkeypatch.setattr("services.fetchers._store.is_any_active", lambda *args: True)
    monkeypatch.setattr(geo, "fetch_with_curl", fake_fetch)
    monkeypatch.setattr(geo, "_mark_fresh", lambda *args, **kwargs: None)

    try:
        geo.fetch_fishing_activity()
        assert len(latest_data["fishing_activity"]) == 3
        assert latest_data["fishing_activity"][2]["id"] == "evt-3"
        assert any("offset=0" in url for url in requests)
        assert any("offset=2" in url for url in requests)
    finally:
        latest_data["fishing_activity"] = original


def test_fetch_fishing_activity_dedupes_to_latest_event_per_vessel(monkeypatch):
    from services.fetchers import geo
    from services.fetchers._store import latest_data

    original = list(latest_data.get("fishing_activity") or [])

    def fake_fetch(url, timeout=30, headers=None):
        payload = {
            "entries": [
                {
                    "id": "evt-old",
                    "type": "fishing",
                    "start": "2026-04-01T00:00:00.000Z",
                    "end": "2026-04-02T00:00:00.000Z",
                    "position": {"lat": 10.0, "lon": 20.0},
                    "event": {"duration": 3600},
                    "vessel": {"id": "v-1", "ssvid": "ssvid-1", "name": "Alpha", "flag": "PA"},
                },
                {
                    "id": "evt-new",
                    "type": "fishing",
                    "start": "2026-04-03T00:00:00.000Z",
                    "end": "2026-04-04T00:00:00.000Z",
                    "position": {"lat": 11.0, "lon": 21.0},
                    "event": {"duration": 7200},
                    "vessel": {"id": "v-1", "ssvid": "ssvid-1", "name": "Alpha", "flag": "PA"},
                },
                {
                    "id": "evt-other",
                    "type": "fishing",
                    "start": "2026-04-03T00:00:00.000Z",
                    "end": "2026-04-03T12:00:00.000Z",
                    "position": {"lat": 12.0, "lon": 22.0},
                    "event": {"duration": 1800},
                    "vessel": {"id": "v-2", "ssvid": "ssvid-2", "name": "Bravo", "flag": "US"},
                },
            ]
        }
        return SimpleNamespace(status_code=200, json=lambda: payload)

    monkeypatch.setenv("GFW_API_TOKEN", "test-token")
    monkeypatch.setenv("GFW_EVENTS_PAGE_SIZE", "500")
    monkeypatch.setattr("services.fetchers._store.is_any_active", lambda *args: True)
    monkeypatch.setattr(geo, "fetch_with_curl", fake_fetch)
    monkeypatch.setattr(geo, "_mark_fresh", lambda *args, **kwargs: None)

    try:
        geo.fetch_fishing_activity()
        assert len(latest_data["fishing_activity"]) == 2
        assert latest_data["fishing_activity"][0]["id"] == "evt-new"
        assert latest_data["fishing_activity"][0]["event_count"] == 2
        assert latest_data["fishing_activity"][0]["vessel_ssvid"] == "ssvid-1"
    finally:
        latest_data["fishing_activity"] = original
