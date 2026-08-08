"""ムード管理 API ルーター"""
from fastapi import APIRouter
from app.core.mood import get_mood

router = APIRouter()

@router.get("/mood")
async def get_current_mood():
    """現在のムード値を取得"""
    return get_mood()
