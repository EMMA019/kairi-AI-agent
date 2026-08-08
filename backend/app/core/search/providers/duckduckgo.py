import httpx
import re
from urllib.parse import quote_plus, unquote
from app.utils.logger import get_logger

logger = get_logger(__name__)

async def search_duckduckgo(query: str, max_results: int = 10) -> list[dict]:
    """
    DuckDuckGo 完全無料検索プロバイダ (APIキー不要・利用枠制限なし)
    Brave Search の月1000回制限を補うため、エラー時や無料枠超過時に自動フォールバックして稼働する。
    """
    try:
        from .http_client import get_http_client
        client = get_http_client()
        
        # DuckDuckGo HTML 検索エンドポイント
        url = "https://html.duckduckgo.com/html/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,ja;q=0.8",
            "Referer": "https://html.duckduckgo.com/"
        }
        data = {"q": query, "b": ""}
        
        res = await client.post(url, headers=headers, data=data, timeout=12, follow_redirects=True)
        if res.status_code != 200:
            logger.warning(f"DuckDuckGo HTML検索レスポンス異常: {res.status_code}")
            return []
            
        html = res.text
        results = []
        
        # HTML結果ブロックからタイトル・URL・スニペットを抽出
        # DuckDuckGo htmlフォーマット: <a class="result__url" href="..."> または <a class="result__snippet" ...>
        result_blocks = re.findall(r'<div class="result\s+results_links.*?>(.*?)</div>\s*</div>', html, re.DOTALL)
        
        for block in result_blocks[:max_results]:
            # タイトルとリンク
            title_match = re.search(r'<a class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.DOTALL)
            if not title_match:
                continue
            raw_url = title_match.group(1)
            raw_title = re.sub(r'<[^>]+>', '', title_match.group(2)).strip()
            
            # リダイレクトURL (/l/?kh=-1&uddg=...) の実URLパース
            real_url = raw_url
            if "uddg=" in raw_url:
                uddg_match = re.search(r'uddg=([^&]+)', raw_url)
                if uddg_match:
                    real_url = unquote(uddg_match.group(1))
            
            # スニペット
            snippet_match = re.search(r'<a class="result__snippet"[^>]*>(.*?)</a>', block, re.DOTALL)
            raw_snippet = ""
            if snippet_match:
                raw_snippet = re.sub(r'<[^>]+>', '', snippet_match.group(1)).strip()
                
            if raw_title and real_url and real_url.startswith("http"):
                results.append({
                    "title": raw_title,
                    "snippet": raw_snippet or raw_title,
                    "url": real_url,
                    "source": "duckduckgo (Free)"
                })
                
        logger.info(f"🦆 DuckDuckGo無料検索成功 ('{query}'): {len(results)}件取得")
        return results

    except Exception as e:
        logger.warning(f"DuckDuckGo検索エラー ('{query}'): {e}")
        return []
