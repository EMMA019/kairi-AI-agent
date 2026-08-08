"""IBKR market data type / batch quote helpers."""
import os
from unittest.mock import patch

from app.core.ibkr import client as ibkr_client
from app.core.tools import market_data


def test_market_data_type_defaults_to_live():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("IBKR_MARKET_DATA_TYPE", None)
        assert ibkr_client.market_data_type() == 1


def test_market_data_type_delayed():
    with patch.dict(os.environ, {"IBKR_MARKET_DATA_TYPE": "3"}, clear=False):
        assert ibkr_client.market_data_type() == 3


def test_parse_ticker_list():
    assert market_data._parse_ticker_list("AAPL, MSFT") == ["AAPL", "MSFT"]
    assert market_data._parse_ticker_list(["SPY", "QQQ"]) == ["SPY", "QQQ"]
    assert market_data._parse_ticker_list('["DIA","IWM"]') == ["DIA", "IWM"]


def test_quotes_batch_uses_ibkr_then_yf_gap():
    ib_payload = {
        "ok": True,
        "data": {
            "quotes": {
                "AAPL": {
                    "ticker": "AAPL",
                    "current_price": 100.0,
                    "source": "ibkr",
                    "realtime": True,
                    "market_data_type": 1,
                },
                "MSFT": {
                    "ticker": "MSFT",
                    "error": "not_subscribed",
                    "message": "10089",
                    "source": "ibkr",
                },
            }
        },
    }
    yf_q = {"ticker": "MSFT", "current_price": 200.0, "source": "yfinance"}

    with patch("app.core.ibkr.client.ibkr_market_data_enabled", return_value=True):
        with patch("app.core.ibkr.client.fetch_quotes", return_value=ib_payload):
            with patch(
                "app.core.tools.market_data._quote_dict_yf",
                return_value=yf_q,
            ):
                with patch("app.core.tools.market_data._merge_vol_atr", side_effect=lambda q: q):
                    out = market_data._quotes_batch(
                        ["AAPL", "MSFT"],
                        prefer_yfinance=False,
                        enrich_vol_atr=False,
                    )
    assert out["quotes"]["AAPL"]["source"] == "ibkr"
    assert out["quotes"]["MSFT"]["source"] == "yfinance"
    assert out["source"] == "mixed"


def test_running_on_cloud_render():
    with patch.dict(
        os.environ,
        {"RENDER": "true", "KAIRI_CLOUD": ""},
        clear=False,
    ):
        os.environ.pop("KAIRI_CLOUD", None)
        assert ibkr_client.running_on_cloud() is True


def test_market_data_off_on_cloud_when_unset():
    env = {
        "IBKR_ENABLED": "1",
        "RENDER": "true",
    }
    with patch.dict(os.environ, env, clear=False):
        os.environ.pop("IBKR_MARKET_DATA", None)
        os.environ.pop("KAIRI_CLOUD", None)
        assert ibkr_client.ibkr_market_data_enabled() is False


def test_market_data_off_local_when_unset():
    """未設定時は Yahoo 専属（API データ課金回避）。"""
    with patch.dict(os.environ, {"IBKR_ENABLED": "1"}, clear=False):
        os.environ.pop("IBKR_MARKET_DATA", None)
        os.environ.pop("RENDER", None)
        os.environ.pop("RENDER_EXTERNAL_URL", None)
        os.environ.pop("RENDER_SERVICE_ID", None)
        os.environ.pop("KAIRI_CLOUD", None)
        assert ibkr_client.running_on_cloud() is False
        assert ibkr_client.ibkr_market_data_enabled() is False


def test_market_data_explicit_overrides_cloud():
    with patch.dict(
        os.environ,
        {"IBKR_ENABLED": "1", "RENDER": "true", "IBKR_MARKET_DATA": "1"},
        clear=False,
    ):
        assert ibkr_client.ibkr_market_data_enabled() is True


def test_format_jp_snapshot_forces_prefer_yfinance():
    with patch(
        "app.core.tools.market_data.get_jp_market_snapshot",
        return_value={
            "source": "yfinance",
            "session": "afternoon",
            "indices": {},
            "sectors": {},
            "errors": [],
            "n225_intraday": {"ok": False},
        },
    ) as snap:
        market_data.format_jp_market_snapshot_for_prompt("日本市場どうだった？")
        assert snap.call_args.kwargs.get("prefer_yfinance") is True
