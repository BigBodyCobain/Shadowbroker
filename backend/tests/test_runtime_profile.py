"""Runtime profile detection for lean fleet nodes."""

from services import runtime_profile


def test_resolve_profile_name_env_override(monkeypatch):
    monkeypatch.setenv("GT_ANALYTICS_PROFILE", "standard")
    monkeypatch.setattr(runtime_profile, "detect_cpu_limit", lambda: 1.0)
    assert runtime_profile.resolve_profile_name() == "standard"


def test_resolve_profile_name_auto_lean_on_one_cpu(monkeypatch):
    monkeypatch.delenv("GT_ANALYTICS_PROFILE", raising=False)
    monkeypatch.setattr(runtime_profile, "detect_cpu_limit", lambda: 1.0)
    assert runtime_profile.resolve_profile_name() == "lean"


def test_runtime_profile_payload(monkeypatch):
    monkeypatch.delenv("GT_ANALYTICS_PROFILE", raising=False)
    monkeypatch.setattr(runtime_profile, "detect_cpu_limit", lambda: 1.0)
    monkeypatch.setattr(runtime_profile, "detect_memory_limit_mb", lambda: 4096)
    runtime_profile.clear_runtime_profile_cache()
    payload = runtime_profile.get_runtime_profile()
    assert payload["profile"] == "lean"
    assert payload["cpu_limit"] == 1.0
    assert payload["gt_analytics"]["recommended"] is False
    assert payload["gt_analytics"]["lean_node"] is True
    assert "1 vCPU" in (payload["gt_analytics"]["warning"] or "")
