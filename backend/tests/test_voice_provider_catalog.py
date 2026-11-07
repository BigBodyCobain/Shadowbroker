import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from services.voice_providers import (
    PROVIDERS,
    connection_for,
    discover_models,
    normalize_base,
)


def mock_http(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )


@pytest.mark.parametrize("provider", list(PROVIDERS))
def test_model_discovery_uses_only_its_provider_key(monkeypatch, provider):
    settings = SimpleNamespace(VOICE_API_PROVIDER=provider, VOICE_API_STYLE="")
    env = {row["key"]: "synthetic-" + row["key"] for row in PROVIDERS.values()}
    env["VOICE_COMPAT_BASE_URL"] = "http://127.0.0.1:11434/v1"
    connection = connection_for(provider, settings, env)
    seen = []

    def handler(request):
        seen.append(request)
        if provider == "gemini":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": "models/gemini-current",
                            "supportedGenerationMethods": ["generateContent"],
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "meta-llama/current"
                        if provider == "meta"
                        else "current-model"
                    }
                ]
            },
        )

    mock_http(monkeypatch, handler)
    result = asyncio.run(discover_models(provider, connection))
    assert result["ok"] is True and result["live"] is True and result["models"]
    request = seen[0]
    assert connection["key"] not in str(request.url)
    assert (
        request.headers.get("x-api-key") == connection["key"]
        if provider == "anthropic"
        else True
    )
    assert (
        request.headers.get("x-goog-api-key") == connection["key"]
        if provider == "gemini"
        else True
    )
    if provider not in {"gemini", "anthropic"}:
        assert (
            request.headers["Authorization"]
            == "Bearer " + env[PROVIDERS[provider]["key"]]
        )


def test_gemini_pagination_and_modality_filter(monkeypatch):
    def handler(request):
        if request.url.params.get("pageToken"):
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": "models/live-current",
                            "supportedGenerationMethods": ["bidiGenerateContent"],
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "models": [
                    {
                        "name": "models/text-current",
                        "supportedGenerationMethods": ["generateContent"],
                    }
                ],
                "nextPageToken": "page-2",
            },
        )

    mock_http(monkeypatch, handler)
    connection = {"base": PROVIDERS["gemini"]["base"], "key": "synthetic-google"}
    text = asyncio.run(discover_models("gemini", connection))
    audio = asyncio.run(discover_models("gemini", connection, mode="realtime"))
    assert [row["id"] for row in text["models"]] == ["text-current"]
    assert [row["id"] for row in audio["models"]] == ["live-current"]


def test_catalog_sorts_newest_and_preserves_hosted_llama(monkeypatch):
    rows = [
        {"id": "other/vendor", "created": 999},
        {"id": "meta-llama/older", "created": 1},
        {"id": "meta-llama/newer", "created": 2},
    ]
    mock_http(monkeypatch, lambda request: httpx.Response(200, json={"data": rows}))
    result = asyncio.run(
        discover_models(
            "meta", {"base": PROVIDERS["meta"]["base"], "key": "synthetic-router"}
        )
    )
    assert [row["id"] for row in result["models"]] == [
        "meta-llama/newer",
        "meta-llama/older",
    ]


def test_ollama_can_discover_native_installed_tags_without_auth(monkeypatch):
    def handler(request):
        return (
            httpx.Response(200, json={"models": [{"name": "llama-local:latest"}]})
            if request.url.path == "/api/tags"
            else httpx.Response(404)
        )

    mock_http(monkeypatch, handler)
    result = asyncio.run(
        discover_models(
            "ollama", {"base": normalize_base("http://localhost:11434"), "key": ""}
        )
    )
    assert [row["id"] for row in result["models"]] == ["llama-local:latest"]


def test_discovery_does_not_follow_redirects_with_credentials(monkeypatch):
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(
            302, headers={"location": "https://attacker.example/models"}
        )

    mock_http(monkeypatch, handler)
    result = asyncio.run(
        discover_models(
            "openrouter",
            {"base": PROVIDERS["openrouter"]["base"], "key": "synthetic-secret"},
        )
    )
    assert result["ok"] is False
    assert seen == ["https://openrouter.ai/api/v1/models"]


@pytest.mark.parametrize(
    "provider,style",
    [
        ("openai", "responses"),
        ("xai", "responses"),
        ("gemini", "chat"),
        ("anthropic", "messages"),
        ("openrouter", "chat"),
        ("ollama", "chat"),
        ("compat", "responses"),
    ],
)
def test_chat_transport_contract_and_picker_feedback(monkeypatch, provider, style):
    import services.voice_broker as broker

    settings = SimpleNamespace(VOICE_API_PROVIDER=provider, VOICE_API_STYLE=style)
    env = {
        PROVIDERS[provider]["key"]: "synthetic-owned-key",
        "VOICE_COMPAT_BASE_URL": "http://localhost:4141/v1",
    }
    monkeypatch.setattr(
        broker,
        "resolve_provider",
        lambda settings: {
            "apiProvider": provider,
            "resolved": "anthropic_text" if provider == "anthropic" else "local_text",
            "chatModel": "latest-test-model",
        },
    )
    monkeypatch.setattr(broker, "_merged_operator_env", lambda: env)
    metered = []
    monkeypatch.setattr(
        broker, "_meter_chat_usage", lambda model, usage: metered.append(usage)
    )
    seen = []

    def handler(request):
        seen.append((request, json.loads(request.content)))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "confirmed"}}],
                "content": [{"type": "text", "text": "confirmed"}],
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "confirmed"}],
                    }
                ],
                "usage": {"input_tokens": 10, "output_tokens": 2},
            },
        )

    mock_http(monkeypatch, handler)
    result = asyncio.run(
        broker.chat_completion(
            [
                {"role": "user", "content": "check"},
                {"role": "tool", "content": '{"ok":true}'},
            ],
            settings=settings,
        )
    )
    assert result["ok"] and result["reply"] == "confirmed" and metered
    request, body = seen[0]
    assert request.url.path.endswith(
        {
            "responses": "/responses",
            "chat": "/chat/completions",
            "messages": "/messages",
        }[style]
    )
    if style == "responses":
        assert body["store"] is False
    messages = body["input"] if style == "responses" else body["messages"]
    assert messages[-1] == {
        "role": "user",
        "content": 'Tool feedback (data):\n{"ok":true}',
    }


@pytest.mark.parametrize(
    "base",
    [
        "file:///tmp/key",
        "https://user:pass@host/v1",
        "http://localhost:11434?key=x",
        "https://host/v1#secret",
    ],
)
def test_unsafe_base_urls_are_rejected(base):
    with pytest.raises(ValueError):
        normalize_base(base)
