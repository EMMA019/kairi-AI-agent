"""JP market snapshot の構造テスト（ネットワーク不要）。"""
from unittest.mock import patch

from app.core.tools.market_data import (
    _normalize_ticker,
    format_jp_market_snapshot_for_prompt,
    get_jp_market_snapshot,
)


def test_normalize_topix_and_nikkei():
    assert _normalize_ticker("TOPIX") == "^TOPX"
    assert _normalize_ticker("Nikkei 225") == "^N225"
    assert _normalize_ticker("^N225") == "^N225"


def test_jp_snapshot_structure_with_mock():
    fake = {
        "ticker": "^N225",
        "name": "Nikkei 225",
        "current_price": 60784.10,
        "previous_close": 62364.92,
        "change": -1580.82,
        "change_pct": -2.53,
        "open": 62734.68,
        "day_low": 60784.10,
        "day_high": 63138.04,
        "52_week_low": None,
        "52_week_high": None,
        "volume": None,
        "dividend_yield": None,
        "trailing_pe": None,
        "forward_pe": None,
        "market_cap": None,
        "currency": "JPY",
        "source": "yfinance",
    }

    def fake_quote(ticker: str, enrich_vol_atr: bool = False):
        q = dict(fake)
        q["ticker"] = ticker
        if ticker == "1306.T":
            q["current_price"] = 2800.0
            q["previous_close"] = 2790.0
            q["change"] = 10.0
            q["change_pct"] = 0.36
        return q

    fake_intra = {
        "ok": True,
        "session": "afternoon",
        "open": 62734.68,
        "morning_high": 63138.04,
        "morning_low": 61201.98,
        "morning_close": 61689.86,
        "morning_close_at": "2026-07-29T11:30:00+09:00",
        "last": 60784.10,
        "last_at": "2026-07-29T12:55:00+09:00",
        "previous_close": 62364.92,
    }

    with patch("app.core.ibkr.client.ibkr_market_data_enabled", return_value=False):
        with patch("app.core.tools.market_data._quote_dict_yf", side_effect=fake_quote):
            with patch("app.core.tools.market_data._n225_intraday_levels", return_value=fake_intra):
                with patch("app.core.tools.market_data._jp_session_bucket", return_value="afternoon"):
                    snap = get_jp_market_snapshot(include_sectors=True)
                    assert "^N225" in snap["indices"]
                    assert "1306.T" in snap["indices"]
                    assert "1631.T" in snap["sectors"]
                    assert "1633.T" in snap["sectors"]
                    assert "1615.T" not in snap["sectors"]
                    assert len(snap["sectors"]) >= 17
                    text = format_jp_market_snapshot_for_prompt("7/29の日本市場前場")
                    assert "前場終値" in text
                    assert "61,689.86" in text
                    assert "直近値" in text
                    assert "前場終値ではない" in text or "morning_close" in text
                    assert "推測禁止" in text
                    assert "銀行(1631)" in text or "1631" in text
