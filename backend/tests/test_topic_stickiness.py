"""曖昧フォロー（介入等）のトピック粘着・為替優先の回帰テスト。銘柄非依存。"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from app.core.prompt_builder.entity_resolution import (
    is_finance_jargon_topic_shift,
    resolve_zero_anaphora,
    build_entity_registry_context,
)
from app.core.search_planner import plan_search


def test_finance_jargon_is_topic_shift():
    assert is_finance_jargon_topic_shift("介入するかな？ってかしてるのかな？")
    assert is_finance_jargon_topic_shift("円安止まらんね")
    assert not is_finance_jargon_topic_shift("それの介入ってどうなの")
    assert not is_finance_jargon_topic_shift("いいニュースあった？")


def test_zero_anaphora_no_anchor_on_kainyu():
    entities = [
        {"name": "Semiconductor ETF", "description": "ETF", "list_position": 1},
        {"name": "Bank sector", "description": "銀行", "list_position": 2},
    ]
    assert resolve_zero_anaphora("介入するかな？", entities)["mode"] == "no_anchor"
    assert build_entity_registry_context(
        [
            {"role": "assistant", "content": "1. Semiconductor ETF — 強い\n2. Bank sector — 弱い"},
            {"role": "user", "content": "いいニュースあった？"},
        ],
        "介入するかな？ってかしてるのかな？",
    ) == ""


def test_ambiguous_kainyu_forces_fx_and_ignores_prior_company_history():
    """前ターンがどの企業でも、単独『介入』は為替クエリになり履歴企業名をクエリに載せない。"""

    async def _run():
        with patch("app.core.search_planner.call_model", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = (
                '{"needs_search": false, "search_queries": ["NVDA regulation intervention"],'
                ' "providers": ["brave"], "needs_deep_search": false,'
                ' "recommended_mode": "chat", "category": "general"}'
            )
            plan = await plan_search(
                "介入するかな？ってかしてるのかな？",
                [
                    {"role": "user", "content": "NVIDIA健闘してるんだけどいいニュースあった？"},
                    {"role": "assistant", "content": "決算が強かったです"},
                ],
            )
        assert plan["needs_search"] is True
        blob = " ".join(plan.get("search_queries") or []).lower()
        assert "為替介入" in blob or "intervention" in blob
        assert "nvda" not in blob
        assert "nvidia" not in blob
        # 話題転換時は履歴を planner に渡さない
        sent = mock_llm.await_args.kwargs.get("messages") or mock_llm.await_args.args[1]
        # call_model(system_instruction=..., messages=[...])
        if mock_llm.await_args.kwargs.get("messages"):
            ctx = mock_llm.await_args.kwargs["messages"][0]["content"]
        else:
            ctx = mock_llm.await_args.args[1][0]["content"]
        assert "NVIDIA" not in ctx
        assert "直近の会話履歴" in ctx
        assert "なし" in ctx

    asyncio.run(_run())


def test_explicit_regulatory_kainyu_not_forced_to_fx():
    async def _run():
        with patch("app.core.search_planner.call_model", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = (
                '{"needs_search": true, "search_queries": ["EU DMA fine antitrust"],'
                ' "providers": ["brave"], "needs_deep_search": false,'
                ' "recommended_mode": "chat", "category": "finance"}'
            )
            plan = await plan_search(
                "EUの規制介入どうなってる？",
                [{"role": "user", "content": "前の話続き"}],
            )
        blob = " ".join(plan.get("search_queries") or [])
        assert "為替介入" not in blob
        assert plan["needs_search"] is True

    asyncio.run(_run())
