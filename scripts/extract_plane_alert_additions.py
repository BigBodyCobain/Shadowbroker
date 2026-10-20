#!/usr/bin/env python3
"""Extract plane-alert-db entries missing from tracked_names.json."""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SB = ROOT / "backend" / "data" / "tracked_names.json"
PAD = Path.home() / "Downloads" / "plane-alert-db-main" / "plane-alert-db-main"

# Categories to import into tracked_names
IMPORT_CATS = {
    "Don't you know who I am?",
    "Oligarch",
    "Royal Aircraft",
    "Football",
    "Head of State",
    "Dictator Alert",
}

# As Seen on TV / Bizjets only when operator looks like a person (heuristic)
PERSON_CATS = {"As Seen on TV", "Bizjets", "Vanity Plate"}

# Skip obvious corps / generic operators
CORP_RE = re.compile(
    r"\b(inc|llc|ltd|corp|company|co\.|group|holdings|university|air force|"
    r"airlines|aviation|services|systems|international|global|partners|"
    r"foundation|bank|pharma|laboratories|transportation|motors|enterprises)\b",
    re.I,
)

CELEB_HINTS = re.compile(
    r"\b(actor|actress|singer|rapper|musician|celebrity|nfl|nba|f1|formula|"
    r"royal|prince|princess|king|queen|duke|sheik|sultan|oligarch|billionaire|"
    r"mogul|tycoon|founder|ceo|president|senator|governor|judge|athlete|"
    r"footballer|golfer|tennis|director|producer|host|comedian|model|"
    r"influencer|youtuber|podcast|chef|author|writer|artist|designer)\b",
    re.I,
)

KNOWN_PERSON_NAMES = {
    "elon musk", "jay z", "jay-z", "kanye", "west", "kim kardashian", "taylor swift",
    "beyonce", "drake", "rihanna", "oprah", "gates", "bezos", "zuckerberg",
    "buffett", "dalio", "icahn", "ackman", "soros", "thiel", "musk", "cruise",
    "dicaprio", "pitt", "jolie", "clooney", "hanks", "spielberg", "lucas",
    "branson", "trump", "biden", "obama", "clinton", "bush", "romney",
    "ramaswamy", "benioff", "blavatnik", "abramovich", "abramov", "potanin",
    "fridman", "deripaska", "kerimov", "tinkov", "mordashov", "rybolovlev",
    "lisin", "vekselberg", "medvedchuk", "alekperov", "mikhelson", "diddy",
    "combs", "sean combs", "ronaldo", "messi", "mbappe", "beckham", "jordan",
    "lebron", "brady", "mahomes", "kroenke", "kraft", "jones", "snyder",
    "sheindlin", "judge judy", "elton john", "moss", "ambani", "adani",
    "lowry", "ecclestone", "hamilton", "verstappen", "schumacher", "woods",
    "nicklaus", "federer", "nadal", "djokovic", "osaka", "williams", "serena",
    "venus", "sharapova", "mcgregor", "mayweather", "paul", "logan paul",
    "jake paul", "mrbeast", "pewdiepie", "charlie munger", "larry ellison",
    "michael dell", "tim cook", "satya nadella", "sundar pichai", "jensen huang",
    "gisele", "tom brady", "gwyneth", "howard stern", "howard marks",
    "steven cohen", "ken griffin", "david tepper", "ray dalio", "peter thiel",
    "paul allen", "steve ballmer", "mark cuban", "richard branson", "larry page",
    "sergey brin", "eric schmidt", "reid hoffman", "marc andreessen",
    "chamath", "naval", "andretti", "penske", "hendrick", "rick hendrick",
}


def norm_reg(s: str) -> str:
    return (s or "").strip().upper()


def norm_name(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def looks_like_person(operator: str, tag1: str, tag2: str, tag3: str) -> bool:
    blob = " ".join([operator, tag1, tag2, tag3]).strip()
    if not blob or len(blob) < 3:
        return False
    low = blob.lower()
    if CORP_RE.search(low) and not any(h in low for h in KNOWN_PERSON_NAMES):
        # allow "Falcon Landing LLC" when tag says Elon Musk
        if not any(h in low for h in KNOWN_PERSON_NAMES):
            return False
    if any(h in low for h in KNOWN_PERSON_NAMES):
        return True
    if CELEB_HINTS.search(low):
        return True
    # Two+ capitalized words, no corp suffix — weak person signal
    words = operator.split()
    if 2 <= len(words) <= 4 and operator == operator.title() and not CORP_RE.search(low):
        return True
    return False


def sb_category_for(cat: str, operator: str) -> str:
    low = operator.lower()
    if cat in {"Oligarch", "Dictator Alert"}:
        return "Oligarch"
    if cat == "Royal Aircraft" or "royal" in low:
        return "Royal"
    if cat == "Football":
        return "Sports"
    if cat in {"Head of State"}:
        return "Government"
    if any(x in low for x in ("nfl", "nba", "mlb", "football", "basketball", "soccer", "f1", "formula")):
        return "Sports"
    return "Celebrity"


def row_get(row: dict[str, str], *keys: str) -> str:
    for k in keys:
        if row.get(k):
            return str(row[k]).strip()
    return ""


def main() -> None:
    with SB.open(encoding="utf-8") as f:
        sb = json.load(f)

    sb_regs: set[str] = set()
    sb_names: dict[str, str] = {}
    for name, info in sb.get("details", {}).items():
        for reg in info.get("registrations", []):
            r = norm_reg(reg)
            if r:
                sb_regs.add(r)
                sb_names[r] = name

    additions: dict[str, dict] = {}
    merge: dict[str, list[str]] = {}

    csv_paths = [
        PAD / "plane-alert-db.csv",
        PAD / "plane-alert-civ.csv",
        PAD / "plane-alert-gov.csv",
        PAD / "plane-alert-mil.csv",
    ]

    seen: set[tuple[str, str]] = set()
    person_hits = 0

    for path in csv_paths:
        if not path.exists():
            continue
        with path.open(encoding="utf-8", errors="replace") as f:
            for row in csv.DictReader(f):
                cat = row_get(row, "Category")
                reg = norm_reg(row_get(row, "$Registration", "Registration"))
                op = norm_reg(row_get(row, "$Operator", "Operator"))
                op_display = norm_name(row_get(row, "$Operator", "Operator"))
                tag1 = row_get(row, "$Tag 1", "Tag 1")
                tag2 = row_get(row, "#Tag 2", "$#Tag 2")
                tag3 = row_get(row, "#Tag 3", "$#Tag 3")

                if not reg:
                    continue
                if (reg, cat) in seen:
                    continue
                seen.add((reg, cat))

                include = cat in IMPORT_CATS
                if not include and cat in PERSON_CATS:
                    if looks_like_person(op_display, tag1, tag2, tag3):
                        include = True
                        person_hits += 1

                if not include:
                    continue
                if reg in sb_regs:
                    continue

                # Prefer tag person name over shell company
                display = op_display
                for tag in (tag1, tag2, tag3):
                    if tag and any(h in tag.lower() for h in KNOWN_PERSON_NAMES):
                        display = tag
                        break
                    if tag and len(tag.split()) <= 4 and tag[0].isupper() and "llc" not in tag.lower():
                        if cat == "Don't you know who I am?" and tag not in {"Bizjet", "Pusher Prop"}:
                            display = tag

                key = display
                if key in sb.get("details", {}):
                    merge.setdefault(key, []).append(reg)
                else:
                    entry = additions.setdefault(
                        key,
                        {"category": sb_category_for(cat, display), "registrations": []},
                    )
                    if reg not in entry["registrations"]:
                        entry["registrations"].append(reg)

    print(f"New named entries: {len(additions)}")
    print(f"Merge into existing: {len(merge)}")
    print(f"Person-heuristic hits (ASTV/Bizjets): {person_hits}")
    print()

    by_cat: dict[str, list[tuple[str, list[str]]]] = {}
    for name, info in sorted(additions.items()):
        by_cat.setdefault(info["category"], []).append((name, info["registrations"]))

    for cat in sorted(by_cat):
        items = by_cat[cat]
        print(f"## {cat} ({len(items)})")
        for name, regs in items[:40]:
            print(f"  {name}: {', '.join(regs)}")
        if len(items) > 40:
            print(f"  ... +{len(items)-40} more")
        print()

    out = ROOT / "scripts" / "plane_alert_additions.json"
    out.write_text(
        json.dumps({"additions": additions, "merge": merge}, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
