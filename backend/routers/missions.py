"""Authenticated mission workspace and existing-watchdog controls."""

from contextlib import contextmanager, asynccontextmanager
import json
import logging
import os
import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from auth import require_local_operator
from limiter import limiter
from services import mission_store as store

_MESH_ONLY = os.environ.get("MESH_ONLY", "").strip().lower() in ("1", "true", "yes")


@asynccontextmanager
async def lifespan(app):
    if _MESH_ONLY:
        yield
        return
    from services.openclaw_watchdog import restore_watches

    try:
        restore_watches()
    except (OSError, sqlite3.Error, ValueError) as exc:
        logging.getLogger(__name__).warning(
            "Saved monitoring could not be restored: %s", type(exc).__name__
        )
    try:
        yield
    finally:
        from services.openclaw_watchdog import stop_watchdog

        stop_watchdog()


router = APIRouter(
    prefix="/api/voice",
    dependencies=[Depends(require_local_operator)],
    tags=["missions"],
    lifespan=lifespan,
)


@contextmanager
def errors():
    try:
        yield
    except KeyError:
        raise HTTPException(404, "Mission or evidence not found") from None
    except store.MissionConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    except (sqlite3.Error, OSError):
        raise HTTPException(
            503, "Mission storage is unavailable; no work was started"
        ) from None


def snapshot(value):
    from services.voice_broker import validate_grounding_snapshot

    if value is None:
        return None
    clean = validate_grounding_snapshot(value)
    if clean is None:
        raise ValueError("Invalid or oversized dashboard snapshot")
    return clean


class Role(BaseModel):
    role: Literal["coordinator", "researcher", "analyst", "reviewer"]
    provider: Literal[
        "openai",
        "gemini",
        "anthropic",
        "xai",
        "openrouter",
        "meta",
        "ollama",
        "lmstudio",
        "compat",
    ]
    model: str = Field(min_length=1, max_length=200)
    max_calls: int = Field(default=5, ge=1, le=8)


class NewMission(BaseModel):
    objective: str = Field(min_length=3, max_length=2000)
    roles: list[Role] = Field(min_length=1, max_length=4)
    snapshot: dict | None = None


class Dashboard(BaseModel):
    dashboard: str = Field(min_length=8, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")


class Advance(Dashboard):
    revision: int = Field(ge=1)


class Control(Dashboard):
    action: Literal["resume", "pause", "cancel", "resolve", "next_role"]


class Action(Dashboard):
    action_id: str = Field(min_length=32, max_length=32, pattern=r"^[a-f0-9]+$")


class Receipt(Action):
    result: dict
    snapshot: dict | None = None


class Approval(Action):
    approve: bool


class Evidence(BaseModel):
    pinned: bool


@router.get("/missions/config")
def configuration():
    from services.config import get_settings
    from services.voice_broker import resolve_provider
    from services.voice_providers import PROVIDERS, PROVIDER_ALIASES
    from services.mission_engine import ROLE_PURPOSES

    current = resolve_provider(get_settings())
    provider = current.get("apiProvider")
    if not provider:
        provider = (
            "anthropic"
            if current.get("resolved") == "anthropic_text"
            else "compat"
            if current.get("compatBaseUrlSet")
            else PROVIDER_ALIASES.get(current.get("resolved"), "compat")
        )
    return {
        "ok": True,
        "providers": [
            {"id": key, "label": row["label"]} for key, row in PROVIDERS.items()
        ],
        "provider": provider,
        "model": current.get("chatModel") or "",
        "role_purposes": ROLE_PURPOSES,
    }


@router.get("/missions")
def index():
    with errors():
        return {"ok": True, "missions": store.list_missions()}


@router.post("/missions")
@limiter.limit("10/minute")
def create(request: Request, body: NewMission):
    with errors():
        if len({role.role for role in body.roles}) != len(body.roles):
            raise ValueError("Each specialist role can appear only once")
        if len(body.objective.strip()) < 3:
            raise ValueError("Enter a mission objective")
        from services.mission_engine import prepare_role

        roles = [prepare_role(role.model_dump()) for role in body.roles]
        record = store.create(body.objective.strip(), roles, snapshot(body.snapshot))
        return {"ok": True, "mission": store.public(record)}


@router.get("/missions/{mission_id}")
def read(mission_id: str):
    with errors():
        return {"ok": True, "mission": store.public(store.get(mission_id))}


@router.delete("/missions/{mission_id}")
def delete(mission_id: str):
    with errors():
        store.delete(mission_id)
        return {"ok": True}


@router.post("/missions/{mission_id}/control")
def control(mission_id: str, body: Control):
    with errors():
        return {
            "ok": True,
            "mission": store.public(
                store.control(mission_id, body.dashboard, body.action)
            ),
        }


@router.post("/missions/{mission_id}/advance")
@limiter.limit("60/minute")
async def advance(request: Request, mission_id: str, body: Advance):
    from services.mission_engine import advance as step

    with errors():
        return {
            "ok": True,
            "mission": store.public(
                await step(mission_id, body.dashboard, body.revision)
            ),
        }


@router.post("/missions/{mission_id}/client-start")
def client_start(mission_id: str, body: Action):
    from services.mission_engine import client_start as start

    with errors():
        return {
            "ok": True,
            "mission": store.public(start(mission_id, body.dashboard, body.action_id)),
        }


@router.post("/missions/{mission_id}/receipt")
def receipt(mission_id: str, body: Receipt):
    from services.mission_engine import client_receipt

    with errors():
        if len(
            json.dumps(body.result, allow_nan=False).encode()
        ) > 12000 or not isinstance(body.result.get("ok"), bool):
            raise ValueError(
                "Receipt requires a bounded result with an explicit ok boolean"
            )
        return {
            "ok": True,
            "mission": store.public(
                client_receipt(
                    mission_id,
                    body.dashboard,
                    body.action_id,
                    body.result,
                    snapshot(body.snapshot),
                )
            ),
        }


@router.post("/missions/{mission_id}/approve")
async def approve(mission_id: str, body: Approval):
    from services.mission_engine import execute_pending

    with errors():
        if body.approve:
            record = await execute_pending(
                mission_id, body.dashboard, body.action_id, approved=True
            )
        else:

            def reject(record):
                pending = record.get("pending")
                if (
                    record["status"] != "needs_approval"
                    or not pending
                    or pending["id"] != body.action_id
                    or pending["started"]
                ):
                    raise store.MissionConflict(
                        "Approval is no longer current for this dashboard"
                    )
                store.feedback(
                    record,
                    pending["tool"],
                    {
                        "ok": False,
                        "error": "Operator rejected this action. Do not repeat it.",
                    },
                )
                store.event(
                    record, "rejected", pending["tool"], action_id=body.action_id
                )
                record.update(
                    pending=None,
                    status="paused",
                    reason="Action rejected by operator",
                    owner=body.dashboard,
                )

            record = store.mutate(mission_id, reject)
        return {"ok": True, "mission": store.public(record)}


@router.post("/missions/{mission_id}/evidence/{evidence_id}")
def pin(mission_id: str, evidence_id: str, body: Evidence):
    with errors():

        def change(record):
            item = next(
                (item for item in record["evidence"] if item["id"] == evidence_id), None
            )
            if not item:
                raise KeyError(evidence_id)
            item["pinned"] = body.pinned

        return {"ok": True, "mission": store.public(store.mutate(mission_id, change))}


class NewWatch(BaseModel):
    type: Literal[
        "track_aircraft",
        "track_callsign",
        "track_registration",
        "track_ship",
        "track_entity",
        "geofence",
        "keyword",
    ]
    params: dict
    mission_id: str | None = Field(default=None, max_length=32)


class WatchState(BaseModel):
    paused: bool


def full_access():
    from services.config import get_settings

    if get_settings().OPENCLAW_ACCESS_TIER.strip().lower() != "full":
        raise HTTPException(403, "Full agent access is required to change watches")


@router.get("/watches")
def watches():
    from services.openclaw_watchdog import list_watches

    with errors():
        return {"ok": True, "watches": list_watches()}


@router.post("/watches")
@limiter.limit("10/minute")
def create_watch(request: Request, body: NewWatch):
    from services.openclaw_watchdog import add_watch, update_watch

    full_access()
    with errors():
        if len(json.dumps(body.params, allow_nan=False)) > 4000:
            raise ValueError("Watch parameters are too large")
        if body.mission_id:
            store.get(body.mission_id)
        watch = add_watch(body.type, body.params)
        if body.mission_id:
            watch = update_watch(watch["id"], mission_id=body.mission_id)
        return {"ok": True, "watch": watch}


@router.patch("/watches/{watch_id}")
def pause_watch(watch_id: str, body: WatchState):
    from services.openclaw_watchdog import update_watch

    full_access()
    with errors():
        return {"ok": True, "watch": update_watch(watch_id, paused=body.paused)}


@router.delete("/watches/{watch_id}")
def delete_watch(watch_id: str):
    from services.openclaw_watchdog import remove_watch

    full_access()
    with errors():
        return remove_watch(watch_id)


if _MESH_ONLY:
    router.routes.clear()
