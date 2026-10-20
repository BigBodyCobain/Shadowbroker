#!/usr/bin/env python3
"""Compare plane-alert-db CSVs to Shadowbroker tracked_names.json."""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

SB = Path(__file__).resolve().parents[1] / "backend" / "data" / "tracked_names.json"
PAD = Path.home() / "Downloads" / "plane-alert-db-main" / "plane-alert-db-main"

CELEB_CATS = {
    "Don't you know who I am?",
    "As Seen on TV",
    "Joe Cool",
    "Vanity Plate",
    "Football",
    "Head of State",
    "Royal Aircraft",
    "Oligarch",
    "Bizjets",
}

PURE_CELEB_CATS = {
    "Don't you know who I am?",
    "As Seen on TV",
    "Joe Cool",
    "Vanity Plate",
    "Football",
}


def norm_name(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def load_csv(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with path.open(encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows


def row_field(row: dict[str, str], *keys: str) -> str:
    for key in keys:
        if row.get(key):
            return str(row[key]).strip()
    return ""


def main() -> None:
    with SB.open(encoding="utf-8") as f:
        sb = json.load(f)

    sb_regs: set[str] = set()
    sb_names: set[str] = set()
    for name, info in sb.get("details", {}).items():
        sb_names.add(norm_name(name))
        for reg in info.get("registrations", []):
            r = reg.strip().upper()
            if r:
                sb_regs.add(r)

    rows: list[dict[str, str]] = []
    for fname in ("plane-alert-db.csv", "plane-alert-civ.csv"):
        path = PAD / fname
        if path.exists():
            rows.extend(load_csv(path))

    seen: set[tuple[str, str, str]] = set()
    new_by_cat: dict[str, list[dict[str, str]]] = {}

    for row in rows:
        cat = row_field(row, "Category")
        if cat not in CELEB_CATS:
            continue
        reg = row_field(row, "$Registration", "Registration").upper()
        op = row_field(row, "$Operator", "Operator")
        icao = row_field(row, "$ICAO", "ICAO").upper()
        if not reg and not op:
            continue
        key = (reg, norm_name(op), cat)
        if key in seen:
            continue
        seen.add(key)

        in_sb = False
        if reg and reg in sb_regs:
            in_sb = True
        if norm_name(op) in sb_names:
            in_sb = True
        if not in_sb and op:
            opn = norm_name(op)
            for sn in sb_names:
                if len(sn) >= 6 and (sn in opn or opn in sn):
                    in_sb = True
                    break

        if in_sb:
            continue

        entry = {
            "registration": reg,
            "operator": op,
            "category": cat,
            "type": row_field(row, "$Type", "Type"),
            "icao": icao,
            "tag1": row_field(row, "$Tag 1", "Tag 1"),
        }
        new_by_cat.setdefault(cat, []).append(entry)

    print("=== Shadowbroker tracked ===")
    print(f"  names in details: {len(sb_names)}")
    print(f"  registrations: {len(sb_regs)}")
    print()
    print("=== NEW celebrity/VIP-ish entries (not in Shadowbroker) ===")

    total = 0
    for cat in sorted(new_by_cat, key=lambda c: -len(new_by_cat[c])):
        items = new_by_cat[cat]
        total += len(items)
        print(f"\n## {cat} ({len(items)})")
        for e in sorted(items, key=lambda x: x["operator"])[:30]:
            reg = e["registration"] or "(no reg)"
            tag = f" | {e['tag1']}" if e["tag1"] else ""
            print(f"  {reg:12} {e['operator'][:60]}{tag}")
        if len(items) > 30:
            print(f"  ... and {len(items) - 30} more")

    print(f"\n=== TOTAL NEW (all VIP categories): {total} ===")

    pure_items = [e for c in PURE_CELEB_CATS for e in new_by_cat.get(c, [])]
    print(f"\n=== HIGH-SIGNAL CELEB / NOTABLE ({len(pure_items)}) ===")
    for e in sorted(pure_items, key=lambda x: (x["category"], x["operator"])):
        reg = e["registration"] or "????"
        tag = f" ({e['tag1']})" if e["tag1"] else ""
        print(f"[{e['category']}] {reg} — {e['operator']}{tag}")


if __name__ == "__main__":
    main()
