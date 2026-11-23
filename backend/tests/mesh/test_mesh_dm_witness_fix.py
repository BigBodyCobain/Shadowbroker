"""Tests for /api/mesh/dm/witness handler invariants.

These are source-shape guards: the endpoint is intentionally lightweight
(no preflight signature verification) but must keep its core validation and
recording behavior.
"""

import ast
from pathlib import Path

MAIN_PY = Path(__file__).resolve().parents[2] / "main.py"


def _find_dm_key_witness_func(source: str) -> ast.AsyncFunctionDef | None:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "dm_key_witness":
            return node
    return None


def _func_source() -> str:
    source = MAIN_PY.read_text(encoding="utf-8")
    func = _find_dm_key_witness_func(source)
    assert func is not None, "dm_key_witness function not found in main.py"
    func_source = ast.get_source_segment(source, func)
    assert func_source is not None
    return func_source


def test_witness_endpoint_validates_timestamp_window():
    src = _func_source()
    assert "abs(timestamp - now_ts) > 7 * 86400" in src


def test_witness_endpoint_validates_dm_witness_sequence_domain():
    src = _func_source()
    assert 'domain="dm_witness"' in src


def test_witness_endpoint_records_witness():
    src = _func_source()
    assert "dm_relay.record_witness(" in src
    assert "witness_id, target_id, dh_pub_key, timestamp" in src
