"""OpenClaw Agent Bridge - Identity management and command routing.

This module manages the OpenClaw agent's cryptographic identity and provides
a secure command bridge between the agent and ShadowBroker's AI Intel subsystem.

The agent gets its own Ed25519 keypair, separate from the operator's identity.
The private key never leaves this server - the agent's commands are validated
and executed locally, then results returned.

Phase 2 of the secure OpenClaw connectivity architecture.
"""

import base64
import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Agent identity is stored encrypted alongside other mesh secrets
DATA_DIR = Path(__file__).resolve().parent / "mesh"
AGENT_IDENTITY_FILE = Path(__file__).resolve().parent.parent / "data" / "openclaw_agent_identity.json"


def _ensure_data_dir() -> None:
    """Ensure the data directory exists."""
    AGENT_IDENTITY_FILE.parent.mkdir(parents=True, exist_ok=True)


def _read_agent_identity() -> dict[str, Any]:
    """Read the agent identity from encrypted storage."""
    try:
        from services.mesh.mesh_secure_storage import read_secure_json
        return read_secure_json(AGENT_IDENTITY_FILE, lambda: {})
    except Exception:
        if AGENT_IDENTITY_FILE.exists():
            try:
                data = json.loads(AGENT_IDENTITY_FILE.read_text(encoding="utf-8"))
                if data.get("private_key"):
                    logger.warning(
                        "Agent identity file appears to contain an unencrypted "
                        "private key — secure storage may not be working. "
                        "Re-bootstrap the identity to encrypt it."
                    )
                return data
            except Exception:
                pass
    return {}


def _write_agent_identity(data: dict[str, Any]) -> None:
    """Write agent identity to encrypted storage.

    Raises RuntimeError if encrypted storage is unavailable — private keys
    must never be silently written as plain-text JSON.
    """
    _ensure_data_dir()
    try:
        from services.mesh.mesh_secure_storage import write_secure_json
        write_secure_json(AGENT_IDENTITY_FILE, data)
    except Exception as exc:
        logger.critical(
            "Encrypted storage unavailable — refusing to write agent private key "
            "as plain text. Install cryptography or fix secure storage. Error: %s",
            exc,
        )
        raise RuntimeError(
            "Cannot write agent identity: encrypted storage unavailable. "
            "Private keys must not be stored as plain text."
        ) from exc


def generate_agent_keypair(force: bool = False) -> dict[str, Any]:
    """Generate an Ed25519 keypair for the OpenClaw agent.

    The private key is stored encrypted on the server.
    Only the public key and node_id are returned.

    Args:
        force: If True, regenerates even if one already exists.

    Returns:
        Public identity info (never the private key).
    """
    existing = _read_agent_identity()
    if existing.get("bootstrapped") and not force:
        return get_agent_public_info()

    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import (
            Encoding,
            NoEncryption,
            PrivateFormat,
            PublicFormat,
        )
        from services.mesh.mesh_crypto import derive_node_id

        # Generate Ed25519 keypair
        private_key = Ed25519PrivateKey.generate()
        private_bytes = private_key.private_bytes(
            Encoding.Raw, PrivateFormat.Raw, NoEncryption()
        )
        public_bytes = private_key.public_key().public_bytes(
            Encoding.Raw, PublicFormat.Raw
        )

        private_key_b64 = base64.b64encode(private_bytes).decode("ascii")
        public_key_b64 = base64.b64encode(public_bytes).decode("ascii")

        # Derive node_id from public key (same as mesh protocol)
        node_id = derive_node_id(public_key_b64)

        # Generate X25519 DH keypair for key exchange
        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

        dh_private = X25519PrivateKey.generate()
        dh_private_bytes = dh_private.private_bytes(
            Encoding.Raw, PrivateFormat.Raw, NoEncryption()
        )
        dh_public_bytes = dh_private.public_key().public_bytes(
            Encoding.Raw, PublicFormat.Raw
        )

        identity = {
            "bootstrapped": True,
            "bootstrapped_at": int(time.time()),
            "scope": "openclaw_agent",
            "label": "openclaw-agent",
            "node_id": node_id,
            "public_key": public_key_b64,
            "public_key_algo": "Ed25519",
            "private_key": private_key_b64,
            "dh_pub_key": base64.b64encode(dh_public_bytes).decode("ascii"),
            "dh_private_key": base64.b64encode(dh_private_bytes).decode("ascii"),
            "dh_algo": "X25519",
            "sequence": 0,
        }

        _write_agent_identity(identity)
        logger.info("OpenClaw agent identity generated: %s", node_id)

        return {
            "ok": True,
            "bootstrapped": True,
            "node_id": node_id,
            "public_key": public_key_b64,
            "public_key_algo": "Ed25519",
            "dh_pub_key": base64.b64encode(dh_public_bytes).decode("ascii"),
            "dh_algo": "X25519",
            "bootstrapped_at": identity["bootstrapped_at"],
        }

    except ImportError:
        return {
            "ok": False,
            "detail": "cryptography library not available - install: pip install cryptography",
        }
    except Exception as exc:
        logger.error("Failed to generate agent keypair: %s", exc)
        return {"ok": False, "detail": "keypair generation failed"}


def get_agent_public_info() -> dict[str, Any]:
    """Return only public identity info for the agent.

    NEVER returns private keys.
    """
    identity = _read_agent_identity()
    if not identity.get("bootstrapped"):
        return {
            "ok": True,
            "bootstrapped": False,
            "node_id": "",
            "public_key": "",
            "public_key_algo": "Ed25519",
        }

    return {
        "ok": True,
        "bootstrapped": True,
        "node_id": str(identity.get("node_id", "")),
        "public_key": str(identity.get("public_key", "")),
        "public_key_algo": str(identity.get("public_key_algo", "Ed25519")),
        "dh_pub_key": str(identity.get("dh_pub_key", "")),
        "dh_algo": str(identity.get("dh_algo", "X25519")),
        "bootstrapped_at": int(identity.get("bootstrapped_at", 0) or 0),
    }


def sign_for_agent(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Sign an event using the agent's Ed25519 private key.

    Used when the agent needs to post to the InfoNet or sign mesh events.
    The private key never leaves the server.
    """
    identity = _read_agent_identity()
    if not identity.get("bootstrapped"):
        return {"ok": False, "detail": "agent identity not bootstrapped"}

    private_key_b64 = str(identity.get("private_key", ""))
    node_id = str(identity.get("node_id", ""))
    public_key = str(identity.get("public_key", ""))

    if not private_key_b64 or not node_id:
        return {"ok": False, "detail": "agent identity incomplete"}

    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from services.mesh.mesh_crypto import build_signature_payload
        from services.mesh.mesh_protocol import PROTOCOL_VERSION

        # Increment sequence
        seq = int(identity.get("sequence", 0) or 0) + 1
        identity["sequence"] = seq
        _write_agent_identity(identity)

        # Build canonical signature payload
        sig_payload = build_signature_payload(
            event_type=event_type,
            node_id=node_id,
            sequence=seq,
            payload=payload,
        )

        # Sign
        key_bytes = base64.b64decode(private_key_b64)
        signing_key = Ed25519PrivateKey.from_private_bytes(key_bytes)
        signature = signing_key.sign(sig_payload.encode("utf-8"))

        return {
            "ok": True,
            "node_id": node_id,
            "public_key": public_key,
            "public_key_algo": "Ed25519",
            "signature": signature.hex(),
            "sequence": seq,
            "protocol_version": PROTOCOL_VERSION,
        }

    except Exception as exc:
        logger.error("Agent signing failed: %s", type(exc).__name__)
        return {"ok": False, "detail": "signing failed"}


def revoke_agent_identity() -> dict[str, Any]:
    """Revoke (delete) the agent's identity.

    The keypair is permanently destroyed. A new one must be generated.
    """
    try:
        if AGENT_IDENTITY_FILE.exists():
            AGENT_IDENTITY_FILE.unlink()
        return {"ok": True, "detail": "Agent identity revoked"}
    except Exception as exc:
        return {"ok": False, "detail": f"revocation failed: {exc}"}
