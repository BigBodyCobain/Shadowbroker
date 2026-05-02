from __future__ import annotations

import json
import time

from services.mesh import mesh_secure_storage


def _fresh_transparency_env(tmp_path, monkeypatch):
    from services.mesh import (
        mesh_wormhole_identity,
        mesh_wormhole_persona,
        mesh_wormhole_root_manifest,
        mesh_wormhole_root_transparency,
    )
    from services.config import get_settings

    for env_name in (
        "MESH_DM_ROOT_EXTERNAL_WITNESS_IMPORT_PATH",
        "MESH_DM_ROOT_EXTERNAL_WITNESS_IMPORT_URI",
        "MESH_DM_ROOT_EXTERNAL_WITNESS_MAX_AGE_S",
        "MESH_DM_ROOT_EXTERNAL_WITNESS_WARN_AGE_S",
        "MESH_DM_ROOT_TRANSPARENCY_LEDGER_EXPORT_PATH",
        "MESH_DM_ROOT_TRANSPARENCY_LEDGER_READBACK_URI",
        "MESH_DM_ROOT_TRANSPARENCY_LEDGER_MAX_AGE_S",
        "MESH_DM_ROOT_TRANSPARENCY_LEDGER_WARN_AGE_S",
    ):
        monkeypatch.delenv(env_name, raising=False)

    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    monkeypatch.setattr(mesh_wormhole_persona, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_persona, "PERSONA_FILE", tmp_path / "wormhole_persona.json")
    monkeypatch.setattr(mesh_wormhole_persona, "LEGACY_DM_IDENTITY_FILE", tmp_path / "wormhole_identity.json")
    monkeypatch.setattr(mesh_wormhole_root_manifest, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_root_transparency, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "_MASTER_KEY_CACHE", None)
    monkeypatch.setattr(mesh_secure_storage, "_DOMAIN_KEY_CACHE", {})
    get_settings.cache_clear()
    return mesh_wormhole_persona, mesh_wormhole_identity, mesh_wormhole_root_manifest, mesh_wormhole_root_transparency


def test_publish_root_transparency_record_binds_manifest_and_receipts(tmp_path, monkeypatch):
    persona_mod, _identity_mod, manifest_mod, transparency_mod = _fresh_transparency_env(tmp_path, monkeypatch)

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    distribution = manifest_mod.publish_current_root_manifest(expires_in_s=3600, policy_version=3)
    published = transparency_mod.publish_root_transparency_record(distribution=distribution)
    verified = transparency_mod.verify_root_transparency_record(
        published["record"],
        distribution["manifest"],
        distribution["witnesses"],
    )

    assert published["ok"] is True
    assert verified["ok"] is True
    assert verified["record_index"] == 1
    assert verified["previous_record_fingerprint"] == ""
    assert verified["binding_fingerprint"] == published["binding_fingerprint"]


def test_get_current_root_transparency_record_reuses_and_appends_on_distribution_change(tmp_path, monkeypatch):
    persona_mod, _identity_mod, manifest_mod, transparency_mod = _fresh_transparency_env(tmp_path, monkeypatch)

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    first_distribution = manifest_mod.publish_current_root_manifest(expires_in_s=3600, policy_version=1)
    first_record = transparency_mod.get_current_root_transparency_record(distribution=first_distribution)
    reused_record = transparency_mod.get_current_root_transparency_record(distribution=first_distribution)
    second_distribution = manifest_mod.publish_current_root_manifest(expires_in_s=3600, policy_version=2)
    second_record = transparency_mod.get_current_root_transparency_record(distribution=second_distribution)

    assert first_record["ok"] is True
    assert reused_record["record_fingerprint"] == first_record["record_fingerprint"]
    assert second_record["ok"] is True
    assert second_record["record_fingerprint"] != first_record["record_fingerprint"]
    assert second_record["record_index"] == 2
    assert second_record["previous_record_fingerprint"] == first_record["record_fingerprint"]


def test_exported_root_transparency_ledger_is_chain_verifiable(tmp_path, monkeypatch):
    persona_mod, _identity_mod, manifest_mod, transparency_mod = _fresh_transparency_env(tmp_path, monkeypatch)

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    first_distribution = manifest_mod.publish_current_root_manifest(expires_in_s=3600, policy_version=1)
    transparency_mod.get_current_root_transparency_record(distribution=first_distribution)
    second_distribution = manifest_mod.publish_current_root_manifest(expires_in_s=3600, policy_version=2)
    current = transparency_mod.get_current_root_transparency_record(distribution=second_distribution)
    exported = transparency_mod.export_root_transparency_ledger()
    verified = transparency_mod.verify_root_transparency_ledger_export(exported["ledger"])

    assert current["ok"] is True
    assert exported["ok"] is True
    assert exported["record_count"] == 2
    assert verified["ok"] is True
    assert verified["record_count"] == 2
    assert verified["current_record_fingerprint"] == current["record_fingerprint"]
    assert verified["head_binding_fingerprint"] == current["binding_fingerprint"]


def test_exported_root_transparency_ledger_rejects_tampered_chain(tmp_path, monkeypatch):
    persona_mod, _identity_mod, manifest_mod, transparency_mod = _fresh_transparency_env(tmp_path, monkeypatch)

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    first_distribution = manifest_mod.publish_current_root_manifest(expires_in_s=3600, policy_version=1)
    transparency_mod.get_current_root_transparency_record(distribution=first_distribution)
    second_distribution = manifest_mod.publish_current_root_manifest(expires_in_s=3600, policy_version=2)
    transparency_mod.get_current_root_transparency_record(distribution=second_distribution)
    exported = transparency_mod.export_root_transparency_ledger()
    tampered = dict(exported["ledger"] or {})
    records = [dict(item or {}) for item in list(tampered.get("records") or [])]
    records[1]["payload"] = {
        **dict(records[1].get("payload") or {}),
        "previous_record_fingerprint": "",
    }
    tampered["records"] = records

    rejected = transparency_mod.verify_root_transparency_ledger_export(tampered)

    assert rejected["ok"] is False
    assert rejected["detail"] == "stable root transparency ledger chain mismatch"


def test_publish_root_transparency_ledger_to_file_and_read_back(tmp_path, monkeypatch):
    persona_mod, _identity_mod, manifest_mod, transparency_mod = _fresh_transparency_env(tmp_path, monkeypatch)

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    distribution = manifest_mod.publish_current_root_manifest(expires_in_s=3600, policy_version=1)
    transparency_mod.get_current_root_transparency_record(distribution=distribution)
    export_path = tmp_path / "published_root_transparency_ledger.json"

    published = transparency_mod.publish_root_transparency_ledger_to_file(path=str(export_path), max_records=8)
    loaded = transparency_mod.read_exported_root_transparency_ledger(str(export_path))

    assert published["ok"] is True
    assert published["path"] == str(export_path)
    assert export_path.exists()
    assert loaded["ok"] is True
    assert loaded["path"] == str(export_path)
    assert loaded["current_record_fingerprint"] == published["current_record_fingerprint"]
    assert loaded["head_binding_fingerprint"] == published["head_binding_fingerprint"]


def test_get_current_root_transparency_record_auto_publishes_configured_ledger(tmp_path, monkeypatch):
    persona_mod, _identity_mod, manifest_mod, transparency_mod = _fresh_transparency_env(tmp_path, monkeypatch)
    from services.config import get_settings

    ledger_path = tmp_path / "auto_root_transparency_ledger.json"
    monkeypatch.setenv("MESH_DM_ROOT_TRANSPARENCY_LEDGER_EXPORT_PATH", str(ledger_path))
    get_settings.cache_clear()

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    distribution = manifest_mod.publish_current_root_manifest(expires_in_s=3600, policy_version=1)
    current = transparency_mod.get_current_root_transparency_record(distribution=distribution)
    loaded = transparency_mod.read_exported_root_transparency_ledger(str(ledger_path))

    assert current["ok"] is True
    assert current["ledger_export_ok"] is True
    assert current["ledger_export_path"] == str(ledger_path)
    assert current["ledger_operator_state"] == "not_configured"
    assert ledger_path.exists()
    assert loaded["ok"] is True
    assert loaded["current_record_fingerprint"] == current["record_fingerprint"]


def test_get_current_root_transparency_record_verifies_configured_external_readback_uri(tmp_path, monkeypatch):
    persona_mod, _identity_mod, manifest_mod, transparency_mod = _fresh_transparency_env(tmp_path, monkeypatch)
    from services.config import get_settings

    ledger_path = tmp_path / "external_root_transparency_ledger.json"
    monkeypatch.setenv("MESH_DM_ROOT_TRANSPARENCY_LEDGER_EXPORT_PATH", str(ledger_path))
    monkeypatch.setenv("MESH_DM_ROOT_TRANSPARENCY_LEDGER_READBACK_URI", ledger_path.as_uri())
    get_settings.cache_clear()

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    distribution = manifest_mod.publish_current_root_manifest(expires_in_s=3600, policy_version=1)
    current = transparency_mod.get_current_root_transparency_record(distribution=distribution)

    assert current["ok"] is True
    assert current["ledger_export_ok"] is True
    assert current["ledger_readback_ok"] is True
    assert current["ledger_readback_source_ref"] == ledger_path.as_uri()
    assert current["ledger_readback_record_visible"] is True
    assert current["ledger_readback_binding_matches"] is True
    assert current["ledger_operator_state"] == "current"
    assert current["ledger_external_verification_required"] is False


def test_get_current_root_transparency_record_reports_stale_for_old_external_readback(tmp_path, monkeypatch):
    persona_mod, _identity_mod, manifest_mod, transparency_mod = _fresh_transparency_env(tmp_path, monkeypatch)
    from services.config import get_settings

    export_path = tmp_path / "published_root_transparency_ledger.json"
    readback_path = tmp_path / "external_root_transparency_readback.json"
    monkeypatch.setenv("MESH_DM_ROOT_TRANSPARENCY_LEDGER_EXPORT_PATH", str(export_path))
    monkeypatch.setenv("MESH_DM_ROOT_TRANSPARENCY_LEDGER_READBACK_URI", readback_path.as_uri())
    monkeypatch.setenv("MESH_DM_ROOT_TRANSPARENCY_LEDGER_MAX_AGE_S", "60")
    get_settings.cache_clear()

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    distribution = manifest_mod.publish_current_root_manifest(expires_in_s=3600, policy_version=1)
    current = transparency_mod.get_current_root_transparency_record(distribution=distribution)
    stale_ledger = json.loads(export_path.read_text(encoding="utf-8"))
    stale_ledger["exported_at"] = int(time.time()) - 120
    readback_path.write_text(json.dumps(stale_ledger, sort_keys=True, indent=2), encoding="utf-8")

    stale = transparency_mod.get_current_root_transparency_record(distribution=distribution)

    assert current["ledger_operator_state"] == "stale"
    assert current["ledger_external_verification_required"] is True
    assert stale["ok"] is True
    assert stale["ledger_readback_ok"] is False
    assert stale["ledger_operator_state"] == "stale"
    assert stale["ledger_external_verification_required"] is True
    assert stale["ledger_readback_exported_at"] > 0
    assert stale["ledger_readback_export_age_s"] >= 120
    assert stale["ledger_freshness_window_s"] == 60
    assert "external ledger stale" in str(stale["ledger_readback_detail"] or "")


def test_transparency_operator_status_reports_error_before_any_successful_export_or_readback(tmp_path, monkeypatch):
    _persona_mod, _identity_mod, _manifest_mod, transparency_mod = _fresh_transparency_env(tmp_path, monkeypatch)
    from services.config import get_settings

    missing_readback_path = tmp_path / "missing_root_transparency_ledger.json"
    monkeypatch.setenv("MESH_DM_ROOT_TRANSPARENCY_LEDGER_READBACK_URI", missing_readback_path.as_uri())
    get_settings.cache_clear()

    status = transparency_mod._transparency_operator_status({})

    assert status["ledger_readback_configured"] is True
    assert status["ledger_operator_state"] == "error"
    assert status["ledger_external_verification_required"] is True


def test_get_current_root_transparency_record_reports_stale_when_configured_readback_source_becomes_unreadable(
    tmp_path,
    monkeypatch,
):
    persona_mod, _identity_mod, manifest_mod, transparency_mod = _fresh_transparency_env(tmp_path, monkeypatch)
    from services.config import get_settings

    export_path = tmp_path / "published_root_transparency_ledger.json"
    readback_path = tmp_path / "external_root_transparency_readback.json"
    monkeypatch.setenv("MESH_DM_ROOT_TRANSPARENCY_LEDGER_EXPORT_PATH", str(export_path))
    monkeypatch.setenv("MESH_DM_ROOT_TRANSPARENCY_LEDGER_READBACK_URI", readback_path.as_uri())
    get_settings.cache_clear()

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    distribution = manifest_mod.publish_current_root_manifest(expires_in_s=3600, policy_version=1)
    first = transparency_mod.get_current_root_transparency_record(distribution=distribution)
    readback_path.write_text(export_path.read_text(encoding="utf-8"), encoding="utf-8")

    current = transparency_mod.get_current_root_transparency_record(distribution=distribution)
    readback_path.unlink()
    stale = transparency_mod.get_current_root_transparency_record(distribution=distribution)

    assert first["ledger_operator_state"] == "stale"
    assert current["ok"] is True
    assert current["ledger_operator_state"] == "current"
    assert current["ledger_external_verification_required"] is False
    assert stale["ok"] is True
    assert stale["record_fingerprint"] == current["record_fingerprint"]
    assert stale["ledger_readback_ok"] is False
    assert "unreadable" in str(stale["ledger_readback_detail"] or "")
    assert stale["ledger_operator_state"] == "stale"
    assert stale["ledger_external_verification_required"] is True
