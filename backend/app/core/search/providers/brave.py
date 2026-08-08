import httpx
import os
from app.utils.logger import get_logger

logger = get_logger(__name__)

async def search_brave(query: str, count: int = 10) -> list[dict]:
    """
    Brave Search API。
    Google Custom Searchの代替として一般検索・最新情報・ニュース全般をカバー。
    """
    BRAVE_API_KEY = os.environ.get("BRAVE_API_KEY")
    
    if not BRAVE_API_KEY:
        logger.warning("Brave Search APIのキーが設定されていません。")
        return []

    url = "https://api.search.brave.com/res/v1/web/search"
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": BRAVE_API_KEY
    }
    params = {
        "q": query,
        "count": count,
    }
    
    try:
        from .http_client import get_http_client
        client = get_http_client()
        res = await client.get(url, headers=headers, params=params, timeout=10)
        if res.status_code != 200:
            logger.error(f"Brave API エラー詳細: {res.status_code} - {res.text}")
            return []
        data = res.json()

        results = []
        # Braveのレスポンスは data["web"]["results"] に配列として入っています
        for item in data.get("web", {}).get("results", []):
            age = item.get("page_age")
            snippet = item.get("description", "")
            if age:
                snippet = f"【公開日時: {age}】\n" + snippet
                
            results.append({
                "title":   item.get("title", ""),
                "snippet": snippet,
                "url":     item.get("url", ""),
                "source":  "brave",
            })
        return results
    except Exception as e:
        logger.error(f"Brave検索例外 [{type(e).__name__}]: {repr(e)}")
        return []