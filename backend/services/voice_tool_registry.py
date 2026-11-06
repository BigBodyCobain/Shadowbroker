"""Voice-agent tool registry — one manifest, two surfaces (voice-agent plan U3, §3.3).

Merges the server commands dispatched by ``openclaw_channel._dispatch_command``
(the same surface published by ``GET /api/ai/tools``) with the client-side
MapLibre/UI verbs only the browser can execute, and gates every voice-initiated
call through the tier/expensive/destructive gates plus schema validation before
anything executes.

Pure module: stdlib + pure service imports at module level (AST-freeze safe,
§1.5); the heavy ``routers.ai_intel`` metadata import happens inside
``build_manifest``'s function body. This module must never import
``services.openclaw_watchdog`` (watchdog decoupling, §3.8) or any transport.

Public API:
    build_manifest(include_client=True) -> list[dict]
    validate_and_gate(call, *, access_tier) -> (clean_call, None)
                                             | (None, error_envelope)
    resolve_deterministic(text, *, lat=None, lng=None) -> dict

The ``GET /api/voice/tools`` / ``POST /api/voice/tool`` endpoints live on
``routers/voice.py`` (U2's router); this module ships standalone so U3's phase
gate is "registry + fixture-drift + gate tests green".
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from services.config import get_settings
from services.openclaw_channel import READ_COMMANDS, WRITE_COMMANDS
from services.openclaw_routing import (
    EXPENSIVE_GATE_MESSAGE,
    LATENCY_TIER_MS,
    requires_expensive_confirm,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fixtures & constants
# ---------------------------------------------------------------------------

CLIENT_TOOLS_FIXTURE_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "fixtures", "voice_client_tools.json")
)

#: Commands that mutate or destroy operator state and demand an explicit
#: ``confirm: true`` (§3.3 destructive gate — same two-turn unlock pattern as
#: the expensive gate). ``clear_pins`` is listed per plan even though it is a
#: REST route rather than a channel command today; membership is harmless while
#: it stays outside the manifest.
DESTRUCTIVE_COMMANDS = frozenset(
    {
        "delete_layer",
        "delete_pin",
        "clear_pins",
        "clear_watches",
        "clear_analysis_zones",
        "delete_analysis_zone",
    }
)

#: Entry types visible below the ``full`` access tier (§3.3 tier gate): camera/ui
#: verbs are deliberately below write tier — "zoom in" must never demand full tier.
RESTRICTED_ENTRY_TYPES = frozenset({"read", "camera", "ui"})

_PARAM_TYPES = frozenset({"string", "integer", "float", "boolean", "array", "object"})

#: Control keys consumed by the gates themselves — never forwarded as args.
_CONTROL_ARG_KEYS = frozenset({"confirm", "confirm_expensive"})

#: Default upper bound applied to ``radius_km`` args lacking an explicit schema
#: max (§3.3 "range clamps (e.g. radius_km ≤ 1000)").
DEFAULT_RADIUS_KM_MAX = 1000.0

_FALLBACK_LATENCY_MS = 100


# ---------------------------------------------------------------------------
# Manifest construction
# ---------------------------------------------------------------------------


def _load_client_fixture() -> list[dict[str, Any]]:
    """Load the committed client verb fixture (generated source of truth)."""
    import json

    with open(CLIENT_TOOLS_FIXTURE_PATH, encoding="utf-8") as fh:
        payload = json.load(fh)
    tools = payload.get("tools") if isinstance(payload, dict) else payload
    if not isinstance(tools, list):
        raise ValueError(f"voice client fixture malformed: {CLIENT_TOOLS_FIXTURE_PATH}")
    return [dict(entry) for entry in tools]


def _server_metadata() -> dict[str, dict[str, Any]]:
    """Per-command rich metadata published by ``agent_tool_manifest()``.

    Imported from ``routers.ai_intel`` inside the function body (lazy-import
    convention, §1.5). If the router cannot be imported the registry still
    builds from the command sets alone — every command keeps a valid generic
    entry so the manifest union is always complete.
    """
    try:
        from routers.ai_intel import _AGENT_TOOLS
    except Exception as exc:  # pragma: no cover - defensive; tests import it fine
        logger.warning("voice registry: agent tool metadata unavailable: %s", exc)
        return {}
    return {entry["name"]: entry for entry in _AGENT_TOOLS if isinstance(entry, dict) and entry.get("name")}


def _base_server_entry(cmd: str, cmd_type: str) -> dict[str, Any]:
    # U3-judge advisory (applied U5): destructive members must advertise
    # requires_confirm=True so models learn the confirm requirement upfront
    # instead of discovering it at the gate.
    return {
        "name": cmd,
        "type": cmd_type,
        "surface": "server",
        "description": (
            f"Server command dispatched via POST /api/ai/channel/command "
            f"(cmd={cmd})."
        ),
        "parameters": {},
        "returns": "{ok, data, version?, format?}",
        "latency_tier_ms": LATENCY_TIER_MS.get(cmd, _FALLBACK_LATENCY_MS),
        "requires_confirm": cmd in DESTRUCTIVE_COMMANDS,
    }


def _check_entry_schema(entry: Any, origin: str) -> None:
    """Schema self-check for a single manifest entry (raises ValueError)."""
    if not isinstance(entry, dict):
        raise ValueError(f"{origin}: entry is not an object")
    for key in ("name", "type", "surface", "description", "parameters", "returns"):
        if key not in entry:
            raise ValueError(f"{origin}: entry {entry.get('name')!r} missing {key!r}")
    if not isinstance(entry["name"], str) or not entry["name"]:
        raise ValueError(f"{origin}: bad name")
    if entry["surface"] not in ("server", "client"):
        raise ValueError(f"{origin}: {entry['name']!r} bad surface {entry['surface']!r}")
    if not isinstance(entry["parameters"], dict):
        raise ValueError(f"{origin}: {entry['name']!r} parameters must be an object")
    for pname, spec in entry["parameters"].items():
        if not isinstance(spec, dict):
            raise ValueError(f"{origin}: {entry['name']}.{pname} spec must be an object")
        if spec.get("type") not in _PARAM_TYPES:
            raise ValueError(f"{origin}: {entry['name']}.{pname} bad type {spec.get('type')!r}")
        enum = spec.get("enum")
        if enum is not None and not (isinstance(enum, list) and enum):
            raise ValueError(f"{origin}: {entry['name']}.{pname} enum must be a non-empty list")
    latency = entry.get("latency_tier_ms")
    if latency is not None and (not isinstance(latency, int) or isinstance(latency, bool) or latency < 0):
        raise ValueError(f"{origin}: {entry['name']!r} bad latency_tier_ms")


def build_manifest(include_client: bool = True) -> list[dict[str, Any]]:
    """Build the merged voice tool manifest.

    Server entries derive from the ``READ_COMMANDS | WRITE_COMMANDS`` sets
    *imported* (never copied) from ``openclaw_channel``, overlaid with the rich
    metadata published by ``agent_tool_manifest()``. Client entries load from
    the committed fixture. Name collisions fail loudly at build time (test #11).
    """
    metadata = _server_metadata()
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()

    for cmd in sorted(READ_COMMANDS | WRITE_COMMANDS):
        cmd_type = "write" if cmd in WRITE_COMMANDS else "read"
        entry = _base_server_entry(cmd, cmd_type)
        meta = metadata.get(cmd)
        if meta is not None:
            for key in ("description", "parameters", "returns"):
                if key in meta:
                    entry[key] = meta[key]
        _check_entry_schema(entry, f"server:{cmd}")
        if entry["name"] in seen:
            raise ValueError(f"duplicate tool name in manifest: {entry['name']}")
        seen.add(entry["name"])
        entries.append(entry)

    if include_client:
        for entry in _load_client_fixture():
            _check_entry_schema(entry, f"client:{entry.get('name')}")
            if entry["name"] in seen:
                raise ValueError(f"client tool collides with server tool: {entry['name']}")
            seen.add(entry["name"])
            entries.append(entry)

    return entries


def get_tool_entry(name: str, include_client: bool = True) -> dict[str, Any] | None:
    """Return the manifest entry for ``name``, or None if unknown."""
    for entry in build_manifest(include_client=include_client):
        if entry["name"] == name:
            return entry
    return None


# ---------------------------------------------------------------------------
# Gates & validation
# ---------------------------------------------------------------------------

_STATIC_UNKNOWN_TOOL_DETAIL = "unknown tool — consult GET /api/voice/tools for the available manifest."
_STATIC_TIER_BLOCKED_DETAIL = "write commands require full OpenClaw access tier (OPENCLAW_ACCESS_TIER)."
_STATIC_DESTRUCTIVE_DETAIL = "destructive command blocked — pass confirm=true to apply this action."
_STATIC_INVALID_ARGS_DETAIL = "arguments failed validation."


def _error(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    envelope: dict[str, Any] = {"ok": False, "code": code, "detail": detail}
    envelope.update(extra)
    return envelope


def _coerce_value(pname: str, spec: dict[str, Any], value: Any) -> tuple[bool, Any]:
    """Coerce ``value`` to the declared parameter type. Returns (ok, value|reason)."""
    ptype = spec.get("type")
    if ptype == "string":
        if isinstance(value, str):
            return True, value
        if isinstance(value, bool):
            return True, "true" if value else "false"
        if isinstance(value, (int, float)):
            return True, str(value)
        return False, "expected string"
    if ptype == "integer":
        if isinstance(value, bool):
            return False, "expected integer"
        if isinstance(value, int):
            return True, value
        if isinstance(value, float) and float(value).is_integer():
            return True, int(value)
        if isinstance(value, str):
            try:
                return True, int(value.strip())
            except ValueError:
                return False, "expected integer"
        return False, "expected integer"
    if ptype == "float":
        if isinstance(value, bool):
            return False, "expected number"
        if isinstance(value, (int, float)):
            return True, float(value)
        if isinstance(value, str):
            try:
                return True, float(value.strip())
            except ValueError:
                return False, "expected number"
        return False, "expected number"
    if ptype == "boolean":
        if isinstance(value, bool):
            return True, value
        if isinstance(value, int) and value in (0, 1):
            return True, bool(value)
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in ("true", "1", "yes"):
                return True, True
            if lowered in ("false", "0", "no"):
                return True, False
        return False, "expected boolean"
    if ptype == "array":
        if isinstance(value, (list, tuple)):
            return True, list(value)
        return False, "expected array"
    if ptype == "object":
        if isinstance(value, dict):
            return True, value
        return False, "expected object"
    return False, f"unknown parameter type {ptype!r}"


def _validate_args(entry: dict[str, Any], args: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Validate/coerce ``args`` against the entry schema.

    Returns (clean_args, None) on success or (None, error_envelope) on failure.
    Unknown args are dropped and reported via ``ignored_args`` (models
    hallucinate optional spellings; the validator remains the authority).
    """
    schema = entry.get("parameters") or {}
    clean: dict[str, Any] = {}
    ignored = [key for key in args if key not in schema and key not in _CONTROL_ARG_KEYS]

    for pname, spec in schema.items():
        if pname in args:
            ok, coerced = _coerce_value(pname, spec, args[pname])
            if not ok:
                return None, _error(
                    "invalid_arguments",
                    _STATIC_INVALID_ARGS_DETAIL,
                    param=pname,
                    reason=coerced,
                )
            enum = spec.get("enum")
            if enum is not None and coerced not in enum:
                return None, _error(
                    "invalid_arguments",
                    _STATIC_INVALID_ARGS_DETAIL,
                    param=pname,
                    reason="value not in allowed options",
                )
            if isinstance(coerced, (int, float)) and not isinstance(coerced, bool):
                maximum = spec.get("max")
                minimum = spec.get("min")
                if maximum is None and pname == "radius_km":
                    maximum = DEFAULT_RADIUS_KM_MAX
                if maximum is not None:
                    coerced = min(coerced, float(maximum))
                if minimum is not None:
                    coerced = max(coerced, float(minimum))
            clean[pname] = coerced
        elif spec.get("required"):
            return None, _error(
                "invalid_arguments",
                _STATIC_INVALID_ARGS_DETAIL,
                param=pname,
                reason="missing required parameter",
            )

    result = {"args": clean}
    if ignored:
        result["ignored_args"] = sorted(ignored)
    return result, None


def validate_and_gate(
    call: Any,
    *,
    access_tier: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Gate and validate one model-proposed tool call.

    ``call`` is the picker-contract object ``{"tool": ..., "args": {...}}``
    (``cmd``/``name`` accepted as aliases). Returns ``(clean_call, None)`` where
    ``clean_call`` is ``{"tool", "surface", "args"[, "ignored_args"]}``, or
    ``(None, error_envelope)`` whose ``detail`` strings are static — free-text
    never flows into error text (injection defense, §3.4).
    """
    if not isinstance(call, dict):
        return None, _error("bad_call", "tool call must be an object.")

    name = call.get("tool") or call.get("cmd") or call.get("name")
    if not isinstance(name, str) or not name.strip():
        return None, _error("bad_call", "tool call missing tool name.")
    name = name.strip()

    args = call.get("args")
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return None, _error("bad_call", "tool call args must be an object.")

    entry = get_tool_entry(name)
    if entry is None:
        return None, _error("unknown_tool", _STATIC_UNKNOWN_TOOL_DETAIL)

    tier = str(access_tier or "").strip().lower()
    if tier != "full" and entry["type"] not in RESTRICTED_ENTRY_TYPES:
        return None, _error("tier_blocked", _STATIC_TIER_BLOCKED_DETAIL)

    # Expensive gate — reused verbatim from openclaw_channel._expensive_gate.
    if requires_expensive_confirm(name, args):
        return None, {
            "ok": False,
            "detail": EXPENSIVE_GATE_MESSAGE,
            "code": "expensive_command_blocked",
            "hint": "route_query",
        }

    # Destructive gate — same two-turn unlock pattern with confirm=true.
    if name in DESTRUCTIVE_COMMANDS and args.get("confirm") is not True:
        return None, _error(
            "destructive_confirm_required",
            _STATIC_DESTRUCTIVE_DETAIL,
            hint="confirm",
        )

    validated, err = _validate_args(entry, args)
    if err is not None:
        return None, err

    clean_call: dict[str, Any] = {
        "tool": name,
        "surface": entry["surface"],
        "args": validated["args"],
    }
    if "ignored_args" in validated:
        clean_call["ignored_args"] = validated["ignored_args"]
    return clean_call, None


# ---------------------------------------------------------------------------
# Deterministic fallback resolver (§3.7 — camera intents first, then route_query)
# ---------------------------------------------------------------------------

_RE_ORBIT_STOP = re.compile(r"\b(?:stop|cancel|end)\s+(?:the\s+)?orbit\b", re.IGNORECASE)
_RE_ORBIT = re.compile(r"\borbit\b", re.IGNORECASE)
_RE_ZOOM = re.compile(r"\bzoom\s+(in|out)\b", re.IGNORECASE)
_RE_FLY_TO = re.compile(
    r"\b(?:show|go|fly|jump|take\s+me)\s+(?:me\s+)?(?:to|over|towards)?\s*"
    r"(?:the\s+)?(?P<place>[a-z0-9\u00c0-\u024f ,.'\-]{2,64})",
    re.IGNORECASE,
)


def resolve_deterministic(text: str, *, lat: float | None = None, lng: float | None = None) -> dict[str, Any]:
    """Resolve free text to a tool call without any LLM (zero-model mode, §3.7).

    Camera intents are matched first and never reach ``route_query``; everything
    else delegates to ``openclaw_routing.route_query`` verbatim (its
    ``recommended`` pick still passes through :func:`validate_and_gate` before
    execution). Camera fly-to returns the place label only — lat/lng resolution
    via ``GET /api/geocode/search`` happens at the execution layer (U4 wiring).
    """
    raw = str(text or "").strip()
    if not raw:
        return {"kind": "route_query", **_route_query(text="", lat=lat, lng=lng)}

    if _RE_ORBIT_STOP.search(raw):
        return {"kind": "client_verb", "tool": "map_orbit", "args": {"stop": True}}
    zoom = _RE_ZOOM.search(raw)
    if zoom:
        return {
            "kind": "client_verb",
            "tool": "map_zoom",
            "args": {"direction": zoom.group(1).lower()},
        }
    if _RE_ORBIT.search(raw):
        return {"kind": "client_verb", "tool": "map_orbit", "args": {}}
    fly = _RE_FLY_TO.search(raw)
    if fly:
        place = fly.group("place").strip(" .,-'")
        return {"kind": "client_verb", "tool": "map_fly_to", "args": {"label": place}}

    return {"kind": "route_query", **_route_query(text=raw, lat=lat, lng=lng)}


def _route_query(*, text: str, lat: float | None, lng: float | None) -> dict[str, Any]:
    from services.openclaw_routing import route_query

    return route_query(text=text, lat=lat, lng=lng)
