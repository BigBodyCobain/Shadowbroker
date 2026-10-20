#!/usr/bin/env python3
"""Fresh-install v1 swarm smoke test: GHCR image + empty data volume only.

Simulates a new operator who runs the published backend image with fleet
defaults and no hand-edited peer list. Equivalent to NODE / meshnode.sh join.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

IMAGE = os.environ.get(
    "SWARM_FRESH_IMAGE",
    "ghcr.io/bigbodycobain/shadowbroker-backend:latest",
)
CONTAINER = os.environ.get("SWARM_FRESH_CONTAINER", "swarm-fresh-smoke")
VOLUME = os.environ.get("SWARM_FRESH_VOLUME", "swarm_fresh_smoke_data")
HOST_PORT = int(os.environ.get("SWARM_FRESH_PORT", "18001"))
API = f"http://127.0.0.1:{HOST_PORT}"
MARKER = os.environ.get("SWARM_FRESH_MARKER", f"FRESH-SWARM-{int(time.time())}")
KEEP = os.environ.get("SWARM_FRESH_KEEP", "") == "1"


def run(cmd: list[str], *, check: bool = True, timeout: int = 600) -> subprocess.CompletedProcess:
    print("+", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    if check and proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"command failed: {cmd}")
    return proc


def http_json(method: str, path: str, body: dict | None = None, *, timeout: int = 30) -> dict:
    data = None
    headers = {"Content-Type": "application/json"}
    if body is not None:
        data = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
    req = urllib.request.Request(f"{API}{path}", data=data, headers=headers, method=method.upper())
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def docker_python(code: str) -> str:
    proc = run(
        ["docker", "exec", CONTAINER, "python", "-c", code],
        timeout=300,
    )
    return proc.stdout.strip()


def wait_healthy(timeout_s: int = 180) -> None:
    deadline = time.time() + timeout_s
    last_error = "backend not healthy"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{API}/api/health", timeout=10) as resp:
                if resp.status == 200:
                    print("PASS: fresh container health")
                    return
        except Exception as exc:
            last_error = str(exc)
        time.sleep(3)
    raise RuntimeError(last_error)


def step_start_fresh_container() -> None:
    run(["docker", "rm", "-f", CONTAINER], check=False)
    run(["docker", "volume", "rm", VOLUME], check=False)
    run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            CONTAINER,
            "-p",
            f"127.0.0.1:{HOST_PORT}:8000",
            "-v",
            f"{VOLUME}:/app/data",
            IMAGE,
        ],
        timeout=120,
    )
    print(f"Started {CONTAINER} on {API} with empty volume {VOLUME}")


def step_fleet_defaults() -> None:
    out = docker_python(
        "import json; "
        "from services.mesh.mesh_fleet_defaults import infonet_fleet_join_enabled, FLEET_SEED_ONION_URL; "
        "from services.config import get_settings; "
        "print(json.dumps({"
        "'fleet_join': infonet_fleet_join_enabled(), "
        "'seed': FLEET_SEED_ONION_URL, "
        "'arti': bool(get_settings().MESH_ARTI_ENABLED), "
        "'push_secret_configured': bool(__import__('services.mesh.mesh_fleet_defaults', fromlist=['effective_peer_push_secret']).effective_peer_push_secret())"
        "}))"
    )
    payload = json.loads(out)
    if not payload.get("fleet_join"):
        raise RuntimeError(f"fleet join disabled in fresh image: {payload}")
    if not str(payload.get("seed") or "").endswith(".onion:8000"):
        raise RuntimeError(f"unexpected fleet seed in fresh image: {payload}")
    if not payload.get("push_secret_configured"):
        raise RuntimeError(f"fleet HMAC not configured in fresh image: {payload}")
    print("PASS: image ships sb-testnet fleet defaults (no env edits)")


def step_node_join_like_ui() -> dict:
    """NODE / meshnode equivalent: warm Tor, enable node, announce, pull manifest."""
    code = r"""
import json
import time
from services.openclaw_infonet import ensure_infonet_ready
from services.mesh.mesh_swarm_runtime import announce_local_peer_to_seeds, refresh_swarm_manifest_from_seeds

warm = ensure_infonet_ready(join_swarm=False)
if not warm.get("ok"):
    print(json.dumps(warm))
    raise SystemExit(1)

joined = {"ok": False, "announce": {}, "manifest_pull": {}}
try:
    from services.mesh.mesh_swarm_runtime import join_swarm_with_retries
    joined = join_swarm_with_retries()
except Exception:
    for attempt in range(6):
        announce = announce_local_peer_to_seeds(force=True)
        manifest = refresh_swarm_manifest_from_seeds(force=True)
        joined = {
            "ok": False,
            "attempts": attempt + 1,
            "announce": announce,
            "manifest_pull": manifest,
        }
        announce_ok = any(
            int(r.get("status_code") or 0) == 200
            for r in (announce.get("results") or [])
            if r.get("ok")
        )
        manifest_ok = bool(manifest.get("ok")) and int(
            manifest.get("merged_peer_count") or manifest.get("peer_count") or 0
        ) >= 1
        if announce_ok and manifest_ok:
            joined["ok"] = True
            break
        time.sleep(15)

warm["steps"]["announce"] = joined.get("announce") or {}
warm["steps"]["manifest_pull"] = joined.get("manifest_pull") or {}
warm["steps"]["swarm_attempts"] = joined.get("attempts")
warm["ok"] = bool(joined.get("ok"))
warm["detail"] = "Infonet participant runtime ready" if warm["ok"] else "swarm join incomplete"
print(json.dumps(warm))
"""
    payload = json.loads(docker_python(code))
    print("fresh join:", json.dumps(payload, indent=2)[:5000])
    if not payload.get("ok"):
        raise RuntimeError(f"fresh NODE-equivalent join failed: {payload}")

    announce = (payload.get("steps") or {}).get("announce") or {}
    manifest = (payload.get("steps") or {}).get("manifest_pull") or {}
    attempts = (payload.get("steps") or {}).get("swarm_attempts")
    results = announce.get("results") or []
    if not any(r.get("ok") and int(r.get("status_code") or 0) == 200 for r in results):
        raise RuntimeError(f"seed announce did not return 200: {announce}")
    peer_count = int(manifest.get("merged_peer_count") or manifest.get("peer_count") or 0)
    if peer_count < 1:
        raise RuntimeError(f"manifest pull returned no peers: {manifest}")
    attempt_note = f" after {attempts} attempt(s)" if attempts else ""
    print(f"PASS: announce 200 + manifest ({peer_count} peer(s)){attempt_note}")
    return payload


def step_gate_message_visible() -> None:
    marker = json.dumps(MARKER)
    code = f"""
import json
from services.mesh.mesh_hashchain import infonet
from services.openclaw_infonet import post_gate_message

before = len(infonet.events)
result = post_gate_message("infonet", {marker})
after = len(infonet.events)
print(json.dumps({{"ok": bool(result.get("ok")), "before": before, "after": after, "result": result}}))
"""
    payload = json.loads(docker_python(code))
    if not payload.get("ok"):
        raise RuntimeError(f"gate post failed on fresh node: {payload}")
    if int(payload.get("after") or 0) <= int(payload.get("before") or 0):
        raise RuntimeError(f"gate message not appended locally: {payload}")
    print(f"PASS: gate message '{MARKER}' visible in local infonet chain")


def cleanup() -> None:
    if KEEP:
        print(f"KEEP=1: leaving {CONTAINER} and volume {VOLUME} running")
        return
    run(["docker", "rm", "-f", CONTAINER], check=False)
    run(["docker", "volume", "rm", VOLUME], check=False)
    print("cleaned up fresh smoke container + volume")


def main() -> int:
    try:
        print(f"Fresh participant swarm smoke ({IMAGE})")
        step_start_fresh_container()
        wait_healthy()
        step_fleet_defaults()
        step_node_join_like_ui()
        step_gate_message_visible()
        print("ALL FRESH PARTICIPANT SWARM CHECKS PASSED")
        return 0
    finally:
        cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
