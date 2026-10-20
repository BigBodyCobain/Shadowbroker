from types import SimpleNamespace

from services.mesh import mesh_infonet_relay_bootstrap as relay_bootstrap


def test_relay_auto_wormhole_skipped_by_default(monkeypatch):
    monkeypatch.setattr(
        relay_bootstrap,
        "get_settings",
        lambda: SimpleNamespace(
            MESH_INFONET_RELAY_AUTO_WORMHOLE=False,
            MESH_INFONET_RELAY_AUTO_WORMHOLE_DISABLED=False,
            MESH_BOOTSTRAP_SIGNER_PRIVATE_KEY="",
        ),
    )
    assert relay_bootstrap.infonet_relay_auto_wormhole_requested() is False


def test_relay_auto_wormhole_enabled_by_flag(monkeypatch):
    monkeypatch.setattr(
        relay_bootstrap,
        "get_settings",
        lambda: SimpleNamespace(
            MESH_INFONET_RELAY_AUTO_WORMHOLE=True,
            MESH_INFONET_RELAY_AUTO_WORMHOLE_DISABLED=False,
            MESH_BOOTSTRAP_SIGNER_PRIVATE_KEY="",
        ),
    )
    assert relay_bootstrap.infonet_relay_auto_wormhole_requested() is True


def test_relay_auto_wormhole_enabled_by_seed_signer_key(monkeypatch):
    monkeypatch.setattr(
        relay_bootstrap,
        "get_settings",
        lambda: SimpleNamespace(
            MESH_INFONET_RELAY_AUTO_WORMHOLE=False,
            MESH_INFONET_RELAY_AUTO_WORMHOLE_DISABLED=False,
            MESH_BOOTSTRAP_SIGNER_PRIVATE_KEY="seed-private-key",
        ),
    )
    assert relay_bootstrap.infonet_relay_auto_wormhole_requested() is True


def test_relay_auto_wormhole_disabled_override(monkeypatch):
    monkeypatch.setattr(
        relay_bootstrap,
        "get_settings",
        lambda: SimpleNamespace(
            MESH_INFONET_RELAY_AUTO_WORMHOLE=True,
            MESH_INFONET_RELAY_AUTO_WORMHOLE_DISABLED=True,
            MESH_BOOTSTRAP_SIGNER_PRIVATE_KEY="seed-private-key",
        ),
    )
    assert relay_bootstrap.infonet_relay_auto_wormhole_requested() is False


def test_ensure_relay_wormhole_writes_settings_and_connects(monkeypatch, tmp_path):
    wormhole_file = tmp_path / "wormhole.json"
    monkeypatch.setattr(relay_bootstrap, "WORMHOLE_FILE", wormhole_file, raising=False)
    monkeypatch.setattr(
        "services.wormhole_settings.WORMHOLE_FILE",
        wormhole_file,
    )
    monkeypatch.setattr(
        "services.wormhole_settings.DATA_DIR",
        tmp_path,
    )

    settings = SimpleNamespace(
        MESH_INFONET_RELAY_AUTO_WORMHOLE=True,
        MESH_INFONET_RELAY_AUTO_WORMHOLE_DISABLED=False,
        MESH_BOOTSTRAP_SIGNER_PRIVATE_KEY="",
        MESH_ARTI_SOCKS_PORT=9050,
    )
    monkeypatch.setattr(relay_bootstrap, "get_settings", lambda: settings)

    tor_calls: list[int] = []

    class _TorService:
        def start(self, *, target_port: int):
            tor_calls.append(target_port)
            return {"ok": True, "hostname": "example.onion"}

    env_writes: list[tuple[str, str]] = []

    def _fake_write_env_value(key: str, value: str) -> None:
        env_writes.append((key, value))

    wormhole_calls: list[str] = []

    def _fake_restart_wormhole(*, reason: str):
        wormhole_calls.append(f"restart:{reason}")
        return {"connected": True, "reason": reason}

    def _fake_connect_wormhole(*, reason: str):
        wormhole_calls.append(f"connect:{reason}")
        return {"connected": True, "reason": reason}

    monkeypatch.setattr(
        "services.tor_hidden_service.tor_service",
        _TorService(),
    )
    monkeypatch.setattr("routers.ai_intel._write_env_value", _fake_write_env_value)
    monkeypatch.setattr(
        "services.wormhole_supervisor.restart_wormhole",
        _fake_restart_wormhole,
    )
    monkeypatch.setattr(
        "services.wormhole_supervisor.connect_wormhole",
        _fake_connect_wormhole,
    )

    result = relay_bootstrap.ensure_infonet_relay_wormhole_ready(reason="test_relay")

    assert result["ok"] is True
    assert result["skipped"] is False
    assert result["settings_updated"] is True
    assert tor_calls == [8000]
    assert env_writes == [("MESH_ARTI_ENABLED", "true")]
    assert wormhole_calls == ["restart:test_relay"]
    saved = relay_bootstrap.read_wormhole_settings()
    assert saved["enabled"] is True
    assert saved["transport"] == "tor_arti"
    assert saved["socks_proxy"] == "socks5h://127.0.0.1:9050"
    assert saved["anonymous_mode"] is True
