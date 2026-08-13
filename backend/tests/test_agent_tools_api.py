"""HTTP tests for the agent tool endpoints (manifest, invoke, audit, scopes)."""

import pytest


@pytest.fixture(autouse=True)
def _isolated_store():
    from storage import reset_store_for_tests

    reset_store_for_tests()
    yield
    reset_store_for_tests()


def test_manifest_lists_typed_tools(client):
    r = client.get("/api/agent/tools")
    assert r.status_code == 200, r.text
    data = r.json()
    names = {t["name"] for t in data["tools"]}
    assert {"search_entities", "find_anomalies", "create_investigation", "generate_briefing"} <= names
    # each tool declares a scope and typed parameters
    for t in data["tools"]:
        assert t["scope"] in ("read", "write", "act")
        assert isinstance(t["parameters"], dict)
    assert "granted_scopes" in data


def test_invoke_read_tool_ok(client):
    r = client.post("/api/agent/tools/invoke", json={"tool": "search_events", "args": {}})
    assert r.status_code == 200, r.text
    env = r.json()
    assert env["ok"] is True and env["scope"] == "read"
    assert "data" in env and "meta" in env


def test_invoke_unknown_tool_404(client):
    r = client.post("/api/agent/tools/invoke", json={"tool": "does_not_exist", "args": {}})
    assert r.status_code == 404


def test_invoke_validation_error_400(client):
    r = client.post("/api/agent/tools/invoke", json={"tool": "get_entity", "args": {}})
    assert r.status_code == 400  # missing required entity_id


def test_write_tool_denied_at_restricted_tier(client, monkeypatch):
    # Default OPENCLAW_ACCESS_TIER is restricted -> only read scope granted.
    monkeypatch.setattr("routers.agent_tools._granted_scopes", lambda: {"read"})
    r = client.post("/api/agent/tools/invoke", json={"tool": "create_investigation", "args": {"title": "x"}})
    assert r.status_code == 403


def test_write_tool_allowed_at_full_tier(client, monkeypatch):
    monkeypatch.setattr("routers.agent_tools._granted_scopes", lambda: {"read", "write", "act"})
    r = client.post("/api/agent/tools/invoke", json={"tool": "create_investigation", "args": {"title": "Full Tier Case"}})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["title"] == "Full Tier Case"


def test_untrusted_content_is_wrapped_in_live_results(client):
    # search_entities includes live telemetry matches wrapped as untrusted data.
    r = client.post("/api/agent/tools/invoke", json={"tool": "search_entities", "args": {"query": "test", "include_live": True}})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert "live_matches" in data
    assert data["live_matches"]["_untrusted_external_data"] is True


def test_audit_endpoint_records_invocations(client):
    client.post("/api/agent/tools/invoke", json={"tool": "search_events", "args": {}})
    r = client.get("/api/agent/audit")
    assert r.status_code == 200
    assert any(e["action"] == "tool_invoke" for e in r.json()["audit"])


def test_tools_require_auth(remote_client):
    # Non-loopback without HMAC/admin key is rejected.
    r = remote_client.get("/api/agent/tools")
    assert r.status_code in (401, 403)
    r = remote_client.post("/api/agent/tools/invoke", json={"tool": "search_events", "args": {}})
    assert r.status_code in (401, 403)
