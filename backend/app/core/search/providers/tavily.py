import os
from app.utils.logger import get_logger
from .http_client import get_http_client

logger = get_logger(__name__)

async def search_tavily(query: str, max_results: int = 10, topic: str = "general", days: int = 3) -> list[dict]:
    """
    Tavily Search API (AI向け検索特化)。
    クリーンなテキスト結果を返す。
    """
    TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")
    
    if not TAVILY_API_KEY:
        logger.warning("Tavily APIのキーが設定されていません。")
        return []

    url = "https://api.tavily.com/search"
    payload = {
        "api_key": TAVILY_API_KEY,
        "query": query,
        "search_depth": "basic",
        "include_answer": False,
        "include_images": False,
        "include_raw_content": False,
        "max_results": max_results,
        "topic": topic,
        "days": days
    }
    
    try:
        client = get_http_client()
        res = await client.post(url, json=payload, timeout=10)
        if res.status_code != 200:
            logger.error(f"Tavily API エラー詳細: {res.status_code} - {res.text}")
            return []
            
        data = res.json()
        results = []
        for item in data.get("results", []):
            results.append({
                "title": item.get("title", ""),
                "snippet": item.get("content", ""),
                "url": item.get("url", ""),
                "source": "tavily",
            })
        return results
    except Exception as e:
        logger.error(f"Tavily検索例外 [{type(e).__name__}]: {repr(e)}")
        return []
