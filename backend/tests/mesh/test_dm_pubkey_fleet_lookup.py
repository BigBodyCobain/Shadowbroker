"""dm_get_pubkey resolves invite handles across the private fleet."""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.mark.asyncio
async def test_dm_get_pubkey_falls_back_to_fleet_prekey_lookup():
    import main

    request = main.Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/mesh/dm/pubkey",
            "headers": [],
            "client": ("127.0.0.1", 12345),
        }
    )

    remote_bundle = {
        "ok": True,
        "agent_id": "!sb_peer_test",
        "identity_dh_pub_key": "Uo/wk78hu+ISyT9iCjNhcWgiANaHSXLMyNLn2q8YCkc=",
        "dh_algo": "X25519",
        "public_key": "v0pVNDQAz8wzvpMfIURjjVyCHhKZlAmrDPGaqzoJ7Rk=",
        "public_key_algo": "Ed25519",
        "signature": "sig",
        "sequence": 1,
        "bundle": {"identity_dh_pub_key": "Uo/wk78hu+ISyT9iCjNhcWgiANaHSXLMyNLn2q8YCkc="},
    }

    with patch("services.mesh.mesh_dm_relay.dm_relay") as relay, patch(
        "services.mesh.mesh_wormhole_prekey.fetch_dm_prekey_bundle",
        return_value=remote_bundle,
    ):
        relay.get_dh_key_by_lookup.return_value = (None, "")
        result = await main.dm_get_pubkey(request, lookup_token="fleet-handle-token")

    assert result["ok"] is True
    assert result["agent_id"] == "!sb_peer_test"
    assert result["dh_pub_key"] == "Uo/wk78hu+ISyT9iCjNhcWgiANaHSXLMyNLn2q8YCkc="
