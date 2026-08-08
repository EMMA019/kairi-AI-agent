"""IBKR 優先株価経路の単体テスト。"""
from unittest.mock import patch

from app.core.ibkr.client import resolve_ib_contract
from app.core.tools import market_data


def test_resolve_us_and_jp_contracts():
    us = resolve_ib_contract("AAPL")
    assert us.symbol == "AAPL"
    assert us.exchange == "SMART"
    jp = resolve_ib_contract("7203.T")
    assert jp.symbol == "7203"
    assert jp.currency == "JPY"
    n225 = resolve_ib_contract("^N225")
    assert n225.symbol == "N225"
    assert n225.exchange == "OSE.JPN"
    topx = resolve_ib_contract("^TOPX")
    assert topx.symbol == "TOPX"
    assert topx.exchange == "OSE.JPN"


def test_quote_prefers_ibkr():
    ib_q = {
        "ticker": "AAPL",
        "name": "AAPL",
        "current_price": 100.0,
        "previous_close": 99.0,
        "change": 1.0,
        "change_pct": 1.01,
        "dividend_yield": None,
        "currency": "USD",
        "source": "ibkr",
    }
    with patch("app.core.tools.market_data._try_ibkr_quote", return_value=ib_q):
        with patch("app.core.tools.market_data._quote_dict_yf") as yf:
            out = market_data._quote_dict("AAPL")
            yf.assert_not_called()
    assert out["source"] == "ibkr"
    assert out["current_price"] == 100.0
    assert out["dividend_yield"] is None


def test_quote_falls_back_to_yfinance():
    yf_q = {
        "ticker": "AAPL",
        "current_price": 200.0,
        "dividend_yield": "0.40%",
        "source": "yfinance",
    }
    with patch("app.core.tools.market_data._try_ibkr_quote", return_value=None):
        with patch("app.core.tools.market_data._quote_dict_yf", return_value=yf_q):
            out = market_data._quote_dict("AAPL")
    assert out["source"] == "yfinance"
    assert out["current_price"] == 200.0
