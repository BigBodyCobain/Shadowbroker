import time


def _configure_alias_runtime(tmp_path, monkeypatch):
    from services.mesh import (
        mesh_secure_storage,
        mesh_wormhole_contacts,
        mesh_wormhole_persona,
    )

    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    monkeypatch.setattr(mesh_wormhole_persona, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_persona, "PERSONA_FILE", tmp_path / "wormhole_persona.json")
    monkeypatch.setattr(
        mesh_wormhole_persona,
        "LEGACY_DM_IDENTITY_FILE",
        tmp_path / "wormhole_identity.json",
    )
    monkeypatch.setattr(mesh_wormhole_contacts, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_contacts, "CONTACTS_FILE", tmp_path / "wormhole_dm_contacts.json")
    return mesh_wormhole_contacts


def test_contact_alias_acceptance_defaults_to_current_only(tmp_path, monkeypatch):
    contacts = _configure_alias_runtime(tmp_path, monkeypatch)

    contact = contacts.upsert_wormhole_dm_contact(
        "peer_current_only",
        {"sharedAlias": "dmx_current"},
    )

    assert contacts.accepted_contact_shared_aliases(contact) == ["dmx_current"]
    assert contacts.contact_shared_alias_accepted(contact, "dmx_current") is True
    assert contacts.contact_shared_alias_accepted(contact, "dmx_pending") is False


def test_contact_alias_acceptance_includes_pending_only_during_grace(tmp_path, monkeypatch):
    contacts = _configure_alias_runtime(tmp_path, monkeypatch)
    now_ms = int(time.time() * 1000)

    contact = contacts.upsert_wormhole_dm_contact(
        "peer_grace",
        {
            "sharedAlias": "dmx_current",
            "pendingSharedAlias": "dmx_pending",
            "sharedAliasGraceUntil": now_ms + 60_000,
            "previousSharedAliases": ["dmx_prev1", "dmx_prev2"],
        },
    )

    accepted = contacts.accepted_contact_shared_aliases(contact, now_ms=now_ms)

    assert accepted == ["dmx_current", "dmx_pending"]
    assert contacts.contact_shared_alias_accepted(contact, "dmx_current", now_ms=now_ms) is True
    assert contacts.contact_shared_alias_accepted(contact, "dmx_pending", now_ms=now_ms) is True
    assert contacts.contact_shared_alias_accepted(contact, "dmx_prev1", now_ms=now_ms) is False


def test_contact_alias_acceptance_rejects_old_alias_after_grace(tmp_path, monkeypatch):
    from services.mesh import mesh_wormhole_dead_drop

    contacts = _configure_alias_runtime(tmp_path, monkeypatch)

    initial = mesh_wormhole_dead_drop.issue_pairwise_dm_alias(
        peer_id="peer_promoted",
        peer_dh_pub="dhpub_promoted",
    )
    rotated = mesh_wormhole_dead_drop.rotate_pairwise_dm_alias(
        peer_id="peer_promoted",
        peer_dh_pub="dhpub_promoted",
        grace_ms=5_000,
    )

    future = rotated["grace_until"] / 1000.0 + 1
    monkeypatch.setattr(contacts.time, "time", lambda: future)
    promoted = contacts.list_wormhole_dm_contacts()["peer_promoted"]

    assert promoted["sharedAlias"] == initial["shared_alias"]
    assert promoted["pendingSharedAlias"] == rotated["pending_alias"]
    assert contacts.contact_shared_alias_accepted(promoted, rotated["pending_alias"], now_ms=int(future * 1000)) is False
    assert contacts.contact_shared_alias_accepted(promoted, initial["shared_alias"], now_ms=int(future * 1000)) is True


def test_mailbox_refs_keep_current_alias_first_during_grace(tmp_path, monkeypatch):
    from services.mesh import mesh_wormhole_contacts, mesh_wormhole_dead_drop

    _configure_alias_runtime(tmp_path, monkeypatch)
    now_ms = int(time.time() * 1000)
    mesh_wormhole_contacts.upsert_wormhole_dm_contact(
        "peer_mailbox",
        {
            "sharedAlias": "dmx_current",
            "pendingSharedAlias": "dmx_pending",
            "sharedAliasGraceUntil": now_ms + 60_000,
            "previousSharedAliases": ["dmx_prev1", "dmx_prev2"],
        },
    )

    refs = mesh_wormhole_dead_drop._mailbox_peer_refs("peer_mailbox")
    assert refs == ["dmx_current", "dmx_pending", "dmx_prev1", "dmx_prev2"]


def test_outbound_prefers_current_alias_while_grace_is_active(tmp_path, monkeypatch):
    import main
    from services.mesh import mesh_wormhole_contacts

    _configure_alias_runtime(tmp_path, monkeypatch)
    now_ms = int(time.time() * 1000)
    mesh_wormhole_contacts.upsert_wormhole_dm_contact(
        "peer_outbound",
        {
            "sharedAlias": "dmx_current",
            "pendingSharedAlias": "dmx_pending",
            "sharedAliasGraceUntil": now_ms + 60_000,
        },
    )

    assert main._preferred_remote_dm_alias("peer_outbound") == "dmx_current"


def test_second_rotation_during_grace_returns_existing_pending_alias(tmp_path, monkeypatch):
    from services.mesh import mesh_wormhole_dead_drop

    _configure_alias_runtime(tmp_path, monkeypatch)

    mesh_wormhole_dead_drop.issue_pairwise_dm_alias(
        peer_id="peer_repeat_rotate",
        peer_dh_pub="dhpub_repeat",
    )
    first = mesh_wormhole_dead_drop.rotate_pairwise_dm_alias(
        peer_id="peer_repeat_rotate",
        peer_dh_pub="dhpub_repeat",
        grace_ms=60_000,
    )
    second = mesh_wormhole_dead_drop.rotate_pairwise_dm_alias(
        peer_id="peer_repeat_rotate",
        peer_dh_pub="dhpub_repeat",
        grace_ms=60_000,
    )

    assert first["rotated"] is True
    assert second["rotated"] is False
    assert second["pending_alias"] == first["pending_alias"]
    assert second["active_alias"] == first["active_alias"]


def test_pairwise_alias_rotation_default_grace_is_14_days(tmp_path, monkeypatch):
    from services.mesh import mesh_wormhole_dead_drop

    _configure_alias_runtime(tmp_path, monkeypatch)
    now_seconds = 1_700_000_000
    monkeypatch.setattr(mesh_wormhole_dead_drop.time, "time", lambda: now_seconds)

    mesh_wormhole_dead_drop.issue_pairwise_dm_alias(
        peer_id="peer_default_grace",
        peer_dh_pub="dhpub_default",
    )
    rotated = mesh_wormhole_dead_drop.rotate_pairwise_dm_alias(
        peer_id="peer_default_grace",
        peer_dh_pub="dhpub_default",
    )

    assert rotated["grace_until"] - int(now_seconds * 1000) == mesh_wormhole_dead_drop.PAIRWISE_ALIAS_GRACE_DEFAULT_MS
