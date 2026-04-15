import json
from pathlib import Path

from services.mesh.mesh_crypto import build_signature_payload


def test_mesh_canonical_fixtures() -> None:
    root = Path(__file__).resolve().parents[3]
    fixtures_path = root / "docs" / "mesh" / "mesh-canonical-fixtures.json"
    fixtures = json.loads(fixtures_path.read_text(encoding="utf-8"))

    for case in fixtures:
        result = build_signature_payload(
            event_type=case["event_type"],
            node_id=case["node_id"],
            sequence=case["sequence"],
            payload=case["payload"],
        )
        assert result == case["expected"], f"fixture mismatch: {case['name']}"
