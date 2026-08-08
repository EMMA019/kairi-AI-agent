"""
Discord Webhook Dispatcher — 初動ニュース＆アラート通知クライアント

【機能】
1. Discord Webhook への非同期 Markdown/Embed 送信
2. 検知タイプ（初動カタリスト/価格連動/非常事態）に応じた美しい色分けとヘッダー整形
3. DISCORD_WEBHOOK_URL 未設定時または --dry-run 時の自動ログ出力フォールバック
"""
import os
import json
import httpx
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv
from app.utils.logger import get_logger

load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.env")))
logger = get_logger(__name__)

# Discord Embed 色定義 (10進数)
EMBED_COLORS = {
    "CATALYST_EARLY_WARNING": 0xF1C40F,  # ゴールド (超初動・変動前カタリスト)
    "PRICE_AND_NEWS_ALERT": 0xE74C3C,    # レッド (価格急落×ニュース確定)
    "ALERT_LEVEL_2": 0x990000,           # ダークレッド (サーキットブレーカー/非常事態)
    "ALERT_LEVEL_1": 0xE67E22,           # オレンジ (要注目トリガー)
    "NEWS_HIGH": 0x3498DB,               # ブルー (マクロ速報・経済指標)
    "DEFAULT": 0x95A5A6                  # グレー
}

DISCORD_CONTENT_LIMIT = 1900  # 2000字制限に余裕を持たせる


def _split_discord_chunks(content: str, limit: int = DISCORD_CONTENT_LIMIT) -> List[str]:
    """改行優先で Discord 本文を分割する。"""
    text = (content or "").strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]

    chunks: List[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        cut = remaining.rfind("\n", 0, limit)
        if cut < limit // 3:
            cut = limit
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip("\n")
    return chunks


async def send_discord_text(
    content: str,
    *,
    dry_run: bool = False,
) -> bool:
    """
    Discord Webhook へプレーンテキストを全文送信（2000字超は分割）。
    Embed ではなく content フィールドを使う。Webhook 未設定時はログのみ。
    """
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    chunks = _split_discord_chunks(content)
    if not chunks:
        return True

    if dry_run or not webhook_url:
        mode_str = "DRY-RUN (Webhook未設定)" if not webhook_url else "DRY-RUN"
        for i, chunk in enumerate(chunks, 1):
            logger.info(
                f"📢 [{mode_str}] Discord text chunk {i}/{len(chunks)} ({len(chunk)} chars):\n{chunk[:500]}"
            )
        return True

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            for i, chunk in enumerate(chunks, 1):
                payload = {"content": chunk}
                resp = await client.post(webhook_url, json=payload)
                if resp.status_code not in (200, 204):
                    logger.error(
                        f"❌ Discord text chunk {i}/{len(chunks)} failed "
                        f"({resp.status_code}): {resp.text}"
                    )
                    return False
            logger.info(f"✅ Discord text sent ({len(chunks)} chunk(s))")
            return True
    except Exception as e:
        logger.error(f"❌ Discord text send exception: {e}")
        return False


async def send_discord_alert(
    alert_item: Dict[str, Any],
    dry_run: bool = False
) -> bool:
    """
    Discord Webhook へ検証済みアラートを配信する。
    """
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    alert_level = alert_item.get("alert_level", "CATALYST_EARLY_WARNING")
    color = EMBED_COLORS.get(alert_level, EMBED_COLORS["DEFAULT"])

    title = alert_item.get("title", "【市場監視速報】重要ニュース検知")
    url = alert_item.get("url", "")
    source = alert_item.get("source", "確度検証済みソース")
    importance = alert_item.get("importance", 0)
    import re

    body_fact = alert_item.get("verified_fact", alert_item.get("summary", "")) or ""
    body_fact = re.sub(r"<[^>]+>", "", body_fact)
    body_fact = re.sub(r"\s*⚠️\s*\[属性紐付け確認要:[^\]]*\]", "", body_fact)
    title = re.sub(r"<[^>]+>", "", title or "")
    targets = alert_item.get("matched_targets", [])
    entities = alert_item.get("matched_entities", [])
    catalysts = alert_item.get("detected_catalysts", [])
    price_reaction = (alert_item.get("price_reaction") or "").strip()

    # ターゲットバッジ文字列生成
    target_badges = []
    for t in targets:
        from app.core.monitor.watchlist import TARGET_DEFINITIONS
        t_name = TARGET_DEFINITIONS.get(t, {}).get("name", t)
        target_badges.append(f"`{t_name}`")
    for e in entities:
        target_badges.append(f"`{e}`")
    target_str = " ".join(target_badges) if target_badges else "`5大指数・総合マクロ`"

    # ヘッダー絵文字・ラベル選択
    if alert_level == "CATALYST_EARLY_WARNING":
        header_title = f"⚡ **【超初動・変動前ニュース検知】** (重要度: {importance}pt)"
    elif alert_level == "ALERT_LEVEL_2":
        header_title = f"🚨 **【非常事態 Level 2 トリガー】** (重要度: {importance}pt)"
    else:
        header_title = f"🥇 **【市場監視速報】** (重要度: {importance}pt)"

    # Embed フィールド構築（価格反応スタブは出さない）
    fields = [
        {
            "name": "🎯 関連ターゲット＆銘柄",
            "value": target_str,
            "inline": True
        },
    ]
    if price_reaction and not price_reaction.startswith("±0.0%"):
        fields.append({
            "name": "📈 現在の市場反応 (織り込み状況)",
            "value": f"**{price_reaction}**",
            "inline": True
        })

    if catalysts:
        fields.append({
            "name": "💣 検出されたカタリスト・材料",
            "value": "\n".join(f"• {c}" for c in catalysts),
            "inline": False
        })

    fields.append({
        "name": "📋 確定ファクト要約 (ゼロハルシネーション検証済み)",
        "value": f"{body_fact}\n\n🔗 [1次・検証済みソースを確認する]({url})" if url else body_fact,
        "inline": False
    })

    # タイトル自動和訳 (英語・韓国語等への対応)
    from app.core.translate import translate_title_ja
    translated_title = await translate_title_ja(title)
    if translated_title and translated_title.strip() != title.strip():
        display_title = f"{title}\n🇯🇵 **和訳: {translated_title.strip()}**"
    else:
        display_title = title

    full_title = f"{header_title}\n{display_title}"
    if len(full_title) > 256:
        full_title = full_title[:253] + "..."

    embed = {
        "title": full_title,
        "color": color,
        "fields": fields,
        "footer": {
            "text": f"出典: {source} | Kairi Proactive Market Radar (自動ファクト検証済み)"
        }
    }
    
    if url:
        embed["url"] = url

    payload = {"embeds": [embed]}

    # ドライラン時またはWebhook未設定時
    if dry_run or not webhook_url:
        mode_str = "DRY-RUN (Webhook未設定)" if not webhook_url else "DRY-RUN"
        logger.info(f"📢 [{mode_str}] Discord Webhook 送信ログ:\n{json.dumps(payload, ensure_ascii=False, indent=2)}")
        return True

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhook_url, json=payload)
            if resp.status_code in [200, 204]:
                logger.info(f"✅ Discord Webhook 通知送信成功: {title[:30]}...")
                return True
            else:
                logger.error(f"❌ Discord Webhook 送信エラー ({resp.status_code}): {resp.text}")
                return False
    except Exception as e:
        logger.error(f"❌ Discord Webhook 通信例外: {e}")
        return False

if __name__ == "__main__":
    import asyncio
    import sys

    async def _test():
        test_item = {
            "title": "【テスト送信】SK Hynix および TSMC 半導体セクター初動検知テスト",
            "url": "https://www.reuters.com",
            "source": "Reuters (Test)",
            "importance": 85,
            "alert_level": "CATALYST_EARLY_WARNING",
            "verified_fact": "これは Discord Webhook 通知のテストメッセージです。正常にカラーEmbedとターゲットバッジが表示されていることをご確認ください。",
            "matched_targets": ["^SOX", "^KS11"],
            "matched_entities": ["SK_HYNIX", "TSMC"],
            "detected_catalysts": ["🚨 サーキットブレーカー/売買停止", "💥 追証・強制ロスカット・連鎖決済"],
            "price_reaction": "±0.0% (変動前/超初動)"
        }
        dry = "--dry-run" in sys.argv
        if not os.environ.get("DISCORD_WEBHOOK_URL") and not dry:
            print("[WARN] DISCORD_WEBHOOK_URL is not set. Using --dry-run mode.")
            dry = True
        success = await send_discord_alert(test_item, dry_run=dry)
        if success:
            print("[OK] Test notification dispatched successfully!")
        else:
            print("[ERROR] Failed to send notification. Please check the Webhook URL.")

    asyncio.run(_test())
