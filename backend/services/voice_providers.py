"""Provider connections and live model discovery for the operator AI console."""

from datetime import datetime
from urllib.parse import urlsplit


# Meta/Llama uses OpenRouter here; locally hosted Llama also works through Ollama.
PROVIDERS = {
    "openai": {
        "label": "OpenAI",
        "key": "VOICE_OPENAI_API_KEY",
        "base": "https://api.openai.com/v1",
        "style": "responses",
    },
    "gemini": {
        "label": "Google Gemini",
        "key": "VOICE_GEMINI_API_KEY",
        "base": "https://generativelanguage.googleapis.com/v1beta/openai",
        "style": "chat",
    },
    "anthropic": {
        "label": "Anthropic / Claude",
        "key": "VOICE_ANTHROPIC_API_KEY",
        "base": "https://api.anthropic.com/v1",
        "style": "messages",
    },
    "xai": {
        "label": "xAI / Grok",
        "key": "VOICE_XAI_API_KEY",
        "base": "https://api.x.ai/v1",
        "style": "responses",
    },
    "openrouter": {
        "label": "OpenRouter",
        "key": "VOICE_OPENROUTER_API_KEY",
        "base": "https://openrouter.ai/api/v1",
        "style": "chat",
    },
    "meta": {
        "label": "Meta / Llama via OpenRouter",
        "key": "VOICE_OPENROUTER_API_KEY",
        "base": "https://openrouter.ai/api/v1",
        "style": "chat",
    },
    "ollama": {
        "label": "Ollama",
        "key": "VOICE_COMPAT_API_KEY",
        "base": "http://127.0.0.1:11434/v1",
        "style": "chat",
    },
    "lmstudio": {
        "label": "LM Studio",
        "key": "VOICE_COMPAT_API_KEY",
        "base": "http://127.0.0.1:1234/v1",
        "style": "chat",
    },
    "compat": {
        "label": "Custom API",
        "key": "VOICE_COMPAT_API_KEY",
        "base": "",
        "style": "chat",
    },
}
LOCAL_PROVIDERS = {"ollama", "lmstudio", "compat"}
PROVIDER_ALIASES = {
    "openai_realtime": "openai",
    "gemini_live": "gemini",
    "anthropic_text": "anthropic",
    "compatible_ws": "compat",
    "local_text": "compat",
}


def normalize_base(value: str) -> str:
    base = str(value or "").strip().rstrip("/")
    try:
        if "\\" in base or any(ord(char) < 32 for char in base):
            raise ValueError
        parsed = urlsplit(base)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError
        _ = parsed.port
    except ValueError:
        raise ValueError(
            "Use an HTTP(S) API base URL without credentials, query, or fragment."
        ) from None
    return base + "/v1" if not parsed.path else base


def connection_for(provider: str, settings, env: dict) -> dict:
    profile = PROVIDERS[provider]
    base = profile["base"]
    if provider in LOCAL_PROVIDERS:
        base = str(env.get("VOICE_COMPAT_BASE_URL") or "")
    elif provider == "openai":
        base = str(getattr(settings, "VOICE_OPENAI_BASE_URL", "") or base)
    elif provider == "anthropic":
        base = str(getattr(settings, "VOICE_ANTHROPIC_BASE_URL", "") or base)
    selected = str(getattr(settings, "VOICE_API_PROVIDER", "") or "")
    return {
        "base": normalize_base(base) if base else "",
        "key": str(env.get(profile["key"]) or "").strip(),
        "style": str(getattr(settings, "VOICE_API_STYLE", "") or profile["style"])
        if selected == provider
        else profile["style"],
    }


def _created(value) -> float:
    try:
        return float(value or 0)
    except (ValueError, TypeError):
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
        except (ValueError, TypeError, OSError):
            return 0


async def discover_models(
    provider: str, connection: dict, *, mode: str = "text"
) -> dict:
    """Only use the server-saved destination/key. Never follow credential redirects."""
    import httpx

    base, key = connection["base"], connection["key"]
    if not base or (provider not in LOCAL_PROVIDERS and not key):
        return {
            "ok": True,
            "models": [],
            "note": "Save this provider's credentials first.",
            "live": False,
        }
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    url = base + "/models"
    if provider == "anthropic":
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    elif provider == "gemini":
        url = "https://generativelanguage.googleapis.com/v1beta/models"
        headers = {"x-goog-api-key": key}
    params = (
        {"pageSize": 1000}
        if provider == "gemini"
        else {"limit": 100}
        if provider == "anthropic"
        else {}
    )
    rows = []
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
            for _ in range(10):
                response = await client.get(url, headers=headers, params=params)
                if response.status_code == 404 and provider == "ollama":
                    response = await client.get(
                        base.removesuffix("/v1") + "/api/tags", headers=headers
                    )
                if response.status_code != 200:
                    return {
                        "ok": False,
                        "models": [],
                        "error": "models_unavailable",
                        "detail": f"Model discovery returned HTTP {response.status_code}.",
                    }
                body = response.json()
                if not isinstance(body, dict):
                    raise ValueError("Invalid model list")
                batch = (
                    body.get("models")
                    if provider in {"gemini", "ollama"} and "models" in body
                    else body.get("data")
                )
                if not isinstance(batch, list):
                    raise ValueError("Invalid model list")
                rows.extend(row for row in batch if isinstance(row, dict))
                token = body.get("nextPageToken")
                if token and provider == "gemini":
                    params["pageToken"] = str(token)
                elif body.get("has_more") and batch and provider == "anthropic":
                    params["after_id"] = str(
                        body.get("last_id") or batch[-1].get("id", "")
                    )
                else:
                    break
    except (httpx.HTTPError, httpx.InvalidURL, ValueError, TypeError) as exc:
        return {
            "ok": False,
            "models": [],
            "error": "models_unavailable",
            "detail": f"Could not load models ({type(exc).__name__}).",
        }
    models = {}
    for row in rows:
        model_id = str(row.get("id") or row.get("name") or "").removeprefix("models/")
        if not model_id or len(model_id) > 256:
            continue
        methods = row.get("supportedGenerationMethods") or []
        realtime = (
            "bidiGenerateContent" in methods
            if provider == "gemini"
            else "realtime" in model_id.lower()
        )
        if mode == "speech" and provider == "openai":
            if not any(word in model_id.lower() for word in ("transcribe", "whisper")):
                continue
        elif mode == "realtime":
            if provider not in {"openai", "gemini", "compat"} or not realtime:
                continue
        else:
            if provider == "gemini" and "generateContent" not in methods:
                continue
            if provider == "openai" and (
                realtime
                or any(
                    word in model_id.lower()
                    for word in (
                        "embedding",
                        "tts",
                        "transcribe",
                        "whisper",
                        "moderation",
                        "image",
                        "audio",
                        "live",
                        "dall-e",
                        "sora",
                    )
                )
            ):
                continue
            architecture = row.get("architecture") or {}
            if not isinstance(architecture, dict):
                architecture = {}
            if (
                architecture.get("output_modalities")
                and "text" not in architecture["output_modalities"]
            ):
                continue
        if provider == "meta" and not model_id.startswith("meta-llama/"):
            continue
        models[model_id] = {
            "id": model_id,
            "name": str(
                row.get("display_name")
                or row.get("displayName")
                or row.get("name")
                or model_id
            ),
            "created": _created(row.get("created") or row.get("created_at")),
            "realtime": realtime,
        }
    return {
        "ok": True,
        "models": sorted(
            models.values(), key=lambda model: (-model["created"], model["id"])
        )[:2000],
        "live": True,
        "provider": provider,
    }
