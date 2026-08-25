"""Voice-router topology guards (voice-agent plan §7.B, items 17–20).

17. AST walk of ``routers/voice.py``: no module-level import of ``main``
    (mirrors ``test_3c_router_extraction.py``).
18. Source assertions on ``main.py`` wiring: the MESH_ONLY stub, exactly one
    lazy else-branch load, exactly one include; no scheduler/`add_job`
    reference added to ``data_fetcher.py`` for voice; voice router absent from
    any lean import list.
19. Unbrokered-speech-egress guard: neither ``SpeechRecognition`` nor
    ``webkitSpeechRecognition`` may appear anywhere under
    ``frontend/src/**/*.{ts,tsx}`` (empty allow-list). Chromium's
    SpeechRecognition ships mic audio to Google cloud — unbrokered egress that
    cannot be metered or gated. See ``docs/OUTBOUND_DATA.md``.
20. Watchdog decoupling grep: no ``from services.openclaw_watchdog import`` in
    ``routers/voice.py`` / ``services/voice_tool_registry.py``.
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
FRONTEND_SRC = REPO_ROOT / "frontend" / "src"


def _backend_source(rel: str) -> str:
    return (BACKEND_ROOT / rel).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 17 — no module-level import of main in routers/voice.py
# ---------------------------------------------------------------------------


class TestVoiceRouterNoModuleLevelMainImport:
    def test_no_module_level_main_import(self):
        source = _backend_source("routers/voice.py")
        tree = ast.parse(source)
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "main", (
                        f"routers/voice.py has a module-level 'import main' at line {node.lineno}"
                    )
            if isinstance(node, ast.ImportFrom):
                assert node.module != "main", (
                    f"routers/voice.py has a module-level 'from main import' at line {node.lineno}"
                )

    def test_no_scheduler_references_for_voice(self):
        """No APScheduler entry for voice anywhere in the new surface (§1.5)."""
        for rel in ("routers/voice.py", "services/voice_broker.py",
                    "services/voice_session_tokens.py"):
            source = _backend_source(rel)
            assert "apscheduler" not in source.lower(), f"{rel} must not reference APScheduler"
            assert "add_job" not in source, f"{rel} must not add scheduler jobs"

    def test_no_voice_scheduler_entry_in_data_fetcher(self):
        source = _backend_source("services/data_fetcher.py")
        for line in source.splitlines():
            low = line.lower()
            assert not ("voice" in low and ("add_job" in low or "scheduler" in low)), (
                f"data_fetcher.py must gain no scheduler entry for voice, found: {line.strip()!r}"
            )


# ---------------------------------------------------------------------------
# 18 — main.py wiring source assertions
# ---------------------------------------------------------------------------


def _branch_segment(main_source: str, start_marker: str, end_markers: list[str]) -> str:
    """Return the source segment after ``start_marker`` up to the first line
    that starts with any of ``end_markers``."""
    idx = main_source.index(start_marker)
    segment = main_source[idx:]
    end = len(segment)
    for marker in end_markers:
        pos = segment.find("\n" + marker)
        if pos != -1:
            end = min(end, pos)
    return segment[:end]


class TestMainWiring:
    def _main_source(self) -> str:
        return _backend_source("main.py")

    def test_mesh_only_branch_has_empty_stub(self):
        source = self._main_source()
        branch = _branch_segment(source, "if _MESH_ONLY:", ["else:"])
        assert "voice_router = APIRouter()" in branch, (
            "main.py's `if _MESH_ONLY:` branch must stub voice_router = APIRouter()"
        )
        assert "_load_optional_router(\"routers.voice\")" not in branch, (
            "lean mode must never import routers.voice"
        )

    def test_else_branch_loads_voice_router_exactly_once(self):
        source = self._main_source()
        assert source.count('_load_optional_router("routers.voice")') == 1, (
            'main.py must call _load_optional_router("routers.voice") exactly once'
        )
        branch = _branch_segment(source, "\nelse:", ['\n\n#'])
        assert '_load_optional_router("routers.voice")' in branch, (
            "the lazy routers.voice load must live only in the else (non-lean) branch"
        )

    def test_voice_router_included_exactly_once_after_agent_shell(self):
        source = self._main_source()
        assert source.count("app.include_router(voice_router)") == 1
        agent_shell_idx = source.index("app.include_router(agent_shell_router)")
        voice_idx = source.index("app.include_router(voice_router)")
        assert agent_shell_idx < voice_idx, (
            "app.include_router(voice_router) must follow app.include_router(agent_shell_router)"
        )


# ---------------------------------------------------------------------------
# 19 — unbrokered-speech-egress guard (SpeechRecognition prohibition, §1.4)
# ---------------------------------------------------------------------------


class TestSpeechRecognitionEgressGuard:
    def test_no_speech_recognition_anywhere_in_frontend_src(self):
        offenders: list[str] = []
        patterns = ("*.ts", "*.tsx")
        seen: set[Path] = set()
        for pattern in patterns:
            for path in FRONTEND_SRC.rglob(pattern):
                if path in seen:
                    continue
                seen.add(path)
                try:
                    text = path.read_text(encoding="utf-8")
                except OSError:
                    continue
                if "SpeechRecognition" in text:
                    offenders.append(str(path.relative_to(REPO_ROOT)))
        assert not offenders, (
            "Browser SpeechRecognition is PROHIBITED (its Chromium implementation ships "
            "mic audio to Google cloud — unbrokered egress). Found in: "
            + ", ".join(offenders)
            + ". Degraded input must be typed text via POST /api/voice/chat. "
            "See docs/OUTBOUND_DATA.md; the sanctioned future path is a server-brokered "
            "STT endpoint behind the same two-step opt-in gate."
        )


# ---------------------------------------------------------------------------
# 20 — watchdog decoupling
# ---------------------------------------------------------------------------


class TestWatchdogDecoupling:
    def test_no_watchdog_import_in_voice_modules(self):
        for rel in ("routers/voice.py", "services/voice_tool_registry.py"):
            source = _backend_source(rel)
            assert "from services.openclaw_watchdog import" not in source, (
                f"{rel} must not import openclaw_watchdog — voice consumes watchdog "
                "alerts as wire-format context events only (§3.8)"
            )
