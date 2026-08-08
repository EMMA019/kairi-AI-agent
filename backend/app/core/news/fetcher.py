"""
News Fetcher — 並列RSS取得 + ローリングプール向け収集

【ポリシー】
- フィードは並列取得（フィードごと10秒タイムアウト）
- 1フィードの失敗で全体を止めない
- Google News RSS / アジア系フィードでカバレッジを補完
- フィード健全性を feed_health に記録
"""
from __future__ import annotations

import asyncio
from typing import Optional
from urllib.parse import quote_plus

import feedparser

from app.utils.logger import get_logger

logger = get_logger(__name__)

FEED_TIMEOUT_SECONDS = 10.0

# 1次情報＆世界・国内株式市場最速速報RSS
ON_DEMAND_FEEDS = [
    # --- 企業公式開示 ---
    {"name": "SEC EDGAR 8-K", "url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&count=40&output=atom"},
    {"name": "PR Newswire", "url": "https://www.prnewswire.com/rss/news-releases-list.rss"},
    {"name": "BusinessWire", "url": "https://feed.businesswire.com/rss/home/?rss=G1QFDERJXkJeEFdX"},
    {"name": "GlobeNewswire", "url": "https://www.globenewswire.com/NewsRoom/Rss"},
    # --- 米国ウォール街 ---
    {"name": "Seeking Alpha Market Currents", "url": "https://seekingalpha.com/market_currents.xml"},
    {"name": "WSJ Markets", "url": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml"},
    {"name": "CNBC Market News", "url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664"},
    {"name": "CNBC Investing / Stocks", "url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=15839069"},
    {"name": "MarketWatch Top Stories", "url": "http://feeds.marketwatch.com/marketwatch/topstories/"},
    {"name": "MarketWatch Market Pulse", "url": "http://feeds.marketwatch.com/marketwatch/marketpulse/"},
    {"name": "Yahoo Finance Top News", "url": "https://finance.yahoo.com/news/rssindex"},
    {"name": "Investing.com Stock Market News", "url": "https://www.investing.com/rss/news_25.rss"},
    # --- アジア ---
    {"name": "Yahoo Japan 経済・市況", "url": "https://news.yahoo.co.jp/rss/topics/business.xml"},
    {"name": "Yahoo Japan IT/テック", "url": "https://news.yahoo.co.jp/rss/topics/it.xml"},
    {"name": "Yonhap News Economy", "url": "https://www.yna.co.kr/rss/economy.xml"},
    {"name": "Nikkei Asia", "url": "https://asia.nikkei.com/rss/feed/nar"},
    {"name": "SCMP Business", "url": "https://www.scmp.com/rss/92/feed"},
    # --- 通信社・テック ---
    {"name": "AP News", "url": "https://rsshub.app/apnews/topics/apf-topnews"},
    {"name": "Reuters", "url": "https://www.reutersagency.com/feed/"},
    {"name": "TechCrunch", "url": "https://techcrunch.com/feed/"},
    # Hacker News は市況レーダー/プールのノイズ源のため除外
    # --- Google News RSS（横断保険・IPO/中国/半導体/日本株） ---
    {
        "name": "Google News: semiconductor",
        "url": f"https://news.google.com/rss/search?q={quote_plus('semiconductor OR chip stocks')}&hl=en-US&gl=US&ceid=US:en",
    },
    {
        "name": "Google News: IPO listing",
        "url": f"https://news.google.com/rss/search?q={quote_plus('IPO listing')}&hl=en-US&gl=US&ceid=US:en",
    },
    {
        "name": "Google News: China / Hong Kong",
        "url": f"https://news.google.com/rss/search?q={quote_plus('China stocks OR Hong Kong OR CXMT')}&hl=en-US&gl=US&ceid=US:en",
    },
    {
        "name": "Google News: 日本株",
        "url": f"https://news.google.com/rss/search?q={quote_plus('日本株 OR 日経平均')}&hl=ja&gl=JP&ceid=JP:ja",
    },
]

MIN_NEWS_COUNT = 15


def _strip_html(text: str) -> str:
    import re

    return re.sub(r"<[^>]+>", "", text or "").strip()


def normalize_entry(entry, source_name: str) -> Optional[dict]:
    try:
        link = entry.get("link", "") or ""
        # Google News 等で link が list の場合
        if isinstance(link, list) and link:
            link = link[0].get("href", "") if isinstance(link[0], dict) else str(link[0])
        return {
            "title": _strip_html(entry.get("title", "") or ""),
            "url": link,
            "published": entry.get("published", entry.get("updated", "")) or "",
            "source": source_name,
            "summary": _strip_html(entry.get("summary", "") or ""),
            "guid": entry.get("id") or entry.get("guid") or link,
        }
    except Exception:
        return None


def _parse_items_from_bytes(content: bytes, source_name: str) -> list[dict]:
    """取得済みバイト列を feedparser / BeautifulSoup でパース。"""
    items: list[dict] = []
    parsed = feedparser.parse(content)
    if parsed.entries:
        for entry in parsed.entries:
            normalized = normalize_entry(entry, source_name)
            if normalized and normalized.get("title") and normalized.get("url"):
                items.append(normalized)
        return items

    # BeautifulSoup フォールバック
    try:
        import bs4

        soup = bs4.BeautifulSoup(content, "xml")
        tags = soup.find_all(["item", "entry"])
        if not tags:
            soup = bs4.BeautifulSoup(content, "html.parser")
            tags = soup.find_all(["item", "entry"])
        for item in tags:
            title_tag = item.find("title")
            link_tag = item.find("link")
            link_val = ""
            if link_tag is not None:
                link_val = (
                    link_tag.get("href")
                    if link_tag.has_attr("href")
                    else (link_tag.text or "")
                )
            summary_tag = (
                item.find("description") or item.find("summary") or item.find("content")
            )
            pub_tag = item.find("pubDate") or item.find("published") or item.find("updated")
            if title_tag and link_val:
                items.append(
                    {
                        "title": title_tag.text.strip(),
                        "url": link_val.strip(),
                        "published": pub_tag.text.strip() if pub_tag else "",
                        "source": source_name,
                        "summary": summary_tag.text.strip() if summary_tag else "",
                        "guid": link_val.strip(),
                    }
                )
    except Exception as e:
        logger.debug(f"BeautifulSoup fallback failed for {source_name}: {e}")
    return items


async def _fetch_one_feed(feed: dict) -> tuple[str, str, list[dict], Optional[str]]:
    """
    1フィードを取得。
    Returns: (name, url, items, error_message)
    """
    name = feed["name"]
    url = feed["url"]
    try:
        from app.core.search.providers.http_client import get_http_client

        client = get_http_client()
        resp = await client.get(
            url,
            timeout=FEED_TIMEOUT_SECONDS,
            headers={"User-Agent": "KairiNewsBot/1.0 (+https://localhost)"},
        )
        resp.raise_for_status()
        items = await asyncio.to_thread(_parse_items_from_bytes, resp.content, name)
        return name, url, items, None
    except Exception as e:
        return name, url, [], str(e)


async def fetch_rss_on_demand(feeds: list[dict] = None) -> list[dict]:
    """全フィードを並列取得し、健全性を記録する。"""
    if feeds is None:
        feeds = ON_DEMAND_FEEDS

    logger.info(f"📡 並列RSS取得開始: {len(feeds)}フィード (timeout={FEED_TIMEOUT_SECONDS}s)")

    results = await asyncio.gather(
        *[_fetch_one_feed(f) for f in feeds],
        return_exceptions=True,
    )

    all_items: list[dict] = []
    try:
        from app.core.news.database import record_feed_success, record_feed_failure
    except Exception:
        record_feed_success = record_feed_failure = None  # type: ignore

    for res in results:
        if isinstance(res, Exception):
            logger.error(f"❌ RSS gather 例外: {res}")
            continue
        name, url, items, err = res
        if err is not None:
            logger.warning(f"⚠️ RSS取得失敗: {name} — {err}")
            if record_feed_failure:
                try:
                    fails = await record_feed_failure(name, url)
                    if fails >= 3:
                        logger.warning(
                            f"🚨 フィード連続失敗 {fails}回: {name} — カバレッジ低下に注意"
                        )
                except Exception as he:
                    logger.debug(f"feed_health failure record error: {he}")
            continue

        logger.info(f"✅ {name}: {len(items)}件")
        all_items.extend(items)
        if record_feed_success:
            try:
                await record_feed_success(name, url, len(items))
            except Exception as he:
                logger.debug(f"feed_health success record error: {he}")

    logger.info(f"📊 並列RSS取得完了: 合計{len(all_items)}件")
    return all_items


async def fetch_primary_news(query: str = "") -> list[dict]:
    """
    1次情報を優先してニュースを取得。

    フロー:
    1. 主要RSSを並列取得
    2. 日本市場クエリ時は海外テック系RSSノイズを除外
    3. キーワードがあればBraveで補完検索
    """
    is_jp_or_market = any(
        kw in query
        for kw in ["日本", "日経", "東京", "東証", "TOPIX", "株", "為替", "円", "国内", "市場"]
    )
    is_finance = any(
        kw in query
        for kw in ["銘柄", "投資", "ETF", "決算", "半導体", "インフレ", "経済", "FRB", "金利", "雇用", "相場"]
    )

    if query and not (
        is_jp_or_market or is_finance or "ニュース" in query or "news" in query.lower()
    ):
        results = []
    else:
        results = await fetch_rss_on_demand()

    if is_jp_or_market and results:
        results = [
            r
            for r in results
            if r.get("source")
            not in ["Hacker News", "MIT Technology Review", "Ars Technica", "TechCrunch"]
        ]

    if query:
        from app.core.search import web_search

        if is_jp_or_market:
            site_query = f"{query} 日経平均 OR 株価 OR 東京株式市場 OR 終値 OR ニュース"
        else:
            site_query = (
                f"site:prnewswire.com OR site:businesswire.com OR site:apnews.com {query}"
            )
        _, brave_sources = await web_search(site_query, providers=["brave"])
        if brave_sources:
            existing_urls = {item["url"] for item in results if item.get("url")}
            for src in brave_sources:
                if src.get("url") not in existing_urls:
                    results.append(
                        {
                            "title": src.get("title", ""),
                            "url": src.get("url", ""),
                            "published": "",
                            "source": "PRIMARY (Brave JP)" if is_jp_or_market else "PRIMARY (Brave)",
                            "summary": src.get("snippet", ""),
                            "guid": src.get("url", ""),
                        }
                    )

    if len(results) < MIN_NEWS_COUNT:
        logger.info(f"⚠️ RSS取得が{len(results)}件と少ないため、Braveで補完検索を実行")
        try:
            from app.core.search import web_search

            fallback_query = (
                f"{query} 日本市場 株価 市況 最新ニュース"
                if is_jp_or_market
                else (query if query else "latest breaking news 2026")
            )
            _, brave_sources = await web_search(fallback_query, providers=["brave"])
            if brave_sources:
                existing_urls = {item["url"] for item in results if item.get("url")}
                added = 0
                for src in brave_sources:
                    if src.get("url") and src.get("url") not in existing_urls:
                        results.append(
                            {
                                "title": src.get("title", ""),
                                "url": src.get("url", ""),
                                "published": src.get("published", ""),
                                "source": "NEWS (Brave)",
                                "summary": src.get("snippet", ""),
                                "guid": src.get("url", ""),
                            }
                        )
                        existing_urls.add(src.get("url"))
                        added += 1
                logger.info(f"✅ Brave補完: {added}件追加")
        except Exception as e:
            logger.warning(f"⚠️ Brave補完検索エラー: {e}")

    logger.info(f"📊 最終ニュース件数: {len(results)}件")
    return results
