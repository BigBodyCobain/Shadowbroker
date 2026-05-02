import json
import time

from services.mesh import mesh_reputation, mesh_secure_storage
from services.config import get_settings


def _reset_reputation_vote_salt_state(monkeypatch):
    monkeypatch.setattr(mesh_reputation, "_VOTE_STORAGE_SALT_CACHE", None, raising=False)
    monkeypatch.setattr(mesh_reputation, "_VOTE_STORAGE_SALT_WARNING_EMITTED", False, raising=False)
    get_settings.cache_clear()


def _configure_reputation_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(mesh_reputation, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_reputation, "LEDGER_FILE", tmp_path / "reputation_ledger.json")
    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    _reset_reputation_vote_salt_state(monkeypatch)


def test_identity_link_merges_reputation(tmp_path, monkeypatch):
    monkeypatch.setattr(mesh_reputation, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_reputation, "LEDGER_FILE", tmp_path / "rep.json")
    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")

    ledger = mesh_reputation.ReputationLedger()

    now = time.time()
    ledger.votes = [
        {
            "voter_id": "!sb_v1",
            "target_id": "!sb_old",
            "vote": 1,
            "gate": "",
            "timestamp": now,
            "weight": 1.0,
            "agent_verify": False,
        },
        {
            "voter_id": "!sb_v2",
            "target_id": "!sb_new",
            "vote": 1,
            "gate": "",
            "timestamp": now,
            "weight": 1.0,
            "agent_verify": False,
        },
    ]
    ledger._scores_dirty = True

    ok, _ = ledger.link_identities("!sb_old", "!sb_new")
    assert ok is True

    rep = ledger.get_reputation("!sb_new")
    assert rep["overall"] == 2
    assert "linked_from" not in rep
    assert ledger.aliases["!sb_new"] == "!sb_old"


def test_reputation_ledger_is_encrypted_at_rest(tmp_path, monkeypatch):
    _configure_reputation_storage(tmp_path, monkeypatch)

    ledger = mesh_reputation.ReputationLedger()
    ledger.register_node("!sb_voter")
    ledger.register_node("!sb_target")

    ok, _reason, _weight = ledger.cast_vote("!sb_voter", "!sb_target", 1)
    assert ok is True

    ledger._flush()
    domain_path = tmp_path / mesh_reputation.LEDGER_DOMAIN / mesh_reputation.LEDGER_FILE.name
    raw = domain_path.read_text(encoding="utf-8")

    assert '"kind": "sb_secure_json"' in raw
    assert domain_path.exists()
    assert not mesh_reputation.LEDGER_FILE.exists()
    assert "!sb_voter" not in raw
    assert "!sb_target" not in raw


def test_reputation_votes_are_blinded_inside_encrypted_ledger(tmp_path, monkeypatch):
    _configure_reputation_storage(tmp_path, monkeypatch)

    ledger = mesh_reputation.ReputationLedger()
    ledger.register_node("!sb_voter")
    ledger.register_node("!sb_target")

    ok, _reason, _weight = ledger.cast_vote("!sb_voter", "!sb_target", 1)
    assert ok is True

    ledger._flush()
    stored = mesh_secure_storage.read_domain_json(
        mesh_reputation.LEDGER_DOMAIN,
        mesh_reputation.LEDGER_FILE.name,
        lambda: {},
    )
    vote = stored["votes"][0]

    assert "voter_id" not in vote
    assert vote["blinded_voter_id"]


def test_reputation_duplicate_same_direction_vote_is_rejected(tmp_path, monkeypatch):
    _configure_reputation_storage(tmp_path, monkeypatch)

    ledger = mesh_reputation.ReputationLedger()
    ledger.register_node("!sb_voter")
    ledger.register_node("!sb_target")

    ok, reason, _weight = ledger.cast_vote("!sb_voter", "!sb_target", 1, "infonet")
    assert ok is True
    assert "Voted up" in reason
    assert len([vote for vote in ledger.votes if not vote.get("vote_cost")]) == 1

    ok, reason, _weight = ledger.cast_vote("!sb_voter", "!sb_target", 1, "infonet")
    assert ok is False
    assert reason == "Vote already set to up on !sb_target in gate 'infonet'"
    assert len([vote for vote in ledger.votes if not vote.get("vote_cost")]) == 1


def test_reputation_vote_direction_can_change_without_creating_duplicates(tmp_path, monkeypatch):
    _configure_reputation_storage(tmp_path, monkeypatch)

    ledger = mesh_reputation.ReputationLedger()
    ledger.register_node("!sb_voter")
    ledger.register_node("!sb_target")

    ok, _reason, _weight = ledger.cast_vote("!sb_voter", "!sb_target", 1, "infonet")
    assert ok is True
    assert len([vote for vote in ledger.votes if not vote.get("vote_cost")]) == 1

    ok, reason, _weight = ledger.cast_vote("!sb_voter", "!sb_target", -1, "infonet")
    assert ok is True
    assert "Voted down" in reason
    assert len([vote for vote in ledger.votes if not vote.get("vote_cost")]) == 1
    assert next(vote for vote in ledger.votes if not vote.get("vote_cost"))["vote"] == -1


def test_reputation_vote_rotation_preserves_duplicate_detection(tmp_path, monkeypatch):
    _configure_reputation_storage(tmp_path, monkeypatch)
    monkeypatch.setenv("MESH_PEER_PUSH_SECRET", "shadowbroker-peer-secret-rotation-test")
    monkeypatch.setenv("MESH_VOTER_BLIND_SALT_ROTATE_DAYS", "30")
    monkeypatch.setenv("MESH_VOTER_BLIND_SALT_GRACE_DAYS", "30")
    _reset_reputation_vote_salt_state(monkeypatch)

    now = 1_700_000_000.0
    monkeypatch.setattr(mesh_reputation.time, "time", lambda: now)

    ledger = mesh_reputation.ReputationLedger()
    ledger.register_node("!sb_voter")
    ledger.register_node("!sb_target")

    ok, _reason, _weight = ledger.cast_vote("!sb_voter", "!sb_target", 1, "infonet")
    assert ok is True
    initial_blinded = ledger.votes[0]["blinded_voter_id"]

    now += 31 * 86400
    _reset_reputation_vote_salt_state(monkeypatch)

    ok, reason, _weight = ledger.cast_vote("!sb_voter", "!sb_target", 1, "infonet")
    assert ok is False
    assert reason == "Vote already set to up on !sb_target in gate 'infonet'"
    assert mesh_reputation._blind_voter("!sb_voter", mesh_reputation._vote_storage_salt()) != initial_blinded


def test_reputation_vote_rotation_keeps_wallet_costs_visible_across_history(tmp_path, monkeypatch):
    _configure_reputation_storage(tmp_path, monkeypatch)
    monkeypatch.setenv("MESH_PEER_PUSH_SECRET", "shadowbroker-peer-secret-wallet-test")
    monkeypatch.setenv("MESH_VOTER_BLIND_SALT_ROTATE_DAYS", "30")
    monkeypatch.setenv("MESH_VOTER_BLIND_SALT_GRACE_DAYS", "30")
    _reset_reputation_vote_salt_state(monkeypatch)

    now = 1_700_000_000.0
    monkeypatch.setattr(mesh_reputation.time, "time", lambda: now)

    ledger = mesh_reputation.ReputationLedger()
    ledger.register_node("!sb_voter")
    ledger.register_node("!sb_target")

    ok, _reason, _weight = ledger.cast_vote("!sb_voter", "!sb_target", 1)
    assert ok is True
    ledger._flush()

    now += 62 * 86400
    _reset_reputation_vote_salt_state(monkeypatch)
    ledger = mesh_reputation.ReputationLedger()

    rep = ledger.get_reputation("!sb_voter")
    assert rep["overall"] < 0
    assert rep["downvotes"] >= 1


def test_reputation_local_voter_salt_history_migrates_legacy_file(tmp_path, monkeypatch):
    _configure_reputation_storage(tmp_path, monkeypatch)
    monkeypatch.delenv("MESH_PEER_PUSH_SECRET", raising=False)
    monkeypatch.setenv("MESH_VOTER_BLIND_SALT_ROTATE_DAYS", "30")
    monkeypatch.setenv("MESH_VOTER_BLIND_SALT_GRACE_DAYS", "30")
    _reset_reputation_vote_salt_state(monkeypatch)

    legacy_salt = bytes.fromhex("11" * 32)
    (tmp_path / "voter_blind_salt.bin").write_bytes(legacy_salt)
    now = 1_700_000_000.0
    monkeypatch.setattr(mesh_reputation.time, "time", lambda: now)

    salts = mesh_reputation._vote_storage_salts()

    assert legacy_salt in salts
    assert salts[0] != legacy_salt
    assert not (tmp_path / "voter_blind_salt.bin").exists()


def test_gate_catalog_is_domain_encrypted_with_legacy_migration(tmp_path, monkeypatch):
    monkeypatch.setattr(mesh_reputation, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_reputation, "GATES_FILE", tmp_path / "gates.json")
    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")

    legacy = {"ops": {"display_name": "Ops", "fixed": False}}
    mesh_reputation.GATES_FILE.write_text(json.dumps(legacy), encoding="utf-8")

    manager = mesh_reputation.GateManager(mesh_reputation.ReputationLedger())
    domain_path = tmp_path / mesh_reputation.GATES_DOMAIN / mesh_reputation.GATES_FILE.name
    stored = mesh_secure_storage.read_domain_json(
        mesh_reputation.GATES_DOMAIN,
        mesh_reputation.GATES_FILE.name,
        lambda: {},
    )

    assert domain_path.exists()
    assert not mesh_reputation.GATES_FILE.exists()
    assert stored["ops"]["display_name"] == "Ops"
    assert manager.gates["ops"]["display_name"] == "Ops"
