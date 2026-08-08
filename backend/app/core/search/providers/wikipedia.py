import httpx
from app.utils.logger import get_logger

logger = get_logger(__name__)

async def search_wikipedia(query: str, lang: str = "ja", num: int = 5) -> list[dict]:
    """
    Wikipedia公式API。
    定義・人物・歴史・概念系のクエリに最適。
    """
    url = f"https://{lang}.wikipedia.org/w/api.php"
    params = {
        "action":   "query",
        "list":     "search",
        "srsearch": query,
        "format":   "json",
        "srlimit":  num,
        "srprop":   "snippet",
    }
    
    headers = {
        "User-Agent": "Antigravity/2.1 (contact: test@example.com)"
    }
    
    try:
        from .http_client import get_http_client
        client = get_http_client()
        res = await client.get(url, params=params, headers=headers, timeout=10)
        res.raise_for_status()
        data = res.json()

        results = []
        for item in data.get("query", {}).get("search", []):
            snippet = item["snippet"]
            snippet = snippet.replace('<span class="searchmatch">', "").replace("</span>", "")
            # HTMLエンティティの簡易デコード
            snippet = snippet.replace("&quot;", '"').replace("&amp;", "&")
            
            results.append({
                "title":   item["title"],
                "snippet": snippet,
                "url":     f"https://{lang}.wikipedia.org/wiki/{item['title'].replace(' ', '_')}",
                "source":  "wikipedia",
            })
        return results
    except Exception as e:
        logger.error(f"Wikipedia検索エラー: {e}")
        return []
