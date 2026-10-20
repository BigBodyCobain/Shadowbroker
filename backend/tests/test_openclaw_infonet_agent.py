"""OpenClaw Infonet delegation — command allowlist and dispatch."""

from __future__ import annotations

from unittest.mock import patch

from services.openclaw_channel import (
    READ_COMMANDS,
    WRITE_COMMANDS,
    _dispatch_command,
    allowed_commands,
)
from services.openclaw_channel import CommandChannel


INFONET_READS = frozenset({
    "infonet_status",
    "list_gates",
    "read_gate_messages",
    "poll_dms",
})

INFONET_WRITES = frozenset({
    "ensure_infonet_ready",
    "join_infonet_swarm",
    "post_gate_message",
    "cast_vote",
    "send_dm",
})


def test_infonet_commands_in_allowlists():
    assert INFONET_READS <= READ_COMMANDS
    assert INFONET_WRITES <= WRITE_COMMANDS


def test_restricted_tier_allows_infonet_reads_only():
    allowed = allowed_commands("restricted")
    assert INFONET_READS <= allowed
    assert not (INFONET_WRITES & allowed)


def test_full_tier_allows_infonet_writes():
    allowed = allowed_commands("full")
    assert INFONET_WRITES <= allowed


def test_restricted_tier_blocks_post_gate_message():
    channel = CommandChannel()
    result = channel.submit_command("post_gate_message", {"gate_id": "infonet", "plaintext": "hi"})
    assert result["ok"] is False
    assert "full access tier" in str(result.get("detail", ""))


def test_dispatch_infonet_status_mocked():
    fake = {"ok": True, "chain": {"length": 3}, "valid": True}
    with patch("services.openclaw_infonet.get_infonet_status", return_value=fake):
        result = _dispatch_command("infonet_status", {})
    assert result == fake


def test_dispatch_list_gates_mocked():
    fake = {"ok": True, "gates": [{"id": "infonet"}]}
    with patch("services.openclaw_infonet.list_gates", return_value=fake):
        result = _dispatch_command("list_gates", {})
    assert result["gates"][0]["id"] == "infonet"


def test_dispatch_post_gate_message_mocked():
    fake = {"ok": True, "event_id": "evt-test"}
    with patch("services.openclaw_infonet.post_gate_message", return_value=fake):
        result = _dispatch_command(
            "post_gate_message",
            {"gate_id": "infonet", "plaintext": "agent bulletin"},
        )
    assert result["event_id"] == "evt-test"


def test_cast_vote_rejects_invalid_vote():
    result = _dispatch_command("cast_vote", {"target_id": "!sb_test", "vote": 2})
    assert result["ok"] is False
