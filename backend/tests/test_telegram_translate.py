"""Telegram OSINT auto-translation."""

from services import telegram_translate


def test_guess_source_lang_detects_cyrillic():
    assert telegram_translate.guess_source_lang("В Крым поедем несмотря ни на что") == "ru"


def test_apply_post_translation_skips_english(monkeypatch):
    monkeypatch.setattr(telegram_translate, "telegram_translate_enabled", lambda: True)
    post = {
        "title": "Missile strike reported near Kyiv overnight.",
        "description": "Missile strike reported near Kyiv overnight.",
    }
    enriched = telegram_translate.apply_post_translation(post, "en")
    assert enriched["source_lang"] == "en"
    assert "title_translated" not in enriched


def test_apply_post_translation_adds_fields(monkeypatch):
    monkeypatch.setattr(telegram_translate, "telegram_translate_enabled", lambda: True)
    monkeypatch.setattr(
        telegram_translate,
        "translate_text",
        lambda text, target_lang=None: (
            "We will go to Crimea no matter what. This is our homeland!",
            "ru",
        ),
    )
    post = {
        "title": "«В Крым поедем несмотря ни на что. Это наша родина!»",
        "description": "«В Крым поедем несмотря ни на что. Это наша родина!»",
    }
    enriched = telegram_translate.apply_post_translation(post, "en")
    assert enriched["source_lang"] == "ru"
    assert enriched["translate_to"] == "en"
    assert "Crimea" in enriched["title_translated"]


def test_normalize_translate_target_maps_ui_locales():
    assert telegram_translate.normalize_translate_target("zh-CN") == "zh-CN"
    assert telegram_translate.normalize_translate_target("fr") == "fr"


def test_source_lang_label_avoids_uk_country_confusion():
    assert telegram_translate.source_lang_label("uk") == "Ukrainian"
    assert telegram_translate.source_lang_label("ru") == "Russian"


def test_polish_translation_expands_bpla_shorthand():
    assert "UAV" in telegram_translate.polish_translation("Kyiv 1x BpLa on Rembazu.")


def test_guess_source_lang_prefers_ukrainian_markers():
    assert telegram_translate.guess_source_lang("Київ 1х БпЛА") == "uk"