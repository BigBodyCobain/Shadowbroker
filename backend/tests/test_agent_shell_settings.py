def test_agent_shell_settings_roundtrip(tmp_path, monkeypatch):
    from services import agent_shell_settings

    settings_path = tmp_path / "agent_shell_settings.json"
    workdir = tmp_path / "workspace"
    workdir.mkdir()

    monkeypatch.setattr(agent_shell_settings, "_SETTINGS_FILE", settings_path)

    assert agent_shell_settings.get_agent_shell_settings()["working_directory"]

    saved = agent_shell_settings.set_agent_shell_working_directory(str(workdir))
    assert saved["working_directory"] == str(workdir.resolve())
    assert agent_shell_settings.get_agent_shell_settings()["working_directory"] == str(workdir.resolve())
