"""ShadowBroker message signature system.

Every outbound message from the ShadowBroker AI co-pilot starts with a
branded emoji + text prefix so the user always knows:
  1. It's from the ShadowBroker app
  2. What TYPE of action is being performed

Usage:
    from sb_signatures import sig
    message = f"{sig('brief')}\\nYour morning intelligence digest..."
"""

# Signature registry — emoji prefix + action label
_SIGNATURES: dict[str, str] = {
    # ── Core Intelligence ──────────────────────────────────────────────
    "brief":       "🌍📡 SHADOWBROKER BRIEF:",
    "warning":     "🌍⚠️ SHADOWBROKER WARNING:",
    "news":        "🌍📰 SHADOWBROKER NEWS:",
    "intel":       "🌍🛰️ SHADOWBROKER INTEL:",
    "update":      "🌍🌐 SHADOWBROKER UPDATE:",

    # ── Search & Discovery ─────────────────────────────────────────────
    "searching":   "🌍🔍 SHADOWBROKER SEARCHING:",
    "pinning":     "🌍📌 SHADOWBROKER PINNING:",
    "geolocate":   "🌍📸 SHADOWBROKER GEOLOCATE:",

    # ── Proximity & Location ───────────────────────────────────────────
    "near_you":    "🌍📍 SHADOWBROKER NEAR YOU:",
    "watching":    "🌍👁️ SHADOWBROKER WATCHING:",

    # ── Threat & Security ──────────────────────────────────────────────
    "threat":      "🌍🔴 SHADOWBROKER THREAT:",
    "sigint":      "🌍📻 SHADOWBROKER SIGINT:",
    "anomaly":     "🌍🔶 SHADOWBROKER ANOMALY:",

    # ── Transport & Movement ───────────────────────────────────────────
    "flight":      "🌍🛫 SHADOWBROKER FLIGHT:",
    "maritime":    "🌍🚢 SHADOWBROKER MARITIME:",
    "satellite":   "🌍🛰️ SHADOWBROKER SATELLITE:",

    # ── Infrastructure ─────────────────────────────────────────────────
    "cyber":       "🌍💻 SHADOWBROKER CYBER:",
    "network":     "🌍🔗 SHADOWBROKER NETWORK:",

    # ── System ─────────────────────────────────────────────────────────
    "online":      "🌍✅ SHADOWBROKER ONLINE:",
    "offline":     "🌍🔴 SHADOWBROKER OFFLINE:",
    "error":       "🌍❌ SHADOWBROKER ERROR:",

    # ── Mesh & Wormhole ────────────────────────────────────────────────
    "mesh":        "🌍📶 SHADOWBROKER MESH:",
    "wormhole":    "🌍🌀 SHADOWBROKER WORMHOLE:",
    "dead_drop":   "🌍💀 SHADOWBROKER DEAD DROP:",

    # ── Time Machine ───────────────────────────────────────────────────
    "timemachine": "🌍🕰️ SHADOWBROKER TIMEMACHINE:",

    # ── Reports ────────────────────────────────────────────────────────
    "report":      "🌍📋 SHADOWBROKER REPORT:",

    # ── SAR (Synthetic Aperture Radar) ─────────────────────────────────
    "sar":         "🌍📡 SHADOWBROKER SAR:",
}


def sig(action: str) -> str:
    """Get the branded signature prefix for an action type.

    Args:
        action: One of the registered action types (brief, warning, news, etc.)

    Returns:
        The full branded signature string, e.g. "🌍📡 SHADOWBROKER BRIEF:"
        Falls back to a generic UPDATE signature for unknown actions.
    """
    return _SIGNATURES.get(action.lower().strip(), _SIGNATURES["update"])


def all_signatures() -> dict[str, str]:
    """Return all registered signatures."""
    return dict(_SIGNATURES)
