"""
Antigravity 検索バックエンド v2.2
DuckDuckGo に代わり、Wikipedia, Brave, Jina AI, Open-Meteo を使用するモジュール。
検索結果はベクトルリランキングにより意味的に並べ替えられる。
"""
import re
from app.utils.logger import get_logger
from .router import search, fetch_url
from .formatter import format_for_prompt
from .reranker import rerank

logger = get_logger(__name__)

async def web_search(query: str, max_results: int = 10, providers: list[str] = None) -> tuple[str, list[dict]]:
    """
    旧 search.py の互換インターフェース。
    クエリを受け取り、指定されたプロバイダーで検索を行い、
    ベクトルリランキングで関連度順に並べ替えた上でプロンプト用の文字列を返す。
    """
    if providers is None:
        providers = ["brave"]
    try:
        # URLが直接入力された場合は Jina AI でフェッチする機能を簡易追加
        url_match = re.search(r'(https?://[^\s]+)', query)
        if url_match:
            url = url_match.group(1)
            logger.info(f"URLを検出したため、直接フェッチします: {url}")
            text = await fetch_url(url)
            if text:
                return f"URL ({url}) の内容:\n\n{text}", [{"title": url, "url": url}]
            else:
                return f"URL ({url}) から内容を取得できませんでした。回答を保留してください。", []

        logger.info(f"検索リクエスト: '{query}' (Providers: {providers})")
        results = await search(query, providers)
        
        # ベクトルリランキング: 意味的に関連度の高い結果を上位に並べ替え
        if results and len(results) > 1:
            results = rerank(query, results, top_k=max_results)
        
        # formatter 側で、結果がない場合の厳格なハルシネーション防止テキストを付与する
        formatted_text = format_for_prompt(results, query=query)
        return formatted_text, results

    except Exception as e:
        logger.error(f"検索モジュール全体エラー: {e}")
        # 絶対にハルシネーションを起こさせないためのエラーメッセージ
        return (
            f"検索システムでエラーが発生しました ({str(e)})。\n"
            "【重要・絶対遵守】この情報について、あなたは自分の持つ事前知識を使って回答を生成してはいけません。\n"
            "必ず「検索システムのエラーにより回答できません。公式サイト等をご確認ください。」とだけ返答してください。"
        ), []