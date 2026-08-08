"""場中終値誤認・夜間先物時間軸の単体テスト。"""
from datetime import datetime
from unittest.mock import patch

from app.core.market_session import (
    JST,
    get_jp_session_bucket,
    get_ose_night_futures_phase,
    get_tse_market_session_context,
    jp_cash_price_query_word,
)
from app.core.tools.market_data import format_jp_market_snapshot_for_prompt
from app.core.fact_filters.financial import (
    correct_jp_session_price_labels,
    soften_stale_night_futures_claims,
)


def test_session_bucket_morning_and_closed():
    assert get_jp_session_bucket(datetime(2026, 7, 30, 11, 0, tzinfo=JST)) == "morning"
    assert get_jp_session_bucket(datetime(2026, 7, 30, 18, 42, tzinfo=JST)) == "closed"
    assert get_jp_session_bucket(datetime(2026, 7, 30, 12, 0, tzinfo=JST)) == "lunch"


def test_price_query_word_avoids_close_during_session():
    assert jp_cash_price_query_word(datetime(2026, 7, 30, 11, 0, tzinfo=JST)) == "現在値"
    assert jp_cash_price_query_word(datetime(2026, 7, 30, 13, 0, tzinfo=JST)) == "現在値"
    assert jp_cash_price_query_word(datetime(2026, 7, 30, 12, 0, tzinfo=JST)) == "前場終値"
    assert jp_cash_price_query_word(datetime(2026, 7, 30, 16, 0, tzinfo=JST)) == "終値"


def test_ose_night_phase_evening_vs_morning():
    assert get_ose_night_futures_phase(datetime(2026, 7, 30, 6, 0, tzinfo=JST)) == "night_just_ended"
    assert get_ose_night_futures_phase(datetime(2026, 7, 30, 18, 42, tzinfo=JST)) == "night_active"
    assert get_ose_night_futures_phase(datetime(2026, 7, 30, 15, 45, tzinfo=JST)) == "evening_pre_night"


def test_morning_context_forbids_close_label():
    fake_now = datetime(2026, 7, 30, 11, 0, tzinfo=JST)

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fake_now.replace(tzinfo=None)
            return fake_now.astimezone(tz)

    with patch("app.core.market_session.datetime", _FixedDatetime):
        with patch("app.core.market_session.is_tse_holiday", return_value=False):
            ctx = get_tse_market_session_context("日経平均どう？")
    assert "前場" in ctx
    assert "終値誤認禁止" in ctx or "前場終値" in ctx and "禁止" in ctx


def test_evening_context_warns_stale_night_futures():
    fake_now = datetime(2026, 7, 30, 18, 42, tzinfo=JST)

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fake_now.replace(tzinfo=None)
            return fake_now.astimezone(tz)

    with patch("app.core.market_session.datetime", _FixedDatetime):
        with patch("app.core.market_session.is_tse_holiday", return_value=False):
            ctx = get_tse_market_session_context("日本市場今日はどうだった?")
    assert "夜間" in ctx
    assert "スタート" in ctx or "直前夜間" in ctx


def test_snapshot_morning_does_not_emit_morning_close_label():
    fake_intra = {
        "ok": True,
        "session": "morning",
        "open": 61258.0,
        "morning_high": 62924.0,
        "morning_low": 61201.0,
        "morning_close": None,
        "morning_close_at": None,
        "last": 62810.09,
        "last_at": "2026-07-30T11:00:00+09:00",
        "previous_close": 61434.0,
    }
    fake_snap = {
        "source": "yfinance",
        "session": "morning",
        "n225_intraday": fake_intra,
        "indices": {
            "^N225": {
                "label": "日経平均",
                "current_price": 62810.09,
                "change": 1376.0,
                "change_pct": 2.24,
            }
        },
        "sectors": {},
        "errors": [],
    }
    with patch("app.core.tools.market_data.get_jp_market_snapshot", return_value=fake_snap):
        with patch("app.core.tools.market_data._jp_session_bucket", return_value="morning"):
            text = format_jp_market_snapshot_for_prompt("日経どう？")
    assert "- 前場終値" not in text
    assert "直近値" in text
    assert "終値でも前場終値でもない" in text or "場中/寄り前" in text


def test_correct_jp_session_price_labels_morning():
    src = "【市場スナップショット source=yf session=morning】\n- 直近値: 62,810"
    text = "本日の日経平均は前場終値62,810.09（+2.24%）と大幅高です。"
    out = correct_jp_session_price_labels(text, src)
    assert "前場終値" not in out
    assert "直近値（前場取引中）" in out


def test_soften_stale_night_futures_evening():
    src = (
        "日経225先物：30日夜間取引終値＝1410円安、6万1040円\n"
        "日経225先物：30日0時＝590円安、6万1860円"
    )
    text = (
        "本日30日夜間取引（大阪取引所）では、前日比1,410円安の6万1,040円でスタートしています。"
    )
    out = soften_stale_night_futures_claims(text, src)
    assert "でスタートしています" not in out
    assert "直前の夜間セッション終値" in out
