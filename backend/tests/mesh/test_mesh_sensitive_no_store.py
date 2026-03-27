import asyncio


class TestSensitiveBackendNoStore:
    def test_mesh_status_sets_privacy_security_headers(self, client):
        r = client.get("/api/mesh/infonet/status")
        assert r.status_code == 200
        assert "default-src 'self'" in (r.headers.get("content-security-policy") or "")
        assert (r.headers.get("x-frame-options") or "").upper() == "DENY"
        assert (r.headers.get("x-content-type-options") or "").lower() == "nosniff"
        assert (r.headers.get("referrer-policy") or "").lower() == "no-referrer"

    def test_wormhole_status_is_no_store(self, client):
        r = client.get("/api/wormhole/status")
        assert r.status_code == 200
        assert "no-store" in (r.headers.get("cache-control") or "").lower()

    def test_settings_privacy_profile_is_no_store(self, client):
        r = client.get("/api/settings/privacy-profile")
        assert r.status_code == 200
        assert "no-store" in (r.headers.get("cache-control") or "").lower()

    def test_settings_wormhole_is_no_store(self, client):
        r = client.get("/api/settings/wormhole")
        assert r.status_code == 200
        assert "no-store" in (r.headers.get("cache-control") or "").lower()

    def test_settings_wormhole_status_is_no_store(self, client):
        r = client.get("/api/settings/wormhole-status")
        assert r.status_code == 200
        assert "no-store" in (r.headers.get("cache-control") or "").lower()

    def test_dm_pubkey_is_no_store_even_on_failure(self, client):
        r = client.get("/api/mesh/dm/pubkey?agent_id=missing")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is False
        assert "no-store" in (r.headers.get("cache-control") or "").lower()

    def test_anonymous_mode_blocked_dm_send_is_no_store(self, client, monkeypatch):
        import main
        from services import wormhole_settings, wormhole_status

        monkeypatch.setattr(
            wormhole_settings,
            "read_wormhole_settings",
            lambda: {
                "enabled": True,
                "privacy_profile": "default",
                "transport": "direct",
                "anonymous_mode": True,
            },
        )
        monkeypatch.setattr(
            wormhole_status,
            "read_wormhole_status",
            lambda: {
                "running": True,
                "ready": True,
                "transport_active": "direct",
            },
        )

        async def _post():
            from httpx import ASGITransport, AsyncClient

            transport = ASGITransport(app=main.app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                return await ac.post("/api/mesh/dm/send", json={})

        response = asyncio.run(_post())
        assert response.status_code == 428
        assert "no-store" in (response.headers.get("cache-control") or "").lower()
