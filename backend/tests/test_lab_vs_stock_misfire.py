"""献血検査表が株検索・soft-US に誤発火しないことの回帰テスト。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.chat_search import (
    balance_search_queries,
    extract_us_company_search_seeds,
    is_medical_lab_context,
    is_soft_us_single_stock_query,
)
from app.core.search_planner import _market_today_shortcut

LAB_PASTE = """献血したんだけど、採決結果どう思う？血圧・脈拍
2回前
2025/11/26
1回前
2026/3/27
最新
2026/7/30
血圧（最高）
99	104	108
血圧（最低）
66	76	71
脈拍
79	79	99
生化学検査
ALT（GPT）
13	17	13
γ-GTP
11	13	14
総蛋白　TP
7.1	7.6	7.1
アルブミン　ALB
4.7	4.9	4.5
コレステロール　CHOL
161	184	171
グリコアルブミン　GA
12.9	12.2	12.6
血球計数検査
赤血球数　RBC
516	549	518
ヘモグロビン量　Hb
15.7	16.8	16.0
白血球数　WBC
58	65	73
血小板数　PLT
24.5	23.8	23.7
"""

ROUTE_A = "Googleなにかいいニュースあったのかな?決算で下げてたけど、今日めっちゃ上がったみたいだね"


def test_medical_lab_context_detected():
    assert is_medical_lab_context(LAB_PASTE) is True
    assert is_medical_lab_context(ROUTE_A) is False


def test_lab_paste_yields_no_company_seeds():
    assert extract_us_company_search_seeds(LAB_PASTE) == []


def test_lab_paste_not_soft_us():
    assert is_soft_us_single_stock_query(LAB_PASTE) is False


def test_lab_paste_shortcut_none():
    out = _market_today_shortcut(LAB_PASTE, "2026-08-01", "August 1, 2026")
    assert out is None


def test_lab_paste_balance_no_stock_queries():
    _needed, qs = balance_search_queries(LAB_PASTE, False, ["検査結果の見方"])
    blob = " ".join(qs).lower()
    assert "wall street" not in blob
    assert "stock news" not in blob
    assert "why up" not in blob
    assert "nasdaq" not in blob
    # soft-US 全置換されていない
    assert qs == ["検査結果の見方"]


def test_google_soft_us_still_works():
    assert is_soft_us_single_stock_query(ROUTE_A) is True
    seeds = extract_us_company_search_seeds(ROUTE_A)
    assert any(s["ticker"] == "GOOGL" for s in seeds)
    needed, qs = balance_search_queries(ROUTE_A, False, ["noise"])
    assert needed is True
    blob = " ".join(qs)
    assert "GOOGL" in blob or "Alphabet" in blob
    assert "why up" in blob.lower()


def test_metabo_does_not_seed_meta():
    # メタボ ≠ Meta
    assert extract_us_company_search_seeds("メタボが気になる健康診断だった") == []


def test_meta_stock_still_seeds():
    seeds = extract_us_company_search_seeds("Meta株どう？今日下がったみたい")
    assert any(s["ticker"] == "META" for s in seeds)


def test_bare_ticker_without_finance_cue_ignored():
    # 金融手がかりなしの ALT 単独はシードにしない
    assert extract_us_company_search_seeds("ALT is high in this report") == []


def test_bare_ticker_with_stock_cue_allowed_unless_lab_deny():
    # 金融手がかりあってもラボ略語は拒否
    assert extract_us_company_search_seeds("ALT株どう？") == []
    # 実在ティッカーは許可
    seeds = extract_us_company_search_seeds("IBM株どう？今日上がった")
    assert any(s["ticker"] == "IBM" for s in seeds)
