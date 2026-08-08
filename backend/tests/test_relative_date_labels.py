"""相対語（明日/あさって）と絶対日の不一致補正テスト。"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.fact_filters.temporal import fix_relative_date_labels
from app.core.market_calendar import format_market_status
import datetime


def test_ashita_plus_two_days_becomes_asatte():
    today = date(2026, 7, 29)
    raw = "明日7月31日の日銀金融政策決定会合が最大の焦点です。"
    fixed = fix_relative_date_labels(raw, today=today)
    assert "あさって7月31日" in fixed
    assert "明日7月31日" not in fixed


def test_correct_ashita_unchanged():
    today = date(2026, 7, 29)
    raw = "明日7月30日に発表予定です。"
    assert fix_relative_date_labels(raw, today=today) == raw


def test_correct_asatte_unchanged():
    today = date(2026, 7, 29)
    raw = "あさって7月31日の会合を控えています。"
    assert fix_relative_date_labels(raw, today=today) == raw


def test_ashita_far_future_strips_relative():
    today = date(2026, 7, 29)
    raw = "明日8月5日に予定されています。"
    fixed = fix_relative_date_labels(raw, today=today)
    assert "明日" not in fixed
    assert "8月5日" in fixed


def test_ashita_with_connector_mid():
    today = date(2026, 7, 29)
    raw = "明日の7月31日会合"
    fixed = fix_relative_date_labels(raw, today=today)
    assert "あさって" in fixed
    assert "7月31日" in fixed
    assert "明日" not in fixed


def test_format_market_status_has_relative_anchor():
    jst = datetime.timezone(datetime.timedelta(hours=9))
    dt = datetime.datetime(2026, 7, 29, 13, 0, tzinfo=jst)
    text = format_market_status(dt)
    assert "相対日付対応表" in text
    assert "今日=2026/07/29" in text
    assert "明日=2026/07/30" in text
    assert "あさって=2026/07/31" in text
