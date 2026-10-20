#!/usr/bin/env python3
"""Verify v1 Infonet swarm: fleet join, manifest peers, optional gate propagation."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

API = os.environ.get("SHADOWBROKER_API", "http://127.0.0.1:8000").strip().rstrip("/")
MARKER = os.environ.get("SWARM_VERIFY_MARKER", f"SWARM-V1-{int(time.time())}")


def http_json(method: str, path: str, body: dict | None = None, *, timeout: int = 180) -> dict:
    data = None
    headers = {"Content-Type": "application/json"}
    if body is not None:
        data = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
    req = urllib.request.Request(f"{API}{path}", data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} -> {exc.code}: {detail}") from exc


def docker_python(code: str) -> str:
    proc = subprocess.run(
        ["docker", "exec", "shadowbroker-backend", "python", "-c", code],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "docker exec failed")
    return proc.stdout.strip()


def step_ghcr_fleet_join() -> None:
    out = docker_python(
        "import json; "
        "from services.mesh.mesh_fleet_defaults import infonet_fleet_join_enabled, FLEET_SEED_ONION_URL; "
        "print(json.dumps({'fleet_join': infonet_fleet_join_enabled(), 'seed': FLEET_SEED_ONION_URL}))"
    )
    payload = json.loads(out)
    if not payload.get("fleet_join"):
        raise RuntimeError(f"fleet join disabled in container: {payload}")
    if not str(payload.get("seed") or "").endswith(".onion:8000"):
        raise RuntimeError(f"unexpected fleet seed: {payload}")
    print("PASS: container has fleet join defaults")


def step_enable_node_and_join() -> dict:
    code = r"""
import json
import main as main_mod
from services.mesh.mesh_swarm_runtime import (
    announce_local_peer_to_seeds,
    refresh_swarm_manifest_from_seeds,
)

main_mod._set_participant_node_enabled(True)
announce = announce_local_peer_to_seeds(force=True)
manifest = refresh_swarm_manifest_from_seeds(force=True)
print(json.dumps({
    'ok': bool(announce.get('ok')) or bool(manifest.get('ok')),
    'announce': announce,
    'manifest_pull': manifest,
}))
"""
    join = json.loads(docker_python(code))
    print("swarm/join:", json.dumps(join, indent=2)[:4000])
    if not join.get("ok"):
        raise RuntimeError(f"swarm join failed: {join}")
    manifest = join.get("manifest_pull") or {}
    peer_count = int(manifest.get("merged_peer_count") or manifest.get("peer_count") or 0)
    if peer_count < 1:
        raise RuntimeError(f"manifest has no peers: {join}")
    print(f"PASS: swarm join ok ({peer_count} manifest peer(s))")
    return join


def step_manifest_lists_pete(join: dict) -> None:
    manifest = join.get("manifest_pull") or {}
    peer_count = int(manifest.get("merged_peer_count") or manifest.get("peer_count") or 0)
    if peer_count < 2:
        raise RuntimeError(f"expected fleet manifest with seed + participants, got: {manifest}")
    code = r"""
import json
from services.mesh.mesh_router import authenticated_push_peer_urls
print(json.dumps({'push_peers': authenticated_push_peer_urls()[:12]}))
"""
    payload = json.loads(docker_python(code))
    push_peers = [p for p in payload.get("push_peers") or [] if p]
    onion_peers = [p for p in push_peers if ".onion" in p]
    print("sync peer store:", json.dumps(payload, indent=2))
    if not onion_peers:
        raise RuntimeError(f"expected onion peers in local sync store after manifest pull, got: {push_peers}")
    print("PASS: manifest pull populated onion fleet peer(s)")


def step_gate_propagation() -> None:
    try:
        subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(__file__), "e2e_openclaw_infonet_agent_live.py")],
            env={**os.environ, "E2E_MARKER": MARKER, "SHADOWBROKER_API": API},
            check=True,
            timeout=600,
        )
        print("PASS: gate event propagated across fleet")
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"gate propagation check failed (exit {exc.returncode})") from exc
    except FileNotFoundError:
        print("SKIP: e2e_openclaw_infonet_agent_live.py not available")


def main() -> int:
    print(f"Swarm v1 verify against {API}")
    step_ghcr_fleet_join()
    join = step_enable_node_and_join()
    step_manifest_lists_pete(join)
    if os.environ.get("SWARM_VERIFY_SKIP_PROPAGATION") != "1":
        step_gate_propagation()
    print("ALL SWARM V1 CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
