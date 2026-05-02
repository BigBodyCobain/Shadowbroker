from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import auth
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


def _fake_client(monkeypatch, library_path: Path, *, version: str = "privacy-core/0.9.6-test") -> None:
    class _FakeClient:
        def __init__(self, path: Path) -> None:
            self.library_path = path

        def version(self) -> str:
            return version

    monkeypatch.setattr(
        privacy_core_attestation.PrivacyCoreClient,
        "load",
        classmethod(lambda cls: _FakeClient(library_path)),
    )


def test_current_trusted_hash_and_version_pass_attestation(monkeypatch, tmp_path):
    library_path = tmp_path / "privacy_core.dll"
    payload = b"privacy-core-test-artifact"
    library_path.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    _fake_client(monkeypatch, library_path)

    attestation = privacy_core_attestation.privacy_core_attestation(
        _settings(PRIVACY_CORE_ALLOWED_SHA256=digest)
    )

    assert attestation["attestation_state"] == "attested_current"
    assert attestation["policy_ok"] is True
    assert attestation["loaded_version"] == "privacy-core/0.9.6-test"
    assert attestation["loaded_hash"] == digest
    assert attestation["trusted_hash"] == digest
    assert attestation["manifest_source"] == "settings.PRIVACY_CORE_ALLOWED_SHA256"


def test_unenrolled_artifact_reports_unattested_unenrolled(monkeypatch, tmp_path):
    library_path = tmp_path / "privacy_core.dll"
    payload = b"privacy-core-test-artifact"
    library_path.write_bytes(payload)
    _fake_client(monkeypatch, library_path)

    attestation = privacy_core_attestation.privacy_core_attestation(_settings())

    assert attestation["available"] is True
    assert attestation["attestation_state"] == "unattested_unenrolled"
    assert attestation["policy_ok"] is False
    assert attestation["detail"] == (
        "privacy-core loaded, but no trusted artifact hash enrollment is configured"
    )


def test_mismatched_artifact_reports_attestation_mismatch_without_mutation(monkeypatch, tmp_path):
    library_path = tmp_path / "privacy_core.dll"
    payload = b"privacy-core-test-artifact"
    library_path.write_bytes(payload)
    configured_hash = "ab" * 32
    _fake_client(monkeypatch, library_path)

    attestation = privacy_core_attestation.privacy_core_attestation(
        _settings(PRIVACY_CORE_ALLOWED_SHA256=configured_hash)
    )

    assert attestation["attestation_state"] == "attestation_mismatch"
    assert attestation["policy_ok"] is False
    assert attestation["trusted_hash"] == configured_hash
    assert attestation["loaded_hash"] != configured_hash


def test_mismatched_artifact_does_not_auto_repin_across_repeated_attestation_calls(monkeypatch, tmp_path):
    library_path = tmp_path / "privacy_core.dll"
    payload = b"privacy-core-test-artifact"
    library_path.write_bytes(payload)
    configured_hash = "ab" * 32
    _fake_client(monkeypatch, library_path)

    first = privacy_core_attestation.privacy_core_attestation(
        _settings(PRIVACY_CORE_ALLOWED_SHA256=configured_hash)
    )
    second = privacy_core_attestation.privacy_core_attestation(
        _settings(PRIVACY_CORE_ALLOWED_SHA256=configured_hash)
    )

    assert first["attestation_state"] == "attestation_mismatch"
    assert second["attestation_state"] == "attestation_mismatch"
    assert first["trusted_hash"] == configured_hash
    assert second["trusted_hash"] == configured_hash
    assert first["loaded_hash"] == second["loaded_hash"]
    assert first["loaded_hash"] != configured_hash


def test_development_override_reports_explicit_override(monkeypatch, tmp_path):
    library_path = tmp_path / "privacy_core.dll"
    payload = b"privacy-core-test-artifact"
    library_path.write_bytes(payload)
    _fake_client(monkeypatch, library_path)

    attestation = privacy_core_attestation.privacy_core_attestation(
        _settings(PRIVACY_CORE_DEV_OVERRIDE=True)
    )

    assert attestation["attestation_state"] == "development_override"
    assert attestation["override_active"] is True
    assert attestation["policy_ok"] is False
    assert "development override" in attestation["detail"]


def test_privacy_core_attestation_reports_failure_detail(monkeypatch):
    monkeypatch.setattr(
        privacy_core_attestation.PrivacyCoreClient,
        "load",
        classmethod(lambda cls: (_ for _ in ()).throw(RuntimeError("load failed"))),
    )

    attestation = privacy_core_attestation.privacy_core_attestation()

    assert attestation["available"] is False
    assert attestation["attestation_state"] == "attestation_stale_or_unknown"
    assert attestation["loaded_version"] == ""
    assert attestation["loaded_hash"] == ""
    assert attestation["policy_ok"] is False
    assert attestation["detail"] == "load failed"


def test_strong_claim_status_degrades_honestly_when_attestation_not_current(monkeypatch):
    monkeypatch.setattr(
        "services.privacy_core_attestation.privacy_core_attestation",
        lambda *_args, **_kwargs: {
            "attestation_state": "attestation_mismatch",
            "override_active": False,
            "detail": "privacy-core loaded, but its artifact hash does not match the trusted enrollment",
        },
    )
    monkeypatch.setattr(
        auth,
        "_anonymous_mode_state",
        lambda: {"enabled": True, "ready": True, "effective_transport": "tor_arti"},
    )
    monkeypatch.setattr(
        auth,
        "_external_assurance_status_snapshot",
        lambda: {
            "current": True,
            "configured": True,
            "state": "current_external",
            "detail": "configured external assurance is current",
        },
    )

    snapshot = auth._strong_claims_policy_snapshot(current_tier="private_strong")

    assert snapshot["allowed"] is False
    assert snapshot["privacy_core_attestation_state"] == "attestation_mismatch"
    assert "privacy_core_attestation_not_current" in snapshot["reasons"]


def test_release_gate_status_exposes_new_attestation_fields(monkeypatch):
    monkeypatch.setattr(
        main,
        "_privacy_core_status",
        lambda: {
            "available": True,
            "policy_ok": False,
            "attestation_state": "attestation_mismatch",
            "loaded_version": "privacy-core/0.9.6-test",
            "loaded_hash": "cd" * 32,
            "trusted_hash": "ab" * 32,
            "manifest_source": "settings.PRIVACY_CORE_ALLOWED_SHA256",
            "override_active": False,
            "detail": "privacy-core loaded, but its artifact hash does not match the trusted enrollment",
        },
    )
    monkeypatch.setattr(
        main,
        "_release_attestation_snapshot",
        lambda: {"dm_relay_security_suite_green": True, "detail": "green"},
    )

    status = main._release_gate_status(
        strong_claims={
            "compatibility": {},
            "compat_overrides_clear": True,
            "clearnet_fallback_blocked": True,
            "external_assurance_current": True,
            "external_assurance_configured": True,
            "external_assurance_state": "current_external",
            "external_assurance_detail": "current",
        }
    )

    criterion = status["criteria"]["privacy_core_pinned"]
    assert criterion["ok"] is False
    assert criterion["attestation_state"] == "attestation_mismatch"
    assert criterion["loaded_version"] == "privacy-core/0.9.6-test"
    assert criterion["loaded_hash"] == "cd" * 32
    assert criterion["trusted_hash"] == "ab" * 32
    assert criterion["manifest_source"] == "settings.PRIVACY_CORE_ALLOWED_SHA256"
    assert criterion["override_active"] is False
