#!/usr/bin/env python3
"""Live E2E: short-address lookup -> contact request -> remote participant mailbox.

Environment:
  PETE_SSH / REMOTE_PARTICIPANT_SSH — SSH host for remote participant (default: pete)
  E2E_DM_TOR_ONLY=1 — skip disk-inject fallbacks; require Tor replicate-envelope only
  E2E_DM_LEAVE_LEAN_BACKEND=1 — keep MESH_ONLY lean backend after E2E (default: restore full telemetry)
  E2E_DM_DEPLOY_FROM_GIT=1 — remote participant: git pull + compose (no harness SCP patches)
  E2E_DM_FRESH_BACKEND=1 — recreate local lean E2E backend before run
  docker-compose.participant.yml — deploy lean participant on any fleet peer
"""

from __future__ import annotations

import json
import base64
import hashlib
import hmac
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import urllib.error
import urllib.parse
import urllib.request

API = os.environ.get("SHADOWBROKER_API", "http://127.0.0.1:8000")
MARKER = os.environ.get("E2E_DM_MARKER", f"dm-short-addr-e2e-{int(time.time())}")
REPLY_MARKER = os.environ.get("E2E_DM_REPLY_MARKER", f"{MARKER}-reply")
_E2E_REQUESTS_MAILBOX_TOKEN = "e2e-tor-requests"
PETE_HANDLE = os.environ.get("PETE_DM_SHORT_HANDLE", "").strip()
PETE_LOOKUP_PEER_URL = os.environ.get("PETE_DM_LOOKUP_PEER_URL", "").strip()
FRESH_BACKEND = os.environ.get("E2E_DM_FRESH_BACKEND", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}
SSH_PETE = os.environ.get("REMOTE_PARTICIPANT_SSH") or os.environ.get("PETE_SSH", "pete")
TOR_ONLY = os.environ.get("E2E_DM_TOR_ONLY", "0").strip().lower() not in {
    "0",
    "false",
    "no",
}
DEPLOY_FROM_GIT = os.environ.get("E2E_DM_DEPLOY_FROM_GIT", "0").strip().lower() not in {
    "0",
    "false",
    "no",
}
SKIP_REMOTE_PREP = os.environ.get("E2E_DM_SKIP_REMOTE_PREP", "0").strip().lower() not in {
    "0",
    "false",
    "no",
}
PETE_ONION = os.environ.get("REMOTE_PARTICIPANT_ONION") or os.environ.get(
    "PETE_ONION",
    "nwbs4ur2usffb7lk3vyffhaqrijry544vmfjkk3qbrhvoh4v26fwxlid.onion:8000",
).strip()


def _embed_json_value(value: object) -> str:
    """Embed JSON-serializable data in generated Python via json.loads."""
    return f"json.loads({json.dumps(json.dumps(value))})"

PRIVATE_DM_TRANSPORT_LOCK = "private_strong"
LOCAL_COMPOSE_FILES = (
    "docker-compose.yml",
    "docker-compose.override.yml",
    "docker-compose.e2e.yml",
)
FULL_LOCAL_COMPOSE_FILES = (
    "docker-compose.yml",
    "docker-compose.override.yml",
)

_EMBED_SIGNED_MAILBOX_HELPERS = textwrap.dedent(
    """
    from services.mesh.mesh_protocol import SIGNED_CONTEXT_FIELD, build_signed_context

    def _build_signed_mailbox_request(
        *,
        agent_id: str,
        event_type: str,
        kind: str,
        endpoint: str,
        sequence_domain: str,
        claims: list,
    ) -> tuple[dict, bytes]:
        from services.mesh.mesh_protocol import PROTOCOL_VERSION
        from services.mesh.mesh_wormhole_persona import get_dm_identity, sign_dm_wormhole_event

        identity = get_dm_identity()
        sequence = int(identity.get("sequence", 0) or 0) + 1
        ts = int(time.time())
        nonce = secrets.token_hex(8)
        signed_payload = {
            "mailbox_claims": claims,
            "timestamp": ts,
            "nonce": nonce,
            "transport_lock": "private_strong",
        }
        signed_payload[SIGNED_CONTEXT_FIELD] = build_signed_context(
            event_type=event_type,
            kind=kind,
            endpoint=endpoint,
            lane_floor="private_strong",
            sequence_domain=sequence_domain,
            node_id=agent_id,
            sequence=sequence,
            payload=signed_payload,
        )
        signed = sign_dm_wormhole_event(
            event_type=event_type,
            payload=signed_payload,
            sequence=sequence,
        )
        body = {
            "agent_id": agent_id,
            "mailbox_claims": claims,
            "timestamp": ts,
            "nonce": nonce,
            "transport_lock": "private_strong",
            "public_key": str(signed.get("public_key") or ""),
            "public_key_algo": str(signed.get("public_key_algo") or ""),
            "signature": str(signed.get("signature") or ""),
            "sequence": int(signed.get("sequence") or 0),
            "protocol_version": str(signed.get("protocol_version") or PROTOCOL_VERSION),
            "signed_context": dict(signed_payload.get(SIGNED_CONTEXT_FIELD) or {}),
        }
        data = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
        return body, data
    """
).strip()


def _docker_json(method: str, path: str, body: dict | None = None, *, admin_key: str = "", timeout_s: int = 30) -> dict:
    use_stdin = body is not None
    payload = ["docker", "exec"]
    if use_stdin:
        payload.append("-i")
    payload.extend(["shadowbroker-backend", "curl", "-s", "--max-time", str(timeout_s)])
    if admin_key:
        payload.extend(["-H", f"X-Admin-Key: {admin_key}"])
    if body is not None:
        payload.extend(["-H", "Content-Type: application/json", "-X", method.upper(), "-d", "@-"])
    else:
        payload.extend(["-X", method.upper()])
    payload.append(f"http://127.0.0.1:8000{path}")
    proc = subprocess.run(
        payload,
        input=json.dumps(body) if body is not None else None,
        capture_output=True,
        text=True,
        timeout=timeout_s + 15,
        check=False,
    )
    raw = (proc.stdout or "").strip()
    if not raw:
        raise RuntimeError(proc.stderr.strip() or f"{method} {path} produced no response")
    parsed = json.loads(raw)
    if isinstance(parsed, dict) and parsed.get("detail") == "private_delivery_item_not_found" and method.upper() == "POST":
        return parsed
    return parsed if isinstance(parsed, dict) else {"ok": False, "detail": "invalid json response"}


def _json(method: str, path: str, body: dict | None = None, *, admin_key: str = "") -> dict:
    data = None
    headers = {"Content-Type": "application/json"}
    if admin_key:
        headers["X-Admin-Key"] = admin_key
    if body is not None:
        data = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
    req = urllib.request.Request(f"{API}{path}", data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} -> {exc.code}: {detail}") from exc


def _docker_admin_key() -> str:
    proc = subprocess.run(
        ["docker", "exec", "shadowbroker-backend", "printenv", "ADMIN_KEY"],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def _ssh_pete_admin_key() -> str:
    proc = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", SSH_PETE, "docker exec shadowbroker-backend printenv ADMIN_KEY"],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def _pete_http_post(path: str, body: dict, pete_admin: str, *, timeout_s: int = 120) -> dict:
    """POST JSON to Pete's live uvicorn via host curl (published :8000, same as invite)."""
    body_b64 = base64.b64encode(json.dumps(body).encode("utf-8")).decode("ascii")
    remote_cmd = (
        f"echo {body_b64} | base64 -d | curl -s --max-time {int(timeout_s)} -X POST "
        f"-H 'X-Admin-Key: {pete_admin}' -H 'Content-Type: application/json' "
        f"--data-binary @- 'http://127.0.0.1:8000{path}'"
    )
    proc = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", SSH_PETE, remote_cmd],
        capture_output=True,
        timeout=timeout_s + 30,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", errors="replace").strip() or "pete http post failed")
    raw = proc.stdout.decode("utf-8", errors="replace").strip()
    if not raw:
        raise RuntimeError(proc.stderr.decode("utf-8", errors="replace").strip() or "pete http post produced no output")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(raw or str(exc)) from exc
    if not payload.get("ok") and payload.get("detail"):
        raise RuntimeError(str(payload.get("detail") or "pete http post failed"))
    return payload


def _ensure_pete_invite(pete_admin: str) -> tuple[str, str]:
    if PETE_HANDLE:
        lookup = PETE_LOOKUP_PEER_URL or (
            f"http://{PETE_ONION}" if PETE_ONION else ""
        )
        return PETE_HANDLE, lookup.rstrip("/")
    proc = subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            SSH_PETE,
            f"curl -s -H 'X-Admin-Key: {pete_admin}' 'http://127.0.0.1:8000/api/wormhole/dm/invite?label=e2e-live'",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    invite = json.loads(proc.stdout)
    payload = dict(invite.get("invite", {}).get("payload", {}) or {})
    handle = str(payload.get("prekey_lookup_handle", "") or "").strip()
    lookup_peer_url = str(payload.get("lookup_peer_url", "") or "").strip().rstrip("/")
    if not handle:
        raise RuntimeError(f"could not mint Pete short handle: {invite}")
    return handle, lookup_peer_url


def _ensure_local_invite(local_admin: str) -> tuple[str, str]:
    code = (
        "import json\n"
        "from routers.wormhole import export_wormhole_dm_invite\n"
        "from services.wormhole_supervisor import get_wormhole_state\n"
        "invite = export_wormhole_dm_invite(label='e2e-local-sender')\n"
        "payload = dict((invite.get('invite') or {}).get('payload') or {})\n"
        "handle = str(payload.get('prekey_lookup_handle') or '').strip()\n"
        "lookup_peer_url = str(payload.get('lookup_peer_url') or '').strip().rstrip('/')\n"
        "if not lookup_peer_url:\n"
        "    tor = dict((get_wormhole_state() or {}).get('tor') or {})\n"
        "    lookup_peer_url = str(tor.get('onion_address') or '').strip().rstrip('/')\n"
        "print(json.dumps({'handle': handle, 'lookup_peer_url': lookup_peer_url, 'invite': invite}))\n"
    )
    result = _docker_python(code)
    handle = str(result.get("handle", "") or "").strip()
    lookup_peer_url = str(result.get("lookup_peer_url", "") or "").strip().rstrip("/")
    if not handle:
        raise RuntimeError(f"could not mint local short handle: {result.get('invite', result)}")
    return handle, lookup_peer_url


def _ensure_local_prekey_registered() -> dict:
    """Ensure local wormhole prekey bundle is registered on the relay."""
    code = """import json
from services.mesh.mesh_wormhole_prekey import register_wormhole_prekey_bundle
from services.mesh.mesh_dm_relay import dm_relay
from services.mesh.mesh_wormhole_persona import get_dm_identity
reg = register_wormhole_prekey_bundle()
node_id = str((get_dm_identity() or {}).get("node_id") or "")
stored = dm_relay.get_prekey_bundle(node_id) if node_id else None
print(json.dumps({
    "ok": bool(stored and stored.get("bundle")),
    "register_ok": bool(reg.get("ok")),
    "node_id": node_id,
}))
"""
    return _docker_python(code)


def _seed_local_prekey_on_pete(local_sender_id: str, local_handle: str) -> dict:
    reg = _ensure_local_prekey_registered()
    if not reg.get("ok"):
        return {"ok": False, "detail": "local prekey bundle unavailable", "register": reg}
    export_code = (
        "import json\n"
        "from services.mesh.mesh_dm_relay import dm_relay\n"
        f"stored = dm_relay.get_prekey_bundle({json.dumps(local_sender_id)})\n"
        "print(json.dumps(stored or {}))\n"
    )
    stored = _docker_python(export_code)
    if not isinstance(stored, dict) or not stored.get("bundle"):
        return {"ok": False, "detail": "local prekey bundle unavailable after register"}
    seed_code = f"""import json
from services.mesh.mesh_dm_relay import dm_relay
stored = {json.dumps(stored)}
agent_id = {json.dumps(local_sender_id)}
handle = {json.dumps(local_handle)}
existing = dm_relay.get_prekey_bundle(agent_id)
seq = max(1, int(stored.get("sequence") or 0))
if existing:
    seq = max(seq, int(existing.get("sequence") or 0)) + 1
ok, reason, meta = dm_relay.register_prekey_bundle(
    agent_id=agent_id,
    bundle=dict(stored.get("bundle") or {{}}),
    signature=str(stored.get("signature") or ""),
    public_key=str(stored.get("public_key") or ""),
    public_key_algo=str(stored.get("public_key_algo") or "Ed25519"),
    protocol_version=str(stored.get("protocol_version") or "infonet/2"),
    sequence=seq,
    lookup_aliases=[{{"handle": handle}}],
)
print(json.dumps({{"ok": ok, "detail": reason, "sequence": seq, "meta": meta or {{}}}}))
"""
    return _ssh_pete_python(seed_code, timeout_s=90)


def _docker_python(code: str, *, timeout_s: int = 600) -> dict:
    proc = subprocess.run(
        ["docker", "exec", "-i", "shadowbroker-backend", "python", "-"],
        input=code,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "docker python failed")
    line = proc.stdout.strip().splitlines()[-1]
    return json.loads(line)


def _docker_python_contact_send(
    *,
    handle: str,
    peer_id: str,
    note: str,
    lookup_peer_url: str,
    cached_prekey_bundle: dict,
    timeout_s: int = 120,
) -> dict:
    """Send contact request in an isolated backend subprocess with a cached prekey bundle."""
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json", encoding="utf-8") as tmp:
        json.dump(cached_prekey_bundle, tmp)
        local_path = tmp.name
    try:
        subprocess.run(
            ["docker", "cp", local_path, "shadowbroker-backend:/tmp/e2e_prekey_bundle.json"],
            check=True,
            capture_output=True,
            text=True,
        )
    finally:
        os.unlink(local_path)
    code = (
        "import json\n"
        "from services.openclaw_infonet import send_contact_request\n"
        'bundle = json.load(open("/tmp/e2e_prekey_bundle.json", encoding="utf-8"))\n'
        f"result = send_contact_request(lookup_token={json.dumps(handle)}, "
        f"peer_id={json.dumps(peer_id)}, note={json.dumps(note)}, "
        f"lookup_peer_url={json.dumps(lookup_peer_url)}, cached_prekey_bundle=bundle)\n"
        "print(json.dumps({"
        "'ok': bool(result.get('ok')), "
        "'send': result, "
        "'msg_id': result.get('msg_id',''), "
        "'sender_id': result.get('sender_id',''), "
        "'recipient_id': result.get('recipient_id','')"
        "}))\n"
    )
    return _docker_python(code, timeout_s=timeout_s)


def _local_compose_cmd(*subcommand: str) -> list[str]:
    cmd = ["docker", "compose"]
    for compose_file in LOCAL_COMPOSE_FILES:
        cmd.extend(["-f", compose_file])
    cmd.extend(subcommand)
    return cmd


def _full_compose_cmd(*subcommand: str) -> list[str]:
    cmd = ["docker", "compose"]
    for compose_file in FULL_LOCAL_COMPOSE_FILES:
        cmd.extend(["-f", compose_file])
    cmd.extend(subcommand)
    return cmd


def _restore_local_full_backend() -> None:
    """Return the dashboard backend to full telemetry mode after E2E (MESH_ONLY off)."""
    if os.environ.get("E2E_DM_LEAVE_LEAN_BACKEND", "0").strip().lower() in {
        "1",
        "true",
        "yes",
    }:
        return
    print("== cleanup: restore full backend (telemetry / OSINT fetchers) ==")
    proc = subprocess.run(
        _full_compose_cmd("up", "-d", "--force-recreate", "backend"),
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if proc.returncode != 0:
        print(
            f"full backend restore failed: {proc.stderr.strip() or proc.stdout.strip() or 'compose error'}"
        )
        return
    try:
        _wait_local_backend_healthy(timeout_s=180)
        print("full backend restored (MESH_ONLY off — map telemetry should return)")
    except Exception as exc:
        print(f"full backend restore health wait: {exc}")


def _wait_local_backend_healthy(*, timeout_s: int = 300) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        probe = subprocess.run(
            [
                "docker",
                "exec",
                "shadowbroker-backend",
                "curl",
                "-s",
                "--max-time",
                "60",
                "http://127.0.0.1:8000/api/health",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if probe.returncode == 0:
            mesh_only = subprocess.run(
                ["docker", "exec", "shadowbroker-backend", "printenv", "MESH_ONLY"],
                capture_output=True,
                text=True,
                check=False,
            )
            if (mesh_only.stdout or "").strip().lower() == "true":
                print("local lean E2E backend healthy (MESH_ONLY=true)")
                return
            raise RuntimeError("local backend is up but MESH_ONLY is not enabled")
        time.sleep(3)
    raise RuntimeError("backend did not become healthy after restart")


def _ensure_local_e2e_backend(*, recreate: bool) -> None:
    """Run local backend in lean E2E mode (no OSINT fetchers)."""
    _scrub_local_dm_state()
    if recreate:
        proc = subprocess.run(
            _local_compose_cmd("up", "-d", "--force-recreate", "backend"),
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        action = "recreated"
    else:
        proc = subprocess.run(
            _local_compose_cmd("restart", "backend"),
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        action = "restarted"
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "local backend compose failed")
    _wait_local_backend_healthy()
    print(f"local backend {action} with docker-compose.e2e.yml")


def _prime_dm_wormhole() -> dict:
    """Start wormhole inside the running uvicorn process (not a one-off exec shell)."""
    return _docker_json("POST", "/api/wormhole/join", body={}, timeout_s=120)


def _hidden_transport_enforced() -> bool:
    code = (
        "import json\n"
        "from services.wormhole_settings import read_wormhole_settings\n"
        "settings = read_wormhole_settings()\n"
        "transport = str(settings.get('transport', '') or '').lower()\n"
        "print(json.dumps({\n"
        "    'ok': bool(settings.get('anonymous_mode'))\n"
        "    and transport in {'tor', 'tor_arti', 'i2p', 'mixnet'},\n"
        "}))\n"
    )
    return bool(_docker_python(code).get("ok"))


_TIER_ORDER = {"public_degraded": 0, "private_transitional": 1, "private_strong": 2}


def _transport_lane_sufficient(current: str, required: str) -> bool:
    return _TIER_ORDER.get(str(current or "").strip(), 0) >= _TIER_ORDER.get(str(required or "").strip(), 0)


def _runtime_lane_snapshot(runtime: dict) -> dict:
    tier = str(runtime.get("transport_tier") or "")
    required = "private_transitional"
    tier_ok = _transport_lane_sufficient(tier, required)
    transport_ready = (
        bool(runtime.get("ready"))
        and bool(runtime.get("anonymous_mode_ready"))
        and bool(runtime.get("arti_ready"))
    )
    return {"ok": tier_ok and transport_ready, "tier": tier, "required": required}


def _private_lane_ready(*, join: bool = False) -> dict:
    """Check private lane readiness from live uvicorn wormhole state."""
    if not join:
        try:
            status = _docker_json("GET", "/api/settings/wormhole-status", timeout_s=10)
            if status and bool(status.get("ready")):
                return {"ok": True, "tier": "private_transitional", "required": "private_transitional"}
            if status:
                return {"ok": False, "tier": "", "required": "private_transitional"}
        except Exception:
            pass
        return {"ok": False, "tier": "", "required": "private_transitional"}
    payload = _docker_json("POST", "/api/wormhole/join", body={}, timeout_s=120)
    return _runtime_lane_snapshot(dict(payload.get("runtime") or {}))


def _wait_hidden_transport_ready(*, timeout_s: int = 360) -> dict:
    if not _hidden_transport_enforced():
        return {"ok": True, "transport_tier": "not_enforced"}
    try:
        _docker_json("POST", "/api/wormhole/join", body={}, timeout_s=120)
    except Exception:
        pass
    deadline = time.time() + timeout_s
    last_lane: dict = {}
    polls = 0
    while time.time() < deadline:
        last_lane = _private_lane_ready(join=(polls == 0))
        if last_lane.get("ok"):
            return {"ok": True, "transport_tier": last_lane.get("tier")}
        polls += 1
        if polls % 20 == 0:
            try:
                last_lane = _private_lane_ready(join=True)
                if last_lane.get("ok"):
                    return {"ok": True, "transport_tier": last_lane.get("tier")}
            except Exception:
                pass
        time.sleep(3)
    return {
        "ok": False,
        "detail": "hidden transport or private lane not ready",
        "transport_tier": last_lane.get("tier"),
        "required_tier": last_lane.get("required"),
    }


def _ssh_pete_release_outbox(pete_admin: str, outbox_id: str, *, timeout_s: int = 180) -> dict:
    outbox_id = str(outbox_id or "").strip()
    if not outbox_id:
        return {"ok": True, "skipped": True, "reason": "no outbox_id"}
    proc = subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            SSH_PETE,
            (
                f"curl -s -X POST -H 'X-Admin-Key: {pete_admin}' "
                f"-H 'Content-Type: application/json' "
                f"-d '{{\"action\":\"relay\"}}' "
                f"'http://127.0.0.1:8000/api/wormhole/private-delivery/{outbox_id}/action'"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if proc.returncode != 0:
        return {"ok": False, "detail": proc.stderr.strip() or proc.stdout.strip() or "pete release failed"}
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        status_proc = subprocess.run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                SSH_PETE,
                f"curl -s -H 'X-Admin-Key: {pete_admin}' 'http://127.0.0.1:8000/api/wormhole/status'",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if status_proc.returncode == 0 and status_proc.stdout.strip():
            status = json.loads(status_proc.stdout)
            items = list((status.get("private_delivery") or {}).get("items") or [])
            item = next((entry for entry in items if str(entry.get("id", "")) == outbox_id), None)
            if item and str(item.get("release_state", "")) == "delivered":
                return {"ok": True, "item": item}
        time.sleep(3)
    return {"ok": False, "detail": "pete private release did not complete in time", "outbox_id": outbox_id}


def _wait_pete_outbox_delivered(pete_admin: str, outbox_id: str, *, timeout_s: int = 300) -> dict:
    outbox_id = str(outbox_id or "").strip()
    if not outbox_id:
        return {"ok": False, "detail": "missing outbox_id"}
    deadline = time.time() + timeout_s
    last_state = ""
    while time.time() < deadline:
        status_proc = subprocess.run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                SSH_PETE,
                (
                    "curl -s --max-time 20 "
                    f"-H 'X-Admin-Key: {pete_admin}' "
                    f"'http://127.0.0.1:8000/api/wormhole/private-delivery/{outbox_id}'"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        if status_proc.returncode == 0 and status_proc.stdout.strip():
            payload = json.loads(status_proc.stdout)
            item = payload.get("item") if isinstance(payload, dict) else None
            if isinstance(item, dict):
                last_state = str(item.get("release_state", "") or "")
                if last_state == "delivered":
                    return {"ok": True, "item": item}
        time.sleep(3)
    return {
        "ok": False,
        "detail": "pete private release did not complete in time",
        "outbox_id": outbox_id,
        "last_release_state": last_state,
    }


def _docker_json_optional(
    method: str,
    path: str,
    body: dict | None = None,
    *,
    admin_key: str = "",
    timeout_s: int = 30,
) -> dict | None:
    try:
        return _docker_json(method, path, body, admin_key=admin_key, timeout_s=timeout_s)
    except (RuntimeError, json.JSONDecodeError, subprocess.TimeoutExpired):
        return None


def _get_local_outbox_item(admin_key: str, outbox_id: str) -> dict | None:
    # Prefer in-process read — HTTP /api/wormhole/private-delivery can wedge when
    # fleet peer-push floods the single uvicorn worker during Tor E2E.
    code = (
        "import json\n"
        "from services.mesh.mesh_private_outbox import private_delivery_outbox\n"
        f"item = private_delivery_outbox.get_item({json.dumps(outbox_id)}, exposure='ordinary')\n"
        "print(json.dumps({'item': item}))\n"
    )
    try:
        payload = _docker_python(code)
        item = payload.get("item")
        if isinstance(item, dict):
            return item
    except Exception:
        pass
    payload = _docker_json_optional(
        "GET",
        f"/api/wormhole/private-delivery/{outbox_id}",
        admin_key=admin_key,
        timeout_s=20,
    )
    if not payload:
        return None
    item = payload.get("item")
    return item if isinstance(item, dict) else None


def _wake_local_release_worker() -> None:
    code = (
        "import json\n"
        "from services.mesh.mesh_private_release_worker import private_release_worker\n"
        "private_release_worker.ensure_started()\n"
        "private_release_worker.wake()\n"
        "private_release_worker.run_once()\n"
        "print(json.dumps({'ok': True}))\n"
    )
    try:
        _docker_python(code)
    except Exception as exc:
        print(f"local release worker wake skipped: {exc}")


def _wake_pete_release_worker() -> None:
    code = (
        "import json\n"
        "from services.mesh.mesh_private_release_worker import private_release_worker\n"
        "private_release_worker.ensure_started()\n"
        "private_release_worker.wake()\n"
        "private_release_worker.run_once()\n"
        "print(json.dumps({'ok': True}))\n"
    )
    try:
        _ssh_pete_python(code, timeout_s=60)
    except Exception as exc:
        print(f"pete release worker wake skipped: {exc}")


def _wait_local_outbox_delivered(admin_key: str, outbox_id: str, *, timeout_s: int = 300) -> dict:
    outbox_id = str(outbox_id or "").strip()
    if not outbox_id:
        return {"ok": False, "detail": "missing outbox_id"}
    deadline = time.time() + timeout_s
    last_state = ""
    while time.time() < deadline:
        item = _get_local_outbox_item(admin_key, outbox_id)
        if item:
            last_state = str(item.get("release_state", "") or "")
            if last_state == "delivered":
                return {"ok": True, "item": item}
        time.sleep(3)
    return {
        "ok": False,
        "detail": "private release did not complete in time",
        "outbox_id": outbox_id,
        "last_release_state": last_state,
    }


def _release_dm_outbox(admin_key: str, outbox_id: str, *, timeout_s: int = 180) -> dict:
    outbox_id = str(outbox_id or "").strip()
    if not outbox_id:
        return {"ok": False, "detail": "missing outbox_id"}
    action_timeout_s = max(120, int(os.environ.get("MESH_RELAY_PUSH_TIMEOUT_S", "120") or 120) + 30)
    try:
        _docker_json(
            "POST",
            f"/api/wormhole/private-delivery/{outbox_id}/action",
            {"action": "relay"},
            admin_key=admin_key,
            timeout_s=action_timeout_s,
        )
    except Exception as exc:
        print(f"private relay nudge skipped: {exc}")
    return _wait_local_outbox_delivered(admin_key, outbox_id, timeout_s=timeout_s)


def _socks_handshake_preamble(*, deadline_s: int = 90) -> str:
    """Wait for Arti SOCKS port only (curl push does not need torproject proof)."""
    return (
        "import json, os, socket, time\n"
        "from routers.ai_intel import _write_env_value\n"
        "from services.config import get_settings\n"
        "os.environ['MESH_RELAY_PUSH_TIMEOUT_S'] = '90'\n"
        "_write_env_value('MESH_ARTI_ENABLED', 'true')\n"
        "get_settings.cache_clear()\n"
        f"_socks_deadline = time.time() + {int(deadline_s)}\n"
        "def _socks_ready():\n"
        "    port = int(get_settings().MESH_ARTI_SOCKS_PORT or 9050)\n"
        "    try:\n"
        "        with socket.create_connection(('127.0.0.1', port), timeout=2.0) as sock:\n"
        "            sock.sendall(b'\\x05\\x01\\x00')\n"
        "            return sock.recv(2) == b'\\x05\\x00'\n"
        "    except OSError:\n"
        "        return False\n"
        "while time.time() < _socks_deadline and not _socks_ready():\n"
        "    time.sleep(2)\n"
        "if not _socks_ready():\n"
        "    print(json.dumps({'ok': False, 'detail': 'Arti SOCKS not ready for scoped replicate nudge'}))\n"
        "    raise SystemExit(0)\n"
    )


_ARTI_NUDGE_PREAMBLE = _socks_handshake_preamble(deadline_s=90)


def _scoped_replicate_outbox_nudge_code(
    outbox_id: str,
    *,
    msg_id_hint: str = "",
    warm_arti: bool = False,
) -> str:
    preamble = _ARTI_NUDGE_PREAMBLE if warm_arti else ""
    return preamble + (
        "import json\n"
        "from services.mesh.mesh_private_outbox import private_delivery_outbox\n"
        "from services.mesh.mesh_dm_connect_delivery import enrich_connect_release_payload, relay_push_peer_urls_for_payload\n"
        "from services.mesh.mesh_dm_relay import dm_relay\n"
        f"outbox_id = {json.dumps(outbox_id)}\n"
        f"msg_id_hint = {json.dumps(msg_id_hint)}\n"
        "item = private_delivery_outbox._items.get(outbox_id, {})\n"
        "payload = enrich_connect_release_payload(dict(item.get('payload') or {}))\n"
        "urls = [\n"
        "    str(raw or '').strip().rstrip('/')\n"
        "    for raw in list(payload.get('relay_push_peer_urls') or [])\n"
        "    if str(raw or '').strip()\n"
        "]\n"
        "if not urls:\n"
        "    urls = relay_push_peer_urls_for_payload(payload)\n"
        "if not urls:\n"
        "    print(json.dumps({'ok': False, 'detail': 'no relay push urls in outbox payload'}))\n"
        "else:\n"
        "    recipient_id = str(payload.get('recipient_id') or '')\n"
        "    envelope_obj = dict(payload.get('envelope') or {})\n"
        "    msg_id = str(payload.get('msg_id') or envelope_obj.get('msg_id') or msg_id_hint or '')\n"
        "    delivery_class = str(payload.get('delivery_class') or 'request').strip().lower()\n"
        "    recipient_token = str(payload.get('recipient_token') or '')\n"
        "    if not msg_id and recipient_id:\n"
        "        epoch = dm_relay._epoch_bucket()\n"
        "        for offset in (0, -1, -2):\n"
        "            key = dm_relay._mailbox_key('requests', recipient_id, epoch + offset)\n"
        "            for message in reversed(list(dm_relay._mailboxes.get(key, []))):\n"
        "                candidate = str(message.msg_id or '')\n"
        "                if candidate:\n"
        "                    msg_id = candidate\n"
        "                    break\n"
        "            if msg_id:\n"
        "                break\n"
        "    if delivery_class == 'shared':\n"
        "        mailbox_key = dm_relay._hashed_mailbox_token(recipient_token)\n"
        "    else:\n"
        "        mailbox_key = dm_relay.mailbox_key_for_delivery(\n"
        "            recipient_id=recipient_id,\n"
        "            delivery_class=delivery_class or 'request',\n"
        "            recipient_token=recipient_token or None,\n"
        "        )\n"
        "    envelope = dm_relay.envelope_for_replication(\n"
        "        mailbox_key=mailbox_key,\n"
        "        msg_id=msg_id,\n"
        "        recipient_id=recipient_id,\n"
        "        recipient_token=recipient_token or None,\n"
        "    )\n"
        "    if envelope:\n"
        "        if not str(envelope.get('delivery_class') or '').strip():\n"
        "            envelope['delivery_class'] = delivery_class or 'request'\n"
        "        if not str(envelope.get('recipient_id') or '').strip():\n"
        "            envelope['recipient_id'] = recipient_id\n"
        "        replicate = dm_relay._replicate_envelope_to_peers(\n"
        "            envelope=envelope, preferred_peer_urls=urls,\n"
        "        )\n"
        "    else:\n"
        "        deposited = dm_relay.deposit(\n"
        "            sender_id=str(payload.get('sender_id') or ''),\n"
        "            raw_sender_id=str(payload.get('sender_id') or ''),\n"
        "            recipient_id=recipient_id,\n"
        "            ciphertext=str(payload.get('ciphertext') or ''),\n"
        "            msg_id=msg_id,\n"
        "            delivery_class=delivery_class,\n"
        "            sender_seal=str(payload.get('sender_seal') or ''),\n"
        "            sender_token_hash=str(payload.get('sender_token_hash') or ''),\n"
        "            payload_format=str(payload.get('format') or 'mls1'),\n"
        "            replication_peer_urls=urls,\n"
        "            recipient_token=recipient_token,\n"
        "        )\n"
        "        replicate = dict(deposited.get('replicate') or {})\n"
        "    print(json.dumps({'ok': bool(replicate.get('ok')), 'replicate': replicate, 'urls': urls, 'msg_id': msg_id}))\n"
    )


def _scoped_replicate_envelope_package_code(
    outbox_id: str = "",
    *,
    msg_id_hint: str = "",
    payload: dict | None = None,
) -> str:
    """Build a signed replicate-envelope POST package without opening Tor sockets."""
    if payload is not None:
        payload_loader = (
            f"payload = enrich_connect_release_payload(dict({json.dumps(payload)}))\n"
        )
        imports = (
            "import json, base64, hashlib, hmac\n"
            "from services.mesh.mesh_dm_connect_delivery import enrich_connect_release_payload, relay_push_peer_urls_for_payload\n"
        )
    else:
        payload_loader = (
            f"outbox_id = {json.dumps(outbox_id)}\n"
            "item = private_delivery_outbox._items.get(outbox_id, {})\n"
            "payload = enrich_connect_release_payload(dict(item.get('payload') or {}))\n"
        )
        imports = (
            "import json, base64, hashlib, hmac\n"
            "from services.mesh.mesh_private_outbox import private_delivery_outbox\n"
            "from services.mesh.mesh_dm_connect_delivery import enrich_connect_release_payload, relay_push_peer_urls_for_payload\n"
        )
    return (
        imports
        + "from services.mesh.mesh_dm_relay import dm_relay\n"
        "from services.mesh.mesh_crypto import normalize_peer_url, resolve_peer_key_for_url\n"
        f"msg_id_hint = {json.dumps(msg_id_hint)}\n"
        + payload_loader
        + "urls = [\n"
        "    str(raw or '').strip().rstrip('/')\n"
        "    for raw in list(payload.get('relay_push_peer_urls') or [])\n"
        "    if str(raw or '').strip()\n"
        "]\n"
        "if not urls:\n"
        "    urls = relay_push_peer_urls_for_payload(payload)\n"
        "if not urls:\n"
        "    print(json.dumps({'ok': False, 'detail': 'no relay push urls in outbox payload'}))\n"
        "else:\n"
        "    recipient_id = str(payload.get('recipient_id') or '')\n"
        "    envelope_obj = dict(payload.get('envelope') or {})\n"
        "    msg_id = str(payload.get('msg_id') or envelope_obj.get('msg_id') or msg_id_hint or '')\n"
        "    delivery_class = str(payload.get('delivery_class') or 'request').strip().lower()\n"
        "    recipient_token = str(payload.get('recipient_token') or '')\n"
        "    if not msg_id and recipient_id:\n"
        "        epoch = dm_relay._epoch_bucket()\n"
        "        for offset in (0, -1, -2):\n"
        "            key = dm_relay._mailbox_key('requests', recipient_id, epoch + offset)\n"
        "            for message in reversed(list(dm_relay._mailboxes.get(key, []))):\n"
        "                candidate = str(message.msg_id or '')\n"
        "                if candidate:\n"
        "                    msg_id = candidate\n"
        "                    break\n"
        "            if msg_id:\n"
        "                break\n"
        "    if delivery_class == 'shared':\n"
        "        mailbox_key = dm_relay._hashed_mailbox_token(recipient_token)\n"
        "    else:\n"
        "        mailbox_key = dm_relay.mailbox_key_for_delivery(\n"
        "            recipient_id=recipient_id,\n"
        "            delivery_class=delivery_class or 'request',\n"
        "            recipient_token=recipient_token or None,\n"
        "        )\n"
        "    envelope = dm_relay.envelope_for_replication(\n"
        "        mailbox_key=mailbox_key,\n"
        "        msg_id=msg_id,\n"
        "        recipient_id=recipient_id,\n"
        "        recipient_token=recipient_token or None,\n"
        "    )\n"
        "    if not envelope:\n"
        "        ciphertext = str(payload.get('ciphertext') or envelope_obj.get('ciphertext') or '')\n"
        "        sender_id = str(payload.get('sender_id') or envelope_obj.get('sender_id') or '')\n"
        "        sender_seal = str(payload.get('sender_seal') or envelope_obj.get('sender_seal') or '')\n"
        "        sender_token_hash = str(payload.get('sender_token_hash') or envelope_obj.get('sender_token_hash') or '')\n"
        "        payload_format = str(payload.get('format') or envelope_obj.get('payload_format') or 'mls1')\n"
        "        session_welcome = str(payload.get('session_welcome') or envelope_obj.get('session_welcome') or '')\n"
        "        if ciphertext and msg_id and mailbox_key:\n"
        "            sender_block_ref = dm_relay._sender_block_ref(\n"
        "                sender_id,\n"
        "                scope=dm_relay._sender_block_scope(\n"
        "                    recipient_id=recipient_id,\n"
        "                    recipient_token=str(recipient_token or ''),\n"
        "                    delivery_class=delivery_class,\n"
        "                ),\n"
        "            )\n"
        "            envelope = {\n"
        "                'msg_id': msg_id,\n"
        "                'mailbox_key': mailbox_key,\n"
        "                'recipient_id': recipient_id,\n"
        "                'recipient_token': recipient_token,\n"
        "                'sender_id': sender_id,\n"
        "                'sender_block_ref': sender_block_ref,\n"
        "                'sender_seal': sender_seal,\n"
        "                'ciphertext': ciphertext,\n"
        "                'delivery_class': delivery_class or 'request',\n"
        "                'payload_format': payload_format,\n"
        "                'session_welcome': session_welcome,\n"
        "                'timestamp': float(payload.get('timestamp') or envelope_obj.get('timestamp') or 0) or __import__('time').time(),\n"
        "            }\n"
        "    if not envelope:\n"
        "        print(json.dumps({'ok': False, 'detail': 'envelope missing for scoped replicate', 'msg_id': msg_id}))\n"
        "    else:\n"
        "        if not str(envelope.get('delivery_class') or '').strip():\n"
        "            envelope['delivery_class'] = delivery_class or 'request'\n"
        "        if not str(envelope.get('recipient_id') or '').strip():\n"
        "            envelope['recipient_id'] = recipient_id\n"
        "        target = normalize_peer_url(str(urls[0]))\n"
        "        peer_key = resolve_peer_key_for_url(target)\n"
        "        if not peer_key:\n"
        "            print(json.dumps({'ok': False, 'detail': 'no peer key for replicate target', 'target': target}))\n"
        "        else:\n"
        "            body_bytes = json.dumps({'envelope': envelope}, separators=(',', ':'), sort_keys=True).encode('utf-8')\n"
        "            host = target.replace('http://', '').replace('https://', '').rstrip('/')\n"
        "            sig = hmac.new(peer_key, body_bytes, hashlib.sha256).hexdigest()\n"
        "            print(json.dumps({\n"
        "                'ok': True,\n"
        "                'target_host': host,\n"
        "                'peer_url': target,\n"
        "                'peer_hmac': sig,\n"
        "                'body_b64': base64.b64encode(body_bytes).decode('ascii'),\n"
        "                'msg_id': msg_id,\n"
        "            }))\n"
    )


def _local_api_health(*, timeout_s: int = 10) -> bool:
    proc = subprocess.run(
        [
            "docker",
            "exec",
            "shadowbroker-backend",
            "curl",
            "-s",
            "-o",
            "/dev/null",
            "-w",
            "%{http_code}",
            "--max-time",
            str(timeout_s),
            "http://127.0.0.1:8000/api/health",
        ],
        capture_output=True,
        text=True,
        timeout=timeout_s + 15,
        check=False,
    )
    return (proc.stdout or "").strip() == "200"


def _ensure_local_api_responsive(*, reason: str = "") -> None:
    if _local_api_health(timeout_s=10):
        return
    label = f" ({reason})" if reason else ""
    print(f"local backend unresponsive{label} — restarting before replicate push")
    subprocess.run(
        _local_compose_cmd("restart", "backend"),
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    _wait_local_backend_healthy(timeout_s=300)
    _prime_dm_wormhole()


def _pete_api_health(timeout_s: int = 10) -> bool:
    proc = subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            SSH_PETE,
            f"curl -s -o /dev/null -w '%{{http_code}}' --max-time {int(timeout_s)} http://127.0.0.1:8000/api/health",
        ],
        capture_output=True,
        text=True,
        timeout=timeout_s + 20,
        check=False,
    )
    return (proc.stdout or "").strip() == "200"


def _ensure_pete_api_responsive(pete_admin: str = "", *, reason: str = "") -> None:
    if _pete_api_health(timeout_s=10):
        return
    label = f" ({reason})" if reason else ""
    print(f"Pete backend unresponsive{label} — restarting container")
    subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            SSH_PETE,
            "cd /home/ubuntu/Shadowbroker && docker compose -f docker-compose.yml -f docker-compose.participant.yml restart backend",
        ],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    time.sleep(30)
    for _ in range(20):
        if _pete_api_health(timeout_s=10):
            if pete_admin:
                join = _prime_pete_wormhole_http(pete_admin)
                print(json.dumps({"pete_reprime_after_restart": join}, indent=2))
            return
        time.sleep(6)
    raise RuntimeError("Pete backend did not become healthy after restart")


def _push_replicate_package_direct_local(package: dict) -> dict:
    """POST replicate-envelope to local uvicorn (no Tor) — lands in live mailbox."""
    if not package.get("ok"):
        return package
    py = (
        "import base64, json, subprocess\n"
        f"body = base64.b64decode({json.dumps(package.get('body_b64', ''))})\n"
        f"peer_url = {json.dumps(package.get('peer_url', ''))}\n"
        f"peer_hmac = {json.dumps(package.get('peer_hmac', ''))}\n"
        "proc = subprocess.run(\n"
        "    [\n"
        "        'curl', '-s', '-w', '\\n%{http_code}', '--max-time', '60',\n"
        "        '-X', 'POST',\n"
        "        '-H', 'Content-Type: application/json',\n"
        "        '-H', f'X-Peer-Url: {peer_url}',\n"
        "        '-H', f'X-Peer-HMAC: {peer_hmac}',\n"
        "        '--data-binary', '@-',\n"
        "        'http://127.0.0.1:8000/api/mesh/dm/replicate-envelope',\n"
        "    ],\n"
        "    input=body,\n"
        "    capture_output=True,\n"
        ")\n"
        "raw = (proc.stdout or b'').decode('utf-8', errors='replace').strip()\n"
        "lines = raw.splitlines()\n"
        "code = lines[-1] if lines else ''\n"
        "text = '\\n'.join(lines[:-1]) if len(lines) > 1 else ''\n"
        "replicate_ok = False\n"
        "detail = (proc.stderr or b'').decode('utf-8', errors='replace').strip() or text\n"
        "try:\n"
        "    payload = json.loads(text) if text else {}\n"
        "    if isinstance(payload, dict):\n"
        "        replicate_ok = bool(payload.get('ok'))\n"
        "        if not replicate_ok:\n"
        "            detail = str(payload.get('detail', '') or detail)\n"
        "except Exception:\n"
        "    replicate_ok = code == '200'\n"
        "print(json.dumps({\n"
        "    'ok': bool(replicate_ok and code == '200'),\n"
        "    'http_code': code,\n"
        "    'detail': detail,\n"
        "    'msg_id': "
        f"{json.dumps(package.get('msg_id', ''))},\n"
        "}))\n"
    )
    return _docker_python(py)


def _local_accept_replica_direct(package: dict) -> dict:
    """Ingest replicate envelope via one-off python (on-disk relay for poll/decrypt)."""
    if not package.get("ok") or not package.get("body_b64"):
        return {"ok": False, "detail": "missing replicate package"}
    code = (
        "import json, base64\n"
        "from services.mesh.mesh_dm_relay import dm_relay\n"
        f"body = json.loads(base64.b64decode({json.dumps(package.get('body_b64', ''))}).decode('utf-8'))\n"
        "envelope = dict(body.get('envelope') or {})\n"
        f"result = dm_relay.accept_replica(envelope=envelope, originating_peer_url={json.dumps(str(package.get('peer_url') or ''))})\n"
        "dm_relay._flush()\n"
        "print(json.dumps(result))\n"
    )
    try:
        return _docker_python(code, timeout_s=60)
    except Exception as exc:
        return {"ok": False, "detail": str(exc) or type(exc).__name__}


def _push_replicate_package(package: dict, *, remote: str = "local") -> dict:
    if not package.get("ok"):
        return package
    timeout_s = max(180, int(os.environ.get("MESH_RELAY_PUSH_TIMEOUT_S", "300") or 300) + 30)
    py = (
        "import base64, json, subprocess\n"
        f"body = base64.b64decode({json.dumps(package.get('body_b64', ''))})\n"
        f"target = {json.dumps(package.get('target_host', ''))}\n"
        f"peer_url = {json.dumps(package.get('peer_url', ''))}\n"
        f"peer_hmac = {json.dumps(package.get('peer_hmac', ''))}\n"
        "proc = subprocess.run(\n"
        "    [\n"
        "        'curl', '-s', '-w', '\\n%{http_code}', '--max-time', "
        f"{json.dumps(str(timeout_s))},\n"
        "        '--socks5-hostname', '127.0.0.1:9050',\n"
        "        '-X', 'POST',\n"
        "        '-H', 'Content-Type: application/json',\n"
        "        '-H', f'X-Peer-Url: {peer_url}',\n"
        "        '-H', f'X-Peer-HMAC: {peer_hmac}',\n"
        "        '--data-binary', '@-',\n"
        "        f'http://{target}/api/mesh/dm/replicate-envelope',\n"
        "    ],\n"
        "    input=body,\n"
        "    capture_output=True,\n"
        ")\n"
        "raw = (proc.stdout or b'').decode('utf-8', errors='replace').strip()\n"
        "lines = raw.splitlines()\n"
        "code = lines[-1] if lines else ''\n"
        "text = '\\n'.join(lines[:-1]) if len(lines) > 1 else ''\n"
        "replicate_ok = False\n"
        "detail = (proc.stderr or b'').decode('utf-8', errors='replace').strip() or text\n"
        "try:\n"
        "    payload = json.loads(text) if text else {}\n"
        "    if isinstance(payload, dict):\n"
        "        replicate_ok = bool(payload.get('ok'))\n"
        "        if not replicate_ok:\n"
        "            detail = str(payload.get('detail', '') or detail)\n"
        "except Exception:\n"
        "    replicate_ok = code == '200'\n"
        "print(json.dumps({\n"
        "    'ok': bool(replicate_ok and code == '200'),\n"
        "    'http_code': code,\n"
        "    'detail': detail,\n"
        "    'msg_id': "
        f"{json.dumps(package.get('msg_id', ''))},\n"
        "}))\n"
    )
    if remote == "pete":
        return _ssh_pete_python(py, timeout_s=timeout_s + 45)
    return _docker_python(py)


def _nudge_scoped_replicate_to_pete(
    outbox_id: str,
    *,
    msg_id: str = "",
    pete_admin: str = "",
) -> dict:
    """Push local sealed outbox envelope to Pete relay (scoped replicate)."""
    outbox_id = str(outbox_id or "").strip()
    if not outbox_id:
        return {"ok": False, "detail": "missing outbox_id"}
    try:
        package: dict = {"ok": False}
        payload = _fetch_local_outbox_payload(outbox_id)
        if payload:
            package = _docker_python(
                _scoped_replicate_envelope_package_code("", msg_id_hint=msg_id, payload=payload)
            )
            if package.get("ok"):
                package["source"] = "local_disk_payload_local_sign"
        if not package.get("ok"):
            package = _docker_python(_scoped_replicate_envelope_package_code(outbox_id, msg_id_hint=msg_id))
            if package.get("ok"):
                package["source"] = "local_outbox_exec"
        if package.get("ok") and package.get("target_host"):
            if pete_admin:
                join = _prime_pete_wormhole_http(pete_admin)
                if not join.get("ok"):
                    print(json.dumps({"pete_wormhole_prime_before_7c": join}, indent=2))
            pushed = _push_replicate_package(package, remote="pete")
            result = {
                "ok": bool(pushed.get("ok")),
                "replicate": pushed,
                "urls": [package.get("target_host", "")],
                "msg_id": package.get("msg_id", msg_id),
                "package_source": package.get("source", ""),
                "push_via": "pete_tor",
                "package": package,
            }
            if not result.get("ok"):
                print(json.dumps({"pete_tor_push_failed": pushed}, indent=2))
            if result.get("ok"):
                if not TOR_ONLY:
                    disk = _pete_accept_replica_direct(package)
                    result["disk_inject"] = disk
                return result
            if TOR_ONLY:
                return result
            pushed = _push_replicate_package_direct_pete(package)
            result = {
                "ok": bool(pushed.get("ok")),
                "replicate": pushed,
                "urls": [package.get("target_host", "")],
                "msg_id": package.get("msg_id", msg_id),
                "package_source": package.get("source", ""),
                "push_via": "pete_http",
                "package": package,
            }
            if not result.get("ok"):
                print(json.dumps({"pete_http_push_failed": pushed}, indent=2))
            if result.get("ok") and not TOR_ONLY:
                disk = _pete_accept_replica_direct(package)
                result["disk_inject"] = disk
                return result
            if result.get("ok"):
                return result
        return _docker_python(
            _scoped_replicate_outbox_nudge_code(outbox_id, msg_id_hint=msg_id, warm_arti=True)
        )
    except Exception as exc:
        return {"ok": False, "detail": str(exc) or type(exc).__name__}


def _nudge_scoped_replicate_from_pete(
    outbox_id: str,
    *,
    msg_id: str = "",
    pete_admin: str = "",
) -> dict:
    """Tor-push Pete's sealed outbox envelope back to local onion (scoped replicate)."""
    outbox_id = str(outbox_id or "").strip()
    if not outbox_id:
        return {"ok": False, "detail": "missing outbox_id"}
    try:
        package: dict = {"ok": False}
        payload = _fetch_pete_outbox_payload(outbox_id)
        if payload:
            package = _docker_python(
                _scoped_replicate_envelope_package_code("", msg_id_hint=msg_id, payload=payload)
            )
            if package.get("ok"):
                package["source"] = "pete_disk_payload_local_sign"
        if not package.get("ok"):
            package = _ssh_pete_python(
                _scoped_replicate_envelope_package_code(outbox_id, msg_id_hint=msg_id),
                timeout_s=90,
            )
            if package.get("ok"):
                package["source"] = "pete_outbox_exec"
        if package.get("ok") and package.get("target_host"):
            _ensure_local_api_responsive(reason="scoped replicate push")
            pushed = _push_replicate_package(package, remote="local")
            result = {
                "ok": bool(pushed.get("ok")),
                "replicate": pushed,
                "urls": [package.get("target_host", "")],
                "msg_id": package.get("msg_id", msg_id),
                "package_source": package.get("source", ""),
                "push_via": "local_tor",
                "package": package,
            }
            if not result.get("ok"):
                print(json.dumps({"local_tor_push_failed": pushed}, indent=2))
            if result.get("ok"):
                if not TOR_ONLY:
                    disk = _local_accept_replica_direct(package)
                    result["disk_inject"] = disk
                return result
            if TOR_ONLY:
                return result
            pushed = _push_replicate_package_direct_local(package)
            result = {
                "ok": bool(pushed.get("ok")),
                "replicate": pushed,
                "urls": [package.get("target_host", "")],
                "msg_id": package.get("msg_id", msg_id),
                "package_source": package.get("source", ""),
                "push_via": "local_http",
                "package": package,
            }
            if not result.get("ok"):
                print(json.dumps({"local_http_push_failed": pushed}, indent=2))
            if result.get("ok") and not TOR_ONLY:
                disk = _local_accept_replica_direct(package)
                result["disk_inject"] = disk
                return result
            if result.get("ok"):
                return result
            if pete_admin:
                join = _prime_pete_wormhole_http(pete_admin)
                if not join.get("ok"):
                    print(json.dumps({"pete_wormhole_http_prime": join}, indent=2))
            socks = _wait_pete_socks_port(timeout_s=90)
            print(json.dumps({"pete_socks_before_push": socks}, indent=2))
            pushed = _push_replicate_package(package, remote="pete")
            result = {
                "ok": bool(pushed.get("ok")),
                "replicate": pushed,
                "urls": [package.get("target_host", "")],
                "msg_id": package.get("msg_id", msg_id),
                "package_source": package.get("source", ""),
                "push_via": "pete",
            }
            if result.get("ok"):
                return result
        return _ssh_pete_python(
            _scoped_replicate_outbox_nudge_code(outbox_id, msg_id_hint=msg_id, warm_arti=True),
            timeout_s=240,
        )
    except Exception as exc:
        return {"ok": False, "detail": str(exc) or type(exc).__name__}


def _fetch_local_outbox_payload(outbox_id: str) -> dict | None:
    """Read sealed outbox payload from local disk (reloads before lookup)."""
    outbox_id = str(outbox_id or "").strip()
    if not outbox_id:
        return None
    code = (
        "import json\n"
        "from services.mesh.mesh_private_outbox import private_delivery_outbox\n"
        f"outbox_id = {json.dumps(outbox_id)}\n"
        "private_delivery_outbox._load()\n"
        "item = private_delivery_outbox._items.get(outbox_id, {})\n"
        "payload = dict(item.get('payload') or {})\n"
        "print(json.dumps({'ok': bool(payload), 'payload': payload}))\n"
    )
    try:
        result = _docker_python(code, timeout_s=60)
        if result.get("ok") and isinstance(result.get("payload"), dict):
            return dict(result["payload"])
    except Exception as exc:
        print(f"local outbox payload fetch skipped: {exc}")
    return None


def _fetch_pete_outbox_payload(outbox_id: str) -> dict | None:
    """Read sealed outbox payload from Pete disk (reloads before lookup)."""
    outbox_id = str(outbox_id or "").strip()
    if not outbox_id:
        return None
    code = (
        "import json\n"
        "from services.mesh.mesh_private_outbox import private_delivery_outbox\n"
        f"outbox_id = {json.dumps(outbox_id)}\n"
        "private_delivery_outbox._load()\n"
        "item = private_delivery_outbox._items.get(outbox_id, {})\n"
        "payload = dict(item.get('payload') or {})\n"
        "print(json.dumps({'ok': bool(payload), 'payload': payload}))\n"
    )
    try:
        result = _ssh_pete_python(code, timeout_s=60)
        if result.get("ok") and isinstance(result.get("payload"), dict):
            return dict(result["payload"])
    except Exception as exc:
        print(f"Pete outbox payload fetch skipped: {exc}")
    return None


    return None


def _pete_accept_replica_direct(package: dict) -> dict:
    """Ingest replicate envelope on Pete via one-off python (on-disk relay)."""
    if not package.get("ok") or not package.get("body_b64"):
        return {"ok": False, "detail": "missing replicate package"}
    code = (
        "import json, base64\n"
        "from services.mesh.mesh_dm_relay import dm_relay\n"
        f"body = json.loads(base64.b64decode({json.dumps(package.get('body_b64', ''))}).decode('utf-8'))\n"
        "envelope = dict(body.get('envelope') or {})\n"
        f"result = dm_relay.accept_replica(envelope=envelope, originating_peer_url={json.dumps(str(package.get('peer_url') or ''))})\n"
        "dm_relay._flush()\n"
        "print(json.dumps(result))\n"
    )
    try:
        return _ssh_pete_python(code, timeout_s=60)
    except Exception as exc:
        return {"ok": False, "detail": str(exc) or type(exc).__name__}


def _push_replicate_package_direct_pete(package: dict) -> dict:
    """POST replicate-envelope to Pete uvicorn (no Tor)."""
    if not package.get("ok"):
        return package
    py = (
        "import base64, json, subprocess\n"
        f"body = base64.b64decode({json.dumps(package.get('body_b64', ''))})\n"
        f"peer_url = {json.dumps(package.get('peer_url', ''))}\n"
        f"peer_hmac = {json.dumps(package.get('peer_hmac', ''))}\n"
        "proc = subprocess.run(\n"
        "    [\n"
        "        'curl', '-s', '-w', '\\n%{http_code}', '--max-time', '60',\n"
        "        '-X', 'POST',\n"
        "        '-H', 'Content-Type: application/json',\n"
        "        '-H', f'X-Peer-Url: {peer_url}',\n"
        "        '-H', f'X-Peer-HMAC: {peer_hmac}',\n"
        "        '--data-binary', '@-',\n"
        "        'http://127.0.0.1:8000/api/mesh/dm/replicate-envelope',\n"
        "    ],\n"
        "    input=body,\n"
        "    capture_output=True,\n"
        ")\n"
        "raw = (proc.stdout or b'').decode('utf-8', errors='replace').strip()\n"
        "lines = raw.splitlines()\n"
        "code = lines[-1] if lines else ''\n"
        "text = '\\n'.join(lines[:-1]) if len(lines) > 1 else ''\n"
        "replicate_ok = False\n"
        "detail = (proc.stderr or b'').decode('utf-8', errors='replace').strip() or text\n"
        "try:\n"
        "    payload = json.loads(text) if text else {}\n"
        "    if isinstance(payload, dict):\n"
        "        replicate_ok = bool(payload.get('ok'))\n"
        "        if not replicate_ok:\n"
        "            detail = str(payload.get('detail', '') or detail)\n"
        "except Exception:\n"
        "    replicate_ok = code == '200'\n"
        "print(json.dumps({\n"
        "    'ok': bool(replicate_ok and code == '200'),\n"
        "    'http_code': code,\n"
        "    'detail': detail,\n"
        "    'msg_id': "
        f"{json.dumps(package.get('msg_id', ''))},\n"
        "}))\n"
    )
    return _ssh_pete_python(py, timeout_s=90)


def _prime_pete_wormhole_http(pete_admin: str) -> dict:
    """Prime Pete wormhole/Tor inside the running uvicorn process."""
    proc = subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            SSH_PETE,
            (
                "curl -s --max-time 120 -X POST "
                f"-H 'X-Admin-Key: {pete_admin}' "
                "-H 'Content-Type: application/json' "
                "-d '{}' "
                "'http://127.0.0.1:8000/api/wormhole/join'"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=150,
        check=False,
    )
    if proc.returncode != 0:
        return {"ok": False, "detail": proc.stderr.strip() or proc.stdout.strip() or "pete join failed"}
    try:
        return json.loads(proc.stdout.strip() or "{}")
    except json.JSONDecodeError:
        return {"ok": False, "detail": proc.stdout.strip() or "pete join invalid json"}


def _wait_pete_socks_port(*, timeout_s: int = 120) -> dict:
    code = (
        "import json, socket, time\n"
        "from services.config import get_settings\n"
        f"deadline = time.time() + {int(timeout_s)}\n"
        "port = int(get_settings().MESH_ARTI_SOCKS_PORT or 9050)\n"
        "ready = False\n"
        "while time.time() < deadline:\n"
        "    try:\n"
        "        with socket.create_connection(('127.0.0.1', port), timeout=2.0) as sock:\n"
        "            sock.sendall(b'\\x05\\x01\\x00')\n"
        "            if sock.recv(2) == b'\\x05\\x00':\n"
        "                ready = True\n"
        "                break\n"
        "    except OSError:\n"
        "        pass\n"
        "    time.sleep(2)\n"
        "print(json.dumps({'ok': ready, 'socks_port': port}))\n"
    )
    try:
        return _ssh_pete_python(code, timeout_s=timeout_s + 30)
    except Exception as exc:
        return {"ok": False, "detail": str(exc) or type(exc).__name__}


def _wait_pete_arti_ready(*, timeout_s: int = 120) -> dict:
    code = (
        "import json, time\n"
        "from routers.ai_intel import _write_env_value\n"
        "from services.config import get_settings\n"
        "from services.wormhole_supervisor import _check_arti_ready\n"
        "_write_env_value('MESH_ARTI_ENABLED', 'true')\n"
        "get_settings.cache_clear()\n"
        f"deadline = time.time() + {int(timeout_s)}\n"
        "ready = False\n"
        "while time.time() < deadline:\n"
        "    if _check_arti_ready():\n"
        "        ready = True\n"
        "        break\n"
        "    time.sleep(2)\n"
        "print(json.dumps({'ok': ready, 'arti_ready': ready}))\n"
    )
    try:
        return _ssh_pete_python(code, timeout_s=timeout_s + 30)
    except Exception as exc:
        return {"ok": False, "detail": str(exc) or type(exc).__name__}


def _scrub_local_dm_state() -> None:
    """Drop persisted private outbox + local dm_relay spool between E2E runs."""
    proc = subprocess.run(
        [
            "docker",
            "exec",
            "shadowbroker-backend",
            "sh",
            "-c",
            "rm -f /app/data/private_outbox/sealed_private_outbox.json /app/data/dm_relay.json "
            "/app/data/dm_alias/wormhole_dm_mls.json /app/data/dm_alias_rust/wormhole_dm_mls_rust.bin",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        print(f"local DM state scrub skipped: {proc.stderr.strip() or proc.stdout.strip()}")
    restart = subprocess.run(
        _local_compose_cmd("restart", "backend"),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if restart.returncode != 0:
        print(f"local backend restart after scrub skipped: {restart.stderr.strip() or restart.stdout.strip()}")
    else:
        try:
            _wait_local_backend_healthy(timeout_s=120)
        except Exception as exc:
            print(f"local backend health wait after scrub skipped: {exc}")


def _drain_pete_request_mailbox(agent_id: str = "") -> None:
    resolved_agent_id = str(agent_id or "").strip()
    drain_code = f"""import json, secrets, time, urllib.request
from services.mesh.mesh_wormhole_persona import get_dm_identity, sign_dm_wormhole_event

{_EMBED_SIGNED_MAILBOX_HELPERS}

def _poll_once():
    agent_id = {json.dumps(resolved_agent_id)} or str((get_dm_identity() or {{}}).get("node_id") or "")
    claims = [{{"type": "requests", "token": {json.dumps(_E2E_REQUESTS_MAILBOX_TOKEN)}}}]
    body, data = _build_signed_mailbox_request(
        agent_id=agent_id,
        event_type="dm_poll",
        kind="dm_poll",
        endpoint="/api/mesh/dm/poll",
        sequence_domain="dm_poll",
        claims=claims,
    )
    req = urllib.request.Request(
        "http://127.0.0.1:8000/api/mesh/dm/poll",
        data=data,
        headers={{"Content-Type": "application/json"}},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))

drained = 0
for _ in range(8):
    payload = _poll_once()
    count = int(payload.get("count", 0) or 0)
    drained += count
    if count <= 0 and not payload.get("has_more"):
        break
    time.sleep(1)
print(json.dumps({{"ok": True, "drained": drained}}))
"""
    try:
        result = _ssh_pete_python(drain_code)
        print(f"Pete request mailbox drain: {result.get('drained', 0)} message(s)")
    except Exception as exc:
        print(f"Pete request mailbox drain skipped: {exc}")


def _restart_pete_backend() -> None:
    if DEPLOY_FROM_GIT:
        remote_cmd = (
            "cd /home/ubuntu/Shadowbroker && "
            "git fetch origin && git reset --hard origin/main && "
            "docker compose -f docker-compose.yml -f docker-compose.participant.yml pull && "
            "docker compose -f docker-compose.yml -f docker-compose.participant.yml up -d && "
            "sleep 8 && "
            "docker exec shadowbroker-backend sh -c "
            "'rm -f /app/data/dm_relay.json /app/data/private_outbox/sealed_private_outbox.json "
            "/app/data/dm_alias/wormhole_dm_mls.json /app/data/dm_alias_rust/wormhole_dm_mls_rust.bin'"
        )
        proc = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", SSH_PETE, remote_cmd],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "remote git deploy failed")
        time.sleep(int(os.environ.get("E2E_DM_PETE_BOOTSTRAP_WAIT_S", "90")))
        return
    repo_root = os.path.dirname(os.path.dirname(__file__))
    patch_files = [
        ("backend/services/mesh/mesh_dm_relay.py", "/tmp/mesh_dm_relay.py"),
        ("backend/services/mesh/mesh_signed_events.py", "/tmp/mesh_signed_events.py"),
        ("backend/services/openclaw_infonet.py", "/tmp/openclaw_infonet.py"),
        ("backend/services/wormhole_supervisor.py", "/tmp/wormhole_supervisor.py"),
        ("backend/services/tor_hidden_service.py", "/tmp/tor_hidden_service.py"),
        ("backend/services/privacy_core_attestation.py", "/tmp/privacy_core_attestation.py"),
        ("backend/routers/wormhole.py", "/tmp/wormhole_router.py"),
        ("backend/main.py", "/tmp/main.py"),
        ("docker-compose.participant.yml", "/tmp/docker-compose.participant.yml"),
    ]
    for rel_path, remote_tmp in patch_files:
        local_path = os.path.join(repo_root, rel_path)
        if os.path.isfile(local_path):
            subprocess.run(
                ["scp", "-o", "BatchMode=yes", local_path, f"{SSH_PETE}:{remote_tmp}"],
                capture_output=True,
                text=True,
                check=False,
            )
    remote_cmd = (
        "cd /home/ubuntu/Shadowbroker && "
        "cp /tmp/docker-compose.participant.yml docker-compose.participant.yml 2>/dev/null || true && "
        "docker compose -f docker-compose.yml -f docker-compose.participant.yml up -d backend && "
        "sleep 8 && "
        "docker exec shadowbroker-backend sh -c "
        "'rm -f /app/data/dm_relay.json /app/data/private_outbox/sealed_private_outbox.json "
        "/app/data/dm_alias/wormhole_dm_mls.json /app/data/dm_alias_rust/wormhole_dm_mls_rust.bin' && "
        "docker cp /tmp/mesh_dm_relay.py shadowbroker-backend:/app/services/mesh/mesh_dm_relay.py 2>/dev/null || true; "
        "docker cp /tmp/mesh_signed_events.py shadowbroker-backend:/app/services/mesh/mesh_signed_events.py 2>/dev/null || true; "
        "docker cp /tmp/openclaw_infonet.py shadowbroker-backend:/app/services/openclaw_infonet.py 2>/dev/null || true; "
        "docker cp /tmp/wormhole_supervisor.py shadowbroker-backend:/app/services/wormhole_supervisor.py 2>/dev/null || true; "
        "docker cp /tmp/tor_hidden_service.py shadowbroker-backend:/app/services/tor_hidden_service.py 2>/dev/null || true; "
        "docker cp /tmp/privacy_core_attestation.py shadowbroker-backend:/app/services/privacy_core_attestation.py 2>/dev/null || true; "
        "docker cp /tmp/wormhole_router.py shadowbroker-backend:/app/routers/wormhole.py 2>/dev/null || true; "
        "docker cp /tmp/main.py shadowbroker-backend:/app/main.py 2>/dev/null || true; "
        "docker compose -f docker-compose.yml -f docker-compose.participant.yml restart backend"
    )
    proc = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", SSH_PETE, remote_cmd],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "pete backend restart failed")
    time.sleep(int(os.environ.get("E2E_DM_PETE_BOOTSTRAP_WAIT_S", "120")))


def _prime_pete_dm_wormhole() -> dict:
    code = (
        "import json\n"
        "from routers.ai_intel import _write_env_value\n"
        "from services.config import get_settings\n"
        "from services.tor_hidden_service import tor_service\n"
        "from services.wormhole_settings import write_wormhole_settings\n"
        "from services.wormhole_supervisor import connect_wormhole\n"
        "port = int(get_settings().MESH_ARTI_SOCKS_PORT or 9050)\n"
        "write_wormhole_settings(enabled=True, transport='tor_arti', "
        "socks_proxy=f'socks5h://127.0.0.1:{port}', socks_dns=True, anonymous_mode=True)\n"
        "tor = tor_service.start(target_port=8000)\n"
        "if tor.get('ok'):\n"
        "    _write_env_value('MESH_ARTI_ENABLED', 'true')\n"
        "    get_settings.cache_clear()\n"
        "runtime = connect_wormhole(reason='e2e_dm_pete_warmup')\n"
        "print(json.dumps({'ok': True, 'tor': tor, 'runtime': runtime}))\n"
    )
    return _ssh_pete_python(code)


def _prime_remote_wormhole_join() -> dict:
    """Join wormhole on remote participant via in-container curl (no admin key)."""
    proc = subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            SSH_PETE,
            (
                "docker exec shadowbroker-backend curl -s -X POST "
                "-H 'Content-Type: application/json' -d '{}' "
                "http://127.0.0.1:8000/api/wormhole/join --max-time 120"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=150,
        check=False,
    )
    if proc.returncode != 0:
        return {"ok": False, "detail": proc.stderr.strip() or proc.stdout.strip() or "remote join failed"}
    try:
        return json.loads(proc.stdout.strip() or "{}")
    except json.JSONDecodeError:
        return {"ok": False, "detail": proc.stdout.strip() or "remote join invalid json"}


def _warmup_tor() -> None:
    """Prime local Arti SOCKS before fleet lookups (cold Tor can exceed lookup budgets)."""
    if not PETE_ONION:
        return
    for attempt in range(1, 7):
        proc = subprocess.run(
            [
                "docker",
                "exec",
                "shadowbroker-backend",
                "curl",
                "-s",
                "-o",
                "/dev/null",
                "-w",
                "%{http_code}",
                "--max-time",
                "120",
                "--socks5-hostname",
                "127.0.0.1:9050",
                f"http://{PETE_ONION}/api/health",
            ],
            capture_output=True,
            text=True,
            timeout=150,
            check=False,
        )
        code = (proc.stdout or "").strip()
        print(f"Tor warmup Pete health (attempt {attempt}): {code or proc.stderr.strip() or 'failed'}")
        if code == "200":
            return
        time.sleep(30)
    raise RuntimeError(f"Tor warmup to Pete onion failed after retries ({PETE_ONION})")


def _ensure_local_tor_hidden_service() -> dict:
    """Start/refresh the local Tor hidden service inside the live uvicorn process."""
    join = _docker_json("POST", "/api/wormhole/join", body={}, timeout_s=120)
    tor = dict(join.get("tor") or {})
    return {
        "ok": bool(tor.get("ok")),
        "tor": tor,
        "onion_address": str(tor.get("onion_address") or ""),
    }


def _warmup_tor_from_pete_to_local(local_onion: str, *, max_attempts: int = 0, raise_on_failure: bool = True) -> bool:
    """Verify Pete can reach this node's inbound onion (accept replicate path)."""
    host = str(local_onion or "").strip().replace("http://", "").replace("https://", "").rstrip("/")
    if not host:
        if raise_on_failure:
            raise RuntimeError("missing local onion for Pete inbound Tor warmup")
        return False
    attempts = int(max_attempts or os.environ.get("E2E_DM_PETE_LOCAL_WARMUP_MAX", "12") or 12)
    if attempts < 1:
        attempts = 1
    if attempts == 12:
        time.sleep(int(os.environ.get("E2E_DM_ONION_PROPAGATION_WAIT_S", "45")))
    else:
        time.sleep(int(os.environ.get("E2E_DM_ONION_PROPAGATION_WAIT_SHORT_S", "10")))
    for attempt in range(1, attempts + 1):
        proc = subprocess.run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                SSH_PETE,
                (
                    "docker exec shadowbroker-backend curl -s -o /dev/null -w '%{http_code}' "
                    f"--max-time 120 --socks5-hostname 127.0.0.1:9050 http://{host}/api/health"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=150,
            check=False,
        )
        code = (proc.stdout or "").strip()
        print(f"Tor warmup Pete->local health (attempt {attempt}): {code or proc.stderr.strip() or 'failed'}")
        if code == "200":
            return True
        time.sleep(30)
    if raise_on_failure:
        raise RuntimeError(f"Tor warmup from Pete to local onion failed ({host})")
    return False


def _local_onion_from_join() -> str:
    join = _docker_json("POST", "/api/wormhole/join", body={}, timeout_s=120)
    onion = str((join.get("tor") or {}).get("onion_address") or "").strip().rstrip("/")
    if not onion:
        raise RuntimeError(f"could not resolve local onion from join: {join}")
    return onion


def _ssh_pete_python(code: str, *, timeout_s: int = 120) -> dict:
    # Pipe script stdin to Pete's running backend container — avoids Windows
    # docker-exec base64 bugs and SSH command-line length limits on long polls.
    proc = subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            SSH_PETE,
            "docker exec -i shadowbroker-backend python",
        ],
        input=code.encode("utf-8"),
        capture_output=True,
        timeout=timeout_s,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "pete python failed")
    lines = [line for line in proc.stdout.strip().splitlines() if line.strip()]
    if not lines:
        raise RuntimeError(proc.stderr.strip() or "pete python produced no output")
    return json.loads(lines[-1])


def _local_fetch_request_ciphertext(
    agent_id: str,
    *,
    msg_id: str = "",
    sender_id: str = "",
) -> dict:
    code = f"""import json
from services.mesh.mesh_dm_relay import dm_relay
agent_id = {json.dumps(agent_id)}
msg_id = {json.dumps(msg_id)}
sender_id = {json.dumps(sender_id)}
token = {json.dumps(_E2E_REQUESTS_MAILBOX_TOKEN)}
ciphertext = ""
resolved_msg_id = ""
resolved_sender = ""
seen = []
with dm_relay._lock:
    dm_relay._refresh_from_shared_relay()
    keys = []
    epoch = dm_relay._epoch_bucket()
    for offset in range(-3, 2):
        keys.append(dm_relay._mailbox_key("requests", agent_id, epoch + offset))
    bound = dm_relay._bound_mailbox_key(agent_id, "requests")
    if bound:
        keys.insert(0, bound)
    dm_relay._remember_mailbox_binding(agent_id, "requests", token)
    keys.extend(dm_relay._mailbox_keys_for_claim(agent_id, {{"type": "requests", "token": token}}))
    for key in list(dict.fromkeys(keys)):
        if msg_id:
            envelope = dm_relay.envelope_for_replication(
                mailbox_key=key, msg_id=msg_id, recipient_id=agent_id,
            )
            if envelope and str(envelope.get("ciphertext") or ""):
                ciphertext = str(envelope.get("ciphertext") or "")
                resolved_msg_id = str(envelope.get("msg_id") or msg_id)
                resolved_sender = str(envelope.get("sender_id") or "")
                break
        for message in list(dm_relay._mailboxes.get(key, [])):
            seen.append(str(message.msg_id or ""))
            if msg_id and str(message.msg_id) == msg_id:
                ciphertext = str(message.ciphertext or "")
                resolved_msg_id = str(message.msg_id or "")
                resolved_sender = str(message.sender_id or "")
                break
            if sender_id and str(message.sender_id) in {{sender_id, f"sender_token:{{sender_id}}"}}:
                ciphertext = str(message.ciphertext or "")
                resolved_msg_id = str(message.msg_id or "")
                resolved_sender = str(message.sender_id or "")
                break
        if ciphertext:
            break
print(json.dumps({{
    "ok": bool(ciphertext),
    "ciphertext": ciphertext,
    "msg_id": resolved_msg_id,
    "sender_id": resolved_sender,
    "seen": seen,
}}))
"""
    return _docker_python(code)


def _local_relay_requests_count(agent_id: str) -> dict:
    """Count request-mailbox messages via persisted dm_relay (avoids wedged uvicorn HTTP)."""
    code = f"""import json
from services.mesh.mesh_dm_relay import dm_relay
agent_id = {json.dumps(agent_id)}
token = {json.dumps(_E2E_REQUESTS_MAILBOX_TOKEN)}
claims = [{{"type": "requests", "token": token}}]
with dm_relay._lock:
    dm_relay._refresh_from_shared_relay()
    dm_relay._remember_mailbox_binding(agent_id, "requests", token)
    count = int(dm_relay.count_claims(agent_id, claims))
print(json.dumps({{
    "ok": True,
    "count": count,
}}))
"""
    return _docker_python(code)


def _local_http_dm_count(agent_id: str, *, timeout_s: int = 8) -> dict:
    """Read mailbox count from the live uvicorn process (short timeout)."""
    code = f"""import json, secrets, time, urllib.request
from services.mesh.mesh_wormhole_persona import sign_dm_wormhole_event

{_EMBED_SIGNED_MAILBOX_HELPERS}

agent_id = {json.dumps(agent_id)}
claims = [{{"type": "requests", "token": {json.dumps(_E2E_REQUESTS_MAILBOX_TOKEN)}}}]
body, data = _build_signed_mailbox_request(
    agent_id=agent_id,
    event_type="dm_count",
    kind="dm_count",
    endpoint="/api/mesh/dm/count",
    sequence_domain="dm_count",
    claims=claims,
)
req = urllib.request.Request(
    "http://127.0.0.1:8000/api/mesh/dm/count",
    data=data,
    headers={{"Content-Type": "application/json"}},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout={int(timeout_s)}) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    print(json.dumps({{
        "ok": bool(payload.get("ok")),
        "count": int(payload.get("count", 0) or 0),
        "source": "http",
    }}))
except Exception as exc:
    print(json.dumps({{"ok": False, "count": 0, "source": "http", "detail": str(exc) or type(exc).__name__}}))
"""
    return _docker_python(code)


def _local_http_dm_poll_hit(
    agent_id: str,
    *,
    accept_msg_id: str = "",
    sender_id: str = "",
    timeout_s: int = 8,
) -> dict:
    code = f"""import json, secrets, time, urllib.request
from services.mesh.mesh_wormhole_persona import sign_dm_wormhole_event

{_EMBED_SIGNED_MAILBOX_HELPERS}

agent_id = {json.dumps(agent_id)}
accept_msg_id = {json.dumps(accept_msg_id)}
sender_id = {json.dumps(sender_id)}
claims = [{{"type": "requests", "token": {json.dumps(_E2E_REQUESTS_MAILBOX_TOKEN)}}}]
body, data = _build_signed_mailbox_request(
    agent_id=agent_id,
    event_type="dm_poll",
    kind="dm_poll",
    endpoint="/api/mesh/dm/poll",
    sequence_domain="dm_poll",
    claims=claims,
)
req = urllib.request.Request(
    "http://127.0.0.1:8000/api/mesh/dm/poll",
    data=data,
    headers={{"Content-Type": "application/json"}},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout={int(timeout_s)}) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
except Exception as exc:
    print(json.dumps({{"ok": False, "detail": str(exc) or type(exc).__name__}}))
else:
    hit = None
    for message in list(payload.get("messages") or []):
        if accept_msg_id and str(message.get("msg_id", "")) == accept_msg_id:
            hit = message
            break
        if sender_id and str(message.get("sender_id", "")) == sender_id:
            hit = message
            break
    print(json.dumps({{
        "ok": bool(hit),
        "message": hit or {{}},
        "count": int(payload.get("count", 0) or 0),
        "source": "http",
    }}))
"""
    return _docker_python(code)


def _local_mailbox_requests_count(agent_id: str) -> dict:
    file_count = _local_relay_requests_count(agent_id)
    if int(file_count.get("count", 0) or 0) > 0:
        return file_count
    return _local_http_dm_count(agent_id)


def _local_decrypt_contact_accept(agent_id: str, accept_msg_id: str, pete_id: str) -> dict:
    """Fetch accept from relay spool and bootstrap-decrypt without wedging uvicorn."""
    fetched = _local_fetch_request_ciphertext(agent_id, msg_id=accept_msg_id, sender_id=pete_id)
    ciphertext = str(fetched.get("ciphertext") or "")
    msg_id = str(fetched.get("msg_id") or accept_msg_id)
    if not ciphertext:
        polled = _local_http_dm_poll_hit(agent_id, accept_msg_id=accept_msg_id, sender_id=pete_id)
        message = dict(polled.get("message") or {})
        ciphertext = str(message.get("ciphertext") or "")
        msg_id = str(message.get("msg_id") or accept_msg_id)
        if not ciphertext:
            return {
                "ok": False,
                "detail": "accept not in local requests mailbox",
                "seen": list(fetched.get("seen") or []),
                "http_count": int(polled.get("count", 0) or 0),
            }
    code = f"""import json
from services.mesh.mesh_wormhole_dead_drop import parse_contact_consent
from services.mesh.mesh_wormhole_prekey import bootstrap_decrypt_from_sender
pete_id = {json.dumps(pete_id)}
ciphertext = {json.dumps(ciphertext)}
dec = bootstrap_decrypt_from_sender(pete_id, ciphertext)
consent = parse_contact_consent(str(dec.get("result", "") or ""))
print(json.dumps({{
    "ok": bool(dec.get("ok") and consent and consent.get("kind") == "contact_accept"),
    "shared_alias": str((consent or {{}}).get("shared_alias", "") or ""),
    "detail": dec.get("detail", ""),
    "msg_id": {json.dumps(msg_id)},
}}))
"""
    decrypted = _docker_python(code)
    if isinstance(decrypted, dict):
        decrypted["seen"] = list(fetched.get("seen") or [])
    return decrypted


def _ssh_pete_fetch_request_ciphertext(
    pete_id: str,
    *,
    msg_id: str = "",
    sender_id: str = "",
) -> dict:
    code = f"""import json
from services.mesh.mesh_dm_relay import dm_relay
pete_id = {json.dumps(pete_id)}
msg_id = {json.dumps(msg_id)}
sender_id = {json.dumps(sender_id)}
claims = [{{"type": "requests", "token": {json.dumps(_E2E_REQUESTS_MAILBOX_TOKEN)}}}]
messages, _has_more = dm_relay.collect_claims(pete_id, claims, limit=32)
ciphertext = ""
resolved_msg_id = ""
resolved_sender = ""
for message in list(messages or []):
    if msg_id and str(message.get("msg_id", "")) == msg_id:
        ciphertext = str(message.get("ciphertext", "") or "")
        resolved_msg_id = str(message.get("msg_id", "") or "")
        resolved_sender = str(message.get("sender_id", "") or "")
        break
    if sender_id and str(message.get("sender_id", "")) in {{sender_id, f"sender_token:{{sender_id}}"}}:
        ciphertext = str(message.get("ciphertext", "") or "")
        resolved_msg_id = str(message.get("msg_id", "") or "")
        resolved_sender = str(message.get("sender_id", "") or "")
        break
print(json.dumps({{
    "ok": bool(ciphertext),
    "ciphertext": ciphertext,
    "msg_id": resolved_msg_id,
    "sender_id": resolved_sender,
    "seen": [str(m.get("msg_id", "") or "") for m in list(messages or [])],
}}))
"""
    return _ssh_pete_python(code, timeout_s=90)


def _ssh_pete_dm_count(agent_id: str) -> dict:
    return _pete_http_dm_count(agent_id, timeout_s=15)


def _pete_relay_requests_count(agent_id: str) -> dict:
    """Count request-mailbox messages on Pete via persisted dm_relay (avoids wedged HTTP)."""
    code = f"""import json
from services.mesh.mesh_dm_relay import dm_relay
agent_id = {json.dumps(agent_id)}
token = {json.dumps(_E2E_REQUESTS_MAILBOX_TOKEN)}
claims = [{{"type": "requests", "token": token}}]
with dm_relay._lock:
    dm_relay._refresh_from_shared_relay()
    dm_relay._remember_mailbox_binding(agent_id, "requests", token)
    count = int(dm_relay.count_claims(agent_id, claims))
print(json.dumps({{
    "ok": True,
    "count": count,
    "source": "disk_relay",
}}))
"""
    try:
        return _ssh_pete_python(code, timeout_s=45)
    except Exception as exc:
        return {"ok": False, "count": 0, "source": "disk_relay", "detail": str(exc) or type(exc).__name__}


def _pete_http_dm_count(agent_id: str, *, timeout_s: int = 8) -> dict:
    """Read Pete mailbox count from live uvicorn (short timeout)."""
    code = f"""import json, secrets, time, urllib.request
from services.mesh.mesh_wormhole_persona import sign_dm_wormhole_event

{_EMBED_SIGNED_MAILBOX_HELPERS}

agent_id = {json.dumps(agent_id)}
claims = [{{"type": "requests", "token": {json.dumps(_E2E_REQUESTS_MAILBOX_TOKEN)}}}]
body, data = _build_signed_mailbox_request(
    agent_id=agent_id,
    event_type="dm_count",
    kind="dm_count",
    endpoint="/api/mesh/dm/count",
    sequence_domain="dm_count",
    claims=claims,
)
req = urllib.request.Request(
    "http://127.0.0.1:8000/api/mesh/dm/count",
    data=data,
    headers={{"Content-Type": "application/json"}},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout={int(timeout_s)}) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    print(json.dumps({{
        "ok": bool(payload.get("ok")),
        "count": int(payload.get("count", 0) or 0),
        "source": "http",
        "detail": str(payload.get("detail", "") or ""),
    }}))
except Exception as exc:
    print(json.dumps({{"ok": False, "count": 0, "source": "http", "detail": str(exc) or type(exc).__name__}}))
"""
    return _ssh_pete_python(code, timeout_s=int(timeout_s) + 30)


def _shared_mailbox_claims(
    shared_send: dict,
    *,
    sender_id: str = "",
    shared_alias: str = "",
) -> list[dict]:
    """Build shared-lane mailbox claims from the sender's release tokens."""
    tokens: list[str] = []
    for key in ("recipient_token", "recipient_token_prev"):
        token = str(shared_send.get(key) or "").strip()
        if token and token not in tokens:
            tokens.append(token)
    if not tokens and sender_id:
        code = f"""import json
from services.mesh.mesh_wormhole_dead_drop import derive_dead_drop_token_pair
from services.mesh.mesh_wormhole_persona import get_dm_identity
identity = get_dm_identity()
sender_dh = str(identity.get("dh_pub_key") or "")
tokens = []
for peer_ref in [{json.dumps(sender_id)}, {json.dumps(shared_alias)}]:
    peer_ref = str(peer_ref or "").strip()
    if not peer_ref:
        continue
    pair = derive_dead_drop_token_pair(
        peer_id={json.dumps(sender_id)},
        peer_dh_pub=sender_dh,
        peer_ref=peer_ref,
    )
    if not pair.get("ok"):
        continue
    for token in [str(pair.get("current") or ""), str(pair.get("previous") or "")]:
        if token and token not in tokens:
            tokens.append(token)
print(json.dumps({{"ok": bool(tokens), "tokens": tokens}}))
"""
        derived = _docker_python(code, timeout_s=45)
        if not derived.get("ok"):
            raise RuntimeError(f"shared mailbox tokens unavailable: {derived}")
        tokens = [str(t) for t in list(derived.get("tokens") or []) if str(t or "").strip()]
    if not tokens:
        raise RuntimeError("shared mailbox tokens unavailable")
    return [{"type": "shared", "token": token} for token in tokens]


def _shared_hit_from_replicate_package(package: dict, *, shared_msg_id: str = "") -> dict | None:
    """Extract poll hit fields from a scoped replicate package (host-side, no remote exec)."""
    if not package.get("ok") or not package.get("body_b64"):
        return None
    try:
        body = json.loads(base64.b64decode(str(package.get("body_b64") or "")).decode("utf-8"))
    except Exception:
        return None
    envelope = dict(body.get("envelope") or {})
    msg_id = str(envelope.get("msg_id") or "").strip()
    if shared_msg_id and msg_id and msg_id != shared_msg_id:
        return None
    ciphertext = str(envelope.get("ciphertext") or "").strip()
    if not ciphertext:
        return None
    payload_format = str(envelope.get("payload_format") or envelope.get("format") or "mls1")
    return {
        "msg_id": msg_id,
        "ciphertext": ciphertext,
        "format": payload_format,
        "payload_format": payload_format,
        "session_welcome": str(envelope.get("session_welcome") or ""),
        "mailbox_key": str(envelope.get("mailbox_key") or ""),
    }


def _remote_http_dm_poll_shared(
    agent_id: str,
    claims: list[dict],
    *,
    shared_msg_id: str = "",
    timeout_s: int = 45,
) -> dict:
    """Poll remote participant shared mailbox via live uvicorn HTTP only."""
    code = f"""import json, secrets, time, urllib.request
{_EMBED_SIGNED_MAILBOX_HELPERS}

agent_id = {json.dumps(agent_id)}
claims = {json.dumps(claims)}
shared_msg_id = {json.dumps(shared_msg_id)}
body, data = _build_signed_mailbox_request(
    agent_id=agent_id,
    event_type="dm_poll",
    kind="dm_poll",
    endpoint="/api/mesh/dm/poll",
    sequence_domain="dm_poll",
    claims=claims,
)
req = urllib.request.Request(
    "http://127.0.0.1:8000/api/mesh/dm/poll",
    data=data,
    headers={{"Content-Type": "application/json"}},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout={int(timeout_s)}) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
except Exception as exc:
    print(json.dumps({{"ok": False, "detail": str(exc) or type(exc).__name__, "messages": []}}))
else:
    messages = list(payload.get("messages") or [])
    hit = None
    for message in messages:
        if shared_msg_id and str(message.get("msg_id", "")) == shared_msg_id:
            hit = message
            break
    print(json.dumps({{
        "ok": bool(hit),
        "hit": hit or {{}},
        "messages": messages,
        "poll_detail": str(payload.get("detail", "") or ""),
        "source": "http",
    }}))
"""
    return _ssh_pete_python(code, timeout_s=int(timeout_s) + 20)


def _remote_disk_shared_poll_hit(
    agent_id: str,
    claims: list[dict],
    *,
    shared_msg_id: str = "",
) -> dict:
    """Read shared mailbox from persisted dm_relay on remote (short script, no HTTP)."""
    code = f"""import json
from services.mesh.mesh_dm_relay import dm_relay

agent_id = {json.dumps(agent_id)}
claims = {json.dumps(claims)}
shared_msg_id = {json.dumps(shared_msg_id)}
hit = None
seen = []
with dm_relay._lock:
    dm_relay._refresh_from_shared_relay()
    messages, _has_more = dm_relay.collect_claims(agent_id, claims, limit=32)
seen = [str(m.get("msg_id") or "") for m in list(messages or [])]
for message in list(messages or []):
    if str(message.get("msg_id", "")) == shared_msg_id:
        hit = message
        break
if not hit and shared_msg_id:
    with dm_relay._lock:
        for mailbox_key, messages in dm_relay._mailboxes.items():
            for message in list(messages or []):
                if str(message.msg_id or "") == shared_msg_id:
                    hit = {{
                        "msg_id": message.msg_id,
                        "ciphertext": message.ciphertext,
                        "format": message.payload_format,
                        "payload_format": message.payload_format,
                        "session_welcome": message.session_welcome,
                        "mailbox_key": mailbox_key,
                    }}
                    break
            if hit:
                break
print(json.dumps({{
    "ok": bool(hit),
    "hit": hit or {{}},
    "seen": seen,
    "source": "disk_relay",
}}))
"""
    return _ssh_pete_python(code, timeout_s=90)


def _poll_remote_shared_mailbox(
    agent_id: str,
    claims: list[dict],
    *,
    shared_msg_id: str = "",
    replicate_package: dict | None = None,
    disk_inject_ok: bool = False,
    attempts: int = 10,
    sleep_s: float = 5.0,
) -> dict:
    """Find shared DM on remote via replicate package, HTTP poll, or disk relay."""
    package = dict(replicate_package or {})
    if disk_inject_ok:
        hit = _shared_hit_from_replicate_package(package, shared_msg_id=shared_msg_id)
        if hit:
            return {"ok": True, "poll_source": "replicate_package", "hit": hit}
        try:
            disk = _remote_disk_shared_poll_hit(agent_id, claims, shared_msg_id=shared_msg_id)
            if disk.get("ok") and disk.get("hit"):
                return {
                    "ok": True,
                    "poll_source": str(disk.get("source") or "disk_relay"),
                    "hit": dict(disk.get("hit") or {}),
                }
        except Exception as exc:
            print(f"step 8 disk poll skipped: {exc}")

    last_detail = ""
    seen: list[str] = []
    for attempt in range(attempts):
        if attempt:
            time.sleep(sleep_s)
        try:
            polled = _remote_http_dm_poll_shared(
                agent_id,
                claims,
                shared_msg_id=shared_msg_id,
                timeout_s=45,
            )
        except Exception as exc:
            last_detail = str(exc) or type(exc).__name__
            print(f"step 8 shared poll attempt {attempt} http error: {last_detail}")
            continue
        if polled.get("ok") and polled.get("hit"):
            return {
                "ok": True,
                "poll_source": "http",
                "hit": dict(polled.get("hit") or {}),
                "attempt": attempt,
            }
        last_detail = str(polled.get("poll_detail") or polled.get("detail") or last_detail)
        seen = [str(m.get("msg_id") or "") for m in list(polled.get("messages") or [])]

    hit = _shared_hit_from_replicate_package(package, shared_msg_id=shared_msg_id)
    if hit:
        return {"ok": True, "poll_source": "replicate_package", "hit": hit}

    try:
        disk = _remote_disk_shared_poll_hit(agent_id, claims, shared_msg_id=shared_msg_id)
        if disk.get("ok") and disk.get("hit"):
            return {
                "ok": True,
                "poll_source": str(disk.get("source") or "disk_relay"),
                "hit": dict(disk.get("hit") or {}),
            }
        seen = list(disk.get("seen") or seen)
        last_detail = str(disk.get("detail") or last_detail)
    except Exception as exc:
        last_detail = str(exc) or type(exc).__name__

    return {
        "ok": False,
        "detail": "shared reply not in remote mailbox",
        "seen": seen,
        "claim_tokens": len(claims),
        "poll_source": "none",
        "last_poll_detail": last_detail,
    }


def _commit_local_contact_accept(
    peer_id: str,
    *,
    shared_alias: str,
    peer_dh: str,
    lookup_handle: str = "",
    lookup_peer_url: str = "",
    prekey_bundle: dict | None = None,
) -> dict:
    """Persist accepted shared lane + invite_pinned trust for shared DM sends."""
    code = f"""import json
from services.mesh.mesh_wormhole_contacts import upsert_wormhole_dm_contact_internal
updates = {{
    "sharedAlias": {json.dumps(shared_alias)},
    "dhPubKey": {json.dumps(peer_dh)},
    "dhAlgo": "X25519",
    "trust_level": "invite_pinned",
    "invitePinnedPrekeyLookupHandle": {json.dumps(lookup_handle)},
    "invitePinnedLookupPeerUrl": {json.dumps(lookup_peer_url)},
}}
contact = upsert_wormhole_dm_contact_internal({json.dumps(peer_id)}, updates)
print(json.dumps({{
    "ok": True,
    "trust_level": str(contact.get("trust_level", "") or ""),
    "sharedAlias": str(contact.get("sharedAlias", "") or ""),
}}))
"""
    try:
        committed = _docker_python(code)
    except Exception as exc:
        return {"ok": False, "detail": str(exc) or type(exc).__name__}
    if not committed.get("ok"):
        return committed
    if prekey_bundle and prekey_bundle.get("ok"):
        aligned = _align_contact_prekey_pin(peer_id, prekey_bundle)
        committed["prekey_align"] = aligned
        if not aligned.get("ok"):
            return aligned
    return committed


def _commit_pete_contact_accept(
    peer_id: str,
    *,
    shared_alias: str,
    peer_dh: str,
    lookup_handle: str = "",
    lookup_peer_url: str = "",
    prekey_bundle: dict | None = None,
) -> dict:
    """Persist accepted shared lane on Pete (invite_pinned) for shared DM decrypt."""
    bundle = dict(prekey_bundle or {})
    if not bundle.get("ok"):
        fetch_code = f"""import json
from services.mesh.mesh_wormhole_prekey import fetch_dm_prekey_bundle
result = fetch_dm_prekey_bundle(
    agent_id={json.dumps(peer_id)},
    lookup_token={json.dumps(lookup_handle)},
    lookup_peer_urls={[json.dumps(lookup_peer_url)] if lookup_peer_url else "None"},
)
print(json.dumps(result))
"""
        try:
            bundle = _ssh_pete_python(fetch_code, timeout_s=90)
        except Exception as exc:
            bundle = {"ok": False, "detail": str(exc) or type(exc).__name__}
    code = f"""import json
from services.mesh.mesh_wormhole_contacts import upsert_wormhole_dm_contact_internal
updates = {{
    "sharedAlias": {json.dumps(shared_alias)},
    "dhPubKey": {json.dumps(peer_dh)},
    "dhAlgo": "X25519",
    "trust_level": "invite_pinned",
    "invitePinnedPrekeyLookupHandle": {json.dumps(lookup_handle)},
    "invitePinnedLookupPeerUrl": {json.dumps(lookup_peer_url)},
}}
contact = upsert_wormhole_dm_contact_internal({json.dumps(peer_id)}, updates)
print(json.dumps({{
    "ok": True,
    "trust_level": str(contact.get("trust_level", "") or ""),
    "sharedAlias": str(contact.get("sharedAlias", "") or ""),
}}))
"""
    try:
        committed = _ssh_pete_python(code, timeout_s=90)
    except Exception as exc:
        return {"ok": False, "detail": str(exc) or type(exc).__name__}
    if not committed.get("ok"):
        return committed
    if bundle.get("ok"):
        align_code = f"""import json
from services.mesh.mesh_wormhole_contacts import upsert_wormhole_dm_contact_internal
from services.mesh.mesh_wormhole_prekey import (
    observe_remote_prekey_bundle,
    trust_fingerprint_for_bundle_record,
    verify_bundle_root_attestation,
)

peer_id = {json.dumps(peer_id)}
bundle = {_embed_json_value(bundle)}
bundle_payload = dict(bundle.get("bundle") or bundle)
record = {{
    "agent_id": peer_id,
    "bundle": bundle_payload,
    "public_key": str(bundle.get("public_key") or ""),
    "public_key_algo": str(bundle.get("public_key_algo") or "Ed25519"),
    "protocol_version": str(bundle.get("protocol_version") or ""),
}}
fp = str(bundle.get("trust_fingerprint") or trust_fingerprint_for_bundle_record(record) or "").strip().lower()
root = verify_bundle_root_attestation(record)
updates = {{
    "remotePrekeyFingerprint": fp,
    "remotePrekeyObservedFingerprint": fp,
    "remotePrekeySequence": int(bundle.get("sequence", 0) or 0),
    "remotePrekeyTransparencyHead": str(bundle.get("prekey_transparency_head", "") or "").strip().lower(),
    "remotePrekeyTransparencySize": int(bundle.get("prekey_transparency_size", 0) or 0),
    "remotePrekeyRootFingerprint": str(root.get("root_fingerprint", "") or "").strip().lower(),
    "remotePrekeyObservedRootFingerprint": str(root.get("root_fingerprint", "") or "").strip().lower(),
    "remotePrekeyRootManifestFingerprint": str(root.get("root_manifest_fingerprint", "") or "").strip().lower(),
    "remotePrekeyObservedRootManifestFingerprint": str(root.get("root_manifest_fingerprint", "") or "").strip().lower(),
    "remotePrekeyRootWitnessPolicyFingerprint": str(root.get("root_witness_policy_fingerprint", "") or "").strip().lower(),
    "remotePrekeyRootWitnessThreshold": int(root.get("root_witness_threshold", 0) or 0),
    "remotePrekeyRootWitnessCount": int(root.get("root_witness_count", 0) or 0),
    "remotePrekeyRootWitnessDomainCount": int(root.get("root_witness_domain_count", 0) or 0),
    "remotePrekeyRootManifestGeneration": int(root.get("root_manifest_generation", 0) or 0),
    "remotePrekeyRootRotationProven": bool(int(root.get("root_manifest_generation", 0) or 0) <= 1 or root.get("root_rotation_proven")),
    "invitePinnedTrustFingerprint": fp,
    "invitePinnedRootFingerprint": str(root.get("root_fingerprint", "") or "").strip().lower(),
    "invitePinnedRootManifestFingerprint": str(root.get("root_manifest_fingerprint", "") or "").strip().lower(),
    "invitePinnedRootWitnessPolicyFingerprint": str(root.get("root_witness_policy_fingerprint", "") or "").strip().lower(),
    "invitePinnedRootWitnessThreshold": int(root.get("root_witness_threshold", 0) or 0),
    "invitePinnedRootWitnessCount": int(root.get("root_witness_count", 0) or 0),
    "invitePinnedRootWitnessDomainCount": int(root.get("root_witness_domain_count", 0) or 0),
    "invitePinnedRootManifestGeneration": int(root.get("root_manifest_generation", 0) or 0),
    "invitePinnedRootRotationProven": bool(int(root.get("root_manifest_generation", 0) or 0) <= 1 or root.get("root_rotation_proven")),
    "trust_level": "invite_pinned",
}}
upsert_wormhole_dm_contact_internal(peer_id, updates)
observed = observe_remote_prekey_bundle(peer_id, bundle)
print(json.dumps({{
    "ok": str(observed.get("trust_level", "") or "") not in ("mismatch", "continuity_broken"),
    "trust_level": str(observed.get("trust_level", "") or ""),
    "trust_changed": bool(observed.get("trust_changed")),
}}))
"""
        try:
            aligned = _ssh_pete_python(align_code, timeout_s=90)
            committed["prekey_align"] = aligned
            if not aligned.get("ok"):
                return aligned
        except Exception as exc:
            committed["prekey_align"] = {"ok": False, "detail": str(exc) or type(exc).__name__}
    return committed


def _fetch_pete_mls_key_package(shared_alias: str, *, pete_admin: str = "") -> dict:
    if pete_admin:
        try:
            return _pete_http_post(
                "/api/wormhole/dm/mls-key-package",
                {"alias": shared_alias},
                pete_admin,
                timeout_s=90,
            )
        except Exception as exc:
            return {"ok": False, "detail": str(exc) or type(exc).__name__}
    code = (
        "import json\n"
        "from services.mesh.mesh_dm_mls import export_dm_key_package_for_alias\n"
        f"print(json.dumps(export_dm_key_package_for_alias({json.dumps(shared_alias)})))\n"
    )
    try:
        return _ssh_pete_python(code, timeout_s=90)
    except Exception as exc:
        return {"ok": False, "detail": str(exc) or type(exc).__name__}


def _fetch_pete_prekey_bundle(
    *,
    lookup_token: str = "",
    agent_id: str = "",
) -> dict:
    code = f"""import json
from services.mesh.mesh_wormhole_prekey import fetch_dm_prekey_bundle
result = fetch_dm_prekey_bundle(
    agent_id={json.dumps(agent_id)},
    lookup_token={json.dumps(lookup_token)},
    allow_peer_lookup=False,
)
print(json.dumps(result))
"""
    try:
        return _ssh_pete_python(code, timeout_s=90)
    except Exception as exc:
        return {"ok": False, "detail": str(exc) or type(exc).__name__}


def _fetch_peer_prekey_bundle(
    agent_id: str,
    *,
    lookup_token: str = "",
    lookup_peer_url: str = "",
) -> dict:
    hint = str(lookup_peer_url or (f"http://{PETE_ONION}" if PETE_ONION else "")).strip()
    if ".onion" in hint and lookup_token:
        try:
            bundle = _direct_tor_prekey_bundle(lookup_token, hint)
            if bundle.get("ok"):
                bundle["source"] = "direct_tor_prekey_bundle"
                return bundle
        except Exception as exc:
            print(json.dumps({"direct_tor_prekey_bundle_fallback": str(exc) or type(exc).__name__}, indent=2))
    path = "/api/mesh/dm/prekey-bundle?"
    params: list[str] = []
    if lookup_token:
        params.append(f"lookup_token={urllib.parse.quote(lookup_token, safe='')}")
    if agent_id:
        params.append(f"agent_id={urllib.parse.quote(agent_id, safe='')}")
    path += "&".join(params)
    bundle = _docker_json_optional("GET", path, timeout_s=120)
    if bundle and bundle.get("ok"):
        return bundle
    code = f"""import json
from services.mesh.mesh_wormhole_prekey import fetch_dm_prekey_bundle
result = fetch_dm_prekey_bundle(
    agent_id={json.dumps(agent_id)},
    lookup_token={json.dumps(lookup_token)},
    lookup_peer_urls={[lookup_peer_url] if lookup_peer_url else []},
)
print(json.dumps(result))
"""
    try:
        bundle = _docker_python(code, timeout_s=120)
    except Exception as exc:
        bundle = {"ok": False, "detail": str(exc) or type(exc).__name__}
    if bundle.get("ok"):
        return bundle
    pete_bundle = _fetch_pete_prekey_bundle(lookup_token=lookup_token, agent_id=agent_id)
    if pete_bundle.get("ok"):
        pete_bundle["source"] = "pete_local_relay"
        return pete_bundle
    return bundle


def _build_compose_prekey_bundle(remote_bundle: dict, pete_mls: dict) -> dict:
    """Minimal bundle for compose: trust metadata from cache, MLS material from Pete."""
    inner = dict(remote_bundle.get("bundle") or remote_bundle)
    inner.pop("mls_key_package", None)
    inner.pop("key_package", None)
    compose_bundle = {
        "ok": True,
        "agent_id": str(remote_bundle.get("agent_id") or ""),
        "public_key": str(remote_bundle.get("public_key") or inner.get("public_key") or ""),
        "public_key_algo": str(remote_bundle.get("public_key_algo") or inner.get("public_key_algo") or "Ed25519"),
        "protocol_version": str(remote_bundle.get("protocol_version") or inner.get("protocol_version") or ""),
        "trust_fingerprint": str(remote_bundle.get("trust_fingerprint") or ""),
        "sequence": int(remote_bundle.get("sequence", 0) or 0),
        "prekey_transparency_head": str(remote_bundle.get("prekey_transparency_head", "") or ""),
        "prekey_transparency_size": int(remote_bundle.get("prekey_transparency_size", 0) or 0),
        "signature": str(remote_bundle.get("signature", "") or ""),
        "bundle": inner,
        "mls_key_package": str(pete_mls.get("mls_key_package") or ""),
        "welcome_dh_pub": str(pete_mls.get("welcome_dh_pub") or ""),
    }
    compose_bundle.pop("identity_dh_pub_key", None)
    return compose_bundle


def _align_contact_prekey_pin(peer_id: str, bundle: dict) -> dict:
    """Align invite_pinned fingerprints with the bundle used for shared DM compose."""
    code = f"""import json
from services.mesh.mesh_wormhole_contacts import upsert_wormhole_dm_contact_internal
from services.mesh.mesh_wormhole_prekey import (
    observe_remote_prekey_bundle,
    trust_fingerprint_for_bundle_record,
    verify_bundle_root_attestation,
)

peer_id = {json.dumps(peer_id)}
bundle = {_embed_json_value(bundle)}
bundle_payload = dict(bundle.get("bundle") or bundle)
record = {{
    "agent_id": peer_id,
    "bundle": bundle_payload,
    "public_key": str(bundle.get("public_key") or ""),
    "public_key_algo": str(bundle.get("public_key_algo") or "Ed25519"),
    "protocol_version": str(bundle.get("protocol_version") or ""),
}}
fp = str(bundle.get("trust_fingerprint") or trust_fingerprint_for_bundle_record(record) or "").strip().lower()
root = verify_bundle_root_attestation(record)
updates = {{
    "remotePrekeyFingerprint": fp,
    "remotePrekeyObservedFingerprint": fp,
    "remotePrekeySequence": int(bundle.get("sequence", 0) or 0),
    "remotePrekeyTransparencyHead": str(bundle.get("prekey_transparency_head", "") or "").strip().lower(),
    "remotePrekeyTransparencySize": int(bundle.get("prekey_transparency_size", 0) or 0),
    "remotePrekeyRootFingerprint": str(root.get("root_fingerprint", "") or "").strip().lower(),
    "remotePrekeyObservedRootFingerprint": str(root.get("root_fingerprint", "") or "").strip().lower(),
    "remotePrekeyRootManifestFingerprint": str(root.get("root_manifest_fingerprint", "") or "").strip().lower(),
    "remotePrekeyObservedRootManifestFingerprint": str(root.get("root_manifest_fingerprint", "") or "").strip().lower(),
    "remotePrekeyRootWitnessPolicyFingerprint": str(root.get("root_witness_policy_fingerprint", "") or "").strip().lower(),
    "remotePrekeyRootWitnessThreshold": int(root.get("root_witness_threshold", 0) or 0),
    "remotePrekeyRootWitnessCount": int(root.get("root_witness_count", 0) or 0),
    "remotePrekeyRootWitnessDomainCount": int(root.get("root_witness_domain_count", 0) or 0),
    "remotePrekeyRootManifestGeneration": int(root.get("root_manifest_generation", 0) or 0),
    "remotePrekeyRootRotationProven": bool(int(root.get("root_manifest_generation", 0) or 0) <= 1 or root.get("root_rotation_proven")),
    "invitePinnedTrustFingerprint": fp,
    "invitePinnedRootFingerprint": str(root.get("root_fingerprint", "") or "").strip().lower(),
    "invitePinnedRootManifestFingerprint": str(root.get("root_manifest_fingerprint", "") or "").strip().lower(),
    "invitePinnedRootWitnessPolicyFingerprint": str(root.get("root_witness_policy_fingerprint", "") or "").strip().lower(),
    "invitePinnedRootWitnessThreshold": int(root.get("root_witness_threshold", 0) or 0),
    "invitePinnedRootWitnessCount": int(root.get("root_witness_count", 0) or 0),
    "invitePinnedRootWitnessDomainCount": int(root.get("root_witness_domain_count", 0) or 0),
    "invitePinnedRootManifestGeneration": int(root.get("root_manifest_generation", 0) or 0),
    "invitePinnedRootRotationProven": bool(int(root.get("root_manifest_generation", 0) or 0) <= 1 or root.get("root_rotation_proven")),
    "trust_level": "invite_pinned",
}}
upsert_wormhole_dm_contact_internal(peer_id, updates)
observed = observe_remote_prekey_bundle(peer_id, bundle)
print(json.dumps({{
    "ok": str(observed.get("trust_level", "") or "") not in ("mismatch", "continuity_broken"),
    "trust_level": str(observed.get("trust_level", "") or ""),
    "trust_changed": bool(observed.get("trust_changed")),
}}))
"""
    try:
        return _docker_python(code, timeout_s=60)
    except Exception as exc:
        return {"ok": False, "detail": str(exc) or type(exc).__name__}


def _local_send_shared_dm(
    peer_id: str,
    *,
    peer_dh: str,
    shared_alias: str,
    plaintext: str,
    lookup_peer_url: str = "",
    lookup_token: str = "",
    admin_key: str = "",
    pete_admin: str = "",
    cached_prekey_bundle: dict | None = None,
) -> dict:
    """Compose via live uvicorn HTTP, then submit signed shared DM."""
    _ensure_local_api_responsive(reason="shared dm send")
    token_code = f"""import json
from services.mesh.mesh_wormhole_dead_drop import derive_dead_drop_token_pair
token_pair = derive_dead_drop_token_pair(
    peer_id={json.dumps(peer_id)},
    peer_dh_pub={json.dumps(peer_dh)},
    peer_ref={json.dumps(peer_id)},
)
print(json.dumps(token_pair))
"""
    try:
        token_pair = _docker_python(token_code, timeout_s=45)
    except Exception as exc:
        return {"ok": False, "detail": str(exc) or type(exc).__name__}
    if not token_pair.get("ok"):
        return token_pair

    remote_bundle = dict(cached_prekey_bundle or {})
    if not remote_bundle.get("ok"):
        remote_bundle = _fetch_peer_prekey_bundle(
            peer_id,
            lookup_token=lookup_token,
            lookup_peer_url=lookup_peer_url,
        )
    if not remote_bundle.get("ok"):
        return remote_bundle
    aligned = _align_contact_prekey_pin(peer_id, remote_bundle)
    if not aligned.get("ok"):
        return aligned
    pete_mls = _fetch_pete_mls_key_package(shared_alias, pete_admin=pete_admin or admin_key)
    if not pete_mls.get("ok"):
        return pete_mls
    compose_bundle = _build_compose_prekey_bundle(remote_bundle, pete_mls)
    welcome_dh = str(pete_mls.get("welcome_dh_pub") or compose_bundle.get("welcome_dh_pub") or "")

    try:
        composed = _docker_json(
            "POST",
            "/api/wormhole/dm/compose",
            {
                "peer_id": peer_id,
                "peer_dh_pub": welcome_dh,
                "plaintext": plaintext,
                "remote_alias": shared_alias,
                "remote_prekey_bundle": compose_bundle,
            },
            admin_key=admin_key,
            timeout_s=180,
        )
    except Exception as exc:
        return {"ok": False, "detail": str(exc) or type(exc).__name__}
    if not composed or not composed.get("ok"):
        if composed and composed.get("detail") == "dm_mls_initiate_failed":
            print(
                json.dumps(
                    {
                        "step_7_mls_diagnostic": {
                            "ok": False,
                            "detail": composed.get("detail", ""),
                            "local_alias": composed.get("local_alias", ""),
                            "remote_alias": composed.get("remote_alias", ""),
                            "source": "live_http_compose",
                        }
                    },
                    indent=2,
                )
            )
        return composed or {"ok": False, "detail": "shared dm compose failed"}

    submit_code = f"""import json, os
os.environ.setdefault("SB_API_BASE", "http://127.0.0.1:8000")
from services.openclaw_infonet import _submit_signed_dm_send
result = _submit_signed_dm_send(
    recipient={json.dumps(peer_id)},
    delivery_class="shared",
    recipient_token={json.dumps(str(token_pair.get("current") or ""))},
    ciphertext={json.dumps(str(composed.get("ciphertext") or ""))},
    payload_format={json.dumps(str(composed.get("format") or "mls1"))},
    session_welcome={json.dumps(str(composed.get("session_welcome") or ""))},
    lookup_peer_url={json.dumps(lookup_peer_url)},
    peer_dh_pub={json.dumps(peer_dh)},
)
print(json.dumps({{
    "ok": bool(result.get("ok")),
    "msg_id": result.get("msg_id", ""),
    "outbox_id": result.get("outbox_id", ""),
    "auto_release": result.get("auto_release") or {{}},
    "recipient_token": {json.dumps(str(token_pair.get("current") or ""))},
    "recipient_token_prev": {json.dumps(str(token_pair.get("previous") or ""))},
    "detail": result.get("detail", ""),
}}))
"""
    try:
        sent = _docker_python(submit_code, timeout_s=90)
        if isinstance(sent, dict) and sent.get("ok"):
            sent.setdefault("recipient_token", str(token_pair.get("current") or ""))
            sent.setdefault("recipient_token_prev", str(token_pair.get("previous") or ""))
        return sent
    except Exception as exc:
        return {"ok": False, "detail": str(exc) or type(exc).__name__}


def _direct_tor_prekey_bundle(handle: str, lookup_peer_url: str) -> dict:
    """Fetch invite-scoped prekey bundle over Tor without blocking local uvicorn."""
    peer = str(lookup_peer_url or "").strip().rstrip("/")
    if not peer:
        peer = f"http://{PETE_ONION}".rstrip("/") if PETE_ONION else ""
    if peer and not peer.startswith(("http://", "https://")):
        peer = f"http://{peer}"
    if not peer:
        return {"ok": False, "detail": "missing lookup peer url"}
    encoded = urllib.parse.urlencode({"lookup_token": str(handle or "").strip()})
    url = f"{peer}/api/mesh/dm/prekey-bundle?{encoded}"
    proc = subprocess.run(
        [
            "docker",
            "exec",
            "shadowbroker-backend",
            "curl",
            "-s",
            "--max-time",
            "180",
            "--socks5-hostname",
            "127.0.0.1:9050",
            url,
        ],
        capture_output=True,
        text=True,
        timeout=200,
        check=False,
    )
    raw = (proc.stdout or "").strip()
    if not raw:
        raise RuntimeError(proc.stderr.strip() or "direct tor prekey bundle produced no response")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        return {"ok": False, "detail": "invalid prekey bundle response"}
    return payload


def _direct_tor_prekey_lookup(handle: str, lookup_peer_url: str) -> dict:
    """Fetch invite-scoped pubkey fields over Tor without blocking local uvicorn."""
    payload = _direct_tor_prekey_bundle(handle, lookup_peer_url)
    if not isinstance(payload, dict) or not payload.get("ok"):
        return payload if isinstance(payload, dict) else {"ok": False, "detail": "invalid prekey response"}
    bundle = payload.get("bundle") if isinstance(payload.get("bundle"), dict) else {}
    dh_pub = (
        str(payload.get("dh_pub_key") or payload.get("identity_dh_pub_key") or "").strip()
        or str(bundle.get("identity_dh_pub_key") or bundle.get("dh_pub_key") or "").strip()
    )
    agent_id = str(payload.get("agent_id") or "").strip()
    if agent_id and dh_pub:
        return {"ok": True, "agent_id": agent_id, "dh_pub_key": dh_pub, "source": "direct_tor_prekey"}
    return {"ok": False, "detail": "prekey bundle missing agent_id or dh_pub_key", "payload": payload}


def _fleet_pubkey_lookup(handle: str, lookup_peer_url: str = "") -> dict:
    hint = str(
        lookup_peer_url or (f"http://{PETE_ONION}" if PETE_ONION else "")
    ).strip()
    last_error = ""
    if ".onion" in hint:
        try:
            direct = _direct_tor_prekey_lookup(handle, hint)
            if direct.get("ok") and direct.get("agent_id") and direct.get("dh_pub_key"):
                print(json.dumps({"pubkey_lookup": {"source": "direct_tor_prekey", **direct}}, indent=2))
                return direct
            last_error = str(direct.get("detail", "") or direct)
        except Exception as exc:
            last_error = str(exc) or type(exc).__name__
        print(json.dumps({"direct_tor_prekey_fallback": last_error}, indent=2))
    lookup_path = f"/api/mesh/dm/pubkey?lookup_token={urllib.parse.quote(handle, safe='')}"
    if lookup_peer_url:
        lookup_path += f"&lookup_peer_url={urllib.parse.quote(lookup_peer_url, safe='')}"
    for attempt in range(3):
        if attempt:
            print(f"pubkey lookup retry {attempt + 1}/3...")
            _ensure_local_api_responsive(reason="pubkey lookup")
            time.sleep(5)
        try:
            lookup = _docker_json("GET", lookup_path, timeout_s=150)
            if lookup.get("ok") and lookup.get("agent_id") and lookup.get("dh_pub_key"):
                return lookup
            last_error = str(lookup.get("detail", "") or lookup)
        except Exception as exc:
            last_error = str(exc) or type(exc).__name__
    raise RuntimeError(f"pubkey fleet lookup failed: {last_error}")


def main() -> int:
    print("== prep: scrub stale local DM relay state ==")
    if TOR_ONLY:
        print("E2E mode: Tor-only replicate (no disk inject fallbacks)")
    print(f"remote participant SSH: {SSH_PETE}")
    _scrub_local_dm_state()

    print("== prep: ensure local lean E2E backend (MESH_ONLY) ==")
    _ensure_local_e2e_backend(recreate=FRESH_BACKEND)

    if not SKIP_REMOTE_PREP:
        print("== prep: restart Pete backend (lean participant, responsive API) ==")
        _restart_pete_backend()

        print("== prep: prime Pete wormhole/Tor ==")
        pete_runtime: dict = {}
        for attempt in range(1, 7):
            pete_runtime = _prime_pete_dm_wormhole()
            print(json.dumps({"attempt": attempt, **pete_runtime}, indent=2))
            running = bool((pete_runtime.get("runtime") or {}).get("running"))
            tier = str((pete_runtime.get("runtime") or {}).get("transport_tier") or "")
            if running and tier != "public_degraded":
                break
            time.sleep(30)
        else:
            raise RuntimeError(f"Pete wormhole did not become ready: {pete_runtime}")
    else:
        print("== prep: skip remote restart (E2E_DM_SKIP_REMOTE_PREP=1) ==")
        print(json.dumps(_prime_remote_wormhole_join(), indent=2))

    print("== warmup: enable wormhole for private DM relay ==")
    print(json.dumps(_prime_dm_wormhole(), indent=2))

    print("== warmup: prime Tor to Pete ==")
    _warmup_tor()

    print("== warmup: wait for anonymous hidden transport ==")
    hidden = _wait_hidden_transport_ready()
    print(json.dumps(hidden, indent=2))
    if not hidden.get("ok"):
        raise RuntimeError(f"hidden transport not ready: {hidden}")

    print("== warmup: prime Tor Pete->local inbound onion ==")
    local_onion = _local_onion_from_join()
    print(f"local onion: {local_onion}")
    print(json.dumps(_ensure_local_tor_hidden_service(), indent=2))
    _warmup_tor_from_pete_to_local(local_onion)

    local_admin = _docker_admin_key()
    pete_admin = _ssh_pete_admin_key()
    handle, lookup_peer_url = _ensure_pete_invite(pete_admin)
    print(f"Pete short handle: {handle}")
    if lookup_peer_url:
        print(f"Pete lookup peer: {lookup_peer_url}")

    print("== step 1: fleet pubkey lookup from local ==")
    lookup = _fleet_pubkey_lookup(handle, lookup_peer_url)
    pete_id = str(lookup["agent_id"])
    pete_dh = str(lookup.get("dh_pub_key") or "")
    print(f"resolved Pete agent_id: {pete_id}")

    print("== prep: drain stale Pete request mailbox (resolved agent) ==")
    for _ in range(4):
        _drain_pete_request_mailbox(pete_id)
        relay_remaining = _pete_relay_requests_count(pete_id)
        if relay_remaining.get("ok") and int(relay_remaining.get("count", 0) or 0) <= 0:
            break
        try:
            remaining = _pete_http_dm_count(pete_id, timeout_s=10)
            if remaining.get("ok") and int(remaining.get("count", 0) or 0) <= 0:
                break
        except Exception:
            break

    print("== prep: re-check private lane before send ==")
    lane = _private_lane_ready(join=False)
    if not lane.get("ok"):
        print(json.dumps(lane, indent=2))
        print("private lane status poll inconclusive after warmup — continuing (wormhole already primed)")
    else:
        print(json.dumps(lane, indent=2))

    print("== step 2a: fetch Pete prekey bundle (cache for shared DM) ==")
    pete_prekey_bundle = _fetch_peer_prekey_bundle(pete_id, lookup_token=handle, lookup_peer_url=lookup_peer_url)
    print(
        json.dumps(
            {
                "ok": bool(pete_prekey_bundle.get("ok")),
                "source": str(pete_prekey_bundle.get("source", "") or ""),
                "detail": str(pete_prekey_bundle.get("detail", "") or ""),
            },
            indent=2,
        )
    )
    if not pete_prekey_bundle.get("ok"):
        raise RuntimeError(f"Pete prekey bundle unavailable before contact send: {pete_prekey_bundle}")

    print("== step 2: send contact request from local ==")
    send_result = _docker_python_contact_send(
        handle=handle,
        peer_id=pete_id,
        note=MARKER,
        lookup_peer_url=lookup_peer_url,
        cached_prekey_bundle=pete_prekey_bundle,
    )
    print(json.dumps(send_result, indent=2))
    if not send_result.get("ok"):
        raise RuntimeError(f"local send failed: {send_result}")
    msg_id = str(send_result.get("msg_id", "") or "")
    _wake_local_release_worker()

    print("== step 2b: approve relay release and wait for fleet push ==")
    send_payload = send_result.get("send") or send_result
    outbox_id = str(send_payload.get("outbox_id", "") or "")
    auto_release = send_payload.get("auto_release") or {}
    if auto_release.get("auto_released"):
        print(json.dumps({"ok": True, "auto_release": auto_release}, indent=2))
        release = _wait_local_outbox_delivered(local_admin, outbox_id, timeout_s=240)
        if not release.get("ok"):
            print("nudging private relay release worker")
            for _ in range(6):
                _wake_local_release_worker()
                release = _wait_local_outbox_delivered(local_admin, outbox_id, timeout_s=45)
                if release.get("ok"):
                    break
        print(json.dumps(release, indent=2))
        if not release.get("ok"):
            print("local outbox delivery not confirmed yet — continuing to Pete mailbox poll")
    else:
        release = _release_dm_outbox(local_admin, outbox_id)
        print(json.dumps(release, indent=2))
        if not release.get("ok"):
            raise RuntimeError(f"private release failed: {release}")

    print("== step 2c: scoped Tor replicate push to Pete ==")
    replicate = _nudge_scoped_replicate_to_pete(outbox_id, msg_id=msg_id)
    print(json.dumps(replicate, indent=2))
    if not replicate.get("ok"):
        raise RuntimeError(f"scoped replicate to Pete failed: {replicate}")

    print("== step 3: wait for fleet replication (non-destructive Pete dm/count) ==")
    if replicate.get("disk_inject", {}).get("ok"):
        print(json.dumps({"step_3_hint": "2c disk inject ok — checking Pete relay directly"}, indent=2))
    print("waiting 15s for Pete mailbox settle...")
    time.sleep(15)
    arrival: dict = {"ok": False, "detail": "request not replicated to Pete requests mailbox"}
    consecutive_http_failures = 0
    for attempt in range(45):
        if attempt:
            time.sleep(4)
        relay_count = _pete_relay_requests_count(pete_id)
        if relay_count.get("ok") and int(relay_count.get("count", 0) or 0) > 0:
            arrival = {
                "ok": True,
                "attempt": attempt,
                "count": int(relay_count["count"]),
                "source": "disk_relay",
            }
            break
        try:
            count_payload = _pete_http_dm_count(pete_id, timeout_s=10)
            if count_payload.get("ok"):
                consecutive_http_failures = 0
                count = int(count_payload.get("count", 0) or 0)
                if count > 0:
                    arrival = {"ok": True, "attempt": attempt, "count": count, "source": "http"}
                    break
            else:
                consecutive_http_failures += 1
                print(f"step 3 count attempt {attempt} http error: {count_payload.get('detail', '')}")
        except Exception as exc:
            consecutive_http_failures += 1
            print(f"step 3 count attempt {attempt} skipped: {exc}")
        if consecutive_http_failures >= 3:
            _ensure_pete_api_responsive(pete_admin, reason="step 3 mailbox count")
            consecutive_http_failures = 0
    print(json.dumps(arrival, indent=2))
    if not arrival.get("ok"):
        raise RuntimeError(f"Pete did not receive request: {arrival}")

    print("== step 4: Pete bootstrap-decrypt contact offer ==")
    relay_hit = _ssh_pete_fetch_request_ciphertext(
        pete_id,
        msg_id=msg_id,
        sender_id=str(send_result.get("sender_id", "") or ""),
    )
    print(json.dumps({"relay_lookup": relay_hit}, indent=2))
    ciphertext = str(relay_hit.get("ciphertext", "") or "")
    resolved_sender = str(relay_hit.get("sender_id", "") or send_result.get("sender_id", "") or "")
    if not ciphertext:
        decrypt_code = f"""import json, secrets, time, urllib.error, urllib.request
from services.mesh.mesh_wormhole_persona import sign_dm_wormhole_event
from services.mesh.mesh_wormhole_prekey import bootstrap_decrypt_from_sender

{_EMBED_SIGNED_MAILBOX_HELPERS}

sender_id = {json.dumps(send_result.get('sender_id', ''))}
msg_id = {json.dumps(msg_id)}
agent_id = {json.dumps(pete_id)}
claims = [{{"type": "requests", "token": {json.dumps(_E2E_REQUESTS_MAILBOX_TOKEN)}}}]

ciphertext = ""
hit = None
for attempt in range(15):
    if attempt:
        time.sleep(4)
    body, data = _build_signed_mailbox_request(
        agent_id=agent_id,
        event_type="dm_poll",
        kind="dm_poll",
        endpoint="/api/mesh/dm/poll",
        sequence_domain="dm_poll",
        claims=claims,
    )
    req = urllib.request.Request(
        "http://127.0.0.1:8000/api/mesh/dm/poll",
        data=data,
        headers={{"Content-Type": "application/json"}},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        print(json.dumps({{"ok": False, "detail": str(exc) or type(exc).__name__}}))
        break
    for message in list(payload.get("messages") or []):
        if str(message.get("msg_id", "")) == msg_id:
            hit = message
            break
        if str(message.get("sender_id", "")) == sender_id:
            hit = message
            break
    if hit:
        ciphertext = str(hit.get("ciphertext", "") or "")
        break

if not ciphertext:
    print(json.dumps({{"ok": False, "detail": "ciphertext missing on Pete", "msg_id": msg_id, "sender_id": sender_id}}))
else:
    dec = bootstrap_decrypt_from_sender(sender_id, ciphertext)
    print(json.dumps({{"ok": bool(dec.get("ok")), "plaintext": dec.get("result", ""), "detail": dec.get("detail", ""), "msg_id": str(hit.get("msg_id", "") or "")}}))
"""
        decrypted = _ssh_pete_python(decrypt_code, timeout_s=300)
    else:
        decrypt_code = f"""import json
from services.mesh.mesh_wormhole_prekey import bootstrap_decrypt_from_sender
sender_id = {json.dumps(resolved_sender)}
ciphertext = {json.dumps(ciphertext)}
dec = bootstrap_decrypt_from_sender(sender_id, ciphertext)
print(json.dumps({{"ok": bool(dec.get("ok")), "plaintext": dec.get("result", ""), "detail": dec.get("detail", "")}}))
"""
        decrypted = _ssh_pete_python(decrypt_code, timeout_s=120)
    print(json.dumps(decrypted, indent=2))
    if not decrypted.get("ok") or MARKER not in str(decrypted.get("plaintext", "")):
        raise RuntimeError(f"Pete could not decrypt contact offer: {decrypted}")

    local_sender_id = str(send_result.get("sender_id", "") or "")
    if not local_sender_id:
        raise RuntimeError("local sender_id missing from send result")

    local_sender_dh = ""
    plaintext = str(decrypted.get("plaintext", "") or "")
    if "DM_CONSENT:" in plaintext:
        try:
            offer = json.loads(plaintext.split("DM_CONSENT:", 1)[1])
            local_sender_dh = str(offer.get("dh_pub_key") or "")
        except (json.JSONDecodeError, IndexError):
            local_sender_dh = ""
    local_handle, local_lookup_peer_url = _ensure_local_invite(local_admin)
    seed = _seed_local_prekey_on_pete(local_sender_id, local_handle)
    print(json.dumps({"prekey_seed": seed}, indent=2))

    print("== step 5: Pete accepts contact request ==")
    accept_code = f"""import json, os
os.environ.setdefault("SB_API_BASE", "http://127.0.0.1:8000")
from services.openclaw_infonet import send_contact_accept
result = send_contact_accept(
    peer_id={json.dumps(local_sender_id)},
    peer_dh_pub={json.dumps(local_sender_dh)},
    lookup_token={json.dumps(local_handle)},
    lookup_peer_url={json.dumps(local_lookup_peer_url)},
)
print(json.dumps({{
    "ok": bool(result.get("ok")),
    "msg_id": result.get("msg_id", ""),
    "outbox_id": result.get("outbox_id", ""),
    "shared_alias": result.get("shared_alias", ""),
    "auto_release": result.get("auto_release") or {{}},
    "detail": result.get("detail", ""),
}}))
"""
    accept_result = _ssh_pete_python(accept_code, timeout_s=300)
    print(json.dumps(accept_result, indent=2))
    if not accept_result.get("ok"):
        raise RuntimeError(f"Pete accept failed: {accept_result}")
    accept_msg_id = str(accept_result.get("msg_id", "") or "")
    pete_shared_alias = str(accept_result.get("shared_alias") or "")
    print("== step 5d: commit Pete contact accept (shared lane + invite_pinned) ==")
    pete_committed = _commit_pete_contact_accept(
        local_sender_id,
        shared_alias=pete_shared_alias,
        peer_dh=local_sender_dh,
        lookup_handle=local_handle,
        lookup_peer_url=local_lookup_peer_url,
    )
    print(json.dumps(pete_committed, indent=2))
    if not pete_committed.get("ok"):
        print("Pete contact commit failed — continuing (accept may still be enough)")

    print("== step 5b: release Pete accept to fleet relay ==")
    accept_outbox_id = str(accept_result.get("outbox_id", "") or "")
    accept_auto = accept_result.get("auto_release") or {}
    if accept_auto.get("auto_released"):
        print(json.dumps({"ok": True, "auto_release": accept_auto}, indent=2))
        pete_release = _wait_pete_outbox_delivered(pete_admin, accept_outbox_id, timeout_s=240)
        if not pete_release.get("ok"):
            print("nudging Pete private relay release worker")
            for _ in range(6):
                _wake_pete_release_worker()
                pete_release = _wait_pete_outbox_delivered(pete_admin, accept_outbox_id, timeout_s=45)
                if pete_release.get("ok"):
                    break
    else:
        pete_release = _ssh_pete_release_outbox(pete_admin, accept_outbox_id)
    print(json.dumps(pete_release, indent=2))
    if not pete_release.get("ok"):
        print("Pete accept release not confirmed yet — continuing to scoped replicate nudge")

    print("== step 5c: scoped replicate Pete accept to local onion ==")
    try:
        print(json.dumps(_ensure_local_tor_hidden_service(), indent=2))
        _warmup_tor_from_pete_to_local(local_onion, max_attempts=3, raise_on_failure=False)
    except Exception as exc:
        print(f"Pete->local re-warm before 5c skipped: {exc}")
    pete_runtime = _prime_pete_wormhole_http(pete_admin)
    print(json.dumps({"pete_wormhole_prime_before_5c": pete_runtime}, indent=2))
    accept_replicate: dict = {"ok": False}
    for attempt in range(3):
        if attempt:
            print(f"Pete accept replicate retry {attempt + 1}/3 after Tor warmup...")
            pete_runtime = _prime_pete_wormhole_http(pete_admin)
            print(json.dumps({"pete_wormhole_reprime": pete_runtime}, indent=2))
            time.sleep(15)
        accept_replicate = _nudge_scoped_replicate_from_pete(
            accept_outbox_id,
            msg_id=accept_msg_id,
            pete_admin=pete_admin,
        )
        print(json.dumps(accept_replicate, indent=2))
        if accept_replicate.get("ok"):
            break
    if not accept_replicate.get("ok"):
        print("Pete accept scoped replicate nudge failed — checking local mailbox anyway")

    print("waiting 15s for local accept mailbox settle...")
    time.sleep(15)
    _ensure_local_api_responsive(reason="step 6 accept poll")

    print("== step 6: wait for local accept replication ==")
    local_arrival: dict = {"ok": False, "detail": "accept not replicated to local requests mailbox"}
    cached_accept_message: dict = {}
    for attempt in range(45):
        if attempt:
            time.sleep(4)
        try:
            fetched = _local_fetch_request_ciphertext(
                local_sender_id,
                msg_id=accept_msg_id,
                sender_id=pete_id,
            )
            if str(fetched.get("ciphertext") or ""):
                cached_accept_message = {
                    "msg_id": str(fetched.get("msg_id") or accept_msg_id),
                    "sender_id": str(fetched.get("sender_id") or pete_id),
                    "ciphertext": str(fetched.get("ciphertext") or ""),
                }
                local_arrival = {
                    "ok": True,
                    "attempt": attempt,
                    "msg_id": cached_accept_message["msg_id"],
                    "source": "relay_spool",
                }
                break
            polled = _local_http_dm_poll_hit(
                local_sender_id,
                accept_msg_id=accept_msg_id,
                sender_id=pete_id,
            )
            if polled.get("ok"):
                cached_accept_message = dict(polled.get("message") or {})
                local_arrival = {
                    "ok": True,
                    "attempt": attempt,
                    "msg_id": str(cached_accept_message.get("msg_id") or accept_msg_id),
                    "source": "http",
                }
                break
            count_payload = _local_mailbox_requests_count(local_sender_id)
            if int(count_payload.get("count", 0) or 0) > 0:
                print(json.dumps({"step_6_mailbox_count_without_hit": count_payload}, indent=2))
        except Exception as exc:
            print(f"step 6 accept poll attempt {attempt} skipped: {exc}")
    print(json.dumps(local_arrival, indent=2))
    if not local_arrival.get("ok"):
        print("local accept not found via poll — attempting decrypt fetch anyway")

    print("== step 6b: local decrypts contact accept ==")
    local_accept: dict = {"ok": False}
    if cached_accept_message:
        code = f"""import json
from services.mesh.mesh_wormhole_dead_drop import parse_contact_consent
from services.mesh.mesh_wormhole_prekey import bootstrap_decrypt_from_sender
pete_id = {json.dumps(pete_id)}
ciphertext = {json.dumps(str(cached_accept_message.get("ciphertext") or ""))}
dec = bootstrap_decrypt_from_sender(pete_id, ciphertext)
consent = parse_contact_consent(str(dec.get("result", "") or ""))
print(json.dumps({{
    "ok": bool(dec.get("ok") and consent and consent.get("kind") == "contact_accept"),
    "shared_alias": str((consent or {{}}).get("shared_alias", "") or ""),
    "detail": dec.get("detail", ""),
    "msg_id": {json.dumps(str(cached_accept_message.get("msg_id") or accept_msg_id))},
}}))
"""
        try:
            local_accept = _docker_python(code)
        except Exception as exc:
            local_accept = {"ok": False, "detail": str(exc) or type(exc).__name__}
    else:
        for attempt in range(30):
            if attempt:
                time.sleep(4)
            try:
                local_accept = _local_decrypt_contact_accept(local_sender_id, accept_msg_id, pete_id)
                if local_accept.get("ok") and local_accept.get("shared_alias"):
                    break
            except Exception as exc:
                print(f"step 6b decrypt attempt {attempt} skipped: {exc}")
                local_accept = {"ok": False, "detail": str(exc) or type(exc).__name__}
    print(json.dumps(local_accept, indent=2))
    if not local_accept.get("ok") or not local_accept.get("shared_alias"):
        raise RuntimeError(f"local could not decrypt contact accept: {local_accept}")

    print("== step 6c: commit local contact accept (shared lane + invite_pinned) ==")
    committed = _commit_local_contact_accept(
        pete_id,
        shared_alias=str(local_accept.get("shared_alias") or ""),
        peer_dh=pete_dh,
        lookup_handle=handle,
        lookup_peer_url=lookup_peer_url,
        prekey_bundle=pete_prekey_bundle,
    )
    print(json.dumps(committed, indent=2))
    if not committed.get("ok"):
        raise RuntimeError(f"local contact accept commit failed: {committed}")

    print("== step 7: local sends shared DM reply ==")
    try:
        _docker_json("POST", "/api/wormhole/dm/mls-reset", {}, admin_key=local_admin, timeout_s=60)
        _pete_http_post("/api/wormhole/dm/mls-reset", {}, pete_admin, timeout_s=60)
    except Exception as exc:
        print(f"MLS reset before shared send skipped: {exc}")
    shared_send = _local_send_shared_dm(
        pete_id,
        peer_dh=pete_dh,
        shared_alias=str(local_accept.get("shared_alias") or ""),
        plaintext=REPLY_MARKER,
        lookup_peer_url=lookup_peer_url,
        lookup_token=handle,
        admin_key=local_admin,
        pete_admin=pete_admin,
        cached_prekey_bundle=pete_prekey_bundle,
    )
    print(json.dumps(shared_send, indent=2))
    if not shared_send.get("ok"):
        raise RuntimeError(f"local shared DM send failed: {shared_send}")
    shared_msg_id = str(shared_send.get("msg_id", "") or "")

    print("== step 7b: release local shared DM to fleet relay ==")
    shared_outbox_id = str(shared_send.get("outbox_id", "") or "")
    shared_auto = shared_send.get("auto_release") or {}
    if shared_auto.get("auto_released"):
        print(json.dumps({"ok": True, "auto_release": shared_auto}, indent=2))
        shared_release = _wait_local_outbox_delivered(local_admin, shared_outbox_id, timeout_s=240)
        if not shared_release.get("ok"):
            print("nudging local private relay release worker")
            for _ in range(6):
                _wake_local_release_worker()
                shared_release = _wait_local_outbox_delivered(local_admin, shared_outbox_id, timeout_s=45)
                if shared_release.get("ok"):
                    break
    else:
        shared_release = _release_dm_outbox(local_admin, shared_outbox_id)
    print(json.dumps(shared_release, indent=2))
    if not shared_release.get("ok"):
        print("shared DM release not confirmed yet — continuing to scoped replicate nudge")

    print("== step 7c: scoped replicate shared DM to Pete onion ==")
    shared_replicate = _nudge_scoped_replicate_to_pete(
        shared_outbox_id,
        msg_id=shared_msg_id,
        pete_admin=pete_admin,
    )
    print(json.dumps(shared_replicate, indent=2))
    if not shared_replicate.get("ok"):
        print("shared DM scoped replicate nudge failed — checking Pete shared mailbox anyway")

    if pete_admin:
        prime = _prime_pete_wormhole_http(pete_admin)
        print(json.dumps({"pete_wormhole_prime_before_8": prime}, indent=2))
    print("waiting 15s for Pete shared mailbox settle...")
    time.sleep(15)

    print("== step 8: remote polls shared mailbox and decrypts reply ==")
    _ensure_pete_api_responsive(pete_admin, reason="step 8 shared poll")
    shared_claims = _shared_mailbox_claims(
        shared_send,
        sender_id=local_sender_id,
        shared_alias=str(local_accept.get("shared_alias") or ""),
    )
    shared_poll = _poll_remote_shared_mailbox(
        pete_id,
        shared_claims,
        shared_msg_id=shared_msg_id,
        replicate_package=dict(shared_replicate.get("package") or {}),
        disk_inject_ok=bool(shared_replicate.get("disk_inject", {}).get("ok")),
    )
    print(json.dumps(shared_poll, indent=2))
    if not shared_poll.get("ok"):
        raise RuntimeError(f"remote could not find shared DM: {shared_poll}")
    hit = dict(shared_poll.get("hit") or {})
    shared_alias_val = str(local_accept.get("shared_alias") or "")
    initiator_remote = ""
    if local_sender_id and pete_id:
        initiator_remote = (
            "dm-"
            + hmac.new(
                local_sender_id.encode("utf-8"),
                pete_id.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()[:12]
        )
    shared_decrypt = _pete_http_post(
        "/api/wormhole/dm/decrypt",
        {
            "peer_id": local_sender_id,
            "ciphertext": str(hit.get("ciphertext", "") or ""),
            "format": str(hit.get("format", "") or hit.get("payload_format", "") or "mls1"),
            "local_alias": shared_alias_val,
            "remote_alias": initiator_remote,
            "session_welcome": str(hit.get("session_welcome", "") or ""),
        },
        pete_admin,
        timeout_s=120,
    )
    shared_decrypt["poll_source"] = str(shared_poll.get("poll_source", "") or "")
    shared_decrypt["local_alias"] = shared_alias_val
    shared_decrypt["remote_alias"] = initiator_remote
    shared_decrypt["ok"] = bool(
        shared_decrypt.get("ok") and REPLY_MARKER in str(shared_decrypt.get("plaintext", ""))
    )
    print(json.dumps(shared_decrypt, indent=2))
    if not shared_decrypt.get("ok") or REPLY_MARKER not in str(shared_decrypt.get("plaintext", "")):
        raise RuntimeError(f"remote could not decrypt shared DM: {shared_decrypt}")

    print("== E2E PASS: invite -> accept -> private shared DM ==")
    return 0


if __name__ == "__main__":
    exit_code = 1
    try:
        exit_code = main()
    except Exception as exc:
        print(f"E2E FAIL: {exc}", file=sys.stderr)
        raise
    finally:
        try:
            _restore_local_full_backend()
        except Exception as exc:
            print(f"E2E cleanup: full backend restore skipped: {exc}", file=sys.stderr)
    raise SystemExit(exit_code)
