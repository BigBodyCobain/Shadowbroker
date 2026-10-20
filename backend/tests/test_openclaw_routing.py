"""OpenClaw routing, playbooks, and expensive-command gate."""

from __future__ import annotations

from services.openclaw_channel import _dispatch_command
from services.openclaw_routing import (
    EXPENSIVE_COMMANDS,
    plan_playbook,
    requires_expensive_confirm,
    route_query,
    routing_manifest,
)


def test_routing_manifest_has_agent_surface():
    manifest = routing_manifest()
    assert manifest["preferred_entry"] == "route_query"
    assert manifest["client_wrapper"] == "ShadowBrokerClient.ask"
    assert "search_telemetry" in manifest["expensive_commands"]
    assert "hot_snapshot" in manifest["playbooks"]


def test_route_query_tail_number():
    plan = route_query("track N628TS position")
    assert plan["recommended"]["cmd"] == "find_flights"
    assert plan["recommended"]["args"]["registration"] == "N628TS"
    assert "search_telemetry" in plan["avoid"]


def test_route_query_callsign():
    plan = route_query("where is AF1 right now")
    assert plan["recommended"]["cmd"] == "find_flights"
    assert plan["recommended"]["args"]["callsign"] == "AF1"


def test_route_query_news():
    plan = route_query("telegram news about Iran tanker")
    assert plan["recommended"]["cmd"] == "search_news"


def test_route_query_cve():
    plan = route_query("details for CVE-2024-1234")
    assert plan["recommended"]["cmd"] == "osint_lookup"
    assert plan["recommended"]["args"]["tool"] == "cve"


def test_route_query_default_entity():
    plan = route_query("where is the patriots jet")
    assert plan["recommended"]["cmd"] == "find_entity"
    assert plan["recommended"]["args"]["query"]


def test_expensive_gate_blocks_search_telemetry():
    assert requires_expensive_confirm("search_telemetry", {"query": "test"})
    assert not requires_expensive_confirm(
        "search_telemetry",
        {"query": "test", "confirm_expensive": True},
    )
    result = _dispatch_command("search_telemetry", {"query": "test"})
    assert result["ok"] is False
    assert result.get("code") == "expensive_command_blocked"


def test_expensive_gate_blocks_get_telemetry():
    result = _dispatch_command("get_telemetry", {})
    assert result["ok"] is False
    assert result.get("code") == "expensive_command_blocked"


def test_dispatch_route_query():
    result = _dispatch_command("route_query", {"text": "news about carrier strike"})
    assert result["ok"] is True
    assert result["data"]["recommended"]["cmd"] == "search_news"


def test_dispatch_run_playbook_hot_snapshot():
    result = _dispatch_command("run_playbook", {"name": "status_check"})
    assert result["ok"] is True
    cmds = [item["cmd"] for item in result["data"]["results"]]
    assert cmds == ["channel_status", "get_summary"]


def test_plan_playbook_track_snapshot_requires_query():
    plan = plan_playbook("track_snapshot", {})
    assert plan["ok"] is False
    plan_ok = plan_playbook("track_snapshot", {"query": "patriots jet"})
    assert plan_ok["ok"] is True
    assert plan_ok["batch"][0]["cmd"] == "get_entity_profile"


def test_expensive_commands_set():
    assert "get_report" in EXPENSIVE_COMMANDS
    assert "route_query" not in EXPENSIVE_COMMANDS


def test_routing_manifest_includes_infonet_hints():
    manifest = routing_manifest()
    recipes = " ".join(item.get("use", "") for item in manifest.get("recipes", []))
    assert "post_gate_message" in recipes
    writes = manifest.get("agent_surface", {}).get("writes", [])
    assert "post_gate_message" in writes
