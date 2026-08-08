import httpx
import os
import time
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 同一リクエスト/ターン内での重複フェッチ・Jina API重複呼び出し防止用キャッシュ (TTL 300秒)
_RECENT_FETCH_CACHE: dict[str, tuple[float, str]] = {}

def _smart_academic_extract(text: str, max_chars: int = 25000) -> str:
    """学術論文から冒頭部およびDefense Mechanism/実験表/結論など後半セクションを優先抽出"""
    if not text or len(text) <= max_chars:
        return text
    head = text[:8000]
    tail = text[-17000:]
    return head + "\n\n[...論文中間部（一部数式等）省略...]\n\n" + tail
from urllib.parse import quote_plus


async def search_jina(query: str, max_results: int = 10) -> list[dict]:
    """
    Jina AI Search公式API (`s.jina.ai`)。
    BraveとDuckDuckGoの間で機能する無料検索APIとして高精度なタイトル・スニペット・URLをJSON形式で返却する。
    """
    JINA_API_KEY = os.environ.get("JINA_API_KEY")
    encoded_query = quote_plus(query)
    url = f"https://s.jina.ai/{encoded_query}"
    
    headers = {
        "Accept": "application/json",
        "X-Retain-Images": "none",
    }
    if JINA_API_KEY:
        headers["Authorization"] = f"Bearer {JINA_API_KEY}"
        
    try:
        from .http_client import get_http_client
        client = get_http_client()
        res = await client.get(url, headers=headers, timeout=12)
        if res.status_code != 200:
            logger.warning(f"Jina Search API レスポンス異常: {res.status_code} - {res.text[:200]}")
            return []
            
        data_json = res.json()
        results = []
        
        # Jina Search のレスポンスは data["data"] に配列で入る（あるいはリスト直の場合もある）
        items = data_json.get("data", []) if isinstance(data_json, dict) else (data_json if isinstance(data_json, list) else [])
        
        for item in items[:max_results]:
            title = item.get("title", "")
            item_url = item.get("url", "")
            description = item.get("description", "")
            content = item.get("content", "")
            
            # スニペット作成（descriptionを優先しつつ、contentがあれば補強）
            snippet = description
            if content:
                content_preview = content[:600].replace("\n", " ").strip()
                snippet = f"{description}\n\n{content_preview}" if description else content_preview
                
            if item_url and item_url.startswith("http"):
                results.append({
                    "title": title or item_url,
                    "snippet": snippet.strip() or title,
                    "url": item_url,
                    "source": "jina (s.jina.ai)",
                })
                
        logger.info(f"🔍 Jina Search無料API成功 ('{query}'): {len(results)}件取得")
        return results
    except Exception as e:
        logger.warning(f"Jina Searchエラー ('{query}'): {e}")
        return []


async def fetch_with_jina(url: str) -> str:
    """
    Jina AI Reader公式API。
    任意のURLからクリーンなテキストを取得。
    """
    now = time.time()
    if url in _RECENT_FETCH_CACHE:
        cached_time, cached_text = _RECENT_FETCH_CACHE[url]
        if now - cached_time < 300:
            logger.debug(f"Jina AI Reader(キャッシュヒット): {url}")
            return cached_text

    JINA_API_KEY = os.environ.get("JINA_API_KEY")
    jina_url = f"https://r.jina.ai/{url}"
    headers = {"Accept": "text/plain"}
    if JINA_API_KEY:
        headers["Authorization"] = f"Bearer {JINA_API_KEY}"

    try:
        from .http_client import get_http_client
        client = get_http_client()
        res = await client.get(jina_url, headers=headers, timeout=15)
        res.raise_for_status()
        raw_text = res.text
        
        import re
        text = re.sub(r'!\[.*?\]\(.*?\)', '', raw_text)
        text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
        clean_text = _smart_academic_extract(text)
        _RECENT_FETCH_CACHE[url] = (time.time(), clean_text)
        return clean_text
    except Exception as e:
        logger.warning(f"Jina AI Reader取得エラー (URL: {url}): {e} -> 直接HTTPスクレイピングにフォールバックします")
        return await fetch_direct_html(url)


from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

async def _can_fetch_robots(url: str, user_agent: str = "*") -> bool:
    """対象サイトのrobots.txtを遵守しスクレイピング許可・禁止状況を確認する"""
    try:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        from .http_client import get_http_client
        client = get_http_client()
        res = await client.get(robots_url, timeout=5)
        if res.status_code == 200:
            rp = RobotFileParser()
            rp.parse(res.text.splitlines())
            allowed = rp.can_fetch(user_agent, url)
            if not allowed:
                logger.warning(f"robots.txt によりスクレイピング禁止エリアと判定されました: {url}")
            return allowed
    except Exception:
        pass
    return True


async def fetch_direct_html(url: str, depth: int = 0, max_depth: int = 1) -> str:
    """Jina失敗時の直接HTTP+HTMLテキストスクレイピングフォールバック (robots.txt厳守・重要お知らせ1階層追跡対応)"""
    from app.core.ssrf import is_blocked_url
    if is_blocked_url(url):
        logger.warning(f"🚫 SSRF遮断(直接HTTP): {url}")
        return ""

    now = time.time()
    if url in _RECENT_FETCH_CACHE:
        cached_time, cached_text = _RECENT_FETCH_CACHE[url]
        if now - cached_time < 300:
            logger.debug(f"直接HTTPスクレイピング(キャッシュヒット): {url}")
            return cached_text

    try:
        from .http_client import get_http_client
        import re
        from urllib.parse import urlparse, urljoin
        
        # --- 🛡️ robots.txt マナー遵守チェック ---
        if not await _can_fetch_robots(url):
            logger.warning(f"robots.txt 遵守のため直接フェッチをスキップします: {url}")
            return ""

        client = get_http_client()
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        }
        res = await client.get(url, headers=headers, timeout=15, follow_redirects=True)
        res.raise_for_status()
        html = res.text

        # --- 🔗 1-hop 重要お知らせ追跡（トップページ・一覧ページ限定、近傍マッチ対応、最大2件まで） ---
        subpage_texts = []
        parsed_base = urlparse(url)
        path_parts = [p for p in parsed_base.path.strip("/").split("/") if p]
        is_top_or_list_page = (
            len(path_parts) <= 1
            or parsed_base.path in ["", "/", "/index.html", "/index.php"]
            or any(kw in parsed_base.path.lower() for kw in ["news", "info", "notice", "topic", "list"])
        )

        if depth < max_depth and is_top_or_list_page:
            NOTICE_KEYWORDS = ["工事", "休業", "メンテナンス", "営業時間変更", "臨時休館", "休止", "中止", "閉鎖"]
            seen_urls = {url}
            sub_links_to_fetch = []

            for match in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.IGNORECASE | re.DOTALL):
                href = match.group(1)
                anchor_html = match.group(2)
                anchor_text = re.sub(r'<[^>]+>', '', anchor_html).strip()

                # ① 近傍マッチ: <a>タグの前後±150文字のコンテキストを取得して判定
                surround_start = max(0, match.start() - 150)
                surround_end = min(len(html), match.end() + 150)
                surround_text = re.sub(r'<[^>]+>', '', html[surround_start:surround_end])

                if not any(kw in anchor_text or kw in href or kw in surround_text for kw in NOTICE_KEYWORDS):
                    continue
                if href.startswith(("#", "mailto:", "tel:", "javascript:")):
                    continue
                if any(href.lower().endswith(ext) for ext in [".pdf", ".zip", ".jpg", ".jpeg", ".png", ".gif"]):
                    continue

                abs_url = urljoin(url, href)
                parsed_sub = urlparse(abs_url)
                if parsed_sub.netloc != parsed_base.netloc:
                    continue
                if abs_url in seen_urls:
                    continue

                seen_urls.add(abs_url)
                sub_links_to_fetch.append(abs_url)
                if len(sub_links_to_fetch) >= 2:
                    break

            # 件数上限を明確に適用（最大2件）
            sub_links_to_fetch = sub_links_to_fetch[:2]

            for sub_url in sub_links_to_fetch:
                logger.info(f"🔗 1-hop 重要お知らせ詳細ページを自動追跡します: {sub_url}")
                sub_text = await fetch_direct_html(sub_url, depth=depth + 1, max_depth=max_depth)
                if sub_text and len(sub_text.strip()) > 50:
                    subpage_texts.append(f"【お知らせ詳細ページ追跡本文: {sub_url}】\n{sub_text}")

        # <script>, <style> タグなどの非表示領域を削除
        html = re.sub(r'<script[\s\S]*?</script>', '', html, flags=re.IGNORECASE)
        html = re.sub(r'<style[\s\S]*?</style>', '', html, flags=re.IGNORECASE)
        html = re.sub(r'<header[\s\S]*?</header>', '', html, flags=re.IGNORECASE)
        html = re.sub(r'<footer[\s\S]*?</footer>', '', html, flags=re.IGNORECASE)

        # HTMLタグの除去とテキスト抽出
        text = re.sub(r'<[^>]+>', ' ', html)
        # 空行や余分なスペースの整理
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        full_text = "\n".join(lines)
        clean_text = _smart_academic_extract(full_text)
        logger.info(f"直接HTTPスクレイピング成功: {url} ({len(clean_text)}文字)")

        if subpage_texts:
            clean_text += "\n\n" + "\n\n".join(subpage_texts)

        _RECENT_FETCH_CACHE[url] = (time.time(), clean_text)
        return clean_text
    except Exception as e2:
        logger.error(f"直接HTTPスクレイピングも失敗 (URL: {url}): {e2}")
        return ""

