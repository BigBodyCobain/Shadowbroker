"""EUvsDisinfo FIMI (Foreign Information Manipulation & Interference) fetcher.

Parses the EUvsDisinfo RSS feed to extract disinformation narratives,
debunked claims, threat actor mentions, and target country references.
Refreshes every 12 hours (FIMI data updates weekly).
"""

import re
import logging
from datetime import datetime, timezone

import feedparser
from services.network_utils import fetch_with_curl
from services.fetchers._store import latest_data, _data_lock, _mark_fresh
from services.fetchers.retry import with_retry

logger = logging.getLogger("services.data_fetcher")

_FIMI_FEED_URL = "https://euvsdisinfo.eu/feed/"

# ── Threat actor keywords ──────────────────────────────────────────────────
# Map of keyword → canonical actor name.  Checked case-insensitively.
_THREAT_ACTORS: dict[str, str] = {
    "russia":       "Russia",
    "russian":      "Russia",
    "kremlin":      "Russia",
    "pro-kremlin":  "Russia",
    "moscow":       "Russia",
    "china":        "China",
    "chinese":      "China",
    "beijing":      "China",
    "iran":         "Iran",
    "iranian":      "Iran",
    "tehran":       "Iran",
    "north korea":  "North Korea",
    "pyongyang":    "North Korea",
    "dprk":         "North Korea",
    "belarus":      "Belarus",
    "belarusian":   "Belarus",
    "minsk":        "Belarus",
}

# ── Target country/region keywords ─────────────────────────────────────────
_TARGET_KEYWORDS: dict[str, str] = {
    "ukraine":      "Ukraine",
    "kyiv":         "Ukraine",
    "moldova":      "Moldova",
    "georgia":      "Georgia",
    "tbilisi":      "Georgia",
    "eu":           "EU",
    "european union": "EU",
    "europe":       "Europe",
    "nato":         "NATO",
    "united states": "United States",
    "usa":          "United States",
    "germany":      "Germany",
    "france":       "France",
    "poland":       "Poland",
    "baltic":       "Baltics",
    "lithuania":    "Baltics",
    "latvia":       "Baltics",
    "estonia":      "Baltics",
    "romania":      "Romania",
    "czech":        "Czech Republic",
    "slovakia":     "Slovakia",
    "armenia":      "Armenia",
    "africa":       "Africa",
    "middle east":  "Middle East",
    "syria":        "Syria",
    "israel":       "Israel",
    "serbia":       "Serbia",
    "india":        "India",
    "brazil":       "Brazil",
}

# ── Disinformation topic keywords (for cross-referencing news) ─────────────
_DISINFO_TOPICS = [
    "sanctions",
    "energy crisis",
    "gas supply",
    "nuclear threat",
    "nato expansion",
    "biolab",
    "biological weapon",
    "provocation",
    "false flag",
    "staged",
    "nazi",
    "genocide",
    "referendum",
    "regime change",
    "coup",
    "puppet government",
    "election interference",
    "election meddling",
    "voter fraud",
    "migrant invasion",
    "refugee crisis",
    "civil war",
    "food crisis",
    "grain deal",
]

# Regex for extracting debunked report URLs from feed HTML
_REPORT_URL_RE = re.compile(
    r'https?://euvsdisinfo\.eu/report/[a-z0-9\-]+/?',
    re.IGNORECASE,
)

# Regex for extracting the claim title from a report URL slug
_SLUG_RE = re.compile(r'/report/([a-z0-9\-]+)/?$', re.IGNORECASE)


def _slug_to_title(url: str) -> str:
    """Convert a report URL slug to a human-readable title."""
    m = _SLUG_RE.search(url)
    if not m:
        return url
    return m.group(1).replace("-", " ").title()


def _count_mentions(text: str, keywords: dict[str, str]) -> dict[str, int]:
    """Count keyword mentions, mapping to canonical names."""
    counts: dict[str, int] = {}
    text_lower = text.lower()
    for kw, canonical in keywords.items():
        # Word-boundary match, case-insensitive
        pattern = r'\b' + re.escape(kw) + r'\b'
        matches = re.findall(pattern, text_lower)
        if matches:
            counts[canonical] = counts.get(canonical, 0) + len(matches)
    return counts


def _extract_disinfo_keywords(text: str) -> list[str]:
    """Return which disinformation topic keywords appear in the text."""
    text_lower = text.lower()
    found = []
    for topic in _DISINFO_TOPICS:
        if topic in text_lower:
            found.append(topic)
    return found


def _is_major_wave(narratives: list[dict], targets: dict[str, int]) -> bool:
    """Heuristic: detect a 'major disinformation wave'.

    Triggers when:
    - 3+ narratives in the feed mention the same target, OR
    - A single target has 10+ total mentions across all narratives, OR
    - 5+ distinct debunked claims extracted in one fetch
    """
    if not narratives:
        return False

    # Check per-target narrative count
    target_narrative_counts: dict[str, int] = {}
    total_claims = 0
    for n in narratives:
        for t in n.get("targets", []):
            target_narrative_counts[t] = target_narrative_counts.get(t, 0) + 1
        total_claims += len(n.get("claims", []))

    if any(c >= 3 for c in target_narrative_counts.values()):
        return True
    if any(c >= 10 for c in targets.values()):
        return True
    if total_claims >= 5:
        return True
    return False


@with_retry(max_retries=1, base_delay=5)
def fetch_fimi():
    """Fetch and parse the EUvsDisinfo RSS feed."""
    try:
        resp = fetch_with_curl(_FIMI_FEED_URL, timeout=15)
        feed = feedparser.parse(resp.text)
    except Exception as e:
        logger.warning(f"FIMI feed fetch failed: {e}")
        return

    if not feed.entries:
        logger.warning("FIMI feed: no entries found")
        return

    narratives = []
    all_claims: list[dict] = []
    agg_actors: dict[str, int] = {}
    agg_targets: dict[str, int] = {}
    all_disinfo_kw: set[str] = set()

    for entry in feed.entries[:15]:  # Cap at 15 entries
        title = entry.get("title", "")
        link = entry.get("link", "")
        published = entry.get("published", "")
        summary_html = entry.get("summary", "") or entry.get("description", "")

        # Strip HTML tags for text analysis
        summary_text = re.sub(r"<[^>]+>", " ", summary_html)
        summary_text = re.sub(r"\s+", " ", summary_text).strip()
        full_text = f"{title} {summary_text}"

        # Extract debunked report URLs
        report_urls = list(set(_REPORT_URL_RE.findall(summary_html)))
        claims = [{"url": url, "title": _slug_to_title(url)} for url in report_urls]
        all_claims.extend(claims)

        # Count threat actors
        actors = _count_mentions(full_text, _THREAT_ACTORS)
        for actor, count in actors.items():
            agg_actors[actor] = agg_actors.get(actor, 0) + count

        # Count target countries
        targets = _count_mentions(full_text, _TARGET_KEYWORDS)
        for target, count in targets.items():
            agg_targets[target] = agg_targets.get(target, 0) + count

        # Extract disinfo topic keywords
        disinfo_kw = _extract_disinfo_keywords(full_text)
        all_disinfo_kw.update(disinfo_kw)

        # Truncate summary for storage
        snippet = summary_text[:300] + ("..." if len(summary_text) > 300 else "")

        narratives.append({
            "title": title,
            "link": link,
            "published": published,
            "snippet": snippet,
            "claims": claims,
            "actors": list(actors.keys()),
            "targets": list(targets.keys()),
            "disinfo_keywords": disinfo_kw,
        })

    # Sort actors and targets by count (descending)
    sorted_actors = dict(sorted(agg_actors.items(), key=lambda x: x[1], reverse=True))
    sorted_targets = dict(sorted(agg_targets.items(), key=lambda x: x[1], reverse=True))

    # Deduplicate claims
    seen_urls: set[str] = set()
    unique_claims = []
    for c in all_claims:
        if c["url"] not in seen_urls:
            seen_urls.add(c["url"])
            unique_claims.append(c)

    major_wave = _is_major_wave(narratives, sorted_targets)

    fimi_data = {
        "narratives": narratives,
        "claims": unique_claims,
        "threat_actors": sorted_actors,
        "targets": sorted_targets,
        "disinfo_keywords": sorted(all_disinfo_kw),
        "major_wave": major_wave,
        "major_wave_target": (
            max(sorted_targets, key=sorted_targets.get) if major_wave and sorted_targets else None
        ),
        "last_fetched": datetime.now(timezone.utc).isoformat(),
        "source": "EUvsDisinfo",
        "source_url": "https://euvsdisinfo.eu",
    }

    with _data_lock:
        latest_data["fimi"] = fimi_data
    _mark_fresh("fimi")
    logger.info(
        f"FIMI fetch complete: {len(narratives)} narratives, "
        f"{len(unique_claims)} claims, "
        f"{len(sorted_actors)} actors, "
        f"major_wave={major_wave}"
    )
