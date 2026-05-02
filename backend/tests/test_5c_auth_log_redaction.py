"""Phase 5C — auth.py log redaction tests.

Validates that:
1. Malformed MESH_SCOPED_TOKENS returns {}
2. Malformed MESH_SCOPED_TOKENS logging does not include token fragments
3. Malformed MESH_SCOPED_TOKENS logging still includes a safe signal (e.g. JSONDecodeError)
4. Valid MESH_SCOPED_TOKENS mapping still parses correctly
"""
import json
import logging

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _patch_settings(monkeypatch, raw_value: str):
    """Patch get_settings().MESH_SCOPED_TOKENS to return *raw_value*."""
    import auth

    class _FakeSettings:
        MESH_SCOPED_TOKENS = raw_value

    monkeypatch.setattr(auth, "get_settings", lambda: _FakeSettings())


# ---------------------------------------------------------------------------
# 1. Malformed input returns empty dict
# ---------------------------------------------------------------------------

class TestMalformedReturnsEmpty:
    def test_truncated_json_returns_empty(self, monkeypatch):
        import auth
        _patch_settings(monkeypatch, '{"tok_secret_abc": ["gate"')
        assert auth._scoped_admin_tokens() == {}

    def test_plain_string_returns_empty(self, monkeypatch):
        import auth
        _patch_settings(monkeypatch, "not-json-at-all")
        assert auth._scoped_admin_tokens() == {}

    def test_array_returns_empty(self, monkeypatch):
        """JSON array is valid JSON but not an object mapping."""
        import auth
        _patch_settings(monkeypatch, '["tok_secret_abc"]')
        assert auth._scoped_admin_tokens() == {}


# ---------------------------------------------------------------------------
# 2. Log output does NOT include token fragments
# ---------------------------------------------------------------------------

class TestLogDoesNotLeakTokens:
    def test_truncated_json_log_omits_token_value(self, monkeypatch, caplog):
        import auth
        secret_fragment = "tok_secret_abc"
        _patch_settings(monkeypatch, f'{{"{secret_fragment}": ["gate"')
        with caplog.at_level(logging.WARNING, logger="auth"):
            auth._scoped_admin_tokens()
        log_text = caplog.text
        assert secret_fragment not in log_text

    def test_garbled_json_log_omits_embedded_token(self, monkeypatch, caplog):
        import auth
        secret_fragment = "Bearer_xyzzy_9999"
        _patch_settings(monkeypatch, f'{{"key": {secret_fragment}}}')
        with caplog.at_level(logging.WARNING, logger="auth"):
            auth._scoped_admin_tokens()
        log_text = caplog.text
        assert secret_fragment not in log_text


# ---------------------------------------------------------------------------
# 3. Log output still includes a safe observable signal
# ---------------------------------------------------------------------------

class TestLogIncludesSafeSignal:
    def test_json_parse_failure_logs_exception_type(self, monkeypatch, caplog):
        import auth
        _patch_settings(monkeypatch, "{bad json")
        with caplog.at_level(logging.WARNING, logger="auth"):
            auth._scoped_admin_tokens()
        assert "JSONDecodeError" in caplog.text

    def test_warning_level_emitted(self, monkeypatch, caplog):
        import auth
        _patch_settings(monkeypatch, "{bad json")
        with caplog.at_level(logging.WARNING, logger="auth"):
            auth._scoped_admin_tokens()
        assert any(r.levelno == logging.WARNING for r in caplog.records)


# ---------------------------------------------------------------------------
# 4. Valid input still parses correctly
# ---------------------------------------------------------------------------

class TestValidInputParses:
    def test_single_token_single_scope(self, monkeypatch):
        import auth
        _patch_settings(monkeypatch, json.dumps({"my-token": ["gate"]}))
        result = auth._scoped_admin_tokens()
        assert result == {"my-token": ["gate"]}

    def test_multiple_tokens_multiple_scopes(self, monkeypatch):
        import auth
        payload = {"tok-a": ["gate", "dm"], "tok-b": ["wormhole"]}
        _patch_settings(monkeypatch, json.dumps(payload))
        result = auth._scoped_admin_tokens()
        assert result == payload

    def test_empty_string_returns_empty(self, monkeypatch):
        import auth
        _patch_settings(monkeypatch, "")
        assert auth._scoped_admin_tokens() == {}

    def test_whitespace_only_returns_empty(self, monkeypatch):
        import auth
        _patch_settings(monkeypatch, "   ")
        assert auth._scoped_admin_tokens() == {}

    def test_scalar_scope_normalized_to_list(self, monkeypatch):
        import auth
        _patch_settings(monkeypatch, json.dumps({"tok": "gate"}))
        result = auth._scoped_admin_tokens()
        assert result == {"tok": ["gate"]}
