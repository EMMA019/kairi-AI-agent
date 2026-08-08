"""completion_status / 空洞完了判定の単体テスト。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.completion_status import (
    is_aborted_short_market_reply,
    is_hollow_completion,
    response_ok,
    wants_code_in_chat,
    build_done_payload,
)


def test_wants_code_in_chat():
    assert wants_code_in_chat("フルコードだけ書いて")
    assert wants_code_in_chat("Approved. Please implement.")
    assert not wants_code_in_chat("今日の天気は？")


def test_hollow_file_created_meta_only():
    text = (
        "ファイル作成完了。実行・検証はユーザー指示範囲外のためスキップ。\n"
        "# pairs_trading_v3.py 作成済み"
    )
    assert is_hollow_completion(text, "フルコードだけ書いて")
    assert not response_ok(text, "フルコードだけ書いて")


def test_real_code_not_hollow():
    text = (
        "保存先: pairs_trading_v3.py\n\n"
        "改善点は look-ahead 除去です。\n\n"
        "```python\n"
        + ("import numpy as np\n" * 20)
        + "def main():\n    print(1)\n"
        + "```\n"
    )
    assert not is_hollow_completion(text, "実装して")
    assert response_ok(text, "実装して")


def test_empty_not_ok():
    assert not response_ok("", "hello")
    payload = build_done_payload("", "hello")
    assert payload["ok"] is False
    assert payload["type"] == "done"


def test_failure_fallback_not_ok():
    text = "*(⚠️ 応答の生成に失敗しました。もう一度お試しください)*"
    assert not response_ok(text)


def test_aborted_short_market_reply():
    assert is_aborted_short_market_reply("か", "日本市場どうだった？")
    assert not response_ok("か", "日本市場どうだった？")
    assert not is_aborted_short_market_reply("か", "今日の天気は？")
    long_ok = "前場は下落で終えました。" * 3
    assert not is_aborted_short_market_reply(long_ok, "日本市場どうだった？")
    assert response_ok(long_ok, "日本市場どうだった？")
