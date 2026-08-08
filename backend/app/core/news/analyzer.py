import json
import asyncio
from app.utils.logger import get_logger
from app.core.llm_client import call_model
from app.core.news.database import get_unprocessed_news, update_news_analysis, update_news_body
from app.core.search.providers.jina import fetch_with_jina
import os

logger = get_logger(__name__)

ANALYZER_PROMPT = """
あなたはグローバル経済・テクノロジー・暗号資産の幅広い領域をカバーするプロフェッショナルアナリストです。
以下のニュース記事の「タイトル」と「要約」を分析し、指定されたJSON形式でメタデータを出力してください。
必ずJSONのみを出力し、マークダウンブロック(```json ... ```)で囲まないでください。

【判定基準】
- importance: ニュースの重要度を0〜100で評価してください。
  * グローバル市場全体を動かすもの(FOMC、巨大テック決算等)は「特大(80-100)」
  * 特定の国(日本など)や特定セクター(暗号資産、スタートアップ技術)における歴史的・重大なニュースも、その領域での影響度を考慮し高く(70-90)評価してください。米国市場やマクロ経済にのみスコアが偏らないよう注意してください。
- sentiment: Positive, Negative, Neutral のいずれか。
- sector: 関連する業種・領域名（英語推奨。例: Semiconductor, Finance, Automotive, Crypto, AI, Web3）。該当なしは空文字。
- stocks: 関連するティッカーシンボル。
  * 米国株（例: "NVDA", "AAPL"）
  * 日本株（例: "7203.T", "9984.T"）
  * 暗号資産（例: "BTC", "ETH"）
  * 該当なしの場合は空リスト。
- country: 主要な関連国（USA, Japan, China, Global等）。暗号資産など国境を持たないものは「Global」または「Decentralized」。
- tags: 検索や分類に役立つキーワード（AI, FOMC, 日銀, Bitcoin, SaaS等）を3〜5個程度。

【出力フォーマット（厳守）】
{
    "importance": 85,
    "sentiment": "Positive",
    "sector": "Semiconductor",
    "stocks": ["NVDA", "TSM"],
    "country": "USA",
    "tags": ["AI", "Datacenter", "Earnings"]
}
"""

async def analyze_news_batch():
    """
    未処理のニュースを一括で分析する
    """
    unprocessed = await get_unprocessed_news()
    if not unprocessed:
        return
        
    logger.info(f"AI Analyzer: 未処理のニュースを {len(unprocessed)} 件発見しました。分析を開始します。")
    
    # Provider setting
    provider = os.environ.get("NEWS_ANALYZER_PROVIDER", "deepseek")
    
    for item in unprocessed:
        try:
            user_msg = f"タイトル: {item['title']}\n要約: {item['summary']}"
            
            # Call LLM
            response_text = await call_model(
                system_instruction=ANALYZER_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
                provider=provider,
                temperature=0.1
            )
            
            # Clean JSON (remove think tags if present from reasoning models)
            if "<think>" in response_text:
                response_text = response_text.split("</think>")[-1].strip()
            
            # Parse JSON safely using regex
            import re
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                clean_text = json_match.group(0)
                try:
                    analysis = json.loads(clean_text)
                except json.JSONDecodeError as e:
                    logger.error(f"JSON Parse Error. Clean text: {clean_text[:100]}... Error: {e}")
                    raise e
            else:
                logger.error(f"No JSON object found in response: {response_text[:100]}")
                raise ValueError("No JSON object found in LLM response")
                
            # DB更新
            await update_news_analysis(item["id"], analysis)
            logger.info(f"Analyzed ID {item['id']}: importance={analysis.get('importance')}, stocks={analysis.get('stocks')}")
            
            # 重要度が80以上の場合、Jina Readerで本文を取得
            importance = analysis.get("importance", 0)
            if isinstance(importance, int) and importance >= 80 and item.get("url"):
                logger.info(f"High importance ({importance}) detected for ID {item['id']}. Fetching full body...")
                body_text = await fetch_with_jina(item["url"])
                if body_text:
                    await update_news_body(item["id"], body_text)
                    
            # 連続APIコールによるレートリミット回避
            await asyncio.sleep(1)
            
        except Exception as e:
            logger.error(f"Failed to analyze news ID {item['id']}: {e}")
