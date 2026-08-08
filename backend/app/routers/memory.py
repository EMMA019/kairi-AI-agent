"""KV メモリ API ルーター"""
from fastapi import APIRouter, HTTPException

from app.models.memory import KVEntry
from app.core.kv_store import kv_store
from app.core.memory_policy import is_junk_memory
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


@router.get("/kv")
async def get_all_memories():
    """KVメモリ一覧を取得"""
    return {"memories": await kv_store.get_all()}


@router.post("/kv")
async def add_memory(entry: KVEntry):
    """KVメモリを手動追加"""
    added = await kv_store.add(entry.model_dump())
    return {"success": True, "entry": added}


@router.delete("/kv/{entry_id}")
async def delete_memory(entry_id: int):
    """KVメモリを削除"""
    if not await kv_store.delete(entry_id):
        raise HTTPException(status_code=404, detail="Entry not found")
    return {"success": True}


@router.post("/kv/purge-junk")
async def purge_junk_memories():
    """ニュース・会話メタ・AI自己説明など長期記憶に不適切なエントリを一括削除する。"""
    memories = await kv_store.get_all()
    deleted_ids: list[int] = []
    for m in memories:
        if is_junk_memory(m):
            mid = m.get("id")
            if mid is not None and await kv_store.delete(int(mid)):
                deleted_ids.append(int(mid))
                logger.info(f"ジャンクKV削除: id={mid} target={m.get('summary', {}).get('target')}")
    return {"success": True, "deleted_count": len(deleted_ids), "deleted_ids": deleted_ids}
