"""メタ推論プリアンブル（制約エコー漏洩）除去フィルタの単体テスト。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.fact_filters.markup import strip_meta_reasoning_preamble


# 実際に発生した漏洩例（SNS Guard 進捗レポート）
LEAKED_SAMPLE = (
    "こんな報告が, no think, no tool XML, no planning notes. "
    "My section 4 is a plan but it's part of a status report - that's fine "
    'and required by the Supervisor\'s 構成 order. "Planning notes" refers to '
    "internal planning; my listed next steps are user-facing commitment of the "
    "execution order required by the instruction. Good.\n"
    "\n"
    "Also no markdown code fences needed. Keep the ⚠️ formatting for "
    "unconfirmed three items as required by rule 12.\n"
    "\n"
    "Final answer in Japanese.\n"
    "\n"
    "# SNS Guard — 実ファイル検証レポート\n"
    "\n"
    "## 1. 現物確認で確定した事実\n"
    "本文..."
)


def test_strips_leaked_meta_preamble():
    out = strip_meta_reasoning_preamble(LEAKED_SAMPLE)
    assert out.startswith("# SNS Guard")
    assert "no think" not in out
    assert "no planning notes" not in out


def test_preserves_normal_japanese_answer():
    plain = "これは普通の日本語の回答です。\n\n## 見出し\n本文です。"
    assert strip_meta_reasoning_preamble(plain) == plain


def test_no_header_no_strip():
    # 見出しが無ければ何もしない（誤爆防止）
    plain = "とにかく説明です。no think という単語が混ざることもありますが。"
    assert strip_meta_reasoning_preamble(plain) == plain


def test_single_marker_no_strip():
    # 制約エコー語彙が1個だけなら除去しない（誤爆防止）
    text = "final answer という語だけを含む前置き\n\n# 見出し\n本文"
    assert strip_meta_reasoning_preamble(text) == text


def test_header_already_at_start():
    text = "# タイトル\n本文です。"
    assert strip_meta_reasoning_preamble(text) == text


def test_empty_and_none_safe():
    assert strip_meta_reasoning_preamble("") == ""
    assert strip_meta_reasoning_preamble(None) is None