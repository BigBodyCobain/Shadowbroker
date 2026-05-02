from __future__ import annotations

from dataclasses import dataclass
from typing import Any

TRANSPORT_TIER_ORDER = {
    "public_degraded": 0,
    "private_control_only": 1,
    "private_transitional": 2,
    "private_strong": 3,
}

PRIVATE_DELIVERY_STATUS_LABELS = {
    "preparing_private_lane": "Preparing private lane",
    "queued_private_delivery": "Queued for private delivery",
    "delivered_privately": "Delivered privately",
    "weaker_privacy_approval_required": "Needs your approval to send with weaker privacy",
    "sealed_local": "Sealed locally",
    "queued_private_release": "Queued for private release",
    "publishing_private": "Publishing privately",
    "published_private": "Published privately",
    "delivered_private": "Delivered privately",
    "released_private": "Released privately",
    "release_failed": "Private release failed",
}

PRIVATE_LANE_READINESS_LABELS = {
    "preparing_private_lane": "Preparing private lane",
    "private_lane_ready": "Private lane ready",
    "retrying_private_lane": "Retrying private lane",
    "private_lane_unavailable": "Private lane unavailable",
    "weaker_privacy_approval_required": "Needs your approval to send with weaker privacy",
}

@dataclass(frozen=True)
class PrivateLaneSemantics:
    lane: str
    local_operation_tier: str
    queued_acceptance_tier: str
    network_release_tier: str
    content_private: bool


_DEFAULT_LANE_SEMANTICS = PrivateLaneSemantics(
    lane="generic_private",
    local_operation_tier="private_control_only",
    queued_acceptance_tier="public_degraded",
    network_release_tier="private_strong",
    content_private=True,
)

PRIVATE_LANE_SEMANTICS = {
    "dm": PrivateLaneSemantics(
        lane="dm",
        local_operation_tier="private_control_only",
        queued_acceptance_tier="public_degraded",
        network_release_tier="private_strong",
        content_private=True,
    ),
    "gate": PrivateLaneSemantics(
        lane="gate",
        local_operation_tier="private_control_only",
        queued_acceptance_tier="public_degraded",
        # Hardening Rec #4: gate content release now requires private_strong
        # (both Tor and RNS ready), matching the DM lane. Previously
        # private_transitional accepted Tor-only *or* RNS-only, which is still
        # metadata-private per-hop but loses defense-in-depth when one of the
        # two transports is unavailable or compromised. Gate queued_acceptance
        # remains public_degraded so messages can be composed offline and
        # released when the floor is satisfied.
        network_release_tier="private_strong",
        content_private=True,
    ),
    "trust_graph": PrivateLaneSemantics(
        lane="trust_graph",
        local_operation_tier="private_strong",
        queued_acceptance_tier="private_strong",
        network_release_tier="private_strong",
        content_private=True,
    ),
}

RELEASE_LANE_FLOORS = {
    lane: semantics.network_release_tier
    for lane, semantics in PRIVATE_LANE_SEMANTICS.items()
}


@dataclass(frozen=True)
class PrivateReleaseDecision:
    lane: str
    current_tier: str
    required_tier: str
    allowed: bool
    should_queue: bool
    should_bootstrap: bool
    status_code: str
    status_label: str
    reason_code: str
    plain_reason: str


def lane_semantics(lane: str) -> PrivateLaneSemantics:
    return PRIVATE_LANE_SEMANTICS.get(str(lane or "").strip().lower(), _DEFAULT_LANE_SEMANTICS)


def local_operation_required_tier(lane: str) -> str:
    return lane_semantics(lane).local_operation_tier


def queued_acceptance_required_tier(lane: str) -> str:
    return lane_semantics(lane).queued_acceptance_tier


def network_release_required_tier(lane: str) -> str:
    return lane_semantics(lane).network_release_tier


def lane_content_private(lane: str) -> bool:
    return bool(lane_semantics(lane).content_private)


def lane_truth_snapshot(lane: str) -> dict[str, Any]:
    semantics = lane_semantics(lane)
    return {
        "lane": semantics.lane,
        "local_operation_tier": semantics.local_operation_tier,
        "queued_acceptance_tier": semantics.queued_acceptance_tier,
        "network_release_tier": semantics.network_release_tier,
        "content_private": bool(semantics.content_private),
    }


def normalize_transport_tier(value: str | None) -> str:
    candidate = str(value or "").strip().lower()
    return candidate if candidate in TRANSPORT_TIER_ORDER else "public_degraded"


def transport_tier_from_state(state: dict[str, Any] | None) -> str:
    snapshot = state or {}
    if not bool(snapshot.get("configured")):
        return "public_degraded"
    if not bool(snapshot.get("ready")):
        return "public_degraded"
    arti_ready = bool(snapshot.get("arti_ready"))
    rns_ready = bool(snapshot.get("rns_ready"))
    if arti_ready and rns_ready:
        return "private_strong"
    if arti_ready or rns_ready:
        return "private_transitional"
    return "private_control_only"


def transport_tier_is_sufficient(current_tier: str | None, required_tier: str | None) -> bool:
    current = normalize_transport_tier(current_tier)
    required = normalize_transport_tier(required_tier)
    return TRANSPORT_TIER_ORDER[current] >= TRANSPORT_TIER_ORDER[required]


def release_lane_required_tier(lane: str) -> str:
    return network_release_required_tier(lane)


def private_delivery_status(status_code: str, *, reason_code: str = "", plain_reason: str = "") -> dict[str, str]:
    code = str(status_code or "").strip() or "queued_private_delivery"
    label = PRIVATE_DELIVERY_STATUS_LABELS.get(code, PRIVATE_DELIVERY_STATUS_LABELS["queued_private_delivery"])
    return {
        "code": code,
        "label": label,
        "reason_code": str(reason_code or "").strip(),
        "reason": str(plain_reason or "").strip(),
    }


def canonical_release_state(release_state: str, *, local_sealed: bool = True) -> str:
    state = str(release_state or "").strip().lower()
    if state == "delivered":
        return "released_private"
    if state in {"failed", "release_failed"}:
        return "release_failed"
    if state == "releasing":
        return "publishing_private"
    if state in {"queued", "accepted_locally", "sealed"}:
        return "queued_private_release"
    if local_sealed:
        return "sealed_local"
    return "queued_private_release"


def network_release_state(
    lane: str,
    release_state: str,
    *,
    result: dict | None = None,
    local_sealed: bool = True,
) -> str:
    """User-facing network state without overclaiming gate delivery.

    ``release_state`` is intentionally kept backward-compatible for older API
    consumers.  This projection is the stricter state machine used by newer UI
    surfaces: gate publication is not the same thing as recipient delivery.
    """
    normalized_lane = str(lane or "").strip().lower()
    state = str(release_state or "").strip().lower()
    result_payload = dict(result or {})
    if state == "delivered":
        if normalized_lane == "gate":
            if bool(result_payload.get("published", False)):
                return "published_private"
            return "queued_private_release"
        return "delivered_private"
    return canonical_release_state(state, local_sealed=local_sealed)


def private_lane_readiness_status(
    status_code: str,
    *,
    reason_code: str = "",
    plain_reason: str = "",
) -> dict[str, str]:
    code = str(status_code or "").strip() or "private_lane_unavailable"
    label = PRIVATE_LANE_READINESS_LABELS.get(
        code,
        PRIVATE_LANE_READINESS_LABELS["private_lane_unavailable"],
    )
    return {
        "code": code,
        "label": label,
        "reason_code": str(reason_code or "").strip(),
        "reason": str(plain_reason or "").strip(),
    }


def evaluate_network_release(lane: str, current_tier: str | None) -> PrivateReleaseDecision:
    normalized_lane = str(lane or "").strip().lower()
    normalized_tier = normalize_transport_tier(current_tier)
    required_tier = release_lane_required_tier(normalized_lane)
    if transport_tier_is_sufficient(normalized_tier, required_tier):
        return PrivateReleaseDecision(
            lane=normalized_lane,
            current_tier=normalized_tier,
            required_tier=required_tier,
            allowed=True,
            should_queue=False,
            should_bootstrap=False,
            status_code="delivered_privately",
            status_label=PRIVATE_DELIVERY_STATUS_LABELS["delivered_privately"],
            reason_code="release_floor_satisfied",
            plain_reason="The private lane is ready for delivery.",
        )
    if normalized_tier == "public_degraded":
        reason_code = f"{normalized_lane}_release_waiting_for_private_lane"
        return PrivateReleaseDecision(
            lane=normalized_lane,
            current_tier=normalized_tier,
            required_tier=required_tier,
            allowed=False,
            should_queue=True,
            should_bootstrap=True,
            status_code="preparing_private_lane",
            status_label=PRIVATE_DELIVERY_STATUS_LABELS["preparing_private_lane"],
            reason_code=reason_code,
            plain_reason="The app is preparing the private lane before release.",
        )
    return PrivateReleaseDecision(
        lane=normalized_lane,
        current_tier=normalized_tier,
        required_tier=required_tier,
        allowed=False,
        should_queue=True,
        should_bootstrap=True,
        status_code="queued_private_delivery",
        status_label=PRIVATE_DELIVERY_STATUS_LABELS["queued_private_delivery"],
        reason_code=f"{normalized_lane}_release_waiting_for_{required_tier}",
        plain_reason="The message is sealed locally and waiting for the required private lane.",
    )


def queued_delivery_status(lane: str, current_tier: str | None) -> dict[str, str]:
    decision = evaluate_network_release(lane, current_tier)
    if decision.allowed:
        return private_delivery_status(
            "queued_private_delivery",
            reason_code=f"{decision.lane}_release_queued",
            plain_reason="The sealed message is queued for private delivery.",
        )
    return private_delivery_status(
        decision.status_code,
        reason_code=decision.reason_code,
        plain_reason=decision.plain_reason,
    )
