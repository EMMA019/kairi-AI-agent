from fastapi import APIRouter
from app.core.database import get_db
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

@router.get("/integrity/stats")
async def get_integrity_stats():
    """累計の誠実さ（インテグリティ）統計を取得"""
    empty = {
        "verified_facts": 0,
        "unverified_facts": 0,
        "excluded_sources": 0,
        "citations": 0,
        "search_executions": 0,
        "truncation_detected": 0,
        "trim_applied": 0,
        "uncited_assertions": 0,
    }
    try:
        async with get_db() as db:
            cursor = await db.execute("""
                SELECT 
                    SUM(verified_facts) as verified_facts,
                    SUM(unverified_facts) as unverified_facts,
                    SUM(excluded_sources) as excluded_sources,
                    SUM(citations) as citations,
                    COUNT(*) as search_executions,
                    COALESCE(SUM(truncation_detected), 0) as truncation_detected,
                    COALESCE(SUM(trim_applied), 0) as trim_applied,
                    COALESCE(SUM(uncited_assertions), 0) as uncited_assertions
                FROM integrity_stats
            """)
            row = await cursor.fetchone()
            
            if row:
                return {
                    "verified_facts": row[0] or 0,
                    "unverified_facts": row[1] or 0,
                    "excluded_sources": row[2] or 0,
                    "citations": row[3] or 0,
                    "search_executions": row[4] or 0,
                    "truncation_detected": row[5] or 0,
                    "trim_applied": row[6] or 0,
                    "uncited_assertions": row[7] or 0,
                }
            return empty
    except Exception as e:
        logger.error(f"Integrity stats fetch error: {e}")
        return empty
