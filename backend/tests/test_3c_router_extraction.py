"""Sprint 3C/3D: Router Extraction Verification — regression tests.

Covers invariants established by the router extraction from main.py:
1. gate_peer_pull calls _verify_peer_push_hmac (HMAC enforcement).
2. mesh_peer_sync.py imports _verify_peer_push_hmac from auth, not main.
3. All 13 router modules have no module-level import of main.
4. Router modules do not import sync_wormhole_with_settings or shutdown_wormhole_supervisor.
5. No duplicate peer-sync handlers in mesh_public.py (Sprint 3D canonicalization).
6. Router registration order: mesh_peer_sync before mesh_public, mesh_operator before mesh_public.
"""

import ast
import inspect
import os


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_backend_source(filename: str) -> str:
    path = os.path.join(os.path.dirname(__file__), "..", filename)
    with open(os.path.normpath(path), encoding="utf-8") as fh:
        return fh.read()


def _read_router_source(router_name: str) -> str:
    return _read_backend_source(os.path.join("routers", router_name))


_ROUTER_FILES = [
    "mesh_public.py",
    "wormhole.py",
    "mesh_dm.py",
    "data.py",
    "mesh_oracle.py",
    "tools.py",
    "cctv.py",
    "mesh_peer_sync.py",
    "mesh_operator.py",
    "admin.py",
    "radio.py",
    "health.py",
    "sigint.py",
]


# ---------------------------------------------------------------------------
# 1. gate_peer_pull calls _verify_peer_push_hmac
# ---------------------------------------------------------------------------

class TestGatePeerPullHmacEnforcement:
    """gate_peer_pull must call _verify_peer_push_hmac before processing."""

    def test_gate_peer_pull_calls_verify_hmac_in_mesh_peer_sync(self):
        source = _read_router_source("mesh_peer_sync.py")
        # Find the gate_peer_pull function and verify it contains the HMAC check
        assert "def gate_peer_pull" in source, (
            "mesh_peer_sync.py must define gate_peer_pull"
        )
        # Extract gate_peer_pull function source via AST
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == "gate_peer_pull":
                    func_source = ast.get_source_segment(source, node)
                    assert "_verify_peer_push_hmac" in func_source, (
                        "gate_peer_pull in mesh_peer_sync.py must call "
                        "_verify_peer_push_hmac before processing"
                    )
                    return
        raise AssertionError("gate_peer_pull function not found in mesh_peer_sync.py AST")

    def test_gate_peer_pull_hmac_before_body_parse(self):
        """_verify_peer_push_hmac must be called before json parsing of the body."""
        source = _read_router_source("mesh_peer_sync.py")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == "gate_peer_pull":
                    func_source = ast.get_source_segment(source, node)
                    hmac_pos = func_source.find("_verify_peer_push_hmac")
                    json_pos = func_source.find("json_mod.loads")
                    assert hmac_pos < json_pos, (
                        "HMAC verification must occur before JSON body parsing "
                        "in gate_peer_pull"
                    )
                    return


# ---------------------------------------------------------------------------
# 2. mesh_peer_sync.py imports _verify_peer_push_hmac from auth
# ---------------------------------------------------------------------------

class TestPeerSyncHmacImportSource:
    """_verify_peer_push_hmac must be imported from auth in mesh_peer_sync.py."""

    def test_verify_peer_push_hmac_imported_from_auth(self):
        source = _read_router_source("mesh_peer_sync.py")
        # Check for 'from auth import ... _verify_peer_push_hmac'
        tree = ast.parse(source)
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "auth":
                names = [alias.name for alias in node.names]
                if "_verify_peer_push_hmac" in names:
                    found = True
                    break
        assert found, (
            "mesh_peer_sync.py must import _verify_peer_push_hmac from auth, "
            "not from main or any other module"
        )

    def test_verify_peer_push_hmac_not_from_main(self):
        """The HMAC verifier must not be imported via main or _main_delegate."""
        source = _read_router_source("mesh_peer_sync.py")
        assert '_main_delegate("_verify_peer_push_hmac")' not in source, (
            "_verify_peer_push_hmac must be imported directly from auth, "
            "not delegated through main"
        )


# ---------------------------------------------------------------------------
# 3. No module-level import of main in any router module
# ---------------------------------------------------------------------------

class TestRouterNoModuleLevelMainImport:
    """All 13 router modules must not import main at module level.

    `import main` is allowed only inside _main_delegate wrappers or
    function bodies (lazy imports), never at the top of the file.
    """

    def test_no_module_level_main_import(self):
        for router_file in _ROUTER_FILES:
            source = _read_router_source(router_file)
            tree = ast.parse(source)
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert alias.name != "main", (
                            f"{router_file} has a module-level 'import main' "
                            f"at line {node.lineno}"
                        )
                if isinstance(node, ast.ImportFrom):
                    assert node.module != "main", (
                        f"{router_file} has a module-level 'from main import' "
                        f"at line {node.lineno}"
                    )


# ---------------------------------------------------------------------------
# 4. Router modules do not import wormhole supervisor lifecycle functions
# ---------------------------------------------------------------------------

class TestNoSupervisorLeakIntoRouters:
    """sync_wormhole_with_settings and shutdown_wormhole_supervisor must not
    appear in any router module. These are lifecycle functions that belong
    exclusively in main.py's lifespan management."""

    def test_no_sync_wormhole_with_settings(self):
        for router_file in _ROUTER_FILES:
            source = _read_router_source(router_file)
            assert "sync_wormhole_with_settings" not in source, (
                f"{router_file} must not reference sync_wormhole_with_settings"
            )

    def test_no_shutdown_wormhole_supervisor(self):
        for router_file in _ROUTER_FILES:
            source = _read_router_source(router_file)
            assert "shutdown_wormhole_supervisor" not in source, (
                f"{router_file} must not reference shutdown_wormhole_supervisor"
            )


# ---------------------------------------------------------------------------
# 5. No duplicate peer-sync handlers in mesh_public.py (Sprint 3D)
# ---------------------------------------------------------------------------

class TestNoDuplicatePeerSyncInMeshPublic:
    """mesh_public.py must NOT define infonet_peer_push, gate_peer_push, or
    gate_peer_pull. These handlers are canonically owned by mesh_peer_sync.py.

    Sprint 3D removed the duplicates. This class guards against re-introduction.
    """

    _PEER_SYNC_HANDLERS = ["infonet_peer_push", "gate_peer_push", "gate_peer_pull"]

    def test_no_peer_sync_handler_definitions_in_mesh_public(self):
        source = _read_router_source("mesh_public.py")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert node.name not in self._PEER_SYNC_HANDLERS, (
                    f"mesh_public.py must not define {node.name} — "
                    f"peer-sync handlers belong in mesh_peer_sync.py"
                )

    def test_no_peer_sync_route_decorators_in_mesh_public(self):
        """Ensure no @router route paths for the peer-sync endpoints exist."""
        source = _read_router_source("mesh_public.py")
        peer_sync_paths = [
            "/api/mesh/infonet/peer-push",
            "/api/mesh/gate/peer-push",
            "/api/mesh/gate/peer-pull",
        ]
        for path in peer_sync_paths:
            assert path not in source, (
                f"mesh_public.py must not contain route path {path} — "
                f"peer-sync routes belong in mesh_peer_sync.py"
            )

    def test_verify_peer_push_hmac_not_imported_in_mesh_public(self):
        """With peer-sync handlers removed, mesh_public.py should not import
        _verify_peer_push_hmac (no remaining call sites)."""
        source = _read_router_source("mesh_public.py")
        assert "_verify_peer_push_hmac" not in source, (
            "mesh_public.py should not reference _verify_peer_push_hmac "
            "after peer-sync handler removal"
        )

    def test_canonical_handlers_exist_in_mesh_peer_sync(self):
        """All three peer-sync handlers must be defined in mesh_peer_sync.py."""
        source = _read_router_source("mesh_peer_sync.py")
        tree = ast.parse(source)
        defined = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in self._PEER_SYNC_HANDLERS:
                    defined.add(node.name)
        missing = set(self._PEER_SYNC_HANDLERS) - defined
        assert not missing, (
            f"mesh_peer_sync.py must define all peer-sync handlers. "
            f"Missing: {missing}"
        )


# ---------------------------------------------------------------------------
# 6. Router registration order invariants
# ---------------------------------------------------------------------------

class TestRouterRegistrationOrder:
    """mesh_peer_sync_router must be registered before mesh_public_router,
    and mesh_operator_router must be registered before mesh_public_router.

    FastAPI matches routes in registration order. If these orderings are
    violated, the wrong handler may serve peer-sync or operator routes.
    """

    def test_registration_order_peer_sync_before_public(self):
        source = _read_backend_source("main.py")
        peer_sync_pos = source.find("include_router(mesh_peer_sync_router")
        public_pos = source.find("include_router(mesh_public_router")
        assert peer_sync_pos != -1, (
            "main.py must register mesh_peer_sync_router"
        )
        assert public_pos != -1, (
            "main.py must register mesh_public_router"
        )
        assert peer_sync_pos < public_pos, (
            "mesh_peer_sync_router must be registered before mesh_public_router "
            "so HMAC-protected peer-sync routes take priority"
        )

    def test_registration_order_operator_before_public(self):
        source = _read_backend_source("main.py")
        operator_pos = source.find("include_router(mesh_operator_router")
        public_pos = source.find("include_router(mesh_public_router")
        assert operator_pos != -1, (
            "main.py must register mesh_operator_router"
        )
        assert public_pos != -1, (
            "main.py must register mesh_public_router"
        )
        assert operator_pos < public_pos, (
            "mesh_operator_router must be registered before mesh_public_router "
            "so operator routes (require_local_operator) take priority"
        )
