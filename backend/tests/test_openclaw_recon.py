"""Tests for OpenClaw recon / OSINT command dispatch."""

import pytest


def test_osint_tools_lists_supported_lookups():
    from services.osint.openclaw_recon import osint_tool_help

    help_data = osint_tool_help()
    assert "ip" in help_data["tools"]
    assert "sanctions" in help_data["tools"]
    assert "aircraft" in help_data["entity_types"]


def test_osint_lookup_ip(monkeypatch):
    from services.osint import openclaw_recon

    monkeypatch.setattr(
        openclaw_recon.lookups,
        "lookup_ip",
        lambda ip: {"ip": ip, "geo": {"country": "US"}},
    )
    result = openclaw_recon.run_osint_lookup("ip", {"ip": "8.8.8.8"})
    assert result["ip"] == "8.8.8.8"
    assert result["geo"]["country"] == "US"


def test_osint_lookup_sanctions_passes_schema(monkeypatch):
    from services.osint import openclaw_recon

    captured = {}

    def fake_sanctions(query, *, schema=None, limit=25):
        captured["query"] = query
        captured["schema"] = schema
        captured["limit"] = limit
        return {"query": query, "results": []}

    monkeypatch.setattr(openclaw_recon.lookups, "lookup_sanctions", fake_sanctions)
    openclaw_recon.run_osint_lookup(
        "sanctions",
        {"query": "Example Corp", "schema": "Company", "limit": 10},
    )
    assert captured["query"] == "Example Corp"
    assert captured["schema"] == "Company"
    assert captured["limit"] == 10


def test_osint_lookup_rejects_unknown_tool():
    from services.osint.openclaw_recon import run_osint_lookup

    with pytest.raises(ValueError, match="Unknown OSINT tool"):
        run_osint_lookup("not_a_tool", {})


def test_openclaw_osint_lookup_command(monkeypatch):
    from services import openclaw_channel

    monkeypatch.setattr(
        "services.osint.openclaw_recon.run_osint_lookup",
        lambda tool, args: {"ip": args["ip"], "tool": tool},
    )
    result = openclaw_channel._dispatch_command(
        "osint_lookup",
        {"tool": "ip", "ip": "1.1.1.1"},
    )
    assert result["ok"] is True
    assert result["data"]["ip"] == "1.1.1.1"


def test_openclaw_entity_expand_command(monkeypatch):
    from services import openclaw_channel

    monkeypatch.setattr(
        "services.osint.openclaw_recon.run_entity_expand",
        lambda args: {"nodes": [{"id": "ip:1.1.1.1"}], "links": []},
    )
    result = openclaw_channel._dispatch_command(
        "entity_expand",
        {"type": "ip", "id": "1.1.1.1"},
    )
    assert result["ok"] is True
    assert result["data"]["nodes"][0]["id"] == "ip:1.1.1.1"


def test_osint_sweep_requires_full_tier_for_restricted():
    from services.openclaw_channel import WRITE_COMMANDS, allowed_commands

    assert "osint_sweep" in WRITE_COMMANDS
    assert "osint_sweep" not in allowed_commands("restricted")
    assert "osint_sweep" in allowed_commands("full")


def test_osint_lookup_available_on_restricted_tier():
    from services.openclaw_channel import allowed_commands

    assert "osint_lookup" in allowed_commands("restricted")
    assert "entity_expand" in allowed_commands("restricted")
