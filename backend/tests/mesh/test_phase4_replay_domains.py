import time

from services.mesh import mesh_hashchain
from services.mesh.mesh_signed_events import (
    PreparedSignedWrite,
    SignedWriteKind,
    _SignedWriteAbort,
    _apply_signed_write_freshness_policy,
)


def test_infonet_sequence_domains_are_independent(tmp_path, monkeypatch):
    monkeypatch.setattr(mesh_hashchain, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_hashchain, "CHAIN_FILE", tmp_path / "infonet.json")
    monkeypatch.setattr(mesh_hashchain, "WAL_FILE", tmp_path / "infonet.wal")

    inf = mesh_hashchain.Infonet()

    assert inf.validate_and_set_sequence("node-a", 1, domain="dm_poll") == (True, "ok")
    assert inf.validate_and_set_sequence("node-a", 1, domain="dm_send") == (True, "ok")

    ok, reason = inf.validate_and_set_sequence("node-a", 1, domain="dm_poll")
    assert ok is False
    assert "Replay detected" in reason

    assert inf.node_sequences == {}
    assert inf.sequence_domains["node-a|dm_poll"] == 1
    assert inf.sequence_domains["node-a|dm_send"] == 1


def test_private_signed_sequence_helper_falls_back_for_legacy_infonet():
    import main

    class LegacyInfonet:
        def __init__(self):
            self.sequences = {}

        def validate_and_set_sequence(self, node_id, sequence):
            last = self.sequences.get(node_id, 0)
            if sequence <= last:
                return False, f"Replay detected: sequence {sequence} <= last {last}"
            self.sequences[node_id] = sequence
            return True, "OK"

    inf = LegacyInfonet()

    assert main._validate_private_signed_sequence(
        inf,
        "node-a",
        1,
        domain="dm_poll",
    ) == (True, "OK")
    assert main._validate_private_signed_sequence(
        inf,
        "node-a",
        1,
        domain="dm_send",
    ) == (True, "OK")

    ok, reason = main._validate_private_signed_sequence(
        inf,
        "node-a",
        1,
        domain="dm_poll",
    )
    assert ok is False
    assert "Replay detected" in reason
    assert inf.sequences["node-a|dm_poll"] == 1
    assert inf.sequences["node-a|dm_send"] == 1


def _prepared_timestamped_write(timestamp: int) -> PreparedSignedWrite:
    return PreparedSignedWrite(
        kind=SignedWriteKind.DM_SEND,
        event_type="dm_message",
        body={},
        node_id="node-a",
        sequence=1,
        public_key="pub",
        public_key_algo="Ed25519",
        signature="sig",
        protocol_version="1",
        payload={"timestamp": timestamp},
    )


def test_signed_write_freshness_rejects_ancient_timestamp(monkeypatch):
    monkeypatch.setenv("MESH_SIGNED_WRITE_MAX_AGE_S", "60")

    stale = int(time.time()) - 61
    try:
        _apply_signed_write_freshness_policy(_prepared_timestamped_write(stale))
    except _SignedWriteAbort as exc:
        assert exc.response["ok"] is False
        assert exc.response["max_age_s"] == 60
        assert "freshness window" in exc.response["detail"]
    else:
        raise AssertionError("stale signed write was accepted")


def test_signed_write_freshness_accepts_current_timestamp(monkeypatch):
    monkeypatch.setenv("MESH_SIGNED_WRITE_MAX_AGE_S", "60")

    _apply_signed_write_freshness_policy(_prepared_timestamped_write(int(time.time())))
