"""soft-US: 個別株初回で why-up + クォート注入の回帰テスト。"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.chat_search import (
    balance_search_queries,
    build_us_market_search_queries,
    is_soft_us_single_stock_query,
    prior_turn_was_us_market,
    store_search_carryover,
    clear_search_carryover,
    _format_us_single_stock_quotes_for_prompt,
    run_web_search,
)
from app.core.search_planner import _market_today_shortcut


ROUTE_A = "Googleなにかいいニュースあったのかな?決算で下げてたけど、今日めっちゃ上がったみたいだね"
ROUTE_B = "GOOGLEってなにかあった？"


def test_soft_us_route_a_without_us_market_keyword():
    assert is_soft_us_single_stock_query(ROUTE_A)
    needed, qs = balance_search_queries(ROUTE_A, False, ["noise"])
    assert needed is True
    blob = " ".join(qs)
    assert "GOOGL" in blob or "Alphabet" in blob
    assert "why up" in blob.lower()
    # 指数だけで上書きされていない
    assert not all("Wall Street" in q or "Dow" in q for q in qs)


def test_soft_us_settled_still_why_up_on_move():
    from datetime import datetime
    from app.core.chat_search import JST

    post = datetime(2026, 8, 1, 6, 0, tzinfo=JST)  # ET post_market
    qs = build_us_market_search_queries(ROUTE_A, now_jst=post, company_focus=True)
    blob = " ".join(qs).lower()
    assert "why up" in blob or "surge" in blob
    assert "googl" in blob or "alphabet" in blob


def test_shortcut_soft_us_skips_planner():
    out = _market_today_shortcut(ROUTE_A, "2026-08-01", "August 1, 2026")
    assert out is not None
    assert out["needs_search"] is True
    blob = " ".join(out["search_queries"])
    assert "GOOGL" in blob or "Alphabet" in blob


def test_route_b_followup_after_us_market_carryover():
    sid = "test-soft-us-route-b"
    clear_search_carryover(sid)
    store_search_carryover(
        sid,
        "【米国市場スナップショット】Dow up",
        ["Wall Street closes July 31, 2026", "Dow S&P Nasdaq close 2026-07-31"],
        "今日の米国市場どうだった？大きく上げたところある？",
    )
    try:
        assert prior_turn_was_us_market(sid) is True
        assert is_soft_us_single_stock_query(ROUTE_B, session_id=sid) is True
        # todayish 無しでも soft-US
        assert "今日" not in ROUTE_B
        needed, qs = balance_search_queries(
            ROUTE_B, False, ["noise"], session_id=sid
        )
        assert needed is True
        blob = " ".join(qs).lower()
        assert "googl" in blob or "alphabet" in blob
        assert "why up" in blob or "catalyst" in blob or "rally" in blob

        out = _market_today_shortcut(
            ROUTE_B, "2026-08-01", "August 1, 2026", session_id=sid
        )
        assert out is not None
    finally:
        clear_search_carryover(sid)


def test_route_b_without_carryover_still_fires_on_nani_attta():
    """『なにかあった』自体が材料聞きなので carry 無しでも soft-US。"""
    assert is_soft_us_single_stock_query(ROUTE_B, session_id=None) is True


def test_single_stock_quote_block_format():
    fake = {
        "ticker": "GOOGL",
        "current_price": 356.13,
        "previous_close": 333.66,
        "change": 22.47,
        "change_pct": 6.73,
        "price_kind": "session_close_or_last",
    }
    with patch(
        "app.core.tools.market_data._quote_dict_yf",
        return_value=fake,
    ):
        block = _format_us_single_stock_quotes_for_prompt(ROUTE_A)
    assert "【個別株クォート" in block
    assert "GOOGL" in block
    assert "356.13" in block
    assert "6.73" in block


def test_run_web_search_prefers_single_quote_over_index_for_soft_us():
    fake = {
        "ticker": "GOOGL",
        "current_price": 356.13,
        "previous_close": 333.66,
        "change": 22.47,
        "change_pct": 6.73,
        "price_kind": "session_close_or_last",
    }

    async def fake_web_search(q, providers=None):
        return ("search body", [{"title": "t", "url": "https://example.com", "content": "c"}])

    async def _run():
        with (
            patch("app.core.chat_search.web_search", side_effect=fake_web_search),
            patch(
                "app.core.tools.market_data._quote_dict_yf",
                return_value=fake,
            ),
            patch(
                "app.core.chat_search._format_us_market_snapshot_for_prompt",
                return_value="【米国ETFスナップ】SHOULD_NOT_APPEAR",
            ),
            patch(
                "app.core.search.reranker.rerank",
                side_effect=lambda _u, srcs, top_k=20: srcs[:top_k],
            ),
            patch(
                "app.core.search.formatter.format_for_prompt",
                side_effect=lambda *a, **k: "formatted",
            ),
        ):
            final = None
            async for ev in run_web_search(
                user_input=ROUTE_A,
                search_queries=[
                    "Alphabet OR GOOGL stock news why up OR surge July 31, 2026",
                    "GOOGL stock 2026-07-31 rally OR jump OR catalyst",
                ],
                search_providers=["brave"],
            ):
                if ev.get("type") == "_result":
                    final = ev.get("text") or ""
            return final

    text = asyncio.run(_run())
    assert text is not None
    assert "【個別株クォート" in text
    assert "356.13" in text
    assert "SHOULD_NOT_APPEAR" not in text
