import os
from types import SimpleNamespace
from unittest.mock import patch


def test_wormhole_subprocess_env_whitelists_runtime_and_mesh_vars():
    from services import wormhole_supervisor

    settings = {
        "transport": "tor",
        "socks_proxy": "127.0.0.1:9050",
        "socks_dns": True,
    }
    config_snapshot = SimpleNamespace(MESH_RNS_ENABLED=False)

    with patch.dict(
        os.environ,
        {
            "PATH": "C:\\Python;C:\\Windows\\System32",
            "SYSTEMROOT": "C:\\Windows",
            "PYTHONPATH": "F:\\Codebase\\Oracle\\live-risk-dashboard\\backend",
            "ADMIN_KEY": "admin-secret",
            "MESH_PEER_PUSH_SECRET": "peer-secret-value",
            "UNRELATED_SECRET": "should-not-leak",
        },
        clear=True,
    ):
        env = wormhole_supervisor._wormhole_subprocess_env(
            settings,
            settings_obj=config_snapshot,
        )

    assert env["PATH"] == "C:\\Python;C:\\Windows\\System32"
    assert env["SYSTEMROOT"] == "C:\\Windows"
    assert env["PYTHONPATH"] == "F:\\Codebase\\Oracle\\live-risk-dashboard\\backend"
    assert env["ADMIN_KEY"] == "admin-secret"
    assert env["MESH_PEER_PUSH_SECRET"] == "peer-secret-value"
    assert env["MESH_ONLY"] == "true"
    assert env["MESH_RNS_ENABLED"] == "false"
    assert env["WORMHOLE_TRANSPORT"] == "tor"
    assert env["WORMHOLE_SOCKS_PROXY"] == "127.0.0.1:9050"
    assert env["WORMHOLE_SOCKS_DNS"] == "true"
    assert "UNRELATED_SECRET" not in env
