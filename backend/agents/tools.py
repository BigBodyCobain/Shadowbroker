"""Typed AI analyst tools over structured backend data.

Each tool declares a strict input schema and an authorization ``scope``
(``read`` / ``write`` / ``act``). :func:`ToolRegistry.invoke` validates inputs,
enforces the caller's granted scopes, executes the handler, wraps the result in
a predictable envelope, and writes an audit record — so every AI action is
schema-checked, authorized and auditable.

Tools reuse existing systems (the ``telemetry`` inverted-index search, the
``correlation_engine`` detectors, and the investigation store/service) rather
than reimplementing them. External OSINT text returned by read tools is wrapped
via :mod:`agents.untrusted` so it can never be interpreted as instructions.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from agents.untrusted import wrap_records
from storage import get_store

# Access tiers (the existing coarse OPENCLAW_ACCESS_TIER) map to typed scopes.
# This keeps a single operator-facing switch while giving the tool layer real
# per-tool, per-scope authorization instead of one global boolean.
SCOPE_READ = "read"
SCOPE_WRITE = "write"
SCOPE_ACT = "act"

_TIER_SCOPES = {
    "restricted": {SCOPE_READ},
    "full": {SCOPE_READ, SCOPE_WRITE, SCOPE_ACT},
}


def scopes_for_tier(tier: str) -> set[str]:
    return set(_TIER_SCOPES.get(str(tier or "restricted").strip().lower(), {SCOPE_READ}))


class ToolError(Exception):
    """Raised for validation/authorization/handler failures with a status hint."""

    def __init__(self, message: str, *, status: int = 400):
        super().__init__(message)
        self.status = status


@dataclass
class ToolParam:
    type: str  # string | integer | number | boolean | array | object
    required: bool = False
    description: str = ""
    default: Any = None

    def to_dict(self) -> dict:
        d = {"type": self.type, "required": self.required, "description": self.description}
        if self.default is not None:
            d["default"] = self.default
        return d


@dataclass
class ToolContext:
    """Who is calling and what they're allowed to do."""

    actor: str = "agent"
    granted_scopes: set[str] = field(default_factory=lambda: {SCOPE_READ})


@dataclass
class Tool:
    name: str
    scope: str
    description: str
    params: dict[str, ToolParam]
    handler: Callable[[dict, ToolContext], Any]
    returns: str = ""

    def manifest(self) -> dict:
        return {
            "name": self.name,
            "scope": self.scope,
            "description": self.description,
            "parameters": {k: v.to_dict() for k, v in self.params.items()},
            "returns": self.returns,
        }


_PY_TYPES = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _coerce(name: str, value: Any, ptype: str) -> Any:
    """Validate/coerce a single parameter value to its declared type."""
    if ptype == "string":
        return str(value)
    if ptype == "integer":
        if isinstance(value, bool):
            raise ToolError(f"'{name}' must be an integer")
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ToolError(f"'{name}' must be an integer") from exc
    if ptype == "number":
        if isinstance(value, bool):
            raise ToolError(f"'{name}' must be a number")
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise ToolError(f"'{name}' must be a number") from exc
    if ptype == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if ptype == "array":
        if not isinstance(value, (list, tuple)):
            raise ToolError(f"'{name}' must be an array")
        return list(value)
    if ptype == "object":
        if not isinstance(value, dict):
            raise ToolError(f"'{name}' must be an object")
        return value
    return value


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def manifest(self, *, granted_scopes: Optional[set[str]] = None) -> dict:
        tools = []
        for t in sorted(self._tools.values(), key=lambda x: x.name):
            entry = t.manifest()
            if granted_scopes is not None:
                entry["available"] = t.scope in granted_scopes
            tools.append(entry)
        return {
            "tools": tools,
            "scopes": {"read": SCOPE_READ, "write": SCOPE_WRITE, "act": SCOPE_ACT},
            "count": len(tools),
        }

    def validate(self, tool: Tool, args: dict) -> dict:
        args = dict(args or {})
        cleaned: dict[str, Any] = {}
        for pname, spec in tool.params.items():
            if pname in args and args[pname] is not None:
                cleaned[pname] = _coerce(pname, args[pname], spec.type)
            elif spec.required:
                raise ToolError(f"missing required parameter '{pname}'")
            elif spec.default is not None:
                cleaned[pname] = spec.default
        return cleaned

    def invoke(self, name: str, args: dict, context: ToolContext) -> dict:
        started = time.monotonic()
        tool = self._tools.get(name)
        if tool is None:
            raise ToolError(f"unknown tool '{name}'", status=404)
        if tool.scope not in context.granted_scopes:
            get_store().audit(
                context.actor, "tool_denied", tool=name, scope=tool.scope,
                detail={"reason": "scope_not_granted", "granted": sorted(context.granted_scopes)},
            )
            raise ToolError(
                f"tool '{name}' requires scope '{tool.scope}' which is not granted", status=403
            )
        cleaned = self.validate(tool, args)
        try:
            data = tool.handler(cleaned, context)
        except ToolError:
            raise
        except Exception as exc:  # handler failure -> structured error, audited
            get_store().audit(context.actor, "tool_error", tool=name, scope=tool.scope, detail={"error": str(exc)})
            raise ToolError(f"tool '{name}' failed: {exc}", status=500) from exc
        elapsed_ms = int((time.monotonic() - started) * 1000)
        get_store().audit(context.actor, "tool_invoke", tool=name, scope=tool.scope, detail={"args": list(cleaned)})
        return {
            "ok": True,
            "tool": name,
            "scope": tool.scope,
            "data": data,
            "error": None,
            "meta": {"actor": context.actor, "elapsed_ms": elapsed_ms},
        }


# --------------------------------------------------------------------------- #
# Handlers (bridge to existing systems + the investigation store)
# --------------------------------------------------------------------------- #
def _h_search_entities(args: dict, ctx: ToolContext) -> dict:
    st = get_store()
    stored = st.search_entities(query=args.get("query", ""), etype=args.get("type", ""), limit=args.get("limit", 25))
    result = {"stored_entities": [e.to_dict() for e in stored]}
    # Also surface live telemetry matches (untrusted external content wrapped).
    if args.get("include_live", True):
        try:
            from services import telemetry

            live = telemetry.find_entity(query=args.get("query", ""), limit=args.get("limit", 25))
            live_results = live.get("results", []) if isinstance(live, dict) else []
            result["live_matches"] = wrap_records(live_results, source="telemetry")
        except Exception:
            result["live_matches"] = wrap_records([], source="telemetry")
    return result


def _h_get_entity(args: dict, ctx: ToolContext) -> dict:
    st = get_store()
    ent = st.get_entity(args["entity_id"])
    if ent is None:
        raise ToolError(f"unknown entity '{args['entity_id']}'", status=404)
    return {
        "entity": ent.to_dict(),
        "observations": [o.to_dict() for o in st.observations_for_entity(args["entity_id"], limit=args.get("limit", 100))],
        "relationships": [r.to_dict() for r in st.relationships_for_entity(args["entity_id"])],
    }


def _h_get_entity_relationships(args: dict, ctx: ToolContext) -> dict:
    st = get_store()
    rels = st.relationships_for_entity(args["entity_id"])
    return {"relationships": [r.to_dict() for r in rels], "count": len(rels)}


def _h_search_events(args: dict, ctx: ToolContext) -> dict:
    st = get_store()
    events = st.search_events(
        etype=args.get("type", ""),
        classification=args.get("classification", ""),
        time_from=args.get("time_from", ""),
        time_to=args.get("time_to", ""),
        limit=args.get("limit", 100),
    )
    return {"events": [e.to_dict() for e in events], "count": len(events)}


def _h_search_observations(args: dict, ctx: ToolContext) -> dict:
    st = get_store()
    obs = st.observations_for_entity(args["entity_id"], limit=args.get("limit", 200))
    return {"observations": [o.to_dict() for o in obs], "count": len(obs)}


def _h_get_events_near_location(args: dict, ctx: ToolContext) -> dict:
    st = get_store()
    near = st.events_near(args["lat"], args["lng"], radius_km=args.get("radius_km", 100), limit=args.get("limit", 50))
    stored = [{"event": ev.to_dict(), "distance_km": d} for ev, d in near]
    result: dict = {"events": stored, "count": len(stored)}
    # Live proximity from the telemetry aggregator (external content wrapped).
    if args.get("include_live", True):
        try:
            from services import telemetry

            live = telemetry.entities_near(lat=args["lat"], lng=args["lng"], radius_km=args.get("radius_km", 100), limit=args.get("limit", 50))
            result["live_nearby"] = wrap_records(live.get("results", []) if isinstance(live, dict) else [], source="telemetry")
        except Exception:
            result["live_nearby"] = wrap_records([], source="telemetry")
    return result


def _h_get_activity_timeline(args: dict, ctx: ToolContext) -> dict:
    from services import investigation_service as svc

    inv_id = args.get("investigation_id", "")
    if not inv_id:
        raise ToolError("investigation_id is required")
    try:
        return {"timeline": svc.build_timeline(inv_id)}
    except KeyError as exc:
        raise ToolError(f"unknown investigation '{inv_id}'", status=404) from exc


def _h_compare_time_ranges(args: dict, ctx: ToolContext) -> dict:
    """Compare stored event counts between two time windows — deterministic and
    explainable ("what changed?")."""
    st = get_store()
    a = st.search_events(time_from=args["from_a"], time_to=args["to_a"], limit=1000)
    b = st.search_events(time_from=args["from_b"], time_to=args["to_b"], limit=1000)

    def _by_type(events):
        out: dict[str, int] = {}
        for e in events:
            out[e.type] = out.get(e.type, 0) + 1
        return out

    ta, tb = _by_type(a), _by_type(b)
    all_types = sorted(set(ta) | set(tb))
    delta = {t: tb.get(t, 0) - ta.get(t, 0) for t in all_types}
    return {
        "range_a": {"from": args["from_a"], "to": args["to_a"], "total": len(a), "by_type": ta},
        "range_b": {"from": args["from_b"], "to": args["to_b"], "total": len(b), "by_type": tb},
        "delta_by_type": delta,
        "net_change": len(b) - len(a),
    }


def _h_find_anomalies(args: dict, ctx: ToolContext) -> dict:
    """Run the existing correlation engine over the live telemetry snapshot and
    return explainable correlated events (each carries WHY it was grouped)."""
    from domain.correlation_adapter import correlations_to_events

    try:
        from services.fetchers._store import get_latest_data_refs_snapshot

        snapshot = get_latest_data_refs_snapshot()
    except Exception:
        snapshot = {}
    try:
        from services import correlation_engine

        raw = correlation_engine.compute_correlations(snapshot)
    except Exception as exc:
        raise ToolError(f"correlation engine unavailable: {exc}", status=503) from exc
    events = correlations_to_events(raw)
    persist = bool(args.get("persist", False)) and SCOPE_WRITE in ctx.granted_scopes
    st = get_store()
    out = []
    for ev in events:
        if persist:
            st.upsert_event(ev)
        out.append(ev.to_dict())
    return {"anomalies": out, "count": len(out), "persisted": persist}


def _h_get_evidence(args: dict, ctx: ToolContext) -> dict:
    st = get_store()
    inv_id = args.get("investigation_id", "")
    if inv_id:
        return {"evidence": [e.to_dict() for e in st.evidence_for_investigation(inv_id)]}
    if args.get("evidence_id"):
        evd = st.get_evidence(args["evidence_id"])
        if evd is None:
            raise ToolError("unknown evidence", status=404)
        return {"evidence": evd.to_dict()}
    raise ToolError("investigation_id or evidence_id required")


def _h_generate_briefing(args: dict, ctx: ToolContext) -> dict:
    from services import investigation_service as svc

    try:
        return svc.generate_briefing(args["investigation_id"])
    except KeyError as exc:
        raise ToolError("unknown investigation", status=404) from exc


# -- write-scope handlers ---------------------------------------------------- #
def _h_create_investigation(args: dict, ctx: ToolContext) -> dict:
    from services import investigation_service as svc

    inv = svc.create_investigation(
        title=args["title"],
        question=args.get("question", ""),
        description=args.get("description", ""),
        author=ctx.actor,
        tags=args.get("tags", []),
    )
    return inv.to_dict()


def _h_update_investigation(args: dict, ctx: ToolContext) -> dict:
    from services import investigation_service as svc

    fields = {k: v for k, v in args.items() if k != "investigation_id"}
    try:
        inv = svc.update_investigation(args["investigation_id"], actor=ctx.actor, **fields)
    except KeyError as exc:
        raise ToolError("unknown investigation", status=404) from exc
    return inv.to_dict()


def _h_add_evidence(args: dict, ctx: ToolContext) -> dict:
    from services import investigation_service as svc

    try:
        evd = svc.add_evidence(
            args["investigation_id"],
            kind=args.get("kind", "observation"),
            title=args["title"],
            description=args.get("description", ""),
            classification=args.get("classification", "raw_observation"),
            provenance=args.get("provenance"),
            confidence=args.get("confidence"),
            ref_type=args.get("ref_type", ""),
            ref_id=args.get("ref_id", ""),
            actor=ctx.actor,
        )
    except KeyError as exc:
        raise ToolError("unknown investigation", status=404) from exc
    return evd.to_dict()


def _h_add_event(args: dict, ctx: ToolContext) -> dict:
    from services import investigation_service as svc

    try:
        ev = svc.add_event(
            args.get("investigation_id"),
            type=args.get("type", "generic"),
            title=args["title"],
            summary=args.get("summary", ""),
            classification=args.get("classification", "derived_event"),
            occurred_at=args.get("occurred_at"),
            lat=args.get("lat"),
            lng=args.get("lng"),
            severity=args.get("severity", "info"),
            explanation=args.get("explanation", ""),
            actor=ctx.actor,
        )
    except KeyError as exc:
        raise ToolError("unknown investigation", status=404) from exc
    return ev.to_dict()


def _h_create_hypothesis(args: dict, ctx: ToolContext) -> dict:
    from services import investigation_service as svc

    try:
        hyp = svc.create_hypothesis(
            args["investigation_id"],
            statement=args["statement"],
            supporting_evidence_ids=args.get("supporting_evidence_ids", []),
            contradicting_evidence_ids=args.get("contradicting_evidence_ids", []),
            author=ctx.actor,
        )
    except KeyError as exc:
        raise ToolError("unknown investigation", status=404) from exc
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    return hyp.to_dict()


# --------------------------------------------------------------------------- #
# Registry assembly
# --------------------------------------------------------------------------- #
def _build_registry() -> ToolRegistry:
    r = ToolRegistry()
    P = ToolParam

    r.register(Tool(
        "search_entities", SCOPE_READ,
        "Search tracked entities (stored + live telemetry). External live matches are returned as untrusted data.",
        {"query": P("string", False, "Free-text query"),
         "type": P("string", False, "Entity type filter, e.g. aircraft, vessel"),
         "limit": P("integer", False, "Max results", 25),
         "include_live": P("boolean", False, "Also search live telemetry", True)},
        _h_search_entities,
        returns="{stored_entities:[...], live_matches:{_untrusted_external_data, records}}",
    ))
    r.register(Tool(
        "get_entity", SCOPE_READ,
        "Get one entity with its observations and relationships.",
        {"entity_id": P("string", True, "Entity id"), "limit": P("integer", False, "Max observations", 100)},
        _h_get_entity,
    ))
    r.register(Tool(
        "get_entity_relationships", SCOPE_READ, "Get relationships (graph edges) for an entity.",
        {"entity_id": P("string", True, "Entity id")}, _h_get_entity_relationships,
    ))
    r.register(Tool(
        "search_events", SCOPE_READ, "Search derived events with type/classification/time filters.",
        {"type": P("string", False, "Event type"),
         "classification": P("string", False, "raw_observation|derived_event|analysis|hypothesis"),
         "time_from": P("string", False, "ISO lower bound on occurred_at"),
         "time_to": P("string", False, "ISO upper bound on occurred_at"),
         "limit": P("integer", False, "Max results", 100)},
        _h_search_events,
    ))
    r.register(Tool(
        "search_observations", SCOPE_READ, "List raw observations for an entity.",
        {"entity_id": P("string", True, "Entity id"), "limit": P("integer", False, "Max results", 200)},
        _h_search_observations,
    ))
    r.register(Tool(
        "get_events_near_location", SCOPE_READ,
        "Find events (and live telemetry) near a point. Live results returned as untrusted data.",
        {"lat": P("number", True, "Latitude"), "lng": P("number", True, "Longitude"),
         "radius_km": P("number", False, "Radius km", 100), "limit": P("integer", False, "Max results", 50),
         "include_live": P("boolean", False, "Also include live telemetry", True)},
        _h_get_events_near_location,
    ))
    r.register(Tool(
        "get_activity_timeline", SCOPE_READ, "Chronological timeline for an investigation.",
        {"investigation_id": P("string", True, "Investigation id")}, _h_get_activity_timeline,
    ))
    r.register(Tool(
        "compare_time_ranges", SCOPE_READ,
        "Compare stored event activity between two time windows (what changed?).",
        {"from_a": P("string", True, "Range A start ISO"), "to_a": P("string", True, "Range A end ISO"),
         "from_b": P("string", True, "Range B start ISO"), "to_b": P("string", True, "Range B end ISO")},
        _h_compare_time_ranges,
    ))
    r.register(Tool(
        "find_anomalies", SCOPE_READ,
        "Run the correlation engine over live telemetry and return explainable correlated events (each states why it was grouped). Set persist=true (needs write scope) to store them.",
        {"persist": P("boolean", False, "Persist anomalies as events (requires write scope)", False)},
        _h_find_anomalies,
    ))
    r.register(Tool(
        "get_evidence", SCOPE_READ, "Get evidence for an investigation, or a single evidence item.",
        {"investigation_id": P("string", False, "Investigation id"), "evidence_id": P("string", False, "Evidence id")},
        _h_get_evidence,
    ))
    r.register(Tool(
        "generate_briefing", SCOPE_READ,
        "Generate a structured, evidence-first briefing that keeps facts and inferences separate.",
        {"investigation_id": P("string", True, "Investigation id")}, _h_generate_briefing,
    ))

    # write scope
    r.register(Tool(
        "create_investigation", SCOPE_WRITE, "Create a new investigation workspace.",
        {"title": P("string", True, "Title"), "question": P("string", False, "Central question"),
         "description": P("string", False, "Description"), "tags": P("array", False, "Tags")},
        _h_create_investigation,
    ))
    r.register(Tool(
        "update_investigation", SCOPE_WRITE, "Update an investigation's fields.",
        {"investigation_id": P("string", True, "Investigation id"), "title": P("string", False, ""),
         "question": P("string", False, ""), "description": P("string", False, ""),
         "status": P("string", False, "open|active|on_hold|closed|archived")},
        _h_update_investigation,
    ))
    r.register(Tool(
        "add_event", SCOPE_WRITE, "Record a derived event (optionally attached to an investigation).",
        {"investigation_id": P("string", False, "Investigation id"), "type": P("string", False, "Event type"),
         "title": P("string", True, "Title"), "summary": P("string", False, ""),
         "classification": P("string", False, "derived_event|analysis"),
         "occurred_at": P("string", False, "ISO time"), "lat": P("number", False, ""), "lng": P("number", False, ""),
         "severity": P("string", False, "info|low|medium|high|critical"), "explanation": P("string", False, "Why")},
        _h_add_event,
    ))
    r.register(Tool(
        "add_evidence", SCOPE_WRITE, "Attach evidence (with provenance & classification) to an investigation.",
        {"investigation_id": P("string", True, "Investigation id"), "title": P("string", True, "Title"),
         "kind": P("string", False, "observation|event|source_document|correlation|imagery|signal"),
         "description": P("string", False, ""),
         "classification": P("string", False, "raw_observation|derived_event|analysis|hypothesis"),
         "provenance": P("object", False, "{source_name, source_url, observed_at, method}"),
         "confidence": P("object", False, "Confidence object"),
         "ref_type": P("string", False, ""), "ref_id": P("string", False, "")},
        _h_add_evidence,
    ))
    r.register(Tool(
        "create_hypothesis", SCOPE_WRITE,
        "Create a hypothesis (always classified as inference; confidence derived from linked evidence).",
        {"investigation_id": P("string", True, "Investigation id"), "statement": P("string", True, "Hypothesis statement"),
         "supporting_evidence_ids": P("array", False, "Evidence ids that support"),
         "contradicting_evidence_ids": P("array", False, "Evidence ids that contradict")},
        _h_create_hypothesis,
    ))
    return r


_REGISTRY: Optional[ToolRegistry] = None


def get_registry() -> ToolRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _build_registry()
    return _REGISTRY
