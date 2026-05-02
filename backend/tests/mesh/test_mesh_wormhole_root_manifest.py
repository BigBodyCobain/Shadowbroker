import time

from services.mesh import mesh_secure_storage


def _fresh_manifest_env(tmp_path, monkeypatch):
    from services.mesh import (
        mesh_wormhole_identity,
        mesh_wormhole_persona,
        mesh_wormhole_root_manifest,
        mesh_wormhole_root_transparency,
    )
    from services.config import get_settings

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
    return mesh_wormhole_persona, mesh_wormhole_identity, mesh_wormhole_root_manifest


def test_publish_current_root_manifest_is_root_signed_and_witnessed(tmp_path, monkeypatch):
    persona_mod, _identity_mod, manifest_mod = _fresh_manifest_env(tmp_path, monkeypatch)

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    published = manifest_mod.publish_current_root_manifest(expires_in_s=3600, policy_version=3)
    root_identity = persona_mod.get_root_identity()

    assert published["ok"] is True
    assert published["manifest"]["node_id"] == root_identity["node_id"]
    assert published["manifest"]["public_key"] == root_identity["public_key"]

    manifest_verified = manifest_mod.verify_root_manifest(published["manifest"])
    witness_verified = manifest_mod.verify_root_manifest_witness_set(
        published["manifest"],
        published["witnesses"],
    )
    assert manifest_verified["ok"] is True
    assert witness_verified["ok"] is True
    assert witness_verified["witness_independent_quorum_met"] is False
    assert witness_verified["witness_finality_met"] is False
    assert published["witness_identity"]["node_id"] != root_identity["node_id"]
    assert published["witness_identity"]["public_key"] != root_identity["public_key"]
    assert len(published["witnesses"]) == 3
    assert published["witness_threshold"] == 2
    assert published["witness_count"] == 3

    payload = dict(published["manifest"]["payload"])
    assert payload["root_node_id"]
    assert payload["root_public_key"]
    assert payload["root_public_key_algo"] == "Ed25519"
    assert payload["root_fingerprint"]
    assert payload["generation"] == 1
    assert payload["issued_at"] > 0
    assert payload["expires_at"] > payload["issued_at"]
    assert payload["witness_policy"]["threshold"] == 2
    assert len(payload["witness_policy"]["witnesses"]) == 3
    assert payload["previous_root_fingerprint"] == ""
    assert payload["previous_root_cross_signature"] == ""
    assert payload["policy_version"] == 3
    assert manifest_verified["rotation_proven"] is True


def test_verify_root_manifest_rejects_payload_tamper(tmp_path, monkeypatch):
    _persona_mod, _identity_mod, manifest_mod = _fresh_manifest_env(tmp_path, monkeypatch)

    published = manifest_mod.publish_current_root_manifest(expires_in_s=3600)
    tampered = {
        **published["manifest"],
        "payload": {**published["manifest"]["payload"], "generation": published["manifest"]["payload"]["generation"] + 1},
    }

    verified = manifest_mod.verify_root_manifest(tampered)

    assert verified["ok"] is False
    assert "invalid" in verified["detail"] or "mismatch" in verified["detail"]


def test_verify_root_manifest_witness_rejects_manifest_hash_tamper(tmp_path, monkeypatch):
    _persona_mod, _identity_mod, manifest_mod = _fresh_manifest_env(tmp_path, monkeypatch)

    first = manifest_mod.publish_current_root_manifest(expires_in_s=3600, policy_version=1)
    second = manifest_mod.publish_current_root_manifest(expires_in_s=3600, policy_version=2)

    verified = manifest_mod.verify_root_manifest_witness(second["manifest"], first["witnesses"][0])

    assert verified["ok"] is False
    assert "payload mismatch" in verified["detail"]


def test_witness_policy_change_is_signed_as_explicit_continuity_event(tmp_path, monkeypatch):
    _persona_mod, _identity_mod, manifest_mod = _fresh_manifest_env(tmp_path, monkeypatch)

    first = manifest_mod.publish_current_root_manifest(expires_in_s=3600, policy_version=1)
    second = manifest_mod.publish_current_root_manifest(expires_in_s=3600, policy_version=2)

    first_policy_fingerprint = manifest_mod.witness_policy_fingerprint(first["manifest"]["payload"]["witness_policy"])
    second_payload = dict(second["manifest"]["payload"] or {})
    verified = manifest_mod.verify_root_manifest(second["manifest"])

    assert second_payload["generation"] == 1
    assert second_payload["previous_witness_policy_fingerprint"] == first_policy_fingerprint
    assert second_payload["previous_witness_policy_sequence"] > 0
    assert second_payload["previous_witness_policy_signature"]
    assert verified["ok"] is True
    assert verified["policy_change_proven"] is True


def test_root_rotation_republishes_with_incremented_generation_and_previous_fingerprint(tmp_path, monkeypatch):
    persona_mod, _identity_mod, manifest_mod = _fresh_manifest_env(tmp_path, monkeypatch)

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    first = manifest_mod.publish_current_root_manifest(expires_in_s=3600)
    first_root_fingerprint = first["root_fingerprint"]

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    second = manifest_mod.publish_current_root_manifest(expires_in_s=3600)

    second_payload = dict(second["manifest"]["payload"])
    assert second["ok"] is True
    assert second_payload["generation"] == dict(first["manifest"]["payload"])["generation"] + 1
    assert second_payload["previous_root_fingerprint"] == first_root_fingerprint
    assert second_payload["root_fingerprint"] != first_root_fingerprint
    assert second_payload["previous_root_cross_signature"]
    verified = manifest_mod.verify_root_manifest(second["manifest"])
    assert verified["ok"] is True
    assert verified["rotation_proven"] is True
    assert manifest_mod.verify_root_manifest_witness_set(second["manifest"], second["witnesses"])["ok"] is True


def test_verify_root_manifest_marks_rotation_without_previous_root_proof_as_unproven(tmp_path, monkeypatch):
    persona_mod, _identity_mod, manifest_mod = _fresh_manifest_env(tmp_path, monkeypatch)

    persona_mod.bootstrap_wormhole_persona_state(force=True)
    manifest_mod.publish_current_root_manifest(expires_in_s=3600)
    persona_mod.bootstrap_wormhole_persona_state(force=True)
    rotated = manifest_mod.publish_current_root_manifest(expires_in_s=3600)

    stripped_payload = {
        **dict(rotated["manifest"]["payload"]),
        "previous_root_cross_sequence": 0,
        "previous_root_cross_signature": "",
    }
    resigned = persona_mod.sign_root_wormhole_event(
        event_type=manifest_mod.STABLE_DM_ROOT_MANIFEST_EVENT_TYPE,
        payload=stripped_payload,
    )
    stripped_manifest = {
        **dict(rotated["manifest"]),
        "node_id": str(resigned.get("node_id", "") or ""),
        "public_key": str(resigned.get("public_key", "") or ""),
        "public_key_algo": str(resigned.get("public_key_algo", "Ed25519") or "Ed25519"),
        "protocol_version": str(resigned.get("protocol_version", "") or ""),
        "sequence": int(resigned.get("sequence", 0) or 0),
        "payload": dict(resigned.get("payload") or {}),
        "signature": str(resigned.get("signature", "") or ""),
    }

    verified = manifest_mod.verify_root_manifest(stripped_manifest)

    assert verified["ok"] is True
    assert verified["generation"] == 2
    assert verified["rotation_proven"] is False


def test_verify_root_manifest_marks_witness_policy_change_without_proof_as_unproven(tmp_path, monkeypatch):
    persona_mod, _identity_mod, manifest_mod = _fresh_manifest_env(tmp_path, monkeypatch)

    manifest_mod.publish_current_root_manifest(expires_in_s=3600, policy_version=1)
    changed = manifest_mod.publish_current_root_manifest(expires_in_s=3600, policy_version=2)

    stripped_payload = {
        **dict(changed["manifest"]["payload"] or {}),
        "previous_witness_policy_sequence": 0,
        "previous_witness_policy_signature": "",
    }
    resigned = persona_mod.sign_root_wormhole_event(
        event_type=manifest_mod.STABLE_DM_ROOT_MANIFEST_EVENT_TYPE,
        payload=stripped_payload,
    )
    stripped_manifest = {
        **dict(changed["manifest"]),
        "node_id": str(resigned.get("node_id", "") or ""),
        "public_key": str(resigned.get("public_key", "") or ""),
        "public_key_algo": str(resigned.get("public_key_algo", "Ed25519") or "Ed25519"),
        "protocol_version": str(resigned.get("protocol_version", "") or ""),
        "sequence": int(resigned.get("sequence", 0) or 0),
        "payload": dict(resigned.get("payload") or {}),
        "signature": str(resigned.get("signature", "") or ""),
    }

    verified = manifest_mod.verify_root_manifest(stripped_manifest)

    assert verified["ok"] is True
    assert verified["generation"] == 1
    assert verified["policy_change_proven"] is False


def test_verify_root_manifest_witness_set_requires_threshold(tmp_path, monkeypatch):
    _persona_mod, _identity_mod, manifest_mod = _fresh_manifest_env(tmp_path, monkeypatch)

    published = manifest_mod.publish_current_root_manifest(expires_in_s=3600, policy_version=4)

    single_witness = manifest_mod.verify_root_manifest_witness_set(
        published["manifest"],
        [published["witnesses"][0]],
    )
    quorum_witnesses = manifest_mod.verify_root_manifest_witness_set(
        published["manifest"],
        published["witnesses"][:2],
    )

    assert single_witness["ok"] is False
    assert single_witness["detail"] == "stable root manifest witness threshold not met"
    assert single_witness["witness_threshold"] == 2
    assert single_witness["witness_count"] == 1
    assert quorum_witnesses["ok"] is True
    assert quorum_witnesses["witness_threshold"] == 2
    assert quorum_witnesses["witness_count"] == 2
    assert quorum_witnesses["witness_independent_quorum_met"] is False
    assert quorum_witnesses["witness_finality_met"] is False


def test_root_witness_finality_short_circuits_single_witness_threshold():
    from services.mesh import mesh_wormhole_root_manifest as manifest_mod

    assert (
        manifest_mod.root_witness_finality_met(
            witness_threshold=1,
            witness_quorum_met=True,
            witness_independent_quorum_met=False,
        )
        is True
    )


def test_external_witness_descriptors_extend_manifest_policy(tmp_path, monkeypatch):
    _persona_mod, _identity_mod, manifest_mod = _fresh_manifest_env(tmp_path, monkeypatch)

    external_identity = manifest_mod._witness_identity_record(index=9)
    external_identity["management_scope"] = "external"
    external_identity["independence_group"] = "independent_a"
    configured = manifest_mod.configure_external_root_witness_descriptors(
        [manifest_mod._public_witness_descriptor(external_identity)]
    )

    published = manifest_mod.publish_current_root_manifest(expires_in_s=3600, policy_version=5)
    witness_policy = dict(published["manifest"]["payload"]["witness_policy"] or {})
    external_descriptors = [
        item for item in list(witness_policy.get("witnesses") or []) if item.get("management_scope") == "external"
    ]

    assert configured["ok"] is True
    assert configured["external_witness_count"] == 1
    assert published["ok"] is True
    assert len(list(witness_policy.get("witnesses") or [])) == 4
    assert len(external_descriptors) == 1
    assert external_descriptors[0]["independence_group"] == "independent_a"


def test_staged_external_witness_receipt_upgrades_current_manifest_to_independent_quorum(tmp_path, monkeypatch):
    _persona_mod, _identity_mod, manifest_mod = _fresh_manifest_env(tmp_path, monkeypatch)

    external_identity = manifest_mod._witness_identity_record(index=9)
    external_identity["management_scope"] = "external"
    external_identity["independence_group"] = "independent_a"
    manifest_mod.configure_external_root_witness_descriptors(
        [manifest_mod._public_witness_descriptor(external_identity)]
    )
    published = manifest_mod.publish_current_root_manifest(expires_in_s=3600, policy_version=6)

    external_receipt = manifest_mod._sign_with_witness_identity(
        identity=external_identity,
        event_type=manifest_mod.STABLE_DM_ROOT_MANIFEST_WITNESS_EVENT_TYPE,
        payload=manifest_mod._witness_payload(published["manifest"]),
    )
    staged = manifest_mod.stage_external_root_manifest_witnesses(
        [external_receipt],
        manifest=published["manifest"],
    )
    current = manifest_mod.get_current_root_manifest()
    verified = manifest_mod.verify_root_manifest_witness_set(current["manifest"], current["witnesses"])

    assert staged["ok"] is True
    assert staged["external_witness_count"] == 1
    assert staged["witness_independent_quorum_met"] is True
    assert staged["witness_finality_met"] is True
    assert current["ok"] is True
    assert len(current["witnesses"]) == 4
    assert verified["ok"] is True
    assert verified["witness_domain_count"] == 2
    assert verified["witness_independent_quorum_met"] is True
    assert verified["witness_finality_met"] is True


def test_import_external_root_witness_material_updates_source_and_stages_receipts(tmp_path, monkeypatch):
    _persona_mod, _identity_mod, manifest_mod = _fresh_manifest_env(tmp_path, monkeypatch)

    external_identity = manifest_mod._witness_identity_record(index=9)
    external_identity["management_scope"] = "external"
    external_identity["independence_group"] = "independent_a"
    imported = manifest_mod.import_external_root_witness_material(
        {
            "type": manifest_mod.STABLE_DM_ROOT_MANIFEST_EXTERNAL_WITNESS_IMPORT_TYPE,
            "schema_version": 1,
            "source_scope": "https_fetch",
            "source_label": "witness-a",
            "descriptors": [manifest_mod._public_witness_descriptor(external_identity)],
        }
    )
    current = manifest_mod.get_current_root_manifest()
    external_receipt = manifest_mod._sign_with_witness_identity(
        identity=external_identity,
        event_type=manifest_mod.STABLE_DM_ROOT_MANIFEST_WITNESS_EVENT_TYPE,
        payload=manifest_mod._witness_payload(current["manifest"]),
    )
    restaged = manifest_mod.import_external_root_witness_material(
        {
            "type": manifest_mod.STABLE_DM_ROOT_MANIFEST_EXTERNAL_WITNESS_IMPORT_TYPE,
            "schema_version": 1,
            "source_scope": "https_fetch",
            "source_label": "witness-a",
            "manifest_fingerprint": current["manifest_fingerprint"],
            "witnesses": [external_receipt],
        }
    )
    refreshed = manifest_mod.get_current_root_manifest()
    verified = manifest_mod.verify_root_manifest_witness_set(refreshed["manifest"], refreshed["witnesses"])

    assert imported["ok"] is True
    assert imported["external_witness_source_scope"] == "https_fetch"
    assert imported["external_witness_source_label"] == "witness-a"
    assert imported["external_witness_count"] == 1
    assert restaged["ok"] is True
    assert restaged["staged_external_witness_count"] == 1
    assert refreshed["external_witness_source_scope"] == "https_fetch"
    assert refreshed["external_witness_source_label"] == "witness-a"
    assert verified["ok"] is True
    assert verified["witness_independent_quorum_met"] is True
    assert verified["witness_finality_met"] is True


def test_import_external_root_witness_material_from_file_reads_package(tmp_path, monkeypatch):
    _persona_mod, _identity_mod, manifest_mod = _fresh_manifest_env(tmp_path, monkeypatch)

    external_identity = manifest_mod._witness_identity_record(index=9)
    external_identity["management_scope"] = "external"
    external_identity["independence_group"] = "independent_a"
    package_path = tmp_path / "external_witness_import.json"
    package_path.write_text(
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

    imported = manifest_mod.import_external_root_witness_material_from_file(str(package_path))
    current = manifest_mod.get_current_root_manifest()

    assert imported["ok"] is True
    assert imported["source_path"] == str(package_path)
    assert imported["external_witness_source_scope"] == "file_export"
    assert imported["external_witness_source_label"] == "witness-a"
    assert len(current["external_witness_descriptors"]) == 1


def test_get_current_root_manifest_auto_refreshes_configured_external_witness_file(tmp_path, monkeypatch):
    _persona_mod, _identity_mod, manifest_mod = _fresh_manifest_env(tmp_path, monkeypatch)

    external_identity = manifest_mod._witness_identity_record(index=9)
    external_identity["management_scope"] = "external"
    external_identity["independence_group"] = "independent_a"
    package_path = tmp_path / "external_witness_auto.json"
    monkeypatch.setenv("MESH_DM_ROOT_EXTERNAL_WITNESS_IMPORT_PATH", str(package_path))
    from services.config import get_settings

    get_settings.cache_clear()
    package_path.write_text(
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

    first = manifest_mod.get_current_root_manifest()
    external_receipt = manifest_mod._sign_with_witness_identity(
        identity=external_identity,
        event_type=manifest_mod.STABLE_DM_ROOT_MANIFEST_WITNESS_EVENT_TYPE,
        payload=manifest_mod._witness_payload(first["manifest"]),
    )
    package_path.write_text(
        manifest_mod._stable_json(
            {
                "type": manifest_mod.STABLE_DM_ROOT_MANIFEST_EXTERNAL_WITNESS_IMPORT_TYPE,
                "schema_version": 1,
                "source_scope": "file_export",
                "source_label": "witness-a",
                "exported_at": int(time.time()),
                "descriptors": [manifest_mod._public_witness_descriptor(external_identity)],
                "manifest_fingerprint": first["manifest_fingerprint"],
                "witnesses": [external_receipt],
            }
        ),
        encoding="utf-8",
    )

    refreshed = manifest_mod.get_current_root_manifest()
    verified = manifest_mod.verify_root_manifest_witness_set(refreshed["manifest"], refreshed["witnesses"])

    assert first["ok"] is True
    assert len(first["witness_policy"]["witnesses"]) == 4
    assert first["external_witness_refresh_ok"] is True
    assert "waiting for current-manifest receipts" in first["external_witness_refresh_detail"]
    assert first["external_witness_operator_state"] == "descriptors_only"
    assert first["external_witness_source_configured"] is True
    assert first["external_witness_reacquire_required"] is True
    assert refreshed["ok"] is True
    assert refreshed["external_witness_refresh_ok"] is True
    assert refreshed["external_witness_receipt_count"] == 1
    assert refreshed["external_witness_receipts_current"] is True
    assert refreshed["external_witness_operator_state"] == "current"
    assert refreshed["external_witness_manifest_matches_current"] is True
    assert refreshed["external_witness_reacquire_required"] is False
    assert len(refreshed["witnesses"]) == 4
    assert verified["ok"] is True
    assert verified["witness_independent_quorum_met"] is True


def test_get_current_root_manifest_auto_refreshes_configured_external_witness_uri(tmp_path, monkeypatch):
    _persona_mod, _identity_mod, manifest_mod = _fresh_manifest_env(tmp_path, monkeypatch)

    external_identity = manifest_mod._witness_identity_record(index=9)
    external_identity["management_scope"] = "external"
    external_identity["independence_group"] = "independent_a"
    package_path = tmp_path / "external_witness_auto_uri.json"
    monkeypatch.setenv("MESH_DM_ROOT_EXTERNAL_WITNESS_IMPORT_URI", package_path.as_uri())
    from services.config import get_settings

    get_settings.cache_clear()
    package_path.write_text(
        manifest_mod._stable_json(
            {
                "type": manifest_mod.STABLE_DM_ROOT_MANIFEST_EXTERNAL_WITNESS_IMPORT_TYPE,
                "schema_version": 1,
                "source_scope": "https_fetch",
                "source_label": "witness-uri",
                "exported_at": int(time.time()),
                "descriptors": [manifest_mod._public_witness_descriptor(external_identity)],
            }
        ),
        encoding="utf-8",
    )

    first = manifest_mod.get_current_root_manifest()
    external_receipt = manifest_mod._sign_with_witness_identity(
        identity=external_identity,
        event_type=manifest_mod.STABLE_DM_ROOT_MANIFEST_WITNESS_EVENT_TYPE,
        payload=manifest_mod._witness_payload(first["manifest"]),
    )
    package_path.write_text(
        manifest_mod._stable_json(
            {
                "type": manifest_mod.STABLE_DM_ROOT_MANIFEST_EXTERNAL_WITNESS_IMPORT_TYPE,
                "schema_version": 1,
                "source_scope": "https_fetch",
                "source_label": "witness-uri",
                "exported_at": int(time.time()),
                "descriptors": [manifest_mod._public_witness_descriptor(external_identity)],
                "manifest_fingerprint": first["manifest_fingerprint"],
                "witnesses": [external_receipt],
            }
        ),
        encoding="utf-8",
    )

    refreshed = manifest_mod.get_current_root_manifest()

    assert first["ok"] is True
    assert first["external_witness_refresh_ok"] is True
    assert first["external_witness_refresh_source_ref"] == package_path.as_uri()
    assert first["external_witness_operator_state"] == "descriptors_only"
    assert refreshed["ok"] is True
    assert refreshed["external_witness_refresh_ok"] is True
    assert refreshed["external_witness_refresh_source_ref"] == package_path.as_uri()
    assert refreshed["external_witness_receipt_count"] == 1
    assert refreshed["external_witness_receipts_current"] is True
    assert refreshed["external_witness_operator_state"] == "current"


def test_get_current_root_manifest_reports_stale_for_old_external_witness_package(tmp_path, monkeypatch):
    _persona_mod, _identity_mod, manifest_mod = _fresh_manifest_env(tmp_path, monkeypatch)
    from services.config import get_settings

    external_identity = manifest_mod._witness_identity_record(index=9)
    external_identity["management_scope"] = "external"
    external_identity["independence_group"] = "independent_a"
    package_path = tmp_path / "external_witness_stale.json"
    monkeypatch.setenv("MESH_DM_ROOT_EXTERNAL_WITNESS_IMPORT_URI", package_path.as_uri())
    monkeypatch.setenv("MESH_DM_ROOT_EXTERNAL_WITNESS_MAX_AGE_S", "60")
    get_settings.cache_clear()

    package_path.write_text(
        manifest_mod._stable_json(
            {
                "type": manifest_mod.STABLE_DM_ROOT_MANIFEST_EXTERNAL_WITNESS_IMPORT_TYPE,
                "schema_version": 1,
                "source_scope": "https_fetch",
                "source_label": "witness-stale",
                "exported_at": int(time.time()),
                "descriptors": [manifest_mod._public_witness_descriptor(external_identity)],
            }
        ),
        encoding="utf-8",
    )

    first = manifest_mod.get_current_root_manifest()
    external_receipt = manifest_mod._sign_with_witness_identity(
        identity=external_identity,
        event_type=manifest_mod.STABLE_DM_ROOT_MANIFEST_WITNESS_EVENT_TYPE,
        payload=manifest_mod._witness_payload(first["manifest"]),
    )
    package_path.write_text(
        manifest_mod._stable_json(
            {
                "type": manifest_mod.STABLE_DM_ROOT_MANIFEST_EXTERNAL_WITNESS_IMPORT_TYPE,
                "schema_version": 1,
                "source_scope": "https_fetch",
                "source_label": "witness-stale",
                "exported_at": int(time.time()) - 120,
                "descriptors": [manifest_mod._public_witness_descriptor(external_identity)],
                "manifest_fingerprint": first["manifest_fingerprint"],
                "witnesses": [external_receipt],
            }
        ),
        encoding="utf-8",
    )

    stale = manifest_mod.get_current_root_manifest()

    assert stale["ok"] is True
    assert stale["external_witness_refresh_ok"] is False
    assert stale["external_witness_operator_state"] == "stale"
    assert stale["external_witness_reacquire_required"] is True
    assert stale["external_witness_source_exported_at"] > 0
    assert stale["external_witness_source_age_s"] >= 120
    assert stale["external_witness_freshness_window_s"] == 60
    assert "source stale" in str(stale["external_witness_refresh_detail"] or "")
