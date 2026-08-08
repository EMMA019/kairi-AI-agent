"""内部マークアップ除去・途切れ検知・スキル判定の単体テスト。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.fact_filters.markup import (
    strip_internal_markup,
    looks_incomplete_output,
    sanitize_preserving_body,
)
from app.core.fact_filters.format import trim_incomplete_trailing_sentence
from app.core.prompt_builder.skill_meta import parse_skill_frontmatter, skill_matches
from app.core.prompt_builder.loader import load_active_skills


def test_strip_incomplete_mcp_call():
    text = (
        "Sources list here\n"
        '<mcp_call tool="get_stock_quote" ticker="^N225"\n\n'
        "それでは本日の市場です。"
    )
    out = strip_internal_markup(text)
    assert "mcp_call" not in out
    assert "本日の市場" in out


def test_strip_orphan_think_close():
    text = "分析します。\n</think>\n\n結論は続伸です。"
    out = strip_internal_markup(text)
    assert "</think>" not in out
    assert "結論は続伸" in out


def test_strip_think_block():
    text = "<think>内部思考</think>\n本文です。"
    out = strip_internal_markup(text)
    assert "内部思考" not in out
    assert "本文です" in out


def test_sanitize_preserving_body_restores():
    text = "有効な本文がここにあります。"

    def wipe(_t):
        return ""

    out = sanitize_preserving_body(text, wipe)
    assert "有効な本文" in out


def test_looks_incomplete_mid_code():
    text = "```python\ndef foo():\n    if len(spread) "
    assert looks_incomplete_output(text)


def test_trim_unclosed_fence_drops_incomplete_line():
    text = "例です。\n```python\ndef foo():\n    if len(spread) "
    result = trim_incomplete_trailing_sentence(text)
    assert "if len(spread)" not in result
    assert result.count("```") % 2 == 0


def test_skill_frontmatter_keywords():
    raw = """---
name: quant-pairs-trading
keywords: ["ペアトレード", "kalman", "バックテスト"]
---

# Body
"""
    meta, body = parse_skill_frontmatter(raw)
    assert meta["name"] == "quant-pairs-trading"
    assert "kalman" in meta["keywords"]
    assert body.startswith("# Body")


def test_skill_matches_quant_not_generic_code():
    assert skill_matches("ペアトレードのコード書いて", "quant-pairs-trading", ["ペアトレード", "kalman"])
    assert not skill_matches("普通のコード書いて", "quant-pairs-trading", ["ペアトレード", "kalman"])


def test_load_active_skills_quant_only():
    text = load_active_skills("日米セクターETFのペアトレードをバックテストしたい")
    assert "quant" in text.lower() or "ペア" in text or "Active Skill" in text
    # 汎用「コード」だけでは frontend が誤発火しないこと（この入力には frontend 語が無い）
    assert "frontend-dev" not in text or "react" not in text.lower()
