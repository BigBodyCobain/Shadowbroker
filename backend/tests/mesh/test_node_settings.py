def test_node_settings_roundtrip(tmp_path, monkeypatch):
    from services import node_settings

    settings_path = tmp_path / "node.json"
    monkeypatch.setattr(node_settings, "NODE_FILE", settings_path)
    monkeypatch.setattr(node_settings, "_cache", None)
    monkeypatch.setattr(node_settings, "_cache_ts", 0.0)

    initial = node_settings.read_node_settings()
    updated = node_settings.write_node_settings(enabled=True)
    reread = node_settings.read_node_settings()

    assert initial["enabled"] is False
    assert updated["enabled"] is True
    assert reread["enabled"] is True
