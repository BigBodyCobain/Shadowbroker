"""Auto-translation for Telegram OSINT post text (server-side, cached)."""
from __future__ import annotations

import hashlib
import logging
import os
import re
import urllib.parse
from threading import Lock
from typing import Any

import requests

logger = logging.getLogger(__name__)

_CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")
_UKRAINIAN_MARKERS_RE = re.compile(r"[іїєґІЇЄҐ]")
_ARABIC_RE = re.compile(r"[\u0600-\u06FF]")
_HEBREW_RE = re.compile(r"[\u0590-\u05FF]")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")

# Common war-reporting shorthand that machine translation often transliterates.
_POST_TRANSLATION_GLOSSARY: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bBpLa\b", re.IGNORECASE), "UAV"),
    (re.compile(r"\bБпЛА\b", re.IGNORECASE), "UAV"),
    (re.compile(r"\bбпла\b"), "UAV"),
    (re.compile(r"\bБПЛА\b"), "UAV"),
    (re.compile(r"\bрсзв\b", re.IGNORECASE), "MLRS"),
    (re.compile(r"\bРСЗВ\b"), "MLRS"),
)

_SOURCE_LANG_LABELS = {
    "uk": "Ukrainian",
    "ru": "Russian",
    "en": "English",
    "ar": "Arabic",
    "he": "Hebrew",
    "zh-cn": "Chinese",
    "fr": "French",
    "de": "German",
    "pl": "Polish",
}

_CACHE: dict[str, tuple[str, str]] = {}
_CACHE_LOCK = Lock()
_CACHE_MAX = 512

_LOCALE_TO_GOOGLE = {
    "en": "en",
    "fr": "fr",
    "zh-cn": "zh-CN",
    "zh": "zh-CN",
}


def telegram_translate_enabled() -> bool:
    return str(os.environ.get("TELEGRAM_OSINT_TRANSLATE", "true")).strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
        "",
    }


def telegram_translate_target() -> str:
    raw = str(os.environ.get("TELEGRAM_OSINT_TRANSLATE_TO", "en")).strip().lower()
    return _LOCALE_TO_GOOGLE.get(raw, raw or "en")


def normalize_translate_target(locale: str | None) -> str:
    raw = str(locale or telegram_translate_target()).strip().lower().replace("_", "-")
    return _LOCALE_TO_GOOGLE.get(raw, raw or "en")


def _looks_english(text: str) -> bool:
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return True
    ascii_letters = sum(1 for char in letters if ord(char) < 128)
    return ascii_letters / len(letters) > 0.9


def contains_cyrillic(text: str) -> bool:
    return bool(_CYRILLIC_RE.search(str(text or "")))


def source_lang_label(code: str | None) -> str:
    raw = str(code or "").strip().lower().replace("_", "-")
    return _SOURCE_LANG_LABELS.get(raw, raw.upper() if raw else "Unknown")


def polish_translation(text: str) -> str:
    polished = str(text or "")
    for pattern, replacement in _POST_TRANSLATION_GLOSSARY:
        polished = pattern.sub(replacement, polished)
    return polished.strip()


def guess_source_lang(text: str) -> str:
    if _UKRAINIAN_MARKERS_RE.search(text):
        return "uk"
    if _CYRILLIC_RE.search(text):
        return "ru"
    if _ARABIC_RE.search(text):
        return "ar"
    if _HEBREW_RE.search(text):
        return "he"
    if _CJK_RE.search(text):
        return "zh-CN"
    if _looks_english(text):
        return "en"
    return "auto"


def _cache_key(text: str, target_lang: str) -> str:
    digest = hashlib.sha1(f"{target_lang}|{text}".encode("utf-8")).hexdigest()
    return digest


def _cache_get(text: str, target_lang: str) -> tuple[str, str] | None:
    key = _cache_key(text, target_lang)
    with _CACHE_LOCK:
        return _CACHE.get(key)


def _cache_put(text: str, target_lang: str, translated: str, source_lang: str) -> None:
    key = _cache_key(text, target_lang)
    with _CACHE_LOCK:
        if len(_CACHE) >= _CACHE_MAX:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[key] = (translated, source_lang)


def _google_translate(clean: str, target: str, source: str | None = None) -> tuple[str, str]:
    params = {
        "client": "gtx",
        "sl": source or "auto",
        "tl": target,
        "dt": "t",
        "q": clean[:4500],
    }
    url = "https://translate.googleapis.com/translate_a/single?" + urllib.parse.urlencode(params)
    resp = requests.get(
        url,
        timeout=8,
        headers={"User-Agent": "Mozilla/5.0 (compatible; Shadowbroker-Telegram-Translate/1.0)"},
    )
    resp.raise_for_status()
    data = resp.json()
    detected = str(data[2] or guess_source_lang(clean)).strip().lower()
    if detected in {"zh-cn", "zh-tw"}:
        detected = "zh-CN"
    parts: list[str] = []
    for chunk in data[0] or []:
        if chunk and chunk[0]:
            parts.append(str(chunk[0]))
    translated = polish_translation("".join(parts).strip() or clean)
    return translated, detected


def translate_text(text: str, target_lang: str | None = None) -> tuple[str, str]:
    """Translate text via Google Translate (unofficial client endpoint).

    Returns ``(translated_text, detected_source_lang)``.
    """
    clean = str(text or "").strip()
    if not clean:
        return "", "en"

    target = normalize_translate_target(target_lang)
    if _looks_english(clean) and target == "en":
        return clean, "en"

    cached = _cache_get(clean, target)
    if cached:
        return cached

    try:
        translated, detected = _google_translate(clean, target)
        if detected == target or (detected == "en" and target == "en"):
            result = (clean, detected)
            _cache_put(clean, target, clean, detected)
            return result
        if contains_cyrillic(translated) and contains_cyrillic(clean):
            hinted = guess_source_lang(clean)
            if hinted not in {"auto", target}:
                retry_translated, retry_detected = _google_translate(clean, target, hinted)
                if not contains_cyrillic(retry_translated) or len(retry_translated) > len(translated):
                    translated, detected = retry_translated, retry_detected
        result = (translated, detected)
        _cache_put(clean, target, translated, detected)
        return result
    except Exception as exc:
        logger.warning("Telegram translation failed: %s", exc)
        fallback_lang = guess_source_lang(clean)
        return clean, fallback_lang


def apply_post_translation(post: dict[str, Any], target_lang: str | None = None) -> dict[str, Any]:
    """Add translation fields to a Telegram OSINT post dict."""
    if not telegram_translate_enabled():
        return post

    target = normalize_translate_target(target_lang)
    description = str(post.get("description") or "").strip()
    title = str(post.get("title") or "").strip()
    full_text = description or title
    if not full_text:
        return post

    existing_translated = str(post.get("description_translated") or post.get("title_translated") or "").strip()
    if post.get("translate_to") == target and existing_translated:
        updated = dict(post)
        polished = polish_translation(existing_translated)
        if polished != existing_translated:
            lines = polished.split("\n", 1)
            updated["title_translated"] = lines[0][:160]
            updated["description_translated"] = polished[:1200]
        updated["source_lang_label"] = source_lang_label(str(post.get("source_lang") or ""))
        return updated

    translated_full, source_lang = translate_text(full_text, target)
    updated = dict(post)
    updated["source_lang"] = source_lang
    updated["translate_to"] = target
    updated["source_lang_label"] = source_lang_label(source_lang)

    if translated_full != full_text and source_lang != target:
        lines = translated_full.split("\n", 1)
        updated["title_translated"] = lines[0][:160]
        updated["description_translated"] = translated_full[:1200]

    return updated


def apply_posts_translations(
    posts: list[dict[str, Any]],
    target_lang: str | None = None,
) -> list[dict[str, Any]]:
    if not telegram_translate_enabled():
        return posts
    return [apply_post_translation(post, target_lang) for post in posts]