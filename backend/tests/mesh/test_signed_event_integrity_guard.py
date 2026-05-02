import ast
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[2]
HANDLER_MODULES = [
    BACKEND_DIR / "main.py",
    BACKEND_DIR / "routers" / "mesh_dm.py",
    BACKEND_DIR / "routers" / "mesh_public.py",
    BACKEND_DIR / "routers" / "mesh_oracle.py",
]
WRITE_METHODS = {"post", "put", "patch", "delete"}
ALLOWED_EXEMPTIONS = {"PEER_GOSSIP", "ADMIN_CONTROL", "LOCAL_OPERATOR_ONLY"}
FORBIDDEN_ROUTE_HELPERS = {
    "_verify_signed_event",
    "_preflight_signed_event_integrity",
    "verify_signed_event",
    "preflight_signed_event_integrity",
    "_verify_signed_write",
    "verify_signed_write",
    "_verify_gate_message_signed_write",
    "verify_gate_message_signed_write",
}


def _verify_signature_call_lines(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id == "verify_signature":
            lines.append(node.lineno)
        elif isinstance(node.func, ast.Attribute) and node.func.attr == "verify_signature":
            lines.append(node.lineno)
    return sorted(lines)


def _route_decorators(node: ast.AST) -> list[ast.Call]:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return []
    return [
        decorator
        for decorator in node.decorator_list
        if isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Attribute)
        and decorator.func.attr in {"get", "post", "put", "patch", "delete"}
    ]


def _mesh_write_route(node: ast.AST) -> bool:
    for decorator in _route_decorators(node):
        if decorator.func.attr not in WRITE_METHODS or not decorator.args:
            continue
        first_arg = decorator.args[0]
        if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
            if first_arg.value.startswith("/api/mesh/"):
                return True
    return False


def _has_named_decorator(node: ast.AST, name: str) -> bool:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Call):
            func = decorator.func
            if isinstance(func, ast.Name) and func.id == name:
                return True
            if isinstance(func, ast.Attribute) and func.attr == name:
                return True
    return False


def _exemption_value(node: ast.AST) -> str | None:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return None
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        func = decorator.func
        func_name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if func_name != "mesh_write_exempt" or len(decorator.args) != 1:
            continue
        arg = decorator.args[0]
        if isinstance(arg, ast.Attribute) and isinstance(arg.value, ast.Name) and arg.value.id == "MeshWriteExemption":
            return arg.attr
        return "__invalid__"
    return None


def _request_json_call_lines(node: ast.AST) -> list[int]:
    lines: list[int] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        if isinstance(child.func, ast.Attribute) and child.func.attr == "json":
            owner = child.func.value
            if isinstance(owner, ast.Name) and owner.id == "request":
                lines.append(child.lineno)
    return sorted(lines)


def _forbidden_route_helper_lines(node: ast.AST) -> list[int]:
    lines: list[int] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        if isinstance(child.func, ast.Name) and child.func.id in FORBIDDEN_ROUTE_HELPERS:
            lines.append(child.lineno)
        elif isinstance(child.func, ast.Attribute) and child.func.attr in FORBIDDEN_ROUTE_HELPERS:
            lines.append(child.lineno)
    return sorted(lines)


def _mesh_write_contract_report(path: Path) -> dict[str, dict[str, object]]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    report: dict[str, dict[str, object]] = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not _mesh_write_route(node):
            continue
        exemption = _exemption_value(node)
        decorated = _has_named_decorator(node, "requires_signed_write")
        report[node.name] = {
            "decorated": decorated,
            "exemption": exemption,
            "json_lines": _request_json_call_lines(node),
            "forbidden_lines": _forbidden_route_helper_lines(node),
        }
    return report


def test_request_handlers_do_not_call_verify_signature_directly():
    offenders = {
        str(path.relative_to(BACKEND_DIR)): _verify_signature_call_lines(path)
        for path in HANDLER_MODULES
        if _verify_signature_call_lines(path)
    }
    assert not offenders, (
        "Request-handling modules must route signature checks through "
        "services.mesh.mesh_signed_events, not raw verify_signature(). "
        f"Found direct calls: {offenders}"
    )


def test_mesh_write_handlers_are_decorated_or_explicitly_exempt():
    offenders: dict[str, dict[str, dict[str, object]]] = {}
    for path in HANDLER_MODULES:
        report = _mesh_write_contract_report(path)
        missing = {
            name: details
            for name, details in report.items()
            if not details["decorated"] and details["exemption"] is None
        }
        if missing:
            offenders[str(path.relative_to(BACKEND_DIR))] = missing
    assert not offenders, (
        "Every /api/mesh write handler must use @requires_signed_write(...) or "
        "@mesh_write_exempt(MeshWriteExemption.*). "
        f"Missing coverage: {offenders}"
    )


def test_mesh_write_exemptions_use_fixed_enum_reasons():
    offenders: dict[str, dict[str, str]] = {}
    for path in HANDLER_MODULES:
        report = _mesh_write_contract_report(path)
        invalid = {}
        for name, details in report.items():
            exemption = details["exemption"]
            if exemption is None:
                continue
            if exemption not in ALLOWED_EXEMPTIONS:
                invalid[name] = str(exemption)
        if invalid:
            offenders[str(path.relative_to(BACKEND_DIR))] = invalid
    assert not offenders, (
        "mesh_write_exempt must use the fixed MeshWriteExemption enum values only. "
        f"Invalid exemptions: {offenders}"
    )


def test_decorated_mesh_write_handlers_do_not_reparse_request_json():
    offenders: dict[str, dict[str, list[int]]] = {}
    for path in HANDLER_MODULES:
        report = _mesh_write_contract_report(path)
        invalid = {
            name: details["json_lines"]
            for name, details in report.items()
            if details["decorated"] and details["json_lines"]
        }
        if invalid:
            offenders[str(path.relative_to(BACKEND_DIR))] = invalid
    assert not offenders, (
        "Decorated /api/mesh write handlers must not call request.json(); they must "
        "consume the shared signed-write body cache. "
        f"Found reparses: {offenders}"
    )


def test_mesh_write_route_handlers_do_not_inline_signed_verification():
    offenders: dict[str, dict[str, list[int]]] = {}
    for path in HANDLER_MODULES:
        report = _mesh_write_contract_report(path)
        invalid = {
            name: details["forbidden_lines"]
            for name, details in report.items()
            if details["forbidden_lines"]
        }
        if invalid:
            offenders[str(path.relative_to(BACKEND_DIR))] = invalid
    assert not offenders, (
        "Route-decorated /api/mesh write handlers must not inline signed-write "
        "verification helpers. The decorator is the enforcement point. "
        f"Found route bypasses: {offenders}"
    )


def test_ast_guard_self_test_rejects_unmarked_mesh_write(tmp_path):
    path = tmp_path / "fake_mesh_routes.py"
    path.write_text(
        """
from fastapi import APIRouter, Request

router = APIRouter()

@router.post("/api/mesh/fake")
async def fake_write(request: Request):
    return {"ok": True}
""".strip(),
        encoding="utf-8",
    )
    report = _mesh_write_contract_report(path)
    assert report["fake_write"]["decorated"] is False
    assert report["fake_write"]["exemption"] is None


def test_ast_guard_self_test_rejects_free_text_exemption_and_json_reparse(tmp_path):
    path = tmp_path / "fake_mesh_routes.py"
    path.write_text(
        """
from fastapi import APIRouter, Request
from services.mesh.mesh_signed_events import mesh_write_exempt, requires_signed_write

router = APIRouter()

@router.post("/api/mesh/fake-exempt")
@mesh_write_exempt("free_text")
async def fake_exempt(request: Request):
    return {"ok": True}

@router.post("/api/mesh/fake-decorated")
@requires_signed_write(kind="mesh_send")
async def fake_decorated(request: Request):
    body = await request.json()
    return {"ok": bool(body)}
""".strip(),
        encoding="utf-8",
    )
    report = _mesh_write_contract_report(path)
    assert report["fake_exempt"]["exemption"] == "__invalid__"
    assert len(report["fake_decorated"]["json_lines"]) == 1
