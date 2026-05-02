from __future__ import annotations

import time


def _fresh_root_http_env(tmp_path, monkeypatch):
    from services.config import get_settings
    from services.mesh import (
        mesh_secure_storage,
        mesh_wormhole_persona,
        mesh_wormhole_root_manifest,
        mesh_wormhole_root_transparency,
    )

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
    mesh_wormhole_persona.bootstrap_wormhole_persona_state(force=True)
    return mesh_wormhole_root_manifest, mesh_wormhole_root_transparency


def _local_operator_override():
    return None


def _admin_override():
    return None


def test_http_root_distribution_and_transparency_export_work(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from auth import require_local_operator
    import main

    _manifest_mod, transparency_mod = _fresh_root_http_env(tmp_path, monkeypatch)

    main.app.dependency_overrides[require_local_operator] = _local_operator_override
    try:
        client = TestClient(main.app, raise_server_exceptions=False)
        distribution_resp = client.get("/api/wormhole/dm/root-distribution")
        transparency_resp = client.get("/api/wormhole/dm/root-transparency")
        health_resp = client.get("/api/wormhole/dm/root-health")
        runbook_resp = client.get("/api/wormhole/dm/root-health/runbook")
        alerts_resp = client.get("/api/wormhole/dm/root-health/alerts")
        ledger_resp = client.get("/api/wormhole/dm/root-transparency/ledger", params={"max_records": 8})

        distribution = distribution_resp.json()
        transparency = transparency_resp.json()
        health = health_resp.json()
        runbook = runbook_resp.json()
        alerts = alerts_resp.json()
        ledger = ledger_resp.json()
        verified_ledger = transparency_mod.verify_root_transparency_ledger_export(ledger.get("ledger"))

        assert distribution_resp.status_code == 200
        assert distribution["ok"] is True
        assert distribution["manifest"]
        assert len(distribution["witnesses"]) == 3
        assert "external_witness_refresh_ok" in distribution
        assert distribution["external_witness_operator_state"] == "not_configured"
        assert distribution["dm_root_operator_summary"]["state"] == "local_cached_only"
        assert distribution["dm_root_operator_summary"]["health_state"] == "warning"
        assert distribution["dm_root_operator_summary"]["recommended_actions"] == [
            "configure_external_witness_source",
            "configure_external_transparency_readback",
        ]

        assert transparency_resp.status_code == 200
        assert transparency["ok"] is True
        assert transparency["record"]
        assert "ledger_export_ok" in transparency
        assert transparency["ledger_operator_state"] == "not_configured"
        assert transparency["dm_root_operator_summary"]["state"] == "local_cached_only"
        assert transparency["dm_root_operator_summary"]["health_state"] == "warning"

        assert health_resp.status_code == 200
        assert health["ok"] is True
        assert health["state"] == "local_cached_only"
        assert health["health_state"] == "warning"
        assert health["strong_trust_blocked"] is False
        assert health["alert_count"] == 2
        assert health["warning_alert_count"] == 2
        assert health["blocking_alert_count"] == 0
        assert health["recommended_actions"] == [
            "configure_external_witness_source",
            "configure_external_transparency_readback",
        ]
        assert health["next_action"] == "configure_external_witness_source"
        assert health["monitoring"]["state"] == "warning"
        assert health["monitoring"]["page_required"] is False
        assert health["runbook"]["next_action"] == "configure_external_witness_source"
        assert health["runbook"]["urgency"] == "ticket"
        assert health["runbook"]["next_action_detail"]["title"] == "Configure external witness source"
        assert health["witness"]["state"] == "not_configured"
        assert health["transparency"]["state"] == "not_configured"

        assert runbook_resp.status_code == 200
        assert runbook["ok"] is True
        assert runbook["urgency"] == "ticket"
        assert runbook["next_action"] == "configure_external_witness_source"
        assert runbook["next_action_detail"]["target"] == "external_witness"
        assert runbook["actions"][0]["title"] == "Configure external witness source"
        assert runbook["actions"][0]["owner"] == "dm_root_ops"

        assert alerts_resp.status_code == 200
        assert alerts["ok"] is True
        assert alerts["state"] == "warning"
        assert alerts["page_required"] is False
        assert alerts["ticket_required"] is True
        assert alerts["active_alert_codes"] == [
            "external_witness_not_configured",
            "external_transparency_not_configured",
        ]
        assert alerts["next_action"] == "configure_external_witness_source"

        assert ledger_resp.status_code == 200
        assert ledger["ok"] is True
        assert ledger["record_count"] >= 1
        assert ledger["head_binding_fingerprint"] == transparency["binding_fingerprint"]
        assert verified_ledger["ok"] is True
        assert verified_ledger["current_record_fingerprint"] == transparency["record_fingerprint"]
    finally:
        main.app.dependency_overrides.pop(require_local_operator, None)


def test_http_external_witness_import_updates_live_root_distribution(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from auth import require_admin, require_local_operator
    import main

    manifest_mod, _transparency_mod = _fresh_root_http_env(tmp_path, monkeypatch)
    external_identity = manifest_mod._witness_identity_record(index=9)
    external_identity["management_scope"] = "external"
    external_identity["independence_group"] = "independent_a"

    main.app.dependency_overrides[require_admin] = _admin_override
    main.app.dependency_overrides[require_local_operator] = _local_operator_override
    try:
        client = TestClient(main.app, raise_server_exceptions=False)
        import_resp = client.post(
            "/api/wormhole/dm/root-witnesses/import",
            json={
                "material": {
                    "type": manifest_mod.STABLE_DM_ROOT_MANIFEST_EXTERNAL_WITNESS_IMPORT_TYPE,
                    "schema_version": 1,
                    "source_scope": "https_fetch",
                    "source_label": "witness-a",
                    "exported_at": int(time.time()),
                    "descriptors": [manifest_mod._public_witness_descriptor(external_identity)],
                }
            },
        )
        first_distribution = client.get("/api/wormhole/dm/root-distribution").json()
        external_receipt = manifest_mod._sign_with_witness_identity(
            identity=external_identity,
            event_type=manifest_mod.STABLE_DM_ROOT_MANIFEST_WITNESS_EVENT_TYPE,
            payload=manifest_mod._witness_payload(first_distribution["manifest"]),
        )
        restage_resp = client.post(
            "/api/wormhole/dm/root-witnesses/import",
            json={
                "material": {
                    "type": manifest_mod.STABLE_DM_ROOT_MANIFEST_EXTERNAL_WITNESS_IMPORT_TYPE,
                    "schema_version": 1,
                    "source_scope": "https_fetch",
                    "source_label": "witness-a",
                    "exported_at": int(time.time()),
                    "manifest_fingerprint": first_distribution["manifest_fingerprint"],
                    "witnesses": [external_receipt],
                }
            },
        )
        refreshed_distribution = client.get("/api/wormhole/dm/root-distribution").json()

        assert import_resp.status_code == 200
        assert import_resp.json()["ok"] is True
        assert restage_resp.status_code == 200
        assert restage_resp.json()["ok"] is True
        assert restage_resp.json()["witness_independent_quorum_met"] is True
        assert refreshed_distribution["ok"] is True
        assert refreshed_distribution["external_witness_source_scope"] == "https_fetch"
        assert refreshed_distribution["external_witness_source_label"] == "witness-a"
        assert len(refreshed_distribution["external_witness_descriptors"]) == 1
        assert len(refreshed_distribution["witnesses"]) == 4
        assert refreshed_distribution["external_witness_operator_state"] == "current"
        verified = manifest_mod.verify_root_manifest_witness_set(
            refreshed_distribution["manifest"],
            refreshed_distribution["witnesses"],
        )
        assert verified["ok"] is True
        assert verified["witness_independent_quorum_met"] is True
    finally:
        main.app.dependency_overrides.pop(require_admin, None)
        main.app.dependency_overrides.pop(require_local_operator, None)


def test_http_root_witness_import_config_and_transparency_publish_round_trip(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from auth import require_admin, require_local_operator
    import main

    manifest_mod, transparency_mod = _fresh_root_http_env(tmp_path, monkeypatch)
    external_identity = manifest_mod._witness_identity_record(index=9)
    external_identity["management_scope"] = "external"
    external_identity["independence_group"] = "independent_a"
    import_path = tmp_path / "external_root_witness_import.json"
    ledger_path = tmp_path / "published_root_transparency_ledger.json"
    import_path.write_text(
        manifest_mod._stable_json(
            {
                "type": manifest_mod.STABLE_DM_ROOT_MANIFEST_EXTERNAL_WITNESS_IMPORT_TYPE,
                "schema_version": 1,
                "source_scope": "file_export",
                "source_label": "witness-a",
                "exported_at": int(time.time()),
                "descriptors": [manifest_mod._public_witness_descriptor(external_identity)],
            }
        ),
        encoding="utf-8",
    )

    main.app.dependency_overrides[require_admin] = _admin_override
    main.app.dependency_overrides[require_local_operator] = _local_operator_override
    try:
        client = TestClient(main.app, raise_server_exceptions=False)
        import_resp = client.post(
            "/api/wormhole/dm/root-witnesses/import-config",
            json={"path": str(import_path)},
        )
        publish_resp = client.post(
            "/api/wormhole/dm/root-transparency/ledger/publish",
            json={"path": str(ledger_path), "max_records": 8},
        )
        published_resp = client.get(
            "/api/wormhole/dm/root-transparency/ledger/published",
            params={"path": str(ledger_path)},
        )

        imported = import_resp.json()
        published = publish_resp.json()
        loaded = published_resp.json()

        assert import_resp.status_code == 200
        assert imported["ok"] is True
        assert imported["source_path"] == str(import_path)
        assert imported["external_witness_source_scope"] == "file_export"

        assert publish_resp.status_code == 200
        assert published["ok"] is True
        assert published["path"] == str(ledger_path)
        assert ledger_path.exists()

        assert published_resp.status_code == 200
        assert loaded["ok"] is True
        assert loaded["path"] == str(ledger_path)
        assert loaded["current_record_fingerprint"] == published["current_record_fingerprint"]
        assert loaded["head_binding_fingerprint"] == published["head_binding_fingerprint"]

        verified = transparency_mod.verify_root_transparency_ledger_export(loaded["ledger"])
        assert verified["ok"] is True
    finally:
        main.app.dependency_overrides.pop(require_admin, None)
        main.app.dependency_overrides.pop(require_local_operator, None)


def test_http_root_endpoints_report_current_external_summary_when_external_sources_are_current(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from auth import require_admin, require_local_operator
    import main

    manifest_mod, _transparency_mod = _fresh_root_http_env(tmp_path, monkeypatch)
    external_identity = manifest_mod._witness_identity_record(index=9)
    external_identity["management_scope"] = "external"
    external_identity["independence_group"] = "independent_a"
    package_path = tmp_path / "external_root_witness_source.json"
    ledger_path = tmp_path / "external_root_transparency_ledger.json"

    monkeypatch.setenv("MESH_DM_ROOT_EXTERNAL_WITNESS_IMPORT_URI", package_path.as_uri())
    monkeypatch.setenv("MESH_DM_ROOT_TRANSPARENCY_LEDGER_EXPORT_PATH", str(ledger_path))
    monkeypatch.setenv("MESH_DM_ROOT_TRANSPARENCY_LEDGER_READBACK_URI", ledger_path.as_uri())

    package_path.write_text(
        manifest_mod._stable_json(
            {
                "type": manifest_mod.STABLE_DM_ROOT_MANIFEST_EXTERNAL_WITNESS_IMPORT_TYPE,
                "schema_version": 1,
                "source_scope": "https_fetch",
                "source_label": "witness-a",
                "exported_at": int(time.time()),
                "descriptors": [manifest_mod._public_witness_descriptor(external_identity)],
            }
        ),
        encoding="utf-8",
    )

    main.app.dependency_overrides[require_admin] = _admin_override
    main.app.dependency_overrides[require_local_operator] = _local_operator_override
    try:
        client = TestClient(main.app, raise_server_exceptions=False)
        first_distribution = client.get("/api/wormhole/dm/root-distribution").json()
        external_receipt = manifest_mod._sign_with_witness_identity(
            identity=external_identity,
            event_type=manifest_mod.STABLE_DM_ROOT_MANIFEST_WITNESS_EVENT_TYPE,
            payload=manifest_mod._witness_payload(first_distribution["manifest"]),
        )
        package_path.write_text(
            manifest_mod._stable_json(
                {
                    "type": manifest_mod.STABLE_DM_ROOT_MANIFEST_EXTERNAL_WITNESS_IMPORT_TYPE,
                    "schema_version": 1,
                    "source_scope": "https_fetch",
                    "source_label": "witness-a",
                    "exported_at": int(time.time()),
                    "descriptors": [manifest_mod._public_witness_descriptor(external_identity)],
                    "manifest_fingerprint": first_distribution["manifest_fingerprint"],
                    "witnesses": [external_receipt],
                }
            ),
            encoding="utf-8",
        )

        distribution_resp = client.get("/api/wormhole/dm/root-distribution")
        transparency_resp = client.get("/api/wormhole/dm/root-transparency")
        health_resp = client.get("/api/wormhole/dm/root-health")
        runbook_resp = client.get("/api/wormhole/dm/root-health/runbook")
        alerts_resp = client.get("/api/wormhole/dm/root-health/alerts")
        distribution = distribution_resp.json()
        transparency = transparency_resp.json()
        health = health_resp.json()
        runbook = runbook_resp.json()
        alerts = alerts_resp.json()

        assert distribution_resp.status_code == 200
        assert distribution["ok"] is True
        assert distribution["external_witness_operator_state"] == "current"
        assert distribution["dm_root_operator_summary"]["state"] == "current_external"
        assert distribution["dm_root_operator_summary"]["external_assurance_current"] is True
        assert distribution["dm_root_operator_summary"]["health_state"] == "ok"
        assert distribution["dm_root_operator_summary"]["recommended_actions"] == []
        assert distribution["dm_root_operator_summary"]["independent_quorum_met"] is True

        assert transparency_resp.status_code == 200
        assert transparency["ok"] is True
        assert transparency["ledger_operator_state"] == "current"
        assert transparency["dm_root_operator_summary"]["state"] == "current_external"
        assert transparency["dm_root_operator_summary"]["external_assurance_current"] is True
        assert transparency["dm_root_operator_summary"]["health_state"] == "ok"

        assert health_resp.status_code == 200
        assert health["ok"] is True
        assert health["state"] == "current_external"
        assert health["health_state"] == "ok"
        assert health["strong_trust_blocked"] is False
        assert health["recommended_actions"] == []
        assert health["next_action"] == ""
        assert health["alert_count"] == 0
        assert health["monitoring"]["state"] == "ok"
        assert health["monitoring"]["page_required"] is False
        assert health["runbook"]["urgency"] == "none"
        assert health["witness"]["state"] == "current"
        assert health["transparency"]["state"] == "current"

        assert runbook_resp.status_code == 200
        assert runbook["ok"] is True
        assert runbook["urgency"] == "none"
        assert runbook["actions"] == []
        assert runbook["next_action_detail"] == {}

        assert alerts_resp.status_code == 200
        assert alerts["ok"] is True
        assert alerts["state"] == "ok"
        assert alerts["page_required"] is False
        assert alerts["ticket_required"] is False
        assert alerts["alert_count"] == 0
    finally:
        main.app.dependency_overrides.pop(require_admin, None)
        main.app.dependency_overrides.pop(require_local_operator, None)


def test_http_root_health_reports_error_and_action_when_external_witness_source_becomes_unreadable(
    tmp_path, monkeypatch
):
    from fastapi.testclient import TestClient
    from auth import require_admin, require_local_operator
    import main

    manifest_mod, _transparency_mod = _fresh_root_http_env(tmp_path, monkeypatch)
    external_identity = manifest_mod._witness_identity_record(index=9)
    external_identity["management_scope"] = "external"
    external_identity["independence_group"] = "independent_a"
    package_path = tmp_path / "external_root_witness_source.json"
    ledger_path = tmp_path / "external_root_transparency_ledger.json"

    monkeypatch.setenv("MESH_DM_ROOT_EXTERNAL_WITNESS_IMPORT_URI", package_path.as_uri())
    monkeypatch.setenv("MESH_DM_ROOT_TRANSPARENCY_LEDGER_EXPORT_PATH", str(ledger_path))
    monkeypatch.setenv("MESH_DM_ROOT_TRANSPARENCY_LEDGER_READBACK_URI", ledger_path.as_uri())

    package_path.write_text(
        manifest_mod._stable_json(
            {
                "type": manifest_mod.STABLE_DM_ROOT_MANIFEST_EXTERNAL_WITNESS_IMPORT_TYPE,
                "schema_version": 1,
                "source_scope": "https_fetch",
                "source_label": "witness-a",
                "exported_at": int(time.time()),
                "descriptors": [manifest_mod._public_witness_descriptor(external_identity)],
            }
        ),
        encoding="utf-8",
    )

    main.app.dependency_overrides[require_admin] = _admin_override
    main.app.dependency_overrides[require_local_operator] = _local_operator_override
    try:
        client = TestClient(main.app, raise_server_exceptions=False)
        first_distribution = client.get("/api/wormhole/dm/root-distribution").json()
        external_receipt = manifest_mod._sign_with_witness_identity(
            identity=external_identity,
            event_type=manifest_mod.STABLE_DM_ROOT_MANIFEST_WITNESS_EVENT_TYPE,
            payload=manifest_mod._witness_payload(first_distribution["manifest"]),
        )
        package_path.write_text(
            manifest_mod._stable_json(
                {
                    "type": manifest_mod.STABLE_DM_ROOT_MANIFEST_EXTERNAL_WITNESS_IMPORT_TYPE,
                    "schema_version": 1,
                    "source_scope": "https_fetch",
                    "source_label": "witness-a",
                    "exported_at": int(time.time()),
                    "descriptors": [manifest_mod._public_witness_descriptor(external_identity)],
                    "manifest_fingerprint": first_distribution["manifest_fingerprint"],
                    "witnesses": [external_receipt],
                }
            ),
            encoding="utf-8",
        )
        assert client.get("/api/wormhole/dm/root-health").json()["state"] == "current_external"

        package_path.unlink()

        health_resp = client.get("/api/wormhole/dm/root-health")
        health = health_resp.json()

        assert health_resp.status_code == 200
        assert health["ok"] is True
        assert health["state"] == "stale_external"
        assert health["health_state"] == "error"
        assert health["strong_trust_blocked"] is True
        assert health["witness_state"] == "error"
        assert health["transparency_state"] == "current"
        assert health["alert_count"] == 1
        assert health["blocking_alert_count"] == 1
        assert health["recommended_actions"] == ["check_external_witness_source"]
        assert health["next_action"] == "check_external_witness_source"
        assert health["runbook_actions"] == [
            {
                "action": "check_external_witness_source",
                "target": "external_witness",
                "severity": "error",
                "blocking": True,
                "reason": "external root witness import source unreadable",
            }
        ]
        assert health["runbook"]["urgency"] == "page"
        assert health["runbook"]["next_action_detail"]["title"] == "Check external witness source"
        alerts = client.get("/api/wormhole/dm/root-health/alerts").json()
        assert alerts["state"] == "critical"
        assert alerts["page_required"] is True
        assert alerts["ticket_required"] is True
        assert alerts["primary_alert"]["code"] == "external_witness_source_error"
        assert alerts["next_action"] == "check_external_witness_source"
        runbook = client.get("/api/wormhole/dm/root-health/runbook").json()
        assert runbook["urgency"] == "page"
        assert runbook["next_action"] == "check_external_witness_source"
        assert runbook["next_action_detail"]["blocking"] is True
        assert runbook["actions"][0]["owner"] == "dm_root_ops"
    finally:
        main.app.dependency_overrides.pop(require_admin, None)
        main.app.dependency_overrides.pop(require_local_operator, None)


def test_http_root_health_warns_before_external_witness_source_reaches_fail_closed_age(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from auth import require_local_operator
    import main

    manifest_mod, _transparency_mod = _fresh_root_http_env(tmp_path, monkeypatch)
    external_identity = manifest_mod._witness_identity_record(index=9)
    external_identity["management_scope"] = "external"
    external_identity["independence_group"] = "independent_a"
    package_path = tmp_path / "aging_external_root_witness_source.json"
    ledger_path = tmp_path / "current_external_root_transparency_ledger.json"

    monkeypatch.setenv("MESH_DM_ROOT_EXTERNAL_WITNESS_IMPORT_URI", package_path.as_uri())
    monkeypatch.setenv("MESH_DM_ROOT_EXTERNAL_WITNESS_MAX_AGE_S", "60")
    monkeypatch.setenv("MESH_DM_ROOT_EXTERNAL_WITNESS_WARN_AGE_S", "30")
    monkeypatch.setenv("MESH_DM_ROOT_TRANSPARENCY_LEDGER_EXPORT_PATH", str(ledger_path))
    monkeypatch.setenv("MESH_DM_ROOT_TRANSPARENCY_LEDGER_READBACK_URI", ledger_path.as_uri())
    monkeypatch.setenv("MESH_DM_ROOT_TRANSPARENCY_LEDGER_MAX_AGE_S", "60")
    monkeypatch.setenv("MESH_DM_ROOT_TRANSPARENCY_LEDGER_WARN_AGE_S", "30")

    package_path.write_text(
        manifest_mod._stable_json(
            {
                "type": manifest_mod.STABLE_DM_ROOT_MANIFEST_EXTERNAL_WITNESS_IMPORT_TYPE,
                "schema_version": 1,
                "source_scope": "https_fetch",
                "source_label": "witness-a",
                "exported_at": int(time.time()) - 40,
                "descriptors": [manifest_mod._public_witness_descriptor(external_identity)],
            }
        ),
        encoding="utf-8",
    )

    main.app.dependency_overrides[require_local_operator] = _local_operator_override
    try:
        client = TestClient(main.app, raise_server_exceptions=False)
        first_distribution = client.get("/api/wormhole/dm/root-distribution").json()
        external_receipt = manifest_mod._sign_with_witness_identity(
            identity=external_identity,
            event_type=manifest_mod.STABLE_DM_ROOT_MANIFEST_WITNESS_EVENT_TYPE,
            payload=manifest_mod._witness_payload(first_distribution["manifest"]),
        )
        package_path.write_text(
            manifest_mod._stable_json(
                {
                    "type": manifest_mod.STABLE_DM_ROOT_MANIFEST_EXTERNAL_WITNESS_IMPORT_TYPE,
                    "schema_version": 1,
                    "source_scope": "https_fetch",
                    "source_label": "witness-a",
                    "exported_at": int(time.time()) - 40,
                    "descriptors": [manifest_mod._public_witness_descriptor(external_identity)],
                    "manifest_fingerprint": first_distribution["manifest_fingerprint"],
                    "witnesses": [external_receipt],
                }
            ),
            encoding="utf-8",
        )

        health_resp = client.get("/api/wormhole/dm/root-health")
        health = health_resp.json()

        assert health_resp.status_code == 200
        assert health["ok"] is True
        assert health["state"] == "current_external"
        assert health["health_state"] == "warning"
        assert health["strong_trust_blocked"] is False
        assert health["witness_health_state"] == "warning"
        assert health["transparency_health_state"] == "ok"
        assert health["warning_due"] is True
        assert health["witness_warning_due"] is True
        assert health["transparency_warning_due"] is False
        assert health["recommended_actions"] == ["refresh_external_witness_source"]
        assert health["next_action"] == "refresh_external_witness_source"
        assert health["alerts"][0]["code"] == "external_witness_age_warning"
        assert health["alerts"][0]["severity"] == "warning"
        assert health["monitoring"]["state"] == "warning"
        assert health["monitoring"]["page_required"] is False
        assert health["runbook"]["urgency"] == "watch"
        assert health["runbook"]["next_action_detail"]["title"] == "Refresh external witness source"
        assert health["witness"]["age_s"] >= 40
        assert health["witness"]["warning_window_s"] == 30
        assert health["witness"]["freshness_window_s"] == 60

        alerts = client.get("/api/wormhole/dm/root-health/alerts").json()
        assert alerts["state"] == "warning"
        assert alerts["page_required"] is False
        assert alerts["ticket_required"] is True
        assert alerts["primary_alert"]["code"] == "external_witness_age_warning"
        assert alerts["next_action"] == "refresh_external_witness_source"
        runbook = client.get("/api/wormhole/dm/root-health/runbook").json()
        assert runbook["urgency"] == "watch"
        assert runbook["next_action"] == "refresh_external_witness_source"
        assert runbook["actions"][0]["title"] == "Refresh external witness source"
    finally:
        main.app.dependency_overrides.pop(require_local_operator, None)
