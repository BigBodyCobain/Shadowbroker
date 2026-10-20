"""Issue #350: Meshtastic callsign in outbound UA is opt-in, not default."""
import os

import pytest


def _send_callsign_header_from_env() -> bool:
    raw = str(os.environ.get("MESHTASTIC_SEND_CALLSIGN_HEADER", "false")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def test_default_does_not_send_callsign(monkeypatch):
    monkeypatch.setenv("MESHTASTIC_OPERATOR_CALLSIGN", "N0CALL")
    monkeypatch.delenv("MESHTASTIC_SEND_CALLSIGN_HEADER", raising=False)
    assert _send_callsign_header_from_env() is False


def test_opt_in_sends_callsign(monkeypatch):
    monkeypatch.setenv("MESHTASTIC_OPERATOR_CALLSIGN", "N0CALL")
    monkeypatch.setenv("MESHTASTIC_SEND_CALLSIGN_HEADER", "true")
    assert _send_callsign_header_from_env() is True


def test_various_falsy_values_do_not_opt_in(monkeypatch):
    for falsy in ("0", "false", "FALSE", "no", "off", ""):
        monkeypatch.setenv("MESHTASTIC_SEND_CALLSIGN_HEADER", falsy)
        assert _send_callsign_header_from_env() is False, f"value {falsy!r} should not opt in"
