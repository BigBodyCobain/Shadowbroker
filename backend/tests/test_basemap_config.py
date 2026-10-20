"""GET /api/basemap-config serves the CARTO basemap key to the browser.

The key is public by nature (the browser sends it to CARTO on every tile
request), so the endpoint needs no admin auth. It must read the key at
request time so Docker operators can set it without a rebuild, and it must
honor the persisted operator key file like every other registry key.
"""

import pytest
from fastapi.testclient import TestClient

from services import api_settings


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api_settings, "OPERATOR_KEYS_ENV_PATH", tmp_path / "operator_api_keys.env")
    monkeypatch.delenv("CARTO_API_KEY", raising=False)
    import main

    return TestClient(main.app, raise_server_exceptions=False)


def test_unconfigured_when_env_unset(client):
    r = client.get("/api/basemap-config")
    assert r.status_code == 200
    assert r.json() == {"carto": {"configured": False, "key": ""}}


def test_returns_trimmed_key_without_admin_auth(client, monkeypatch):
    monkeypatch.setenv("CARTO_API_KEY", "  carto-test-key  ")
    r = client.get("/api/basemap-config")
    assert r.status_code == 200
    assert r.json() == {"carto": {"configured": True, "key": "carto-test-key"}}


def test_reads_persisted_operator_key_file(client, tmp_path):
    (tmp_path / "operator_api_keys.env").write_text("CARTO_API_KEY=persisted-key\n")
    r = client.get("/api/basemap-config")
    assert r.json()["carto"] == {"configured": True, "key": "persisted-key"}


def test_settings_model_exposes_carto_key(monkeypatch):
    # env_check reads keys off Settings, so the field must exist there or the
    # startup check would always report CARTO_API_KEY as unset.
    from services.config import Settings

    monkeypatch.setenv("CARTO_API_KEY", "from-env")
    assert Settings().CARTO_API_KEY == "from-env"


def test_carto_key_is_in_registry_and_saveable():
    assert "CARTO_API_KEY" in api_settings.ALLOWED_ENV_KEYS
    entry = next(a for a in api_settings.API_REGISTRY if a["env_key"] == "CARTO_API_KEY")
    assert entry["required"] is False
