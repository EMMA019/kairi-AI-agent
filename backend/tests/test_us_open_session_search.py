"""米国場中: 前日終値アンカー／closes固定／企業クエリ消失の回帰防止。"""
from __future__ import annotations

from datetime import date, datetime
from unittest.mock import patch

from app.core.chat_search import (
    JST,
    balance_search_queries,
    build_us_market_search_queries,
    current_us_trading_date,
    extract_us_company_search_seeds,
    resolve_market_anchor_date,
    settled_us_session_date,
    _format_us_market_snapshot_for_prompt,
)
from app.core.market_session import get_us_session_bucket, us_session_is_live
from app.core.search_planner import _market_today_shortcut


def test_us_session_bucket_open_vs_post():
    # ET 2026-07-31 10:56 = JST 2026-07-31 23:56
    open_jst = datetime(2026, 7, 31, 23, 56, tzinfo=JST)
    assert get_us_session_bucket(open_jst) == "open"
    assert us_session_is_live(open_jst) is True

    # ET 2026-07-31 17:00 = JST 2026-08-01 06:00
    post_jst = datetime(2026, 8, 1, 6, 0, tzinfo=JST)
    assert get_us_session_bucket(post_jst) == "post_market"
    assert us_session_is_live(post_jst) is False


def test_live_vs_settled_dates_during_rth():
    open_jst = datetime(2026, 7, 31, 23, 56, tzinfo=JST)
    assert current_us_trading_date(open_jst) == date(2026, 7, 31)
    assert settled_us_session_date(open_jst) == date(2026, 7, 30)

    assert resolve_market_anchor_date(
        "米国市場どう？", market="us", now_jst=open_jst, purpose="live"
    ) == date(2026, 7, 31)
    assert resolve_market_anchor_date(
        "米国市場どう？", market="us", now_jst=open_jst, purpose="settled"
    ) == date(2026, 7, 30)
    assert resolve_market_anchor_date(
        "米国市場どう？", market="us", now_jst=open_jst, purpose="auto"
    ) == date(2026, 7, 31)


def test_post_close_auto_uses_settled():
    # ET 7/29 17:48 = JST 7/30 06:48
    post = datetime(2026, 7, 30, 6, 48, tzinfo=JST)
    assert resolve_market_anchor_date(
        "米国市場どうだった？", market="us", now_jst=post, purpose="auto"
    ) == date(2026, 7, 29)


def test_open_queries_are_live_not_closes():
    open_jst = datetime(2026, 7, 31, 23, 56, tzinfo=JST)
    qs = build_us_market_search_queries(
        "今米国市場開いてるけどどんな感じ？",
        now_jst=open_jst,
    )
    blob = " ".join(qs).lower()
    assert "live" in blob or "today" in blob or "movers" in blob
    assert "wall street closes" not in blob
    assert "end higher" not in blob


def test_open_queries_keep_google_company():
    open_jst = datetime(2026, 7, 31, 23, 56, tzinfo=JST)
    text = "今米国市場開いてるけど、Googleなにかいいニュースあったのかな?今日めっちゃ上がってるね"
    seeds = extract_us_company_search_seeds(text)
    assert any(s["ticker"] == "GOOGL" for s in seeds)

    qs = build_us_market_search_queries(text, now_jst=open_jst)
    blob = " ".join(qs)
    assert "GOOGL" in blob or "Alphabet" in blob
    assert "Wall Street closes" not in blob

    with patch(
        "app.core.chat_search.build_us_market_search_queries",
        return_value=qs,
    ):
        needed, balanced = balance_search_queries(
            text, search_needed=True, search_queries=["junk"]
        )
    assert needed is True
    assert any("GOOGL" in q or "Alphabet" in q for q in balanced)


def test_shortcut_open_uses_live_queries():
    with patch("app.core.market_session.us_session_is_live", return_value=True):
        with patch(
            "app.core.chat_search.current_us_trading_date",
            return_value=date(2026, 7, 31),
        ):
            out = _market_today_shortcut(
                "今日の米国市場どう？",
                "2026-07-31",
                "July 31, 2026",
            )
    assert out is not None
    blob = " ".join(out["search_queries"]).lower()
    assert "wall street closes" not in blob
    assert "live" in blob or "today" in blob or "movers" in blob


def test_explicit_past_date_still_uses_closes():
    out = _market_today_shortcut(
        "7/30の米国市場どうだった？",
        "2026-07-31",
        "July 31, 2026",
    )
    assert out is not None
    blob = " ".join(out["search_queries"])
    assert "Wall Street closes" in blob
    assert "2026-07-30" in blob or "July 30" in blob


def test_open_snapshot_labels_live_not_close():
    fake_q = {
        "current_price": 521.0,
        "previous_close": 510.0,
        "change": 11.0,
        "change_pct": 2.16,
    }
    with patch("app.core.market_session.us_session_is_live", return_value=True):
        with patch(
            "app.core.chat_search.current_us_trading_date",
            return_value=date(2026, 7, 31),
        ):
            with patch(
                "app.core.tools.market_data._quote_dict_yf",
                return_value=fake_q,
            ):
                text = _format_us_market_snapshot_for_prompt(
                    "今米国市場開いてるけどどんな感じ？"
                )

    assert "直近値（取引中）" in text
    assert "終値 as_of=2026-07-30" not in text
    assert "status=取引中" in text
