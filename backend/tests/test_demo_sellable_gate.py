"""
売れる水準デモ4本のゲート（P1）。
個別テストは各ファイルに残し、ここは「デモが壊れたらここで落ちる」要約ゲート。
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.chat_search import (
    JST,
    balance_search_queries,
    build_us_market_search_queries,
    extract_us_company_search_seeds,
    is_soft_us_single_stock_query,
)
from app.core.fact_filters.markup import looks_like_tool_dump, strip_tool_dump_blocks
from app.core.market_session import get_us_session_bucket, us_session_is_live
from app.core.search_planner import _market_today_shortcut


LAB_PASTE = (
    "献血したんだけど、採決結果どう思う？血圧・脈拍\n"
    "ALT（GPT）\n"
    "2026/7/30\n"
    "RBC 518"
)
GOOGLE_MOVE = "Googleなにかあった？今日上がった？"
US_TODAY = "今日の米国市場どう？"
TOOL_DUMP = """GOOGLは上昇しました。

[Local Tool: get_stock_quote]
{"ticker": "GOOGL"}

【一般検索結果: Alphabet why up】
[1] [tavily] news
"""


def test_demo1_us_market_today_shortcut_and_session():
    """デモ1: 今日の米国市場 → ショートカット＋セッション日付整合。"""
    out = _market_today_shortcut(US_TODAY, "2026-08-01", "August 1, 2026")
    assert out is not None
    assert out.get("needs_search") is True
    qs = out.get("search_queries") or []
    assert qs, "expected US market search queries"
    blob = " ".join(qs).lower()
    assert "wall street" in blob or "dow" in blob or "nasdaq" in blob or "s&p" in blob

    open_jst = datetime(2026, 7, 31, 23, 56, tzinfo=JST)
    post_jst = datetime(2026, 8, 1, 6, 0, tzinfo=JST)
    assert get_us_session_bucket(open_jst) == "open"
    assert us_session_is_live(open_jst) is True
    assert get_us_session_bucket(post_jst) == "post_market"
    assert us_session_is_live(post_jst) is False

    live_qs = build_us_market_search_queries(US_TODAY, now_jst=open_jst)
    settled_qs = build_us_market_search_queries(US_TODAY, now_jst=post_jst)
    live_blob = " ".join(live_qs).lower()
    settled_blob = " ".join(settled_qs).lower()
    assert "wall street closes" not in live_blob
    assert "close" in settled_blob or "closes" in settled_blob or "wall street" in settled_blob


def test_demo2_google_soft_us_quote_path():
    """デモ2: Googleなにかあった → soft-US + why-up クエリ。"""
    assert is_soft_us_single_stock_query(GOOGLE_MOVE) is True
    needed, qs = balance_search_queries(GOOGLE_MOVE, False, ["noise"])
    assert needed is True
    blob = " ".join(qs).lower()
    assert "googl" in blob or "alphabet" in blob or "google" in blob
    assert "why up" in blob or "news" in blob or "catalyst" in blob or "rally" in blob

    out = _market_today_shortcut(GOOGLE_MOVE, "2026-08-01", "August 1, 2026")
    assert out is not None
    assert out["needs_search"] is True


def test_demo3_lab_results_not_stock_search():
    """デモ3: 献血結果 → 株検索に化けない。"""
    assert extract_us_company_search_seeds(LAB_PASTE) == []
    assert is_soft_us_single_stock_query(LAB_PASTE) is False
    needed, qs = balance_search_queries(LAB_PASTE, False, [])
    blob = " ".join(qs).lower()
    assert "googl" not in blob
    assert "dow jones" not in blob
    assert "wall street" not in blob
    # 検索が要る場合でも金融クエリに化けるべきではない
    if needed:
        assert "alt stock" not in blob


def test_demo4_no_tool_dump_in_body():
    """デモ4: ツール生ダンプが本文に残らない。"""
    assert looks_like_tool_dump(TOOL_DUMP) is True
    cleaned = strip_tool_dump_blocks(TOOL_DUMP)
    assert "Local Tool" not in cleaned
    assert "一般検索結果" not in cleaned
    assert "tavily" not in cleaned.lower()
    assert "GOOGLは上昇" in cleaned


def test_demo_docs_and_packaging_scripts_exist():
    root = Path(__file__).resolve().parents[2]
    assert (root / "scripts" / "prepare_embedded_python.ps1").is_file()
    assert (root / "start_kairi.bat").is_file()
    bat = (root / "start_kairi.bat").read_text(encoding="utf-8", errors="ignore")
    assert "runtime\\python" in bat or "runtime\\python\\python.exe" in bat
