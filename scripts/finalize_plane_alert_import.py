#!/usr/bin/env python3
"""Sync plane_alert_db.json from upstream CSV and add explicit celeb/royal tails.

Does NOT import plane-alert joke tags into tracked_names.json.
"""
from __future__ import annotations

import csv
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SB_PATH = ROOT / "backend" / "data" / "tracked_names.json"
PADB_PATH = ROOT / "backend" / "data" / "plane_alert_db.json"
PAD = Path.home() / "Downloads" / "plane-alert-db-main" / "plane-alert-db-main"

MANUAL_TRACKED: list[tuple[str, str, list[str]]] = [
    ("Michael Dell", "Celebrity", ["N28ZD"]),
    ("Lady Moura", "Celebrity", ["VP-CNR"]),
    ("Lewis Hamilton", "Celebrity", ["G-OFOM"]),
    ("Mario Andretti", "Celebrity", ["N500MA"]),
    ("Frank Lowry", "Celebrity", ["N613LF"]),
    ("Mukesh Ambani", "Celebrity", ["VT-AKV"]),
    ("Judge Judy", "Celebrity", ["N555QB"]),
    ("Monaco Royal Family", "Royal", ["3A-MGA"]),
    ("PGA Tour", "Sports", ["N795HG"]),
]


def norm_reg(s: str) -> str:
    return (s or "").strip().upper()


def norm_icao(s: str) -> str:
    return (s or "").strip().upper()


def row_get(row: dict[str, str], *keys: str) -> str:
    for key in keys:
        if row.get(key):
            return str(row[key]).strip()
    return ""


def load_git_baseline() -> set[str]:
    raw = subprocess.check_output(
        ["git", "-C", str(ROOT), "show", "HEAD:backend/data/tracked_names.json"],
    )
    data = json.loads(raw)
    return set(data.get("details", {}).keys())


def wiki_from_link(link: str) -> str:
    if not link:
        return ""
    if "wikipedia.org/wiki/" in link:
        return link.rsplit("/wiki/", 1)[-1].split("#")[0]
    return ""


def steal_reg(details: dict, reg: str, protect_names: set[str]) -> None:
    reg = norm_reg(reg)
    for name, info in list(details.items()):
        if name in protect_names:
            continue
        regs = info.get("registrations", [])
        kept = [r for r in regs if norm_reg(r) != reg]
        if len(kept) != len(regs):
            if kept:
                info["registrations"] = kept
            else:
                del details[name]


def ensure_entry(
    details: dict,
    names_list: list,
    name: str,
    category: str,
    reg: str,
    *,
    protect_names: set[str] | None = None,
) -> bool:
    reg = norm_reg(reg)
    if not reg:
        return False
    steal_reg(details, reg, protect_names or set())
    entry = details.setdefault(name, {"category": category, "registrations": []})
    entry["category"] = category
    if reg not in {norm_reg(r) for r in entry["registrations"]}:
        entry["registrations"].append(reg)
    if name not in {n["name"] for n in names_list}:
        names_list.append({"name": name, "category": category})
    return True


def sync_plane_alert_db() -> tuple[int, int]:
    if not PADB_PATH.exists():
        return 0, 0
    with PADB_PATH.open(encoding="utf-8") as f:
        db: dict = json.load(f)

    updated = 0
    added = 0
    for fname in (
        "plane-alert-db.csv",
        "plane-alert-civ.csv",
        "plane-alert-gov.csv",
        "plane-alert-mil.csv",
        "plane-alert-pol.csv",
    ):
        path = PAD / fname
        if not path.exists():
            continue
        with path.open(encoding="utf-8", errors="replace") as f:
            for row in csv.DictReader(f):
                icao = norm_icao(row_get(row, "$ICAO", "ICAO"))
                if not icao:
                    continue
                reg = row_get(row, "$Registration", "Registration")
                operator = row_get(row, "$Operator", "Operator")
                ac_type = row_get(row, "$Type", "Type")
                category = row_get(row, "Category")
                tag1 = row_get(row, "$Tag 1", "Tag 1")
                tag2 = row_get(row, "#Tag 2", "$#Tag 2")
                tag3 = row_get(row, "#Tag 3", "$#Tag 3")
                link = row_get(row, "$#Link", "#Link", "$#Link ")
                tags = ", ".join(t for t in (tag1, tag2, tag3) if t)

                record = {
                    "registration": reg,
                    "operator": operator,
                    "ac_type": ac_type,
                    "category": category,
                    "tags": tags,
                    "link": link,
                }
                wiki = wiki_from_link(link)
                if wiki:
                    record["wiki"] = wiki

                if icao in db:
                    if db[icao] != record:
                        db[icao] = record
                        updated += 1
                else:
                    db[icao] = record
                    added += 1

    with PADB_PATH.open("w", encoding="utf-8") as f:
        json.dump(db, f, indent=4, ensure_ascii=False)
        f.write("\n")
    return added, updated


def main() -> None:
    baseline_keys = load_git_baseline()

    with SB_PATH.open(encoding="utf-8") as f:
        sb = json.load(f)

    details: dict = sb.setdefault("details", {})
    names_list: list[dict] = sb.setdefault("names", [])

    manual_added = 0
    for name, category, regs in MANUAL_TRACKED:
        for reg in regs:
            if ensure_entry(details, names_list, name, category, reg, protect_names=baseline_keys):
                manual_added += 1

    for key in baseline_keys:
        if key not in details:
            raise RuntimeError(f"Baseline tracked name lost: {key}")

    names_list.sort(key=lambda x: x["name"].lower())
    with SB_PATH.open("w", encoding="utf-8") as f:
        json.dump(sb, f, indent=2, ensure_ascii=False)
        f.write("\n")

    pad_added, pad_updated = sync_plane_alert_db()

    print(f"Manual celeb regs added: {manual_added}")
    print(f"plane_alert_db.json: +{pad_added} updated {pad_updated}")
    print(f"tracked_names details: {len(details)}")
    print(f"tracked_names registrations: {sum(len(v.get('registrations',[])) for v in details.values())}")


if __name__ == "__main__":
    main()
