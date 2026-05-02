"""Local-only DM diagnostic runner.

The selftest uses dedicated synthetic aliases so operators can verify the DM
MLS path without creating a real contact or publishing a message. It is a
functional/privacy smoke test, not a substitute for a two-node network test.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from typing import Any

from services.config import get_settings
from services.mesh import mesh_dm_mls
from services.mesh.mesh_local_custody import local_custody_status_snapshot
from services.mesh.mesh_rollout_flags import signed_write_content_private_transport_lock_required
from services.mesh.mesh_wormhole_identity import register_wormhole_dm_key
from services.mesh.mesh_wormhole_persona import bootstrap_wormhole_persona_state, get_dm_identity
from services.mesh.mesh_wormhole_prekey import register_wormhole_prekey_bundle
from services.wormhole_supervisor import get_transport_tier, get_wormhole_state


def _sha256_text(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _sha256_b64_payload(value: str) -> str:
    try:
        raw = base64.b64decode(str(value or ""), validate=True)
    except Exception:
        raw = str(value or "").encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _step(name: str, result: dict[str, Any], *, required: bool = True) -> dict[str, Any]:
    ok = bool(result.get("ok"))
    return {
        "name": name,
        "ok": ok,
        "required": bool(required),
        "detail": "ok" if ok else str(result.get("detail", "failed") or "failed"),
    }


def _contains_plaintext(serialized: str, plaintexts: list[str]) -> bool:
    haystack = str(serialized or "")
    return any(bool(text) and text in haystack for text in plaintexts)


def run_dm_selftest(message: str = "") -> dict[str, Any]:
    started_at = int(time.time())
    run_id = secrets.token_hex(6)
    local_alias = f"sb_dm_selftest_local_{run_id}"
    peer_alias = f"sb_dm_selftest_peer_{run_id}"
    plaintext = str(message or "").strip() or f"ShadowBroker DM selftest {run_id}"
    reply_plaintext = f"selftest reply {run_id}"
    steps: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    cleanup: dict[str, Any] = {"ok": False, "detail": "not_run"}
    result: dict[str, Any] | None = None

    try:
        bootstrap_wormhole_persona_state()
        identity = get_dm_identity()
        dm_key = register_wormhole_dm_key()
        prekeys = register_wormhole_prekey_bundle()
        steps.append(_step("dm_identity_loaded", {"ok": bool(identity.get("node_id"))}))
        steps.append(_step("dm_key_registered", dm_key))
        steps.append(_step("prekey_bundle_registered", prekeys, required=False))

        peer_bundle = mesh_dm_mls.export_dm_key_package_for_alias(peer_alias)
        steps.append(_step("synthetic_peer_key_package", peer_bundle))
        if not peer_bundle.get("ok"):
            result = _finish(
                ok=False,
                run_id=run_id,
                started_at=started_at,
                steps=steps,
                checks=checks,
                cleanup=cleanup,
                plaintext_hash=_sha256_text(plaintext),
            )
            return result

        initiated = mesh_dm_mls.initiate_dm_session(local_alias, peer_alias, peer_bundle)
        steps.append(_step("mls_session_initiated", initiated))
        if not initiated.get("ok"):
            result = _finish(
                ok=False,
                run_id=run_id,
                started_at=started_at,
                steps=steps,
                checks=checks,
                cleanup=cleanup,
                plaintext_hash=_sha256_text(plaintext),
            )
            return result

        accepted = mesh_dm_mls.accept_dm_session(peer_alias, local_alias, str(initiated.get("welcome", "")))
        steps.append(_step("mls_session_accepted_by_peer", accepted))
        if not accepted.get("ok"):
            result = _finish(
                ok=False,
                run_id=run_id,
                started_at=started_at,
                steps=steps,
                checks=checks,
                cleanup=cleanup,
                plaintext_hash=_sha256_text(plaintext),
            )
            return result

        encrypted = mesh_dm_mls.encrypt_dm(local_alias, peer_alias, plaintext)
        steps.append(_step("outbound_encrypt", encrypted))
        if not encrypted.get("ok"):
            result = _finish(
                ok=False,
                run_id=run_id,
                started_at=started_at,
                steps=steps,
                checks=checks,
                cleanup=cleanup,
                plaintext_hash=_sha256_text(plaintext),
            )
            return result

        decrypted = mesh_dm_mls.decrypt_dm(
            peer_alias,
            local_alias,
            str(encrypted.get("ciphertext", "")),
            str(encrypted.get("nonce", "")),
        )
        decrypt_matches = bool(decrypted.get("ok")) and decrypted.get("plaintext") == plaintext
        steps.append(
            _step(
                "synthetic_peer_decrypt",
                {"ok": decrypt_matches, "detail": str(decrypted.get("detail", "plaintext_mismatch"))},
            )
        )

        reply_encrypted = mesh_dm_mls.encrypt_dm(peer_alias, local_alias, reply_plaintext)
        steps.append(_step("reply_encrypt", reply_encrypted))
        reply_decrypted = (
            mesh_dm_mls.decrypt_dm(
                local_alias,
                peer_alias,
                str(reply_encrypted.get("ciphertext", "")),
                str(reply_encrypted.get("nonce", "")),
            )
            if reply_encrypted.get("ok")
            else {"ok": False, "detail": "reply_encrypt_failed"}
        )
        reply_matches = bool(reply_decrypted.get("ok")) and reply_decrypted.get("plaintext") == reply_plaintext
        steps.append(
            _step(
                "local_reply_decrypt",
                {"ok": reply_matches, "detail": str(reply_decrypted.get("detail", "plaintext_mismatch"))},
            )
        )

        serialized_cipher_material = "|".join(
            [
                str(encrypted.get("ciphertext", "")),
                str(encrypted.get("nonce", "")),
                str(initiated.get("welcome", "")),
                str(reply_encrypted.get("ciphertext", "")),
                str(reply_encrypted.get("nonce", "")),
            ]
        )
        no_plaintext_in_cipher_material = not _contains_plaintext(
            serialized_cipher_material,
            [plaintext, reply_plaintext],
        )
        checks.extend(
            [
                {
                    "name": "mls_format_locked",
                    "ok": bool(
                        mesh_dm_mls.is_dm_locked_to_mls(local_alias, peer_alias)
                        and mesh_dm_mls.is_dm_locked_to_mls(peer_alias, local_alias)
                    ),
                    "detail": "DM pair is locked to MLS after first encrypt/decrypt.",
                },
                {
                    "name": "cipher_material_no_plaintext_substring",
                    "ok": no_plaintext_in_cipher_material,
                    "detail": "Plaintext was not found as a substring of ciphertext, nonce, or welcome material.",
                },
                {
                    "name": "synthetic_alias_separation",
                    "ok": local_alias != peer_alias and local_alias != str(identity.get("node_id", "")),
                    "detail": "Selftest aliases are separate from the persistent DM alias.",
                },
                {
                    "name": "content_private_transport_lock_required",
                    "ok": bool(signed_write_content_private_transport_lock_required()),
                    "detail": "Signed content-private writes require transport_lock=private_strong.",
                },
                {
                    "name": "relay_fallback_requires_approval",
                    "ok": bool(get_settings().MESH_PRIVATE_RELEASE_APPROVAL_ENABLE),
                    "detail": "Weaker relay fallback is approval-gated.",
                },
                {
                    "name": "local_only_no_network_release",
                    "ok": True,
                    "detail": "Selftest used local MLS compose/decrypt only; it did not publish a test message.",
                },
            ]
        )

        ok = all(step["ok"] for step in steps if step["required"]) and all(check["ok"] for check in checks)
        result = _finish(
            ok=ok,
            run_id=run_id,
            started_at=started_at,
            steps=steps,
            checks=checks,
            cleanup=cleanup,
            plaintext_hash=_sha256_text(plaintext),
            ciphertext_hash=_sha256_b64_payload(str(encrypted.get("ciphertext", ""))),
        )
        return result
    finally:
        cleanup = mesh_dm_mls.forget_dm_aliases([local_alias, peer_alias])
        if result is not None:
            result["cleanup"] = cleanup


def _finish(
    *,
    ok: bool,
    run_id: str,
    started_at: int,
    steps: list[dict[str, Any]],
    checks: list[dict[str, Any]],
    cleanup: dict[str, Any],
    plaintext_hash: str,
    ciphertext_hash: str = "",
) -> dict[str, Any]:
    transport_tier = "public_degraded"
    try:
        transport_tier = str(get_transport_tier() or "public_degraded")
    except Exception:
        try:
            transport_tier = str(get_wormhole_state().get("transport_tier", "public_degraded") or "public_degraded")
        except Exception:
            transport_tier = "unknown"
    return {
        "ok": bool(ok),
        "run_id": str(run_id),
        "mode": "local_synthetic_peer",
        "started_at": int(started_at),
        "completed_at": int(time.time()),
        "transport_tier": transport_tier,
        "local_custody": local_custody_status_snapshot(),
        "steps": steps,
        "privacy_checks": checks,
        "artifacts": {
            "plaintext_sha256": plaintext_hash,
            "ciphertext_sha256": ciphertext_hash,
            "plaintext_returned": False,
            "contact_created": False,
            "network_release_attempted": False,
        },
        "cleanup": cleanup,
        "unproven_by_this_test": [
            "real two-node delivery across RNS/Tor/relay",
            "passive traffic timing resistance",
            "remote peer key custody",
            "invite exchange UX on a separate device",
        ],
        "next_hardening": [
            "add a two-node localhost harness with separate backend data directories",
            "capture packet/HTTP traces during the test and assert no plaintext or stable public identity leaks",
            "add batch/timing-cover assertions for high-privacy mode",
        ],
    }
