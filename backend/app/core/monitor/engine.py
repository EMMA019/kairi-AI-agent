"""
Radar Engine — 変動前・超初動ニュース察知＆ゼロハルシネーション検証エンジン

【機能】
1. システマチック3層処理パイプラインの統括
2. verify_date_and_entity_attribution による日付・主語・数値の縫い合わせエラー排除
3. fact_filter.py との厳格連携および Discord 送信・履歴保存
"""
import re
import json
import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from app.utils.logger import get_logger
from app.core.fact_filter import verify_numbers_exist_in_source, filter_fact
from app.core.monitor.watchlist import (
    systematic_screen_and_score,
    systematic_deduplicate,
    log_rejected_news,
    save_alert_history,
    get_recent_alerts,
    init_monitor_db
)
from app.core.notify.discord import send_discord_alert

logger = get_logger(__name__)

# 銘柄なしでも通知を許可するマクロ系カタリスト（高信頼ソース必須）
_MACRO_CATALYST_IDS = frozenset({
    "CENTRAL_BANK_MACRO",
    "TARIFF_TRADE_WAR",
    "EXPORT_CONTROL_SANCTIONS",
})


def passes_radar_alert_gate(scored_item: Dict[str, Any]) -> Tuple[bool, str]:
    """
    score≥75 に加え、Discord 通知前のハードゲート。
    - カタリスト必須（銘柄＋急騰ワードだけでは通知しない）
    - 銘柄/ターゲット必須。ただしマクロカタリスト＋高信頼ソースは例外
    """
    catalysts = scored_item.get("detected_catalysts") or []
    catalyst_ids = scored_item.get("detected_catalyst_ids") or []
    targets = scored_item.get("matched_targets") or []
    entities = scored_item.get("matched_entities") or []

    if not catalysts or any("SPAM" in str(c) for c in catalysts):
        return False, "カタリスト未検出（銘柄＋急騰ワードのみは通知しない）"

    if targets or entities:
        return True, ""

    macro_hit = bool(set(catalyst_ids) & _MACRO_CATALYST_IDS)
    if not macro_hit:
        return False, "銘柄なし・マクロカタリスト以外"

    if scored_item.get("is_high_trust_source"):
        return True, ""

    from app.core.source_evaluator import evaluate_source_authority
    source = scored_item.get("source") or ""
    eval_res = evaluate_source_authority(
        scored_item.get("url", "") or "",
        scored_item.get("title", "") or "",
        source,
    )
    source_l = source.lower()
    is_high_trust = (
        eval_res.get("tier") == 1
        or "prnewswire" in source_l
        or "businesswire" in source_l
        or "reuters" in source_l
        or "bloomberg" in source_l
    )
    if is_high_trust:
        return True, ""
    return False, "マクロ例外だが高信頼ソースではない"


def verify_date_and_entity_attribution(
    text: str,
    source_raw: str,
    target_symbols: Optional[List[str]] = None,
    target_date: Optional[str] = None
) -> Tuple[bool, str]:
    """
    「数値は存在しても別の日付や別銘柄の数字を組み合わせてしまう」ハルシネーションを機械的に防ぐ。

    Returns:
        (ok, text) — ok=False のとき Discord アラートを棄却する。
    """
    if not text or not source_raw:
        return True, text

    is_num_ok, num_checked_text = verify_numbers_exist_in_source(text, source_raw)
    if not is_num_ok:
        logger.warning("🚨 [VerifyDateEntity] ソースに実在しない数値が含まれていたため、該当数値を削除・置換しました。")
        text = num_checked_text

    num_patterns = re.findall(r'(?:[\$￥€£]\s*\d+(?:\.\d+)?|\d+(?:\.\d+)?\s*(?:%|％|ドル|円|ポイント|pt))', text)
    if not num_patterns or not target_symbols:
        return True, text

    source_sentences = re.split(r'[。！？!\?]|\.(?!\d)', source_raw)

    for num_str in num_patterns:
        clean_num = num_str.strip()
        matching_sents = [s for s in source_sentences if clean_num in s]
        if not matching_sents:
            continue

        entity_co_occurs = False
        for s in matching_sents:
            s_lower = s.lower()
            for sym in target_symbols:
                if sym.lower() in s_lower:
                    entity_co_occurs = True
                    break
            if entity_co_occurs:
                break

        if target_date and not entity_co_occurs:
            for s in matching_sents:
                if target_date.lower() in s.lower() or "today" in s.lower() or "本日" in s.lower() or "今日" in s.lower():
                    entity_co_occurs = True
                    break

        if not entity_co_occurs and len(target_symbols) >= 1:
            logger.warning(
                f"🚨 [VerifyDateEntity] 数値 {clean_num} と主語銘柄 {target_symbols} の乖離を検知 — アラート棄却"
            )
            return False, text

    return True, text

def check_current_price_reaction(targets: List[str], entities: List[str]) -> str:
    """
    価格反応フィールド。実クォート未配線のため空文字を返し、Discord埋め込みでは非表示にする。
    """
    return ""

async def process_news_for_radar(
    news_items: List[Dict[str, Any]],
    dry_run: bool = False
) -> List[Dict[str, Any]]:
    """
    取得したニュースリストに対して、システマチック3層フィルターおよびDiscord配信を実行する。
    
    Returns:
        検証を通過し Discord へ通知（またはログ記録）されたアラートのリスト
    """
    await init_monitor_db()
    recent_alerts = await get_recent_alerts(hours=48)
    surviving_alerts = []
    rejected_items = []

    for item in news_items:
        # Tier 1: システマチックスクリーニング＆スコアリング 【APIコスト ¥0】
        scored_item = systematic_screen_and_score(item)
        if scored_item.get("importance", 0) < 75:
            rejected_items.append(scored_item)
            continue

        # Tier 1.5: カタリスト必須ハードゲート（銘柄＋急騰だけでは通知しない）
        gate_ok, gate_reason = passes_radar_alert_gate(scored_item)
        if not gate_ok:
            scored_item.setdefault("score_reasons", []).append(gate_reason)
            rejected_items.append(scored_item)
            continue

        # Tier 2: システマチック類似度・名寄せ判定 【APIコスト ¥0】
        is_dup, dup_reason = await systematic_deduplicate(scored_item, recent_alerts)
        if is_dup:
            scored_item["score_reasons"].append(dup_reason)
            rejected_items.append(scored_item)
            continue

        # Tier 3: ファクト検証＆属性紐付けチェック 【APIコスト ¥0〜極小】
        raw_summary = re.sub(r"<[^>]+>", "", scored_item.get("summary", "") or "")
        source_raw = re.sub(
            r"<[^>]+>",
            "",
            scored_item.get("body_text") or raw_summary or scored_item.get("title", "") or "",
        )
        targets = scored_item.get("matched_targets", [])
        entities = scored_item.get("matched_entities", [])

        # 1. 数値実在性チェック (verify_numbers_exist_in_source)
        is_num_ok, num_checked = verify_numbers_exist_in_source(raw_summary, source_raw)

        # 2. 日付×主語銘柄紐付けチェック（失敗時は Discord 棄却）
        attr_ok, entity_checked = verify_date_and_entity_attribution(
            num_checked,
            source_raw,
            target_symbols=entities + targets,
            target_date=datetime.now().strftime("%Y-%m-%d")
        )
        if not attr_ok:
            scored_item.setdefault("score_reasons", []).append("属性紐付け不一致により棄却")
            rejected_items.append(scored_item)
            continue

        # 3. 投資断定・推測の純化 (filter_fact)
        clean_fact = filter_fact(entity_checked)
        clean_fact = re.sub(r"<[^>]+>", "", clean_fact or "")
        # 万一古い経路で属性警告が残っていれば除去
        clean_fact = re.sub(r"\s*⚠️\s*\[属性紐付け確認要:[^\]]*\]", "", clean_fact)
        scored_item["verified_fact"] = clean_fact
        scored_item["price_reaction"] = check_current_price_reaction(targets, entities)

        # Discord Webhook へ送信
        success = await send_discord_alert(scored_item, dry_run=dry_run)
        if success:
            await save_alert_history(scored_item)
            surviving_alerts.append(scored_item)
            recent_alerts.insert(0, scored_item)

    # 弾かれた記事を rejected_news_log へ保管＆スマホ確認用のサマリーログ出力
    await log_rejected_news(rejected_items)
    if rejected_items:
        sorted_rejected = sorted(rejected_items, key=lambda x: x.get("importance", 0), reverse=True)[:5]
        summary_lines = [f"📉 [RadarEngine] 棄却ニュース TOP{len(sorted_rejected)}例 (スマホ確認用):"]
        for idx, r_it in enumerate(sorted_rejected, 1):
            r_title = (r_it.get("title") or "")[:50]
            r_score = r_it.get("importance", 0)
            r_reasons = ", ".join(r_it.get("score_reasons", [])) or "基本スコア(20pt)のみ・ターゲット一致なし"
            summary_lines.append(f"  {idx}. [{r_score}pt] 「{r_title}」 (理由: {r_reasons})")
        logger.info("\n".join(summary_lines))
    
    return surviving_alerts

async def run_radar_loop_once(dry_run: bool = False, test_feed: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """
    1回の巡回バッチを実行。オンデマンドニュースを取得し、プロセスパイプラインを通す。
    取得した全件（アラート化されなかったもの含む）をローリングプールへ蓄積する。
    """
    if test_feed is not None:
        raw_news = test_feed
    else:
        try:
            from app.core.news.fetcher import fetch_primary_news
            raw_news = await fetch_primary_news()
        except Exception as e:
            logger.warning(f"ニュース取得時に例外発生: {e} — モック検索またはDB空のまま続行します")
            raw_news = []

    logger.info(f"🛰️ [RadarEngine] 巡回開始: 取得ニュース件数 = {len(raw_news)} 件")

    # ローリングプールへ全件蓄積（72h retention）
    if raw_news and test_feed is None:
        try:
            from app.core.news.database import save_news, purge_old_news, init_db as init_news_db
            await init_news_db()
            inserted = await save_news(raw_news)
            purged = await purge_old_news()
            logger.info(f"🗂️ [RadarEngine] プール蓄積: inserted={inserted} purged={purged}")
        except Exception as e:
            logger.warning(f"プール蓄積に失敗（巡回は継続）: {e}")

    notified = await process_news_for_radar(raw_news, dry_run=dry_run)
    logger.info(f"🛰️ [RadarEngine] 巡回完了: アラート通知 = {len(notified)} 件 / 棄却・重複カット = {len(raw_news) - len(notified)} 件")
    return notified
