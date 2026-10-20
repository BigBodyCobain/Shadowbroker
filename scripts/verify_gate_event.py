#!/usr/bin/env python3
import shlex
import subprocess
import sys

EVENT_ID = sys.argv[1] if len(sys.argv) > 1 else ""
if not EVENT_ID:
    raise SystemExit("usage: verify_gate_event.py <event_id>")

code = (
    "from services.mesh.mesh_hashchain import gate_store; "
    f"e=gate_store.get_event({EVENT_ID!r}); "
    "print('ok' if e else 'no')"
)

hosts = [
    ("local", None, "shadowbroker-backend"),
    ("seed", "shadowbroker", "shadowbroker-relay"),
    ("pete", "pete", "shadowbroker-backend"),
]

for label, ssh_host, container in hosts:
    remote = f"docker exec {container} python -c {shlex.quote(code)}"
    if ssh_host:
        proc = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", ssh_host, remote],
            capture_output=True,
            text=True,
            timeout=60,
        )
    else:
        proc = subprocess.run(
            ["docker", "exec", container, "python", "-c", code],
            capture_output=True,
            text=True,
            timeout=60,
        )
    out = (proc.stdout or proc.stderr).strip()
    print(f"{label}: {out}")
