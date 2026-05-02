import ast
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[2]
DISPATCHER_PATH = BACKEND_DIR / "services" / "mesh" / "mesh_private_dispatcher.py"
EXPECTED_REASONS = {
    "anonymous_mode_forced_relay",
    "relay_approved_by_user",
    "rns_transport_disabled",
    "rns_peer_unknown",
    "rns_peer_offline",
    "rns_link_down",
    "rns_send_failed_unknown",
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


def test_dm_fallback_reason_enum_is_fixed():
    from services.mesh.mesh_private_dispatcher import DMFallbackReason

    assert {reason.value for reason in DMFallbackReason} == EXPECTED_REASONS


def test_private_dispatcher_reason_keywords_do_not_use_free_text_literals():
    offenders = _literal_reason_keyword_lines(DISPATCHER_PATH)
    assert not offenders, (
        "DM fallback reasons must come from the DMFallbackReason enum, not string literals. "
        f"Found literal reason keywords at lines {offenders}."
    )


def test_private_dispatcher_reason_guard_self_test_rejects_literal_reason(tmp_path):
    path = tmp_path / "fake_dispatcher.py"
    path.write_text(
        """
def emit():
    record(reason="free_text")
""".strip(),
        encoding="utf-8",
    )

    assert _literal_reason_keyword_lines(path) == [2]
