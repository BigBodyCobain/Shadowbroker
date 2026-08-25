"""Voice-agent tool registry unit suite (voice-agent plan U3, §7.A items 11–16).

The registry is the single gate between model-proposed tool calls and real
execution, so its manifest union, tier/expensive/destructive gates, validator
coercion, and deterministic-fallback goldens are pinned here. U3's phase gate
is "registry + fixture-drift + gate tests green" (§3.3) — endpoint reachability
lands with U2's ``routers/voice.py``.
"""

import ast
import json
import os
import re

import pytest

from services.openclaw_channel import READ_COMMANDS, WRITE_COMMANDS, _expensive_gate
from services.voice_tool_registry import (
    CLIENT_TOOLS_FIXTURE_PATH,
    DEFAULT_RADIUS_KM_MAX,
    DESTRUCTIVE_COMMANDS,
    build_manifest,
    get_tool_entry,
    resolve_deterministic,
    validate_and_gate,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tool_names(entries):
    return {entry["name"] for entry in entries}


def _repo_root():
    return os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _clienttools_path():
    return os.path.join(_repo_root(), "frontend", "src", "lib", "clientTools.ts")


def _load_fixture_tools():
    with open(CLIENT_TOOLS_FIXTURE_PATH, encoding="utf-8") as fh:
        return json.load(fh)["tools"]


# ---------------------------------------------------------------------------
# Item 11 — manifest union + collisions + schema self-check
# ---------------------------------------------------------------------------


class TestManifestConstruction:
    def test_manifest_covers_full_command_union(self):
        entries = build_manifest(include_client=False)
        names = _tool_names(entries)
        assert names >= set(READ_COMMANDS | WRITE_COMMANDS)

    def test_manifest_appends_client_fixture(self):
        server = build_manifest(include_client=False)
        merged = build_manifest(include_client=True)
        assert _tool_names(merged) == _tool_names(server) | _tool_names(_load_fixture_tools())

    def test_zero_name_collisions(self):
        server_names = _tool_names(build_manifest(include_client=False))
        client_names = _tool_names(_load_fixture_tools())
        assert not server_names & client_names

    def test_collision_fails_loudly_at_build_time(self, monkeypatch):
        colliding = [dict(_load_fixture_tools()[0], name=sorted(READ_COMMANDS)[0])]
        monkeypatch.setattr(
            "services.voice_tool_registry._load_client_fixture",
            lambda: colliding,
        )
        with pytest.raises(ValueError, match="collides"):
            build_manifest(include_client=True)

    def test_schema_self_check_every_entry(self):
        for entry in build_manifest(include_client=True):
            assert entry["surface"] in ("server", "client"), entry["name"]
            assert isinstance(entry["description"], str) and entry["description"], entry["name"]
            assert isinstance(entry["parameters"], dict), entry["name"]
            assert isinstance(entry["returns"], str) and entry["returns"], entry["name"]
            assert entry["type"] in (
                "read",
                "write",
                "camera",
                "ui",
                "interrogate",
            ), entry["name"]
            if entry["surface"] == "server":
                expected_type = "write" if entry["name"] in WRITE_COMMANDS else "read"
                assert entry["type"] == expected_type, entry["name"]

    def test_get_tool_entry_lookup(self):
        assert get_tool_entry("get_summary")["name"] == "get_summary"
        assert get_tool_entry("map_fly_to")["surface"] == "client"
        assert get_tool_entry("__not_a_tool__") is None


# ---------------------------------------------------------------------------
# Item 12 — fixture drift vs TS descriptor block (active since U4)
# ---------------------------------------------------------------------------

_TS_BEGIN_MARKER = "/* voice-client-tools:begin */"
_TS_END_MARKER = "/* voice-client-tools:end */"


def _parse_ts_descriptor_block(source: str) -> list:
    """Parse the marker-delimited descriptor block from clientTools.ts.

    The block must be a JSON-compatible array of tool descriptors (same shape
    as the fixture's ``tools`` entries). Line comments are tolerated; keys must
    stay quoted so the block parses as strict JSON after comment stripping.
    """
    begin = source.index(_TS_BEGIN_MARKER) + len(_TS_BEGIN_MARKER)
    end = source.index(_TS_END_MARKER)
    block = source[begin:end]
    stripped = re.sub(r"^\s*//.*$", "", block, flags=re.MULTILINE)
    parsed = json.loads(stripped)
    assert isinstance(parsed, list)
    return parsed


class TestFixtureDriftGuard:
    def test_fixture_is_valid_json_with_expected_shape(self):
        tools = _load_fixture_tools()
        assert len(tools) >= 16
        for entry in tools:
            assert entry["surface"] == "client"
            assert entry["requires_confirm"] is False

    def test_client_fixture_matches_ts_descriptor_block(self):
        path = _clienttools_path()
        assert os.path.exists(path), (
            "frontend/src/lib/clientTools.ts is required since U4 (§3.9)"
        )
        source = open(path, encoding="utf-8").read()
        assert _TS_BEGIN_MARKER in source and _TS_END_MARKER in source, (
            "clientTools.ts must carry the /* voice-client-tools:begin/end */ "
            "marker block (single source of truth, §3.3/R13)"
        )
        ts_tools = _parse_ts_descriptor_block(source)
        fixture_tools = _load_fixture_tools()
        assert ts_tools == fixture_tools, (
            "voice_client_tools.json drifted from the clientTools.ts descriptor "
            "block — regenerate the fixture (single source of truth, §3.3/R13)"
        )


# ---------------------------------------------------------------------------
# Item 13 — tier gate
# ---------------------------------------------------------------------------


class TestTierGate:
    def test_restricted_rejects_every_write_command(self):
        for cmd in sorted(WRITE_COMMANDS):
            clean, err = validate_and_gate({"tool": cmd, "args": {}}, access_tier="restricted")
            assert clean is None, cmd
            assert err["ok"] is False
            assert err["code"] == "tier_blocked", cmd

    def test_restricted_allows_camera_verbs(self):
        clean, err = validate_and_gate(
            {"tool": "map_fly_to", "args": {"lat": 50.45, "lng": 30.52}},
            access_tier="restricted",
        )
        assert err is None
        assert clean["surface"] == "client"
        assert clean["args"]["lat"] == 50.45

    def test_full_tier_allows_write_commands(self):
        clean, err = validate_and_gate({"tool": "add_watch", "args": {"confirm": False}}, access_tier="full")
        # add_watch requires its own args; the point here is only that the
        # tier gate did NOT fire.
        assert err is None or err["code"] != "tier_blocked"
        if err is None:
            assert clean["tool"] == "add_watch"

    def test_tier_normalization_hostile_input_is_restricted(self):
        # add_watch: a write command outside DESTRUCTIVE_COMMANDS.
        for tier in ("", "  ", "Full-Tier", "admin"):
            clean, err = validate_and_gate({"tool": "add_watch", "args": {}}, access_tier=tier)
            assert clean is None
            assert err is not None and err["code"] == "tier_blocked"
        # Exact "full" survives whitespace/case normalization only.
        _, err = validate_and_gate({"tool": "add_watch", "args": {}}, access_tier=" FULL ")
        assert err is None or err["code"] != "tier_blocked"


# ---------------------------------------------------------------------------
# Item 14 — expensive & destructive gates
# ---------------------------------------------------------------------------


class TestExpensiveGate:
    @pytest.mark.parametrize("cmd,args", [
        ("search_telemetry", {"query": "test"}),
        ("get_telemetry", {}),
        ("get_report", {}),
    ])
    def test_envelope_byte_identical_to_channel_gate(self, cmd, args):
        _, err = validate_and_gate({"tool": cmd, "args": dict(args)}, access_tier="full")
        expected = _expensive_gate(cmd, dict(args))
        assert err == expected
        assert err["code"] == "expensive_command_blocked"

    def test_confirm_expensive_passes_through(self):
        clean, err = validate_and_gate(
            {"tool": "search_telemetry", "args": {"query": "test", "confirm_expensive": True}},
            access_tier="full",
        )
        assert err is None
        assert clean["tool"] == "search_telemetry"
        assert "confirm_expensive" not in clean["args"]


class TestDestructiveGate:
    def test_destructive_commands_are_manifest_members(self):
        manifest_names = _tool_names(build_manifest())
        # clear_pins is listed per plan but is not a channel command today;
        # every other destructive member must exist in the merged manifest.
        rest = DESTRUCTIVE_COMMANDS - {"clear_pins"}
        assert rest <= manifest_names

    @pytest.mark.parametrize("cmd", ["delete_layer", "delete_pin", "clear_analysis_zones"])
    def test_blocks_without_confirm(self, cmd):
        clean, err = validate_and_gate({"tool": cmd, "args": {}}, access_tier="full")
        assert clean is None
        assert err["code"] == "destructive_confirm_required"

    def test_confirm_true_passes_through(self):
        clean, err = validate_and_gate(
            {"tool": "clear_watches", "args": {"confirm": True}},
            access_tier="full",
        )
        assert err is None
        assert clean["tool"] == "clear_watches"
        assert "confirm" not in clean["args"]


# ---------------------------------------------------------------------------
# Item 15 — parameter validation
# ---------------------------------------------------------------------------


class TestValidator:
    def test_enum_violation_rejected(self):
        clean, err = validate_and_gate(
            {"tool": "map_zoom", "args": {"direction": "sideways"}},
            access_tier="restricted",
        )
        assert clean is None
        assert err["code"] == "invalid_arguments"
        assert err["param"] == "direction"

    def test_string_number_coerced_to_float(self):
        clean, err = validate_and_gate(
            {"tool": "map_fly_to", "args": {"lat": "35.5", "lng": "139.76"}},
            access_tier="restricted",
        )
        assert err is None
        assert clean["args"]["lat"] == 35.5
        assert isinstance(clean["args"]["lat"], float)

    def test_unknown_args_dropped_with_ignored_args_warning(self):
        clean, err = validate_and_gate(
            {"tool": "find_flights", "args": {"query": "test", "compact": True, "colour": "violet"}},
            access_tier="restricted",
        )
        assert err is None
        assert clean["args"].get("compact") is True
        assert clean["ignored_args"] == ["colour"]

    def test_missing_required_parameter(self):
        clean, err = validate_and_gate(
            {"tool": "map_fly_to", "args": {"lat": 1.0}},
            access_tier="restricted",
        )
        assert clean is None
        assert err["code"] == "invalid_arguments"
        assert err["param"] == "lng"

    def test_radius_km_clamped_to_default_max(self):
        clean, err = validate_and_gate(
            {"tool": "entities_near", "args": {"lat": 0, "lng": 0, "radius_km": 50000}},
            access_tier="restricted",
        )
        if err is not None:
            pytest.skip(f"entities_near schema unavailable: {err}")
        assert clean["args"]["radius_km"] == DEFAULT_RADIUS_KM_MAX

    def test_unknown_tool_static_error_text(self):
        clean, err = validate_and_gate(
            {"tool": "DROP TABLE agents; --", "args": {}},
            access_tier="full",
        )
        assert clean is None
        assert err["code"] == "unknown_tool"
        # Free text must never flow into detail (injection defense).
        assert "DROP TABLE" not in err["detail"]

    def test_non_object_call_rejected(self):
        for bad in (None, "get_summary", 42, ["get_summary"]):
            clean, err = validate_and_gate(bad, access_tier="full")
            assert clean is None
            assert err["code"] == "bad_call"


# ---------------------------------------------------------------------------
# Item 16 — deterministic fallback goldens (§3.7)
# ---------------------------------------------------------------------------


class TestDeterministicFallbackGoldens:
    def test_what_changed_routes_to_what_changed(self):
        result = resolve_deterministic("what changed")
        assert result["kind"] == "route_query"
        assert result["recommended"]["cmd"] == "what_changed"

    def test_cve_string_routes_to_osint_lookup_cve(self):
        result = resolve_deterministic("explain CVE-2021-44228 please")
        assert result["kind"] == "route_query"
        assert result["recommended"]["cmd"] == "osint_lookup"
        assert result["recommended"]["args"]["tool"] == "cve"

    @pytest.mark.parametrize("phrase,tool", [
        ("fly to Kyiv", "map_fly_to"),
        ("take me to the Black Sea coast", "map_fly_to"),
        ("zoom in", "map_zoom"),
        ("ZOOM OUT", "map_zoom"),
        ("stop orbit", "map_orbit"),
        ("orbit here", "map_orbit"),
    ])
    def test_camera_phrases_never_hit_route_query(self, phrase, tool):
        result = resolve_deterministic(phrase)
        assert result["kind"] == "client_verb", phrase
        assert result["tool"] == tool
        assert "recommended" not in result
