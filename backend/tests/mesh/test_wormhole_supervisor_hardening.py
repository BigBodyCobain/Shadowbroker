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
            "PRIVACY_CORE_LIB": "C:\\privacy-core\\privacy_core.dll",
            "PRIVACY_CORE_MIN_VERSION": "0.1.0",
            "PRIVACY_CORE_ALLOWED_SHA256": "ab" * 32,
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
    assert env["PRIVACY_CORE_LIB"] == "C:\\privacy-core\\privacy_core.dll"
    assert env["PRIVACY_CORE_MIN_VERSION"] == "0.1.0"
    assert env["PRIVACY_CORE_ALLOWED_SHA256"] == "ab" * 32
    assert env["MESH_ONLY"] == "true"
    assert env["MESH_RNS_ENABLED"] == "false"
    assert env["WORMHOLE_TRANSPORT"] == "tor"
    assert env["WORMHOLE_SOCKS_PROXY"] == "127.0.0.1:9050"
    assert env["WORMHOLE_SOCKS_DNS"] == "true"
    assert "UNRELATED_SECRET" not in env


def test_pid_alive_treats_windows_systemerror_as_stale_pid(monkeypatch):
    from services import wormhole_supervisor

    def _raise(_pid, _sig):
        raise SystemError("WinError 87")

    monkeypatch.setattr(wormhole_supervisor.os, "kill", _raise)

    assert wormhole_supervisor._pid_alive(22256) is False
