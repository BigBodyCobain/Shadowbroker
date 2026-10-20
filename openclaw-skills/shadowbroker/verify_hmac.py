#!/usr/bin/env python3
"""Verify OpenClaw HMAC auth against a running ShadowBroker backend.

Usage:
    export SHADOWBROKER_URL=http://127.0.0.1:8000
    export SHADOWBROKER_HMAC_SECRET=<from Connect OpenClaw modal>
    python verify_hmac.py

Signs the same canonical JSON body as openclaw-skills/shadowbroker/sb_query.py.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request


def sign(method: str, path: str, body: bytes, secret: str) -> dict[str, str]:
    ts = str(int(time.time()))
    nonce = secrets.token_hex(16)
    digest = hashlib.sha256(body).hexdigest()
    message = f"{method.upper()}|{path}|{ts}|{nonce}|{digest}"
    signature = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return {
        "X-SB-Timestamp": ts,
        "X-SB-Nonce": nonce,
        "X-SB-Signature": signature,
        "Content-Type": "application/json",
    }


def main() -> int:
    base = os.environ.get("SHADOWBROKER_URL", "http://127.0.0.1:8000").rstrip("/")
    secret = os.environ.get("SHADOWBROKER_HMAC_SECRET", "").strip()
    if not secret:
        print("Set SHADOWBROKER_HMAC_SECRET to the value from Connect OpenClaw.", file=sys.stderr)
        return 2

    path = "/api/ai/channel/command"
    payload = {"cmd": "channel_status", "args": {}}
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    headers = sign("POST", path, body, secret)
    req = urllib.request.Request(
        f"{base}{path}",
        data=body,
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            print(f"HTTP {resp.status}")
            print(text)
            return 0
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"HTTP {exc.code}")
        print(detail)
        if exc.code == 403:
            print(
                "\nTips:\n"
                "- Bootstrap + Reveal the HMAC secret in AI Intel → Connect OpenClaw\n"
                "- Use the exact secret (no extra whitespace)\n"
                "- Sign compact JSON: json.dumps(..., separators=(',', ':'), sort_keys=True)\n"
                "- Hit the backend port directly (e.g. :8000), not the Next.js :3000 proxy\n"
                "- After upgrading, restart the backend so data/openclaw.env is loaded",
                file=sys.stderr,
            )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
