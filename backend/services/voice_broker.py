"""Server-side realtime voice-session brokering (voice-agent plan U2, §4).

Owns everything that must never leak into the browser:

  - provider resolution across ``openai_realtime`` / ``compatible_ws`` /
    ``local_text``, resolved at session start from ``os.environ`` + the
    operator keys env-file (R4 — ``lru_cache``d settings must not hide
    operator-file updates);
  - the bounded session registry with the concurrency gate
    (``VOICE_MAX_CONCURRENT_SESSIONS``);
  - ``build_session_config(context)`` — the single sanctioned point where the
    FULL upstream session config is authored server-side (§4.3). The client
    never supplies prompts, tools, or model ids; its ``session.update`` patches
    merge against a narrow allow-list (VAD/voice/truncation pass);
  - the realtime WS relay: a framing translator that is a dumb pipe for bytes,
    not frames (base64 wrap/strip only — never decodes, resamples, or inspects
    audio content), plus the metering tap (tier-1 usage accounting, tier-2
    conservative audio-seconds estimation via :mod:`services.voice_cost`,
    one-shot warn/cap push) and the wire-contract frame enforcement;
  - the ``local_text`` chat leg (httpx chat-completions proxy).

Cost enforcement is broker-side: on ``capCrossed`` the upstream socket is
closed, a ``cap`` frame is emitted, and the client is drained — client-side
displays are advisory UX only (R5). This module is the sole importer of
``websockets`` (R1); heavy imports stay inside function bodies (AST freeze,
§1.5).
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from services.config import get_settings
from services.voice_cost import (
    VoiceCostTracker,
    estimate_usage_cost_usd,
    is_known_voice_tier,
    resolve_voice_model,
    resolve_voice_model_by_id,
    serialize_cost_limits,
)
from services.voice_daily_budget import evaluate_daily_budget, read_daily_spend, record_response

logger = logging.getLogger("voice_broker")

# Wire contract constants (§4.3).
AUDIO_SAMPLE_RATE = 24000
AUDIO_CHANNELS = 1
MAX_BINARY_FRAME_BYTES = 65536
GROUNDING_SNAPSHOT_MAX_BYTES = 6 * 1024  # §2.4 serialization cap
GROUNDING_SCHEMA_ID = "sb.grounding.v1"
#: Client ``session.update`` patch keys that may pass the allow-list. Everything
#: else (instructions/tools/model/…) is authored server-side and rejected.
CLIENT_PATCH_ALLOWLIST = frozenset(
    {
        "turn_detection",
        "voice",
        "input_audio_transcription",
        "input_audio_noise_reduction",
    }
)
#: Client text-frame types accepted on the media path (§4.3 vocabulary).
CLIENT_FRAME_TYPES = frozenset({"session.update", "stop", "context.grounding"})
VIOLATIONS_BEFORE_CLOSE = 3
IDLE_TIMEOUT_SECONDS = 90.0  # hot-mic brake, §4.7
#: How often the client-side pump wakes to re-check ``session.closed`` so an
#: operator DELETE terminates a live relay promptly (≤1 s) without waiting out
#: the full idle window.
_TERMINATION_POLL_SECONDS = 1.0
#: A minted session grant whose WebSocket never upgraded within this window is
#: reaped — an abandoned POST must not hold its concurrency slot forever.
UNCLAIMED_SESSION_TTL_SECONDS = 120.0

#: Only used when a Settings-like object lacks the fields entirely (tests).
DEFAULT_WARN_FALLBACK = 2.0


def _mesh_only_env_value(raw: Any) -> bool:
    return str(raw or "").strip().lower() in ("1", "true", "yes")


# ---------------------------------------------------------------------------
# Provider configuration resolution (R4)
# ---------------------------------------------------------------------------


def _operator_env_file_rows() -> dict[str, str]:
    """Rows from ``data/operator_api_keys.env``, read at call time."""
    try:
        from services.api_settings import OPERATOR_KEYS_ENV_PATH, _parse_env_file

        return _parse_env_file(OPERATOR_KEYS_ENV_PATH)
    except Exception:  # pragma: no cover - persistence layer must never break status
        return {}


def _merged_operator_env() -> dict[str, str]:
    """Process env wins over operator-file rows (matches get_settings order)."""
    merged = dict(_operator_env_file_rows())
    for key, value in os.environ.items():
        if value != "":
            merged[key] = value
    return merged


def _flag(value: Any) -> bool:
    return bool(str(value or "").strip())


def resolve_provider(settings=None) -> dict[str, Any]:
    """Resolve the voice provider from live env + operator env-file state.

    Never raises; unresolved providers yield a non-empty verbatim
    ``degradedReason`` instead (§4.3 honesty rule).
    """
    s = settings or get_settings()
    env = _merged_operator_env()

    requested_mode = str(getattr(s, "VOICE_PROVIDER", "auto") or "auto").strip().lower()
    openai_key_set = _flag(env.get("VOICE_OPENAI_API_KEY"))
    compat_key_set = _flag(env.get("VOICE_COMPAT_API_KEY"))
    compat_base_set = _flag(env.get("VOICE_COMPAT_BASE_URL"))
    openai_base = str(getattr(s, "VOICE_OPENAI_BASE_URL", "") or "").strip() or "https://api.openai.com"
    compat_base = str(env.get("VOICE_COMPAT_BASE_URL") or "").strip()

    candidates: list[str] = []
    if requested_mode in ("auto", ""):
        candidates = ["openai_realtime", "compatible_ws", "local_text"]
    elif requested_mode in ("openai_realtime", "compatible_ws", "local_text"):
        candidates = [requested_mode]
    else:
        candidates = ["openai_realtime", "compatible_ws", "local_text"]

    chat_model = str(getattr(s, "VOICE_CHAT_MODEL", "") or "").strip()
    chat_model_configured = _flag(chat_model)

    resolved: str | None = None
    for candidate in candidates:
        if candidate == "openai_realtime" and openai_key_set:
            resolved = "openai_realtime"
            break
        if candidate == "compatible_ws" and compat_base_set:
            resolved = "compatible_ws"
            break
        if candidate == "local_text" and chat_model_configured:
            resolved = "local_text"
            break

    reasons: list[str] = []
    enable_raw = str(getattr(s, "VOICE_AGENT_OUTBOUND_ENABLE", "block") or "block").strip().lower()
    ack_set = bool(getattr(s, "VOICE_AGENT_OUTBOUND_ACKNOWLEDGE", False))
    if enable_raw != "allow":
        reasons.append(
            "VOICE_AGENT_OUTBOUND_ENABLE is not 'allow' — two-step opt-in incomplete "
            "(docs/OUTBOUND_DATA.md)"
        )
    elif not ack_set:
        reasons.append(
            "VOICE_AGENT_OUTBOUND_ENABLE=allow without VOICE_AGENT_OUTBOUND_ACKNOWLEDGE=true — "
            "the AI voice agent remains disabled until you explicitly acknowledge that enabling it "
            "sends operator speech to the configured OpenAI-compatible endpoint "
            "(docs/OUTBOUND_DATA.md)."
        )

    degraded_reason: str | None = None
    if resolved is None:
        degraded_reason = (
            "No usable voice provider configured — set VOICE_OPENAI_API_KEY, "
            "VOICE_COMPAT_BASE_URL, or VOICE_CHAT_MODEL (+ VOICE_COMPAT_BASE_URL) for text-only."
        )
        reasons.append(degraded_reason)

    return {
        "resolved": resolved,
        "requestedMode": requested_mode,
        "openaiKeySet": openai_key_set,
        "compatKeySet": compat_key_set,
        "compatBaseUrlSet": compat_base_set,
        "chatModelConfigured": chat_model_configured,
        "degradedReason": degraded_reason,
        "reasons": reasons,
        # Upstream dial details — server-only; never serialized to clients.
        "openaiBase": openai_base,
        "compatBase": compat_base,
        "openaiKey": env.get("VOICE_OPENAI_API_KEY", ""),
        "compatKey": env.get("VOICE_COMPAT_API_KEY", ""),
        "chatModel": chat_model,
    }


def cost_limit_defaults(settings=None) -> dict[str, Any]:
    """JSON-safe warn/cap/daily-budget defaults for the status payload."""
    s = settings or get_settings()

    def encode(value: Any) -> Any:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "off"
        return number if number > 0 else "off"

    return {
        "warnUsd": encode(getattr(s, "VOICE_COST_WARN_USD", 0)),
        "capUsd": encode(getattr(s, "VOICE_COST_CAP_USD", 0)),
        "dailyBudgetUsd": encode(getattr(s, "VOICE_DAILY_BUDGET_USD", 0)),
    }


def daily_spend_view(settings=None, *, now=None) -> dict[str, Any]:
    """Today's persisted ledger projected into the status payload shape."""
    s = settings or get_settings()
    spend = read_daily_spend(now=now)
    raw_budget = getattr(s, "VOICE_DAILY_BUDGET_USD", 0.0)
    try:
        budget_val = float(raw_budget)
    except (TypeError, ValueError):
        budget_val = 0.0
    if budget_val != budget_val or budget_val < 0:  # NaN / negative → off
        budget_val = 0.0
    gate = evaluate_daily_budget(spend, raw_budget, now=now)
    return {
        "date": spend["date"],
        "usdSpent": spend["usdSpent"],
        "budgetUsd": "off" if budget_val <= 0 else round(budget_val, 4),
        "remainingUsd": gate["remainingUsd"],
        "ledgerQuarantined": bool(spend.get("ledgerQuarantined")),
        "_gate": gate,
    }


# ---------------------------------------------------------------------------
# Session registry (bounded, asyncio-relay + REST shared)
# ---------------------------------------------------------------------------


@dataclass
class VoiceSession:
    """One active voice session; created by POST /api/voice/session."""

    session_id: str
    tier: str
    requested_tier: str
    model_id: str
    provider: str
    limits: dict[str, Any]
    tokens_per_sec: int
    max_concurrent: int
    created_at: float = field(default_factory=time.time)
    tracker: VoiceCostTracker = None  # type: ignore[assignment]
    grounding_snapshot: dict[str, Any] | None = None
    client_patch: dict[str, Any] = field(default_factory=dict)
    closed: bool = False
    closed_reason: str | None = None
    #: True once the WebSocket upgrade succeeded — unclaimed grants are the
    #: only ones eligible for TTL reaping.
    ws_connected: bool = False
    #: Live upstream socket handle while a relay runs. Lets ``end_session``
    #: (operator DELETE kill switch) terminate an active relay immediately by
    #: closing the socket both pumps block on.
    relay_upstream: Any = None


_sessions: dict[str, VoiceSession] = {}
_sessions_lock = threading.Lock()


def active_session_count() -> int:
    with _sessions_lock:
        return len(_sessions)


def _reap_unclaimed_locked(now: float) -> None:
    """Drop sessions whose WebSocket never upgraded within the claim TTL.

    A minted grant that was abandoned (page closed before connect) would
    otherwise hold its concurrency slot permanently and exhaust the gate.
    Upgraded sessions never expire here — cost caps, the idle brake, and the
    operator kill switch own those. Caller holds ``_sessions_lock``.
    """
    stale = [
        session_id
        for session_id, session in _sessions.items()
        if not session.ws_connected and (now - session.created_at) > UNCLAIMED_SESSION_TTL_SECONDS
    ]
    for session_id in stale:
        session = _sessions.pop(session_id)
        session.closed = True
        session.closed_reason = "unclaimed_expired"
        logger.info(
            "voice session %s reaped unclaimed after %.0fs", session_id, UNCLAIMED_SESSION_TTL_SECONDS
        )


def get_session(session_id: str, *, now: float | None = None) -> VoiceSession | None:
    cleaned = str(session_id or "").strip()
    moment = time.time() if now is None else now
    with _sessions_lock:
        _reap_unclaimed_locked(moment)
        return _sessions.get(cleaned)


def _terminate_relay(session: VoiceSession) -> None:
    """Kill-switch half of termination: close the live upstream socket.

    Closing it unblocks ``pump_upstream_to_client``'s ``recv`` immediately;
    both pumps additionally poll ``session.closed`` each iteration, so a relay
    terminates even when no event loop is schedulable on this thread.
    """
    upstream = session.relay_upstream
    if upstream is None:
        return

    async def _close_quietly() -> None:
        try:
            await upstream.close()
        except Exception:
            pass

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # cross-thread caller — the closed-flag polls stop the pumps
    loop.create_task(_close_quietly())


def end_session(session_id: str, reason: str = "operator_delete") -> bool:
    cleaned = str(session_id or "").strip()
    with _sessions_lock:
        session = _sessions.pop(cleaned, None)
    if session is None:
        return False
    session.closed = True
    session.closed_reason = reason
    _terminate_relay(session)
    return True


def create_session(*, tier: str = "standard", settings=None) -> tuple[VoiceSession | None, dict[str, Any] | None]:
    """Create and register one session, enforcing the concurrency gate.

    Returns ``(session, None)`` or ``(None, {"error": "concurrency"})``.
    Provider/opt-in/budget gates belong to the route; this is the registry.
    """
    s = settings or get_settings()
    resolved_model = resolve_voice_model(tier)
    requested_tier = str(tier or "").strip().lower()
    limits = serialize_cost_limits(
        {
            "warnUsd": getattr(s, "VOICE_COST_WARN_USD", 0),
            "capUsd": getattr(s, "VOICE_COST_CAP_USD", 0),
        }
    )
    try:
        max_concurrent = max(1, int(getattr(s, "VOICE_MAX_CONCURRENT_SESSIONS", 1)))
    except (TypeError, ValueError):
        max_concurrent = 1
    try:
        tokens_per_sec = max(1, int(getattr(s, "VOICE_FALLBACK_AUDIO_TOKENS_PER_SEC", 50)))
    except (TypeError, ValueError):
        tokens_per_sec = 50

    with _sessions_lock:
        _reap_unclaimed_locked(time.time())
        if len(_sessions) >= max_concurrent:
            return None, {"error": "concurrency"}
        session = VoiceSession(
            session_id=str(uuid.uuid4()),
            tier=resolved_model.tier,
            requested_tier=requested_tier,
            model_id=resolved_model.id,
            provider="",  # stamped by the route once the provider resolves
            limits=limits,
            tokens_per_sec=tokens_per_sec,
            max_concurrent=max_concurrent,
        )
        session.tracker = VoiceCostTracker(
            model_id=resolved_model.id,
            # Raw values — VoiceCostTracker.__init__ is the single normalization
            # authority (corrupt restores default, never disarms; U1 invariant).
            limits={
                "warnUsd": getattr(s, "VOICE_COST_WARN_USD", DEFAULT_WARN_FALLBACK),
                "capUsd": getattr(s, "VOICE_COST_CAP_USD", DEFAULT_WARN_FALLBACK * 2.5),
            },
        )
        _sessions[session.session_id] = session
    return session, None


# ---------------------------------------------------------------------------
# Server-authored session config (§4.3 — single sanctioned injection point)
# ---------------------------------------------------------------------------


def validate_grounding_snapshot(snapshot: Any) -> dict[str, Any] | None:
    """Schema-check a client-supplied ``sb.grounding.v1`` snapshot.

    Returns the snapshot when acceptable, otherwise None (caller emits
    ``bad_frame``). Size-capped at the §2.4 6 KB serialization limit.
    """
    if not isinstance(snapshot, dict):
        return None
    try:
        encoded = json.dumps(snapshot, separators=(",", ":"))
    except (TypeError, ValueError):
        return None
    if len(encoded.encode("utf-8")) > GROUNDING_SNAPSHOT_MAX_BYTES:
        return None
    if snapshot.get("schema") != GROUNDING_SCHEMA_ID:
        return None
    if not isinstance(snapshot.get("view"), dict):
        return None
    layers = snapshot.get("layers")
    if not isinstance(layers, dict):
        return None
    return snapshot


def _manifest_tool_defs() -> list[dict[str, Any]]:
    """Realtime tool definitions from the §3 unified manifest (lazy import)."""
    try:
        from services.voice_tool_registry import build_manifest

        tools = []
        for entry in build_manifest(include_client=True):
            tools.append(
                {
                    "type": "function",
                    "name": entry["name"],
                    "description": str(entry.get("description") or ""),
                    "parameters": entry.get("parameters") or {"type": "object", "properties": {}},
                }
            )
        return tools
    except Exception as exc:  # manifest problems must not kill the media pipe
        logger.warning("voice session-config tool manifest unavailable: %s", exc)
        return []


def build_session_config(session: VoiceSession) -> dict[str, Any]:
    """Author the FULL upstream ``session.update`` payload server-side.

    Model, instructions hook, tools (from the §3 manifest), VAD, truncation,
    and audio formats are all decided here. The most recent accepted
    ``context.grounding`` snapshot rides along as ``context.grounding`` so
    per-turn view context has a defined transport in every mode.
    """
    config: dict[str, Any] = {
        "type": "session.update",
        "session": {
            "model": session.model_id,
            "instructions": "",  # NARRATE/ACT prompt content lands here (U5 hook)
            "tools": _manifest_tool_defs(),
            "input_audio_format": {"type": "pcm16", "sample_rate": AUDIO_SAMPLE_RATE},
            "output_audio_format": {"type": "pcm16", "sample_rate": AUDIO_SAMPLE_RATE},
            "input_audio_transcription": {"model": "whisper-1"},
            "turn_detection": {
                "type": "server_vad",
                "threshold": 0.5,
                "prefix_padding_ms": 300,
                "silence_duration_ms": 500,
            },
        },
    }
    voice = str(getattr(get_settings(), "VOICE_REALTIME_VOICE", "alloy") or "alloy").strip()
    if voice:
        config["session"]["voice"] = voice
    # Client allow-listed patch keys win over defaults — nothing else does.
    for key, value in session.client_patch.items():
        config["session"][key] = value
    if session.grounding_snapshot is not None:
        config["context.grounding"] = session.grounding_snapshot
    return config


def merge_client_patch(session: VoiceSession, patch: Any) -> tuple[dict[str, Any], list[str]]:
    """Merge a client ``session.update`` patch against the allow-list.

    Returns ``(accepted_subset, rejected_keys)``; the session's stored patch is
    updated in place and re-sent upstream by the relay.
    """
    if not isinstance(patch, dict):
        return {}, []
    accepted: dict[str, Any] = {}
    rejected: list[str] = []
    for key, value in patch.items():
        if key in CLIENT_PATCH_ALLOWLIST:
            accepted[key] = value
        else:
            rejected.append(str(key))
    if accepted:
        session.client_patch.update(accepted)
    return accepted, rejected


# ---------------------------------------------------------------------------
# Realtime WS relay (framing translator + metering tap)
# ---------------------------------------------------------------------------


def _ws_url_for(provider_info: dict[str, Any], model_id: str) -> tuple[str, dict[str, str]]:
    """Build (url, headers) for the upstream realtime dial."""
    if provider_info["resolved"] == "openai_realtime":
        base = str(provider_info["openaiBase"]).rstrip("/")
        url = base.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
        if not url.endswith("/v1"):
            url = f"{url}/v1"
        headers = {"Authorization": f"Bearer {provider_info['openaiKey']}", "OpenAI-Beta": "realtime=v1"}
    else:
        base = str(provider_info["compatBase"]).rstrip("/")
        url = base.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
        headers = {}
        if provider_info["compatKey"]:
            headers["Authorization"] = f"Bearer {provider_info['compatKey']}"
    return f"{url}/realtime?model={model_id}", headers


async def _connect_upstream(url: str, headers: dict[str, str]):
    """Sole ``websockets`` call site (R1). Monkeypatched by tests."""
    from websockets.asyncio.client import connect

    return await connect(url, additional_headers=headers, max_size=None)


def _pcm_seconds(num_bytes: int) -> float:
    """PCM16 mono @ 24 kHz ⇒ 2 bytes per sample; bytes ÷ (2 × 24000) = seconds."""
    return num_bytes / (2 * AUDIO_SAMPLE_RATE)


class _RelayState:
    """Per-relay bookkeeping: violations, metered seconds, latches."""

    def __init__(self, session: VoiceSession) -> None:
        self.session = session
        self.violations = 0
        self.input_audio_bytes = 0
        self.output_audio_bytes = 0
        self.response_open = False
        self.upstream: Any = None
        self.cap_sent = False

    async def send_json(self, client_ws: Any, payload: dict[str, Any]) -> None:
        try:
            await client_ws.send_text(json.dumps(payload))
        except Exception:
            pass

    async def register_violation(self, client_ws: Any, code: str, detail: str) -> bool:
        """Record one protocol violation; True ⇒ relay must close now."""
        self.violations += 1
        await self.send_json(
            client_ws,
            {"type": "error", "code": "bad_frame", "detail": code, "message": detail},
        )
        return self.violations >= VIOLATIONS_BEFORE_CLOSE

    async def meter_response_done(self, client_ws: Any, usage: Any) -> None:
        """Fold one ``response.done`` into the tracker + daily ledger."""
        session = self.session
        snapshot_before = session.tracker.state()
        if usage:
            snapshot = session.tracker.record(usage)
        else:
            # Tier-2 conservative estimator: bill counted audio seconds at the
            # session's resolved VOICE_FALLBACK_AUDIO_TOKENS_PER_SEC rate.
            snapshot = session.tracker.record(
                None,
                input_audio_s=_pcm_seconds(self.input_audio_bytes),
                output_audio_s=_pcm_seconds(self.output_audio_bytes),
                tokens_per_sec=session.tokens_per_sec,
            )
        self.input_audio_bytes = 0
        self.output_audio_bytes = 0
        self.response_open = False

        delta = max(0.0, snapshot.total_usd - snapshot_before.total_usd)
        try:
            record_response(usd=delta, fallback_metered=bool(snapshot.estimated))
        except Exception as exc:  # ledger failure must never break media
            logger.warning("voice daily-ledger update failed: %s", exc)

        await self.send_json(client_ws, {"type": "cost", "snapshot": _public_snapshot(snapshot)})
        if snapshot.warn_crossed:
            await self.send_json(client_ws, {"type": "warn", "totalUsd": round(snapshot.total_usd, 6)})
        if snapshot.cap_crossed or snapshot.cap_reached:
            self.cap_sent = True
            await self.send_json(
                client_ws,
                {"type": "cap", "totalUsd": round(snapshot.total_usd, 6), "reason": "cost cap reached"},
            )


def _public_snapshot(snapshot: Any) -> dict[str, Any]:
    """Smallest owned JSON view of a CostSnapshot for the client."""
    return {
        "totalUsd": round(snapshot.total_usd, 6),
        "display": snapshot.display,
        "level": snapshot.level,
        "ratesRecognized": snapshot.rates_recognized,
        "estimated": snapshot.estimated,
        "incomplete": snapshot.incomplete,
        "note": snapshot.note,
    }


async def _drain_binary_to_upstream(state: _RelayState, pcm: bytes) -> None:
    state.input_audio_bytes += len(pcm)
    await state.upstream.send(
        json.dumps(
            {
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(pcm).decode("ascii"),
            }
        )
    )


async def _receive_with_termination_brake(
    client_ws: Any,
    state: _RelayState,
    idle_timeout: float,
) -> Any:
    """Receive one message, waking at least once per poll interval.

    Returns the received message, or a sentinel ``{"type": "idle.timeout"}`` /
    ``{"type": "session.closed"}`` so an operator DELETE terminates a live
    relay within ~1 s instead of after the full 90 s idle window.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + idle_timeout
    while True:
        if state.session.closed:
            return {"type": "session.closed"}
        remaining = deadline - loop.time()
        if remaining <= 0:
            return {"type": "idle.timeout"}
        try:
            return await asyncio.wait_for(
                client_ws.receive(), timeout=min(_TERMINATION_POLL_SECONDS, remaining)
            )
        except asyncio.TimeoutError:
            continue  # slice boundary — re-check session.closed promptly
        except Exception:
            return {"type": "websocket.disconnect"}


async def pump_client_to_upstream(
    client_ws: Any,
    state: _RelayState,
    *,
    idle_timeout: float = IDLE_TIMEOUT_SECONDS,
) -> str:
    """Translate client frames onto the upstream socket.

    Returns a stop reason: ``client_disconnected`` | ``stop_frame`` |
    ``protocol_violation`` | ``idle_timeout`` | ``session_closed``.
    """
    while True:
        message = await _receive_with_termination_brake(client_ws, state, idle_timeout)

        mtype = message.get("type") if isinstance(message, dict) else None
        if mtype == "websocket.disconnect":
            return "client_disconnected"
        if mtype == "idle.timeout":
            return "idle_timeout"
        if mtype == "session.closed":
            return "session_closed"

        if message.get("bytes") is not None:
            pcm = message["bytes"]
            if state.cap_sent or not isinstance(pcm, (bytes, bytearray)) or len(pcm) > MAX_BINARY_FRAME_BYTES:
                if state.cap_sent:
                    continue  # drain silently after cap (R5)
                if await state.register_violation(
                    client_ws, "oversize_binary_frame", "binary frames must be ≤ 65536 bytes"
                ):
                    return "protocol_violation"
                continue
            if state.upstream is not None:
                try:
                    await _drain_binary_to_upstream(state, bytes(pcm))
                except Exception:
                    return "client_disconnected"
            continue

        text = message.get("text")
        if text is None:
            continue
        try:
            frame = json.loads(text)
            if not isinstance(frame, dict):
                raise ValueError("frame must be a JSON object")
        except ValueError:
            if await state.register_violation(
                client_ws, "non_json_text_frame", "text frames must be JSON objects"
            ):
                return "protocol_violation"
            continue

        frame_type = str(frame.get("type") or "")
        if frame_type not in CLIENT_FRAME_TYPES:
            if await state.register_violation(
                client_ws, "unknown_frame_type", f"frame type not allowed: {frame_type!r}"
            ):
                return "protocol_violation"
            continue

        if frame_type == "stop":
            return "stop_frame"
        if frame_type == "session.update":
            accepted, rejected = merge_client_patch(state.session, frame.get("patch"))
            if rejected:
                # Honest feedback; the server-authored config stays authoritative.
                await state.send_json(
                    client_ws,
                    {"type": "error", "code": "patch_rejected", "keys": sorted(rejected)},
                )
            if state.upstream is not None and accepted:
                try:
                    await state.upstream.send(json.dumps(build_session_config(state.session)))
                except Exception:
                    return "client_disconnected"
            continue
        if frame_type == "context.grounding":
            snapshot = validate_grounding_snapshot(frame.get("snapshot"))
            if snapshot is None:
                if await state.register_violation(
                    client_ws,
                    "grounding_snapshot_invalid",
                    f"context.grounding requires a ≤{GROUNDING_SNAPSHOT_MAX_BYTES}B "
                    f"{GROUNDING_SCHEMA_ID} object",
                ):
                    return "protocol_violation"
                continue
            state.session.grounding_snapshot = snapshot
            continue


async def pump_upstream_to_client(client_ws: Any, state: _RelayState) -> str:
    """Tap the untouched provider stream: meter, translate audio, forward.

    Returns ``upstream_closed`` | ``capped`` | ``session_closed``.
    """
    while True:
        if state.session.closed:
            # Operator DELETE (or reap) ended the session mid-relay.
            return "session_closed"
        try:
            raw = await state.upstream.recv()
        except Exception:
            return "upstream_closed"
        if raw is None:
            return "upstream_closed"

        if isinstance(raw, (bytes, bytearray)):
            # The broker is a dumb pipe for bytes: upstream binary would already
            # be a protocol deviation for these providers — count as violation.
            if await state.register_violation(
                client_ws, "unexpected_binary_frame", "upstream sent binary media outside audio events"
            ):
                return "capped" if state.cap_sent else "upstream_closed"
            continue

        try:
            event = json.loads(raw)
        except ValueError:
            # Non-JSON upstream chatter is forwarded verbatim; it is not client
            # protocol traffic and cannot corrupt our state machine.
            try:
                await client_ws.send_text(raw)
            except Exception:
                pass
            continue

        event_type = str(event.get("type") or "")
        if event_type == "response.audio.delta":
            audio_b64 = event.get("delta")
            pcm = _decode_audio_payload(audio_b64)
            if pcm is not None:
                state.output_audio_bytes += len(pcm)
                try:
                    await client_ws.send_bytes(pcm)
                except Exception:
                    return "upstream_closed"
            continue
        if event_type == "response.audio":
            pcm = _decode_audio_payload(event.get("audio"))
            if pcm is not None:
                state.output_audio_bytes += len(pcm)
                try:
                    await client_ws.send_bytes(pcm)
                except Exception:
                    return "upstream_closed"
            continue
        if event_type == "response.created":
            state.response_open = True

        # Everything else forwards VERBATIM — the client tool-picker sees the
        # untouched provider stream, including the cap-crossing response.done.
        try:
            await client_ws.send_text(raw)
        except Exception:
            return "upstream_closed"

        if event_type == "response.done":
            await state.meter_response_done(client_ws, event.get("response", {}).get("usage"))
            if state.cap_sent:
                return "capped"


def _decode_audio_payload(payload: Any) -> bytes | None:
    """Base64-decode an upstream audio payload to raw PCM16 LE. No resampling."""
    if not isinstance(payload, str) or not payload:
        return None
    try:
        return base64.b64decode(payload, validate=False)
    except Exception:
        return None


async def run_realtime_relay(client_ws: Any, session: VoiceSession, settings=None) -> None:
    """Run one realtime session: connect upstream, author config, translate.

    Accepts any duck-typed ``client_ws`` exposing ``send_text`` / ``send_bytes``
    / ``receive`` (FastAPI WebSocket or a test fake).
    """
    s = settings or get_settings()
    provider_info = resolve_provider(s)
    state = _RelayState(session)
    # The upgrade gate passed: this grant is claimed and no longer reapable.
    session.ws_connected = True

    if provider_info["resolved"] is None:
        end_session(session.session_id, "unconfigured")
        await state.send_json(
            client_ws,
            {"type": "upstream.error", "status": 503, "detail": provider_info["degradedReason"]},
        )
        await state.send_json(client_ws, {"type": "closed", "reason": "unconfigured"})
        return

    url, headers = _ws_url_for(provider_info, session.model_id)
    try:
        state.upstream = await _connect_upstream(url, headers)
    except Exception as exc:
        logger.warning("voice upstream connect failed: %s", type(exc).__name__)
        end_session(session.session_id, "upstream_unavailable")
        await state.send_json(
            client_ws,
            {"type": "upstream.error", "status": 502, "detail": f"upstream connect failed: {type(exc).__name__}"},
        )
        await state.send_json(client_ws, {"type": "closed", "reason": "upstream_unavailable"})
        return
    # Register the live socket so the operator DELETE kill switch can close it
    # mid-relay (see _terminate_relay); cleared again in _teardown.
    session.relay_upstream = state.upstream

    session.provider = provider_info["resolved"]
    limits_public = {
        "warnUsd": session.limits["warnUsd"],
        "capUsd": session.limits["capUsd"],
        "maxConcurrent": session.max_concurrent,
    }
    await state.send_json(
        client_ws,
        {
            "type": "ready",
            "sessionId": session.session_id,
            "provider": session.provider,
            "model": session.model_id,
            "upstreamConnected": True,
            "limits": limits_public,
            "audio": {
                "format": "pcm16",
                "sampleRate": AUDIO_SAMPLE_RATE,
                "channels": AUDIO_CHANNELS,
            },
        },
    )
    try:
        await state.upstream.send(json.dumps(build_session_config(session)))
    except Exception:
        await _teardown(client_ws, state, "upstream_unavailable")
        return

    client_task = asyncio.ensure_future(pump_client_to_upstream(client_ws, state))
    upstream_task = asyncio.ensure_future(pump_upstream_to_client(client_ws, state))
    try:
        done, pending = await asyncio.wait(
            {client_task, upstream_task}, return_when=asyncio.FIRST_COMPLETED
        )
        stop_reasons = [task.result() for task in done if not task.cancelled()]
        capped = "capped" in stop_reasons
        protocol_violation = "protocol_violation" in stop_reasons
        # The session was ended externally (operator DELETE kill switch) — the
        # pumps observed it via the closed flag or the upstream socket close.
        terminated = state.session.closed and state.session.closed_reason == "operator_delete"
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.wait(pending, timeout=5)

        if capped and not state.cap_sent:
            # Cap raised by a path that did not emit yet (defensive).
            state.cap_sent = True
            snapshot = session.tracker.state()
            await state.send_json(
                client_ws,
                {"type": "cap", "totalUsd": round(snapshot.total_usd, 6), "reason": "cost cap reached"},
            )
        if capped and state.upstream is not None:
            # Enforcement is broker-side: close the upstream socket and drain.
            try:
                await state.upstream.close()
            except Exception:
                pass
        if protocol_violation:
            await _teardown(client_ws, state, "protocol_violation", close_code=4400)
        else:
            reason = "capped" if capped else "terminated" if terminated else "completed"
            await _teardown(client_ws, state, reason)
    finally:
        for task in (client_task, upstream_task):
            if not task.done():
                task.cancel()


async def _teardown(
    client_ws: Any,
    state: _RelayState,
    reason: str,
    *,
    close_code: int | None = None,
) -> None:
    session = state.session
    if state.response_open:
        snapshot = session.tracker.mark_incomplete()
        try:
            record_response(incomplete=True)
        except Exception as exc:
            logger.warning("voice daily-ledger incomplete-mark failed: %s", exc)
        del snapshot
    if state.upstream is not None:
        try:
            await state.upstream.close()
        except Exception:
            pass
    session.relay_upstream = None
    end_session(session.session_id, reason)
    await state.send_json(client_ws, {"type": "closed", "reason": reason})
    try:
        await client_ws.close(code=close_code) if close_code else await client_ws.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# local_text chat leg (§4.3 text fallback)
# ---------------------------------------------------------------------------

CHAT_CONTEXT_MAX_BYTES = 32 * 1024


def _usage_token(usage: Any, keys: tuple[str, ...]) -> float:
    """First positive value among ``keys`` on a chat-completions usage dict."""
    for key in keys:
        try:
            number = float(usage.get(key))
        except (TypeError, ValueError, AttributeError):
            continue
        if number > 0:
            return number
    return 0.0


def _meter_chat_usage(model_id: str, usage: Any) -> None:
    """Bill one typed-text turn into the persisted daily ledger (§4.1/§4.2).

    Metering is unconditional across all modes — the degraded typed-text leg
    is no exception when the provider returns usage. Chat traffic is text
    tokens, billed against the U1 rate table for the model actually served
    (an unknown id bills at worst-case rates). Never fails the chat turn.
    """
    try:
        prompt = _usage_token(usage, ("prompt_tokens", "input_tokens"))
        completion = _usage_token(usage, ("completion_tokens", "output_tokens"))
        if prompt <= 0 and completion <= 0:
            return
        realtime_usage = {
            "input_tokens": prompt,
            "output_tokens": completion,
            "input_token_details": {"text_tokens": prompt},
            "output_token_details": {"text_tokens": completion},
        }
        usd = estimate_usage_cost_usd(realtime_usage, resolve_voice_model_by_id(model_id).rates)
        if usd > 0:
            record_response(usd=usd)
    except Exception as exc:
        logger.warning("voice chat-leg metering failed: %s", exc)


async def chat_completion(messages: list[dict[str, str]], settings=None) -> dict[str, Any]:
    """Proxy one chat-completions turn to the configured endpoint.

    Returns ``{"ok": True, "reply", "model", "usage"?}`` or a typed error
    envelope ``{"ok": False, "error", "detail"?}``. Sole third-party dial for
    the degraded typed-text channel.
    """
    s = settings or get_settings()
    provider = resolve_provider(s)
    if not provider["chatModelConfigured"]:
        return {"ok": False, "error": "chat_unconfigured"}

    base = provider["compatBase"] or provider["openaiBase"]
    base = str(base).rstrip("/")
    api_key = provider["compatKey"] or provider["openaiKey"]

    import httpx

    payload = {"model": provider["chatModel"], "messages": messages}
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(f"{base}/chat/completions", json=payload, headers=headers)
    except httpx.HTTPError as exc:
        return {"ok": False, "error": "upstream_unreachable", "detail": type(exc).__name__}

    if response.status_code >= 400:
        return {
            "ok": False,
            "error": "upstream_error",
            "status": response.status_code,
            "detail": response.text[:500],
        }
    try:
        body = response.json()
        reply = body["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        return {"ok": False, "error": "upstream_malformed_response"}
    result: dict[str, Any] = {"ok": True, "reply": reply, "model": provider["chatModel"]}
    usage = body.get("usage")
    if isinstance(usage, dict):
        result["usage"] = usage
        _meter_chat_usage(provider["chatModel"], usage)
    return result
