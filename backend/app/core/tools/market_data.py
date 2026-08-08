import json
from typing import Any

import yfinance as yf
from app.core.tools.registry import tool_registry
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 日本市況スナップショット用ティッカー
# 注: yfinance の ^TOPX は欠落することがあるため、TOPIXは 1306.T（連動ETF）を代理にする
JP_INDEX_TICKERS = {
    "^N225": "日経平均",
    "1306.T": "TOPIX連動ETF(1306)",
}
# NEXT FUNDS TOPIX-17（1617–1633。1615は東証33銀行で別銘柄）
# 出典: NEXT FUNDS / JPX
JP_SECTOR_ETFS = {
    "1617.T": "食品(1617)",
    "1618.T": "エネルギー資源(1618)",
    "1619.T": "建設・資材(1619)",
    "1620.T": "素材・化学(1620)",
    "1621.T": "医薬品(1621)",
    "1622.T": "自動車・輸送機(1622)",
    "1623.T": "鉄鋼・非鉄(1623)",
    "1624.T": "機械(1624)",
    "1625.T": "電機・精密(1625)",
    "1626.T": "情報通信・サービス他(1626)",
    "1627.T": "電力・ガス(1627)",
    "1628.T": "運輸・物流(1628)",
    "1629.T": "商社・卸売(1629)",
    "1630.T": "小売(1630)",
    "1631.T": "銀行(1631)",
    "1632.T": "金融除く銀行(1632)",
    "1633.T": "不動産(1633)",
}


def _normalize_ticker(ticker: str) -> str:
    ticker_upper = ticker.upper().strip()
    if ticker_upper in ["S&P 500", "S&P500", "SPX"]:
        return "^GSPC"
    if ticker_upper in ["DOW", "DOW JONES", "DJI", "NY DOW"]:
        return "^DJI"
    if ticker_upper in ["NASDAQ", "COMP"]:
        return "^IXIC"
    if ticker_upper in ["NIKKEI", "NIKKEI 225", "NIKKEI225", "N225", "^N225"]:
        return "^N225"
    if ticker_upper in ["TOPIX", "^TOPX", "TPX", "トピックス"]:
        return "^TOPX"
    if ticker_upper in ["SOX", "PHLX"]:
        return "^SOX"
    if ticker_upper in ["USDJPY", "USD/JPY", "USD.JPY", "USDJPY=X"]:
        return "USDJPY=X"
    return ticker


def _atr14_from_history(history: Any) -> float | None:
    """簡易 ATR(14)。High/Low/Close が必要。"""
    try:
        if history is None or getattr(history, "empty", True) or len(history) < 15:
            return None
        if not all(c in history.columns for c in ("High", "Low", "Close")):
            return None
        high = history["High"].astype(float)
        low = history["Low"].astype(float)
        close = history["Close"].astype(float)
        prev_close = close.shift(1)
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        tr = tr1.combine(tr2, max).combine(tr3, max)
        atr = float(tr.iloc[-14:].mean())
        if atr != atr:  # NaN
            return None
        return atr
    except Exception:
        return None


def _vol_atr_metrics(ticker: str) -> dict[str, Any]:
    """出来高・平均出来高・ATR・日中レンジ・5/20日リターン（主に yfinance history）。"""
    ticker = _normalize_ticker(ticker)
    out: dict[str, Any] = {
        "volume": None,
        "average_volume": None,
        "atr": None,
        "day_range": None,
        "ret_5d": None,
        "ret_20d": None,
    }
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        history = t.history(period="3mo")
        vol = info.get("volume") or info.get("regularMarketVolume")
        avg_vol = info.get("averageVolume") or info.get("averageVolume10days")
        if history is not None and not history.empty:
            if "Volume" in history.columns:
                last_vol = float(history["Volume"].iloc[-1])
                if vol is None:
                    vol = last_vol
                if avg_vol is None and len(history) >= 5:
                    avg_vol = float(history["Volume"].tail(20).mean())
            day_high = float(history["High"].iloc[-1]) if "High" in history.columns else None
            day_low = float(history["Low"].iloc[-1]) if "Low" in history.columns else None
            if day_high is not None and day_low is not None:
                out["day_range"] = day_high - day_low
                out["day_high"] = day_high
                out["day_low"] = day_low
            out["atr"] = _atr14_from_history(history)
            if "Close" in history.columns:
                closes = history["Close"].astype(float)
                last = float(closes.iloc[-1])
                if len(closes) > 5 and closes.iloc[-6] not in (0, None):
                    out["ret_5d"] = (last / float(closes.iloc[-6]) - 1.0) * 100.0
                if len(closes) > 20 and closes.iloc[-21] not in (0, None):
                    out["ret_20d"] = (last / float(closes.iloc[-21]) - 1.0) * 100.0
        out["volume"] = float(vol) if vol is not None else None
        out["average_volume"] = float(avg_vol) if avg_vol is not None else None
        if out["volume"] is not None and out["average_volume"] not in (None, 0):
            out["volume_ratio"] = out["volume"] / out["average_volume"]
        else:
            out["volume_ratio"] = None
    except Exception as e:
        logger.warning(f"vol/ATR metrics failed {ticker}: {e}")
    return out


def _merge_vol_atr(quote: dict[str, Any]) -> dict[str, Any]:
    """既存 quote に volume / average_volume / atr / volume_ratio / ret_* を足す。"""
    q = dict(quote)
    ticker = str(q.get("ticker") or "")
    m = _vol_atr_metrics(ticker)
    if q.get("volume") is None and m.get("volume") is not None:
        q["volume"] = m["volume"]
    if q.get("day_high") is None and m.get("day_high") is not None:
        q["day_high"] = m["day_high"]
    if q.get("day_low") is None and m.get("day_low") is not None:
        q["day_low"] = m["day_low"]
    q["average_volume"] = m.get("average_volume")
    q["atr"] = m.get("atr")
    q["day_range"] = m.get("day_range")
    q["ret_5d"] = m.get("ret_5d")
    q["ret_20d"] = m.get("ret_20d")
    if q.get("volume") is not None and q.get("average_volume") not in (None, 0):
        try:
            q["volume_ratio"] = float(q["volume"]) / float(q["average_volume"])
        except (TypeError, ValueError, ZeroDivisionError):
            q["volume_ratio"] = m.get("volume_ratio")
    else:
        q["volume_ratio"] = m.get("volume_ratio")
    return q


def _format_dividend_yield(
    info: dict[str, Any],
    current_price: float | None,
    previous_close: float | None,
) -> str | None:
    """
    yfinance の dividendYield は時期によって「比率(0.004=0.4%)」と
    「すでに%近傍(0.32=0.32%)」が混在する。AAPL で 0.32→×100=32% になる事故を防ぐ。

    優先: annual dividendRate / price から算出。
    """
    price = current_price or previous_close or info.get("currentPrice") or info.get("regularMarketPrice")
    div_rate = info.get("dividendRate") or info.get("trailingAnnualDividendRate")
    try:
        if div_rate is not None and price not in (None, 0):
            pct = (float(div_rate) / float(price)) * 100.0
            if 0 <= pct < 100:
                return f"{pct:.2f}%"
    except (TypeError, ValueError, ZeroDivisionError):
        pass

    raw = info.get("dividendYield")
    if raw is None:
        raw = info.get("trailingAnnualDividendYield")
    if raw is None:
        raw = info.get("yield")
    if raw is None:
        return None
    try:
        dy = float(raw)
    except (TypeError, ValueError):
        return None

    if dy >= 1:
        pct = dy
    elif dy > 0.05:
        pct = dy
    else:
        pct = dy * 100.0
    if pct < 0 or pct >= 100:
        return None
    return f"{pct:.2f}%"


def _quote_dict_yf(ticker: str, *, enrich_vol_atr: bool = False) -> dict[str, Any]:
    ticker = _normalize_ticker(ticker)
    t = yf.Ticker(ticker)
    info = t.info or {}
    history = t.history(period="5d")

    current_price = None
    previous_close = None
    day_open = None
    day_high = None
    day_low = None
    if history is not None and not history.empty:
        current_price = float(history["Close"].iloc[-1])
        if len(history) > 1:
            previous_close = float(history["Close"].iloc[-2])
        day_open = float(history["Open"].iloc[-1]) if "Open" in history.columns else None
        day_high = float(history["High"].iloc[-1]) if "High" in history.columns else None
        day_low = float(history["Low"].iloc[-1]) if "Low" in history.columns else None

    price_kind = "session_close_or_last"
    if current_price is None:
        live = info.get("currentPrice") or info.get("regularMarketPrice")
        if live is not None:
            current_price = live
            price_kind = "live_or_regular"
        elif info.get("previousClose") is not None:
            # previousClose を current に入れるのは最終手段。ラベル無しで終値扱いしないこと。
            current_price = info.get("previousClose")
            price_kind = "previous_close_fallback"
    if previous_close is None:
        previous_close = info.get("previousClose")

    change = None
    change_pct = None
    if current_price is not None and previous_close not in (None, 0):
        change = current_price - previous_close
        change_pct = (change / previous_close) * 100.0

    dividend_yield = _format_dividend_yield(info, current_price, previous_close)

    volume = info.get("volume") or info.get("regularMarketVolume")
    if volume is None and history is not None and not history.empty and "Volume" in history.columns:
        try:
            volume = float(history["Volume"].iloc[-1])
        except (TypeError, ValueError, IndexError):
            volume = None

    avg_vol = None
    atr = None
    day_range = None
    volume_ratio = None
    dh = day_high if day_high is not None else info.get("dayHigh")
    dl = day_low if day_low is not None else info.get("dayLow")
    if dh is not None and dl is not None:
        try:
            day_range = float(dh) - float(dl)
        except (TypeError, ValueError):
            day_range = None

    # ATR/平均出来高は追加 history が要るので、ウォッチリスト等だけ明示オプトイン
    if enrich_vol_atr:
        metrics = _vol_atr_metrics(ticker)
        if volume is None:
            volume = metrics.get("volume")
        avg_vol = metrics.get("average_volume")
        atr = metrics.get("atr")
        if day_range is None:
            day_range = metrics.get("day_range")
        if dh is None and metrics.get("day_high") is not None:
            dh = metrics["day_high"]
        if dl is None and metrics.get("day_low") is not None:
            dl = metrics["day_low"]
        ret_5d = metrics.get("ret_5d")
        ret_20d = metrics.get("ret_20d")
    else:
        ret_5d = None
        ret_20d = None

    if volume is not None and avg_vol not in (None, 0):
        try:
            volume_ratio = float(volume) / float(avg_vol)
        except (TypeError, ValueError, ZeroDivisionError):
            volume_ratio = None

    return {
        "ticker": ticker,
        "name": info.get("shortName", ticker),
        "current_price": current_price,
        "previous_close": previous_close,
        "price_kind": price_kind,
        "change": change,
        "change_pct": change_pct,
        "open": day_open if day_open is not None else info.get("open"),
        "day_low": dl,
        "day_high": dh,
        "52_week_low": info.get("fiftyTwoWeekLow"),
        "52_week_high": info.get("fiftyTwoWeekHigh"),
        "volume": volume,
        "average_volume": avg_vol,
        "volume_ratio": volume_ratio,
        "atr": atr,
        "day_range": day_range,
        "ret_5d": ret_5d,
        "ret_20d": ret_20d,
        "dividend_yield": dividend_yield,
        "trailing_pe": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "market_cap": info.get("marketCap"),
        "currency": info.get("currency", "USD"),
        "source": "yfinance",
    }


def fetch_us_etf_session_closes(
    session_date: Any,
    tickers: list[str],
) -> dict[str, Any]:
    """
    指定セッション日（ET カレンダー日）の ETF 日足終値を取得。
    朝の『Stock Market News for DATE』が前日終値を要約する問題への対抗として、
    as_of 日付付きの確定バーを返す。
    """
    from datetime import date as date_cls, timedelta

    if not isinstance(session_date, date_cls):
        session_date = date_cls.fromisoformat(str(session_date)[:10])

    out: dict[str, Any] = {
        "session_date": session_date.isoformat(),
        "quotes": {},
        "all_matched": True,
        "source": "yfinance",
    }
    start = (session_date - timedelta(days=10)).isoformat()
    end = (session_date + timedelta(days=3)).isoformat()

    for ticker in tickers:
        entry: dict[str, Any] = {
            "ticker": ticker,
            "ok": False,
            "close": None,
            "previous_close": None,
            "change": None,
            "change_pct": None,
            "as_of": None,
            "matched_session": False,
        }
        try:
            hist = yf.Ticker(ticker).history(start=start, end=end)
            if hist is None or hist.empty:
                out["quotes"][ticker] = entry
                out["all_matched"] = False
                continue
            bars: list[tuple[Any, float]] = []
            for ts, row in hist.iterrows():
                try:
                    if getattr(ts, "tzinfo", None) is not None:
                        try:
                            from zoneinfo import ZoneInfo

                            d = ts.tz_convert(ZoneInfo("America/New_York")).date()
                        except Exception:
                            d = ts.date()
                    else:
                        d = ts.date() if hasattr(ts, "date") else ts
                    bars.append((d, float(row["Close"])))
                except Exception:
                    continue
            if not bars:
                out["quotes"][ticker] = entry
                out["all_matched"] = False
                continue

            chosen_i = None
            for i, (d, _) in enumerate(bars):
                if d == session_date:
                    chosen_i = i
                    break
            if chosen_i is None:
                # 指定日のバーが無い（祝日等）→ それ以前の直近バー（前日終値扱い）
                for i in range(len(bars) - 1, -1, -1):
                    if bars[i][0] <= session_date:
                        chosen_i = i
                        break
                out["all_matched"] = False
            else:
                entry["matched_session"] = True

            if chosen_i is None:
                out["quotes"][ticker] = entry
                out["all_matched"] = False
                continue

            close = bars[chosen_i][1]
            as_of = bars[chosen_i][0]
            prev = bars[chosen_i - 1][1] if chosen_i > 0 else None
            entry["ok"] = True
            entry["close"] = close
            entry["as_of"] = as_of.isoformat() if hasattr(as_of, "isoformat") else str(as_of)
            entry["previous_close"] = prev
            if prev not in (None, 0):
                chg = close - prev
                entry["change"] = chg
                entry["change_pct"] = (chg / prev) * 100.0
            if not entry["matched_session"]:
                out["all_matched"] = False
            out["quotes"][ticker] = entry
        except Exception as e:
            logger.warning(f"US session close fetch failed {ticker}: {e}")
            out["quotes"][ticker] = entry
            out["all_matched"] = False
    return out


def _try_ibkr_quote(ticker: str) -> dict[str, Any] | None:
    try:
        from app.core.ibkr.client import fetch_quote, ibkr_market_data_enabled

        if not ibkr_market_data_enabled():
            return None
        payload = fetch_quote(_normalize_ticker(ticker))
        if not payload.get("ok"):
            logger.info(f"IBKR quote miss {ticker}: {payload.get('error')} {payload.get('message')}")
            return None
        data = payload.get("data") or {}
        if data.get("current_price") is None:
            return None
        return data
    except Exception as e:
        logger.warning(f"IBKR quote path error {ticker}: {e}")
        return None


def _quote_dict(ticker: str, *, enrich_vol_atr: bool = True) -> dict[str, Any]:
    """IBKR 優先、失敗時 yfinance。enrich_vol_atr=True で ATR/平均出来高を補完（既定・単一quote向け）。"""
    ib = _try_ibkr_quote(ticker)
    if ib is not None:
        return _merge_vol_atr(ib) if enrich_vol_atr else ib
    return _quote_dict_yf(ticker, enrich_vol_atr=enrich_vol_atr)


def _as_bool(v: Any, default: bool = False) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    if v is None:
        return default
    return bool(v)


def _parse_ticker_list(tickers: Any) -> list[str]:
    if tickers is None:
        return []
    if isinstance(tickers, str):
        s = tickers.strip()
        if not s:
            return []
        if s.startswith("["):
            try:
                parsed = json.loads(s)
                if isinstance(parsed, list):
                    return [str(x).strip() for x in parsed if str(x).strip()]
            except Exception:
                pass
        return [p.strip() for p in s.split(",") if p.strip()]
    if isinstance(tickers, (list, tuple)):
        return [str(x).strip() for x in tickers if str(x).strip()]
    return [str(tickers).strip()] if str(tickers).strip() else []


def _quotes_batch(
    tickers: list[str],
    *,
    prefer_yfinance: bool = False,
    enrich_vol_atr: bool = True,
) -> dict[str, Any]:
    """
    複数銘柄を一括取得。IBKR は1接続でバッチ→欠けは yfinance。
    本番は prefer_yfinance=False + IBKR_MARKET_DATA_TYPE=1 でリアルタイム。
    """
    out: dict[str, Any] = {}
    errors: list[str] = []
    sources: set[str] = set()

    if not tickers:
        return {"quotes": out, "errors": errors, "source": "none"}

    ib_quotes: dict[str, Any] = {}
    if not prefer_yfinance:
        try:
            from app.core.ibkr.client import fetch_quotes, ibkr_market_data_enabled

            if ibkr_market_data_enabled():
                payload = fetch_quotes(tickers)
                if payload.get("ok"):
                    ib_quotes = (payload.get("data") or {}).get("quotes") or {}
                else:
                    errors.append(
                        f"ibkr_batch: {payload.get('error')} {payload.get('message')}"
                    )
        except Exception as e:
            errors.append(f"ibkr_batch: {e}")
            logger.warning(f"quotes batch IBKR failed: {e}")

    for ticker in tickers:
        q = ib_quotes.get(ticker)
        if q and not q.get("error") and q.get("current_price") is not None:
            result = _merge_vol_atr(q) if enrich_vol_atr else q
            out[ticker] = result
            sources.add(str(result.get("source") or "ibkr"))
            continue
        try:
            yq = _quote_dict_yf(ticker, enrich_vol_atr=enrich_vol_atr)
            out[ticker] = yq
            sources.add("yfinance")
            if q and q.get("error"):
                errors.append(f"{ticker}: ibkr={q.get('message')}; used yfinance")
        except Exception as e:
            errors.append(f"{ticker}: {e}")
            out[ticker] = {"ticker": ticker, "error": str(e), "source": "none"}

    if sources == {"ibkr"} or sources == {"ibkr_delayed"}:
        src = next(iter(sources))
    elif sources == {"yfinance"}:
        src = "yfinance"
    else:
        src = "mixed"
    return {"quotes": out, "errors": errors, "source": src}


@tool_registry.register(
    name="get_stock_quote",
    description=(
        "Fetches stock quotes (IBKR live preferred when TWS connected, else Yahoo Finance). "
        "Ticker examples: HDV, AAPL, 7203.T, ^N225, TOPIX. "
        "prefer_yfinance=true で IBKR をスキップ。"
    ),
)
def get_stock_quote(
    ticker: str,
    prefer_yfinance: bool = False,
    enrich_vol_atr: bool = True,
) -> str:
    logger.info(f"Fetching stock quote for {ticker} (yf={prefer_yfinance}, enrich={enrich_vol_atr})")
    try:
        prefer_yfinance = _as_bool(prefer_yfinance, False)
        enrich_vol_atr = _as_bool(enrich_vol_atr, True)

        if prefer_yfinance:
            result = _quote_dict_yf(ticker, enrich_vol_atr=enrich_vol_atr)
        else:
            result = _quote_dict(ticker, enrich_vol_atr=enrich_vol_atr)
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error fetching stock quote for {ticker}: {e}")
        return json.dumps({"error": f"Failed to fetch data for {ticker}. Exception: {e}"})


@tool_registry.register(
    name="get_stock_quotes",
    description=(
        "複数銘柄の株価を一括取得。IBKR ライブ（1接続）優先、不足分は Yahoo。"
        "Market Desk / 本番リアルタイム更新向け。tickers は配列またはカンマ区切り。"
    ),
)
def get_stock_quotes(
    tickers: Any,
    prefer_yfinance: bool = False,
    enrich_vol_atr: bool = True,
) -> str:
    syms = _parse_ticker_list(tickers)
    prefer_yfinance = _as_bool(prefer_yfinance, False)
    enrich_vol_atr = _as_bool(enrich_vol_atr, True)
    logger.info(
        f"Fetching stock quotes batch n={len(syms)} (yf={prefer_yfinance}, enrich={enrich_vol_atr})"
    )
    try:
        return json.dumps(
            _quotes_batch(syms, prefer_yfinance=prefer_yfinance, enrich_vol_atr=enrich_vol_atr),
            ensure_ascii=False,
            indent=2,
        )
    except Exception as e:
        logger.error(f"Error fetching stock quotes batch: {e}")
        return json.dumps({"error": str(e), "quotes": {}, "errors": [str(e)]}, ensure_ascii=False)


def _jp_session_bucket(now: Any | None = None) -> str:
    """東証セッション粗い区分: preopen / morning / lunch / afternoon / closed."""
    from app.core.market_session import get_jp_session_bucket

    return get_jp_session_bucket(now)


def _n225_intraday_levels() -> dict[str, Any]:
    """
    日経平均の当日5分足から前場レンジ／前場終値を抽出。
    後場中に『直近値＝前場終値』と誤認させないための根拠データ。
    前場中は morning_close を確定させない（最終バー＝直近値のため）。
    """
    session = _jp_session_bucket()
    out: dict[str, Any] = {
        "ok": False,
        "session": session,
        "open": None,
        "morning_high": None,
        "morning_low": None,
        "morning_close": None,
        "morning_close_at": None,
        "last": None,
        "last_at": None,
        "previous_close": None,
    }
    try:
        from datetime import timezone, timedelta

        JST = timezone(timedelta(hours=9))
        t = yf.Ticker("^N225")
        info = t.info or {}
        prev = info.get("previousClose")
        if prev is not None:
            out["previous_close"] = float(prev)
        hist = t.history(period="1d", interval="5m")
        if hist is None or hist.empty:
            return out
        morning_rows = []
        last_ts = None
        last_close = None
        for ts, row in hist.iterrows():
            try:
                tsj = ts.tz_convert(JST) if getattr(ts, "tzinfo", None) else ts.replace(tzinfo=JST)
            except Exception:
                continue
            close = float(row["Close"])
            high = float(row["High"])
            low = float(row["Low"])
            open_ = float(row["Open"])
            last_ts, last_close = tsj, close
            if out["open"] is None:
                out["open"] = open_
            if tsj.hour < 11 or (tsj.hour == 11 and tsj.minute <= 30):
                morning_rows.append((tsj, open_, high, low, close))
        if last_close is not None:
            out["last"] = last_close
            out["last_at"] = last_ts.isoformat() if last_ts else None
        if morning_rows:
            out["morning_high"] = max(r[2] for r in morning_rows)
            out["morning_low"] = min(r[3] for r in morning_rows)
            # 前場終了後のみ morning_close を確定（場中は直近バー＝未確定）
            if session in ("lunch", "afternoon", "closed"):
                out["morning_close"] = morning_rows[-1][4]
                out["morning_close_at"] = morning_rows[-1][0].isoformat()
            if out["open"] is None:
                out["open"] = morning_rows[0][1]
            out["ok"] = True
        # previous_close が info に無い場合は日足から
        if out["previous_close"] is None:
            daily = t.history(period="5d")
            if daily is not None and len(daily) >= 2:
                out["previous_close"] = float(daily["Close"].iloc[-2])
    except Exception as e:
        logger.warning(f"N225 intraday levels failed: {e}")
    return out


def get_jp_market_snapshot(
    include_sectors: bool = True,
    prefer_yfinance: bool = False,
) -> dict[str, Any]:
    """
    日経・TOPIX・主要業種ETFの直近値（場中）または終値（引け後）と前日比をまとめて返す。
    既定は IBKR バッチ優先、欠けた銘柄は yfinance。
    prefer_yfinance=True または IBKR_MARKET_DATA=0 なら Yahoo のみ（Error 10089 回避）。
    """
    include_sectors = _as_bool(include_sectors, True)
    prefer_yfinance = _as_bool(prefer_yfinance, False)

    out: dict[str, Any] = {
        "indices": {},
        "sectors": {},
        "errors": [],
        "source": "mixed",
        "session": _jp_session_bucket(),
        "n225_intraday": {},
    }
    symbols = list(JP_INDEX_TICKERS.keys())
    if include_sectors:
        symbols.extend(JP_SECTOR_ETFS.keys())

    ib_quotes: dict[str, Any] = {}
    try:
        from app.core.ibkr.client import fetch_quotes, ibkr_market_data_enabled

        if not prefer_yfinance and ibkr_market_data_enabled():
            payload = fetch_quotes(symbols)
            if payload.get("ok"):
                ib_quotes = (payload.get("data") or {}).get("quotes") or {}
                out["source"] = "ibkr"
            else:
                out["errors"].append(f"ibkr_batch: {payload.get('error')} {payload.get('message')}")
    except Exception as e:
        out["errors"].append(f"ibkr_batch: {e}")
        logger.warning(f"JP snapshot IBKR batch failed: {e}")

    sources_used = set()

    def _fill(bucket: str, mapping: dict[str, str]) -> None:
        for ticker, label in mapping.items():
            q = ib_quotes.get(ticker)
            if q and not q.get("error") and q.get("current_price") is not None:
                q = dict(q)
                q["label"] = label
                out[bucket][ticker] = q
                sources_used.add(q.get("source") or "ibkr")
                continue
            try:
                yq = _quote_dict_yf(ticker, enrich_vol_atr=False)
                yq["label"] = label
                out[bucket][ticker] = yq
                sources_used.add("yfinance")
                if q and q.get("error"):
                    out["errors"].append(f"{ticker}: ibkr={q.get('message')}; used yfinance")
            except Exception as e:
                out["errors"].append(f"{ticker}: {e}")
                logger.warning(f"JP snapshot failed {ticker}: {e}")

    _fill("indices", JP_INDEX_TICKERS)
    if include_sectors:
        _fill("sectors", JP_SECTOR_ETFS)

    out["n225_intraday"] = _n225_intraday_levels()

    if sources_used == {"ibkr"}:
        out["source"] = "ibkr"
    elif sources_used == {"yfinance"}:
        out["source"] = "yfinance"
    else:
        out["source"] = "mixed"
    return out


@tool_registry.register(
    name="get_jp_market_snapshot",
    description=(
        "日本市場の日経平均・TOPIX・主要業種ETF（銀行/金融/電機/医薬）の直近値/終値と前日比を一括取得。"
        "場中は終値ではない（session を確認）。IBKR 優先（TWS 接続時）、不足分は Yahoo。"
        "prefer_yfinance=true で IBKR をスキップ（購読エラー 10089 回避・Market Desk 向け）。"
    ),
)
def get_jp_market_snapshot_tool(
    include_sectors: bool = True,
    prefer_yfinance: bool = False,
) -> str:
    try:
        return json.dumps(
            get_jp_market_snapshot(
                include_sectors=_as_bool(include_sectors, True),
                prefer_yfinance=_as_bool(prefer_yfinance, False),
            ),
            ensure_ascii=False,
            indent=2,
        )
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def _fmt_pct(q: dict[str, Any]) -> str:
    price = q.get("current_price")
    chg = q.get("change")
    pct = q.get("change_pct")
    if price is None:
        return "取得失敗"
    parts = [f"{price:,.2f}" if isinstance(price, (int, float)) else str(price)]
    if chg is not None and pct is not None:
        sign = "+" if chg >= 0 else ""
        parts.append(f"{sign}{chg:,.2f}（{sign}{pct:.2f}%）")
    return " ".join(parts)


def _fmt_px(v: Any) -> str:
    if v is None:
        return "未確認"
    try:
        return f"{float(v):,.2f}"
    except (TypeError, ValueError):
        return str(v)


def format_jp_market_snapshot_for_prompt(user_input: str = "") -> str:
    """
    検索結果先頭に注入する確定数値ブロック。
    チャット注入は常に Yahoo 即時（IBKR 不通待ちでスマホ応答が途切れないようにする）。
    セッション別に『前場終値』と『直近値』を分離して誤認を防ぐ。
    """
    snap = get_jp_market_snapshot(include_sectors=True, prefer_yfinance=True)
    src = snap.get("source") or "mixed"
    session = snap.get("session") or _jp_session_bucket()
    intra = snap.get("n225_intraday") or {}
    lines = [
        f"【市場スナップショット source={src} session={session}（推測禁止・この数値を優先）】",
        "※ TOPIX・業種別騰落がここに無い／取得失敗の場合は推測で埋めず『未確認』と書くこと。",
    ]
    if session in ("morning", "preopen"):
        lines.append(
            "※【P0】場中/寄り前: 『終値』『前場終値』『大引け』禁止。数値は直近値/現在値として述べよ。"
        )
    else:
        lines.append(
            "※ 『直近値』を『前場終値』と言い換えてはいけない。前場質問には morning_close のみを前場終値として使うこと。"
        )

    if intra.get("ok"):
        prev = intra.get("previous_close")
        m_close = intra.get("morning_close")
        m_chg = None
        m_pct = None
        if m_close is not None and prev not in (None, 0):
            m_chg = float(m_close) - float(prev)
            m_pct = (m_chg / float(prev)) * 100.0
        lines.append("日経平均（5分足から抽出・優先）:")
        lines.append(f"- 前日終値: {_fmt_px(prev)}")
        lines.append(f"- 始値: {_fmt_px(intra.get('open'))}")
        lines.append(
            f"- 前場高値/安値: {_fmt_px(intra.get('morning_high'))} / {_fmt_px(intra.get('morning_low'))}"
        )
        # 前場終値は lunch 以降かつ morning_close が確定しているときだけ
        if m_close is not None and session in ("lunch", "afternoon", "closed"):
            m_line = f"- 前場終値 (morning_close @{intra.get('morning_close_at')}): {_fmt_px(m_close)}"
            if m_chg is not None and m_pct is not None:
                sign = "+" if m_chg >= 0 else ""
                m_line += f" {sign}{m_chg:,.2f}（{sign}{m_pct:.2f}%）"
            lines.append(m_line)
        if session in ("afternoon", "closed"):
            last_label = (
                f"- 終値 (大引け確定 @{intra.get('last_at')}): {_fmt_px(intra.get('last'))}"
                if session == "closed"
                else f"- 直近値 (後場取引中・本日終値ではない @{intra.get('last_at')}): {_fmt_px(intra.get('last'))}"
            )
            lines.append(last_label)
            if session == "afternoon":
                lines.append("※ 後場中は直近値≠前場終値≠本日終値。前場の話では morning_close を使え。")
        elif session == "lunch":
            lines.append("※ 昼休み中。morning_close を前場終値の確定値として明示してよい。本日終値は未確定。")
        elif session in ("morning", "preopen"):
            lines.append(
                f"- 直近値 (前場取引中・終値でも前場終値でもない @{intra.get('last_at')}): {_fmt_px(intra.get('last'))}"
            )
            lines.append(
                "※【P0】前場中/寄り前は『終値』『前場終値』『大引け』と呼ぶな。必ず直近値/現在値。"
            )
    else:
        lines.append("日経平均のセッション別価格抽出に失敗。指数の直近のみ参考（終値としては使わない）:")

    for ticker, q in (snap.get("indices") or {}).items():
        label = q.get("label") or ticker
        lines.append(f"- {label} ({ticker}) 直近: {_fmt_pct(q)}")
    lines.append("主要業種ETF（参考・東証業種代理・直近）:")
    for ticker, q in (snap.get("sectors") or {}).items():
        label = q.get("label") or ticker
        lines.append(f"- {label} ({ticker}): {_fmt_pct(q)}")
    errs = snap.get("errors") or {}
    if isinstance(errs, list) and errs:
        lines.append("取得エラー: " + "; ".join(errs[:5]))
    return "\n".join(lines) + "\n"
