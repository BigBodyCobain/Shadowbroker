import json
from pathlib import Path

from services.mesh.mesh_merkle import merkle_root, verify_merkle_proof


def test_merkle_fixtures() -> None:
    root_dir = Path(__file__).resolve().parents[3]
    fixture_path = root_dir / "docs" / "mesh" / "mesh-merkle-fixtures.json"
    fixtures = json.loads(fixture_path.read_text(encoding="utf-8"))

    leaves = fixtures["leaves"]
    root = fixtures["root"]
    assert merkle_root(leaves) == root

    for idx_str, proof in fixtures["proofs"].items():
        idx = int(idx_str)
        assert verify_merkle_proof(leaves[idx], idx, proof, root)
