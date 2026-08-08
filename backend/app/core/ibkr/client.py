"""
IBKR Gateway / TWS 読み取り専用クライアント。

- 発注・取消・変更 API は一切呼び出さない（コードパス不在）
- 短命接続: connect → fetch → disconnect
- Client ID は base + pid 由来でプロセス間衝突を緩和
"""
from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Any, Callable, TypeVar

# 購読不足・競合時は待たずに諦める（yfinance フォールバックを速くする）
_SUBSCRIPTION_ERROR_CODES = frozenset({10089, 354, 162, 10197, 200})

from app.core.ibkr.schema import (
    ACCOUNT_SUMMARY_TAGS,
    FILL_LIMIT_DEFAULT,
    FILL_LIMIT_MAX,
    empty_account_tags,
    error_payload,
    normalize_fill,
    normalize_position,
    ok_payload,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

T = TypeVar("T")

# live TWS 既定。paper TWS は 7497、Gateway paper は 4002 / live は 4001。
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7496
DEFAULT_CLIENT_ID_BASE = 100
CONNECT_TIMEOUT_SEC = 8.0
CALL_TIMEOUT_SEC = 25.0


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def running_on_cloud() -> bool:
    """
    Render 等のクラウド（外部スマホ向け）かどうか。
    明示 KAIRI_CLOUD=0/1 があればそれを優先。
    """
    raw = os.getenv("KAIRI_CLOUD")
    if raw is not None and raw.strip() != "":
        return _env_bool("KAIRI_CLOUD", False)
    if _env_bool("RENDER", False):
        return True
    if (os.getenv("RENDER_EXTERNAL_URL") or "").strip():
        return True
    if (os.getenv("RENDER_SERVICE_ID") or "").strip():
        return True
    return False


def ibkr_enabled() -> bool:
    return _env_bool("IBKR_ENABLED", False)


def ibkr_market_data_enabled() -> bool:
    """
    株価取得を IBKR 優先にするか。

    - IBKR_ENABLED がオフなら False
    - IBKR_MARKET_DATA 明示時はそれに従う
    - 未設定なら False（Yahoo 専属推奨。API データ課金・Error 10089 回避）
    - 口座ツール（残高・ポジション）は IBKR_ENABLED のみで動く
    """
    if not ibkr_enabled():
        return False
    raw = os.getenv("IBKR_MARKET_DATA")
    if raw is not None and raw.strip() != "":
        return _env_bool("IBKR_MARKET_DATA", False)
    return False


def market_data_type() -> int:
    """
    IBKR reqMarketDataType:
      1 = Live（本番リアルタイム）
      2 = Frozen
      3 = Delayed（〜15分）
      4 = Delayed frozen
    既定は 1（購読あり本番向け）。未購読時は速失敗→yfinance。
    """
    try:
        v = int(os.getenv("IBKR_MARKET_DATA_TYPE", "1"))
    except ValueError:
        v = 1
    return v if v in (1, 2, 3, 4) else 1


def connection_settings() -> dict[str, Any]:
    host = os.getenv("IBKR_HOST", DEFAULT_HOST).strip() or DEFAULT_HOST
    try:
        port = int(os.getenv("IBKR_PORT", str(DEFAULT_PORT)))
    except ValueError:
        port = DEFAULT_PORT
    try:
        base = int(os.getenv("IBKR_CLIENT_ID", str(DEFAULT_CLIENT_ID_BASE)))
    except ValueError:
        base = DEFAULT_CLIENT_ID_BASE
    # 同一マシン上の別プロセス衝突を避ける（短命接続でも並行呼び出しがあり得る）
    client_id = base + (os.getpid() % 10000)
    return {
        "host": host,
        "port": port,
        "client_id_base": base,
        "client_id": client_id,
        "enabled": ibkr_enabled(),
    }


def _run_in_worker(fn: Callable[[], T], timeout: float = CALL_TIMEOUT_SEC) -> T:
    """FastAPI のイベントループと分離して ib_insync を動かす。"""
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="ibkr") as pool:
        fut = pool.submit(fn)
        return fut.result(timeout=timeout)


def _ensure_thread_event_loop() -> Any:
    """ワーカースレッド用に asyncio ループを用意（ib_insync 必須）。"""
    import asyncio

    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop


def _with_ib(fetch: Callable[[Any], dict[str, Any]]) -> dict[str, Any]:
    settings = connection_settings()
    host = settings["host"]
    port = settings["port"]
    client_id = settings["client_id"]

    if not settings["enabled"]:
        return error_payload(
            "ibkr_disabled",
            "IBKR_ENABLED がオフです。Gateway/TWS 起動後に IBKR_ENABLED=1 を設定してください。",
            host=host,
            port=port,
        )

    def worker() -> dict[str, Any]:
        loop = None
        ib = None
        try:
            loop = _ensure_thread_event_loop()
            from ib_insync import IB

            ib = IB()
            ib.connect(host, port, clientId=client_id, timeout=CONNECT_TIMEOUT_SEC, readonly=True)
            if not ib.isConnected():
                return error_payload(
                    "gateway_unavailable",
                    f"TWS/Gateway に接続できませんでした ({host}:{port}, clientId={client_id})",
                    host=host,
                    port=port,
                    extra={"client_id": client_id},
                )
            return fetch(ib)
        except FuturesTimeout:
            raise
        except ImportError:
            return error_payload(
                "ib_insync_missing",
                "ib_insync がインストールされていません。pip install ib_insync を実行してください。",
                host=host,
                port=port,
            )
        except Exception as e:
            logger.warning(f"IBKR connect/fetch failed: {e}")
            return error_payload(
                "gateway_unavailable",
                f"TWS/Gateway 接続または取得に失敗: {e}",
                host=host,
                port=port,
                extra={"client_id": client_id},
            )
        finally:
            try:
                if ib is not None and ib.isConnected():
                    ib.disconnect()
            except Exception:
                pass
            # スレッド再利用時に閉じたループを残さない
            try:
                if loop is not None and not loop.is_closed():
                    loop.close()
            except Exception:
                pass

    try:
        return _run_in_worker(worker)
    except FuturesTimeout:
        return error_payload(
            "timeout",
            f"IBKR 呼び出しが {CALL_TIMEOUT_SEC:.0f}s でタイムアウトしました",
            host=host,
            port=port,
            extra={"client_id": client_id},
        )
    except Exception as e:
        return error_payload(
            "gateway_unavailable",
            f"IBKR ワーカー失敗: {e}",
            host=host,
            port=port,
        )


def fetch_account_summary() -> dict[str, Any]:
    def fetch(ib: Any) -> dict[str, Any]:
        accounts = list(ib.managedAccounts() or [])
        account = accounts[0] if accounts else ""
        tags = empty_account_tags()
        rows = ib.accountSummary(account) if account else ib.accountSummary()
        for av in rows or []:
            tag = getattr(av, "tag", None)
            if tag in tags:
                tags[tag] = getattr(av, "value", None)
            # Currency は複数行あり得るが、USD/JPY の代表を保持
            if tag == "Currency" and tags.get("Currency") is None:
                tags["Currency"] = getattr(av, "value", None)
        # accountSummary に無いタグは accountValues からも拾う
        for av in ib.accountValues(account) if account else ib.accountValues():
            tag = getattr(av, "tag", None)
            if tag in ACCOUNT_SUMMARY_TAGS and tags.get(tag) is None:
                tags[tag] = getattr(av, "value", None)
        return ok_payload(
            {"account": account or None, "tags": tags},
            source="ibkr",
            client_id=connection_settings()["client_id"],
        )

    return _with_ib(fetch)


def fetch_positions() -> dict[str, Any]:
    def fetch(ib: Any) -> dict[str, Any]:
        positions = []
        for p in ib.positions() or []:
            contract = getattr(p, "contract", None)
            row = {
                "symbol": getattr(contract, "symbol", None) if contract else None,
                "localSymbol": getattr(contract, "localSymbol", None) if contract else None,
                "secType": getattr(contract, "secType", None) if contract else None,
                "currency": getattr(contract, "currency", None) if contract else None,
                "exchange": getattr(contract, "exchange", None) if contract else None,
                "conId": getattr(contract, "conId", None) if contract else None,
                "position": float(getattr(p, "position", 0) or 0),
                "avgCost": float(getattr(p, "avgCost", 0) or 0),
            }
            positions.append(normalize_position(row))
        # ゼロポジションは除外
        positions = [x for x in positions if (x.get("position") or 0) != 0]
        return ok_payload(
            {"positions": positions, "count": len(positions)},
            source="ibkr",
        )

    return _with_ib(fetch)


def fetch_recent_fills(limit: int = FILL_LIMIT_DEFAULT) -> dict[str, Any]:
    lim = max(1, min(int(limit or FILL_LIMIT_DEFAULT), FILL_LIMIT_MAX))

    def fetch(ib: Any) -> dict[str, Any]:
        fills_out = []
        # reqExecutions で当日〜直近を取得
        try:
            from ib_insync import ExecutionFilter

            trades = ib.reqExecutions(ExecutionFilter()) or []
        except Exception:
            trades = ib.fills() or []

        for t in trades:
            execution = getattr(t, "execution", t)
            contract = getattr(t, "contract", None)
            commission_report = getattr(t, "commissionReport", None)
            commission = None
            if commission_report is not None:
                commission = getattr(commission_report, "commission", None)
            row = {
                "time": str(getattr(execution, "time", None) or ""),
                "symbol": getattr(contract, "symbol", None) if contract else None,
                "localSymbol": getattr(contract, "localSymbol", None) if contract else None,
                "side": getattr(execution, "side", None),
                "shares": float(getattr(execution, "shares", 0) or 0),
                "price": float(getattr(execution, "price", 0) or 0),
                "commission": float(commission) if commission is not None else None,
                "currency": getattr(contract, "currency", None) if contract else None,
                "execId": getattr(execution, "execId", None),
                "orderId": getattr(execution, "orderId", None),
            }
            fills_out.append(normalize_fill(row))

        # 新しい順（time 文字列降順で近似）
        fills_out.sort(key=lambda x: x.get("time") or "", reverse=True)
        fills_out = fills_out[:lim]
        return ok_payload(
            {"fills": fills_out, "count": len(fills_out), "limit": lim},
            source="ibkr",
        )

    return _with_ib(fetch)


def resolve_ib_contract(symbol: str) -> Any:
    """Yahoo風ティッカー → IB Contract（発注はしない）。"""
    from ib_insync import Forex, Index, Stock

    s = (symbol or "").strip().upper()
    if not s:
        raise ValueError("empty symbol")

    # FX
    if s in ("USDJPY=X", "USDJPY", "USD/JPY", "USD.JPY"):
        return Forex("USDJPY")

    # 指数
    if s in ("^N225", "N225", "NIKKEI", "NIKKEI225", "NIKKEI 225"):
        return Index("N225", "OSE.JPN", "JPY")
    if s in ("^TOPX", "TOPIX", "TOPX", "TPX"):
        return Index("TOPX", "OSE.JPN", "JPY")
    if s in ("^GSPC", "SPX", "S&P500", "S&P 500"):
        return Index("SPX", "CBOE", "USD")
    if s in ("^DJI", "DJI", "DOW", "DJIA"):
        return Index("INDU", "CME", "USD")  # Dow Jones Industrial
    if s in ("^IXIC", "COMP", "NASDAQ"):
        return Index("COMP", "NASDAQ", "USD")
    if s in ("^SOX", "SOX"):
        return Index("SOX", "PHLX", "USD")

    # 東証 .T
    if s.endswith(".T"):
        return Stock(s[:-2], "TSEJ", "JPY")

    # 数字のみ（東証コード）
    if s.isdigit():
        return Stock(s, "TSEJ", "JPY")

    # 米国株デフォルト
    return Stock(s, "SMART", "USD")


def _finite(x: Any) -> float | None:
    import math

    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _quote_from_ib_ticker(symbol: str, contract: Any, t: Any) -> dict[str, Any]:
    last = _finite(getattr(t, "last", None))
    close = _finite(getattr(t, "close", None))
    bid = _finite(getattr(t, "bid", None))
    ask = _finite(getattr(t, "ask", None))
    try:
        mkt = _finite(t.marketPrice()) if hasattr(t, "marketPrice") else None
    except Exception:
        mkt = None
    current = mkt or last or close or bid or ask
    previous = close
    change = None
    change_pct = None
    if current is not None and previous not in (None, 0):
        change = current - previous
        change_pct = (change / previous) * 100.0
    currency = getattr(contract, "currency", None) or "USD"
    name = getattr(contract, "localSymbol", None) or getattr(contract, "symbol", None) or symbol
    return {
        "ticker": symbol,
        "name": name,
        "current_price": current,
        "previous_close": previous,
        "change": change,
        "change_pct": change_pct,
        "open": _finite(getattr(t, "open", None)),
        "day_low": _finite(getattr(t, "low", None)),
        "day_high": _finite(getattr(t, "high", None)),
        "52_week_low": None,
        "52_week_high": None,
        "volume": _finite(getattr(t, "volume", None)),
        "dividend_yield": None,  # IB 経路では捏造しない
        "trailing_pe": None,
        "forward_pe": None,
        "market_cap": None,
        "currency": currency,
        "source": "ibkr",
        "bid": bid,
        "ask": ask,
    }


def _quote_from_bars(symbol: str, contract: Any, bars: Any) -> dict[str, Any] | None:
    if bars is None or len(bars) == 0:
        return None
    last_bar = bars[-1]
    prev_bar = bars[-2] if len(bars) > 1 else None
    current = _finite(getattr(last_bar, "close", None))
    previous = _finite(getattr(prev_bar, "close", None)) if prev_bar else None
    change = None
    change_pct = None
    if current is not None and previous not in (None, 0):
        change = current - previous
        change_pct = (change / previous) * 100.0
    return {
        "ticker": symbol,
        "name": getattr(contract, "localSymbol", None) or getattr(contract, "symbol", None) or symbol,
        "current_price": current,
        "previous_close": previous,
        "change": change,
        "change_pct": change_pct,
        "open": _finite(getattr(last_bar, "open", None)),
        "day_low": _finite(getattr(last_bar, "low", None)),
        "day_high": _finite(getattr(last_bar, "high", None)),
        "52_week_low": None,
        "52_week_high": None,
        "volume": _finite(getattr(last_bar, "volume", None)),
        "dividend_yield": None,
        "trailing_pe": None,
        "forward_pe": None,
        "market_cap": None,
        "currency": getattr(contract, "currency", None) or "USD",
        "source": "ibkr",
        "bid": None,
        "ask": None,
    }


def _ticker_has_price(t: Any) -> bool:
    last = _finite(getattr(t, "last", None))
    close = _finite(getattr(t, "close", None))
    bid = _finite(getattr(t, "bid", None))
    ask = _finite(getattr(t, "ask", None))
    try:
        mkt = _finite(t.marketPrice()) if hasattr(t, "marketPrice") else None
    except Exception:
        mkt = None
    return (mkt or last or close or bid or ask) is not None


def _attach_md_meta(quote: dict[str, Any], md_type: int) -> dict[str, Any]:
    quote = dict(quote)
    quote["market_data_type"] = md_type
    quote["realtime"] = md_type == 1
    if quote.get("source") == "ibkr" and md_type in (3, 4):
        quote["source"] = "ibkr_delayed"
    return quote


def _fetch_one_quote(ib: Any, symbol: str) -> dict[str, Any]:
    contract = resolve_ib_contract(symbol)
    md_type = market_data_type()
    try:
        ib.reqMarketDataType(md_type)
    except Exception:
        pass

    sub_errors: list[str] = []

    def on_error(reqId: Any, errorCode: Any, errorString: Any, contractObj: Any = None) -> None:
        try:
            code = int(errorCode)
        except (TypeError, ValueError):
            return
        if code in _SUBSCRIPTION_ERROR_CODES:
            sub_errors.append(f"{code}:{errorString}")

    try:
        ib.errorEvent += on_error
    except Exception:
        pass

    try:
        qualified = ib.qualifyContracts(contract)
        if not qualified:
            return {
                "ticker": symbol,
                "error": "contract_not_found",
                "message": f"IBKR でコントラクト解決できません: {symbol}",
                "source": "ibkr",
                "market_data_type": md_type,
                "realtime": False,
            }
        contract = qualified[0]
        if sub_errors:
            return {
                "ticker": symbol,
                "error": "not_subscribed",
                "message": f"IBKR 購読/契約エラー: {symbol} ({sub_errors[0]})",
                "source": "ibkr",
                "market_data_type": md_type,
                "realtime": False,
            }

        quote: dict[str, Any] | None = None
        try:
            tickers = ib.reqTickers(contract)
            # 最大 ~1.0s。購読エラー or 価格到着で打ち切り
            for _ in range(5):
                ib.sleep(0.2)
                if sub_errors:
                    break
                if tickers and _ticker_has_price(tickers[0]):
                    break
            if tickers and not sub_errors:
                quote = _quote_from_ib_ticker(symbol, contract, tickers[0])
                if quote.get("current_price") is None:
                    quote = None
        except Exception as e:
            logger.warning(f"IBKR reqTickers failed {symbol}: {e}")
            quote = None

        if sub_errors and quote is None:
            return {
                "ticker": symbol,
                "error": "not_subscribed",
                "message": f"IBKR マーケットデータ未購読: {symbol} ({sub_errors[0]})",
                "source": "ibkr",
                "market_data_type": md_type,
                "realtime": False,
            }

        # 購読エラーが無いときだけ日足フォールバック（終値用）
        if quote is None:
            try:
                bars = ib.reqHistoricalData(
                    contract,
                    endDateTime="",
                    durationStr="10 D",
                    barSizeSetting="1 day",
                    whatToShow="TRADES",
                    useRTH=True,
                    formatDate=1,
                )
                quote = _quote_from_bars(symbol, contract, bars)
            except Exception as e:
                logger.warning(f"IBKR historical fallback failed {symbol}: {e}")
                return {
                    "ticker": symbol,
                    "error": "no_market_data",
                    "message": f"IBKR から価格を取得できません: {symbol} ({e})",
                    "source": "ibkr",
                    "market_data_type": md_type,
                    "realtime": False,
                }

        if quote is None or quote.get("current_price") is None:
            return {
                "ticker": symbol,
                "error": "no_market_data",
                "message": f"IBKR 気配・履歴ともに価格なし: {symbol}",
                "source": "ibkr",
                "market_data_type": md_type,
                "realtime": False,
            }
        return _attach_md_meta(quote, md_type)
    finally:
        try:
            ib.errorEvent -= on_error
        except Exception:
            pass


def fetch_quote(symbol: str) -> dict[str, Any]:
    """単一銘柄の気配／終値。成功時は ok_payload、失敗は error 付き dict。"""

    def fetch(ib: Any) -> dict[str, Any]:
        q = _fetch_one_quote(ib, symbol)
        if q.get("error"):
            return error_payload(
                str(q.get("error")),
                str(q.get("message") or q.get("error")),
                extra={"ticker": symbol, "source": "ibkr", "data": q},
            )
        return ok_payload(q, source="ibkr")

    return _with_ib(fetch)


def fetch_quotes(symbols: list[str]) -> dict[str, Any]:
    """複数銘柄。data.quotes[symbol] = quote dict。"""

    def fetch(ib: Any) -> dict[str, Any]:
        out: dict[str, Any] = {}
        errors: list[str] = []
        for sym in symbols:
            q = _fetch_one_quote(ib, sym)
            out[sym] = q
            if q.get("error"):
                errors.append(f"{sym}: {q.get('message') or q.get('error')}")
        return ok_payload({"quotes": out, "errors": errors}, source="ibkr")

    return _with_ib(fetch)


def to_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)
