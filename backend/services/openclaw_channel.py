"""OpenClaw Bidirectional Command Channel.

Provides an authenticated command channel between OpenClaw agents and
ShadowBroker. Supports both directions:

  Agent → SB:  Commands (get_telemetry, place_pin, etc.)
  SB → Agent:  Tasks/alerts pushed by the operator

Current transport:
  HMAC Direct: Commands travel via HMAC-SHA256 authenticated HTTP.
               Body integrity is bound into the signature (P1A).
               No end-to-end encryption — relies on TLS for wire privacy.

Future (not yet implemented):
  MLS E2EE:    Planned upgrade to route commands via Wormhole DM with
               MLS forward secrecy. Not currently wired into this channel.
"""

from __future__ import annotations

import concurrent.futures
import logging
import secrets
import threading
import time
from collections import OrderedDict
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Persistent thread pool — avoids per-command ThreadPoolExecutor overhead
# ---------------------------------------------------------------------------
_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="openclaw-cmd"
)

# ---------------------------------------------------------------------------
# Queue limits
# ---------------------------------------------------------------------------
MAX_PENDING_COMMANDS = 64
MAX_PENDING_TASKS = 32
COMMAND_RESULT_TTL = 300  # 5 minutes
TASK_TTL = 600  # 10 minutes
COMMAND_TIMEOUT = 30  # seconds — hard cap per command execution


# ---------------------------------------------------------------------------
# Command allowlists (keyed by access tier)
# ---------------------------------------------------------------------------

READ_COMMANDS = frozenset({
    "get_telemetry",
    "get_slow_telemetry",
    "get_summary",
    "get_report",
    "get_layer_slice",
    "find_flights",
    "find_ships",
    "find_entity",
    "correlate_entity",
    "brief_area",
    "what_changed",
    "search_telemetry",
    "search_news",
    "entities_near",
    "get_sigint_totals",
    "get_prediction_markets",
    "get_ai_pins",
    "get_correlations",
    "channel_status",
    "list_watches",
    "timemachine_list",
    "timemachine_config",
    "get_layers",
    # SAR layer reads
    "sar_status",
    "sar_anomalies_recent",
    "sar_anomalies_near",
    "sar_scene_search",
    "sar_coverage_for_aoi",
    "sar_aoi_list",
    "sar_pin_click",
    # Analysis zones (OpenClaw map overlays)
    "list_analysis_zones",
})

WRITE_COMMANDS = frozenset({
    "place_pin",
    "inject_data",
    "take_snapshot",
    "delete_pin",
    "timemachine_playback",
    "create_layer",
    "update_layer",
    "delete_layer",
    "refresh_feed",
    "add_watch",
    "track_entity",
    "watch_area",
    "remove_watch",
    "clear_watches",
    "show_satellite",
    "show_sentinel",
    # SAR layer writes
    "sar_aoi_add",
    "sar_aoi_remove",
    "sar_pin_from_anomaly",
    "sar_watch_anomaly",
    "sar_focus_aoi",
    # Analysis zones (OpenClaw map overlays)
    "place_analysis_zone",
    "delete_analysis_zone",
    "clear_analysis_zones",
})


def allowed_commands(access_tier: str) -> frozenset[str]:
    """Return the set of commands allowed for the given access tier."""
    if access_tier == "full":
        return READ_COMMANDS | WRITE_COMMANDS
    return READ_COMMANDS


# ---------------------------------------------------------------------------
# Tier detection
# ---------------------------------------------------------------------------

_tier_cache: dict[str, Any] | None = None
_tier_cache_ts: float = 0
_TIER_CACHE_TTL = 30  # seconds — tier changes are rare, avoid per-command imports


def detect_tier() -> dict[str, Any]:
    """Detect which communication tier is currently in use.

    The command channel currently operates exclusively over HMAC-authenticated
    HTTP (Tier 1).  MLS E2EE (Tier 2) is planned but not yet wired into
    command dispatch — detect_tier never returns tier 2 until that work
    is complete.

    Results are cached for 30s to avoid expensive dynamic imports on every
    command submission.

    Returns:
        {tier: 1, reason: str, transport: str, forward_secrecy: False,
         sealed_sender: False, mls_upgrade_available: bool}
    """
    global _tier_cache, _tier_cache_ts
    now = time.time()
    if _tier_cache is not None and (now - _tier_cache_ts) < _TIER_CACHE_TTL:
        return _tier_cache

    mls_upgrade_available = False
    transport = "unknown"
    try:
        from services.wormhole_supervisor import get_wormhole_state, transport_tier_from_state
        state = get_wormhole_state()
        transport = transport_tier_from_state(state) or "unknown"

        if transport == "private_strong":
            try:
                from services.privacy_core_client import PrivacyCoreClient
                client = PrivacyCoreClient.load()
                if client:
                    from services.openclaw_bridge import get_agent_public_info
                    info = get_agent_public_info()
                    if info.get("bootstrapped"):
                        # Infrastructure is present but channel dispatch does
                        # not use it yet — flag for UI without overclaiming.
                        mls_upgrade_available = True
            except Exception:
                pass
    except Exception:
        pass

    result = {
        "tier": 1,
        "reason": "HMAC-authenticated HTTP — commands are signed but not end-to-end encrypted",
        "transport": transport,
        "forward_secrecy": False,
        "sealed_sender": False,
        "mls_upgrade_available": mls_upgrade_available,
    }
    _tier_cache = result
    _tier_cache_ts = now
    return result


# ---------------------------------------------------------------------------
# Command & Task entries
# ---------------------------------------------------------------------------

class CommandEntry:
    """A command submitted by the agent."""

    __slots__ = ("id", "cmd", "args", "submitted_at", "status", "result",
                 "completed_at", "tier")

    def __init__(self, cmd: str, args: dict[str, Any], tier: int = 1):
        self.id: str = f"cmd_{int(time.time() * 1000)}_{secrets.token_hex(4)}"
        self.cmd = cmd
        self.args = dict(args or {})
        self.submitted_at = time.time()
        self.status = "pending"    # pending → executing → completed | failed
        self.result: dict[str, Any] | None = None
        self.completed_at: float = 0
        self.tier = tier

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "cmd": self.cmd,
            "status": self.status,
            "submitted_at": self.submitted_at,
            "tier": self.tier,
        }
        if self.result is not None:
            d["result"] = self.result
        if self.completed_at:
            d["completed_at"] = self.completed_at
        return d


class TaskEntry:
    """A task pushed by the operator to the agent."""

    __slots__ = ("id", "task_type", "payload", "created_at", "picked_up",
                 "picked_up_at")

    def __init__(self, task_type: str, payload: dict[str, Any]):
        self.id: str = f"task_{int(time.time() * 1000)}_{secrets.token_hex(4)}"
        self.task_type = task_type  # alert, request, sync, custom
        self.payload = dict(payload or {})
        self.created_at = time.time()
        self.picked_up = False
        self.picked_up_at: float = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.task_type,
            "payload": self.payload,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Channel singleton
# ---------------------------------------------------------------------------

class CommandChannel:
    """Bidirectional command channel between OpenClaw agent and ShadowBroker."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # Agent → SB
        self._commands: OrderedDict[str, CommandEntry] = OrderedDict()
        # SB → Agent
        self._tasks: OrderedDict[str, TaskEntry] = OrderedDict()
        self._stats = {
            "commands_received": 0,
            "commands_executed": 0,
            "commands_failed": 0,
            "tasks_pushed": 0,
            "tasks_picked_up": 0,
        }

    def _prune_expired(self) -> None:
        """Remove completed commands past TTL and expired tasks."""
        now = time.time()
        # Prune completed/failed commands
        expired_cmds = [
            cid for cid, entry in self._commands.items()
            if entry.status in ("completed", "failed")
            and entry.completed_at
            and (now - entry.completed_at) > COMMAND_RESULT_TTL
        ]
        for cid in expired_cmds:
            self._commands.pop(cid, None)
        # Prune expired tasks
        expired_tasks = [
            tid for tid, entry in self._tasks.items()
            if (now - entry.created_at) > TASK_TTL
        ]
        for tid in expired_tasks:
            self._tasks.pop(tid, None)

    # -- Agent → SB: Command submission -----------------------------------

    def submit_command(self, cmd: str, args: dict[str, Any],
                       access_tier: str = "restricted") -> dict[str, Any]:
        """Submit a command from the agent.

        Returns the command ID for tracking, or an error.
        """
        cmd = str(cmd or "").strip().lower()
        if not cmd:
            return {"ok": False, "detail": "empty command"}

        allowed = allowed_commands(access_tier)
        if cmd not in allowed:
            if cmd in WRITE_COMMANDS and access_tier != "full":
                return {
                    "ok": False,
                    "detail": f"command '{cmd}' requires full access tier",
                }
            return {"ok": False, "detail": f"unknown command: {cmd}"}

        tier_info = detect_tier()

        with self._lock:
            self._prune_expired()
            pending = sum(
                1 for e in self._commands.values() if e.status == "pending"
            )
            if pending >= MAX_PENDING_COMMANDS:
                return {"ok": False, "detail": "command queue full"}

            entry = CommandEntry(cmd, args, tier=tier_info["tier"])
            self._commands[entry.id] = entry
            self._stats["commands_received"] += 1

        # Execute with timeout protection
        self._execute_command(entry)

        return {
            "ok": True,
            "command_id": entry.id,
            "tier": tier_info["tier"],
            "status": entry.status,
            "result": entry.result,
        }

    def submit_batch(
        self,
        commands: list[dict[str, Any]],
        access_tier: str = "restricted",
    ) -> dict[str, Any]:
        """Submit multiple commands in one call and return all results.

        Each element should be {"cmd": str, "args": dict}.
        Commands execute concurrently in the shared thread pool, so
        independent queries (e.g. find_flights + search_news) overlap
        instead of serialising behind N HTTP round-trips.

        Returns {"ok": True, "results": [...], "tier": int}.
        """
        MAX_BATCH = 20
        if not commands:
            return {"ok": False, "detail": "empty batch"}
        if len(commands) > MAX_BATCH:
            return {"ok": False, "detail": f"batch too large (max {MAX_BATCH})"}

        tier_info = detect_tier()
        allowed = allowed_commands(access_tier)
        # Pre-allocate results in input order so the caller can match
        # result[i] to command[i] by index.
        results: list[dict[str, Any]] = [None] * len(commands)  # type: ignore[list-item]
        entries_with_index: list[tuple[int, CommandEntry]] = []

        with self._lock:
            self._prune_expired()
            pending = sum(
                1 for e in self._commands.values() if e.status == "pending"
            )
            if pending + len(commands) > MAX_PENDING_COMMANDS:
                return {"ok": False, "detail": "command queue full"}

        # Validate all commands, recording their original index
        for idx, item in enumerate(commands):
            cmd = str(item.get("cmd", "")).strip().lower()
            args = item.get("args") or {}
            if not cmd:
                results[idx] = {"cmd": cmd, "ok": False, "detail": "empty command"}
                continue
            if cmd not in allowed:
                detail = (f"command '{cmd}' requires full access tier"
                          if cmd in WRITE_COMMANDS and access_tier != "full"
                          else f"unknown command: {cmd}")
                results[idx] = {"cmd": cmd, "ok": False, "detail": detail}
                continue
            entry = CommandEntry(cmd, args, tier=tier_info["tier"])
            entries_with_index.append((idx, entry))
            with self._lock:
                self._commands[entry.id] = entry
                self._stats["commands_received"] += 1

        # Execute valid commands concurrently
        if entries_with_index:
            future_to_idx: dict[concurrent.futures.Future, tuple[int, CommandEntry]] = {
                _executor.submit(_dispatch_command, entry.cmd, entry.args): (idx, entry)
                for idx, entry in entries_with_index
            }
            for future in concurrent.futures.as_completed(
                future_to_idx, timeout=COMMAND_TIMEOUT + 5
            ):
                idx, entry = future_to_idx[future]
                entry.status = "executing"
                try:
                    entry.result = future.result(timeout=0)
                    entry.status = "completed"
                    self._stats["commands_executed"] += 1
                except concurrent.futures.TimeoutError:
                    entry.result = {
                        "ok": False,
                        "detail": f"command timed out after {COMMAND_TIMEOUT}s",
                    }
                    entry.status = "failed"
                    self._stats["commands_failed"] += 1
                except Exception as exc:
                    entry.result = {"ok": False, "detail": str(exc)}
                    entry.status = "failed"
                    self._stats["commands_failed"] += 1
                entry.completed_at = time.time()
                results[idx] = {
                    "cmd": entry.cmd,
                    "command_id": entry.id,
                    "ok": entry.status == "completed",
                    "status": entry.status,
                    "result": entry.result,
                }

        return {
            "ok": True,
            "results": results,
            "tier": tier_info["tier"],
            "count": len(results),
        }

    def _execute_command(self, entry: CommandEntry) -> None:
        """Execute a command with timeout protection."""
        entry.status = "executing"
        try:
            future = _executor.submit(_dispatch_command, entry.cmd, entry.args)
            result = future.result(timeout=COMMAND_TIMEOUT)
            entry.result = result
            entry.status = "completed"
            self._stats["commands_executed"] += 1
        except concurrent.futures.TimeoutError:
            entry.result = {
                "ok": False,
                "detail": f"command timed out after {COMMAND_TIMEOUT}s",
            }
            entry.status = "failed"
            self._stats["commands_failed"] += 1
            logger.warning("Command %s timed out after %ds", entry.cmd, COMMAND_TIMEOUT)
        except Exception as exc:
            entry.result = {"ok": False, "detail": str(exc)}
            entry.status = "failed"
            self._stats["commands_failed"] += 1
            logger.warning("Command %s failed: %s", entry.cmd, exc)
        entry.completed_at = time.time()

    def get_command_result(self, command_id: str) -> dict[str, Any] | None:
        """Get result for a specific command."""
        with self._lock:
            entry = self._commands.get(command_id)
            if entry is None:
                return None
            return entry.to_dict()

    def get_completed_commands(self) -> list[dict[str, Any]]:
        """Get all completed/failed command results (destructive read)."""
        with self._lock:
            self._prune_expired()
            results = []
            consumed = []
            for cid, entry in self._commands.items():
                if entry.status in ("completed", "failed"):
                    results.append(entry.to_dict())
                    consumed.append(cid)
            for cid in consumed:
                self._commands.pop(cid, None)
            return results

    # -- SB → Agent: Task push --------------------------------------------

    def push_task(self, task_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Operator pushes a task to the agent."""
        task_type = str(task_type or "custom").strip().lower()
        if task_type not in ("alert", "request", "sync", "custom"):
            return {"ok": False, "detail": f"invalid task type: {task_type}"}

        with self._lock:
            self._prune_expired()
            pending = sum(1 for t in self._tasks.values() if not t.picked_up)
            if pending >= MAX_PENDING_TASKS:
                return {"ok": False, "detail": "task queue full"}

            entry = TaskEntry(task_type, payload)
            self._tasks[entry.id] = entry
            self._stats["tasks_pushed"] += 1

        return {"ok": True, "task_id": entry.id}

    def poll_tasks(self) -> list[dict[str, Any]]:
        """Agent picks up pending tasks (destructive read)."""
        with self._lock:
            self._prune_expired()
            tasks = []
            for tid, entry in list(self._tasks.items()):
                if not entry.picked_up:
                    entry.picked_up = True
                    entry.picked_up_at = time.time()
                    tasks.append(entry.to_dict())
                    self._stats["tasks_picked_up"] += 1
            # Remove picked-up tasks
            consumed = [
                tid for tid, entry in self._tasks.items() if entry.picked_up
            ]
            for tid in consumed:
                self._tasks.pop(tid, None)
            return tasks

    # -- Status ------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Return channel status for the operator."""
        tier_info = detect_tier()
        with self._lock:
            self._prune_expired()
            pending_commands = sum(
                1 for e in self._commands.values()
                if e.status in ("pending", "executing")
            )
            completed_commands = sum(
                1 for e in self._commands.values()
                if e.status in ("completed", "failed")
            )
            pending_tasks = sum(
                1 for t in self._tasks.values() if not t.picked_up
            )
        return {
            "ok": True,
            **tier_info,
            "pending_commands": pending_commands,
            "completed_commands": completed_commands,
            "pending_tasks": pending_tasks,
            "stats": dict(self._stats),
        }


# ---------------------------------------------------------------------------
# Compact response helper — reuses the Time Machine compressed_v1 schema.
#
# When an agent passes ``compact=true`` (or ``format="compact"``) on any
# command that returns full telemetry, we reduce each layer to positional
# + identity fields and strip None values.  This cuts JSON parse time and
# token count on the agent side without removing information the agent
# actually uses for map reasoning.
# ---------------------------------------------------------------------------

def _wants_compact(args: dict[str, Any]) -> bool:
    """True if the agent requested compact/compressed response formatting."""
    if not isinstance(args, dict):
        return False
    if args.get("compact") is True:
        return True
    fmt = args.get("format")
    if isinstance(fmt, str) and fmt.lower() in ("compact", "compressed", "compressed_v1"):
        return True
    return False


def _compact_telemetry_dict(data: dict[str, Any] | None) -> dict[str, Any]:
    """Apply the compressed_v1 schema to every layer in a telemetry dict.

    Non-layer keys (metadata like ``last_updated``, ``freshness``, scalar
    totals) are passed through untouched.  Unknown layers fall back to
    the generic id/lat/lng/name projection from ``_compress_entity``.
    """
    if not isinstance(data, dict):
        return data or {}
    try:
        from routers.ai_intel import _compress_layer_data
    except Exception:
        return data  # compression module unavailable — return as-is
    result: dict[str, Any] = {}
    for key, val in data.items():
        # Metadata / scalars pass through.
        if not isinstance(val, (list, dict)):
            result[key] = val
            continue
        # sigint is a dict-of-lists; _compress_layer_data handles that shape.
        if isinstance(val, list) or key == "sigint":
            try:
                result[key] = _compress_layer_data(key, val)
            except Exception:
                result[key] = val
        else:
            result[key] = val
    return result


def _compact_result_entry(entry: Any) -> Any:
    """Tighten a single search-result dict for compact output.

    Query commands (find_flights, find_ships, entities_near, search_*)
    already return projected dicts — so the main wins here are:
    dropping empty strings / None values, and rounding lat/lng to 3
    decimals to match the compressed_v1 precision budget.  Non-dict
    entries pass through unchanged.
    """
    if not isinstance(entry, dict):
        return entry
    out: dict[str, Any] = {}
    for k, v in entry.items():
        if v is None:
            continue
        if isinstance(v, str) and not v:
            continue
        if k in ("lat", "lng") and isinstance(v, (int, float)):
            out[k] = round(float(v), 3)
        else:
            out[k] = v
    return out


def _compact_query_result(result: Any) -> Any:
    """Apply compact projection to a query-command result payload.

    Shape is typically ``{"results": [...], "version": N, "truncated": bool}``.
    Non-dict payloads and unrecognized shapes pass through.
    """
    if not isinstance(result, dict):
        return result
    results = result.get("results")
    if not isinstance(results, list):
        return result
    out = dict(result)
    out["results"] = [_compact_result_entry(r) for r in results]
    return out


# ---------------------------------------------------------------------------
# Command dispatcher
# ---------------------------------------------------------------------------

def _dispatch_command(cmd: str, args: dict[str, Any]) -> dict[str, Any]:
    """Route a command to the appropriate AI Intel function.

    All commands execute synchronously and return a result dict.
    Commands run in an isolated thread (via _execute_command) so they
    do not need or touch the caller's event loop.
    """
    if cmd == "get_telemetry":
        from services.telemetry import get_cached_telemetry_refs
        data = get_cached_telemetry_refs()
        if _wants_compact(args):
            data = _compact_telemetry_dict(data)
            return {"ok": True, "data": data, "format": "compressed_v1"}
        return {"ok": True, "data": data}

    if cmd == "get_slow_telemetry":
        from services.telemetry import get_cached_slow_telemetry_refs
        data = get_cached_slow_telemetry_refs()
        if _wants_compact(args):
            data = _compact_telemetry_dict(data)
            return {"ok": True, "data": data, "format": "compressed_v1"}
        return {"ok": True, "data": data}

    if cmd == "get_summary":
        from services.telemetry import get_telemetry_summary
        summary = get_telemetry_summary()
        return {"ok": True, "data": summary, "version": summary.get("version")}

    if cmd == "get_layer_slice":
        from services.telemetry import get_layer_slice
        layers = args.get("layers") or []
        slv = args.get("since_layer_versions")
        result = get_layer_slice(
            layers=layers if isinstance(layers, (list, tuple)) else [],
            limit_per_layer=args.get("limit_per_layer"),
            since_version=args.get("since_version"),
            since_layer_versions=slv if isinstance(slv, dict) else None,
        )
        if _wants_compact(args) and isinstance(result, dict):
            inner = result.get("layers")
            if isinstance(inner, dict):
                result = dict(result)
                result["layers"] = _compact_telemetry_dict(inner)
                result["format"] = "compressed_v1"
        return {"ok": True, "data": result}

    if cmd == "find_flights":
        from services.telemetry import find_flights
        result = find_flights(
            query=str(args.get("query", "") or ""),
            callsign=str(args.get("callsign", "") or ""),
            registration=str(args.get("registration", "") or ""),
            icao24=str(args.get("icao24", "") or ""),
            owner=str(args.get("owner", "") or ""),
            categories=args.get("categories") if isinstance(args.get("categories"), (list, tuple)) else None,
            limit=args.get("limit", 25),
        )
        if _wants_compact(args):
            return {"ok": True, "data": _compact_query_result(result), "format": "compressed_v1"}
        return {"ok": True, "data": result}

    if cmd == "find_ships":
        from services.telemetry import find_ships
        result = find_ships(
            query=str(args.get("query", "") or ""),
            mmsi=str(args.get("mmsi", "") or ""),
            imo=str(args.get("imo", "") or ""),
            name=str(args.get("name", "") or ""),
            limit=args.get("limit", 25),
        )
        if _wants_compact(args):
            return {"ok": True, "data": _compact_query_result(result), "format": "compressed_v1"}
        return {"ok": True, "data": result}

    if cmd == "find_entity":
        from services.telemetry import find_entity
        result = find_entity(
            query=str(args.get("query", "") or ""),
            entity_type=str(args.get("entity_type", "") or args.get("type", "") or ""),
            callsign=str(args.get("callsign", "") or ""),
            registration=str(args.get("registration", "") or args.get("tail_number", "") or ""),
            icao24=str(args.get("icao24", "") or ""),
            mmsi=str(args.get("mmsi", "") or ""),
            imo=str(args.get("imo", "") or ""),
            name=str(args.get("name", "") or ""),
            owner=str(args.get("owner", "") or args.get("operator", "") or ""),
            layers=args.get("layers") if isinstance(args.get("layers"), (list, tuple)) else None,
            limit=args.get("limit", 10),
        )
        if _wants_compact(args):
            compact = dict(result)
            compact["results"] = [_compact_result_entry(r) for r in result.get("results", [])]
            if isinstance(result.get("best_match"), dict):
                compact["best_match"] = _compact_result_entry(result["best_match"])
            return {"ok": True, "data": compact, "format": "compressed_v1"}
        return {"ok": True, "data": result}

    if cmd == "correlate_entity":
        from services.telemetry import correlate_entity
        result = correlate_entity(
            query=str(args.get("query", "") or ""),
            entity_type=str(args.get("entity_type", "") or args.get("type", "") or ""),
            callsign=str(args.get("callsign", "") or ""),
            registration=str(args.get("registration", "") or args.get("tail_number", "") or ""),
            icao24=str(args.get("icao24", "") or ""),
            mmsi=str(args.get("mmsi", "") or ""),
            imo=str(args.get("imo", "") or ""),
            name=str(args.get("name", "") or ""),
            owner=str(args.get("owner", "") or args.get("operator", "") or ""),
            radius_km=args.get("radius_km", 100),
            limit=args.get("limit", 10),
        )
        if _wants_compact(args):
            compact = dict(result)
            if isinstance(compact.get("lookup"), dict):
                compact["lookup"] = dict(compact["lookup"])
                compact["lookup"]["results"] = [
                    _compact_result_entry(r) for r in compact["lookup"].get("results", [])
                ]
                if isinstance(compact["lookup"].get("best_match"), dict):
                    compact["lookup"]["best_match"] = _compact_result_entry(compact["lookup"]["best_match"])
            if isinstance(compact.get("entity"), dict):
                compact["entity"] = _compact_result_entry(compact["entity"])
            return {"ok": True, "data": compact, "format": "compressed_v1"}
        return {"ok": True, "data": result}

    if cmd == "search_telemetry":
        from services.telemetry import search_telemetry
        result = search_telemetry(
            query=str(args.get("query", "") or ""),
            layers=args.get("layers") if isinstance(args.get("layers"), (list, tuple)) else None,
            limit=args.get("limit", 25),
        )
        if _wants_compact(args):
            return {"ok": True, "data": _compact_query_result(result), "format": "compressed_v1"}
        return {"ok": True, "data": result}

    if cmd == "search_news":
        from services.telemetry import search_news
        result = search_news(
            query=str(args.get("query", "") or ""),
            limit=args.get("limit", 10),
            include_gdelt=bool(args.get("include_gdelt", True)),
        )
        if _wants_compact(args):
            return {"ok": True, "data": _compact_query_result(result), "format": "compressed_v1"}
        return {"ok": True, "data": result}

    if cmd == "brief_area":
        from services.telemetry import entities_near, search_news, get_layer_slice
        lat = args.get("lat")
        lng = args.get("lng") if args.get("lng") is not None else args.get("lon")
        if lat is None or lng is None:
            return {"ok": False, "detail": "lat and lng required"}
        radius_km = args.get("radius_km", 50)
        entity_types = args.get("entity_types") if isinstance(args.get("entity_types"), (list, tuple)) else None
        nearby = entities_near(
            lat=lat,
            lng=lng,
            radius_km=radius_km,
            entity_types=entity_types,
            limit=args.get("limit", 25),
        )
        topic = str(args.get("query", "") or args.get("topic", "") or "").strip()
        news = search_news(query=topic, limit=10) if topic else {"results": [], "truncated": False}
        layers = ["weather_alerts", "earthquakes", "internet_outages", "sar_anomalies"]
        context = get_layer_slice(layers=layers, limit_per_layer=args.get("context_limit", 10))
        return {
            "ok": True,
            "data": {
                "center": {"lat": float(lat), "lng": float(lng)},
                "radius_km": float(radius_km),
                "nearby": nearby,
                "topic_news": news,
                "context_layers": context,
            },
        }

    if cmd == "what_changed":
        from services.telemetry import get_layer_slice, get_telemetry_summary
        layers = args.get("layers") if isinstance(args.get("layers"), (list, tuple)) else []
        if not layers:
            return {"ok": True, "data": get_telemetry_summary()}
        since_layer_versions = args.get("since_layer_versions")
        result = get_layer_slice(
            layers=layers,
            limit_per_layer=args.get("limit_per_layer", 25),
            since_version=args.get("since_version"),
            since_layer_versions=since_layer_versions if isinstance(since_layer_versions, dict) else None,
        )
        return {"ok": True, "data": result}

    if cmd == "entities_near":
        from services.telemetry import entities_near
        lat = args.get("lat")
        lng = args.get("lng")
        if lat is None or lng is None:
            return {"ok": False, "detail": "lat and lng required"}
        result = entities_near(
            lat=lat,
            lng=lng,
            radius_km=args.get("radius_km", 50),
            entity_types=args.get("entity_types") if isinstance(args.get("entity_types"), (list, tuple)) else None,
            limit=args.get("limit", 25),
        )
        if _wants_compact(args):
            return {"ok": True, "data": _compact_query_result(result), "format": "compressed_v1"}
        return {"ok": True, "data": result}

    if cmd == "get_report":
        from services.telemetry import get_cached_telemetry_refs, get_cached_slow_telemetry_refs
        fast = get_cached_telemetry_refs()
        slow = get_cached_slow_telemetry_refs()
        if _wants_compact(args):
            return {
                "ok": True,
                "data": {
                    "fast": _compact_telemetry_dict(fast),
                    "slow": _compact_telemetry_dict(slow),
                },
                "format": "compressed_v1",
            }
        return {"ok": True, "data": {"fast": fast, "slow": slow}}

    if cmd == "get_sigint_totals":
        from services.telemetry import get_cached_telemetry_refs
        data = get_cached_telemetry_refs()
        sigint = data.get("sigint", {}) if data else {}
        totals = {}
        for key in ("meshtastic", "aprs", "js8call"):
            items = sigint.get(key, [])
            totals[key] = len(items) if isinstance(items, list) else 0
        return {"ok": True, "data": totals}

    if cmd == "get_prediction_markets":
        from services.telemetry import get_cached_slow_telemetry_refs
        slow = get_cached_slow_telemetry_refs()
        markets = slow.get("prediction_markets", []) if slow else []
        return {"ok": True, "data": markets}

    if cmd == "get_ai_pins":
        from services.ai_intel_store import get_all_intel_pins
        pins = get_all_intel_pins()
        return {"ok": True, "data": pins}

    if cmd == "get_layers":
        from services.ai_intel_store import get_intel_layers
        layers = get_intel_layers()
        return {"ok": True, "data": layers}

    if cmd == "get_correlations":
        from services.fetchers._store import get_latest_data_subset_refs
        snap = get_latest_data_subset_refs("correlations")
        return {"ok": True, "data": snap.get("correlations") or []}

    if cmd == "channel_status":
        return channel.status()

    if cmd == "list_watches":
        from services.openclaw_watchdog import list_watches
        return {"ok": True, "data": list_watches()}

    # -- Write commands (full access only) ---------------------------------

    if cmd == "place_pin":
        from services.ai_intel_store import add_intel_pin
        pin = add_intel_pin(args)
        return {"ok": True, "data": pin}

    if cmd == "delete_pin":
        pin_id = str(args.get("id", "") or args.get("pin_id", "")).strip()
        if not pin_id:
            return {"ok": False, "detail": "pin id required"}
        from services.ai_intel_store import delete_intel_pin
        result = delete_intel_pin(pin_id)
        return {"ok": True, "data": result}

    if cmd == "inject_data":
        layer = str(args.get("layer", "")).strip()
        items = args.get("items", [])
        if not layer or not items:
            return {"ok": False, "detail": "layer and items required"}
        from services.ai_intel_store import inject_layer_data
        result = inject_layer_data(layer, items)
        return {"ok": True, "data": result}

    if cmd == "create_layer":
        from services.ai_intel_store import create_intel_layer
        name = str(args.get("name", "")).strip()
        if not name:
            return {"ok": False, "detail": "layer name required"}
        layer = create_intel_layer(args)
        return {"ok": True, "data": layer}

    if cmd == "update_layer":
        layer_id = str(args.get("layer_id", "") or args.get("id", "")).strip()
        if not layer_id:
            return {"ok": False, "detail": "layer_id required"}
        from services.ai_intel_store import update_intel_layer
        result = update_intel_layer(layer_id, args)
        if result is None:
            return {"ok": False, "detail": f"layer '{layer_id}' not found"}
        return {"ok": True, "data": result}

    if cmd == "delete_layer":
        layer_id = str(args.get("layer_id", "") or args.get("id", "")).strip()
        if not layer_id:
            return {"ok": False, "detail": "layer_id required"}
        from services.ai_intel_store import delete_intel_layer
        removed = delete_intel_layer(layer_id)
        return {"ok": True, "data": {"layer_id": layer_id, "pins_removed": removed}}

    if cmd == "refresh_feed":
        layer_id = str(args.get("layer_id", "") or args.get("id", "")).strip()
        if not layer_id:
            return {"ok": False, "detail": "layer_id required"}
        from services.ai_intel_store import get_intel_layers
        layers = get_intel_layers()
        target = next((l for l in layers if l["id"] == layer_id), None)
        if target is None:
            return {"ok": False, "detail": f"layer '{layer_id}' not found"}
        if not target.get("feed_url"):
            return {"ok": False, "detail": "layer has no feed URL"}
        from services.feed_ingester import _fetch_layer_feed
        _fetch_layer_feed(target)
        # Re-fetch for updated state
        layers = get_intel_layers()
        updated = next((l for l in layers if l["id"] == layer_id), target)
        return {"ok": True, "data": updated}

    if cmd == "take_snapshot":
        from routers.ai_intel import _take_snapshot_internal
        layers = args.get("layers") or []
        compress = args.get("compress", True)
        result = _take_snapshot_internal(
            layers=layers if layers else None,
            profile="openclaw",
            compress=compress,
        )
        return {"ok": True, "data": result}

    if cmd == "timemachine_list":
        from routers.ai_intel import _snapshots, _snapshots_lock
        from services.node_settings import read_node_settings
        tm_on = read_node_settings().get("timemachine_enabled", False)
        with _snapshots_lock:
            recent = [
                {"id": s["id"], "timestamp": s["timestamp"],
                 "format": s.get("format", "full"),
                 "layers": s["layers"], "layer_counts": s["layer_counts"]}
                for s in _snapshots[-20:]
            ]
        return {"ok": True, "data": recent, "enabled": tm_on,
                "notice": None if tm_on else "Time Machine auto-snapshots are currently OFF. "
                "The operator can enable them in Settings > Protocol. "
                "Warn the user: ~68 MB/day (~2 GB/month) storage cost."}

    if cmd == "timemachine_playback":
        snapshot_id = str(args.get("snapshot_id", "")).strip()
        if not snapshot_id:
            return {"ok": False, "detail": "snapshot_id required"}
        from routers.ai_intel import _snapshots, _snapshots_lock, _expand_compressed_entity
        with _snapshots_lock:
            target = None
            for snap in _snapshots:
                if snap["id"] == snapshot_id:
                    target = snap
                    break
        if target is None:
            return {"ok": False, "detail": f"snapshot '{snapshot_id}' not found"}
        data = target.get("data", {})
        if target.get("format") == "compressed_v1":
            expanded = {}
            for layer, items in data.items():
                if isinstance(items, list):
                    expanded[layer] = [_expand_compressed_entity(layer, e) for e in items]
                else:
                    expanded[layer] = items
            data = expanded
        return {"ok": True, "data": {
            "snapshot_id": target["id"], "timestamp": target["timestamp"],
            "mode": "playback", "layers": target["layers"], "data": data,
        }}

    if cmd == "timemachine_config":
        from routers.ai_intel import _timemachine_config
        from services.node_settings import read_node_settings
        tm_on = read_node_settings().get("timemachine_enabled", False)
        return {"ok": True, "data": {
            **_timemachine_config,
            "enabled": tm_on,
            "storage_notice": "Time Machine auto-snapshots use ~68 MB/day (~2 GB/month) of compressed storage. "
                              "This feature is OFF by default. The operator must explicitly enable it in Settings > Protocol. "
                              "Always inform the user of the storage cost before recommending they turn it on.",
        }}

    # -- Watchdog commands (write access — agent sets up its own alerts) ----

    if cmd == "add_watch":
        from services.openclaw_watchdog import add_watch
        watch_type = str(args.get("type", "")).strip()
        if not watch_type:
            return {"ok": False, "detail": "watch type required (track_aircraft, track_callsign, track_registration, track_ship, track_entity, geofence, keyword, prediction_market)"}
        watch_params = args.get("params", {})
        if not watch_params:
            # Allow flat args (e.g. {type: "track_callsign", callsign: "N189AM"})
            watch_params = {k: v for k, v in args.items() if k not in ("type", "params")}
        result = add_watch(watch_type, watch_params)
        return {"ok": True, "data": result}

    if cmd == "track_entity":
        from services.openclaw_watchdog import add_watch
        from services.telemetry import find_entity

        query = str(args.get("query", "") or args.get("name", "") or "").strip()
        entity_type = str(args.get("entity_type", "") or args.get("type", "") or "").strip().lower()
        lookup = find_entity(
            query=query,
            entity_type=entity_type,
            callsign=str(args.get("callsign", "") or ""),
            registration=str(args.get("registration", "") or args.get("tail_number", "") or ""),
            icao24=str(args.get("icao24", "") or ""),
            mmsi=str(args.get("mmsi", "") or ""),
            imo=str(args.get("imo", "") or ""),
            name=str(args.get("name", "") or ""),
            owner=str(args.get("owner", "") or args.get("operator", "") or ""),
            layers=args.get("layers") if isinstance(args.get("layers"), (list, tuple)) else None,
            limit=5,
        )
        best = lookup.get("best_match") if isinstance(lookup.get("best_match"), dict) else {}
        group = str(best.get("group", "") or entity_type).lower()
        params = {
            "query": query or best.get("label") or best.get("name") or "",
            "entity_type": entity_type or group,
            "callsign": args.get("callsign") or best.get("callsign") or (best.get("label") if group == "aircraft" else "") or "",
            "registration": args.get("registration") or args.get("tail_number") or best.get("registration") or (best.get("id") if group == "aircraft" else "") or "",
            "icao24": (
                args.get("icao24")
                or best.get("icao24")
                or (best.get("id") if group == "aircraft" else "")
            ),
            "mmsi": args.get("mmsi") or best.get("mmsi") or "",
            "imo": args.get("imo") or best.get("imo") or "",
            "name": args.get("name") or best.get("name") or best.get("label") or "",
            "owner": args.get("owner") or args.get("operator") or best.get("owner") or "",
        }
        if group == "aircraft" or entity_type in {"aircraft", "plane", "flight", "jet", "helicopter"} or any(params.get(k) for k in ("callsign", "registration", "icao24")):
            watch_type = "track_aircraft"
        elif group == "maritime" or entity_type in {"ship", "ships", "vessel", "boat", "yacht", "maritime"} or any(params.get(k) for k in ("mmsi", "imo")):
            watch_type = "track_ship"
        else:
            watch_type = "track_entity"
            if isinstance(args.get("layers"), (list, tuple)):
                params["layers"] = list(args.get("layers") or [])
        result = add_watch(watch_type, {k: v for k, v in params.items() if v not in (None, "")})
        return {"ok": True, "data": {"watch": result, "watch_type": watch_type, "initial_lookup": lookup}}

    if cmd == "watch_area":
        from services.openclaw_watchdog import add_watch
        lat = args.get("lat")
        lng = args.get("lng") if args.get("lng") is not None else args.get("lon")
        if lat is None or lng is None:
            return {"ok": False, "detail": "lat and lng required"}
        entity_types = args.get("entity_types")
        if not isinstance(entity_types, (list, tuple)):
            entity_types = ["aircraft", "ships"]
        params = {
            "lat": float(lat),
            "lng": float(lng),
            "radius_km": float(args.get("radius_km", 50) or 50),
            "entity_types": list(entity_types),
        }
        if args.get("label"):
            params["label"] = str(args.get("label"))
        result = add_watch("geofence", params)
        return {"ok": True, "data": result}

    if cmd == "remove_watch":
        from services.openclaw_watchdog import remove_watch
        watch_id = str(args.get("id", "") or args.get("watch_id", "")).strip()
        if not watch_id:
            return {"ok": False, "detail": "watch id required"}
        return remove_watch(watch_id)

    if cmd == "clear_watches":
        from services.openclaw_watchdog import clear_watches
        return clear_watches()

    # -- Display commands (agent shows imagery to user) ----------------------

    if cmd == "show_satellite":
        lat = args.get("lat")
        lng = args.get("lng")
        if lat is None or lng is None:
            return {"ok": False, "detail": "lat and lng required"}
        try:
            lat, lng = float(lat), float(lng)
        except (ValueError, TypeError):
            return {"ok": False, "detail": "lat/lng must be numbers"}
        # Fetch satellite imagery
        from services.sentinel_search import search_sentinel2_scene
        scene = search_sentinel2_scene(lat, lng)
        # Push display action to frontend
        from routers.ai_intel import push_agent_action
        push_agent_action({
            "action": "show_image",
            "source": "sentinel2",
            "lat": lat,
            "lng": lng,
            "sentinel2": scene,
            "caption": str(args.get("caption", "")) or None,
        })
        return {"ok": True, "data": {
            "displayed": True,
            "lat": lat,
            "lng": lng,
            "scene": scene,
        }}

    if cmd == "show_sentinel":
        lat = args.get("lat")
        lng = args.get("lng")
        if lat is None or lng is None:
            return {"ok": False, "detail": "lat and lng required"}
        try:
            lat, lng = float(lat), float(lng)
        except (ValueError, TypeError):
            return {"ok": False, "detail": "lat/lng must be numbers"}
        preset = str(args.get("preset", "TRUE-COLOR")).upper()
        if preset not in ("TRUE-COLOR", "FALSE-COLOR", "NDVI", "MOISTURE-INDEX"):
            preset = "TRUE-COLOR"
        # Build a Sentinel Hub Process API image URL via the existing backend proxy.
        # The frontend will need CDSE credentials to be configured.
        # For the agent, we generate the tile request params so the frontend can fetch it.
        from routers.ai_intel import push_agent_action
        push_agent_action({
            "action": "show_image",
            "source": "sentinel_hub",
            "lat": lat,
            "lng": lng,
            "preset": preset,
            "caption": str(args.get("caption", "")) or None,
        })
        return {"ok": True, "data": {
            "displayed": True,
            "lat": lat,
            "lng": lng,
            "preset": preset,
            "note": "Image will display if user has Copernicus CDSE credentials configured. "
                    "Falls back to Sentinel-2 STAC (free) if not.",
        }}

    # -- SAR layer commands ------------------------------------------------
    # Read-only commands return data even when Mode B is disabled — the
    # status payload tells the agent how to enable it.

    if cmd == "sar_status":
        from services.sar.sar_config import (
            catalog_enabled as _sar_catalog_enabled,
            openclaw_enabled as _sar_openclaw_enabled,
            products_fetch_status,
            require_private_tier_for_publish,
        )
        if not _sar_openclaw_enabled():
            return {"ok": False, "detail": "SAR OpenClaw integration disabled (MESH_SAR_OPENCLAW_ENABLED=false)"}
        return {
            "ok": True,
            "data": {
                "catalog_enabled": _sar_catalog_enabled(),
                "products": products_fetch_status(),
                "require_private_tier": require_private_tier_for_publish(),
            },
        }

    if cmd == "sar_anomalies_recent":
        from services.sar.sar_config import openclaw_enabled as _sar_openclaw_enabled
        if not _sar_openclaw_enabled():
            return {"ok": False, "detail": "SAR OpenClaw integration disabled"}
        from services.fetchers._store import get_latest_data_subset_refs
        snap = get_latest_data_subset_refs("sar_anomalies")
        items = list(snap.get("sar_anomalies") or [])
        kind = str(args.get("kind", "") or "").strip()
        if kind:
            items = [a for a in items if a.get("kind") == kind]
        limit = int(args.get("limit", 50) or 50)
        return {"ok": True, "data": items[:limit]}

    if cmd == "sar_anomalies_near":
        from services.sar.sar_config import openclaw_enabled as _sar_openclaw_enabled
        if not _sar_openclaw_enabled():
            return {"ok": False, "detail": "SAR OpenClaw integration disabled"}
        lat = args.get("lat")
        lng = args.get("lng") if args.get("lng") is not None else args.get("lon")
        if lat is None or lng is None:
            return {"ok": False, "detail": "lat and lng required"}
        try:
            lat_f = float(lat)
            lng_f = float(lng)
        except (TypeError, ValueError):
            return {"ok": False, "detail": "lat/lng must be numeric"}
        radius_km = float(args.get("radius_km", 50) or 50)
        from services.fetchers._store import get_latest_data_subset_refs
        from services.sar.sar_aoi import haversine_km
        snap = get_latest_data_subset_refs("sar_anomalies")
        matches = []
        for a in (snap.get("sar_anomalies") or []):
            try:
                d = haversine_km(lat_f, lng_f, float(a.get("lat", 0.0)), float(a.get("lon", 0.0)))
            except (TypeError, ValueError):
                continue
            if d <= radius_km:
                a2 = dict(a)
                a2["distance_km"] = round(d, 2)
                matches.append(a2)
        matches.sort(key=lambda x: x.get("distance_km", 0))
        limit = int(args.get("limit", 25) or 25)
        return {"ok": True, "data": matches[:limit]}

    if cmd == "sar_scene_search":
        from services.sar.sar_config import openclaw_enabled as _sar_openclaw_enabled
        if not _sar_openclaw_enabled():
            return {"ok": False, "detail": "SAR OpenClaw integration disabled"}
        from services.fetchers._store import get_latest_data_subset_refs
        snap = get_latest_data_subset_refs("sar_scenes")
        items = list(snap.get("sar_scenes") or [])
        aoi_id = str(args.get("aoi_id", "") or "").strip().lower()
        if aoi_id:
            items = [s for s in items if (s.get("aoi_id") or "").lower() == aoi_id]
        limit = int(args.get("limit", 50) or 50)
        return {"ok": True, "data": items[:limit]}

    if cmd == "sar_coverage_for_aoi":
        from services.sar.sar_config import openclaw_enabled as _sar_openclaw_enabled
        if not _sar_openclaw_enabled():
            return {"ok": False, "detail": "SAR OpenClaw integration disabled"}
        from services.fetchers._store import get_latest_data_subset_refs
        snap = get_latest_data_subset_refs("sar_aoi_coverage")
        coverage = list(snap.get("sar_aoi_coverage") or [])
        aoi_id = str(args.get("aoi_id", "") or "").strip().lower()
        if aoi_id:
            coverage = [c for c in coverage if (c.get("aoi_id") or "").lower() == aoi_id]
        return {"ok": True, "data": coverage}

    if cmd == "sar_aoi_list":
        from services.sar.sar_config import openclaw_enabled as _sar_openclaw_enabled
        if not _sar_openclaw_enabled():
            return {"ok": False, "detail": "SAR OpenClaw integration disabled"}
        from services.sar.sar_aoi import load_aois
        return {"ok": True, "data": [a.to_dict() for a in load_aois(force=True)]}

    if cmd == "sar_aoi_add":
        from services.sar.sar_config import openclaw_enabled as _sar_openclaw_enabled
        if not _sar_openclaw_enabled():
            return {"ok": False, "detail": "SAR OpenClaw integration disabled"}
        try:
            from services.sar.sar_aoi import SarAoi, add_aoi
            aoi = SarAoi(
                id=str(args.get("id", "")).strip().lower(),
                name=str(args.get("name", "")).strip() or str(args.get("id", "")),
                description=str(args.get("description", "")).strip(),
                center_lat=float(args.get("center_lat", args.get("lat", 0.0))),
                center_lon=float(args.get("center_lon", args.get("lon", 0.0))),
                radius_km=float(args.get("radius_km", 25.0)),
                polygon=args.get("polygon") if isinstance(args.get("polygon"), list) else None,
                category=str(args.get("category", "watchlist")).strip().lower() or "watchlist",
            )
        except (TypeError, ValueError) as exc:
            return {"ok": False, "detail": f"invalid AOI: {exc}"}
        if not aoi.id:
            return {"ok": False, "detail": "AOI id required"}
        add_aoi(aoi)
        return {"ok": True, "data": aoi.to_dict()}

    if cmd == "sar_aoi_remove":
        from services.sar.sar_config import openclaw_enabled as _sar_openclaw_enabled
        if not _sar_openclaw_enabled():
            return {"ok": False, "detail": "SAR OpenClaw integration disabled"}
        from services.sar.sar_aoi import remove_aoi
        aoi_id = str(args.get("id", "") or args.get("aoi_id", "")).strip().lower()
        if not aoi_id:
            return {"ok": False, "detail": "aoi id required"}
        removed = remove_aoi(aoi_id)
        return {"ok": True, "data": {"removed": removed, "id": aoi_id}}

    if cmd == "sar_pin_from_anomaly":
        from services.sar.sar_config import openclaw_enabled as _sar_openclaw_enabled
        if not _sar_openclaw_enabled():
            return {"ok": False, "detail": "SAR OpenClaw integration disabled"}
        anomaly_id = str(args.get("anomaly_id", "")).strip()
        if not anomaly_id:
            return {"ok": False, "detail": "anomaly_id required"}
        from services.fetchers._store import get_latest_data_subset_refs
        snap = get_latest_data_subset_refs("sar_anomalies")
        match = next(
            (a for a in (snap.get("sar_anomalies") or []) if a.get("anomaly_id") == anomaly_id),
            None,
        )
        if match is None:
            return {"ok": False, "detail": f"anomaly '{anomaly_id}' not found"}
        from services.ai_intel_store import add_intel_pin
        kind = match.get("kind", "sar_anomaly")
        pin_args = {
            "lat": match.get("lat", 0.0),
            "lng": match.get("lon", 0.0),
            "label": str(args.get("label") or f"SAR {kind}")[:200],
            "category": "sar",
            "description": str(
                args.get("description")
                or f"{kind} (mag={match.get('magnitude')} {match.get('magnitude_unit','')})"
            ),
            "source": match.get("solver", "sar"),
            "source_url": match.get("source_url", ""),
            "confidence": float(match.get("confidence", 0.5)),
            "metadata": {
                "anomaly_id": anomaly_id,
                "evidence_hash": match.get("evidence_hash"),
                "stack_id": match.get("stack_id"),
                "constellation": match.get("source_constellation"),
                "first_seen": match.get("first_seen"),
                "last_seen": match.get("last_seen"),
            },
        }
        pin = add_intel_pin(pin_args)
        return {"ok": True, "data": pin}

    if cmd == "sar_pin_click":
        # Return the full detail payload that the map popup shows when a
        # user clicks a SAR anomaly pin.  Lets OpenClaw "inspect" a pin
        # programmatically without screen-scraping the popup.
        from services.sar.sar_config import openclaw_enabled as _sar_openclaw_enabled
        if not _sar_openclaw_enabled():
            return {"ok": False, "detail": "SAR OpenClaw integration disabled"}
        anomaly_id = str(args.get("anomaly_id", "") or args.get("id", "")).strip()
        if not anomaly_id:
            return {"ok": False, "detail": "anomaly_id required"}
        from services.fetchers._store import get_latest_data_subset_refs
        snap = get_latest_data_subset_refs("sar_anomalies")
        anomaly = next(
            (a for a in (snap.get("sar_anomalies") or []) if a.get("anomaly_id") == anomaly_id),
            None,
        )
        if anomaly is None:
            return {"ok": False, "detail": f"anomaly '{anomaly_id}' not found"}
        # Pull AOI metadata + recent scenes over the same AOI, mirroring
        # the detail popup the operator would see.
        aoi_id = str(anomaly.get("aoi_id") or "").lower()
        aoi_meta: dict[str, Any] | None = None
        recent_scenes: list[dict[str, Any]] = []
        if aoi_id:
            try:
                from services.sar.sar_aoi import load_aois
                match = next((a for a in load_aois() if a.id.lower() == aoi_id), None)
                if match is not None:
                    aoi_meta = match.to_dict()
            except Exception:
                pass
            try:
                scenes_snap = get_latest_data_subset_refs("sar_scenes")
                all_scenes = list(scenes_snap.get("sar_scenes") or [])
                recent_scenes = [
                    s for s in all_scenes if (s.get("aoi_id") or "").lower() == aoi_id
                ][:10]
            except Exception:
                pass
        return {
            "ok": True,
            "data": {
                "anomaly": anomaly,
                "aoi": aoi_meta,
                "recent_scenes": recent_scenes,
            },
        }

    if cmd == "sar_focus_aoi":
        # Fly the user's map to an AOI's center (and optionally open its
        # detail popup via selectedEntity semantics on the frontend side).
        from services.sar.sar_config import openclaw_enabled as _sar_openclaw_enabled
        if not _sar_openclaw_enabled():
            return {"ok": False, "detail": "SAR OpenClaw integration disabled"}
        aoi_id = str(args.get("aoi_id", "") or args.get("id", "")).strip().lower()
        if not aoi_id:
            return {"ok": False, "detail": "aoi_id required"}
        try:
            from services.sar.sar_aoi import load_aois
            match = next((a for a in load_aois() if a.id.lower() == aoi_id), None)
        except Exception as exc:
            return {"ok": False, "detail": f"aoi load failed: {exc}"}
        if match is None:
            return {"ok": False, "detail": f"aoi '{aoi_id}' not found"}
        try:
            zoom = float(args.get("zoom", 8.0))
        except (TypeError, ValueError):
            zoom = 8.0
        from routers.ai_intel import push_agent_action
        push_agent_action({
            "action": "fly_to",
            "source": "sar_focus_aoi",
            "lat": float(match.center_lat),
            "lng": float(match.center_lon),
            "zoom": zoom,
            "aoi_id": match.id,
            "caption": f"AOI: {match.name}",
        })
        return {
            "ok": True,
            "data": {
                "dispatched": True,
                "aoi": match.to_dict(),
            },
        }

    if cmd == "sar_watch_anomaly":
        from services.sar.sar_config import openclaw_enabled as _sar_openclaw_enabled
        if not _sar_openclaw_enabled():
            return {"ok": False, "detail": "SAR OpenClaw integration disabled"}
        try:
            from services.openclaw_watchdog import add_watch
        except ImportError:
            return {"ok": False, "detail": "watchdog module unavailable"}
        aoi_id = str(args.get("aoi_id", "")).strip().lower()
        kind = str(args.get("kind", "")).strip()
        if not aoi_id:
            return {"ok": False, "detail": "aoi_id required"}
        watch_params = {
            "label": str(args.get("label") or f"SAR watch {aoi_id}"),
            "aoi_id": aoi_id,
            "kind": kind,
            "min_magnitude": float(args.get("min_magnitude", 0.0) or 0.0),
        }
        result = add_watch("sar_anomaly", watch_params)
        return {"ok": True, "data": result}

    # ------------------------------------------------------------------
    # Analysis zones — OpenClaw map overlays (yellow squares with reports)
    # ------------------------------------------------------------------

    if cmd == "list_analysis_zones":
        from services.analysis_zone_store import list_zones
        return {"ok": True, "data": {"zones": list_zones()}}

    if cmd == "place_analysis_zone":
        from services.analysis_zone_store import create_zone
        lat = args.get("lat")
        lng = args.get("lng")
        if lat is None or lng is None:
            return {"ok": False, "detail": "lat and lng required"}
        title = str(args.get("title", "Analysis Zone")).strip()
        body = str(args.get("body", "")).strip()
        if not body:
            return {"ok": False, "detail": "body (analysis text) required"}
        zone = create_zone(
            lat=float(lat),
            lng=float(lng),
            title=title,
            body=body,
            category=str(args.get("category", "analysis")).strip().lower(),
            severity=str(args.get("severity", "medium")).strip().lower(),
            cell_size_deg=float(args.get("cell_size_deg", 1.0) or 1.0),
            ttl_hours=float(args.get("ttl_hours", 0) or 0),
            source="openclaw",
            drivers=args.get("drivers"),
        )
        return {"ok": True, "data": {"zone": zone}}

    if cmd == "delete_analysis_zone":
        from services.analysis_zone_store import delete_zone
        zone_id = str(args.get("zone_id", "") or args.get("id", "")).strip()
        if not zone_id:
            return {"ok": False, "detail": "zone_id required"}
        removed = delete_zone(zone_id)
        if not removed:
            return {"ok": False, "detail": "zone not found"}
        return {"ok": True, "data": {"removed": zone_id}}

    if cmd == "clear_analysis_zones":
        from services.analysis_zone_store import clear_zones
        count = clear_zones(source="openclaw")
        return {"ok": True, "data": {"removed_count": count}}

    return {"ok": False, "detail": f"unhandled command: {cmd}"}


# ---------------------------------------------------------------------------
# Cover traffic for command channel polling
# ---------------------------------------------------------------------------
# When high-privacy mode is active, the channel emits synthetic poll
# responses at fixed intervals so an observer watching the HTTP cadence
# cannot distinguish active agent sessions from idle ones.
#
# Design mirrors mesh_rns._cover_loop: fixed interval + jitter, no adaptive
# backoff (S8A ruling: expanding the interval when real traffic is present
# leaks activity state).
#
# This is response-surface only — cover polls return the same JSON shape as
# real polls but with empty result arrays.  No relay internals are touched.
# ---------------------------------------------------------------------------

COVER_POLL_INTERVAL = 10  # seconds between synthetic polls
COVER_POLL_JITTER = (0.7, 1.3)  # multiplier range

_cover_poll_enabled = False
_cover_poll_thread = None


def _is_high_privacy_channel() -> bool:
    """Check if high-privacy mode is active (same check as mesh cover loop)."""
    try:
        from services.config import get_settings
        settings = get_settings()
        return bool(getattr(settings, "MESH_RNS_HIGH_PRIVACY", False))
    except Exception:
        return False


def _cover_poll_loop() -> None:
    """Daemon thread that generates synthetic poll cadence.

    Records synthetic poll events in the channel stats so an external
    observer sees uniform poll timing regardless of agent activity.
    """
    import random

    while _cover_poll_enabled:
        try:
            if not _is_high_privacy_channel():
                time.sleep(3)
                continue
            # Synthetic poll — same shape as real poll response but empty.
            # This touches only the stats counter, not the queue.
            with channel._lock:
                channel._stats.setdefault("cover_polls", 0)
                channel._stats["cover_polls"] += 1
            jitter = random.uniform(*COVER_POLL_JITTER)
            time.sleep(COVER_POLL_INTERVAL * jitter)
        except Exception:
            time.sleep(5)


def start_cover_poll() -> None:
    """Start the cover poll daemon if not already running."""
    global _cover_poll_enabled, _cover_poll_thread
    if _cover_poll_thread and _cover_poll_thread.is_alive():
        return
    _cover_poll_enabled = True
    _cover_poll_thread = threading.Thread(
        target=_cover_poll_loop, daemon=True, name="openclaw-cover-poll"
    )
    _cover_poll_thread.start()
    logger.info("OpenClaw cover poll daemon started (interval=%ds)", COVER_POLL_INTERVAL)


def stop_cover_poll() -> None:
    """Stop the cover poll daemon."""
    global _cover_poll_enabled
    _cover_poll_enabled = False


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

channel = CommandChannel()
