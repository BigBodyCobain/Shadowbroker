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

from __future__ import annotations

import json
import logging
import os

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
    # POST /api/voice/session — mint one short-lived session grant
    # ------------------------------------------------------------------

    @router.post("/api/voice/session", status_code=201, dependencies=[Depends(require_local_operator)])
    @limiter.limit("10/minute")
    async def create_voice_session(request: Request, body: VoiceSessionRequest):
        from services.voice_broker import create_session, daily_spend_view, resolve_provider
        from services.voice_session_tokens import mint_voice_session_token
        from services.voice_daily_budget import evaluate_daily_budget

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

        # Gate 3 — persisted daily budget governor.
        spend = daily_spend_view(s)
        gate = evaluate_daily_budget(
            spend,
            getattr(s, "VOICE_DAILY_BUDGET_USD", 0.0),
            mini_configured=bool(str(getattr(s, "VOICE_MODEL_MINI", "") or "").strip()),
        )
        if not gate["allowed"]:
            retry_after = 3600
            try:
                from datetime import datetime, timezone

                resets_at = datetime.fromisoformat(gate["resetsAt"])
                retry_after = max(60, int((resets_at - datetime.now(timezone.utc)).total_seconds()))
            except Exception:
                pass
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": str(retry_after)},
                content={"error": "budget", "resetsAt": gate["resetsAt"]},
            )

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
