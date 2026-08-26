"""Operator-console AI voice agent routes (voice-agent plan §4/§3.3).

Hosts ALL ``/api/voice/*`` endpoints: status, session issue/delete, the
realtime WS relay, the typed-text chat fallback, and the §3.3 one-line mounts
of the U3 unified tool registry endpoints.

Import-topology rules (§1.5, AST freeze): module-level imports are limited to
stdlib / fastapi / pydantic / auth / limiter / pure services. Heavy imports
(``httpx``, ``websockets``, ``services.voice_broker``) happen inside function
bodies. ``main`` is never imported at module level.

Lean-mode defense-in-depth: this module checks ``MESH_ONLY`` at import with
the canonical idiom (same expression as ``main.py:23``) and refuses route
registration in lean mode — a lean node exposes no voice surface even if the
router module somehow loads.
"""
# NOTE: no ``from __future__ import annotations`` here — it would turn the
# route handlers' parameter annotations into strings that FastAPI cannot
# resolve against these function-scope Pydantic models (``body`` would be
# misread as a query parameter and every JSON POST would fail with 422).
# Python 3.11 evaluates ``X | None`` unions natively at runtime.

import json
import logging
import os
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from auth import require_local_operator
from limiter import limiter

logger = logging.getLogger(__name__)

_MESH_ONLY = os.environ.get("MESH_ONLY", "").strip().lower() in ("1", "true", "yes")

router = APIRouter(tags=["voice"])

if _MESH_ONLY:
    logger.warning(
        "routers.voice loaded under MESH_ONLY lean mode — refusing voice route "
        "registration (the operator console voice agent is hard-absent on lean nodes)"
    )
else:

    # ------------------------------------------------------------------
    # Models
    # ------------------------------------------------------------------

    class VoiceSessionRequest(BaseModel):
        tier: str = Field(default="standard")
        mode: str = Field(default="realtime")

    class VoiceChatRequest(BaseModel):
        text: str = Field(min_length=1)
        history: list[dict] = Field(default_factory=list)

    class VoiceToolCallRequest(BaseModel):
        tool: str
        args: dict = Field(default_factory=dict)
        confirm_expensive: bool = False
        confirm: bool = False

    class VoiceHudSummaryRequest(BaseModel):
        snapshot: dict = Field(default_factory=dict)
        question: str = ""

    class VoiceTurnRequest(BaseModel):
        text: str = Field(min_length=1, max_length=2000)
        snapshot: dict | None = None
        history: list[dict] = Field(default_factory=list)

    class VoiceInterrogateRequest(BaseModel):
        question: str = Field(min_length=1, max_length=2000)
        target: dict | None = None
        snapshot: dict | None = None
        sessionId: str = ""

    class VoiceOptInRequest(BaseModel):
        enable: bool

    class VoiceProviderRequest(BaseModel):
        provider: str  # "openai" | "gemini" | "compat"
        apiKey: str | None = None
        baseUrl: str | None = None
        model: str | None = None  # gemini: VOICE_GEMINI_MODEL; compat: VOICE_CHAT_MODEL

    # ------------------------------------------------------------------
    # Shared helpers (heavy imports stay inside function bodies)
    # ------------------------------------------------------------------
    def _opt_in_state(settings) -> tuple[bool, str, dict]:
        """(effective, opt_in_state, flags) per §4.3 merged status schema."""
        enable_raw = str(getattr(settings, "VOICE_AGENT_OUTBOUND_ENABLE", "block") or "").strip()
        ack_set = bool(getattr(settings, "VOICE_AGENT_OUTBOUND_ACKNOWLEDGE", False))
        requested = enable_raw.lower() == "allow"
        flags = {"enableSet": requested, "acknowledgeSet": ack_set}
        from services.config import voice_outbound_effective

        effective = voice_outbound_effective(settings)
        if not requested:
            state = "not_requested"
        elif not ack_set:
            state = "requested_not_acknowledged"
        else:
            state = "enabled"
        return effective, state, flags

    def _mesh_mode() -> str:
        return "mesh_lean" if os.environ.get("MESH_ONLY", "").strip().lower() in ("1", "true", "yes") else "full"

    def _settings():
        from services.config import get_settings

        return get_settings()

    def _opt_in_refusal_payload(reasons: list[str]) -> dict:
        return {
            "error": "opt_in_required",
            "detail": reasons[0] if reasons else "Voice agent is disabled by configuration",
            "reasons": reasons,
        }

    def _budget_gate(settings):
        """Gate 3 — persisted daily-budget governor (§2.7 "429 latched cap").

        Shared by EVERY voice LLM surface (session mint, hud-summary briefs and
        picker turns): a capped operator must not be able to keep generating.
        Returns ``(refusal_or_None, gate)`` so callers can still read
        ``gate["suggestTier"]`` on the allowed path.
        """
        from services.voice_broker import daily_spend_view
        from services.voice_daily_budget import evaluate_daily_budget

        gate = evaluate_daily_budget(
            daily_spend_view(settings),
            getattr(settings, "VOICE_DAILY_BUDGET_USD", 0.0),
            mini_configured=bool(str(getattr(settings, "VOICE_MODEL_MINI", "") or "").strip()),
        )
        if gate["allowed"]:
            return None, gate
        retry_after = 3600
        try:
            resets_at = datetime.fromisoformat(gate["resetsAt"])
            retry_after = max(60, int((resets_at - datetime.now(timezone.utc)).total_seconds()))
        except Exception:
            pass
        refusal = JSONResponse(
            status_code=429,
            headers={"Retry-After": str(retry_after)},
            content={"error": "budget", "resetsAt": gate["resetsAt"]},
        )
        return refusal, gate

    # ------------------------------------------------------------------
    # GET /api/voice/status — powers mic-button states; never 500s
    # ------------------------------------------------------------------

    @router.get("/api/voice/status", dependencies=[Depends(require_local_operator)])
    @limiter.limit("10/minute")
    async def voice_status(request: Request):
        from services.voice_broker import active_session_count, cost_limit_defaults, daily_spend_view, resolve_provider

        try:
            s = _settings()
            effective, opt_in_state, flags = _opt_in_state(s)
            provider = resolve_provider(s)
            spend = daily_spend_view(s)
            try:
                max_concurrent = max(1, int(getattr(s, "VOICE_MAX_CONCURRENT_SESSIONS", 1)))
            except (TypeError, ValueError):
                max_concurrent = 1
            return {
                "ok": True,
                "effectiveEnable": effective,
                "opt_in_state": opt_in_state,
                "flags": flags,
                "provider": {
                    "resolved": provider["resolved"],
                    "requestedMode": provider["requestedMode"],
                    "openaiKeySet": provider["openaiKeySet"],
                    "compatKeySet": provider["compatKeySet"],
                    "compatBaseUrlSet": provider["compatBaseUrlSet"],
                    "geminiKeySet": bool(provider.get("geminiKeySet", False)),
                    "chatModelConfigured": provider["chatModelConfigured"],
                },
                "degradedReason": provider["degradedReason"],
                "reasons": provider["reasons"],
                "mode": _mesh_mode(),
                "costDefaults": cost_limit_defaults(s),
                "dailySpend": {
                    "date": spend["date"],
                    "usdSpent": spend["usdSpent"],
                    "budgetUsd": spend["budgetUsd"],
                    "remainingUsd": spend["remainingUsd"],
                    "ledgerQuarantined": spend["ledgerQuarantined"],
                },
                "activeSessions": active_session_count(),
                "maxConcurrent": max_concurrent,
            }
        except Exception as exc:  # status NEVER 500s (§4.3)
            logger.warning("voice status degraded: %s", type(exc).__name__)
            return {
                "ok": True,
                "effectiveEnable": False,
                "opt_in_state": "not_requested",
                "flags": {"enableSet": False, "acknowledgeSet": False},
                "provider": {
                    "resolved": None,
                    "requestedMode": "auto",
                    "openaiKeySet": False,
                    "compatKeySet": False,
                    "compatBaseUrlSet": False,
                    "geminiKeySet": False,
                    "chatModelConfigured": False,
                },
                "degradedReason": f"status unavailable: {type(exc).__name__}",
                "reasons": [f"status unavailable: {type(exc).__name__}"],
                "mode": _mesh_mode(),
                "costDefaults": {"warnUsd": "off", "capUsd": "off", "dailyBudgetUsd": "off"},
                "dailySpend": {
                    "date": "",
                    "usdSpent": 0.0,
                    "budgetUsd": "off",
                    "remainingUsd": "off",
                    "ledgerQuarantined": False,
                },
                "activeSessions": 0,
                "maxConcurrent": 1,
            }

    # ------------------------------------------------------------------
    # POST /api/voice/opt-in + POST /api/voice/provider — first-class
    # enablement API (pressable buttons in the UI). Both persist through the
    # sanctioned operator-keys writer and preserve the two-step semantics:
    # a real process environment variable ALWAYS wins over the persisted
    # file row, and that fact is reported verbatim-honestly.
    # ------------------------------------------------------------------

    def _persist_voice_env(updates: dict[str, str]) -> tuple[bool, list[str]]:
        """Persist voice settings via the sanctioned writer and sync live env.

        Mirrors the env-var-wins contract of load_persisted_api_keys_into_environ:
        if a key already has a real process-env value that did NOT come from the
        persisted file (env value differs from the file's previous row), the file
        write cannot win in this process — that key is left untouched and reported.
        Returns ``(written, externally_managed_keys)``.
        """
        from services.api_settings import (
            OPERATOR_KEYS_ENV_PATH,
            _parse_env_file,
            _write_env_values,
        )

        previous_rows = _parse_env_file(OPERATOR_KEYS_ENV_PATH)
        try:
            _write_env_values(OPERATOR_KEYS_ENV_PATH, updates)
        except OSError:
            logger.exception("voice setup: failed to persist %s", sorted(updates))
            return False, []
        externally_managed: list[str] = []
        for key, value in updates.items():
            env_val = str(os.environ.get(key, "") or "")
            file_val = str(previous_rows.get(key, "") or "")
            if env_val.strip() and env_val != file_val:
                externally_managed.append(key)
                continue
            os.environ[key] = value
        return True, externally_managed

    def _fresh_opt_in_payload(managed: list[str]) -> dict:
        from services.config import get_settings, voice_outbound_effective

        get_settings.cache_clear()
        payload: dict = {
            "ok": True,
            "effectiveEnable": voice_outbound_effective(get_settings()),
            "managedByEnvironment": bool(managed),
        }
        if managed:
            payload["note"] = (
                f"A real environment variable controls {', '.join(sorted(managed))}; "
                "environment variables always win over the persisted operator file "
                "(data/operator_api_keys.env), so this change cannot take effect for "
                "those keys until the variable is removed from the container/process "
                "environment."
            )
        return payload

    @router.post("/api/voice/opt-in", dependencies=[Depends(require_local_operator)])
    @limiter.limit("10/minute")
    async def voice_opt_in(request: Request, body: VoiceOptInRequest):
        """Persist one step of the two-step opt-in: ``enable=true`` writes
        VOICE_AGENT_OUTBOUND_ENABLE=allow AND VOICE_AGENT_OUTBOUND_ACKNOWLEDGE=true
        together (the UI button is the explicit acknowledgment); ``enable=false``
        writes block/false. Two-step semantics are unchanged: effectiveEnable is
        recomputed fresh from settings after the persist."""
        written, managed = _persist_voice_env({
            "VOICE_AGENT_OUTBOUND_ENABLE": "allow" if body.enable else "block",
            "VOICE_AGENT_OUTBOUND_ACKNOWLEDGE": "true" if body.enable else "false",
        })
        if not written:
            return JSONResponse(status_code=500, content={"ok": False, "error": "persist_failed"})
        return _fresh_opt_in_payload(managed)

    @router.post("/api/voice/provider", dependencies=[Depends(require_local_operator)])
    @limiter.limit("10/minute")
    async def voice_provider_save(request: Request, body: VoiceProviderRequest):
        """Persist provider credentials server-side (the browser never holds a
        provider key). Responds with is_set booleans only — never echoes the key."""
        from services.voice_broker import resolve_provider

        provider = str(body.provider or "").strip().lower()
        api_key = str(body.apiKey or "").strip()
        base_url = str(body.baseUrl or "").strip()

        updates: dict[str, str] = {}
        if provider == "openai":
            if not api_key:
                return JSONResponse(
                    status_code=400,
                    content={"ok": False, "error": "missing_field", "field": "apiKey"},
                )
            updates["VOICE_OPENAI_API_KEY"] = api_key
        elif provider == "gemini":
            if not api_key:
                return JSONResponse(
                    status_code=400,
                    content={"ok": False, "error": "missing_field", "field": "apiKey"},
                )
            updates["VOICE_GEMINI_API_KEY"] = api_key
            model = str(body.model or "").strip()
            if model:
                updates["VOICE_GEMINI_MODEL"] = model
        elif provider == "compat":
            if not base_url:
                return JSONResponse(
                    status_code=400,
                    content={"ok": False, "error": "missing_field", "field": "baseUrl"},
                )
            updates["VOICE_COMPAT_BASE_URL"] = base_url
            if api_key:
                updates["VOICE_COMPAT_API_KEY"] = api_key
            # Persist the chat-model row too (setup card's model field) so
            # local_text/chat resolution survives restarts.
            model = str(body.model or "").strip()
            if model:
                updates["VOICE_CHAT_MODEL"] = model
        else:
            return JSONResponse(
                status_code=400,
                content={"ok": False, "error": "unknown_provider", "provider": provider},
            )

        written, _managed = _persist_voice_env(updates)
        if not written:
            return JSONResponse(status_code=500, content={"ok": False, "error": "persist_failed"})

        from services.config import get_settings

        get_settings.cache_clear()
        summary = resolve_provider(get_settings())
        return {
            "ok": True,
            "provider": {
                "resolved": summary["resolved"],
                "requestedMode": summary["requestedMode"],
                "openaiKeySet": summary["openaiKeySet"],
                "compatKeySet": summary["compatKeySet"],
                "compatBaseUrlSet": summary["compatBaseUrlSet"],
                "geminiKeySet": bool(summary.get("geminiKeySet", False)),
                "chatModelConfigured": summary["chatModelConfigured"],
            },
            "degradedReason": summary["degradedReason"],
        }

    # ------------------------------------------------------------------
    # POST /api/voice/session — mint one short-lived session grant
    # ------------------------------------------------------------------

    @router.post("/api/voice/session", status_code=201, dependencies=[Depends(require_local_operator)])
    @limiter.limit("10/minute")
    async def create_voice_session(request: Request, body: VoiceSessionRequest):
        from services.voice_broker import create_session, resolve_provider
        from services.voice_session_tokens import mint_voice_session_token

        s = _settings()

        # Gate 1 — two-step opt-in (request+acknowledge).
        effective, _state, _flags = _opt_in_state(s)
        if not effective:
            provider_probe = resolve_provider(s)
            return JSONResponse(status_code=403, content=_opt_in_refusal_payload(provider_probe["reasons"]))

        # Gate 2 — provider must resolve.
        provider = resolve_provider(s)
        if provider["resolved"] is None:
            return JSONResponse(status_code=503, content={"error": "unconfigured", "detail": provider["degradedReason"]})

        # Gate 3 — persisted daily budget governor (shared helper).
        budget_refusal, gate = _budget_gate(s)
        if budget_refusal is not None:
            return budget_refusal

        # Gate 4 — bounded concurrency registry.
        tier = str(body.tier or "standard").strip().lower()
        session, error = create_session(tier=tier, settings=s)
        if error is not None:
            return JSONResponse(status_code=429, content=error)

        # The token is BOUND to this sessionId — a leaked grant cannot be
        # replayed to upgrade a different active session.
        token, expires_in = mint_voice_session_token(session.session_id)
        return JSONResponse(
            status_code=201,
            content={
                "sessionId": session.session_id,
                "token": token,
                "expiresInSeconds": expires_in,
                "wsPath": "/api/voice/session/ws",
                "resolvedProvider": provider["resolved"],
                "modelId": session.model_id,
                "tierFallback": session.tier != session.requested_tier,
                "limits": session.limits,
                "suggestTier": gate.get("suggestTier"),
            },
        )

    # ------------------------------------------------------------------
    # DELETE /api/voice/session/{sessionId} — operator kill switch
    # ------------------------------------------------------------------

    @router.delete("/api/voice/session/{session_id}", dependencies=[Depends(require_local_operator)])
    @limiter.limit("30/minute")
    async def delete_voice_session(request: Request, session_id: str):
        from services.voice_broker import end_session

        if end_session(session_id, reason="operator_delete"):
            return {"ok": True, "sessionId": session_id}
        raise HTTPException(status_code=404, detail="unknown voice session")

    # ------------------------------------------------------------------
    # WebSocket /api/voice/session/ws — realtime relay
    # ------------------------------------------------------------------

    def _voice_origin_allowed(ws: WebSocket) -> bool:
        """Origin check copied (not imported) from routers/agent_shell.py."""
        from urllib.parse import urlsplit

        origin = str(ws.headers.get("origin", "") or "").strip()
        if not origin:
            return True
        try:
            parsed_origin = urlsplit(origin)
        except ValueError:
            return False
        if parsed_origin.scheme not in {"http", "https"} or not parsed_origin.hostname:
            return False
        host_header = str(ws.headers.get("host", "") or "").strip()
        if not host_header:
            return False
        try:
            target_host = urlsplit(f"//{host_header}").hostname
        except ValueError:
            return False
        return bool(target_host and parsed_origin.hostname.lower() == target_host.lower())

    @router.websocket("/api/voice/session/ws")
    async def voice_session_ws(
        ws: WebSocket,
        token: str = Query(default=""),
        sessionId: str = Query(default=""),
    ):
        from services.voice_broker import end_session, get_session, run_realtime_relay
        from services.voice_session_tokens import consume_voice_session_token

        await ws.accept()
        try:
            if not _voice_origin_allowed(ws):
                await ws.close(code=4403, reason="voice origin rejected")
                return
            if not consume_voice_session_token(token, session_id=sessionId):
                await ws.close(code=4403, reason="voice credential required")
                return
            session = get_session(sessionId)
            if session is None:
                await ws.close(code=4403, reason="unknown voice session")
                return
            await run_realtime_relay(ws, session)
        except WebSocketDisconnect:
            end_session(sessionId, reason="client_disconnected")
        except Exception:
            logger.exception("voice relay crashed")
            try:
                await ws.close(code=1011)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # POST /api/voice/chat — typed-text degradation channel (sole input path)
    # ------------------------------------------------------------------

    @router.post("/api/voice/chat", dependencies=[Depends(require_local_operator)])
    @limiter.limit("30/minute")
    async def voice_chat(request: Request, body: VoiceChatRequest):
        from services.voice_broker import CHAT_CONTEXT_MAX_BYTES, chat_completion, resolve_provider

        s = _settings()
        effective, _state, _flags = _opt_in_state(s)
        if not effective:
            provider_probe = resolve_provider(s)
            return JSONResponse(status_code=403, content=_opt_in_refusal_payload(provider_probe["reasons"]))

        messages = []
        for entry in body.history[-8:]:
            if isinstance(entry, dict) and str(entry.get("role")) in ("user", "assistant"):
                messages.append({"role": entry["role"], "content": str(entry.get("content") or "")[:8000]})
        messages.append({"role": "user", "content": body.text})

        context_bytes = len(json.dumps(messages, ensure_ascii=False).encode("utf-8"))
        if context_bytes > CHAT_CONTEXT_MAX_BYTES:
            return JSONResponse(
                status_code=413,
                content={"error": "context_too_large", "limitBytes": CHAT_CONTEXT_MAX_BYTES},
            )

        result = await chat_completion(messages, settings=s)
        if not result.get("ok"):
            if result.get("error") == "chat_unconfigured":
                return JSONResponse(status_code=503, content={"error": "chat_unconfigured"})
            return JSONResponse(status_code=502, content=result)
        return result

    # ------------------------------------------------------------------
    # §3.3 one-line mounts — U3 unified tool registry endpoints
    # ------------------------------------------------------------------

    @router.get("/api/voice/tools", dependencies=[Depends(require_local_operator)])
    @limiter.limit("60/minute")
    async def voice_tools(request: Request):
        from services.voice_tool_registry import build_manifest

        return {"ok": True, "tools": build_manifest(include_client=True)}

    @router.get("/api/voice/models", dependencies=[Depends(require_local_operator)])
    @limiter.limit("30/minute")
    async def voice_models(
        request: Request,
        provider: str = Query(None),
        baseUrl: str = Query(None),
        apiKey: str = Query(None),
    ):
        """List selectable model ids for the setup card's dropdown.

        Compat gateways (OpenRouter, Ollama, …) are queried LIVE server-side
        ({base}/models, OpenAI list shape) so the operator picks from what
        the gateway actually offers. OpenAI/Gemini have no guaranteed list
        endpoint — curated static lists, marked curated:true. Unconfigured
        degrades honestly; this endpoint never 500s and never fabricates a
        gateway list.
        """
        from services.voice_broker import resolve_provider

        s = _settings()
        info = resolve_provider(s)
        resolved = str(provider or "").strip().lower() or info["resolved"]

        if resolved == "openai_realtime":
            curated = ["gpt-realtime", "gpt-realtime-mini", "gpt-4o-realtime-preview", "gpt-4o-mini-realtime-preview"]
            return {"ok": True, "models": [{"id": m} for m in curated], "curated": True}
        if resolved == "gemini_live":
            curated = [
                "gemini-2.0-flash-live-001",
                "gemini-2.5-flash-preview-native-audio-dialog",
                "gemini-2.5-flash-preview-flash-live",
            ]
            return {"ok": True, "models": [{"id": m} for m in curated], "curated": True}

        if resolved in ("compatible_ws", "compat"):
            base = str(baseUrl or info.get("compatBase") or "").strip().rstrip("/")
            key = str(apiKey or info.get("compatKey") or "").strip()
            if not base:
                return {"ok": True, "models": [], "note": "save a provider first"}
            import httpx

            headers = {"Authorization": f"Bearer {key}"} if key else {}
            last_detail = ""
            base_root = base[:-3] if base.endswith("/v1") else base  # no double-/v1
            for url in (f"{base}/models", f"{base_root}/v1/models"):
                try:
                    async with httpx.AsyncClient(timeout=10.0) as ac:
                        resp = await ac.get(url, headers=headers)
                except Exception as exc:
                    last_detail = f"{type(exc).__name__}: {exc}"
                    continue
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                    except ValueError:
                        last_detail = f"non-JSON model list from {url}"
                        continue
                    ids = sorted(
                        {
                            str(m.get("id"))
                            for m in (data.get("data") or [])
                            if isinstance(m, dict) and m.get("id")
                        }
                    )[:100]
                    return {"ok": True, "models": [{"id": i} for i in ids]}
                last_detail = f"HTTP {resp.status_code} from {url}"
            return JSONResponse(
                status_code=200,
                content={"ok": False, "error": "models_unavailable", "detail": last_detail},
            )

        # local_text / unconfigured — honest empty, never a fabricated list.
        return {"ok": True, "models": [], "note": "save a provider first"}

    @router.post("/api/voice/tool", dependencies=[Depends(require_local_operator)])
    @limiter.limit("60/minute")
    async def voice_tool(request: Request, body: VoiceToolCallRequest):
        """Stateless execute — validate/gate against the unified manifest, then
        dispatch through the existing server command dispatcher verbatim."""
        s = _settings()
        access_tier = str(getattr(s, "OPENCLAW_ACCESS_TIER", "restricted") or "restricted").strip().lower()
        from services.voice_tool_registry import validate_and_gate

        # Confirm flags ride in args — the same convention the registry's
        # expensive/destructive gates and _dispatch_command already read.
        args = dict(body.args or {})
        if body.confirm_expensive:
            args["confirm_expensive"] = True
        if body.confirm:
            args["confirm"] = True
        clean_call, error = validate_and_gate({"tool": body.tool, "args": args}, access_tier=access_tier)
        if error is not None:
            return JSONResponse(status_code=400, content={"ok": False, **error})
        from services.openclaw_channel import _dispatch_command

        return _dispatch_command(clean_call["tool"], clean_call.get("args") or {})

    # ------------------------------------------------------------------
    # POST /api/voice/hud-summary — §2.7 NARRATE generation
    # ------------------------------------------------------------------

    #: 30 s SHA-256 dedupe cache (§2.7): identical snapshot+question inside the
    #: window returns the cached brief without a second upstream dial.
    _HUD_DEDUPE_TTL_SECONDS = 30.0
    _hud_dedupe: dict[str, tuple[float, dict]] = {}
    _HUD_SNAPSHOT_MAX_BYTES = 6 * 1024  # §2.4 serialization cap

    @router.post("/api/voice/hud-summary", dependencies=[Depends(require_local_operator)])
    @limiter.limit("30/minute")
    async def voice_hud_summary(request: Request, body: VoiceHudSummaryRequest):
        from services.voice_broker import (
            GROUNDING_SCHEMA_ID,
            chat_completion,
            resolve_provider,
            validate_grounding_snapshot,
        )
        from services.voice_narration import compose_hud_summary_messages, snapshot_fingerprint

        s = _settings()
        effective, _state, _flags = _opt_in_state(s)
        if not effective:
            # SAR-style disabled payload (§2.7): honest reasons, no partial data.
            provider_probe = resolve_provider(s)
            return JSONResponse(
                status_code=409,
                content={
                    "error": "voice_disabled",
                    "detail": provider_probe["reasons"][0] if provider_probe["reasons"] else "disabled",
                    "reasons": provider_probe["reasons"],
                    "mode": _mesh_mode(),
                },
            )

        # Gate 3 — persisted daily-budget cap (§2.7 "429 latched cap"): briefs
        # are billable generations, so the cap applies here too, not only to
        # session minting.
        budget_refusal, _gate = _budget_gate(s)
        if budget_refusal is not None:
            return budget_refusal

        snapshot = validate_grounding_snapshot(body.snapshot)
        if snapshot is None:
            return JSONResponse(
                status_code=400,
                content={
                    "error": "invalid_snapshot",
                    "detail": (
                        f"snapshot must be a ≤{_HUD_SNAPSHOT_MAX_BYTES}B "
                        f"{GROUNDING_SCHEMA_ID} object"
                    ),
                },
            )

        mode = _mesh_mode()
        fingerprint = snapshot_fingerprint(snapshot, body.question)
        now = time.time()
        for key in [k for k, (stamp, _payload) in _hud_dedupe.items() if now - stamp > _HUD_DEDUPE_TTL_SECONDS]:
            _hud_dedupe.pop(key, None)
        cached = _hud_dedupe.get(fingerprint)
        if cached is not None:
            return {**cached[1], "deduped": True}

        messages = compose_hud_summary_messages(snapshot, question=str(body.question or "").strip(), mode=mode)
        result = await chat_completion(messages, settings=s)
        if not result.get("ok"):
            if result.get("error") == "chat_unconfigured":
                return JSONResponse(status_code=503, content={"error": "chat_unconfigured", "mode": mode})
            # 502 with the verbatim upstream reason (§2.7).
            return JSONResponse(status_code=502, content={**result, "mode": mode})

        payload = {
            "ok": True,
            "summary": str(result.get("reply") or ""),
            "model": result.get("model"),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": mode,
            "deduped": False,
        }
        _hud_dedupe[fingerprint] = (now, payload)
        return payload

    # ------------------------------------------------------------------
    # POST /api/voice/turn — §3.6 picker/orchestrator loop (text mode)
    # ------------------------------------------------------------------

    @router.post("/api/voice/turn", dependencies=[Depends(require_local_operator)])
    @limiter.limit("30/minute")
    async def voice_turn(request: Request, body: VoiceTurnRequest):
        from services.voice_broker import resolve_provider, run_picker_turn

        s = _settings()
        effective, _state, _flags = _opt_in_state(s)
        if not effective:
            provider_probe = resolve_provider(s)
            return JSONResponse(status_code=409, content=_opt_in_refusal_payload(provider_probe["reasons"]))

        # Gate 3 — persisted daily-budget cap (§2.7): picker turns dial the
        # chat model, so the same latched cap governs this surface.
        budget_refusal, _gate = _budget_gate(s)
        if budget_refusal is not None:
            return budget_refusal

        result = await run_picker_turn(
            body.text,
            snapshot=body.snapshot,
            history=body.history,
            settings=s,
        )
        if not result.get("ok"):
            if result.get("error") == "chat_unconfigured":
                return JSONResponse(status_code=503, content={"error": "chat_unconfigured"})
            return JSONResponse(status_code=502, content=result)
        result["mode"] = _mesh_mode()
        return result

    # ------------------------------------------------------------------
    # POST /api/voice/interrogate — §2.7 interrogation relay
    # ------------------------------------------------------------------

    @router.post("/api/voice/interrogate", dependencies=[Depends(require_local_operator)])
    @limiter.limit("30/minute")
    async def voice_interrogate(request: Request, body: VoiceInterrogateRequest):
        """Interrogation relay (§2.7): local target resolution →
        correlate_entity / get_entity_profile / gt_dossier through the EXISTING
        dispatcher → evidence pack as second user message → narrated answer.
        Tier gating is inherited via validate_and_gate; per-session memory is
        capped at 2 exchanges inside services.voice_interrogation."""
        from services.voice_broker import resolve_provider
        from services.voice_interrogation import run_interrogation_turn

        s = _settings()
        effective, _state, _flags = _opt_in_state(s)
        if not effective:
            provider_probe = resolve_provider(s)
            return JSONResponse(status_code=409, content=_opt_in_refusal_payload(provider_probe["reasons"]))

        # Gate 3 — persisted daily-budget cap: interrogation turns dial the
        # chat model, so the same latched cap governs this surface.
        budget_refusal, _gate = _budget_gate(s)
        if budget_refusal is not None:
            return budget_refusal

        result = await run_interrogation_turn(
            body.question,
            target=body.target,
            snapshot=body.snapshot,
            session_key=str(body.sessionId or "").strip()[:64] or "default",
            settings=s,
        )
        if not result.get("ok"):
            error = str(result.get("error") or "")
            if error == "chat_unconfigured":
                return JSONResponse(status_code=503, content={"error": "chat_unconfigured"})
            if error in ("no_target", "empty_question"):
                return JSONResponse(status_code=400, content=result)
            if error in ("gate_blocked",):
                return JSONResponse(status_code=400, content={"ok": False, **result})
            return JSONResponse(status_code=502, content=result)
        result["mode"] = _mesh_mode()
        return result
