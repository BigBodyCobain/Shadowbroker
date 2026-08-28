"""Release wiring for the QazPipe/QazLake convergence must not drift."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_production_compose_passes_convergence_runtime_configuration() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    required = (
        "MESH_PEER_PUSH_SECRET_PREVIOUS=${MESH_PEER_PUSH_SECRET_PREVIOUS:-}",
        "SHADOW_LAYER_SOURCE_MODES=${SHADOW_LAYER_SOURCE_MODES:-}",
        "QAZLAKE_SHADOW_FEED_URL=${QAZLAKE_SHADOW_FEED_URL:-}",
        "QAZLAKE_SHADOW_FEED_TOKEN=${QAZLAKE_SHADOW_FEED_TOKEN:-}",
        "QAZLAKE_SHADOW_POLL_INTERVAL_S=${QAZLAKE_SHADOW_POLL_INTERVAL_S:-30}",
        "SHADOW_DERIVED_SIGNALS_TOKEN=${SHADOW_DERIVED_SIGNALS_TOKEN:-}",
    )

    for setting in required:
        assert setting in compose


def test_example_environment_documents_dedicated_credentials() -> None:
    example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "# QAZLAKE_SHADOW_FEED_TOKEN=" in example
    assert "# SHADOW_DERIVED_SIGNALS_TOKEN=" in example
    assert "# MESH_PEER_PUSH_SECRET_PREVIOUS=" in example
