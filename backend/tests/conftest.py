import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture(autouse=True)
def _suppress_background_services():
    """Prevent real scheduler/stream/tracker from starting during tests."""
    with (
        patch("services.data_fetcher.start_scheduler"),
        patch("services.data_fetcher.stop_scheduler"),
        patch("services.ais_stream.start_ais_stream"),
        patch("services.ais_stream.stop_ais_stream"),
        patch("services.carrier_tracker.start_carrier_tracker"),
        patch("services.carrier_tracker.stop_carrier_tracker"),
    ):
        yield


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

        def put(self, url, **kw):
            return self._loop.run_until_complete(self._put(url, **kw))

        async def _put(self, url, **kw):
            async with AsyncClient(transport=self._transport, base_url="http://test") as ac:
                return await ac.put(url, **kw)

    return SyncClient()
