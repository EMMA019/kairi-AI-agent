"""IBKR 閲覧専用ツール／スキーマの単体テスト（Gateway 不要）。"""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

from app.core.ibkr.client import (
    connection_settings,
    fetch_account_summary,
    fetch_positions,
    fetch_recent_fills,
)
from app.core.ibkr.schema import (
    ACCOUNT_SUMMARY_TAGS,
    FILL_KEYS,
    FILL_LIMIT_DEFAULT,
    FILL_LIMIT_MAX,
    POSITION_KEYS,
    normalize_fill,
    normalize_position,
    ok_payload,
)


def test_fill_limits():
    assert FILL_LIMIT_DEFAULT == 20
    assert FILL_LIMIT_MAX == 50


def test_default_port_is_live_tws():
    with patch.dict(
        os.environ,
        {"IBKR_HOST": "127.0.0.1", "IBKR_PORT": "", "IBKR_CLIENT_ID": "100"},
        clear=False,
    ):
        # 空文字は int 失敗で DEFAULT に落ちる実装ではないので明示 7496
        os.environ.pop("IBKR_PORT", None)
        s = connection_settings()
        assert s["port"] == 7496
        assert s["host"] == "127.0.0.1"


def test_client_id_includes_pid_offset():
    with patch.dict(os.environ, {"IBKR_CLIENT_ID": "100"}, clear=False):
        s = connection_settings()
        assert s["client_id_base"] == 100
        assert s["client_id"] == 100 + (os.getpid() % 10000)


def test_position_schema_keys_stable():
    raw = {
        "symbol": "AAPL",
        "localSymbol": "AAPL",
        "secType": "STK",
        "currency": "USD",
        "exchange": "SMART",
        "conId": 265598,
        "position": 10.0,
        "avgCost": 150.0,
        "extra_ignored": True,
    }
    out = normalize_position(raw)
    assert tuple(out.keys()) == POSITION_KEYS
    assert "extra_ignored" not in out


def test_fill_schema_keys_stable():
    raw = {
        "time": "2026-07-28 10:00:00",
        "symbol": "NVDA",
        "localSymbol": "NVDA",
        "side": "BOT",
        "shares": 1.0,
        "price": 100.0,
        "commission": 1.0,
        "currency": "USD",
        "execId": "x",
        "orderId": 1,
        "noise": 1,
    }
    out = normalize_fill(raw)
    assert tuple(out.keys()) == FILL_KEYS
    assert "noise" not in out


def test_account_tags_schema_stable():
    tags = {k: None for k in ACCOUNT_SUMMARY_TAGS}
    tags["NetLiquidation"] = "1000000"
    data = ok_payload({"account": "DU123456", "tags": tags}, source="ibkr")
    assert data["ok"] is True
    assert set(data["data"]["tags"].keys()) == set(ACCOUNT_SUMMARY_TAGS)


def test_disabled_returns_explicit_error():
    with patch.dict(os.environ, {"IBKR_ENABLED": "0"}, clear=False):
        payload = fetch_account_summary()
        assert payload["ok"] is False
        assert payload["error"] == "ibkr_disabled"


def test_mock_positions_via_with_ib():
    pos = MagicMock()
    pos.position = 5
    pos.avgCost = 200.5
    pos.contract = MagicMock(
        symbol="MSFT",
        localSymbol="MSFT",
        secType="STK",
        currency="USD",
        exchange="SMART",
        conId=272093,
    )

    def fake_with_ib(fetch):
        ib = MagicMock()
        ib.positions.return_value = [pos]
        return fetch(ib)

    with patch("app.core.ibkr.client._with_ib", side_effect=fake_with_ib):
        payload = fetch_positions()
    assert payload["ok"] is True
    assert payload["data"]["count"] == 1
    row = payload["data"]["positions"][0]
    assert tuple(row.keys()) == POSITION_KEYS
    assert row["symbol"] == "MSFT"
    assert row["position"] == 5.0


def test_mock_fills_respect_limit():
    def make_fill(i: int):
        t = MagicMock()
        t.contract = MagicMock(symbol=f"T{i}", localSymbol=f"T{i}", currency="USD")
        t.execution = MagicMock(
            time=f"2026-07-28 12:{i:02d}:00",
            side="BOT",
            shares=1.0,
            price=10.0 + i,
            execId=str(i),
            orderId=i,
        )
        t.commissionReport = MagicMock(commission=0.5)
        return t

    def fake_with_ib(fetch):
        ib = MagicMock()
        ib.reqExecutions.return_value = [make_fill(i) for i in range(30)]
        return fetch(ib)

    with patch("app.core.ibkr.client._with_ib", side_effect=fake_with_ib):
        with patch.dict("sys.modules", {"ib_insync": MagicMock(ExecutionFilter=MagicMock)}):
            payload = fetch_recent_fills(limit=20)
    assert payload["ok"] is True
    assert payload["data"]["limit"] == 20
    assert payload["data"]["count"] == 20
    assert tuple(payload["data"]["fills"][0].keys()) == FILL_KEYS


def test_fills_limit_clamped_to_max():
    def fake_with_ib(fetch):
        ib = MagicMock()
        ib.reqExecutions.return_value = []
        return fetch(ib)

    with patch("app.core.ibkr.client._with_ib", side_effect=fake_with_ib):
        with patch.dict("sys.modules", {"ib_insync": MagicMock(ExecutionFilter=MagicMock)}):
            payload = fetch_recent_fills(limit=999)
    assert payload["data"]["limit"] == FILL_LIMIT_MAX


def test_tools_registered():
    from app.core.tools.registry import tool_registry
    import app.core.tools.ibkr_tools  # noqa: F401

    names = set(tool_registry.list_tools())
    assert "ibkr_account_summary" in names
    assert "ibkr_positions" in names
    assert "ibkr_recent_fills" in names


def test_worker_creates_event_loop():
    """スレッド内で event loop 未設定だと ib_insync が落ちる問題の回帰防止。"""
    import asyncio
    from unittest.mock import MagicMock

    seen = {}

    class FakeIB:
        def __init__(self):
            seen["loop"] = asyncio.get_event_loop()

        def connect(self, *a, **k):
            return None

        def isConnected(self):
            return True

        def disconnect(self):
            return None

        def managedAccounts(self):
            return ["DU1"]

        def accountSummary(self, account=""):
            return [MagicMock(tag="NetLiquidation", value="1")]

        def accountValues(self, account=""):
            return []

    with patch.dict(os.environ, {"IBKR_ENABLED": "1"}, clear=False):
        with patch("ib_insync.IB", FakeIB):
            from app.core.ibkr.client import fetch_account_summary

            out = fetch_account_summary()
    assert out["ok"] is True
    assert seen.get("loop") is not None


def test_tool_disabled_json_roundtrip():
    from app.core.tools.ibkr_tools import ibkr_account_summary

    with patch.dict(os.environ, {"IBKR_ENABLED": "0"}, clear=False):
        text = ibkr_account_summary()
    data = json.loads(text)
    assert data["ok"] is False
    assert data["error"] == "ibkr_disabled"
