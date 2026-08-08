"""米市況: 前日終値（朝ラップ）と当日終値の取り違え抑止。"""
from datetime import date
from unittest.mock import patch

from app.core.chat_search import _format_us_market_snapshot_for_prompt
from app.core.fact_filters.financial import soften_us_morning_wrap_as_close
from app.core.search.reranker import _freshness_score, rerank
from app.core.search_planner import _market_today_shortcut
from app.core.tools.market_data import fetch_us_etf_session_closes


def test_us_queries_prefer_close_articles_not_morning_wrap():
    out = _market_today_shortcut(
        "7/30の米国市場どうだった？",
        "2026-07-31",
        "July 31, 2026",
    )
    assert out is not None
    blob = " ".join(out["search_queries"])
    assert "Wall Street closes" in blob
    assert "close" in blob.lower()
    assert "US stock market July" not in blob


def test_rerank_prefers_ends_over_morning_news_for():
    query = "Dow S&P Nasdaq close 2026-07-30"
    results = [
        {
            "title": "Stock Market News for July 30, 2026",
            "snippet": "Dow fell 2.2% to 51,594. Industrial and tech led declines.",
            "url": "https://finance.yahoo.com/news-for-july-30",
        },
        {
            "title": "Wall Street ends sharply higher, lifted by soaring Microsoft",
            "snippet": "July 30, 2026 stocks close higher as Microsoft rallies.",
            "url": "https://www.reuters.com/wall-street-ends-higher",
        },
    ]
    ranked = rerank(query, results, top_k=2)
    assert ranked[0]["url"] == "https://www.reuters.com/wall-street-ends-higher"
    wrap = _freshness_score(query, results[0]["title"], results[0]["snippet"])
    close = _freshness_score(query, results[1]["title"], results[1]["snippet"])
    assert close > wrap


def test_snapshot_labels_close_and_previous_close():
    fake = {
        "session_date": "2026-07-30",
        "source": "yfinance",
        "all_matched": True,
        "quotes": {
            "DIA": {
                "ok": True,
                "close": 450.0,
                "previous_close": 440.0,
                "change": 10.0,
                "change_pct": 2.27,
                "as_of": "2026-07-30",
                "matched_session": True,
            },
            "SPY": {
                "ok": True,
                "close": 580.0,
                "previous_close": 570.0,
                "change": 10.0,
                "change_pct": 1.75,
                "as_of": "2026-07-30",
                "matched_session": True,
            },
            "QQQ": {"ok": False, "close": None},
            "SOXX": {"ok": False, "close": None},
        },
    }
    with patch("app.core.chat_search.resolve_market_anchor_date", return_value=date(2026, 7, 30)):
        with patch(
            "app.core.tools.market_data.fetch_us_etf_session_closes",
            return_value=fake,
        ):
            text = _format_us_market_snapshot_for_prompt("7/30の米国市場どうだった？")
    assert "終値 as_of=2026-07-30" in text
    assert "前日終値" in text
    assert "朝刊ラップ" in text or "Premarket" in text
    assert "DIA / SPY / QQQ / SOXX" in text
    assert "記事の日付を優先" not in text


def test_fetch_marks_unmatched_as_not_session_close():
    import pandas as pd

    idx = pd.to_datetime(["2026-07-28", "2026-07-29"]).tz_localize("America/New_York")
    hist = pd.DataFrame({"Close": [100.0, 110.0]}, index=idx)

    class _T:
        def history(self, **kwargs):
            return hist

    with patch("app.core.tools.market_data.yf.Ticker", return_value=_T()):
        out = fetch_us_etf_session_closes(date(2026, 7, 30), ["DIA"])
    q = out["quotes"]["DIA"]
    assert q["ok"] is True
    assert q["matched_session"] is False
    assert q["as_of"] == "2026-07-29"
    assert q["close"] == 110.0


def test_soften_morning_wrap_vs_ends_higher():
    src = """
    Stock Market News for July 30, 2026 — Dow fell 2.2%.
    Wall Street ends sharply higher, lifted by soaring Microsoft
    """
    text = "7月30日の米国市場は大幅下落で引けました。ダウ終値51,594.14（▲2.2%）。"
    out = soften_us_morning_wrap_as_close(text, src)
    assert "終値日付の要確認" in out


def test_soften_no_false_positive_on_correct_rally_with_snapshot_meta():
    """snapshot指示文＋『前日の大幅下落』では注記しない。"""
    src = """
【米国市場スナップショット session_date=2026-07-30 source=yfinance】
※【P0】朝刊ラップ（News-for-DATE / Premarket / Before-the-Open）は前日終値＋当日見通しのことが多い。
- SPY 終値 as_of=2026-07-30: 741.69 +1.68%
Wall Street ends sharply higher, lifted by soaring Microsoft
"""
    text = (
        "前日7/29の大幅下落から一転、7/30は主要指数が揃って急伸しました。"
        "S&P500 (SPY) 終値 741.69（+1.68%）。"
    )
    out = soften_us_morning_wrap_as_close(text, src)
    assert "終値日付の要確認" not in out
