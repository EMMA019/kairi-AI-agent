"""配当利回りフォーマットの回帰テスト。"""
from app.core.tools.market_data import _format_dividend_yield


def test_aapl_style_yield_not_multiplied_to_32pct():
    # yfinance が 0.32 を返しても ×100 して 32% にしない
    info = {"dividendYield": 0.32, "dividendRate": 1.04}
    out = _format_dividend_yield(info, current_price=336.91, previous_close=333.02)
    assert out is not None
    assert out.endswith("%")
    pct = float(out[:-1])
    assert pct < 2.0  # AAPL 級は 1% 未満が普通
    assert abs(pct - (1.04 / 336.91) * 100) < 0.01


def test_classic_ratio_yield():
    info = {"dividendYield": 0.004}
    out = _format_dividend_yield(info, current_price=100.0, previous_close=100.0)
    assert out == "0.40%"


def test_already_percent_above_one():
    info = {"dividendYield": 2.5}
    out = _format_dividend_yield(info, current_price=None, previous_close=None)
    assert out == "2.50%"
