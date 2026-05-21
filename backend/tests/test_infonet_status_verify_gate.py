"""Issue #207 (tg12): /api/mesh/infonet/status accepted
?verify_signatures=true from anonymous callers, triggering O(n_events)
signature verification across the entire chain. Trivial DoS.

The fix silently downgrades the parameter to False for unauthenticated
callers — no error surfaced, response structure unchanged, the
expensive path runs only when the caller has authenticated.

These tests focus on the source-level contract because a full
FastAPI test client doesn't have an easy hook into the ``_scoped_view_authenticated``
helper. They lock in the key invariant: the ``effective_verify_signatures``
value seen by ``validate_chain()`` is the AND of the request param and
the auth check.
"""
from pathlib import Path


_ROUTER_PATH = Path(__file__).resolve().parent.parent / "routers" / "mesh_public.py"


def _read_router_source() -> str:
    return _ROUTER_PATH.read_text(encoding="utf-8")


def test_infonet_status_gates_verify_signatures():
    """The infonet_status route must AND verify_signatures with auth."""
    src = _read_router_source()
    # The fix introduces an `effective_verify_signatures` variable.
    assert "effective_verify_signatures" in src

    # It must be computed as the AND of the request param and the
    # authenticated check.
    assert "bool(verify_signatures) and authenticated" in src

    # validate_chain() must be called with the effective value, NOT the
    # raw request param.
    assert "validate_chain(verify_signatures=effective_verify_signatures)" in src


def test_no_http_error_path_for_anonymous_callers():
    """No HTTPException is raised for unauthenticated verify_signatures=true.

    The endpoint should silently downgrade — not return 403 — so existing
    frontends that happen to pass the param see no behavior change.
    """
    src = _read_router_source()
    # Within the infonet_status function body, there should be no
    # HTTPException(403) raised because of the verify_signatures param.
    # Find the function definition and inspect the body.
    import re
    m = re.search(
        r"async def infonet_status\(.*?\):(.+?)(?=\n@router|\nasync def |\ndef |\Z)",
        src,
        re.DOTALL,
    )
    assert m, "infonet_status function not found in source"
    body = m.group(1)
    # No explicit 403 around the verify_signatures handling.
    assert "HTTPException(status_code=403" not in body
    assert "raise HTTPException(403" not in body
