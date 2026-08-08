"""文末完全性トリマー / ツール予告除去 / 検索引き継ぎの単体テスト。"""
import sys
from pathlib import Path

# backend/ をパスに追加
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.fact_filters.format import (
    trim_incomplete_trailing_sentence,
    strip_dangling_tool_promises,
    _ends_with_valid_terminal,
)


def test_complete_sentence_unchanged():
    text = "ダウは堅調でした。"
    assert trim_incomplete_trailing_sentence(text) == text


def test_exclamation_and_question_ok():
    assert trim_incomplete_trailing_sentence("すごい！") == "すごい！"
    assert trim_incomplete_trailing_sentence("どう思う？") == "どう思う？"


def test_truncated_trailing_char_trimmed():
    text = "承知しました。現在は週末です。まずデータを取得します。\n\n承"
    result = trim_incomplete_trailing_sentence(text)
    assert not result.endswith("承")
    assert "承知しました" in result
    assert result.rstrip().endswith(("。", "！", "？", "!", "?")) or "取得します。" in result or result.endswith("。")


def test_truncated_mid_sentence():
    text = "カルパナはディープインパクトの孫にあたる血統ですね。\n\nい"
    result = trim_incomplete_trailing_sentence(text)
    assert result.endswith("ね。") or result.endswith("ですね。")
    assert not result.endswith("い")


def test_code_block_unclosed_trims_incomplete_line():
    text = "例です。\n```python\ndef foo():\n    retur"
    result = trim_incomplete_trailing_sentence(text)
    assert "retur" not in result
    assert "```python" in result
    assert result.count("```") % 2 == 0


def test_bullet_list_protected():
    text = "ポイント:\n- ダウは上昇\n- ナスダックは下"
    result = trim_incomplete_trailing_sentence(text)
    # 箇条書き末行は保護
    assert "ナスダックは下" in result


def test_table_row_protected():
    text = "表:\n| 指数 | 方向 |\n| S&P | 横ば"
    result = trim_incomplete_trailing_sentence(text)
    assert "| S&P" in result or "横ば" in result


def test_safety_valve_50_percent():
    # 終端が無く、切り戻しで大半が消えるケースは適用しない
    text = "あいうえお"
    result = trim_incomplete_trailing_sentence(text)
    assert result == text


def test_strip_dangling_tool_promise():
    text = (
        "承知しました。現在は週末で米国市場は休場です。\n\n"
        "まず、残りの主要指数データを取得します。"
    )
    result = strip_dangling_tool_promises(text)
    assert "取得します" not in result
    assert "休場です" in result


def test_strip_dangling_keeps_normal_ending():
    text = "主要指数は以下の通りです。\n\nダウは上昇しました。"
    assert strip_dangling_tool_promises(text) == text


def test_ends_with_valid_terminal():
    assert _ends_with_valid_terminal("完了。") is True
    assert _ends_with_valid_terminal("完了") is False
    assert _ends_with_valid_terminal("OK!") is True
    assert _ends_with_valid_terminal("```") is True


def test_carryover_overlap_logic():
    """同一トピック判定: user_input のみ・閾値2。history 自己一致では発火しない。"""
    from app.routers.chat import (
        _store_search_carryover,
        _maybe_carry_search_results,
        _last_search_by_session,
    )

    sid = "test-session-carry-1"
    _last_search_by_session.pop(sid, None)

    _store_search_carryover(
        sid,
        "カルパナはキングジョージを制覇。騎手は別の騎手。オッズは11.8倍。",
        ["Kalpana King George 2026"],
        "カルパナに賭けて大当たりだった",
    )

    # 現発話に旧トピック語が2語以上 → 再注入
    carried = _maybe_carry_search_results(
        sid,
        "カルパナの大当たりのオッズって結局いくらだった？",
        [{"role": "user", "content": "カルパナに賭けて大当たりだった"},
         {"role": "assistant", "content": "カルパナの好配当でしたね"}],
        search_needed=False,
        search_results_text=None,
    )
    assert carried is not None
    assert "カルパナ" in carried

    # history に旧トピックがあっても、現発話に共有語がなければキャリーしない
    history_only = _maybe_carry_search_results(
        sid,
        "介入するかな？ってかしてるのかな？",
        [
            {"role": "user", "content": "半導体の規制どう？"},
            {"role": "assistant", "content": "カルパナも話題でした"},
        ],
        search_needed=False,
        search_results_text=None,
    )
    assert history_only is None

    # 全く無関係な話題 → 再注入されない
    unrelated = _maybe_carry_search_results(
        sid,
        "今日の天気どう？",
        [{"role": "user", "content": "こんにちは"}],
        search_needed=False,
        search_results_text=None,
    )
    assert unrelated is None

    _last_search_by_session.pop(sid, None)


import asyncio


def test_compression_detect_error_importable():
    """compression.py が _detect_error を正しく import できること。"""
    from app.core.auto_execution_loop.compression import _smart_compress_loop_history

    history = [
        {"role": "assistant", "content": "step1"},
        {"role": "user", "content": "Error: something failed\ntraceback"},
        {"role": "assistant", "content": "step2"},
        {"role": "user", "content": "ok"},
        {"role": "assistant", "content": "step3"},
        {"role": "user", "content": "ok2"},
        {"role": "assistant", "content": "step4"},
        {"role": "user", "content": "latest"},
    ]
    # 7件超で圧縮パスに入り、NameError にならないこと
    result = asyncio.run(_smart_compress_loop_history(history))
    assert isinstance(result, list)


def test_httpexception_importable_from_chat():
    from app.routers import chat as chat_mod
    assert hasattr(chat_mod, "HTTPException")
    assert chat_mod.HTTPException is not None
