"""Deterministic OpenClaw routing — intent → fastest command.

Keeps expensive fuzzy scans and full-layer dumps out of the default agent path.
"""

from __future__ import annotations

import re
from typing import Any

EXPENSIVE_COMMANDS = frozenset({
    "search_telemetry",
    "get_telemetry",
    "get_slow_telemetry",
    "get_report",
})

EXPENSIVE_GATE_MESSAGE = (
    "expensive command blocked — use route_query, find_entity, run_playbook, or targeted reads. "
    "Pass confirm_expensive=true only when fuzzy search or full dumps are intentional."
)

LATENCY_TIER_MS: dict[str, int] = {
    "channel_status": 5,
    "route_query": 5,
    "get_summary": 10,
    "what_changed": 15,
    "search_news": 15,
    "find_flights": 25,
    "find_ships": 25,
    "find_entity": 30,
    "entities_near": 30,
    "brief_area": 30,
    "get_layer_slice": 50,
    "correlate_entity": 15,
    "get_entity_trail": 20,
    "get_entity_profile": 35,
    "entity_expand": 40,
    "osint_lookup": 200,
    "run_playbook": 120,
    "gt_risk_heatmap": 20,
    "gt_dossier": 25,
    "gt_analyze": 80,
    "gt_backtest": 120,
    "gt_rolling_freeze": 30,
    "gt_rolling_label": 20,
    "gt_rolling_backtest": 30,
    "gt_micro_rolling": 20,
    "infonet_status": 20,
    "list_gates": 15,
    "read_gate_messages": 40,
    "poll_dms": 80,
    "ensure_infonet_ready": 120000,
    "join_infonet_swarm": 90000,
    "post_gate_message": 15000,
    "cast_vote": 5000,
    "send_dm": 20000,
    "search_telemetry": 8000,
    "get_telemetry": 3500,
    "get_slow_telemetry": 1500,
    "get_report": 5000,
}

RE_N_NUMBER = re.compile(r"\bN\d{1,5}[A-Z]{0,2}\b", re.I)
RE_CALLSIGN = re.compile(r"\b[A-Z]{2,4}\d{1,4}[A-Z]?\b")
RE_MMSI = re.compile(r"\b\d{9}\b")
RE_CVE = re.compile(r"\bCVE-\d{4}-\d+\b", re.I)
RE_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
RE_DOMAIN = re.compile(
    r"\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:[a-z]{2,})\b",
    re.I,
)

KNOWN_CALLSIGNS = frozenset({
    "AF1", "AF2", "EXEC1", "EXEC2", "SAM", "STALK52", "SPAR19", "SPAR20",
})

PLAYBOOKS: dict[str, dict[str, Any]] = {
    "hot_snapshot": {
        "description": "Summary + hot layers + what changed (one batch)",
        "batch": [
            {"cmd": "get_summary", "args": {"compact": True}},
            {
                "cmd": "get_layer_slice",
                "args": {
                    "layers": [
                        "news",
                        "telegram_osint",
                        "military_flights",
                        "private_jets",
                        "earthquakes",
                    ],
                    "limit_per_layer": 10,
                    "compact": True,
                },
            },
            {"cmd": "what_changed", "args": {"compact": True}},
        ],
    },
    "status_check": {
        "description": "Channel health + layer counts",
        "batch": [
            {"cmd": "channel_status", "args": {}},
            {"cmd": "get_summary", "args": {"compact": True}},
        ],
    },
    "morning_brief": {
        "description": "Operator morning digest layers",
        "batch": [
            {"cmd": "get_summary", "args": {"compact": True}},
            {"cmd": "what_changed", "args": {"compact": True}},
            {
                "cmd": "get_layer_slice",
                "args": {
                    "layers": [
                        "news",
                        "telegram_osint",
                        "gdelt",
                        "earthquakes",
                        "crowdthreat",
                        "military_flights",
                    ],
                    "limit_per_layer": 15,
                    "compact": True,
                },
            },
        ],
    },
    "monitor_heartbeat": {
        "description": "Low-latency monitor poll (replaces full telemetry pull)",
        "batch": [
            {"cmd": "what_changed", "args": {"compact": True}},
            {
                "cmd": "get_layer_slice",
                "args": {
                    "layers": [
                        "military_flights",
                        "ships",
                        "earthquakes",
                        "liveuamap",
                        "crowdthreat",
                        "uap_sightings",
                        "firms_fires",
                        "gps_jamming",
                        "wastewater",
                    ],
                    "limit_per_layer": 200,
                    "compact": True,
                },
            },
        ],
    },
}


def routing_manifest() -> dict[str, Any]:
    """Machine-readable routing hints for /api/ai/capabilities."""
    return {
        "default_read": "find_entity",
        "preferred_entry": "route_query",
        "client_wrapper": "ShadowBrokerClient.ask",
        "batch_playbook": "run_playbook",
        "last_resort": "search_telemetry",
        "expensive_commands": sorted(EXPENSIVE_COMMANDS),
        "latency_tier_ms": LATENCY_TIER_MS,
        "anti_patterns": [
            "search_telemetry for known tail numbers, callsigns, owners, or MMSI",
            "get_telemetry for routine reads — use get_layer_slice or run_playbook hot_snapshot",
            "sequential send_command loops — use send_batch or run_playbook",
            "/api/health for liveness — use channel_status",
            "empty layers: [] on get_layer_slice — pass explicit layer names",
        ],
        "recipes": [
            {
                "intent": "natural language question",
                "use": "route_query → recommended cmd, or ShadowBrokerClient.ask()",
            },
            {
                "intent": "known person/aircraft",
                "use": "get_entity_profile(query=...) or find_entity(query=...)",
            },
            {
                "intent": "news / telegram topic",
                "use": "search_news(query=...)",
            },
            {
                "intent": "near a point",
                "use": "entities_near or brief_area",
            },
            {
                "intent": "hot snapshot",
                "use": "run_playbook(name=hot_snapshot)",
            },
            {
                "intent": "post to infonet gate / join swarm",
                "use": "ensure_infonet_ready then post_gate_message (full tier)",
            },
            {
                "intent": "read encrypted gate traffic",
                "use": "read_gate_messages(gate_id=infonet, decrypt=true)",
            },
            {
                "intent": "dm another node",
                "use": "send_dm(peer_id=..., plaintext=...) (full tier)",
            },
        ],
        "playbooks": {
            name: {"description": spec.get("description", "")}
            for name, spec in PLAYBOOKS.items()
        },
        "agent_surface": {
            "primary": ["ask", "send_batch", "channel_status"],
            "writes": [
                "place_pin",
                "add_watch",
                "inject_data",
                "place_analysis_zone",
                "ensure_infonet_ready",
                "post_gate_message",
                "cast_vote",
                "send_dm",
            ],
            "infonet_reads": [
                "infonet_status",
                "list_gates",
                "read_gate_messages",
                "poll_dms",
            ],
        },
    }


def requires_expensive_confirm(cmd: str, args: dict[str, Any] | None) -> bool:
    if cmd not in EXPENSIVE_COMMANDS:
        return False
    if isinstance(args, dict) and args.get("confirm_expensive") is True:
        return False
    return True


def _compact_args(args: dict[str, Any], *, compact: bool) -> dict[str, Any]:
    out = dict(args)
    if compact and "compact" not in out:
        out["compact"] = True
    return out


def _estimate_ms(cmd: str) -> int:
    return int(LATENCY_TIER_MS.get(cmd, 100))


def _news_query(text: str) -> str:
    cleaned = text
    for prefix in (
        "news about",
        "news on",
        "telegram",
        "headlines about",
        "headlines on",
        "latest on",
        "search news for",
    ):
        if cleaned.lower().startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
    return cleaned.strip(" ?.")


def _gt_region_hint(text: str) -> str:
    lowered = str(text or "").lower()
    hints = (
        "ukraine",
        "middle east",
        "eastern europe",
        "baltics",
        "israel",
        "iran",
        "russia",
        "china",
        "europe",
        "united kingdom",
        "uk",
        "usa",
        "united states",
    )
    for hint in hints:
        if hint in lowered:
            return "uk" if hint == "united kingdom" else hint
    match = re.search(r"\bon\s+([a-z][a-z\s]{2,30})\b", lowered)
    if match:
        return match.group(1).strip()
    return ""


def route_query(
    text: str = "",
    *,
    lat: float | None = None,
    lng: float | None = None,
    radius_km: float = 50,
    compact: bool = True,
) -> dict[str, Any]:
    """Map natural-language intent to the fastest command (no LLM)."""
    raw = str(text or "").strip()
    lowered = raw.lower()
    avoid = ["search_telemetry", "get_telemetry", "get_slow_telemetry"]
    alternates: list[dict[str, Any]] = []

    if not raw and lat is not None and lng is not None:
        recommended = {
            "cmd": "brief_area",
            "args": _compact_args(
                {"lat": lat, "lng": lng, "radius_km": radius_km},
                compact=compact,
            ),
        }
        return {
            "intent": "area_brief",
            "recommended": recommended,
            "alternates": [{"cmd": "entities_near", "args": recommended["args"]}],
            "avoid": avoid,
            "estimated_ms": _estimate_ms("brief_area"),
        }

    if not raw:
        recommended = {"cmd": "get_summary", "args": _compact_args({}, compact=compact)}
        return {
            "intent": "discovery",
            "recommended": recommended,
            "alternates": [{"cmd": "channel_status", "args": {}}],
            "avoid": avoid,
            "estimated_ms": _estimate_ms("get_summary"),
        }

    cve_match = RE_CVE.search(raw)
    if cve_match:
        recommended = {
            "cmd": "osint_lookup",
            "args": _compact_args({"tool": "cve", "cve": cve_match.group(0).upper()}, compact=compact),
        }
        return _route_result("cve_lookup", recommended, avoid, alternates)

    ip_match = RE_IPV4.search(raw)
    if ip_match and ("ip" in lowered or "address" in lowered or lowered.count(".") >= 3):
        recommended = {
            "cmd": "osint_lookup",
            "args": _compact_args({"tool": "ip", "ip": ip_match.group(0)}, compact=compact),
        }
        alternates.append({"cmd": "entity_expand", "args": {"type": "ip", "id": ip_match.group(0)}})
        return _route_result("ip_lookup", recommended, avoid, alternates)

    if "whois" in lowered or ("dns" in lowered and RE_DOMAIN.search(raw)):
        domain = (RE_DOMAIN.search(raw) or re.search(r"\b([a-z0-9-]+\.[a-z]{2,})\b", raw, re.I))
        tool = "whois" if "whois" in lowered else "dns"
        domain_value = domain.group(0) if domain else raw
        recommended = {
            "cmd": "osint_lookup",
            "args": _compact_args({"tool": tool, "domain": domain_value}, compact=compact),
        }
        return _route_result("domain_lookup", recommended, avoid, alternates)

    if "sanction" in lowered or "ofac" in lowered:
        recommended = {
            "cmd": "osint_lookup",
            "args": _compact_args({"tool": "sanctions", "query": raw}, compact=compact),
        }
        return _route_result("sanctions_lookup", recommended, avoid, alternates)

    mmsi_match = RE_MMSI.search(raw)
    if mmsi_match and any(k in lowered for k in ("mmsi", "ship", "vessel", "yacht", "boat", "maritime")):
        recommended = {
            "cmd": "find_ships",
            "args": _compact_args({"mmsi": mmsi_match.group(0)}, compact=compact),
        }
        alternates.append({"cmd": "find_entity", "args": {"mmsi": mmsi_match.group(0), "entity_type": "ship"}})
        return _route_result("maritime_identifier", recommended, avoid, alternates)

    n_match = RE_N_NUMBER.search(raw)
    if n_match:
        reg = n_match.group(0).upper()
        recommended = {
            "cmd": "find_flights",
            "args": _compact_args({"registration": reg}, compact=compact),
        }
        alternates.append({"cmd": "find_entity", "args": {"registration": reg, "entity_type": "aircraft"}})
        return _route_result("tail_number", recommended, avoid, alternates)

    # callsign tokens
    tokens = re.findall(r"\b[A-Z0-9]{2,8}\b", raw.upper())
    for token in tokens:
        if token in KNOWN_CALLSIGNS or RE_CALLSIGN.fullmatch(token):
            recommended = {
                "cmd": "find_flights",
                "args": _compact_args({"callsign": token}, compact=compact),
            }
            alternates.append({"cmd": "find_entity", "args": {"callsign": token, "entity_type": "aircraft"}})
            return _route_result("callsign", recommended, avoid, alternates)

    if any(k in lowered for k in ("news", "telegram", "headline", "headlines", "gdelt")):
        recommended = {
            "cmd": "search_news",
            "args": _compact_args({"query": _news_query(raw), "limit": 10}, compact=compact),
        }
        alternates.append({
            "cmd": "get_layer_slice",
            "args": {"layers": ["telegram_osint", "news"], "limit_per_layer": 10, "compact": compact},
        })
        return _route_result("news_search", recommended, avoid, alternates)

    if any(
        k in lowered
        for k in (
            "gt backtest",
            "backtest gt",
            "historical backtest",
            "wilson confidence",
            "confidence rate",
            "gt benchmark",
            "validate gt",
        )
    ):
        tune = any(k in lowered for k in ("tune", "grid search", "optimize threshold"))
        expanded = "base" not in lowered
        recommended = {
            "cmd": "gt_backtest",
            "args": _compact_args(
                {
                    "expanded": expanded,
                    "tune": tune,
                    "target_confidence": 0.95,
                },
                compact=compact,
            ),
        }
        alternates.append({"cmd": "gt_risk_heatmap", "args": {}})
        return _route_result("gt_backtest", recommended, avoid, alternates)

    if any(
        k in lowered
        for k in (
            "rolling backtest",
            "rolling validation",
            "weekly validation",
            "operational validation",
            "operational backtest",
            "week over week",
            "week-over-week",
            "gt rolling",
            "rolling gt",
            "weekly gt",
            "weekly gt score",
            "gt weekly",
            "gt snapshot",
            "freeze weekly gt",
        )
    ):
        micro = any(
            k in lowered
            for k in (
                "3 day",
                "3-day",
                "three day",
                "micro rolling",
                "rolling average",
                "ignition",
                "micro gt",
            )
        )
        freeze = any(
            k in lowered
            for k in ("freeze", "gt snapshot", "weekly snapshot", "capture week")
        )
        label = any(k in lowered for k in ("label", "outcome", "escalation"))
        if micro and not freeze and not label:
            recommended = {
                "cmd": "gt_micro_rolling",
                "args": _compact_args({"window_days": 3}, compact=compact),
            }
            intent = "gt_micro_rolling"
        elif freeze:
            recommended = {
                "cmd": "gt_rolling_freeze",
                "args": _compact_args({"force": "force" in lowered}, compact=compact),
            }
            intent = "gt_rolling_freeze"
        elif label:
            recommended = {
                "cmd": "gt_rolling_label",
                "args": _compact_args({}, compact=compact),
            }
            intent = "gt_rolling_label"
        else:
            recommended = {
                "cmd": "gt_rolling_backtest",
                "args": _compact_args({"weeks": 8, "target_confidence": 0.80}, compact=compact),
            }
            intent = "gt_rolling_backtest"
        alternates.append({"cmd": "gt_micro_rolling", "args": {"window_days": 3}})
        alternates.append({"cmd": "gt_backtest", "args": {"expanded": True, "compact": True}})
        return _route_result(intent, recommended, avoid, alternates)

    if any(
        k in lowered
        for k in (
            "3 day average",
            "3-day average",
            "rolling 3 day",
            "micro risk",
            "risk ignition",
        )
    ):
        recommended = {
            "cmd": "gt_micro_rolling",
            "args": _compact_args({"window_days": 3}, compact=compact),
        }
        alternates.append({"cmd": "gt_rolling_backtest", "args": {"weeks": 8}})
        return _route_result("gt_micro_rolling", recommended, avoid, alternates)

    if any(
        k in lowered
        for k in (
            "gt analysis",
            "game theoretic",
            "game-theoretic",
            "strategic risk",
            "early warning",
            "risk heatmap",
            "costly signal",
            "gt rationale",
        )
    ):
        region_hint = _gt_region_hint(raw)
        if region_hint and any(k in lowered for k in ("dossier", "rationale", "scenario")):
            recommended = {
                "cmd": "gt_dossier",
                "args": _compact_args({"region": region_hint}, compact=compact),
            }
            alternates.append({"cmd": "gt_risk_heatmap", "args": {}})
            return _route_result("gt_dossier", recommended, avoid, alternates)
        recommended = {
            "cmd": "gt_analyze",
            "args": _compact_args(
                {"refresh": True, "region": region_hint} if region_hint else {"refresh": True},
                compact=compact,
            ),
        }
        alternates.append({"cmd": "gt_risk_heatmap", "args": {}})
        return _route_result("gt_analyze", recommended, avoid, alternates)

    if lat is not None and lng is not None and any(
        k in lowered for k in ("near", "around", "within", "radius", "brief", "aoi")
    ):
        recommended = {
            "cmd": "brief_area",
            "args": _compact_args(
                {"lat": lat, "lng": lng, "radius_km": radius_km, "query": raw},
                compact=compact,
            ),
        }
        alternates.append({
            "cmd": "entities_near",
            "args": {"lat": lat, "lng": lng, "radius_km": radius_km, "compact": compact},
        })
        return _route_result("area_brief", recommended, avoid, alternates)

    if any(k in lowered for k in ("what changed", "updates", "delta", "since last")):
        recommended = {"cmd": "what_changed", "args": _compact_args({}, compact=compact)}
        return _route_result("incremental_poll", recommended, avoid, alternates)

    if any(k in lowered for k in ("summary", "status", "layers populated", "what data")):
        recommended = {"cmd": "get_summary", "args": _compact_args({}, compact=compact)}
        alternates.append({"cmd": "channel_status", "args": {}})
        return _route_result("discovery", recommended, avoid, alternates)

    if any(k in lowered for k in ("recon", "whois", "dns lookup", "cve", "mac address")):
        recommended = {
            "cmd": "osint_tools",
            "args": {},
        }
        return _route_result("recon_discovery", recommended, avoid, alternates)

    entity_type = ""
    if any(k in lowered for k in ("ship", "vessel", "yacht", "boat", "maritime", "carrier")):
        entity_type = "ship"
    elif any(k in lowered for k in ("jet", "plane", "flight", "aircraft", "helicopter", "tail")):
        entity_type = "aircraft"

    owner_hint = ""
    if any(k in lowered for k in ("owner", "operated by", "'s jet", "'s yacht", "belongs to")):
        owner_hint = raw
        for phrase in ("where is", "find", "track", "locate", "jet", "yacht", "plane", "flight", "ship"):
            owner_hint = re.sub(rf"\b{phrase}\b", "", owner_hint, flags=re.I).strip()

    entity_args: dict[str, Any] = {"query": raw, "compact": compact}
    if entity_type:
        entity_args["entity_type"] = entity_type
    if owner_hint and len(owner_hint) >= 3:
        entity_args["owner"] = owner_hint

    recommended = {
        "cmd": "find_entity",
        "args": _compact_args(entity_args, compact=compact),
    }
    alternates = [
        {"cmd": "search_news", "args": {"query": raw, "limit": 10, "compact": compact}},
    ]
    if any(k in lowered for k in ("near", "around")):
        alternates.append({
            "cmd": "search_telemetry",
            "args": {"query": raw, "limit": 10, "confirm_expensive": True, "compact": compact},
        })

    return _route_result("entity_lookup", recommended, avoid, alternates)


def _route_result(
    intent: str,
    recommended: dict[str, Any],
    avoid: list[str],
    alternates: list[dict[str, Any]],
) -> dict[str, Any]:
    cmd = str(recommended.get("cmd", ""))
    return {
        "intent": intent,
        "recommended": recommended,
        "alternates": alternates,
        "avoid": avoid,
        "estimated_ms": _estimate_ms(cmd),
    }


def plan_playbook(name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolve a named playbook to a command batch."""
    playbook = str(name or "").strip().lower()
    params = dict(args or {})
    if not playbook:
        return {"ok": False, "detail": "playbook name required"}

    if playbook == "track_snapshot":
        query = str(params.get("query", "") or params.get("name", "") or "").strip()
        if not query:
            return {"ok": False, "detail": "track_snapshot requires query"}
        return {
            "ok": True,
            "playbook": playbook,
            "description": "Resolve entity and return full movement profile",
            "batch": [
                {
                    "cmd": "get_entity_profile",
                    "args": {
                        "query": query,
                        "entity_type": params.get("entity_type", ""),
                        "compact": True,
                        "include_datalink": True,
                        "include_nearby_context": True,
                    },
                }
            ],
        }

    if playbook == "jet_recon":
        query = str(params.get("query", "") or params.get("registration", "") or params.get("owner", "") or "").strip()
        if not query:
            return {"ok": False, "detail": "jet_recon requires query, registration, or owner"}
        return {
            "ok": True,
            "playbook": playbook,
            "description": "VIP/aircraft dossier: profile + correlation evidence",
            "batch": [
                {
                    "cmd": "get_entity_profile",
                    "args": {
                        "query": query,
                        "entity_type": params.get("entity_type", "aircraft"),
                        "registration": params.get("registration", ""),
                        "icao24": params.get("icao24", ""),
                        "owner": params.get("owner", ""),
                        "compact": True,
                        "include_datalink": True,
                        "include_news": True,
                    },
                },
                {
                    "cmd": "correlate_entity",
                    "args": {
                        "query": query,
                        "entity_type": params.get("entity_type", "aircraft"),
                        "registration": params.get("registration", ""),
                        "icao24": params.get("icao24", ""),
                        "owner": params.get("owner", ""),
                        "radius_km": params.get("radius_km", 150),
                        "compact": True,
                    },
                },
            ],
        }

    if playbook == "area_brief":
        lat = params.get("lat")
        lng = params.get("lng")
        if lat is None or lng is None:
            return {"ok": False, "detail": "area_brief requires lat and lng"}
        return {
            "ok": True,
            "playbook": playbook,
            "description": "Brief an area of interest",
            "batch": [
                {
                    "cmd": "brief_area",
                    "args": {
                        "lat": lat,
                        "lng": lng,
                        "radius_km": params.get("radius_km", 50),
                        "query": params.get("query", ""),
                        "compact": True,
                    },
                }
            ],
        }

    if playbook == "entity_recon":
        query = str(params.get("query", "") or params.get("ip", "") or "").strip()
        ip_match = RE_IPV4.search(query)
        if not ip_match:
            return {"ok": False, "detail": "entity_recon requires an IP in query"}
        return {
            "ok": True,
            "playbook": playbook,
            "description": "IP recon + entity graph",
            "batch": [
                {"cmd": "osint_lookup", "args": {"tool": "ip", "ip": ip_match.group(0), "compact": True}},
                {"cmd": "entity_expand", "args": {"type": "ip", "id": ip_match.group(0)}},
            ],
        }

    spec = PLAYBOOKS.get(playbook)
    if not spec:
        known = sorted(PLAYBOOKS) + ["track_snapshot", "jet_recon", "area_brief", "entity_recon"]
        return {"ok": False, "detail": f"unknown playbook: {playbook}", "known": known}

    return {
        "ok": True,
        "playbook": playbook,
        "description": spec.get("description", ""),
        "batch": [dict(item) for item in spec.get("batch", [])],
    }
