"""Interrogation relay — §2.7 "why this alert?" / "who is this aircraft?".

Pure orchestration over EXISTING surfaces (no new query engine): local target
resolution against the client grounding snapshot, then the operator's question
is answered through the ``correlate_entity`` / ``get_entity_profile`` /
``gt_dossier`` server commands already dispatched by
``services.openclaw_channel._dispatch_command`` — tier gating is inherited via
``services.voice_tool_registry.validate_and_gate`` exactly like every other
picker call. The command envelope rides back to the model verbatim as an
evidence pack (second user message), and narration obeys the shared
``NARRATION_RULES`` (only ok:true content asserted; errors quoted verbatim).

Per-session memory is capped at 2 exchanges (§2.7): the bounded store keeps
the last two question/answer pairs per session key and evicts whole sessions
LRU-style so one chatty operator can never grow the dict unbounded.

Import-topology (§1.5): module-level imports are stdlib + pure services only;
``openclaw_channel`` / ``voice_tool_registry`` / ``voice_broker`` are imported
inside function bodies.
"""

from __future__ import annotations

import json
import re
from collections import OrderedDict
from typing import Any

#: The §2.7 interrogation surface — all READ commands on the merged manifest.
INTERROGATION_COMMANDS: tuple[str, ...] = (
    "correlate_entity",
    "get_entity_profile",
    "gt_dossier",
)

#: Per-session interrogation memory cap (§2.7).
INTERROGATION_MEMORY_MAX_EXCHANGES = 2
#: Bounded number of live interrogation threads (LRU beyond this).
_INTERROGATION_SESSION_MAX = 64

_EVIDENCE_MAX_CHARS = 16000

# Question-keyword routing (local, no model): "why this alert?" wants cross-
# layer correlation evidence; "who is this aircraft?" wants the registry
# profile/dossier.
_RE_CORRELATE = re.compile(r"\b(why|correlat|related|link(?:ed)?|alert|anomal|match|pattern)\w*\b", re.I)
_RE_PROFILE = re.compile(r"\b(who|profile|registry|owner|operator|tail\s*number|registration|dossier|specs?\b|background)", re.I)


def _entity_refs_from_snapshot(snapshot: Any) -> list[dict[str, str]]:
    """Flatten sb.grounding.v1 entities into [{id, name, layer}] refs."""
    refs: list[dict[str, str]] = []
    if not isinstance(snapshot, dict):
        return refs
    entities = snapshot.get("entities")
    if not isinstance(entities, list):
        return refs
    for entity in entities[:24]:
        if not isinstance(entity, dict):
            continue
        entity_id = str(entity.get("id") or "").strip()[:24]
        if not entity_id:
            continue
        refs.append(
            {
                "id": entity_id,
                "name": str(entity.get("name") or "")[:40],
                "layer": str(entity.get("layer") or "")[:24],
            }
        )
    return refs


def _mentions(ref_value: str, question: str) -> bool:
    needle = ref_value.strip().lower()
    haystack = str(question or "").lower()
    if len(needle) < 3:
        # Short ids/hex need exact-token treatment; substring false-positives
        # (hex "ab1" inside random words) are worse than a miss.
        return False
    return needle in haystack


def resolve_interrogation_target(
    question: str,
    *,
    snapshot: Any = None,
    target: Any = None,
) -> dict[str, Any] | None:
    """Resolve WHAT the operator is pointing at, locally (§2.7).

    Returns ``{"cmd", "args", "entity"}`` or ``None`` when nothing in the view
    matches — the caller answers honestly instead of guessing.

    Resolution order:
      1. explicit ``target`` (client selection / picker-supplied ref);
      2. first snapshot entity whose id/name the question mentions;
      3. a lone selected entity in the snapshot (single-entity views answer
         "why this alert?" without naming it).
    """
    text = str(question or "").strip()

    def pick_cmd() -> str:
        if _RE_CORRELATE.search(text):
            return "correlate_entity"
        if _RE_PROFILE.search(text):
            return "get_entity_profile"
        return "correlate_entity"

    entity: dict[str, str] | None = None

    if isinstance(target, dict):
        query = str(target.get("query") or target.get("id") or target.get("name") or "").strip()
        if query:
            entity = {
                "id": str(target.get("id") or query)[:24],
                "name": str(target.get("name") or query)[:40],
                "layer": str(target.get("layer") or "")[:24],
            }
    if entity is None:
        refs = _entity_refs_from_snapshot(snapshot)
        mentioned = [ref for ref in refs if _mentions(ref["id"], text) or _mentions(ref["name"], text)]
        if mentioned:
            entity = mentioned[0]
        elif refs:
            # Nothing named in the question ("why this alert?"): the top
            # snapshot entity is the subject. The resolved ref rides back in
            # the response `target` so the narrator names what it picked.
            entity = refs[0]
    if entity is None:
        return None

    cmd = pick_cmd()
    query = entity["name"] or entity["id"]
    args: dict[str, Any] = {"query": query}
    if entity["id"] and entity["id"] != query:
        # Layer-aware id hint: ships key on MMSI, everything else on ICAO24.
        if entity["layer"] == "ships":
            args["mmsi"] = entity["id"]
        else:
            args["icao24"] = entity["id"]
    return {"cmd": cmd, "args": args, "entity": entity}


# ---------------------------------------------------------------------------
# Evidence pack + message composition
# ---------------------------------------------------------------------------


def build_evidence_pack(envelope: Any) -> str:
    """Verbatim dispatcher envelope as the second user message (§2.7).

    Free-text fields stay DATA — the narration rules' injection defense
    covers anything embedded in them.
    """
    try:
        encoded = json.dumps(envelope, default=str)
    except (TypeError, ValueError):
        encoded = '{"ok": false, "error": "evidence serialization failed"}'
    return f"EVIDENCE PACK (verbatim tool envelope):\n{encoded[:_EVIDENCE_MAX_CHARS]}"


def compose_interrogation_messages(
    question: str,
    *,
    snapshot: Any = None,
    evidence: str | None = None,
    memory: list[dict[str, str]] | None = None,
    mode: str = "full",
) -> list[dict[str, str]]:
    """Chat messages: narration rules + grounding header + prior exchanges +
    the ask + the evidence pack."""
    from services.voice_narration import NARRATION_RULES, build_grounding_header

    rules = NARRATION_RULES + (
        "\n\nINTERROGATION CONTRACT: you are answering a follow-up question "
        "about something on the operator's screen. Ground EVERY claim in the "
        "EVIDENCE PACK below; quote its error text verbatim when ok:false; "
        'describe cross-layer matches as "consistent with".'
    )
    if mode == "mesh_lean":
        rules += "\n\nThis node runs in MESH lean mode: state that plainly."
    messages: list[dict[str, str]] = [{"role": "system", "content": rules}]
    if snapshot is not None:
        messages.append({"role": "user", "content": build_grounding_header(snapshot)})
    for exchange in (memory or [])[-INTERROGATION_MEMORY_MAX_EXCHANGES:]:
        q = str(exchange.get("question") or "")[:400]
        a = str(exchange.get("answer") or "")[:1200]
        messages.append({"role": "user", "content": f"(earlier) {q}"})
        messages.append({"role": "assistant", "content": a})
    messages.append({"role": "user", "content": str(question or "").strip()})
    if evidence:
        messages.append({"role": "user", "content": evidence})
    return messages


# ---------------------------------------------------------------------------
# Bounded per-session memory (cap: 2 exchanges, LRU sessions)
# ---------------------------------------------------------------------------

_memory: OrderedDict[str, OrderedDict[int, dict[str, str]]] = OrderedDict()
_memory_seq = 0


def get_interrogation_memory(session_key: str) -> list[dict[str, str]]:
    thread = _memory.get(str(session_key or "default"))
    if not thread:
        return []
    return [dict(entry) for entry in thread.values()]


def record_interrogation_exchange(session_key: str, question: str, answer: str) -> None:
    global _memory_seq
    key = str(session_key or "default")
    thread = _memory.get(key)
    if thread is None:
        thread = OrderedDict()
        _memory[key] = thread
    _memory_seq += 1
    thread[_memory_seq] = {"question": str(question or "")[:400], "answer": str(answer or "")[:1200]}
    while len(thread) > INTERROGATION_MEMORY_MAX_EXCHANGES:
        thread.popitem(last=False)
    _memory.move_to_end(key)
    while len(_memory) > _INTERROGATION_SESSION_MAX:
        _memory.popitem(last=False)


def reset_interrogation_memory_for_tests() -> None:
    _memory.clear()


# ---------------------------------------------------------------------------
# One interrogation turn
# ---------------------------------------------------------------------------


async def run_interrogation_turn(
    question: str,
    *,
    target: Any = None,
    snapshot: Any = None,
    session_key: str = "default",
    access_tier: str | None = None,
    settings=None,
) -> dict[str, Any]:
    """Resolve → gate → dispatch → narrate one interrogation turn (§2.7).

    Returns ``{"ok": True, "say", "command", "target", "evidence_ok"}``, a
    typed failure (``{"ok": False, "error": "no_target"}``), or the chat-leg
    error envelope (503/502 surfaces pass through untouched).
    """
    from services.config import get_settings
    from services.openclaw_channel import _dispatch_command
    from services.voice_broker import chat_completion
    from services.voice_narration import REFUSAL_TEMPLATE
    from services.voice_tool_registry import validate_and_gate

    s = settings or get_settings()
    if access_tier is None:
        access_tier = str(getattr(s, "OPENCLAW_ACCESS_TIER", "restricted") or "restricted").strip().lower()

    text = str(question or "").strip()
    if not text:
        return {"ok": False, "error": "empty_question"}

    resolved = resolve_interrogation_target(text, snapshot=snapshot, target=target)
    if resolved is None:
        # Honest refusal — never guess about an entity that is not in view.
        return {
            "ok": False,
            "error": "no_target",
            "detail": "No tracked entity in the current view matches the question.",
            "say": REFUSAL_TEMPLATE,
        }

    cmd = resolved["cmd"]
    clean_call, error = validate_and_gate({"tool": cmd, "args": dict(resolved["args"])}, access_tier=access_tier)
    if error is not None:
        return {"ok": False, "error": "gate_blocked", **error}

    envelope = _dispatch_command(clean_call["tool"], clean_call.get("args") or {})
    evidence_ok = bool(envelope.get("ok")) if isinstance(envelope, dict) else False
    evidence = build_evidence_pack(envelope)

    mode = "mesh_lean" if str(getattr(s, "MESH_ONLY", "") or "").strip().lower() in ("1", "true", "yes") else "full"
    messages = compose_interrogation_messages(
        text,
        snapshot=snapshot,
        evidence=evidence,
        memory=get_interrogation_memory(session_key),
        mode=mode,
    )
    leg = await chat_completion(messages, settings=s)
    if not leg.get("ok"):
        return dict(leg)

    say = str(leg.get("reply") or "").strip()
    record_interrogation_exchange(session_key, text, say)
    return {
        "ok": True,
        "say": say,
        "command": clean_call["tool"],
        "target": resolved["entity"],
        "evidence_ok": evidence_ok,
        "mode": mode,
    }
