"""locale → reply-language wiring (hello must not force Japanese when locale=en)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.reply_language import (
    build_gal_persona_instruction,
    build_greeting_system_prompt,
    build_reply_language_instruction,
    looks_clearly_japanese,
    normalize_locale,
)
from app.core.supervisor import get_supervisor_system_prompt


def test_normalize_locale():
    assert normalize_locale("en") == "en"
    assert normalize_locale("ja-JP") == "ja"
    assert normalize_locale(None) == "en"


def test_looks_clearly_japanese():
    assert looks_clearly_japanese("7/31米国市場どうだった？") is True
    assert looks_clearly_japanese("hello") is False
    assert looks_clearly_japanese("OK") is False


def test_reply_language_en_mentions_hello_and_english():
    text = build_reply_language_instruction("en")
    assert "Prefer **English**" in text
    assert "hello" in text.lower()
    assert "Japanese" in text


def test_reply_language_ja_prefers_japanese():
    text = build_reply_language_instruction("ja")
    assert "Japanese" in text
    assert "ask for English" in text or "Prefer" in text


def test_gal_persona_en_not_heisei_gyaru_lexicon():
    en = build_gal_persona_instruction("en")
    assert "English" in en
    assert "チョベリグ" not in en
    ja = build_gal_persona_instruction("ja")
    assert "ギャル" in ja


def test_greeting_en_hello_path():
    g = build_greeting_system_prompt("gal", "en")
    assert "English" in g
    assert "ギャル言葉" not in g
    g_ja = build_greeting_system_prompt("gal", "ja")
    assert "ギャル" in g_ja


def test_build_system_instruction_includes_en_reply_lang():
    from app.core.prompt_builder.builder import build_system_instruction

    fake = {
        "user_name": "you",
        "user_location": "",
        "persona_style": "standard",
        "locale": "en",
    }

    class _S:
        def get(self):
            return fake

    with patch("app.routers.settings.app_settings", _S()):
        _static, dynamic, persona = build_system_instruction(
            user_input="hello",
            mode="chat",
            mood={},
            filtered_kv_text="",
            followup_cooldown=False,
        )
    blob = persona + "\n" + dynamic
    assert "Prefer **English**" in blob
    assert "hello" in blob.lower()


def test_supervisor_prompt_no_unconditional_jp_translate():
    text = get_supervisor_system_prompt("general")
    assert "勝手に忖度して検索結果を捨てない" in text or "検索結果を捨てない" in text
    # Old hard rule removed
    assert "それを日本語に翻訳・要約して提示してください" not in text
    assert "Reply language" in text or "応答言語" in text
