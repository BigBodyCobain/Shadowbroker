import hashlib
import hmac as hmac_mod
import json
import os
import secrets
import time

import pytest
from starlette.requests import Request


def test_persisted_openclaw_secret_loads_when_docker_env_blank(tmp_path, monkeypatch):
    from services import api_settings
    from services.config import get_settings

    openclaw_env = tmp_path / "openclaw.env"
    openclaw_env.write_text('OPENCLAW_HMAC_SECRET="persisted-hmac-secret"\n', encoding="utf-8")
    monkeypatch.setattr(api_settings, "OPENCLAW_ENV_PATH", openclaw_env)
    monkeypatch.setenv("OPENCLAW_HMAC_SECRET", "")
    get_settings.cache_clear()

    api_settings.load_persisted_openclaw_into_environ()

    assert os.environ["OPENCLAW_HMAC_SECRET"] == "persisted-hmac-secret"
    assert get_settings().OPENCLAW_HMAC_SECRET == "persisted-hmac-secret"


def test_persist_openclaw_env_value_writes_data_volume(tmp_path, monkeypatch):
    from services import api_settings

    openclaw_env = tmp_path / "openclaw.env"
    monkeypatch.setattr(api_settings, "OPENCLAW_ENV_PATH", openclaw_env)

    api_settings.persist_openclaw_env_value("OPENCLAW_HMAC_SECRET", "minted-secret")

    assert 'OPENCLAW_HMAC_SECRET="minted-secret"' in openclaw_env.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_hmac_verify_accepts_canonical_json_from_docker_host(monkeypatch):
    import auth

    secret = "docker-hmac-test-secret"
    monkeypatch.setattr(auth, "_openclaw_hmac_secret", lambda: secret)

    body = json.dumps({"args": {}, "cmd": "channel_status"}, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )
    ts = str(int(time.time()))
    nonce = secrets.token_hex(16)
    digest = hashlib.sha256(body).hexdigest()
    message = f"POST|/api/ai/channel/command|{ts}|{nonce}|{digest}"
    signature = hmac_mod.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()

    async def receive():
        return {"type": "http.request", "body": body}

    req = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/ai/channel/command",
            "headers": [
                (b"x-sb-timestamp", ts.encode()),
                (b"x-sb-nonce", nonce.encode()),
                (b"x-sb-signature", signature.encode()),
            ],
            "query_string": b"",
            "root_path": "",
            "server": ("172.17.0.1", 80),
            "client": ("172.17.0.1", 12345),
        },
        receive,
    )

    assert await auth._verify_openclaw_hmac(req) is True
