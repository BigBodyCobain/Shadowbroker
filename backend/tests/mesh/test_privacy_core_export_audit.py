from __future__ import annotations

import pytest

from services import privacy_core_client


def _fake_library(*, missing: set[str] | None = None):
    missing = set(missing or set())
    library = type("FakePrivacyCoreLibrary", (), {})()
    for symbol in privacy_core_client._REQUIRED_PRIVACY_CORE_EXPORTS:
        if symbol in missing:
            continue
        setattr(library, symbol, object())
    return library


def test_privacy_core_load_skips_export_audit_when_flag_disabled(monkeypatch, tmp_path):
    library_path = tmp_path / "privacy_core.dll"
    library_path.write_bytes(b"stub")

    monkeypatch.setenv("PRIVACY_CORE_EXPORT_SET_AUDIT_ENABLE", "false")
    monkeypatch.setattr(
        privacy_core_client.ctypes,
        "CDLL",
        lambda _path: _fake_library(missing={"privacy_core_dm_session_fingerprint"}),
    )
    monkeypatch.setattr(
        privacy_core_client.PrivacyCoreClient,
        "_resolve_library_path",
        staticmethod(lambda _path=None: library_path),
    )
    monkeypatch.setattr(privacy_core_client.PrivacyCoreClient, "_configure_functions", lambda self: None)

    client = privacy_core_client.PrivacyCoreClient.load()

    assert client.library_path == library_path


def test_privacy_core_load_rejects_missing_export_when_flag_enabled(monkeypatch, tmp_path):
    library_path = tmp_path / "privacy_core.dll"
    library_path.write_bytes(b"stub")

    monkeypatch.setenv("PRIVACY_CORE_EXPORT_SET_AUDIT_ENABLE", "true")
    monkeypatch.setattr(
        privacy_core_client.ctypes,
        "CDLL",
        lambda _path: _fake_library(missing={"privacy_core_dm_session_fingerprint"}),
    )
    monkeypatch.setattr(
        privacy_core_client.PrivacyCoreClient,
        "_resolve_library_path",
        staticmethod(lambda _path=None: library_path),
    )
    monkeypatch.setattr(privacy_core_client.PrivacyCoreClient, "_configure_functions", lambda self: None)

    with pytest.raises(privacy_core_client.PrivacyCoreUnavailable) as excinfo:
        privacy_core_client.PrivacyCoreClient.load()

    assert "privacy_core_dm_session_fingerprint" in str(excinfo.value)


def test_privacy_core_load_accepts_complete_export_set_when_flag_enabled(monkeypatch, tmp_path):
    library_path = tmp_path / "privacy_core.dll"
    library_path.write_bytes(b"stub")

    monkeypatch.setenv("PRIVACY_CORE_EXPORT_SET_AUDIT_ENABLE", "true")
    monkeypatch.setattr(
        privacy_core_client.ctypes,
        "CDLL",
        lambda _path: _fake_library(),
    )
    monkeypatch.setattr(
        privacy_core_client.PrivacyCoreClient,
        "_resolve_library_path",
        staticmethod(lambda _path=None: library_path),
    )
    monkeypatch.setattr(privacy_core_client.PrivacyCoreClient, "_configure_functions", lambda self: None)

    client = privacy_core_client.PrivacyCoreClient.load()

    assert client.library_path == library_path
