"""News health / briefing API"""
from fastapi import APIRouter, HTTPException, Query
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


@router.get("/news/health")
async def news_health():
    """フィード健全性とローリングプール件数を返す。"""
    from app.core.news.database import (
        init_db,
        get_feed_health,
        count_pool,
        get_pool_news,
        RETENTION_HOURS,
    )

    await init_db()
    feeds = await get_feed_health()
    pool_total = await count_pool()
    recent_18h = await get_pool_news(hours=18, limit=500)
    failing = [f for f in feeds if (f.get("consecutive_failures") or 0) >= 3]
    return {
        "pool_total": pool_total,
        "pool_last_18h": len(recent_18h),
        "retention_hours": RETENTION_HOURS,
        "feeds": feeds,
        "feeds_failing": len(failing),
        "ok": len(failing) == 0 or pool_total > 0,
    }


@router.post("/briefing/generate")
async def generate_briefing_now(
    kind: str = Query("preopen", pattern="^(preopen|postclose)$"),
    dry_run: bool = Query(False),
):
    """手動でブリーフィング下書きを生成（目視確認用）。"""
    from app.core.briefing.generator import generate_briefing

    result = await generate_briefing(kind, dry_run=dry_run)  # type: ignore[arg-type]
    return {
        "success": True,
        "kind": result["kind"],
        "path": result["path"],
        "story_count": result["story_count"],
        "pool_count": result["pool_count"],
        "dry_run": result["dry_run"],
        "has_commentary": result.get("has_commentary", False),
        "preview": (result.get("markdown") or "")[:2000],
    }


@router.get("/briefing/list")
async def briefing_list():
    """保存済みブリーフィング一覧。"""
    from app.core.briefing.generator import list_briefing_files

    return {"files": list_briefing_files()}


@router.get("/briefing/file/{filename}")
async def briefing_file(filename: str):
    """ブリーフィング本文（パストラバーサル対策済み）。"""
    from app.core.briefing.generator import read_briefing_file

    try:
        content = read_briefing_file(filename)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid filename")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="not found")
    return {"filename": filename, "content": content}
