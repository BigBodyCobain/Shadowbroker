"""CISA KEV + cyber threat stats (Osiris port)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from services.fetchers._store import _data_lock, _mark_fresh, is_any_active, latest_data
from services.network_utils import fetch_with_curl

logger = logging.getLogger(__name__)


def fetch_cyber_threats() -> dict[str, Any]:
    if not is_any_active("cyber_threats"):
        return latest_data.get("cyber_threats") or {"threats": [], "stats": {}}

    results: dict[str, Any] = {"threats": [], "stats": {}, "timestamp": datetime.now(timezone.utc).isoformat()}
    try:
        resp = fetch_with_curl(
            "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json",
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            vulns = data.get("vulnerabilities") or []
            results["stats"]["cisa_total"] = len(vulns)
            now = datetime.now(timezone.utc)
            recent = []
            for v in vulns:
                try:
                    added = datetime.fromisoformat(v.get("dateAdded", "").replace("Z", "+00:00"))
                    days = (now - added).total_seconds() / 86400
                except Exception:
                    continue
                if days <= 30:
                    recent.append(v)
            recent = recent[:10]
            results["threats"] = [
                {
                    "id": v.get("cveID"),
                    "name": v.get("vulnerabilityName"),
                    "vendor": v.get("vendorProject"),
                    "product": v.get("product"),
                    "severity": "CRITICAL",
                    "date": v.get("dateAdded"),
                    "due": v.get("dueDate"),
                    "source": "CISA KEV",
                }
                for v in recent
            ]
    except Exception as exc:
        logger.warning("CISA KEV fetch failed: %s", exc)

    count = len(results["threats"])
    results["stats"]["active_cves"] = count
    results["stats"]["threat_level"] = "CRITICAL" if count >= 8 else "HIGH" if count >= 4 else "ELEVATED"

    with _data_lock:
        latest_data["cyber_threats"] = results
    _mark_fresh("cyber_threats")
    return results
