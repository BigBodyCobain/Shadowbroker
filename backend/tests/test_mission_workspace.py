"""Persistent missions must not replay actions, manufacture approvals, or bypass voice gates."""

import asyncio
import importlib
import json
import time
from unittest.mock import AsyncMock

import httpx
import pytest

from services import mission_engine as engine
from services import mission_store as store

OWNER = "dashboard-test-owner"


@pytest.fixture(autouse=True)
def environment(tmp_path, monkeypatch):
    for key in list(__import__("os").environ):
        if key.startswith("VOICE_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("SB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ADMIN_KEY", "mission-test-admin-" + "x" * 40)
    monkeypatch.setenv("VOICE_AGENT_OUTBOUND_ENABLE", "allow")
    monkeypatch.setenv("VOICE_AGENT_OUTBOUND_ACKNOWLEDGE", "true")
    monkeypatch.setenv("VOICE_API_PROVIDER", "compat")
    monkeypatch.setenv("VOICE_COMPAT_BASE_URL", "http://127.0.0.1:4141/v1")
    monkeypatch.setenv("VOICE_CHAT_MODEL", "synthetic-model")
    monkeypatch.setenv("OPENCLAW_ACCESS_TIER", "full")
    import services.api_settings as keys

    monkeypatch.setattr(keys, "OPERATOR_KEYS_ENV_PATH", tmp_path / "keys.env")
    from services.config import get_settings

    get_settings.cache_clear()
    import services.openclaw_watchdog as watchdog

    monkeypatch.setattr(watchdog, "_ensure_running", lambda: None)
    yield monkeypatch
    get_settings.cache_clear()


def mission(role="analyst", max_calls=5):
    record = store.create(
        "Investigate the test harbor",
        [
            {
                "role": role,
                "provider": "compat",
                "model": "synthetic-model",
                "max_calls": max_calls,
                "calls": 0,
            }
        ],
    )
    return store.control(record["id"], OWNER, "resume")


def model(monkeypatch, *calls):
    import services.voice_broker as broker

    replies = [json.dumps(call) for call in calls]
    upstream = AsyncMock(
        side_effect=lambda *args, **kwargs: {
            "ok": True,
            "reply": replies.pop(0),
            "model": "synthetic-model",
        }
    )
    monkeypatch.setattr(broker, "chat_completion", upstream)
    return upstream


def test_store_survives_module_reload_and_never_stores_provider_keys():
    record = mission()
    loaded = importlib.reload(store).get(record["id"])
    assert loaded["objective"] == record["objective"]
    assert loaded["roles"][0]["model"] == "synthetic-model"
    assert "lease_token" not in store.public(loaded)
    assert "admin" not in json.dumps(loaded)


def test_duplicate_or_foreign_step_claim_cannot_run():
    record = mission()
    claimed, token = store.claim(record["id"], OWNER, record["revision"])
    assert token
    with pytest.raises(store.MissionConflict):
        store.claim(record["id"], OWNER, record["revision"])
    with pytest.raises(store.MissionConflict):
        store.claim(record["id"], "different-dashboard", claimed["revision"])


def test_expired_lease_pauses_without_automatically_replaying():
    record = mission()
    claimed, _ = store.claim(record["id"], OWNER, record["revision"])
    stale = store.mutate(
        record["id"], lambda item: item.update(lease_until=time.time() - 1)
    )
    recovered, token = store.claim(record["id"], OWNER, stale["revision"])
    assert token is None and recovered["status"] == "paused"
    assert "unknown" in recovered["reason"]


@pytest.mark.asyncio
async def test_search_then_browser_receipt_then_review_completes(monkeypatch):
    upstream = model(
        monkeypatch,
        {"tool": "search_news", "args": {"query": "harbor"}},
        {"tool": "open_article", "args": {"url": "https://news.example/harbor"}},
        {
            "tool": None,
            "say": "Harbor report verified from the source and dashboard receipt.",
        },
    )
    import services.openclaw_channel as channel

    monkeypatch.setattr(
        channel,
        "_dispatch_command",
        lambda *args: {
            "ok": True,
            "data": {
                "results": [
                    {
                        "title": "Harbor report",
                        "link": "https://news.example/harbor",
                        "summary": "Synthetic source",
                    }
                ]
            },
        },
    )
    record = mission()
    record = await engine.advance(record["id"], OWNER, record["revision"])
    assert record["evidence"][0]["url"] == "https://news.example/harbor"
    record = await engine.advance(record["id"], OWNER, record["revision"])
    assert record["status"] == "waiting_client"
    pending = record["pending"]
    with pytest.raises(store.MissionConflict):
        engine.client_start(record["id"], "another-owner", pending["id"])
    engine.client_start(record["id"], OWNER, pending["id"])
    with pytest.raises(store.MissionConflict):
        engine.client_start(record["id"], OWNER, pending["id"])
    result = {"ok": True, "action": "open_article", "article": {"id": "harbor"}}
    record = engine.client_receipt(record["id"], OWNER, pending["id"], result)
    again = engine.client_receipt(record["id"], OWNER, pending["id"], result)
    assert sum(item["kind"] == "client_receipt" for item in again["events"]) == 1
    assert again["revision"] == record["revision"]
    record = await engine.advance(record["id"], OWNER, again["revision"])
    assert record["status"] == "completed"
    assert "dashboard receipt" in record["reports"][0]["text"]
    assert any(
        "open_article" in message["content"] for message in upstream.call_args.args[0]
    )


@pytest.mark.asyncio
async def test_model_cannot_approve_its_own_write(monkeypatch):
    model(
        monkeypatch, {"tool": "delete_pin", "args": {"id": "test-pin", "confirm": True}}
    )
    import services.openclaw_channel as channel

    dispatch = __import__("unittest.mock", fromlist=["Mock"]).Mock(
        return_value={"ok": True}
    )
    monkeypatch.setattr(channel, "_dispatch_command", dispatch)
    record = mission()
    record = await engine.advance(record["id"], OWNER, record["revision"])
    assert record["status"] == "needs_approval"
    dispatch.assert_not_called()
    assert "confirm" not in record["pending"]["args"]
    record = await engine.execute_pending(
        record["id"], OWNER, record["pending"]["id"], approved=True
    )
    assert record["status"] == "running"
    dispatch.assert_called_once()
    assert dispatch.call_args.args[1]["confirm"] is True


@pytest.mark.asyncio
async def test_read_only_role_cannot_execute_write_or_display(monkeypatch):
    model(monkeypatch, {"tool": "place_pin", "args": {"lat": 0, "lng": 0}})
    record = mission(role="researcher")
    record = await engine.advance(record["id"], OWNER, record["revision"])
    assert record["pending"] is None
    assert "permissions" in record["messages"][-1]["content"]


@pytest.mark.asyncio
async def test_outbound_opt_in_and_daily_cap_prevent_inference(monkeypatch):
    upstream = model(monkeypatch, {"tool": None, "say": "Should not run"})
    monkeypatch.setenv("VOICE_AGENT_OUTBOUND_ENABLE", "block")
    from services.config import get_settings

    get_settings.cache_clear()
    record = mission()
    record = await engine.advance(record["id"], OWNER, record["revision"])
    assert record["status"] == "paused" and "opt-in" in record["reason"]
    upstream.assert_not_called()
    monkeypatch.setenv("VOICE_AGENT_OUTBOUND_ENABLE", "allow")
    get_settings.cache_clear()
    import services.voice_broker as broker

    monkeypatch.setattr(
        broker, "daily_spend_view", lambda settings: {"_gate": {"allowed": False}}
    )
    record = store.control(record["id"], OWNER, "resume")
    record = await engine.advance(record["id"], OWNER, record["revision"])
    assert "budget" in record["reason"]
    upstream.assert_not_called()


@pytest.mark.asyncio
async def test_role_call_limit_does_not_silently_expand(monkeypatch):
    upstream = model(monkeypatch, {"tool": "not_a_tool", "args": {}})
    record = mission(max_calls=1)
    record = await engine.advance(record["id"], OWNER, record["revision"])
    record = await engine.advance(record["id"], OWNER, record["revision"])
    assert record["status"] == "paused" and "limit" in record["reason"]
    assert record["calls"] == 1
    upstream.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancellation_during_model_call_never_dispatches(monkeypatch):
    import services.voice_broker as broker

    entered, release = asyncio.Event(), asyncio.Event()

    async def waiting(*args, **kwargs):
        entered.set()
        await release.wait()
        return {
            "ok": True,
            "reply": json.dumps({"tool": "open_article", "args": {"query": "harbor"}}),
        }

    monkeypatch.setattr(broker, "chat_completion", waiting)
    record = mission()
    task = asyncio.create_task(engine.advance(record["id"], OWNER, record["revision"]))
    await entered.wait()
    store.control(record["id"], OWNER, "cancel")
    release.set()
    result = await task
    assert result["status"] == "cancelled" and result["pending"] is None
    with pytest.raises(store.MissionConflict):
        store.control(record["id"], OWNER, "pause")


@pytest.mark.asyncio
async def test_started_client_action_requires_explicit_resolution_after_reload(
    monkeypatch,
):
    model(monkeypatch, {"tool": "map_zoom", "args": {"direction": "in"}})
    record = mission()
    record = await engine.advance(record["id"], OWNER, record["revision"])
    engine.client_start(record["id"], OWNER, record["pending"]["id"])
    store.control(record["id"], OWNER, "pause")
    with pytest.raises(store.MissionConflict):
        store.control(record["id"], OWNER, "resume")
    record = store.control(record["id"], OWNER, "resolve")
    assert record["pending"] is None and "unknown" in record["messages"][-1]["content"]


def test_watches_restore_pause_and_keep_trigger_history(monkeypatch):
    import services.openclaw_watchdog as watchdog

    watch = watchdog.add_watch("keyword", {"keyword": "harbor"})
    store.watch_observe(watch["id"], time.time(), {"alert": "New harbor report"})
    watchdog._watches.clear()
    restored = watchdog.list_watches()[0]
    assert (
        restored["fires"] == 1
        and restored["last_alert"]["alert"] == "New harbor report"
    )
    watchdog.update_watch(watch["id"], paused=True)
    assert watchdog.list_watches()[0]["paused"] is True
    assert (
        store.watch_observe(watch["id"], time.time() + 100, {"alert": "ignored"})
        is None
    )
    watchdog.remove_watch(watch["id"])
    assert store.watch_load() == []


@pytest.mark.asyncio
async def test_mission_routes_require_auth_and_bound_receipts_and_snapshots():
    from fastapi import FastAPI
    from routers.missions import router

    app = FastAPI()
    app.include_router(router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 1000)),
        base_url="http://localhost:8000",
    ) as client:
        assert (await client.get("/api/voice/missions")).status_code == 403
        client.headers["X-Admin-Key"] = "mission-test-admin-" + "x" * 40
        payload = {
            "objective": "Test harbor",
            "roles": [
                {
                    "role": "analyst",
                    "provider": "compat",
                    "model": "synthetic-model",
                    "max_calls": 3,
                }
            ],
        }
        created = await client.post("/api/voice/missions", json=payload)
        assert created.status_code == 200
        mission_id = created.json()["mission"]["id"]
        invalid = await client.post(
            f"/api/voice/missions/{mission_id}/receipt",
            json={
                "dashboard": OWNER,
                "action_id": "a" * 32,
                "result": {"ok": True, "data": "x" * 15000},
            },
        )
        assert invalid.status_code == 400
        oversized = await client.post(
            "/api/voice/missions",
            json={
                **payload,
                "snapshot": {
                    "schema": "sb.grounding.v1",
                    "view": {},
                    "layers": {},
                    "data": "x" * 7000,
                },
            },
        )
        assert oversized.status_code == 400
        assert (await client.get("/api/voice/missions")).json()["missions"][0][
            "id"
        ] == mission_id
        assert (
            await client.delete(f"/api/voice/missions/{mission_id}")
        ).status_code == 200


@pytest.mark.asyncio
async def test_specialist_handoffs_keep_their_models_and_context(monkeypatch):
    upstream = model(
        monkeypatch,
        {"tool": None, "say": "Research evidence is missing; do not invent sources."},
        {"tool": None, "say": "Analysis found insufficient data."},
        {"tool": None, "say": "Review: no supported factual conclusion."},
    )
    roles = [
        engine.prepare_role(
            {"role": role, "provider": "compat", "model": name, "max_calls": 2}
        )
        for role, name in [
            ("researcher", "research-model"),
            ("analyst", "analysis-model"),
            ("reviewer", "review-model"),
        ]
    ]
    record = store.create("Investigate with independent roles", roles)
    record = store.control(record["id"], OWNER, "resume")
    for _ in roles:
        record = await engine.advance(record["id"], OWNER, record["revision"])
    assert record["status"] == "completed"
    assert [
        call.kwargs["settings"].VOICE_CHAT_MODEL for call in upstream.call_args_list
    ] == ["research-model", "analysis-model", "review-model"]
    assert [report["role"] for report in record["reports"]] == [
        "researcher",
        "analyst",
        "reviewer",
    ]
    assert any(
        "do not invent" in message["content"]
        for message in upstream.call_args_list[-1].args[0]
    )


@pytest.mark.asyncio
async def test_stored_evidence_cannot_silently_move_to_a_changed_gateway(monkeypatch):
    role = engine.prepare_role(
        {
            "role": "analyst",
            "provider": "compat",
            "model": "synthetic-model",
            "max_calls": 3,
        }
    )
    record = store.create("Sensitive area investigation", [role])
    record = store.control(record["id"], OWNER, "resume")
    upstream = model(monkeypatch, {"tool": None, "say": "Must not run"})
    monkeypatch.setenv("VOICE_COMPAT_BASE_URL", "https://changed.example/v1")
    from services.config import get_settings

    get_settings.cache_clear()
    record = await engine.advance(record["id"], OWNER, record["revision"])
    assert record["status"] == "paused" and "destination" in record["reason"]
    upstream.assert_not_called()


def test_evidence_pins_survive_reload():
    record = mission()
    store.mutate(
        record["id"],
        lambda current: current["evidence"].append(
            {"id": "source", "pinned": True, "title": "Saved source"}
        ),
    )
    assert importlib.reload(store).get(record["id"])["evidence"][0]["pinned"] is True


def test_backend_startup_restores_watches_without_inference(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers.missions import router
    import services.openclaw_watchdog as watchdog

    watch = watchdog.add_watch("keyword", {"keyword": "harbor"})
    watchdog._watches.clear()
    upstream = model(monkeypatch)
    app = FastAPI()
    app.include_router(router)
    with TestClient(app):
        assert watchdog._watches[watch["id"]]["params"] == {"keyword": "harbor"}
    upstream.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path,payload",
    [
        (
            "missions",
            {
                "objective": "Test objective",
                "roles": [{"role": "analyst", "provider": "compat", "model": "test"}],
            },
        ),
        ("missions/test/control", {"dashboard": OWNER, "action": "resume"}),
        ("missions/test/advance", {"dashboard": OWNER, "revision": 1}),
        ("missions/test/client-start", {"dashboard": OWNER, "action_id": "a" * 32}),
        (
            "missions/test/receipt",
            {
                "dashboard": OWNER,
                "action_id": "a" * 32,
                "result": {"ok": True, "action": "map_zoom"},
            },
        ),
        (
            "missions/test/approve",
            {"dashboard": OWNER, "action_id": "a" * 32, "approve": True},
        ),
        ("missions/test/evidence/source", {"pinned": True}),
        ("watches", {"type": "keyword", "params": {"keyword": "harbor"}}),
    ],
)
async def test_every_mission_mutation_requires_operator_credentials(path, payload):
    from fastapi import FastAPI
    from routers.missions import router

    app = FastAPI()
    app.include_router(router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 1000)),
        base_url="http://localhost:8000",
    ) as client:
        response = await client.post("/api/voice/" + path, json=payload)
        assert response.status_code == 403


def test_lean_mode_has_no_mission_surface():
    import os, subprocess, sys

    output = subprocess.check_output(
        [
            sys.executable,
            "-c",
            "from routers.missions import router; print(len(router.routes))",
        ],
        env={**os.environ, "MESH_ONLY": "1"},
        text=True,
    )
    assert output.strip() == "0"


def test_watch_debounce_and_seen_posts_survive_reload():
    import services.openclaw_watchdog as watchdog

    watch = watchdog.add_watch("keyword", {"keyword": "harbor"})
    moment = time.time()
    assert store.watch_observe(
        watch["id"],
        moment,
        {"alert": "New story"},
        seen_posts=["https://t.me/example/123"],
    )
    assert store.watch_observe(watch["id"], moment + 1, {"alert": "Duplicate"}) is None
    watchdog._seen_posts.clear()
    watchdog._watches.clear()
    watchdog.list_watches()
    assert "https://t.me/example/123" in watchdog._seen_posts[watch["id"]]
    assert watchdog._watches[watch["id"]]["fires"] == 1


@pytest.mark.asyncio
async def test_operator_can_review_an_exact_pending_approval_from_a_new_dashboard(
    monkeypatch,
):
    model(
        monkeypatch, {"tool": "delete_pin", "args": {"id": "test-pin", "confirm": True}}
    )
    import services.openclaw_channel as channel
    from unittest.mock import Mock

    dispatch = Mock(return_value={"ok": True})
    monkeypatch.setattr(channel, "_dispatch_command", dispatch)
    record = mission()
    record = await engine.advance(record["id"], OWNER, record["revision"])
    action_id = record["pending"]["id"]
    record = await engine.execute_pending(
        record["id"], "new-dashboard-owner", action_id, approved=True
    )
    assert record["owner"] == "new-dashboard-owner"
    assert record["pending"] is None
    dispatch.assert_called_once()
    with pytest.raises(store.MissionConflict):
        await engine.execute_pending(record["id"], OWNER, action_id, approved=True)


@pytest.mark.asyncio
async def test_expired_browser_action_persists_its_paused_recovery_state(monkeypatch):
    model(monkeypatch, {"tool": "map_zoom", "args": {"direction": "in"}})
    record = mission()
    record = await engine.advance(record["id"], OWNER, record["revision"])
    store.mutate(
        record["id"],
        lambda current: current["pending"].update(deadline=time.time() - 1),
    )
    paused = engine.client_start(record["id"], OWNER, record["pending"]["id"])
    assert paused["status"] == "paused"
    assert store.get(record["id"])["status"] == "paused"
    assert store.get(record["id"])["pending"]["started"] is True


def test_legacy_realtime_config_keeps_its_existing_text_gateway(monkeypatch):
    import services.voice_broker as broker
    from routers.missions import configuration

    monkeypatch.setattr(
        broker,
        "resolve_provider",
        lambda settings: {
            "apiProvider": "",
            "resolved": "openai_realtime",
            "compatBaseUrlSet": True,
            "chatModel": "served-local-model",
        },
    )
    data = configuration()
    assert data["provider"] == "compat"
    assert data["model"] == "served-local-model"
