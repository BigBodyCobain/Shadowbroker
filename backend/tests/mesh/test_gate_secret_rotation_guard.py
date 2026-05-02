import ast
import base64
import copy
import os
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[2]
ALLOWED_GATE_SECRET_WRITERS = {
    "ensure_gate_secret",
    "_rotate_gate_secret_for_member_removal_locked",
}


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    from services.config import get_settings
    from services.mesh import mesh_reputation

    get_settings.cache_clear()
    original_gates = copy.deepcopy(mesh_reputation.gate_manager.gates)
    yield
    mesh_reputation.gate_manager.gates = original_gates
    get_settings.cache_clear()


def _gate_secret_write_report(path: Path) -> dict[str, list[int]]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    report: dict[str, list[int]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        writes: list[int] = []
        for child in ast.walk(node):
            target = None
            if isinstance(child, ast.Assign):
                for candidate in child.targets:
                    if isinstance(candidate, ast.Subscript):
                        target = candidate
                        break
            elif isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Subscript):
                target = child.target
            if target is None:
                continue
            base = target.value
            slice_node = target.slice
            key = slice_node.value if isinstance(slice_node, ast.Index) else slice_node
            if (
                isinstance(base, ast.Name)
                and base.id == "gate"
                and isinstance(key, ast.Constant)
                and key.value == "gate_secret"
            ):
                writes.append(child.lineno)
        if writes:
            report[node.name] = writes
    return report


def _fresh_real_gate_state(tmp_path, monkeypatch):
    from services import wormhole_supervisor
    from services.config import get_settings
    from services.mesh import mesh_gate_mls, mesh_reputation, mesh_secure_storage, mesh_wormhole_persona

    monkeypatch.setenv("MESH_GATE_RECOVERY_ENVELOPE_ENABLE", "true")
    monkeypatch.setenv("MESH_GATE_RECOVERY_ENVELOPE_ENABLE_ACKNOWLEDGE", "true")
    monkeypatch.setenv("MESH_GATE_BAN_KICK_ROTATION_ENABLE", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(mesh_secure_storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_secure_storage, "MASTER_KEY_FILE", tmp_path / "wormhole_secure_store.key")
    monkeypatch.setattr(mesh_gate_mls, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_gate_mls, "STATE_FILE", tmp_path / "wormhole_gate_mls.json")
    monkeypatch.setattr(mesh_wormhole_persona, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mesh_wormhole_persona, "PERSONA_FILE", tmp_path / "wormhole_persona.json")
    monkeypatch.setattr(
        mesh_wormhole_persona,
        "LEGACY_DM_IDENTITY_FILE",
        tmp_path / "wormhole_identity.json",
    )
    monkeypatch.setattr(wormhole_supervisor, "get_transport_tier", lambda: "private_transitional")
    monkeypatch.setattr(
        wormhole_supervisor,
        "get_wormhole_state",
        lambda: {"configured": True, "ready": True, "arti_ready": True, "rns_ready": False},
    )
    monkeypatch.setattr(mesh_reputation.gate_manager, "_save", lambda: None)
    mesh_gate_mls.reset_gate_mls_state()
    return mesh_gate_mls, mesh_wormhole_persona, mesh_reputation.gate_manager


def test_gate_secret_writes_only_flow_through_authorized_helpers():
    report = _gate_secret_write_report(BACKEND_DIR / "services" / "mesh" / "mesh_reputation.py")
    assert set(report) == ALLOWED_GATE_SECRET_WRITERS, report


def test_gate_secret_ast_guard_self_test_rejects_extra_writer(tmp_path):
    path = tmp_path / "fake_gate_manager.py"
    path.write_text(
        """
class Fake:
    def ensure_gate_secret(self, gate):
        gate["gate_secret"] = "ok"

    def rogue(self, gate):
        gate["gate_secret"] = "bad"
""".strip(),
        encoding="utf-8",
    )
    report = _gate_secret_write_report(path)
    assert set(report) == {"ensure_gate_secret", "rogue"}


def test_ban_rotation_updates_archive_and_records_latency(monkeypatch):
    from services.config import get_settings
    from services.mesh import mesh_metrics, mesh_reputation
    from services.mesh import mesh_gate_mls

    monkeypatch.setenv("MESH_GATE_BAN_KICK_ROTATION_ENABLE", "true")
    get_settings.cache_clear()
    mesh_metrics.reset()
    monkeypatch.setattr(mesh_reputation.gate_manager, "_save", lambda: None)
    monkeypatch.setattr(
        mesh_gate_mls,
        "remove_gate_member",
        lambda *_args, **_kwargs: {
            "ok": True,
            "previous_epoch": 4,
            "epoch": 5,
            "previous_valid_through_event_id": "evt-4",
        },
    )
    mesh_reputation.gate_manager.gates["rotation-lab"] = {
        "gate_secret": "old-secret",
        "gate_secret_archive": {},
    }

    result = mesh_reputation.gate_manager.remove_member("rotation-lab", "persona-1", kind="ban")
    snapshot = mesh_metrics.snapshot()

    assert result["ok"] is True
    assert result["gate_secret_rotated"] is True
    assert mesh_reputation.gate_manager.gates["rotation-lab"]["gate_secret"] != "old-secret"
    assert result["gate_secret_archive"]["previous_secret"] == "old-secret"
    assert result["gate_secret_archive"]["previous_valid_through_event_id"] == "evt-4"
    assert result["gate_secret_archive"]["previous_valid_through_epoch"] == 4
    assert snapshot["timers"]["ban_rotation_latency_ms"]["count"] == 1.0
    assert result["ban_rotation_p99_budget_ms"] == mesh_reputation.BAN_ROTATION_P99_BUDGET_MS


def test_leave_does_not_rotate_gate_secret(monkeypatch):
    from services.config import get_settings
    from services.mesh import mesh_reputation
    from services.mesh import mesh_gate_mls

    monkeypatch.setenv("MESH_GATE_BAN_KICK_ROTATION_ENABLE", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(mesh_reputation.gate_manager, "_save", lambda: None)
    monkeypatch.setattr(
        mesh_gate_mls,
        "remove_gate_member",
        lambda *_args, **_kwargs: {
            "ok": True,
            "previous_epoch": 4,
            "epoch": 5,
            "previous_valid_through_event_id": "evt-4",
        },
    )
    mesh_reputation.gate_manager.gates["leave-lab"] = {
        "gate_secret": "leave-secret",
        "gate_secret_archive": {},
    }

    result = mesh_reputation.gate_manager.remove_member("leave-lab", "persona-1", kind="leave")

    assert result["ok"] is True
    assert result["gate_secret_rotated"] is False
    assert mesh_reputation.gate_manager.gates["leave-lab"]["gate_secret"] == "leave-secret"
    assert result["gate_secret_archive"]["previous_secret"] == ""


def test_gate_envelope_decrypt_accepts_previous_secret_before_rotation_ceiling(monkeypatch):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    from services.mesh import mesh_gate_mls, mesh_reputation

    class _ArchiveGateManager:
        def __init__(self):
            self.current_secret = "current-secret"
            self.archive = {
                "previous_secret": "previous-secret",
                "previous_valid_through_event_id": "evt-4",
                "previous_valid_through_epoch": 4,
                "rotated_at": 1.0,
                "reason": "ban",
            }

        def get_gate_secret(self, _gate_id: str) -> str:
            return self.current_secret

        def ensure_gate_secret(self, _gate_id: str) -> str:
            return self.current_secret

        def get_gate_secret_archive(self, _gate_id: str) -> dict:
            return dict(self.archive)

    monkeypatch.setattr(mesh_reputation, "gate_manager", _ArchiveGateManager(), raising=False)

    gate_id = "archive-lab"
    message_nonce = "nonce-1"
    plaintext = "pre-rotation envelope"
    nonce = os.urandom(12)
    aad = f"gate_envelope|{gate_id}|{message_nonce}".encode("utf-8")
    ct = AESGCM(
        mesh_gate_mls._gate_envelope_key_scoped(
            gate_id,
            "previous-secret",
            message_nonce=message_nonce,
        )
    ).encrypt(nonce, plaintext.encode("utf-8"), aad)
    token = base64.b64encode(nonce + ct).decode("ascii")

    decrypted = mesh_gate_mls._gate_envelope_decrypt(
        gate_id,
        token,
        message_nonce=message_nonce,
        message_epoch=4,
        event_id="evt-4",
    )
    rejected = mesh_gate_mls._gate_envelope_decrypt(
        gate_id,
        token,
        message_nonce=message_nonce,
        message_epoch=5,
        event_id="evt-5",
    )

    assert decrypted == plaintext
    assert rejected is None


def test_ban_rotation_preserves_pre_rotation_recovery_reads(tmp_path, monkeypatch):
    from services.mesh import mesh_metrics

    gate_mls, persona_mod, gate_manager = _fresh_real_gate_state(tmp_path, monkeypatch)
    gate_id = "rotation-int"
    gate_manager.gates[gate_id] = {
        "creator_node_id": "node-creator",
        "display_name": gate_id,
        "description": "",
        "rules": {"min_overall_rep": 0, "min_gate_rep": {}},
        "created_at": 1,
        "message_count": 0,
        "fixed": False,
        "sort_order": 1000,
        "gate_secret": "rotation-secret-v1",
        "gate_secret_archive": {},
        "envelope_policy": "envelope_recovery",
        "envelope_always_acknowledged": False,
        "legacy_envelope_fallback": False,
    }
    mesh_metrics.reset()

    first = persona_mod.create_gate_persona(gate_id, label="first")
    second = persona_mod.create_gate_persona(gate_id, label="second")
    persona_mod.activate_gate_persona(gate_id, first["identity"]["persona_id"])
    composed = gate_mls.compose_encrypted_gate_message(gate_id, "pre-rotation envelope")

    result = gate_manager.remove_member(gate_id, second["identity"]["node_id"], kind="ban")
    decrypted = gate_mls.decrypt_gate_message_for_local_identity(
        gate_id=gate_id,
        epoch=int(composed["epoch"]),
        ciphertext=str(composed["ciphertext"]),
        nonce=str(composed["nonce"]),
        sender_ref=str(composed["sender_ref"]),
        gate_envelope=str(composed["gate_envelope"]),
        envelope_hash=str(composed["envelope_hash"]),
        recovery_envelope=True,
        event_id="evt-pre-rotation",
    )

    assert result["ok"] is True
    assert result["gate_secret_rotated"] is True
    assert result["gate_secret_archive"]["previous_valid_through_epoch"] == int(composed["epoch"])
    assert decrypted["ok"] is True
    assert decrypted["plaintext"] == "pre-rotation envelope"


def test_leave_removal_does_not_rotate_secret_integration(tmp_path, monkeypatch):
    gate_mls, persona_mod, gate_manager = _fresh_real_gate_state(tmp_path, monkeypatch)
    gate_id = "leave-int"
    gate_manager.gates[gate_id] = {
        "creator_node_id": "node-creator",
        "display_name": gate_id,
        "description": "",
        "rules": {"min_overall_rep": 0, "min_gate_rep": {}},
        "created_at": 1,
        "message_count": 0,
        "fixed": False,
        "sort_order": 1000,
        "gate_secret": "leave-secret-v1",
        "gate_secret_archive": {},
        "envelope_policy": "envelope_recovery",
        "envelope_always_acknowledged": False,
        "legacy_envelope_fallback": False,
    }

    first = persona_mod.create_gate_persona(gate_id, label="first")
    second = persona_mod.create_gate_persona(gate_id, label="second")
    persona_mod.activate_gate_persona(gate_id, first["identity"]["persona_id"])
    _ = gate_mls.compose_encrypted_gate_message(gate_id, "leave path")

    result = gate_manager.remove_member(gate_id, second["identity"]["node_id"], kind="leave")

    assert result["ok"] is True
    assert result["gate_secret_rotated"] is False
    assert gate_manager.gates[gate_id]["gate_secret"] == "leave-secret-v1"
