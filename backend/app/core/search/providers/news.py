import os
import httpx
from app.utils.logger import get_logger
from app.core.translate import translate_text

logger = get_logger(__name__)

async def search_world_news(query: str, source_countries: str | None = None, max_results: int = 5) -> list[dict] | None:
    """
    WorldNewsAPI を使用して海外ニュースを検索し、DeepLで日本語に翻訳して返す。
    無料枠: 250 req/day
    """
    api_key = os.environ.get("WORLD_NEWS_API_KEY")
    if not api_key:
        logger.info("WORLD_NEWS_API_KEYが設定されていないため、WorldNewsAPIはスキップします。")
        return None

    import re
    # 会話的な表現や一般的な語句を除去し、検索のノイズを減らす
    clean_query = re.sub(r'(教えて|最新の|気になる|あった|について|ください|ニュース|news|アメリカ|米国|イギリス|英国|中国)', '', query).strip()
    
    if not clean_query:
        search_query = "latest"
    else:
        # クエリを英語に翻訳して検索精度を上げる
        translated_query = await translate_text(clean_query, "EN-US")
        
        # 翻訳後も日本語が残っている場合（DeepLのAPIエラーなどで翻訳に失敗した場合）
        # 日本語のまま WorldNewsAPI に投げると検索結果が0件になってしまうため、"latest" にフォールバックする
        if not translated_query or not translated_query.strip() or re.search(r'[ぁ-んァ-ヶｱ-ﾝﾞﾟ一-龠]', translated_query):
            search_query = "latest"
            logger.info("DeepL翻訳失敗または日本語が残っているため、クエリを 'latest' にフォールバックしました。")
        else:
            search_query = translated_query.strip()
            logger.info(f"WorldNewsAPI用クエリ翻訳: {search_query}")

    url = "https://api.worldnewsapi.com/search-news"
    params = {
        "text": search_query,
        "language": "en",  # 基本的に海外(英語)ニュースを取得
        "number": max_results,
        "api-key": api_key,
        "sort": "publish-time",
        "sort-direction": "DESC"
    }
    if source_countries:
        params["source-countries"] = source_countries

    try:
        from .http_client import get_http_client
        client = get_http_client()
        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        articles = data.get("news", [])
        if not articles:
            return []

        results = []
        for item in articles:
            title = item.get("title", "")
            text = item.get("text", "")
            # 本文が長すぎる場合は要約・切り詰め
            if len(text) > 800:
                text = text[:800] + "..."
                
            # 翻訳実行
            translated_title = await translate_text(title, "JA")
            translated_text = await translate_text(text, "JA")

            results.append({
                "title": translated_title,
                "snippet": translated_text,
                "url": item.get("url", ""),
                "source": item.get("author", "WorldNewsAPI") or "WorldNewsAPI"
            })
        
        return results

    except Exception as e:
        logger.error(f"WorldNewsAPI 検索エラー: {e}")
        return None

async def search_japan_news(query: str, max_results: int = 5) -> list[dict] | None:
    """
    NewsData.io を使用して日本のニュースを検索する。
    無料枠: 200 req/day
    """
    api_key = os.environ.get("NEWSDATA_API_KEY")
    if not api_key:
        logger.info("NEWSDATA_API_KEYが設定されていないため、NewsData.ioはスキップします。")
        return None

    search_query = query.replace("ニュース", "").replace("news", "").strip()

    url = "https://newsdata.io/api/1/news"
    params = {
        "apikey": api_key,
        "country": "jp",
        "language": "ja"
    }
    
    if search_query:
        params["q"] = search_query

    try:
        from .http_client import get_http_client
        client = get_http_client()
        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        articles = data.get("results", [])
        if not articles:
            return []

        results = []
        for item in articles[:max_results]:
            title = item.get("title", "")
            # NewsData.io は description や content を返す
            description = item.get("description") or item.get("content") or ""
            if len(description) > 800:
                description = description[:800] + "..."

            results.append({
                "title": title,
                "snippet": description,
                "url": item.get("link", ""),
                "source": item.get("source_id", "NewsData.io")
            })
        
        return results

    except Exception as e:
        logger.error(f"NewsData.io 検索エラー: {e}")
        return None
