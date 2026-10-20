#!/usr/bin/env python3
"""Merge curated plane-alert-db rows into backend/data/tracked_names.json.

Only real people, companies, and organizations — never plane-alert joke tags
(The Gambler, Genomes, Aaaaaaaand its gone, etc.).
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SB_PATH = ROOT / "backend" / "data" / "tracked_names.json"
PAD = Path.home() / "Downloads" / "plane-alert-db-main" / "plane-alert-db-main"

STRICT_CATS = {
    "Don't you know who I am?",
    "Oligarch",
    "Royal Aircraft",
    "Football",
}

GENERIC_TAGS = {
    "bizjet", "bizjets", "pusher prop", "man made climate change", "government",
    "royalty", "pga", "nfl", "nba", "basketball", "war eagle", "volunteers",
    "original nuttah", "jumpers for goalposts", "money money money", "safe return",
    "do a barrel roll", "biplane", "aerospace", "medical", "defense",
    "the gambler", "the house always wins", "house always wins", "snake eyes",
    "bunch of bankers", "scrooge mcduck", "aaaaaaaand its gone", "aaaaaaand its gone",
    "genomes", "football", "zoomies", "you can't see me", "too much money",
    "venture capital", "honda jet", "basic cable", "as seen on tv", "joe cool",
}

COMPANY_HINTS = re.compile(
    r"\b(inc|llc|ltd|corp|company|co\.|bank|group|holdings|international|"
    r"university|airlines|aviation|systems|foundation|tribe|resorts|casino|"
    r"palace|entertainment|insurance|credit union|banco|sa|ag|gmbh|plc)\b",
    re.I,
)

MERGE_ALIASES: dict[str, str] = {
    "falcon landing llc": "Elon Musk",
    "christian ronaldo": "Cristiano Ronaldo",
    "elon musk": "Elon Musk",
    "marc benioff": "Mark Benioff",
    "p. diddy": "P. Diddy",
    "baller": "P. Diddy",
    "empire state of mind": "Jay Z",
    "judy sheindlin": "Judge Judy",
    "doge": "Vivek Ramaswamy",
    "a&m records": "Jerry Moss",
    "wings of grace": "Folorunso Alakija",
    "reliance commercial dealers ltd": "Mukesh Ambani",
    "monaco royal family": "Monaco Royal Family",
    "the royal squadron": "UK Royal Family (RAF)",
    "the kings helicopter flight": "UK Royal Family (RAF)",
}


def norm_reg(s: str) -> str:
    return (s or "").strip().upper()


def row_get(row: dict[str, str], *keys: str) -> str:
    for key in keys:
        if row.get(key):
            return str(row[key]).strip()
    return ""


def sb_category(cat: str, display: str, operator: str) -> str:
    if cat == "Oligarch":
        return "Oligarch"
    if cat in {"Royal Aircraft"} or "royal" in display.lower():
        return "Royal"
    if cat == "Football":
        return "Sports"
    if COMPANY_HINTS.search(operator) or COMPANY_HINTS.search(display):
        return "Business"
    return "Celebrity"


def is_likely_person_name(text: str) -> bool:
    t = text.strip()
    if not t or t.lower() in GENERIC_TAGS:
        return False
    if any(ch in t for ch in "?!"):
        return False
    if COMPANY_HINTS.search(t):
        return False
    words = t.split()
    if len(words) < 2 or len(words) > 5:
        return False
    # Require each word to look name-like (Title case or Mc/Mac/O').
    for w in words:
        if not re.match(r"^[A-Z][\w'.-]*$|^(Mc|Mac|O')[A-Z]", w):
            return False
    return True


def pick_display_name(operator: str, tag1: str, tag2: str, tag3: str, cat: str) -> str | None:
    op_key = operator.strip().lower()
    if op_key in MERGE_ALIASES:
        return MERGE_ALIASES[op_key]

    op = operator.strip()
    if cat == "Football":
        return op or None

    if cat == "Royal Aircraft":
        return op or None

    if cat == "Oligarch":
        if is_likely_person_name(op):
            return op
        for tag in (tag2, tag3, tag1):
            if is_likely_person_name(tag):
                return tag.strip()
        return op or None

    if cat == "Don't you know who I am?":
        if is_likely_person_name(op):
            return op
        for tag in (tag2, tag3, tag1):
            if is_likely_person_name(tag):
                return tag.strip()
        if op and not op.lower() in GENERIC_TAGS:
            return op
        return None

    return None


def load_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for fname in ("plane-alert-db.csv", "plane-alert-civ.csv"):
        path = PAD / fname
        if not path.exists():
            continue
        with path.open(encoding="utf-8", errors="replace") as f:
            rows.extend(list(csv.DictReader(f)))
    return rows


def main() -> None:
    with SB_PATH.open(encoding="utf-8") as f:
        sb = json.load(f)

    details: dict = sb.setdefault("details", {})
    names_list: list[dict[str, str]] = sb.setdefault("names", [])
    existing_names = {n["name"] for n in names_list}

    sb_regs: set[str] = set()
    for info in details.values():
        for reg in info.get("registrations", []):
            r = norm_reg(reg)
            if r:
                sb_regs.add(r)

    added_entries = 0
    added_regs = 0
    merged_regs = 0

    seen: set[tuple[str, str]] = set()

    for row in load_rows():
        cat = row_get(row, "Category")
        if cat not in STRICT_CATS:
            continue

        reg = norm_reg(row_get(row, "$Registration", "Registration"))
        if not reg or (reg, cat) in seen:
            continue
        seen.add((reg, cat))

        operator = row_get(row, "$Operator", "Operator")
        tag1 = row_get(row, "$Tag 1", "Tag 1")
        tag2 = row_get(row, "#Tag 2", "$#Tag 2")
        tag3 = row_get(row, "#Tag 3", "$#Tag 3")

        display = pick_display_name(operator, tag1, tag2, tag3, cat)
        if not display or reg in sb_regs:
            continue

        category = sb_category(cat, display, operator)

        if display in details:
            regs = details[display].setdefault("registrations", [])
            if reg not in regs:
                regs.append(reg)
                merged_regs += 1
                sb_regs.add(reg)
            continue

        details[display] = {
            "category": category,
            "registrations": [reg],
        }
        if display not in existing_names:
            names_list.append({"name": display, "category": category})
            existing_names.add(display)
            added_entries += 1
        added_regs += 1
        sb_regs.add(reg)

    uk_key = "UK Royal Family (RAF)"
    uk_regs = ["G-XWBG", "GZ-100", "ZE700", "ZE701", "ZE707", "ZE708", "G-XXEC"]
    if uk_key in details:
        details[uk_key]["category"] = "Royal"
        regs = details[uk_key].setdefault("registrations", [])
        for r in uk_regs:
            if r not in regs:
                regs.append(r)
                merged_regs += 1
    else:
        details[uk_key] = {"category": "Royal", "registrations": uk_regs}
        if uk_key not in existing_names:
            names_list.append({"name": uk_key, "category": "Royal"})
            added_entries += 1

    names_list.sort(key=lambda x: x["name"].lower())

    with SB_PATH.open("w", encoding="utf-8") as f:
        json.dump(sb, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"New tracked entries: {added_entries}")
    print(f"New registrations: {added_regs}")
    print(f"Merged into existing: {merged_regs}")
    print(f"Total details entries: {len(details)}")
    print(f"Total registrations: {sum(len(v.get('registrations',[])) for v in details.values())}")


if __name__ == "__main__":
    main()
