"""Sprint 3D: Peer-Sync Canonicalization — regression tests.

Verifies that mesh_peer_sync.py is the single canonical source of truth for
peer-sync handlers, and that all HMAC enforcement, import sources, and
routing invariants hold after removing duplicates from mesh_public.py.
"""

import ast
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


_PEER_SYNC_HANDLERS = ["infonet_peer_push", "gate_peer_push", "gate_peer_pull"]

_PEER_SYNC_PATHS = [
    "/api/mesh/infonet/peer-push",
    "/api/mesh/gate/peer-push",
    "/api/mesh/gate/peer-pull",
]


# ---------------------------------------------------------------------------
# 1. Canonical peer-sync router owns all peer-sync handlers
# ---------------------------------------------------------------------------

class TestCanonicalPeerSyncOwnership:
    """mesh_peer_sync.py must define all three peer-sync handlers."""

    def test_all_peer_sync_handlers_defined(self):
        source = _read_router_source("mesh_peer_sync.py")
        tree = ast.parse(source)
        defined = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in _PEER_SYNC_HANDLERS:
                    defined.add(node.name)
        missing = set(_PEER_SYNC_HANDLERS) - defined
        assert not missing, (
            f"mesh_peer_sync.py must define all peer-sync handlers. "
            f"Missing: {missing}"
        )

    def test_all_peer_sync_route_paths_present(self):
        source = _read_router_source("mesh_peer_sync.py")
        for path in _PEER_SYNC_PATHS:
            assert path in source, (
                f"mesh_peer_sync.py must contain route path {path}"
            )


# ---------------------------------------------------------------------------
# 2. No duplicate peer-sync route definitions remain in mesh_public.py
# ---------------------------------------------------------------------------

class TestNoDuplicatesInMeshPublic:
    """mesh_public.py must not define any peer-sync handlers or routes."""

    def test_no_peer_sync_function_definitions(self):
        source = _read_router_source("mesh_public.py")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert node.name not in _PEER_SYNC_HANDLERS, (
                    f"mesh_public.py must not define {node.name} — "
                    f"peer-sync handlers are canonical in mesh_peer_sync.py"
                )

    def test_no_peer_sync_route_paths(self):
        source = _read_router_source("mesh_public.py")
        for path in _PEER_SYNC_PATHS:
            assert path not in source, (
                f"mesh_public.py must not contain route path {path}"
            )


# ---------------------------------------------------------------------------
# 3. gate_peer_pull remains explicitly HMAC-guarded
# ---------------------------------------------------------------------------

class TestGatePeerPullHmacGuard:
    """gate_peer_pull must call _verify_peer_push_hmac before processing."""

    def test_gate_peer_pull_calls_verify_hmac(self):
        source = _read_router_source("mesh_peer_sync.py")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == "gate_peer_pull":
                    func_source = ast.get_source_segment(source, node)
                    assert "_verify_peer_push_hmac" in func_source, (
                        "gate_peer_pull must call _verify_peer_push_hmac"
                    )
                    return
        raise AssertionError("gate_peer_pull not found in mesh_peer_sync.py")

    def test_hmac_check_before_json_parse(self):
        source = _read_router_source("mesh_peer_sync.py")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == "gate_peer_pull":
                    func_source = ast.get_source_segment(source, node)
                    hmac_pos = func_source.find("_verify_peer_push_hmac")
                    json_pos = func_source.find("json_mod.loads")
                    assert hmac_pos != -1 and json_pos != -1, (
                        "gate_peer_pull must contain both HMAC check and JSON parse"
                    )
                    assert hmac_pos < json_pos, (
                        "HMAC verification must precede JSON body parsing"
                    )
                    return


# ---------------------------------------------------------------------------
# 4. Peer-push routes remain explicitly HMAC-guarded
# ---------------------------------------------------------------------------

class TestPeerPushHmacGuard:
    """infonet_peer_push and gate_peer_push must call _verify_peer_push_hmac."""

    def test_infonet_peer_push_calls_verify_hmac(self):
        source = _read_router_source("mesh_peer_sync.py")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == "infonet_peer_push":
                    func_source = ast.get_source_segment(source, node)
                    assert "_verify_peer_push_hmac" in func_source, (
                        "infonet_peer_push must call _verify_peer_push_hmac"
                    )
                    return
        raise AssertionError("infonet_peer_push not found in mesh_peer_sync.py")

    def test_gate_peer_push_calls_verify_hmac(self):
        source = _read_router_source("mesh_peer_sync.py")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == "gate_peer_push":
                    func_source = ast.get_source_segment(source, node)
                    assert "_verify_peer_push_hmac" in func_source, (
                        "gate_peer_push must call _verify_peer_push_hmac"
                    )
                    return
        raise AssertionError("gate_peer_push not found in mesh_peer_sync.py")

    def test_hmac_imported_from_auth_not_main(self):
        """_verify_peer_push_hmac must be imported directly from auth."""
        source = _read_router_source("mesh_peer_sync.py")
        tree = ast.parse(source)
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "auth":
                names = [alias.name for alias in node.names]
                if "_verify_peer_push_hmac" in names:
                    found = True
                    break
        assert found, (
            "_verify_peer_push_hmac must be imported from auth in mesh_peer_sync.py"
        )
        assert '_main_delegate("_verify_peer_push_hmac")' not in source, (
            "_verify_peer_push_hmac must not use _main_delegate indirection"
        )


# ---------------------------------------------------------------------------
# 5. mesh_peer_sync.py has no _main_delegate coupling
# ---------------------------------------------------------------------------

class TestNoMainDelegateInPeerSync:
    """mesh_peer_sync.py should not use _main_delegate at all — it imports
    everything it needs directly from auth and services."""

    def test_no_main_delegate_definition(self):
        source = _read_router_source("mesh_peer_sync.py")
        assert "_main_delegate" not in source, (
            "mesh_peer_sync.py must not use _main_delegate — "
            "all imports should be direct"
        )

    def test_no_module_level_main_import(self):
        source = _read_router_source("mesh_peer_sync.py")
        tree = ast.parse(source)
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "main", (
                        "mesh_peer_sync.py must not import main at module level"
                    )
            if isinstance(node, ast.ImportFrom):
                assert node.module != "main", (
                    "mesh_peer_sync.py must not import from main at module level"
                )


# ---------------------------------------------------------------------------
# 6. Registration order still correct (safety net)
# ---------------------------------------------------------------------------

class TestRegistrationOrder:
    """mesh_peer_sync_router must still be registered before mesh_public_router.

    While peer-sync routes no longer exist in mesh_public.py, maintaining
    this order is a defense-in-depth measure against accidental re-introduction.
    """

    def test_peer_sync_before_public(self):
        source = _read_backend_source("main.py")
        peer_sync_pos = source.find("include_router(mesh_peer_sync_router")
        public_pos = source.find("include_router(mesh_public_router")
        assert peer_sync_pos != -1, "main.py must register mesh_peer_sync_router"
        assert public_pos != -1, "main.py must register mesh_public_router"
        assert peer_sync_pos < public_pos, (
            "mesh_peer_sync_router must be registered before mesh_public_router"
        )
