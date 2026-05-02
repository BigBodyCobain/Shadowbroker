import asyncio

import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture(autouse=True)
def _suppress_background_services():
    """Prevent real scheduler/stream/tracker from starting during tests."""
    from services.mesh.mesh_private_transport_manager import reset_private_transport_manager_for_tests

    reset_private_transport_manager_for_tests()
    with (
        patch("services.data_fetcher.start_scheduler"),
        patch("services.data_fetcher.stop_scheduler"),
        patch("services.ais_stream.start_ais_stream"),
        patch("services.ais_stream.stop_ais_stream"),
        patch("services.carrier_tracker.start_carrier_tracker"),
        patch("services.carrier_tracker.stop_carrier_tracker"),
        patch("services.mesh.mesh_private_transport_manager.private_transport_manager._kickoff_background_bootstrap", return_value=False),
    ):
        yield
    reset_private_transport_manager_for_tests()


@pytest.fixture()
def client(_suppress_background_services):
    """HTTPX test client against the FastAPI app (no real network)."""
    from httpx import ASGITransport, AsyncClient
    from main import app
    import asyncio

    transport = ASGITransport(app=app)

    async def _make_client():
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            return ac

    # Return a sync-usable wrapper
    class SyncClient:
        def __init__(self):
            self._loop = asyncio.new_event_loop()
            self._transport = ASGITransport(app=app)

        def get(self, url, **kw):
            return self._loop.run_until_complete(self._get(url, **kw))

        async def _get(self, url, **kw):
            async with AsyncClient(transport=self._transport, base_url="http://test") as ac:
                return await ac.get(url, **kw)

        def post(self, url, **kw):
            return self._loop.run_until_complete(self._post(url, **kw))

        async def _post(self, url, **kw):
            async with AsyncClient(transport=self._transport, base_url="http://test") as ac:
                return await ac.post(url, **kw)

        def put(self, url, **kw):
            return self._loop.run_until_complete(self._put(url, **kw))

        async def _put(self, url, **kw):
            async with AsyncClient(transport=self._transport, base_url="http://test") as ac:
                return await ac.put(url, **kw)

        def delete(self, url, **kw):
            return self._loop.run_until_complete(self._delete(url, **kw))

        async def _delete(self, url, **kw):
            async with AsyncClient(transport=self._transport, base_url="http://test") as ac:
                return await ac.delete(url, **kw)

    return SyncClient()


@pytest.fixture()
def remote_client(_suppress_background_services):
    """HTTPX test client that simulates a remote (non-loopback) IP address.

    Unlike the default ``client`` fixture (127.0.0.1 — bypasses auth via
    loopback), this client originates from 1.2.3.4 and must present valid
    authentication to access protected routes.
    """
    from httpx import ASGITransport, AsyncClient
    from main import app

    class RemoteSyncClient:
        def __init__(self):
            self._loop = asyncio.new_event_loop()
            self._transport = ASGITransport(app=app, client=("1.2.3.4", 12345))
            self._base = "http://1.2.3.4:8000"

        def get(self, url, **kw):
            return self._loop.run_until_complete(self._req("GET", url, **kw))

        def post(self, url, **kw):
            return self._loop.run_until_complete(self._req("POST", url, **kw))

        def put(self, url, **kw):
            return self._loop.run_until_complete(self._req("PUT", url, **kw))

        def delete(self, url, **kw):
            return self._loop.run_until_complete(self._req("DELETE", url, **kw))

        async def _req(self, method, url, **kw):
            async with AsyncClient(transport=self._transport, base_url=self._base) as ac:
                return await ac.request(method, url, **kw)

    return RemoteSyncClient()
