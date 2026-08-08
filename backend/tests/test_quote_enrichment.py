"""Quote enrichment fields and ticker aliases (no network)."""
from unittest.mock import MagicMock, patch

import pandas as pd

from app.core.tools.market_data import _atr14_from_history, _normalize_ticker


def test_normalize_usdjpy():
    assert _normalize_ticker("USDJPY") == "USDJPY=X"
    assert _normalize_ticker("usd/jpy") == "USDJPY=X"
    assert _normalize_ticker("USDJPY=X") == "USDJPY=X"


def test_atr14_from_history():
    n = 20
    df = pd.DataFrame(
        {
            "High": [10 + i * 0.1 for i in range(n)],
            "Low": [9 + i * 0.1 for i in range(n)],
            "Close": [9.5 + i * 0.1 for i in range(n)],
        }
    )
    atr = _atr14_from_history(df)
    assert atr is not None
    assert atr > 0


def test_quote_dict_yf_includes_metrics():
    from app.core.tools import market_data as md

    hist = pd.DataFrame(
        {
            "Open": [100.0] * 20,
            "High": [102.0] * 20,
            "Low": [99.0] * 20,
            "Close": [101.0] * 20,
            "Volume": [1_000_000] * 20,
        }
    )
    fake_ticker = MagicMock()
    fake_ticker.info = {
        "shortName": "Apple",
        "volume": 1_200_000,
        "averageVolume": 1_000_000,
        "currency": "USD",
    }
    fake_ticker.history = MagicMock(return_value=hist)

    with patch.object(md.yf, "Ticker", return_value=fake_ticker):
        q = md._quote_dict_yf("AAPL", enrich_vol_atr=True)
        assert q["volume"] == 1_200_000
        assert q["average_volume"] == 1_000_000
        assert q["volume_ratio"] == 1.2
        assert q["atr"] is not None
        assert q.get("day_range") is not None
        assert "ret_5d" in q
        assert "ret_20d" in q
