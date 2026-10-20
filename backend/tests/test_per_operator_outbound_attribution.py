"""Round 7a: per-install operator handle threads through every outbound
third-party API call.

Background: before this change every Shadowbroker install identified
itself to Wikipedia, Wikidata, Nominatim, GDELT, OpenMHz, Broadcastify,
weather.gov, NUFORC, etc. with a single project-wide ``Shadowbroker``
User-Agent. From the upstream's perspective, every install in the world
looked like one giant scraper. If one install misbehaved, the upstream's
only recourse was to block ``Shadowbroker`` as a whole, taking out every
other install.

Fix: each install gets a stable pseudonymous handle (auto-generated like
``shadow-7f3a92`` or operator-overridden via ``OPERATOR_HANDLE``) that
gets embedded in the User-Agent for every outbound call. Upstreams can
now rate-limit / contact the specific operator instead of the project.

These tests pin:

  1. The handle is auto-generated on first call if no override exists.
  2. The handle survives process restart (persisted to disk).
  3. ``OPERATOR_HANDLE`` env var override wins over the auto-gen handle.
  4. The handle is sanitized (whitespace, special chars, length).
  5. Every previously-MONSTER-UA call site now sends the per-operator UA.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def isolated_handle(tmp_path, monkeypatch):
    """Redirect the persistence path to tmp and reset caches between tests."""
    from services import network_utils

    handle_file = tmp_path / "operator_handle.json"
    monkeypatch.setattr(network_utils, "_OPERATOR_HANDLE_FILE", handle_file)
    network_utils._reset_operator_handle_cache_for_tests()
    monkeypatch.delenv("OPERATOR_HANDLE", raising=False)

    # Reset Settings cache so OPERATOR_HANDLE env changes are picked up.
    from services.config import get_settings
    get_settings.cache_clear()

    yield network_utils

    network_utils._reset_operator_handle_cache_for_tests()
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Core handle generation / persistence / override
# ---------------------------------------------------------------------------


class TestOperatorHandleGeneration:
    def test_auto_generates_on_first_call(self, isolated_handle):
        h = isolated_handle.get_operator_handle()
        # Prefix is "operator-" (deliberately neutral; "shadow-" looked
        # exactly like a pattern abuse-detection systems would auto-block).
        assert h.startswith("operator-")
        assert len(h) == len("operator-") + 6
        # Hex suffix.
        suffix = h.split("-", 1)[1]
        int(suffix, 16)  # raises if not hex

    def test_persists_to_disk_so_handle_survives_restart(self, isolated_handle):
        first = isolated_handle.get_operator_handle()
        # Simulate process restart: clear in-memory cache, then ask again.
        isolated_handle._reset_operator_handle_cache_for_tests()
        second = isolated_handle.get_operator_handle()
        assert second == first
        # The file actually exists.
        assert isolated_handle._OPERATOR_HANDLE_FILE.exists()
        body = json.loads(isolated_handle._OPERATOR_HANDLE_FILE.read_text())
        assert body["handle"] == first

    def test_env_override_wins_over_auto_generated(self, isolated_handle, monkeypatch):
        # First call without env var auto-generates.
        auto = isolated_handle.get_operator_handle()
        assert auto.startswith("operator-")
        # Setting env var changes the resolved handle without touching the disk file.
        monkeypatch.setenv("OPERATOR_HANDLE", "alice")
        from services.config import get_settings
        get_settings.cache_clear()
        isolated_handle._reset_operator_handle_cache_for_tests()
        assert isolated_handle.get_operator_handle() == "alice"

    def test_handle_is_sanitized(self, isolated_handle, monkeypatch):
        from services.config import get_settings

        # Sanitization tests run against the normalizer directly so the
        # empty-string case can be asserted independently of the env-var
        # resolution path (where empty means "use auto-gen", not "use
        # 'anonymous'").
        from services.network_utils import _normalize_handle

        cases = [
            ("Alice Smith", "alice-smith"),
            ("user@example.com", "user-example-com"),
            ("  whitespace  ", "whitespace"),
            ("UPPER-CASE", "upper-case"),
            ("multiple---dashes", "multiple-dashes"),
            ("/leading/slash", "leading-slash"),
            ("trailing-", "trailing"),
            ("", "anonymous"),
        ]
        for raw, expected in cases:
            got = _normalize_handle(raw)
            assert got == expected, f"{raw!r} -> {got!r}, expected {expected!r}"
            assert got == got.lower()
            for ch in got:
                assert ch.isalnum() or ch in "-_", f"unsafe char {ch!r} in {got!r}"
            assert "--" not in got

    def test_handle_is_length_capped(self, isolated_handle, monkeypatch):
        from services.config import get_settings

        monkeypatch.setenv("OPERATOR_HANDLE", "x" * 1000)
        get_settings.cache_clear()
        isolated_handle._reset_operator_handle_cache_for_tests()
        got = isolated_handle.get_operator_handle()
        assert len(got) <= 48


# ---------------------------------------------------------------------------
# outbound_user_agent() builds the right header
# ---------------------------------------------------------------------------


class TestOutboundUserAgentString:
    def test_ua_is_operator_handle(self, isolated_handle):
        ua = isolated_handle.outbound_user_agent()
        handle = isolated_handle.get_operator_handle()
        assert ua == handle

    def test_includes_purpose_when_provided(self, isolated_handle):
        ua = isolated_handle.outbound_user_agent("wikipedia")
        handle = isolated_handle.get_operator_handle()
        assert ua == f"{handle} (purpose: wikipedia)"

    def test_no_shadowbroker_product_token(self, isolated_handle):
        ua = isolated_handle.outbound_user_agent("nominatim")
        assert "shadowbroker" not in ua.lower()


# ---------------------------------------------------------------------------
# Wikipedia / Wikidata — retroactive fix for PR #284's MONSTER pattern
# ---------------------------------------------------------------------------


class TestWikimediaCallsAreNowPerOperator:
    def test_wikidata_call_uses_per_operator_ua(self, isolated_handle, monkeypatch):
        from services import region_dossier

        captured = []

        class _FakeResp:
            status_code = 200
            def json(self):
                return {"results": {"bindings": []}}

        def fake_fetch(url, **kwargs):
            captured.append(kwargs.get("headers") or {})
            return _FakeResp()

        monkeypatch.setattr(region_dossier, "fetch_with_curl", fake_fetch)
        region_dossier._fetch_wikidata_leader("Testlandia")

        assert captured, "Wikidata fetcher was not called"
        headers = captured[0]
        assert "User-Agent" in headers
        assert "Api-User-Agent" in headers
        handle = isolated_handle.get_operator_handle()
        for header_value in (headers["User-Agent"], headers["Api-User-Agent"]):
            assert header_value.startswith(handle), (
                f"Wikimedia UA must be the per-operator handle; got {header_value!r}"
            )

    def test_wikipedia_summary_uses_per_operator_ua(self, isolated_handle, monkeypatch):
        from services import region_dossier

        captured = []

        class _FakeResp:
            status_code = 200
            def json(self):
                return {
                    "type": "standard",
                    "description": "x",
                    "extract": "y",
                    "thumbnail": {"source": ""},
                }

        def fake_fetch(url, **kwargs):
            captured.append((url, kwargs.get("headers") or {}))
            return _FakeResp()

        monkeypatch.setattr(region_dossier, "fetch_with_curl", fake_fetch)
        region_dossier._fetch_local_wiki_summary("Paris", "France")

        wikipedia_hits = [c for c in captured if "wikipedia.org" in c[0]]
        assert wikipedia_hits, "Wikipedia summary fetch was not called"
        for _url, headers in wikipedia_hits:
            handle = isolated_handle.get_operator_handle()
            ua = headers.get("User-Agent", "")
            assert ua.startswith(handle), f"Wikipedia UA must be the operator handle; got {ua!r}"


# ---------------------------------------------------------------------------
# Generic round-7a regression guard
# ---------------------------------------------------------------------------


class TestNoMonsterUserAgentRemains:
    """The audit's underlying concern was that every Shadowbroker install
    looked like one entity. This test scans the codebase for the OLD
    aggregate identifier patterns and fails if a new one sneaks back in.

    We allow the strings to appear in:
      - comments (audit prose, change-log notes)
      - tests
      - .env.example (documentation)
    The test only fails if the string lives in actual outbound-request
    HEADER values without going through the per-operator helper.
    """

    BANNED_LITERALS = (
        "Shadowbroker/",
        "ShadowBroker-OSINT/1.0",
        "ShadowBroker-OSINT/0.9",
        "ShadowBroker-FeedIngester/1.0",
        "ShadowBroker/0.9.79 local Shodan connector",
        "ShadowBroker/0.9.79 Finnhub connector",
        "ShadowBroker/0.9.8 local Shodan connector",
        "ShadowBroker/0.9.8 Finnhub connector",
        "ShadowBroker/0.9.82 local Shodan connector",
        "ShadowBroker/0.9.82 Finnhub connector",
        "Mozilla/5.0 (compatible; ShadowBroker CCTV proxy)",
    )

    def test_no_banned_aggregate_user_agent_strings(self):
        from pathlib import Path

        backend_root = Path(__file__).parent.parent
        offenders = []
        for py in backend_root.rglob("*.py"):
            # Skip test files and any audit-context comments.
            rel = py.relative_to(backend_root).as_posix()
            if rel.startswith("tests/"):
                continue
            text = py.read_text(encoding="utf-8", errors="ignore")
            # Look only for the literal as part of a string in a User-Agent
            # context: cheap heuristic via "User-Agent" + literal coexisting
            # in the same file. A literal in a comment block won't trigger
            # because the same line won't have User-Agent surrounding it.
            for banned in self.BANNED_LITERALS:
                if banned in text:
                    # Walk lines to ensure it's a real header value.
                    for i, line in enumerate(text.splitlines(), 1):
                        if banned in line:
                            # Comments / docstrings are allowed — only fail
                            # if the line looks like a header assignment.
                            stripped = line.strip()
                            if stripped.startswith("#"):
                                continue
                            if '"User-Agent"' in line or "'User-Agent'" in line:
                                offenders.append(f"{rel}:{i}: {stripped[:120]}")
        assert not offenders, (
            "Round 7a regression: the following lines reintroduced an "
            "aggregate Shadowbroker User-Agent. Use "
            "outbound_user_agent('purpose') instead so the per-install "
            "operator handle is embedded.\n"
            + "\n".join(offenders)
        )
