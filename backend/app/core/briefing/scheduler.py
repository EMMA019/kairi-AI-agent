"""
ブリーフィング・スケジューラ — JST 08:15 寄り前 / 16:00 大引け後。
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

JST = timezone(timedelta(hours=9))

_task: Optional[asyncio.Task] = None
_stop = asyncio.Event()


def _seconds_until(hour: int, minute: int, now: Optional[datetime] = None) -> float:
    now = now or datetime.now(JST)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target = target + timedelta(days=1)
    return max(1.0, (target - now).total_seconds())


async def _briefing_loop():
    logger.info("🗓️ [BriefingScheduler] JST 08:15 / 16:00 ループ起動")
    while not _stop.is_set():
        now = datetime.now(JST)
        # 次の寄り前 or 大引け後の近い方まで待つ
        sec_pre = _seconds_until(8, 15, now)
        sec_post = _seconds_until(16, 0, now)
        if sec_pre <= sec_post:
            wait_s, kind = sec_pre, "preopen"
        else:
            wait_s, kind = sec_post, "postclose"

        logger.info(f"🗓️ [BriefingScheduler] next={kind} in {wait_s/60:.1f} min")
        try:
            await asyncio.wait_for(_stop.wait(), timeout=wait_s)
            break  # stop signaled
        except asyncio.TimeoutError:
            pass

        if _stop.is_set():
            break

        try:
            from app.core.briefing.generator import generate_briefing

            result = await generate_briefing(kind)  # type: ignore[arg-type]
            logger.info(
                f"🗓️ [BriefingScheduler] generated {kind}: "
                f"stories={result.get('story_count')} path={result.get('path')}"
            )
        except Exception as e:
            logger.error(f"❌ [BriefingScheduler] {kind} 生成失敗: {e}")

        # 同じスロットの再実行を避けるため最低61秒待つ
        try:
            await asyncio.wait_for(_stop.wait(), timeout=61)
            break
        except asyncio.TimeoutError:
            pass

    logger.info("🛑 [BriefingScheduler] 停止しました")


def start_briefing_scheduler():
    global _task
    if _task and not _task.done():
        logger.info("⚠️ [BriefingScheduler] 既に稼働中")
        return
    _stop.clear()
    _task = asyncio.create_task(_briefing_loop())
    logger.info("🚀 [BriefingScheduler] バックグラウンドタスク登録")


def stop_briefing_scheduler():
    global _task
    _stop.set()
    if _task and not _task.done():
        _task.cancel()
    _task = None
    logger.info("🛑 [BriefingScheduler] 停止信号送信")
