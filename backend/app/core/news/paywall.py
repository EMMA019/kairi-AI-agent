"""
ペイウォール記事の無料ソース差し替え。

Bloomberg/WSJ 等はタイトルのみのことが多いため、同一トピックの無料記事を
web_search で探し companion_* として添付する。
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse

from app.utils.logger import get_logger

logger = get_logger(__name__)

PAYWALL_DOMAINS = {
    "bloomberg.com",
    "www.bloomberg.com",
    "wsj.com",
    "www.wsj.com",
    "ft.com",
    "www.ft.com",
    "economist.com",
    "www.economist.com",
    "nikkei.com",
    "www.nikkei.com",
    "asia.nikkei.com",
    "barrons.com",
    "www.barrons.com",
    "financialtimes.com",
}

FREE_SOURCE_HINTS = (
    "reuters.com",
    "apnews.com",
    "cnbc.com",
    "yahoo.com",
    "finance.yahoo.com",
    "marketwatch.com",
    "investing.com",
    "seekingalpha.com",
    "techcrunch.com",
    "scmp.com",
    "yna.co.kr",
    "news.yahoo.co.jp",
    "nikkei.com",  # 一部無料記事
)


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def is_paywalled(url: str, source: str = "") -> bool:
    host = _host(url or "")
    if host in PAYWALL_DOMAINS:
        return True
    # サブドメイン対応
    if any(host.endswith("." + d) or host == d for d in PAYWALL_DOMAINS):
        return True
    src = (source or "").lower()
    if any(k in src for k in ("bloomberg", "wsj", "wall street journal", "financial times", "ft ")):
        return True
    return False


def is_free_source(url: str) -> bool:
    host = _host(url or "")
    if not host:
        return False
    if host in PAYWALL_DOMAINS or any(
        host.endswith("." + d) for d in PAYWALL_DOMAINS
    ):
        return False
    return any(host == h or host.endswith("." + h) for h in FREE_SOURCE_HINTS)


def extract_search_keywords(title: str, max_terms: int = 8) -> str:
    """タイトルから検索クエリ用の主要語を抽出。"""
    t = title or ""
    # 記号除去
    t = re.sub(r"[\"'`‘’“”]", "", t)
    # よくあるノイズ語を落とす
    stop = {
        "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
        "as", "at", "by", "from", "is", "are", "was", "were", "be", "been",
        "の", "が", "を", "に", "は", "と", "で", "も", "へ",
    }
    # 英語トークン + 長い日本語連続
    tokens = re.findall(r"[A-Za-z0-9$%]+|[一-龥ぁ-んァ-ン]{2,}", t)
    kept = []
    for tok in tokens:
        if tok.lower() in stop:
            continue
        if len(tok) < 2:
            continue
        kept.append(tok)
        if len(kept) >= max_terms:
            break
    return " ".join(kept) if kept else t[:80]


async def find_free_companion(
    title: str,
    paywall_url: str = "",
    providers: Optional[list[str]] = None,
) -> Optional[dict]:
    """
    ペイウォール記事タイトルに対し、無料ドメインの同一トピック記事を探す。
    Returns: {url, title, summary, source} or None
    """
    query = extract_search_keywords(title)
    if not query.strip():
        return None

    providers = providers or ["brave", "duckduckgo"]
    try:
        from app.core.search import web_search

        _, sources = await web_search(query, max_results=8, providers=providers)
    except Exception as e:
        logger.warning(f"paywall companion search failed: {e}")
        return None

    paywall_host = _host(paywall_url)
    candidates: list[dict] = []
    for src in sources or []:
        url = (src.get("url") or "").strip()
        if not url:
            continue
        host = _host(url)
        if not host:
            continue
        if host == paywall_host or host in PAYWALL_DOMAINS:
            continue
        if any(host.endswith("." + d) for d in PAYWALL_DOMAINS):
            continue
        entry = {
            "url": url,
            "title": src.get("title") or "",
            "summary": src.get("snippet") or "",
            "source": host,
        }
        if is_free_source(url):
            return entry
        candidates.append(entry)
    return candidates[0] if candidates else None


async def attach_companions(items: list[dict], max_lookups: int = 5) -> list[dict]:
    """
    スコア上位などのリストに対し、ペイウォール記事へ companion を付与。
    元の dict をコピーして返す。
    """
    out = []
    lookups = 0
    for item in items:
        copy = dict(item)
        url = copy.get("url") or ""
        source = copy.get("source") or ""
        if (
            lookups < max_lookups
            and is_paywalled(url, source)
            and not copy.get("companion_url")
        ):
            companion = await find_free_companion(copy.get("title") or "", url)
            lookups += 1
            if companion:
                copy["companion_url"] = companion["url"]
                copy["companion_summary"] = companion.get("summary") or ""
                copy["companion_source"] = companion.get("source") or ""
                logger.info(
                    f"🔓 ペイウォール差し替え: {(copy.get('title') or '')[:40]} → {companion['url'][:60]}"
                )
        out.append(copy)
    return out
