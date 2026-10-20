"""Tor hidden service must always publish the mesh SOCKS port."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from services import tor_hidden_service as tor_svc


def test_write_torrc_always_includes_socks_port(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tor_svc, "TOR_DIR", tmp_path)
    monkeypatch.setattr(tor_svc, "TORRC_PATH", tmp_path / "torrc")
    monkeypatch.setattr(tor_svc, "TOR_DATA_DIR", tmp_path / "data")

    tor_svc._write_torrc(target_port=8000, socks_port=19050)

    content = tor_svc.TORRC_PATH.read_text(encoding="utf-8")
    assert "SocksPort 19050" in content
    assert "HiddenServicePort 8000 127.0.0.1:8000" in content


def test_torrc_has_socks_port_detects_missing_line(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tor_svc, "TORRC_PATH", tmp_path / "torrc")
    tor_svc.TORRC_PATH.write_text("HiddenServicePort 8000 127.0.0.1:8000\n", encoding="utf-8")

    assert tor_svc._torrc_has_socks_port(9050) is False

    tor_svc.TORRC_PATH.write_text("SocksPort 9050\n", encoding="utf-8")
    assert tor_svc._torrc_has_socks_port(9050) is True


def test_local_socks_handshake_ready_accepts_valid_response(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeSock:
        def __init__(self) -> None:
            self._sent = b""

        def settimeout(self, timeout: float) -> None:
            return None

        def sendall(self, payload: bytes) -> None:
            self._sent = payload

        def recv(self, size: int) -> bytes:
            assert self._sent == b"\x05\x01\x00"
            return b"\x05\x00"

        def __enter__(self) -> "FakeSock":
            return self

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *_args, **_kwargs: FakeSock(),
    )
    assert tor_svc._local_socks_handshake_ready(9050) is True
