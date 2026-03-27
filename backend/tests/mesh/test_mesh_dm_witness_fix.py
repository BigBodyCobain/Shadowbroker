"""Tests verifying the /api/mesh/dm/witness endpoint uses correct identifiers.

The bug: _preflight_signed_event_integrity was called with event_type="trust_vouch"
and node_id=voucher_id (undefined NameError). Fixed to event_type="dm_key_witness"
and node_id=witness_id.
"""

import ast
import textwrap
from pathlib import Path

MAIN_PY = Path(__file__).resolve().parents[2] / "main.py"


def _find_dm_key_witness_func(source: str) -> ast.AsyncFunctionDef | None:
    """Parse main.py AST and find the dm_key_witness POST handler."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "dm_key_witness":
            return node
    return None


def test_witness_endpoint_uses_correct_event_type():
    """The preflight call must use event_type='dm_key_witness', not 'trust_vouch'."""
    source = MAIN_PY.read_text(encoding="utf-8")
    func = _find_dm_key_witness_func(source)
    assert func is not None, "dm_key_witness function not found in main.py"

    # Extract the function source and look for _preflight_signed_event_integrity call
    func_source = ast.get_source_segment(source, func)
    assert func_source is not None

    assert 'event_type="dm_key_witness"' in func_source, (
        "preflight call should use event_type='dm_key_witness', "
        f"but the function contains: {func_source[:500]}"
    )
    assert 'event_type="trust_vouch"' not in func_source, (
        "preflight call still uses the wrong event_type='trust_vouch'"
    )


def test_witness_endpoint_uses_witness_id_not_voucher_id():
    """The preflight call must use node_id=witness_id, not voucher_id."""
    source = MAIN_PY.read_text(encoding="utf-8")
    func = _find_dm_key_witness_func(source)
    assert func is not None, "dm_key_witness function not found in main.py"

    func_source = ast.get_source_segment(source, func)
    assert func_source is not None

    # Find all _preflight_signed_event_integrity calls in the function
    lines = func_source.splitlines()
    in_preflight = False
    preflight_block = []
    for line in lines:
        if "_preflight_signed_event_integrity" in line:
            in_preflight = True
        if in_preflight:
            preflight_block.append(line)
            if ")" in line and line.strip().endswith(")"):
                break

    preflight_text = "\n".join(preflight_block)
    assert "node_id=witness_id" in preflight_text, (
        f"preflight call should use node_id=witness_id, got:\n{preflight_text}"
    )
    assert "node_id=voucher_id" not in preflight_text, (
        "preflight call still references undefined voucher_id"
    )


def test_verify_signed_event_also_uses_dm_key_witness():
    """The _verify_signed_event call should also use event_type='dm_key_witness'."""
    source = MAIN_PY.read_text(encoding="utf-8")
    func = _find_dm_key_witness_func(source)
    assert func is not None

    func_source = ast.get_source_segment(source, func)
    assert func_source is not None

    # Count occurrences of the correct event_type
    assert func_source.count('event_type="dm_key_witness"') == 2, (
        "Both _verify_signed_event and _preflight_signed_event_integrity "
        "should use event_type='dm_key_witness'"
    )
