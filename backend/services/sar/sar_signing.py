"""SAR anomaly mesh signing.

When the local node is at a high enough trust tier, every SAR anomaly
emitted by the layer is wrapped in a signed mesh event so other nodes
can verify the publisher and the evidence_hash lineage.

This reuses the existing signing pipeline rather than inventing a new
one — the audit identified domain-separated signing as load-bearing for
the rest of the mesh, and the SAR layer is required to honor that.
"""

from __future__ import annotations

import logging
from typing import Any

from services.sar.sar_config import require_private_tier_for_publish
from services.sar.sar_normalize import SarAnomaly

logger = logging.getLogger(__name__)


_PRIVATE_TIERS = {"private_transitional", "private_strong"}


def _current_transport_tier() -> str:
    try:
        from services.wormhole_supervisor import get_transport_tier
        return str(get_transport_tier() or "")
    except Exception:
        return ""


def can_publish_signed(anomaly: SarAnomaly | None = None) -> tuple[bool, str]:
    """Check whether the local node may publish a signed SAR anomaly.

    Returns ``(allowed, reason)``.  Caller decides whether to skip the
    publish entirely or fall back to a local-only write.
    """
    if not require_private_tier_for_publish():
        return True, "tier gate disabled"
    tier = _current_transport_tier()
    if tier in _PRIVATE_TIERS:
        return True, f"tier={tier}"
    return False, (
        f"tier={tier or 'unknown'} — SAR anomalies require private_transitional "
        f"or higher to be signed and broadcast"
    )


def build_signed_payload(anomaly: SarAnomaly) -> dict[str, Any]:
    """Build the canonical payload that goes into the signed event body.

    The shape mirrors normalize_sar_anomaly_payload in mesh_protocol so
    the verifier sees exactly what the signer signed.
    """
    return {
        "anomaly_id": anomaly.anomaly_id,
        "kind": anomaly.kind,
        "lat": anomaly.lat,
        "lon": anomaly.lon,
        "magnitude": anomaly.magnitude,
        "magnitude_unit": anomaly.magnitude_unit,
        "confidence": anomaly.confidence,
        "first_seen": anomaly.first_seen,
        "last_seen": anomaly.last_seen,
        "stack_id": anomaly.aoi_id,
        "scene_count": anomaly.scene_count,
        "evidence_hash": anomaly.evidence_hash,
        "solver": anomaly.solver,
        "source_constellation": anomaly.source_constellation,
    }


def emit_signed_anomaly(anomaly: SarAnomaly) -> dict[str, Any]:
    """Best-effort signed-event emission for a SAR anomaly.

    Falls back gracefully when the mesh signing infrastructure is not
    available — the layer never fails just because the mesh is offline.
    Returns a status dict for diagnostics.
    """
    allowed, reason = can_publish_signed(anomaly)
    if not allowed:
        return {"signed": False, "reason": reason}

    payload = build_signed_payload(anomaly)
    try:
        from services.mesh.mesh_protocol import normalize_payload
        normalized = normalize_payload("sar_anomaly", payload)
    except Exception as exc:
        logger.debug("SAR signed publish failed at normalize: %s", exc)
        return {"signed": False, "reason": f"normalize_failed:{exc}"}

    # Sign + hashchain via the same path the rest of the mesh uses.  We
    # do this lazily so a node without mesh infra can still run the SAR
    # layer in local-only mode.
    try:
        from services.mesh.mesh_hashchain import infonet
        from services.mesh.mesh_wormhole_persona import sign_root_wormhole_event

        signed = sign_root_wormhole_event(
            event_type="sar_anomaly",
            payload=normalized,
        )
        if signed:
            try:
                infonet.append_signed_event(signed)
            except Exception:
                # append is best-effort; the local layer still has the data.
                pass
        return {
            "signed": True,
            "reason": reason,
            "node_id": signed.get("node_id", ""),
            "sequence": signed.get("sequence", 0),
        }
    except Exception as exc:
        logger.debug("SAR signed publish failed at sign: %s", exc)
        return {"signed": False, "reason": f"sign_failed:{exc}"}
