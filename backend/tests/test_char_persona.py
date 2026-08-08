"""
char_persona.py 単体テスト
"""
import pytest
from app.core.char_persona import get_char_system_prompt, get_visual_anchor

def test_visual_anchor_default():
    anchor_gal = get_visual_anchor("hyper_gal", "")
    assert "short magenta bob hair" in anchor_gal
    assert "pink eyes" in anchor_gal
    assert "gyaru style" in anchor_gal

    anchor_kansai = get_visual_anchor("kairi_kansai", "")
    assert "short magenta bob hair" in anchor_kansai
    assert "pink eyes" in anchor_kansai
    assert "friendly smile" in anchor_kansai

def test_char_system_prompt_generation():
    # Default locale is English for public builds
    prompt = get_char_system_prompt("Nao", "", "hyper_gal")
    assert "upbeat energetic companion" in prompt
    assert "Prefer **English**" in prompt
    assert "メッセージアプリのチャット返信（セリフのみ）" in prompt
    assert "地の文（状況説明・描写テキスト）を絶対に書かないでください。" in prompt
    assert "/api/image/generate?prompt=" in prompt
    assert "visual_anchor" not in prompt
    assert "short magenta bob hair" in prompt
    assert "gyaru style" in prompt

    prompt_ja = get_char_system_prompt("Nao", "", "hyper_gal", locale="ja")
    assert "平成ギャル相棒「Kairi」です" in prompt_ja

def test_char_system_prompt_custom_profile():
    custom = "あなたは魔法使いの弟子です。"
    prompt = get_char_system_prompt("Nao", custom, "standard")
    assert "あなたは魔法使いの弟子です。" in prompt
    assert "メッセージアプリのチャット返信（セリフのみ）" in prompt
