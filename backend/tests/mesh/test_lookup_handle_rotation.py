from __future__ import annotations

import asyncio

import main


def _request(path: str):
    from starlette.requests import Request

    return Request(
        {
            "type": "http",
            "headers": [],
            "client": ("test", 12345),
            "method": "GET",
            "path": path.split("?", 1)[0],
            "query_string": path.split("?", 1)[1].encode("utf-8") if "?" in path else b"",
        }
    )


def _fresh_rotation_state(tmp_path, monkeypatch):
    from services.mesh import (
        mesh_dm_relay,
        mesh_secure_storage,
        mesh_wormhole_contacts,
        mesh_wormhole_identity,
        mesh_wormhole_persona,
        mesh_wormhole_prekey,
        mesh_wormhole_root_manifest,
        mesh_wormhole_root_transparency,
    )
    from services.config import get_settings

    monkeypatch.setattr(mesh_dm_relay, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_dm_relay, "RELAY_FILE", tmp_path / "dm_relay.json")
    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    monkeypatch.setattr(mesh_wormhole_persona, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_persona, "PERSONA_FILE", tmp_path / "wormhole_persona.json")
    monkeypatch.setattr(mesh_wormhole_persona, "LEGACY_DM_IDENTITY_FILE", tmp_path / "wormhole_identity.json")
    monkeypatch.setattr(mesh_wormhole_root_manifest, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_root_transparency, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_contacts, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_contacts, "CONTACTS_FILE", tmp_path / "wormhole_dm_contacts.json")
    monkeypatch.setattr(mesh_secure_storage, "_MASTER_KEY_CACHE", None)
    monkeypatch.setattr(mesh_secure_storage, "_DOMAIN_KEY_CACHE", {})
    get_settings.cache_clear()

    relay = mesh_dm_relay.DMRelay()
    monkeypatch.setattr(mesh_dm_relay, "dm_relay", relay)
    mesh_wormhole_identity.bootstrap_wormhole_identity(force=True)
    return relay, mesh_wormhole_identity, mesh_wormhole_contacts, mesh_wormhole_prekey, mesh_dm_relay


def _patch_time(monkeypatch, now, *modules):
    current = {"value": now}
    for module in modules:
        monkeypatch.setattr(module.time, "time", lambda current=current: current["value"])
    return current


def _set_handle_record(identity_mod, handle: str, **updates):
    records = []
    for record in identity_mod.get_prekey_lookup_handle_records():
        current = dict(record)
        if str(current.get("handle", "") or "").strip() == handle:
            current.update(updates)
        records.append(current)
    identity_mod._write_identity({"prekey_lookup_handles": records})


def test_zero_existing_handles_do_not_trigger_rotation_or_mint(tmp_path, monkeypatch):
    _relay, identity_mod, _contacts_mod, prekey_mod, relay_mod = _fresh_rotation_state(tmp_path, monkeypatch)
    now = _patch_time(monkeypatch, 1_700_010_000, identity_mod, prekey_mod, relay_mod)
    identity_mod._write_identity({"prekey_lookup_handles": []})

    result = identity_mod.maybe_rotate_prekey_lookup_handles(now=now["value"])
    records = identity_mod.get_prekey_lookup_handle_records()
    status = identity_mod.lookup_handle_rotation_status_snapshot(now=now["value"])

    assert result == {
        "ok": True,
        "rotated": False,
        "state": "lookup_handle_rotation_ok",
        "detail": "no active lookup handles",
        "active_handle_count": 0,
    }
    assert records == []
    assert status["state"] == "lookup_handle_rotation_ok"
    assert status["detail"] == "no active lookup handles"
    assert status["active_handle_count"] == 0


def test_refresh_paths_with_zero_handles_do_not_create_first_handle(tmp_path, monkeypatch):
    _relay, identity_mod, _contacts_mod, _prekey_mod, _relay_mod = _fresh_rotation_state(tmp_path, monkeypatch)
    identity_mod._write_identity({"prekey_lookup_handles": []})

    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        main,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": False, "rns_ready": False},
    )
    monkeypatch.setattr(main, "_current_private_lane_tier", lambda *_args, **_kwargs: "private_control_only")
    monkeypatch.setattr(main, "bootstrap_wormhole_persona_state", lambda: None)
    monkeypatch.setattr(main, "get_transport_identity", lambda: {"node_id": "transport-node"})
    monkeypatch.setattr(main, "get_dm_identity", lambda: {"node_id": "dm-node"})

    refresh = main._refresh_lookup_handle_rotation_background(reason="startup_resume")
    status = asyncio.run(main.api_wormhole_status(_request("/api/wormhole/status")))
    transport_identity = asyncio.run(main.api_wormhole_identity(_request("/api/wormhole/identity")))
    dm_identity = asyncio.run(main.api_wormhole_dm_identity(_request("/api/wormhole/dm/identity")))
    records = identity_mod.get_prekey_lookup_handle_records()

    assert refresh["rotated"] is False
    assert refresh["detail"] == "no active lookup handles"
    assert status["lookup_handle_rotation"]["state"] == "lookup_handle_rotation_ok"
    assert status["lookup_handle_rotation"]["detail"] == "no active lookup handles"
    assert status["lookup_handle_rotation"]["active_handle_count"] == 0
    assert transport_identity == {"node_id": "transport-node"}
    assert dm_identity == {"node_id": "dm-node"}
    assert records == []


def test_explicit_invite_export_still_creates_lookup_handle(tmp_path, monkeypatch):
    _relay, identity_mod, _contacts_mod, _prekey_mod, _relay_mod = _fresh_rotation_state(tmp_path, monkeypatch)

    exported = identity_mod.export_wormhole_dm_invite()
    records = identity_mod.get_prekey_lookup_handle_records()

    assert exported["ok"] is True
    assert exported["invite"]["payload"]["prekey_lookup_handle"]
    assert len(records) == 1


def test_handle_nearing_ttl_threshold_triggers_automatic_rotation(tmp_path, monkeypatch):
    relay, identity_mod, _contacts_mod, prekey_mod, relay_mod = _fresh_rotation_state(tmp_path, monkeypatch)

    exported = identity_mod.export_wormhole_dm_invite()
    old_handle = str(exported["invite"]["payload"]["prekey_lookup_handle"] or "")
    record = next(
        item for item in identity_mod.get_prekey_lookup_handle_records()
        if str(item.get("handle", "") or "") == old_handle
    )
    now = _patch_time(
        monkeypatch,
        int(record.get("issued_at", 0) or 0),
        identity_mod,
        prekey_mod,
        relay_mod,
    )
    now["value"] = (
        identity_mod._effective_prekey_lookup_handle_expires_at(record)
        - identity_mod.PREKEY_LOOKUP_ROTATE_BEFORE_EXPIRES_S
        + 1
    )

    result = identity_mod.maybe_rotate_prekey_lookup_handles(now=now["value"])
    records = identity_mod.get_prekey_lookup_handle_records()
    new_handles = [str(item.get("handle", "") or "") for item in records if str(item.get("handle", "") or "") != old_handle]

    assert result["ok"] is True
    assert result["rotated"] is True
    assert len(new_handles) == 1
    assert relay.get_prekey_bundle_by_lookup(old_handle)[0] is not None
    assert relay.get_prekey_bundle_by_lookup(new_handles[0])[0] is not None


def test_handle_nearing_use_budget_threshold_triggers_automatic_rotation(tmp_path, monkeypatch):
    relay, identity_mod, _contacts_mod, prekey_mod, relay_mod = _fresh_rotation_state(tmp_path, monkeypatch)

    exported = identity_mod.export_wormhole_dm_invite()
    old_handle = str(exported["invite"]["payload"]["prekey_lookup_handle"] or "")
    record = next(
        item for item in identity_mod.get_prekey_lookup_handle_records()
        if str(item.get("handle", "") or "") == old_handle
    )
    now = _patch_time(
        monkeypatch,
        int(record.get("issued_at", 0) or 0),
        identity_mod,
        prekey_mod,
        relay_mod,
    )
    _set_handle_record(
        identity_mod,
        old_handle,
        use_count=identity_mod.PREKEY_LOOKUP_HANDLE_MAX_USES - identity_mod.PREKEY_LOOKUP_ROTATE_BEFORE_REMAINING_USES + 1,
    )

    result = identity_mod.maybe_rotate_prekey_lookup_handles(now=now["value"])
    records = identity_mod.get_prekey_lookup_handle_records()

    assert result["ok"] is True
    assert result["rotated"] is True
    assert any(str(item.get("handle", "") or "") != old_handle for item in records)
    assert relay.get_prekey_bundle_by_lookup(old_handle)[0] is not None


def test_superseded_handle_is_pruned_after_overlap_expiry(tmp_path, monkeypatch):
    relay, identity_mod, _contacts_mod, prekey_mod, relay_mod = _fresh_rotation_state(tmp_path, monkeypatch)

    exported = identity_mod.export_wormhole_dm_invite()
    old_handle = str(exported["invite"]["payload"]["prekey_lookup_handle"] or "")
    record = next(
        item for item in identity_mod.get_prekey_lookup_handle_records()
        if str(item.get("handle", "") or "") == old_handle
    )
    now = _patch_time(
        monkeypatch,
        int(record.get("issued_at", 0) or 0),
        identity_mod,
        prekey_mod,
        relay_mod,
    )
    now["value"] = (
        identity_mod._effective_prekey_lookup_handle_expires_at(record)
        - identity_mod.PREKEY_LOOKUP_ROTATE_BEFORE_EXPIRES_S
        + 1
    )
    identity_mod.maybe_rotate_prekey_lookup_handles(now=now["value"])
    new_handle = next(
        str(item.get("handle", "") or "")
        for item in identity_mod.get_prekey_lookup_handle_records()
        if str(item.get("handle", "") or "") != old_handle
    )

    now["value"] += identity_mod.PREKEY_LOOKUP_ROTATION_OVERLAP_S + 1

    active_handles = {
        str(item.get("handle", "") or "")
        for item in identity_mod.get_prekey_lookup_handle_records()
    }
    assert old_handle not in active_handles
    assert new_handle in active_handles
    assert relay.get_prekey_bundle_by_lookup(old_handle) == (None, "")
    assert relay.get_prekey_bundle_by_lookup(new_handle)[0] is not None


def test_active_handle_count_remains_bounded_after_repeated_rotations(tmp_path, monkeypatch):
    _relay, identity_mod, _contacts_mod, prekey_mod, relay_mod = _fresh_rotation_state(tmp_path, monkeypatch)

    exported = identity_mod.export_wormhole_dm_invite()
    current_handle = str(exported["invite"]["payload"]["prekey_lookup_handle"] or "")
    record = next(
        item for item in identity_mod.get_prekey_lookup_handle_records()
        if str(item.get("handle", "") or "") == current_handle
    )
    now = _patch_time(
        monkeypatch,
        int(record.get("issued_at", 0) or 0),
        identity_mod,
        prekey_mod,
        relay_mod,
    )

    for _ in range(6):
        _set_handle_record(
            identity_mod,
            current_handle,
            use_count=identity_mod.PREKEY_LOOKUP_HANDLE_MAX_USES - identity_mod.PREKEY_LOOKUP_ROTATE_BEFORE_REMAINING_USES + 1,
        )
        result = identity_mod.maybe_rotate_prekey_lookup_handles(now=now["value"])
        assert result["ok"] is True
        records = identity_mod.get_prekey_lookup_handle_records()
        current_handle = max(
            (dict(item) for item in records),
            key=lambda item: int(item.get("issued_at", 0) or 0),
        )["handle"]
        now["value"] += 60

    assert len(identity_mod.get_prekey_lookup_handle_records()) <= identity_mod.PREKEY_LOOKUP_ROTATION_ACTIVE_CAP


def test_failed_republish_does_not_destroy_currently_working_handle(tmp_path, monkeypatch):
    relay, identity_mod, _contacts_mod, prekey_mod, relay_mod = _fresh_rotation_state(tmp_path, monkeypatch)

    exported = identity_mod.export_wormhole_dm_invite()
    old_handle = str(exported["invite"]["payload"]["prekey_lookup_handle"] or "")
    record = next(
        item for item in identity_mod.get_prekey_lookup_handle_records()
        if str(item.get("handle", "") or "") == old_handle
    )
    now = _patch_time(
        monkeypatch,
        int(record.get("issued_at", 0) or 0),
        identity_mod,
        prekey_mod,
        relay_mod,
    )
    _set_handle_record(
        identity_mod,
        old_handle,
        use_count=identity_mod.PREKEY_LOOKUP_HANDLE_MAX_USES - identity_mod.PREKEY_LOOKUP_ROTATE_BEFORE_REMAINING_USES + 1,
    )
    monkeypatch.setattr(
        prekey_mod,
        "register_wormhole_prekey_bundle",
        lambda: {"ok": False, "detail": "publish failed"},
    )

    result = identity_mod.maybe_rotate_prekey_lookup_handles(now=now["value"])
    handles = {
        str(item.get("handle", "") or "")
        for item in identity_mod.get_prekey_lookup_handle_records()
    }

    assert result["ok"] is False
    assert handles == {old_handle}
    assert relay.get_prekey_bundle_by_lookup(old_handle)[0] is not None


def test_contact_pinned_handle_reference_updates_forward_where_applicable(tmp_path, monkeypatch):
    _relay, identity_mod, contacts_mod, prekey_mod, relay_mod = _fresh_rotation_state(tmp_path, monkeypatch)

    exported = identity_mod.export_wormhole_dm_invite()
    local_identity = identity_mod.read_wormhole_identity()
    old_handle = str(exported["invite"]["payload"]["prekey_lookup_handle"] or "")
    record = next(
        item for item in identity_mod.get_prekey_lookup_handle_records()
        if str(item.get("handle", "") or "") == old_handle
    )
    now = _patch_time(
        monkeypatch,
        int(record.get("issued_at", 0) or 0),
        identity_mod,
        contacts_mod,
        prekey_mod,
        relay_mod,
    )
    contacts_mod.pin_wormhole_dm_invite(
        local_identity["node_id"],
        invite_payload={
            "trust_fingerprint": "aa" * 32,
            "public_key": local_identity["public_key"],
            "public_key_algo": local_identity["public_key_algo"],
            "identity_dh_pub_key": local_identity["dh_pub_key"],
            "dh_algo": local_identity["dh_algo"],
            "prekey_lookup_handle": old_handle,
            "issued_at": now["value"],
            "expires_at": 0,
        },
        attested=True,
    )
    _set_handle_record(
        identity_mod,
        old_handle,
        use_count=identity_mod.PREKEY_LOOKUP_HANDLE_MAX_USES - identity_mod.PREKEY_LOOKUP_ROTATE_BEFORE_REMAINING_USES + 1,
    )

    result = identity_mod.maybe_rotate_prekey_lookup_handles(now=now["value"])
    refreshed = contacts_mod.list_wormhole_dm_contacts()[local_identity["node_id"]]

    assert result["ok"] is True
    assert refreshed["invitePinnedPrekeyLookupHandle"] != old_handle
    assert refreshed["invitePinnedPrekeyLookupHandle"]


def test_authenticated_status_keeps_lookup_handle_rotation_surface_coarse(monkeypatch):
    monkeypatch.setattr(main, "_check_scoped_auth", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        main,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": False, "rns_ready": False},
    )
    monkeypatch.setattr(main, "_current_private_lane_tier", lambda *_args, **_kwargs: "private_control_only")
    monkeypatch.setattr(
        main,
        "_refresh_lookup_handle_rotation_background",
        lambda **_kwargs: {"ok": True, "rotated": False},
    )
    monkeypatch.setattr(
        main,
        "lookup_handle_rotation_status_snapshot",
        lambda: {
            "state": "lookup_handle_rotation_ok",
            "detail": "lookup handles healthy",
            "checked_at": 123,
            "last_success_at": 120,
            "last_failure_at": 0,
            "active_handle_count": 2,
            "fresh_handle_available": True,
        },
    )

    result = asyncio.run(main.api_wormhole_status(_request("/api/wormhole/status")))
    rotation = result["lookup_handle_rotation"]

    assert rotation["state"] == "lookup_handle_rotation_ok"
    assert "handle" not in rotation
    assert "handles" not in rotation
    assert "mapping" not in rotation
