"""
Proactive Market Radar Scheduler — Render等クラウド環境下での24時間365日無人自動巡回バッチ

機能:
1. FastAPI/Kairi起動時に自動で非同期タスクとして立ち上がるバッチループ
2. 30分おきに最新ニュースを取得しシステマチック3層検証を実行
3. カタリスト初動検知時のみ Discord Webhook へ自動速報配信
"""
import asyncio
from typing import Optional
from app.utils.logger import get_logger
from app.core.monitor.engine import run_radar_loop_once

logger = get_logger(__name__)

_radar_task: Optional[asyncio.Task] = None
_is_running: bool = False
RADAR_INTERVAL_SECONDS = 1800  # 30分おきに自動巡回

async def _radar_background_loop():
    """30分間隔で初動レーダー巡回を実行するループタスク"""
    global _is_running
    _is_running = True
    logger.info(f"🛰️ [RadarScheduler] 24時間無人監視ループを起動しました（インターバル: {RADAR_INTERVAL_SECONDS}秒 / 30分）")
    
    # 起動直後の初動スキャン（少し待機してアプリ全体安定後）
    await asyncio.sleep(15)
    
    while _is_running:
        try:
            logger.info("🛰️ [RadarScheduler] 定期初動パトロール実行開始...")
            await run_radar_loop_once(dry_run=False)
        except Exception as e:
            logger.error(f"❌ [RadarScheduler] パトロール中に例外発生: {e}")
        
        # 次回パトロールまで待機
        for _ in range(RADAR_INTERVAL_SECONDS):
            if not _is_running:
                break
            await asyncio.sleep(1)

    logger.info("🛑 [RadarScheduler] 監視ループが正常に停止しました")

def start_radar_scheduler():
    """監視ループを開始（FastAPIのlifespan等から呼び出し）"""
    global _radar_task, _is_running
    if _radar_task is not None and not _radar_task.done():
        logger.info("⚠️ [RadarScheduler] 既に監視ループが稼働中です")
        return
    _is_running = True
    _radar_task = asyncio.create_task(_radar_background_loop())
    logger.info("🚀 [RadarScheduler] バックグラウンドタスクを作成・登録しました")

def stop_radar_scheduler():
    """監視ループを停止"""
    global _is_running, _radar_task
    _is_running = False
    if _radar_task is not None:
        _radar_task.cancel()
        _radar_task = None
    logger.info("🛑 [RadarScheduler] 停止信号を送信しました")
