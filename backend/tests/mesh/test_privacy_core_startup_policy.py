from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import main
from services import privacy_core_attestation


def _settings(**overrides):
    base = {
        "MESH_ARTI_ENABLED": False,
        "MESH_RNS_ENABLED": False,
        "PRIVACY_CORE_MIN_VERSION": "0.1.0",
        "PRIVACY_CORE_ALLOWED_SHA256": "",
        "PRIVACY_CORE_DEV_OVERRIDE": False,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_validate_privacy_core_startup_skips_without_private_lane():
    privacy_core_attestation.validate_privacy_core_startup(_settings())


def test_validate_privacy_core_startup_rejects_unenrolled_private_lane(monkeypatch):
    monkeypatch.setattr(
        privacy_core_attestation,
        "privacy_core_attestation",
        lambda *_args, **_kwargs: {
            "attestation_state": "unattested_unenrolled",
            "detail": "privacy-core loaded, but no trusted artifact hash enrollment is configured",
        },
    )

    with pytest.raises(SystemExit) as excinfo:
        privacy_core_attestation.validate_privacy_core_startup(
            _settings(MESH_RNS_ENABLED=True)
        )
    assert excinfo.value.code == 1


def test_validate_privacy_core_startup_rejects_mismatch_without_auto_repin(monkeypatch):
    monkeypatch.setattr(
        privacy_core_attestation,
        "privacy_core_attestation",
        lambda *_args, **_kwargs: {
            "attestation_state": "attestation_mismatch",
            "detail": "privacy-core loaded, but its artifact hash does not match the trusted enrollment",
        },
    )

    with pytest.raises(SystemExit) as excinfo:
        privacy_core_attestation.validate_privacy_core_startup(
            _settings(MESH_ARTI_ENABLED=True, PRIVACY_CORE_ALLOWED_SHA256="ab" * 32)
        )
    assert excinfo.value.code == 1


def test_validate_privacy_core_startup_accepts_attested_current(monkeypatch):
    monkeypatch.setattr(
        privacy_core_attestation,
        "privacy_core_attestation",
        lambda *_args, **_kwargs: {
            "attestation_state": "attested_current",
            "detail": "privacy-core version and trusted artifact hash are current",
        },
    )

    privacy_core_attestation.validate_privacy_core_startup(
        _settings(
            MESH_ARTI_ENABLED=True,
            PRIVACY_CORE_ALLOWED_SHA256="ab" * 32,
        )
    )


def test_validate_privacy_core_startup_rejects_development_override_in_private_lane(monkeypatch):
    monkeypatch.setattr(
        privacy_core_attestation,
        "privacy_core_attestation",
        lambda *_args, **_kwargs: {
            "attestation_state": "development_override",
            "detail": "privacy-core development override is active; artifact trust is not attested",
        },
    )

    with pytest.raises(SystemExit) as excinfo:
        privacy_core_attestation.validate_privacy_core_startup(
            _settings(MESH_ARTI_ENABLED=True, PRIVACY_CORE_DEV_OVERRIDE=True)
        )
    assert excinfo.value.code == 1


def test_validate_privacy_core_startup_exits_for_stale_or_unknown(monkeypatch):
    monkeypatch.setattr(
        privacy_core_attestation,
        "privacy_core_attestation",
        lambda *_args, **_kwargs: {
            "attestation_state": "attestation_stale_or_unknown",
            "detail": "privacy-core version is stale or unknown",
        },
    )

    with pytest.raises(SystemExit) as excinfo:
        privacy_core_attestation.validate_privacy_core_startup(
            _settings(
                MESH_ARTI_ENABLED=True,
                PRIVACY_CORE_ALLOWED_SHA256="ab" * 32,
            )
        )

    assert excinfo.value.code == 1


def test_lifespan_calls_privacy_core_startup_validation(monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(main, "_validate_insecure_admin_startup", lambda: calls.append("insecure"))
    monkeypatch.setattr(main, "_validate_admin_startup", lambda: calls.append("admin"))
    monkeypatch.setattr(main, "_validate_peer_push_secret", lambda: calls.append("peer"))

    def _raise():
        calls.append("privacy")
        raise RuntimeError("privacy-check-ran")

    monkeypatch.setattr(main, "_validate_privacy_core_startup", _raise)

    async def _enter() -> None:
        async with main.lifespan(main.app):
            pass

    with pytest.raises(RuntimeError, match="privacy-check-ran"):
        asyncio.run(_enter())

    assert calls == ["insecure", "admin", "peer", "privacy"]
