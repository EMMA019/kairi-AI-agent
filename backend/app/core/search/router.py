"""検索ルーター — 天気・Wikipedia・Brave・ニュースDBの統合"""
import re
from app.utils.logger import get_logger
from .providers.wikipedia import search_wikipedia
from .providers.brave import search_brave
from .providers.tavily import search_tavily
from .providers.jina import fetch_with_jina, search_jina
from .providers.weather import get_weather, format_weather_for_prompt
from .cache import cache
from .formatter import format_results

logger = get_logger(__name__)


def _extract_place(query: str) -> str:
    """天気クエリから地名を抽出（簡易版）"""
    WEATHER_KEYWORDS = ["天気", "気温", "天候", "雨", "晴れ", "曇り", "雪", "forecast"]
    for kw in WEATHER_KEYWORDS:
        query = query.replace(kw, "")
    return query.strip() or "東京"


async def search(query: str, providers: list[str] = None) -> list[dict]:
    """
    クエリ内容に応じて指定されたプロバイダーで検索を実行。
    """
    if providers is None:
        providers = ["brave"]
        
    combined_results = []

    # 1. 天気クエリ
    if "weather" in providers:
        place = _extract_place(query)
        cached = cache.get(place, "weather")
        if cached:
            combined_results.extend(cached)
        else:
            weather = await get_weather(place)
            if weather:
                result = [{
                    "title": f"{place}の天気", 
                    "snippet": format_weather_for_prompt(weather),
                    "url": "", 
                    "source": "open-meteo"
                }]
                cache.set(place, result, "weather")
                combined_results.extend(result)

    # 2. Wikipediaで答えられそうなクエリ
    if "wikipedia" in providers:
        cached = cache.get(query, "wiki")
        if cached:
            combined_results.extend(cached)
        else:
            results = await search_wikipedia(query)
            if results:
                formatted = format_results(results, query)
                cache.set(query, formatted, "wiki")
                combined_results.extend(formatted)

    # 3. ニュースクエリ (オンデマンド1次情報取得)
    # 日付フィルタを自動付与（市場・今日系は2日前、通常は7日前）
    from datetime import datetime as _dt, timedelta as _td
    _market_fresh = any(
        kw in (query or "")
        for kw in ("市場", "株", "市況", "終値", "大引け", "今日", "本日", "相場", "market", "today", "close", "Dow", "日経")
    )
    _lookback = 2 if _market_fresh else 7
    _start_date = (_dt.now() - _td(days=_lookback)).strftime("%Y-%m-%d")
    _date_filtered_query = f"{query} after:{_start_date}" if query and "after:" not in query else query
    if "news" in providers:
        from app.core.news.fetcher import fetch_primary_news
        from app.core.news.database import (
            search_news_ranked,
            filter_news_by_freshness,
            rank_news_items_for_chat,
        )
        from app.core.cache_manager import get_search_cache, set_search_cache

        # キャッシュチェック（30分TTL）
        cache_key = f"news_{query}" if query else "news_headlines"
        cached = await get_search_cache(cache_key, providers, max_age_seconds=1800)
        if cached:
            logger.info(f"✅ ニュースキャッシュヒット: {cache_key}")
            combined_results.extend(cached.get("sources", []))
        else:
            formatted_news = []
            seen_urls: set[str] = set()
            pool_hits = 0

            # 1) ローリングプール優先（レーダー蓄積・スコア済み）
            try:
                pool_items = await search_news_ranked(
                    query, limit=10, max_age_days=_lookback
                )
                for r in pool_items:
                    url = (r.get("url") or "").strip()
                    if url and url in seen_urls:
                        continue
                    if url:
                        seen_urls.add(url)
                    pub = (r.get("published") or r.get("fetched_at") or "").strip()
                    item = {
                        "title": r.get("title", ""),
                        "snippet": (r.get("summary") or r.get("verified_fact") or "")[:500],
                        "url": url,
                        "source": f"POOL ({r.get('source', 'news.db')})",
                        "importance": r.get("importance", 0),
                    }
                    if pub:
                        item["published"] = pub
                    formatted_news.append(item)
                    pool_hits += 1
                if pool_hits:
                    logger.info(f"✅ ニュースプールヒット: {pool_hits}件")
            except Exception as e:
                logger.warning(f"ニュースプール検索失敗（ライブRSSへ）: {e}")

            # 2) 薄いときだけライブ RSS（鮮度フィルタ＋スコア）
            if pool_hits < 5:
                logger.info(f"📡 オンデマンドニュース取得: {query or 'ヘッドライン'}")
                news_items = await fetch_primary_news(query)
                news_items = filter_news_by_freshness(news_items, _lookback)
                news_items = rank_news_items_for_chat(news_items, limit=15)
                for r in news_items:
                    url = (r.get("url") or "").strip()
                    if url and url in seen_urls:
                        continue
                    if url:
                        seen_urls.add(url)
                    pub = (r.get("published") or r.get("fetched_at") or "").strip()
                    item = {
                        "title": r.get("title", ""),
                        "snippet": (r.get("summary") or "")[:500],
                        "url": url,
                        "source": f"PRIMARY ({r.get('source', 'RSS')})",
                        "importance": r.get("importance", 0),
                    }
                    if pub:
                        item["published"] = pub
                    formatted_news.append(item)

            # 高スコア優先で上限
            formatted_news.sort(key=lambda x: -(x.get("importance") or 0))
            formatted_news = formatted_news[:12]

            if formatted_news:
                await set_search_cache(
                    cache_key,
                    providers,
                    results="\n".join([f"- {n['title']} ({n['source']})" for n in formatted_news]),
                    sources=formatted_news,
                    ttl_seconds=1800,
                )
                combined_results.extend(formatted_news)
                logger.info(
                    f"✅ ニュース取得成功: {len(formatted_news)}件 (pool={pool_hits})"
                )
            else:
                # フォールバック: Tavily等で一般検索（日付フィルタ付き）
                logger.info("⚠️ 1次情報取得失敗、フォールバック検索を実行")
                _fallback_query = _date_filtered_query if _date_filtered_query else (query or "latest news 2026")

                results = await search_tavily(_fallback_query)
                if not results:
                    logger.info("🔍 Tavily結果なし、Brave APIにフォールバックします")
                    results = await search_brave(_fallback_query)

                if not results:
                    _clean_query = re.sub(r'site:[^\s]+\s*', '', _fallback_query).strip()
                    logger.info("🔍 Tavily結果なし、Jina Searchにフォールバックします")
                    results = await search_jina(_clean_query)

                if results:
                    combined_results.extend(format_results(results, query))

    # 4. 一般クエリ (Tavily / Brave Search / Jina Search / DuckDuckGo 無料フォールバック)
    if "brave" in providers or "duckduckgo" in providers or "free" in providers or "jina" in providers or "tavily" in providers:
        _search_query = query
        cached = cache.get(_search_query, "general")
        if cached:
            combined_results.extend(cached)
        else:
            results = []
            if "duckduckgo" not in providers and "free" not in providers and "jina" not in providers:
                _is_news = any(kw in _search_query for kw in ["市場", "株", "市況", "ニュース", "決算", "相場", "market", "news", "Dow", "Nasdaq", "close"])
                # 明示日付クエリは lookback を広げて Tavily に渡す
                _days = 7
                if any(ch.isdigit() for ch in (_search_query or "")) and any(
                    k in (_search_query or "") for k in ("2026-", "July", "July ", "close", "市場", "market")
                ):
                    _days = 14 if _market_fresh else 7
                elif _market_fresh:
                    _days = 3
                if _is_news:
                    results = await search_tavily(_search_query, topic="news", days=_days)
                else:
                    results = await search_tavily(_search_query, days=_days)

            # Tavily結果なし時は Brave Search API へ自動フォールバック
            if not results and "duckduckgo" not in providers and "jina" not in providers:
                logger.info("🔍 Tavily結果なし、Brave APIに自動フォールバックします")
                # 市況系クエリは日付フィルタを伝播（古い記事混入防止）
                _brave_query = _date_filtered_query if _market_fresh else _search_query
                results = await search_brave(_brave_query)

            # Tavily結果なし時は Jina Search API へ自動フォールバック
            if not results and "duckduckgo" not in providers:
                logger.info("🔍 Tavily/Brave結果なし、Jina Search API (s.jina.ai) に自動フォールバックします")
                _clean_query = re.sub(r'site:[^\s]+\s*', '', _search_query).strip()
                # 市況系クエリは日付フィルタを伝播
                _jina_query = re.sub(r'site:[^\s]+\s*', '', _date_filtered_query if _market_fresh else _search_query).strip()
                results = await search_jina(_jina_query)

            # Jina結果なし・あるいはDuckDuckGo指定時は DuckDuckGo へ自動フォールバック
            if not results:
                logger.info("🦆 Jina/Tavily結果なし、DuckDuckGo無料検索プロバイダに自動フォールバックします")
                _clean_query = re.sub(r'site:[^\s]+\s*', '', _search_query).strip()
                from .providers.duckduckgo import search_duckduckgo
                results = await search_duckduckgo(_clean_query)
                
            if results:
                formatted_res = format_results(results, query)
                cache.set(_search_query, formatted_res, "general")
                combined_results.extend(formatted_res)

    # 5. 結果なしの場合の無料検索・Wikipediaフォールバック
    if not combined_results and "wikipedia" not in providers:
        logger.info("一般検索結果なし、Jina/DuckDuckGo無料検索およびWikipediaでフォールバック検索を実行します")
        from .providers.duckduckgo import search_duckduckgo
        
        _clean_query = re.sub(r'site:[^\s]+\s*', '', query).strip()
        jina_results = await search_jina(_clean_query)
        if jina_results:
            combined_results.extend(format_results(jina_results, query))
        else:
            ddg_results = await search_duckduckgo(_clean_query)
            if ddg_results:
                combined_results.extend(format_results(ddg_results, query))
            else:
                results = await search_wikipedia(query)
                if results:
                    combined_results.extend(format_results(results, query))
            
    return combined_results


async def fetch_url(url: str, force_refresh: bool = False) -> str:
    """特定URLの内容取得（Jina + 直接HTTPフォールバック使用・不完全キャッシュ自動更新）"""
    from app.core.ssrf import is_blocked_url
    if is_blocked_url(url):
        logger.warning(f"🚫 SSRF遮断: 内部/プライベート向けURLのfetchを拒否しました: {url}")
        return "❌ セキュリティ上の理由により、このURLへのアクセスは許可されていません。"

    cached = cache.get(url, "jina")
    # 古いキャッシュや不完全なキャッシュ（10,000文字以下で論文・学術ページ等）は破棄して最新フェッチ
    if cached and not force_refresh:
        content = cached[0].get("snippet", "")
        if len(content) >= 10000 or not any(dom in url for dom in ["pmc", "ncbi", "ieee", "arxiv"]):
            return content

    text = await fetch_with_jina(url)
    if not text or len(text.strip()) < 50:
        from .providers.jina import fetch_direct_html
        text = await fetch_direct_html(url)

    if text:
        cache.set(url, [{"snippet": text}], "jina")
    return text