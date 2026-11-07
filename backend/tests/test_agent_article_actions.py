"""Article preview dispatch stays grounded in current news and existing access tiers."""
import pytest

from services.openclaw_channel import CommandChannel, _dispatch_command
from services.openclaw_routing import route_query


@pytest.fixture
def news(monkeypatch):
    import services.fetchers._store as store
    rows = [
        {"title": "Port traffic update", "summary": "Container arrivals", "link": "https://news.example/port", "coords": [0, 0]},
        {"title": "Storm warning", "link": "https://news.example/storm"},
    ]
    monkeypatch.setattr(store, "get_latest_data_subset_refs", lambda *keys: {"news": rows})
    import routers.ai_intel as router
    queued = []
    monkeypatch.setattr(router, "push_agent_action", queued.append)
    return rows, queued


def test_external_agent_queues_existing_article_without_claiming_display(news):
    rows, queued = news
    result = _dispatch_command("show_article", {"query": "port"})
    assert result["ok"] is True
    assert result["data"]["queued"] is True
    assert result["data"]["displayed"] is False
    assert queued == [{"action": "open_article", "source": "show_article", "article": {"query": rows[0]["title"], "url": rows[0]["link"]}}]


def test_exact_url_wins_over_a_conflicting_query(news):
    rows, queued = news
    result = _dispatch_command("show_article", {"url": rows[1]["link"], "query": "port"})
    assert result["ok"] is True
    assert queued[0]["article"]["url"] == rows[1]["link"]


@pytest.mark.parametrize("args", [{}, {"query": "missing"}, {"url": "https://unrelated.example/", "query": "port"}])
def test_missing_and_arbitrary_articles_are_not_queued(news, args):
    _, queued = news
    assert _dispatch_command("show_article", args)["ok"] is False
    assert queued == []


def test_external_agent_keeps_full_tier_requirement(news):
    _, queued = news
    result = CommandChannel().submit_command("show_article", {"query": "port"}, access_tier="restricted")
    assert result["ok"] is False
    assert "full access" in result["detail"]
    assert queued == []


def test_tool_manifest_exposes_distinct_console_and_external_actions():
    from services.voice_tool_registry import build_manifest, validate_and_gate
    tools = {item["name"]: item for item in build_manifest()}
    assert tools["open_article"]["surface"] == "client"
    assert tools["show_article"]["type"] == "write"
    call, error = validate_and_gate({"tool": "open_article", "args": {"query": "port"}}, access_tier="restricted")
    assert error is None and call["tool"] == "open_article"


@pytest.mark.parametrize("text,args", [
    ("open an article about port", {"query": "port"}),
    ("show me the story about storm warning", {"query": "storm warning"}),
    ("open article https://news.example/port", {"url": "https://news.example/port"}),
])
def test_agent_natural_language_router_knows_article_actions(text, args):
    plan = route_query(text)
    assert plan["recommended"] == {"cmd": "show_article", "args": args}
