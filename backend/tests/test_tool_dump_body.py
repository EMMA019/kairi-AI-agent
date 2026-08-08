"""ツール生ダンプがチャット本文に漏れないことの回帰テスト。"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.fact_filters.markup import looks_like_tool_dump, strip_tool_dump_blocks


SAMPLE_DUMP = """[Local Tool: get_stock_quote]
{
"ticker": "GOOGL",
"current_price": 356.1300048828125,
"change_pct": 6.73440057965654
}

【一般検索結果: Alphabet stock July 31 2026 why up】
【引用契約】以下の各ソースには番号 [n] が付いています。時事的な事実には [n] を付与してください。

[1] [tavily [Tier 3: 三次情報 (一般Web記事・要検証)]] Alphabet Moved Up on Jul 31
URL: https://example.com/googl
↗
"""


def test_looks_like_tool_dump_detects_local_and_search():
    assert looks_like_tool_dump(SAMPLE_DUMP)
    assert looks_like_tool_dump("[MCP Tool: foo->bar]\nresult")
    assert looks_like_tool_dump("前文\n【システムからのツール実行結果】\n後")
    assert not looks_like_tool_dump("GOOGLは前日比で約6.7%上昇しました。")


def test_strip_tool_dump_blocks_removes_tavily_and_local():
    prose = "これは本文です。市場は上昇しました。"
    cleaned = strip_tool_dump_blocks(prose + "\n\n" + SAMPLE_DUMP)
    assert "Local Tool" not in cleaned
    assert "一般検索結果" not in cleaned
    assert "引用契約" not in cleaned
    assert "tavily" not in cleaned.lower()
    assert "これは本文です" in cleaned


def test_duplicate_tool_shutdown_synthesizes_without_dump():
    """同じ get_stock_quote が2回来たら生ダンプではなく合成文を返す。"""
    from app.core.auto_execution_loop.loop import auto_execute_with_retry

    call_n = {"n": 0}
    synth_calls = {"n": 0}

    def fake_executor(**kwargs):
        call_n["n"] += 1
        user = kwargs.get("user_input") or ""
        sys_i = kwargs.get("system_instruction") or ""

        if (
            "自然な文章" in user
            or "ツール生ログ" in user
            or "最終的な回答のみ" in sys_i
            or "ツール生ログは一切出力" in sys_i
        ):
            synth_calls["n"] += 1
            text = (
                "<<<FINAL_ANSWER>>>\n"
                "GOOGLは前日比で上昇しました。決算後の反発とみられます。"
            )
        else:
            text = '<mcp_call tool="get_stock_quote" ticker="GOOGL" />\n'

        async def _gen():
            yield text

        return _gen()

    class FakeHandler:
        def __init__(self, **kwargs):
            self.tool_results: list[str] = []
            self.has_escalation = False
            self.escalation_history: list = []

        async def execute_tools(self, current_response: str):
            self.tool_results = [
                '[Local Tool: get_stock_quote]\n{\n"ticker": "GOOGL",\n"current_price": 356.13\n}',
                "【一般検索結果: Alphabet stock】\n【引用契約】test\n"
                "[1] [tavily [Tier 3: 三次情報]] Article\nURL: https://example.com\n",
            ]
            return current_response, []

    async def fake_compress(history):
        return history

    async def _run():
        with (
            patch("app.core.auto_execution_loop.loop.run_executor", side_effect=fake_executor),
            patch("app.core.auto_execution_loop.loop.ToolHandler", FakeHandler),
            patch(
                "app.core.auto_execution_loop.loop._smart_compress_loop_history",
                side_effect=fake_compress,
            ),
            patch(
                "app.core.fact_filters.pipeline.apply_grounding_pipeline",
                side_effect=lambda t, *_a, **_k: t,
            ),
        ):
            return await auto_execute_with_retry(
                user_input="Googleなにかいいニュースあったのかな?",
                instruction="答えて",
                supervisor_sys_prompt="",
                supervisor_dynamic_sys="",
                executor_sys_prompt="あなたはアシスタントです。",
                executor_dynamic_sys="",
                mode="chat",
                session_id="test-dump",
                history_messages=[],
                search_results=None,
                memory_text=None,
                max_tool_loops=5,
                max_supervisor_retries=2,
                yield_sse_func=None,
            )

    final, _summary, _esc = asyncio.run(_run())
    assert synth_calls["n"] >= 1
    assert "[Local Tool:" not in final
    assert "【一般検索結果" not in final
    assert "【引用契約】" not in final
    assert "GOOGL" in final or "上昇" in final


def test_normal_single_tool_then_prose_no_leak():
    """1回ツール→次ターン自然文、の正常経路でダンプが混ざらない。"""
    from app.core.auto_execution_loop.loop import auto_execute_with_retry

    call_n = {"n": 0}

    def fake_executor(**kwargs):
        call_n["n"] += 1
        if call_n["n"] == 1:
            text = '<mcp_call tool="get_stock_quote" ticker="GOOGL" />\n'
        else:
            text = (
                "<<<FINAL_ANSWER>>>\n"
                "GOOGLの直近値は上昇しています。材料は決算後の買い戻しです。\n"
            )

        async def _gen():
            yield text

        return _gen()

    class FakeHandler:
        def __init__(self, **kwargs):
            self.tool_results: list[str] = []
            self.has_escalation = False
            self.escalation_history: list = []

        async def execute_tools(self, current_response: str):
            self.tool_results = [
                '[Local Tool: get_stock_quote]\n{"ticker": "GOOGL", "current_price": 356.13}',
            ]
            return current_response, []

    async def fake_compress(history):
        return history

    async def _run():
        with (
            patch("app.core.auto_execution_loop.loop.run_executor", side_effect=fake_executor),
            patch("app.core.auto_execution_loop.loop.ToolHandler", FakeHandler),
            patch(
                "app.core.auto_execution_loop.loop._smart_compress_loop_history",
                side_effect=fake_compress,
            ),
            patch(
                "app.core.fact_filters.pipeline.apply_grounding_pipeline",
                side_effect=lambda t, *_a, **_k: t,
            ),
        ):
            return await auto_execute_with_retry(
                user_input="GOOGLどう？",
                instruction="答えて",
                supervisor_sys_prompt="",
                supervisor_dynamic_sys="",
                executor_sys_prompt="あなたはアシスタントです。",
                executor_dynamic_sys="",
                mode="chat",
                session_id="test-ok",
                history_messages=[],
                search_results=None,
                memory_text=None,
                max_tool_loops=5,
                yield_sse_func=None,
            )

    final, _summary, _esc = asyncio.run(_run())
    assert "[Local Tool:" not in final
    assert "上昇" in final
