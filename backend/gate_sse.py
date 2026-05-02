"""gate_sse.py — DEPRECATED. Gate SSE broadcast removed in S3A.

Gate activity is no longer broadcast via SSE. The frontend uses the
authenticated poll loop for gate message refresh.

Stubs are kept so any late imports do not crash at startup.
"""


def _broadcast_gate_events(gate_id: str, events: list[dict]) -> None:  # noqa: ARG001
    """No-op — gate SSE broadcast removed."""
