"""P2C: Tighten pairwise alias history and mailbox-ref linkability.

Tests prove:
- previousSharedAliases bounded to 2 (backend and normalization)
- _merge_alias_history defaults to limit=2
- _mailbox_peer_refs bounded to 4 and excludes long tail
- Alias rotation continuity still works (current + pending + grace)
- Promotion compacts history after grace
- Stable peer_id only appears when no alias exists
- History stays deduplicated
"""

import time


class TestNormalizeContactAliasBound:
    """Backend _normalize_contact truncates previousSharedAliases to 2."""

    def test_normalize_truncates_long_alias_history(self, tmp_path, monkeypatch):
        from services.mesh import mesh_secure_storage, mesh_wormhole_contacts

        monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
        monkeypatch.setattr(mesh_wormhole_contacts, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mesh_wormhole_contacts, "CONTACTS_FILE", tmp_path / "wormhole_dm_contacts.json")

        long_history = [f"dmx_old_{i}" for i in range(8)]
        contact = mesh_wormhole_contacts.upsert_wormhole_dm_contact(
            "peer_a",
            {"previousSharedAliases": long_history},
        )
        assert len(contact["previousSharedAliases"]) == 2
        assert contact["previousSharedAliases"] == long_history[-2:]

    def test_normalize_preserves_short_history(self, tmp_path, monkeypatch):
        from services.mesh import mesh_secure_storage, mesh_wormhole_contacts

        monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
        monkeypatch.setattr(mesh_wormhole_contacts, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mesh_wormhole_contacts, "CONTACTS_FILE", tmp_path / "wormhole_dm_contacts.json")

        contact = mesh_wormhole_contacts.upsert_wormhole_dm_contact(
            "peer_b",
            {"previousSharedAliases": ["dmx_one"]},
        )
        assert contact["previousSharedAliases"] == ["dmx_one"]

    def test_normalize_deduplicates_and_strips(self, tmp_path, monkeypatch):
        from services.mesh import mesh_secure_storage, mesh_wormhole_contacts

        monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
        monkeypatch.setattr(mesh_wormhole_contacts, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mesh_wormhole_contacts, "CONTACTS_FILE", tmp_path / "wormhole_dm_contacts.json")

        contact = mesh_wormhole_contacts.upsert_wormhole_dm_contact(
            "peer_c",
            {"previousSharedAliases": ["dmx_x", "", "  ", "dmx_x", "dmx_y", "dmx_z"]},
        )
        # After stripping empty and dedup, we have dmx_x, dmx_y, dmx_z but capped to last 2
        assert len(contact["previousSharedAliases"]) <= 2


class TestMergeAliasHistoryBound:
    """Both backend _merge_alias_history functions default to limit=2."""

    def test_contacts_merge_defaults_to_2(self):
        from services.mesh.mesh_wormhole_contacts import _merge_alias_history

        result = _merge_alias_history("a", "b", "c", "d")
        assert result == ["a", "b"]

    def test_dead_drop_merge_defaults_to_2(self):
        from services.mesh.mesh_wormhole_dead_drop import _merge_alias_history

        result = _merge_alias_history("x", "y", "z")
        assert result == ["x", "y"]

    def test_merge_deduplicates(self):
        from services.mesh.mesh_wormhole_contacts import _merge_alias_history

        result = _merge_alias_history("a", "a", "b", "c")
        assert result == ["a", "b"]

    def test_merge_skips_empty(self):
        from services.mesh.mesh_wormhole_contacts import _merge_alias_history

        result = _merge_alias_history("", "  ", "a", "b", "c")
        assert result == ["a", "b"]


class TestMailboxPeerRefsBound:
    """Backend _mailbox_peer_refs capped to 4 and excludes long tail."""

    def test_refs_bounded_to_4(self, tmp_path, monkeypatch):
        from services.mesh import mesh_secure_storage, mesh_wormhole_contacts
        from services.mesh.mesh_wormhole_dead_drop import _mailbox_peer_refs

        monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
        monkeypatch.setattr(mesh_wormhole_contacts, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mesh_wormhole_contacts, "CONTACTS_FILE", tmp_path / "wormhole_dm_contacts.json")

        # Even if we somehow have more aliases, refs should be capped
        mesh_wormhole_contacts.upsert_wormhole_dm_contact(
            "peer_d",
            {
                "sharedAlias": "dmx_current",
                "pendingSharedAlias": "dmx_pending",
                "sharedAliasGraceUntil": int(time.time() * 1000) + 30_000,
                "previousSharedAliases": ["dmx_prev1", "dmx_prev2"],
            },
        )
        refs = _mailbox_peer_refs("peer_d")
        assert len(refs) <= 4
        assert "dmx_current" in refs
        assert "dmx_pending" in refs

    def test_refs_do_not_include_stable_id_when_aliases_exist(self, tmp_path, monkeypatch):
        from services.mesh import mesh_secure_storage, mesh_wormhole_contacts
        from services.mesh.mesh_wormhole_dead_drop import _mailbox_peer_refs

        monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
        monkeypatch.setattr(mesh_wormhole_contacts, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mesh_wormhole_contacts, "CONTACTS_FILE", tmp_path / "wormhole_dm_contacts.json")

        mesh_wormhole_contacts.upsert_wormhole_dm_contact(
            "peer_e",
            {"sharedAlias": "dmx_active"},
        )
        refs = _mailbox_peer_refs("peer_e")
        assert "peer_e" not in refs
        assert refs == ["dmx_active"]

    def test_refs_fall_back_to_peer_id_when_no_aliases(self, tmp_path, monkeypatch):
        from services.mesh import mesh_secure_storage, mesh_wormhole_contacts
        from services.mesh.mesh_wormhole_dead_drop import _mailbox_peer_refs

        monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
        monkeypatch.setattr(mesh_wormhole_contacts, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mesh_wormhole_contacts, "CONTACTS_FILE", tmp_path / "wormhole_dm_contacts.json")

        refs = _mailbox_peer_refs("peer_f")
        assert refs == ["peer_f"]

    def test_explicit_peer_refs_capped_to_4(self):
        from services.mesh.mesh_wormhole_dead_drop import _mailbox_peer_refs

        refs = _mailbox_peer_refs(
            "peer_g",
            peer_refs=["r1", "r2", "r3", "r4", "r5", "r6"],
        )
        assert len(refs) == 4
        assert refs == ["r1", "r2", "r3", "r4"]


class TestRotationContinuityWithTighterBounds:
    """Rotation still works correctly with the tighter alias history."""

    def test_rotation_keeps_current_and_pending_during_grace(self, tmp_path, monkeypatch):
        from services.mesh import (
            mesh_secure_storage,
            mesh_wormhole_contacts,
            mesh_wormhole_dead_drop,
            mesh_wormhole_persona,
        )

        monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
        monkeypatch.setattr(mesh_wormhole_persona, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mesh_wormhole_persona, "PERSONA_FILE", tmp_path / "wormhole_persona.json")
        monkeypatch.setattr(mesh_wormhole_persona, "LEGACY_DM_IDENTITY_FILE", tmp_path / "wormhole_identity.json")
        monkeypatch.setattr(mesh_wormhole_contacts, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mesh_wormhole_contacts, "CONTACTS_FILE", tmp_path / "wormhole_dm_contacts.json")

        initial = mesh_wormhole_dead_drop.issue_pairwise_dm_alias(peer_id="peer_h", peer_dh_pub="dhpub_h")
        rotated = mesh_wormhole_dead_drop.rotate_pairwise_dm_alias(peer_id="peer_h", grace_ms=30_000)

        assert rotated["ok"] is True
        contact = rotated["contact"]
        assert contact["sharedAlias"] == initial["shared_alias"]
        assert contact["pendingSharedAlias"] == rotated["pending_alias"]
        assert contact["sharedAliasGraceUntil"] > 0

    def test_promotion_compacts_history_to_bound(self, tmp_path, monkeypatch):
        from services.mesh import (
            mesh_secure_storage,
            mesh_wormhole_contacts,
            mesh_wormhole_dead_drop,
            mesh_wormhole_persona,
        )

        monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
        monkeypatch.setattr(mesh_wormhole_persona, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mesh_wormhole_persona, "PERSONA_FILE", tmp_path / "wormhole_persona.json")
        monkeypatch.setattr(mesh_wormhole_persona, "LEGACY_DM_IDENTITY_FILE", tmp_path / "wormhole_identity.json")
        monkeypatch.setattr(mesh_wormhole_contacts, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mesh_wormhole_contacts, "CONTACTS_FILE", tmp_path / "wormhole_dm_contacts.json")

        # Issue + rotate 4 times to build up history
        mesh_wormhole_dead_drop.issue_pairwise_dm_alias(peer_id="peer_i", peer_dh_pub="dhpub_i")
        aliases_seen = []
        for _ in range(4):
            r = mesh_wormhole_dead_drop.rotate_pairwise_dm_alias(peer_id="peer_i", grace_ms=5_000)
            aliases_seen.append(r["pending_alias"])
            # Promote by advancing time past grace
            future = r["grace_until"] / 1000.0 + 1
            monkeypatch.setattr(mesh_wormhole_contacts.time, "time", lambda _f=future: _f)
            mesh_wormhole_contacts.list_wormhole_dm_contacts()  # triggers promotion

        contact = mesh_wormhole_contacts.list_wormhole_dm_contacts()["peer_i"]
        assert len(contact["previousSharedAliases"]) <= 2
        # Current alias is the last promoted one
        assert contact["sharedAlias"] == aliases_seen[-1]

    def test_multiple_rotations_never_exceed_2_previous(self, tmp_path, monkeypatch):
        from services.mesh import (
            mesh_secure_storage,
            mesh_wormhole_contacts,
            mesh_wormhole_dead_drop,
            mesh_wormhole_persona,
        )

        monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
        monkeypatch.setattr(mesh_wormhole_persona, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mesh_wormhole_persona, "PERSONA_FILE", tmp_path / "wormhole_persona.json")
        monkeypatch.setattr(mesh_wormhole_persona, "LEGACY_DM_IDENTITY_FILE", tmp_path / "wormhole_identity.json")
        monkeypatch.setattr(mesh_wormhole_contacts, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mesh_wormhole_contacts, "CONTACTS_FILE", tmp_path / "wormhole_dm_contacts.json")

        mesh_wormhole_dead_drop.issue_pairwise_dm_alias(peer_id="peer_j", peer_dh_pub="dhpub_j")
        for i in range(6):
            r = mesh_wormhole_dead_drop.rotate_pairwise_dm_alias(peer_id="peer_j", grace_ms=5_000)
            future = r["grace_until"] / 1000.0 + 1
            monkeypatch.setattr(mesh_wormhole_contacts.time, "time", lambda _f=future: _f)
            mesh_wormhole_contacts.list_wormhole_dm_contacts()

        contact = mesh_wormhole_contacts.list_wormhole_dm_contacts()["peer_j"]
        assert len(contact["previousSharedAliases"]) <= 2
        # No duplicates
        assert len(contact["previousSharedAliases"]) == len(set(contact["previousSharedAliases"]))
