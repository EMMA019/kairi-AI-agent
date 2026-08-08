"""キャッシュ正規化・LLM bypass 判定の単体テスト。"""
from app.core.cache_manager import _normalize_query, should_bypass_llm_cache


def test_normalize_oshiete_collapses_with_news():
    a = _normalize_query("最新ニュースを教えて")
    b = _normalize_query("ニュース教えて")
    c = _normalize_query("ニュース")
    assert a == b == c


def test_normalize_keeps_topic_token():
    assert _normalize_query("天気教えて") == _normalize_query("天気")
    assert "天気" in _normalize_query("天気教えて") or _normalize_query("天気教えて") == _normalize_query("天気")


def test_bypass_not_triggered_by_oshiete_alone():
    bypass, reason = should_bypass_llm_cache(
        search_needed=False,
        category="general",
        user_input="天気教えて",
    )
    assert bypass is False
    assert reason == ""


def test_bypass_on_search_needed():
    bypass, reason = should_bypass_llm_cache(
        search_needed=True,
        category="general",
        user_input="天気教えて",
    )
    assert bypass is True
    assert reason == "search_needed"


def test_bypass_on_finance_category():
    bypass, reason = should_bypass_llm_cache(
        search_needed=False,
        category="finance",
        user_input="どう思う？",
    )
    assert bypass is True
    assert "category" in reason


def test_bypass_on_market_keyword_not_short_kabu():
    bypass, _ = should_bypass_llm_cache(
        search_needed=False,
        category="general",
        user_input="今日の株価どう？",
    )
    assert bypass is True
    # 短い「株」だけを含む一般文は bypass しない
    bypass2, _ = should_bypass_llm_cache(
        search_needed=False,
        category="general",
        user_input="株式会社のロゴ案を考えて",
    )
    assert bypass2 is False
