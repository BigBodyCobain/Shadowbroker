#!/usr/bin/env python3
"""GT Strategic Risk report — backtest + heatmap + optional region dossier.

Backtest scores are benchmark validation on labeled historical snippets, not
forward-weeks prediction on live adversarial telemetry. See SKILL.md.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path


def _load_env() -> None:
    for path in (
        Path.home() / ".openclaw" / "workspace" / ".env.shadowbroker",
        Path(__file__).resolve().parent.parent.parent / ".env.shadowbroker",
    ):
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
    parser = argparse.ArgumentParser(description="ShadowBroker GT analytics report")
    parser.add_argument("--region", default="", help="Optional region for gt_analyze dossier")
    parser.add_argument("--tune", action="store_true", help="Grid-search backtest threshold")
    args = parser.parse_args()

    _load_env()
    from sb_query import ShadowBrokerClient

    sb = ShadowBrokerClient()
    report: dict[str, object] = {
        "benchmark_note": (
            "Backtest accuracy is on curated pre-crisis snippets vs cheap-talk controls. "
            "It does not claim multi-week forward prediction on live feeds."
        ),
    }
    try:
        report["backtest"] = await sb.gt_backtest(expanded=True, tune=args.tune)
        heatmap = await sb.gt_risk_heatmap()
        report["heatmap"] = {
            "feature_count": len(heatmap.get("features") or []),
            "clusters": heatmap.get("clusters") or [],
        }
        if args.region:
            report["analyze"] = await sb.gt_analyze(region=args.region, refresh=True)
    finally:
        await sb.close()

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())