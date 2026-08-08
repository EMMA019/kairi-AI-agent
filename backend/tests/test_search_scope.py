"""検索スコープ・鮮度・市場ショートサーキットのテスト。"""
from app.core.chat_search import balance_search_queries, should_skip_deep_fetch
from app.core.search_planner import _market_today_shortcut
from app.core.search.reranker import rerank, _freshness_score, _jp_market_noise_penalty


def test_japan_market_does_not_add_us_etf():
    needed, queries = balance_search_queries(
        "今日の日本市場はどうだった？",
        search_needed=True,
        search_queries=["東京株式市場 今日"],
    )
    assert needed is True
    blob = " ".join(queries).lower()
    assert "us japan stock dividend" not in blob
    assert any("日経" in q or "東京" in q for q in queries)
    assert any("TOPIX" in q for q in queries)
    # 引け後は業種クエリを夜間先物に差し替える場合あり
    assert any("業種" in q or "先物" in q for q in queries)
    assert len(queries) >= 3


def test_japan_finance_followup_queries():
    needed, queries = balance_search_queries(
        "金融セクターとか好調じゃない？ TOPIXは？",
        search_needed=True,
        search_queries=["セクターローテーション"],
    )
    assert needed is True
    blob = " ".join(queries)
    assert "TOPIX" in blob or "業種" in blob or "銀行" in blob


def test_us_market_does_not_add_japan_etf_mix():
    needed, queries = balance_search_queries(
        "米国市場は7/27はどう動くと思う？",
        search_needed=True,
        search_queries=["US stock market"],
    )
    assert needed is True
    blob = " ".join(queries)
    assert "US Japan stock dividend ETF market outlook 2026" not in blob


def test_market_today_shortcut_japan():
    out = _market_today_shortcut("今日の日本市場はどうだった？", "2026-07-27", "July 27, 2026")
    assert out is not None
    assert out["needs_search"] is True
    assert out["category"] == "finance"
    assert any("日経" in q for q in out["search_queries"])
    assert any("TOPIX" in q for q in out["search_queries"])
    assert any("業種" in q or "先物" in q for q in out["search_queries"])


def test_japan_morning_session_is_todayish():
    needed, queries = balance_search_queries(
        "7/29の日本市場前場がどんな感じだった？",
        search_needed=True,
        search_queries=["7月29日 日経平均 前場"],
    )
    assert needed is True
    blob = " ".join(queries)
    assert "日経" in blob
    assert "TOPIX" in blob
    assert "us japan stock dividend" not in blob.lower()


def test_market_today_shortcut_morning():
    out = _market_today_shortcut(
        "7/29の日本市場前場がどんな感じだった？",
        "2026-07-29",
        "July 29, 2026",
    )
    assert out is not None
    assert any("前場" in q for q in out["search_queries"])
    assert "tavily" in out["providers"]
    assert "brave" in out["providers"]
    assert "news" in out["providers"]


def test_explicit_us_date_not_overwritten_by_jst_today(monkeypatch):
    """JSTが7/30でも『7/29の米国市場』は7/29クエリになる。"""
    from datetime import datetime
    from app.core.chat_search import JST, balance_search_queries
    from app.core import chat_search as cs

    fake_now = datetime(2026, 7, 30, 6, 48, tzinfo=JST)

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fake_now.replace(tzinfo=None)
            return fake_now.astimezone(tz)

    monkeypatch.setattr(cs, "datetime", _FixedDatetime)

    needed, queries = balance_search_queries(
        "7/29の米国市場ってどうだった？",
        search_needed=True,
        search_queries=["junk"],
    )
    assert needed is True
    blob = " ".join(queries)
    assert "2026-07-29" in blob or "July 29" in blob
    assert "2026-07-30" not in blob
    assert "July 30" not in blob

    out = _market_today_shortcut(
        "7/29の米国市場ってどうだった？",
        "2026-07-30",
        "July 30, 2026",
    )
    assert out is not None
    qblob = " ".join(out["search_queries"])
    assert "2026-07-29" in qblob or "July 29" in qblob
    assert "2026-07-30" not in qblob
    assert "tavily" in out["providers"]


def test_us_anchor_without_date_uses_last_et_session():
    from datetime import datetime
    from app.core.chat_search import JST, resolve_market_anchor_date

    # JST 7/30 06:48 = ET 7/29 17:48 after hours → last session 7/29
    now = datetime(2026, 7, 30, 6, 48, tzinfo=JST)
    d = resolve_market_anchor_date("米国市場どうだった？", market="us", now_jst=now)
    assert d.isoformat() == "2026-07-29"


def test_jp_today_queries_use_live_price_word_during_morning(monkeypatch):
    """場中は検索クエリに『終値』を硬直指定しない。"""
    from datetime import datetime
    from app.core.chat_search import JST, balance_search_queries
    from app.core import chat_search as cs

    fake_now = datetime(2026, 7, 30, 11, 0, tzinfo=JST)

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fake_now.replace(tzinfo=None)
            return fake_now.astimezone(tz)

    monkeypatch.setattr(cs, "datetime", _FixedDatetime)
    needed, queries = balance_search_queries(
        "日本市場今日はどう？",
        search_needed=True,
        search_queries=["junk"],
    )
    assert needed is True
    blob = " ".join(queries)
    assert "現在値" in blob
    assert "日経平均 終値" not in blob


def test_jp_evening_queries_include_night_futures(monkeypatch):
    from datetime import datetime
    from app.core.chat_search import JST, balance_search_queries
    from app.core import chat_search as cs

    fake_now = datetime(2026, 7, 30, 18, 42, tzinfo=JST)

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fake_now.replace(tzinfo=None)
            return fake_now.astimezone(tz)

    monkeypatch.setattr(cs, "datetime", _FixedDatetime)
    _, queries = balance_search_queries(
        "日本市場今日はどうだった?",
        search_needed=True,
        search_queries=["junk"],
    )
    blob = " ".join(queries)
    assert "終値" in blob
    assert "日経225先物 夜間取引" in blob


def test_skip_deep_fetch_for_close():
    assert should_skip_deep_fetch("今日の日本市場はどうだった？") is True
    assert should_skip_deep_fetch("7/29の日本市場前場") is True
    assert should_skip_deep_fetch("Pythonの書き方教えて") is False


def test_rerank_prefers_fresh_date():
    query = "今日の日本市場 終値"
    results = [
        {
            "title": "Stocks Sink in Broad AI Rout Sparked by China's DeepSeek - WSJ",
            "snippet": "January 27, 2025 AI stocks plunged after DeepSeek news.",
            "url": "https://www.wsj.com/old-deepseek",
        },
        {
            "title": "日経平均大引け 反発 320円高の6万4931円 - 日本経済新聞",
            "snippet": "2026年7月27日の東京株式市場。日経平均は終値6万4931円。",
            "url": "https://www.nikkei.com/today-close",
        },
    ]
    ranked = rerank(query, results, top_k=2)
    assert ranked[0]["url"] == "https://www.nikkei.com/today-close"
    fresh = _freshness_score(query, results[1]["title"], results[1]["snippet"])
    stale = _freshness_score(query, results[0]["title"], results[0]["snippet"])
    assert fresh > stale


def test_rerank_demotes_stale_ath_headline():
    query = "7/29 日本市場 前場 日経平均"
    results = [
        {
            "title": "日経平均株価、最高値更新　終値1636円高の6万6329円に反発 - 日本経済新聞",
            "snippet": "2026年5月22日の東京株式市場。日経平均は大幅続伸。",
            "url": "https://www.nikkei.com/old-ath",
        },
        {
            "title": "日経平均前場 続落 半導体売り - 東京株式市場",
            "snippet": "2026年7月29日 前場の東京株式。日経平均は売り優勢。",
            "url": "https://www.nikkei.com/today-morning",
        },
        {
            "title": "Stocks making the biggest moves premarket: Micron, Exxon",
            "snippet": "Premarket movers after hours.",
            "url": "https://www.cnbc.com/premarket-junk",
        },
    ]
    ranked = rerank(query, results, top_k=3)
    assert ranked[0]["url"] == "https://www.nikkei.com/today-morning"

    query = "今日の日本市場 日経平均 終値"
    results = [
        {
            "title": "Mortgage and refinance interest rates today, Sunday, July 26, 2026: Rates up",
            "snippet": "Best mortgage rates. CD rates provide 4.20% APY.",
            "url": "https://example.com/mortgage",
        },
        {
            "title": "日経平均大引け 反発 — 東京株式市場",
            "snippet": "2026年7月27日 日経平均終値とTOPIX。東証業種別も発表。",
            "url": "https://www.nikkei.com/market",
        },
        {
            "title": "Best CD rates today: Lock in up to 4.20% APY",
            "snippet": "Highest savings APY this year.",
            "url": "https://example.com/cd-rates",
        },
    ]
    ranked = rerank(query, results, top_k=3)
    assert ranked[0]["url"] == "https://www.nikkei.com/market"
    assert _jp_market_noise_penalty(query, results[0]["title"], results[0]["snippet"]) < -20
