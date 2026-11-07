"""Smoke test for the ``websockets`` dependency (voice-agent plan U0 / R1).

The voice broker (U2, services/voice_broker.py) is the sole importer of
``websockets`` and uses only the narrow asyncio surface: ``connect`` as an
async iterator-style client, ``send``, and ``close``. This test exercises
exactly that surface against a local ephemeral server — one live local
handshake, no external network.
"""

import asyncio

import websockets
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve


def test_websockets_narrow_surface_connect_send_close():
    async def scenario():
        async def handler(ws):
            message = await ws.recv()
            await ws.send("echo:" + message)
            await ws.close()

        async with serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            async with connect(f"ws://127.0.0.1:{port}") as client:
                await client.send("ping")
                reply = await asyncio.wait_for(client.recv(), timeout=5)
                assert reply == "echo:ping"
            assert client.close_code == 1000

    asyncio.run(scenario())


def test_websockets_version_is_pinned_compatible():
    pinned_major = "16"
    installed = str(websockets.__version__)
    assert installed.split(".")[0] == pinned_major, (
        "websockets major drifted from the pyproject pin — re-verify the "
        "voice broker's asyncio surface before bumping"
    )
