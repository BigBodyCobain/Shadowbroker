from services.api_settings import ALLOWED_ENV_KEYS, API_REGISTRY


def test_aishub_username_is_in_api_registry():
    entry = next((item for item in API_REGISTRY if item.get("env_key") == "AISHUB_USERNAME"), None)
    assert entry is not None
    assert entry["category"] == "Maritime"
    assert entry["required"] is False
    assert "AISHUB_USERNAME" in ALLOWED_ENV_KEYS
