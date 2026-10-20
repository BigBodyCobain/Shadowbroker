#!/usr/bin/env python3
"""One-shot get_summary for OpenClaw exec — loads .env.shadowbroker automatically."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path


def _load_env() -> None:
    candidates = [
        Path.home() / ".openclaw" / "workspace" / ".env.shadowbroker",
        Path(__file__).resolve().parent.parent.parent / ".env.shadowbroker",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())
        break


async def main() -> None:
    _load_env()
    from sb_query import ShadowBrokerClient

    sb = ShadowBrokerClient()
    try:
        resp = await sb.send_command("get_summary", {"compact": True})
        print(json.dumps(resp, indent=2))
    finally:
        await sb.close()


if __name__ == "__main__":
    asyncio.run(main())