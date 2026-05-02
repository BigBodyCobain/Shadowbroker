import ast
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[2]
DEAD_DROP_PATH = BACKEND_DIR / "services" / "mesh" / "mesh_wormhole_dead_drop.py"
CONTACTS_PATH = BACKEND_DIR / "services" / "mesh" / "mesh_wormhole_contacts.py"
EXPECTED_REASONS = {
    "scheduled_30d",
    "contact_verification_completed",
    "gate_join",
    "suspected_compromise",
    "manual",
}


def _literal_reason_keyword_lines(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg != "reason":
                continue
            if isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                lines.append(node.lineno)
    return sorted(lines)


def test_alias_rotation_reason_enum_is_fixed():
    from services.mesh.mesh_wormhole_dead_drop import AliasRotationReason

    assert {reason.value for reason in AliasRotationReason} == EXPECTED_REASONS


def test_alias_rotation_reason_keywords_do_not_use_free_text_literals():
    offenders = {
        str(path.relative_to(BACKEND_DIR)): _literal_reason_keyword_lines(path)
        for path in (DEAD_DROP_PATH, CONTACTS_PATH)
        if _literal_reason_keyword_lines(path)
    }
    assert not offenders, (
        "Alias rotation reasons must come from AliasRotationReason, not string literals. "
        f"Found literal reason keywords at {offenders}."
    )


def test_alias_rotation_reason_guard_self_test_rejects_literal_reason(tmp_path):
    path = tmp_path / "fake_alias_rotation.py"
    path.write_text(
        """
def rotate():
    emit(reason="free_text")
""".strip(),
        encoding="utf-8",
    )

    assert _literal_reason_keyword_lines(path) == [2]
