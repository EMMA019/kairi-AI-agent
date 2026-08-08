"""Fast Apply（Morph方式マージレイヤー）の単体テスト。"""
import asyncio
import sys
from pathlib import Path

# backend/ をパスに追加
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import fast_apply
from app.core.fast_apply import (
    apply_edit,
    has_lazy_markers,
    validate_merge,
    MAX_ORIGINAL_CHARS,
)


ORIGINAL = """def divide(a, b):
    return a / b


def multiply(a, b):
    return a * b
"""

SNIPPET = """def divide(a, b):
    if b == 0:
        raise ValueError("division by zero")
    return a / b
# ... existing code ...
"""

MERGED_GOOD = """def divide(a, b):
    if b == 0:
        raise ValueError("division by zero")
    return a / b


def multiply(a, b):
    return a * b
"""


# --- マーカー検出 ---

def test_marker_detection_variants():
    assert has_lazy_markers("// ... existing code ...")
    assert has_lazy_markers("# ... existing code ...")
    assert has_lazy_markers("  /* ... existing code ... */")
    assert has_lazy_markers("<!-- ... existing code ... -->")
    assert has_lazy_markers("# ... 既存コード ...")
    assert has_lazy_markers("... existing code ...")


def test_marker_detection_negative():
    assert not has_lazy_markers("x = 1  # normal comment")
    assert not has_lazy_markers("print('... existing code ...')")


# --- マージ検証 ---

def test_validate_merge_success():
    ok, reason = validate_merge(ORIGINAL, SNIPPET, MERGED_GOOD)
    assert ok, reason


def test_validate_merge_rejects_leftover_marker():
    bad = MERGED_GOOD + "\n# ... existing code ...\n"
    ok, reason = validate_merge(ORIGINAL, SNIPPET, bad)
    assert not ok
    assert "マーカー" in reason


def test_validate_merge_rejects_missing_snippet_lines():
    # スニペットの変更内容が全く反映されていない（元ファイルそのまま）
    ok, reason = validate_merge(ORIGINAL, SNIPPET, ORIGINAL)
    assert not ok
    assert "反映率" in reason


def test_validate_merge_rejects_code_loss():
    # 部分編集なのに multiply が丸ごと消えている
    collapsed = """def divide(a, b):
    if b == 0:
        raise ValueError("division by zero")
    return a / b
"""
    original_long = ORIGINAL + "\n\ndef extra_1():\n    pass\n\n\ndef extra_2():\n    pass\n\n\ndef extra_3():\n    pass\n"
    ok, reason = validate_merge(original_long, SNIPPET, collapsed)
    assert not ok
    assert "短く" in reason


def test_validate_merge_rejects_empty():
    ok, _ = validate_merge(ORIGINAL, SNIPPET, "   \n")
    assert not ok


# --- apply_edit（LLM呼び出しをモック） ---

def test_apply_edit_strips_think_and_fences(monkeypatch):
    async def fake_call_model(**kwargs):
        return f"<think>\nマージ手順を考える\n</think>\n```python\n{MERGED_GOOD}```"

    monkeypatch.setattr(fast_apply, "call_model", fake_call_model)
    ok, merged = asyncio.run(apply_edit(ORIGINAL, SNIPPET, "add zero check"))
    assert ok, merged
    assert "<think>" not in merged
    assert "```" not in merged
    assert 'raise ValueError("division by zero")' in merged
    assert "def multiply(a, b):" in merged
    assert merged.endswith("\n")


def test_apply_edit_fails_closed_on_bad_merge(monkeypatch):
    async def fake_call_model(**kwargs):
        return "ごめん、マージできませんでした！"

    monkeypatch.setattr(fast_apply, "call_model", fake_call_model)
    ok, reason = asyncio.run(apply_edit(ORIGINAL, SNIPPET))
    assert not ok


def test_apply_edit_rejects_oversized_file():
    big_original = "x = 1\n" * (MAX_ORIGINAL_CHARS // 6 + 100)
    ok, reason = asyncio.run(apply_edit(big_original, SNIPPET))
    assert not ok
    assert "大きすぎます" in reason


def test_apply_edit_handles_llm_exception(monkeypatch):
    async def fake_call_model(**kwargs):
        raise RuntimeError("API down")

    monkeypatch.setattr(fast_apply, "call_model", fake_call_model)
    ok, reason = asyncio.run(apply_edit(ORIGINAL, SNIPPET))
    assert not ok
    assert "API down" in reason


# --- ハンドラ側の <edit> タグパース ---

def test_edit_tag_regex_parses_with_and_without_instruction():
    import re
    edit_pattern = re.compile(
        r'<edit\s+path=(["\'])(?P<path>.*?)\1'
        r'(?:\s+instruction=(["\'])(?P<instruction>.*?)\3)?\s*>'
        r'\n?(?P<snippet>[\s\S]*?)<\/edit>'
    )
    text_with = '<edit path="src/app.py" instruction="add logging">\nimport logging\n# ... existing code ...\n</edit>'
    m = edit_pattern.search(text_with)
    assert m and m.group("path") == "src/app.py"
    assert m.group("instruction") == "add logging"
    assert "import logging" in m.group("snippet")

    text_without = "<edit path='src/app.py'>\nimport logging\n</edit>"
    m2 = edit_pattern.search(text_without)
    assert m2 and m2.group("path") == "src/app.py"
    assert m2.group("instruction") is None
