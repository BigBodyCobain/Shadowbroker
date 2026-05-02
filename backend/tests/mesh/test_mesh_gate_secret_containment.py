"""S1 Gate Secret Containment — prove gate_secret never leaks via any gate endpoint."""

import asyncio

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


def _fetch_json(app, path):
    """Hit a GET endpoint through the ASGI app and return the JSON body."""

    async def _run():
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.get(path)
            assert resp.status_code == 200, f"unexpected status {resp.status_code}"
            return resp.json()

    return asyncio.run(_run())


def _assert_no_secret_in_gates(gates):
    for gate in gates:
        assert "gate_secret" not in gate, (
            f"gate_secret leaked for gate '{gate.get('gate_id')}'"
        )


# ── Route-level proof: gate_secret absent from /api/mesh/gate/list ──────


def test_gate_list_never_returns_gate_secret_main():
    import main

    data = _fetch_json(main.app, "/api/mesh/gate/list")
    gates = data["gates"]
    assert len(gates) > 0, "gate catalog should not be empty"
    _assert_no_secret_in_gates(gates)


def test_gate_list_never_returns_gate_secret_router():
    """Test the mesh_public router handler independently on a standalone app."""
    from routers.mesh_public import router

    standalone = FastAPI()
    standalone.include_router(router)

    data = _fetch_json(standalone, "/api/mesh/gate/list")
    gates = data["gates"]
    assert len(gates) > 0, "gate catalog should not be empty"
    _assert_no_secret_in_gates(gates)


# ── Route-level proof: gate_secret absent from /api/mesh/gate/{gate_id} ─


def test_gate_detail_never_returns_gate_secret_main():
    import main

    data = _fetch_json(main.app, "/api/mesh/gate/infonet")
    assert "gate_secret" not in data, "gate_secret leaked from detail endpoint"


def test_gate_detail_never_returns_gate_secret_router():
    """Test the detail route on the mesh_public router independently."""
    from routers.mesh_public import router

    standalone = FastAPI()
    standalone.include_router(router)

    data = _fetch_json(standalone, "/api/mesh/gate/infonet")
    assert "gate_secret" not in data, "gate_secret leaked from router detail endpoint"


# ── Regression: gate catalog still returns normal metadata ──────────────


def test_gate_list_returns_expected_catalog_metadata():
    import main

    data = _fetch_json(main.app, "/api/mesh/gate/list")
    gates = data["gates"]
    assert len(gates) > 0, "gate catalog should not be empty"

    gate_ids = {g["gate_id"] for g in gates}
    for expected in ("infonet", "finance", "prediction-markets"):
        assert expected in gate_ids, f"expected gate '{expected}' missing from catalog"

    required_fields = {
        "gate_id",
        "display_name",
        "description",
        "rules",
        "created_at",
        "fixed",
        "sort_order",
    }
    for gate in gates:
        missing = required_fields - set(gate.keys())
        assert not missing, (
            f"gate '{gate.get('gate_id')}' missing fields: {missing}"
        )


def test_gate_detail_returns_expected_metadata():
    """Regression: /api/mesh/gate/{gate_id} still returns public metadata."""
    import main

    data = _fetch_json(main.app, "/api/mesh/gate/infonet")
    assert data.get("gate_id") == "infonet"
    assert "display_name" in data
    assert "description" in data
    assert "rules" in data
    assert "ratification" in data


# ── Unit-level proof: list_gates and get_gate defaults are safe ─────────


def test_list_gates_default_omits_secrets():
    from services.mesh.mesh_reputation import gate_manager

    gates = gate_manager.list_gates()
    _assert_no_secret_in_gates(gates)


def test_get_gate_omits_secrets():
    from services.mesh.mesh_reputation import gate_manager

    gate = gate_manager.get_gate("infonet")
    assert gate is not None
    assert "gate_secret" not in gate, "get_gate() leaked gate_secret"


def test_list_gates_include_secrets_true_includes_secrets():
    """Sanity: include_secrets=True still works for internal callers."""
    from services.mesh.mesh_reputation import gate_manager

    gates = gate_manager.list_gates(include_secrets=True)
    assert len(gates) > 0
    for gate in gates:
        assert "gate_secret" in gate, (
            f"include_secrets=True should include gate_secret for '{gate.get('gate_id')}'"
        )
