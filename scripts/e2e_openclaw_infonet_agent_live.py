#!/usr/bin/env python3
"""Live E2E: OpenClaw HMAC agent posts to Infonet gate and verifies propagation."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SKILL_DIR = os.path.join(ROOT, "openclaw-skills", "shadowbroker")
API = os.environ.get("SHADOWBROKER_API", "http://127.0.0.1:8000")
MARKER = os.environ.get("E2E_MARKER", f"OPENCLAW-AGENT-E2E-{int(time.time())}")


def _json_request(method: str, path: str, body: dict | None = None, *, inside_docker: bool = False) -> dict:
    data = None
    headers = {"Content-Type": "application/json"}
    if body is not None:
        data = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
    req = urllib.request.Request(f"{API}{path}", data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
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


def bootstrap_hmac_and_full_tier() -> str:
    setup = r"""
import json, urllib.request
BASE = 'http://127.0.0.1:8000'

def call(method, path, body=None):
    data = json.dumps(body or {}, separators=(',', ':'), sort_keys=True).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers={'Content-Type': 'application/json'}, method=method)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())

call('POST', '/api/ai/connect-info/bootstrap', {})
call('PUT', '/api/ai/connect-info/access-tier', {'tier': 'full'})
secret = call('POST', '/api/ai/connect-info/reveal', {})['hmac_secret']
print(secret)
"""
    secret = docker_python(setup)
    if not secret or len(secret) < 16:
        raise RuntimeError(f"unexpected HMAC secret: {secret!r}")
    return secret


async def agent_post(secret: str, message: str) -> dict:
    sys.path.insert(0, SKILL_DIR)
    from sb_query import ShadowBrokerClient

    os.environ["SHADOWBROKER_HMAC_SECRET"] = secret
    client = ShadowBrokerClient(base_url=API)
    try:
        ready = await client.ensure_infonet_ready(join_swarm=True)
        print("ensure_infonet_ready:", json.dumps(ready, indent=2)[:2000])
        if not ready.get("ok"):
            raise RuntimeError(f"ensure_infonet_ready failed: {ready}")

        post = await client.post_to_gate("infonet", message)
        print("post_to_gate:", json.dumps(post, indent=2)[:2000])
        if not post.get("ok"):
            raise RuntimeError(f"post_to_gate failed: {post}")
        return post
    finally:
        await client.close()


def local_gate_has_event(event_id: str) -> bool:
    code = f"""
from services.mesh.mesh_hashchain import gate_store
evt = gate_store.get_event({event_id!r})
print('yes' if evt else 'no')
"""
    return docker_python(code) == "yes"


REMOTE_CONTAINERS = {
    "shadowbroker": "shadowbroker-relay",  # seed VPS
    "pete": "shadowbroker-backend",
}


def peer_gate_has_event(host: str, event_id: str) -> bool:
    container = REMOTE_CONTAINERS.get(host, "shadowbroker-backend")
    remote_code = (
        "from services.mesh.mesh_hashchain import gate_store; "
        f"print('yes' if gate_store.get_event({event_id!r}) else 'no')"
    )
    import shlex

    ssh = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        host,
        f"docker exec {container} python -c {shlex.quote(remote_code)}",
    ]
    proc = subprocess.run(ssh, capture_output=True, text=True, timeout=120, check=False)
    out = (proc.stdout or "").strip()
    if proc.returncode != 0:
        print(f"ssh {host} warn:", proc.stderr.strip() or proc.stdout.strip())
        return False
    return out == "yes"


def wait_for_propagation(event_id: str, *, seconds: int = 90) -> dict[str, bool]:
    deadline = time.time() + seconds
    results = {"local": False, "seed": False, "pete": False}
    while time.time() < deadline:
        results["local"] = local_gate_has_event(event_id)
        results["seed"] = peer_gate_has_event("shadowbroker", event_id)
        results["pete"] = peer_gate_has_event("pete", event_id)
        if all(results.values()):
            break
        time.sleep(5)
    return results


def main() -> int:
    print(f"E2E marker: {MARKER}")
    secret = bootstrap_hmac_and_full_tier()
    print("HMAC secret bootstrapped (full tier)")

    post = asyncio.run(agent_post(secret, MARKER))
    event_id = str(post.get("event_id") or "")
    if not event_id:
        raise RuntimeError(f"post succeeded but no event_id in response: {post}")
    print(f"event_id={event_id}")

    print("Waiting for propagation to local / seed / pete ...")
    results = wait_for_propagation(event_id, seconds=120)
    print("propagation:", json.dumps(results, indent=2))

    if not results["local"]:
        raise SystemExit("FAIL: event not in local gate_store")
    if not results["seed"] and not results["pete"]:
        raise SystemExit("FAIL: event not observed on seed or pete within timeout")

    if results["seed"] and results["pete"]:
        print("PASS: agent HMAC post propagated to local, seed, and pete")
        return 0
    print("PARTIAL: local ok; seed=%s pete=%s" % (results["seed"], results["pete"]))
    return 0 if results["local"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
