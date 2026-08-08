"""会話履歴 API ルーター"""
import uuid
from fastapi import APIRouter, HTTPException

from app.models.chat import SessionCreate, SessionInfo
from app.core.database import get_db

router = APIRouter()


@router.post("/history")
async def create_session(request: SessionCreate = None):
    """新規セッションを作成"""
    session_id = str(uuid.uuid4())
    title = request.title if request else None

    async with get_db() as db:
        await db.execute(
            "INSERT INTO sessions (id, title) VALUES (?, ?)",
            (session_id, title),
        )
        await db.commit()

    return {"session_id": session_id}


@router.get("/history")
async def list_sessions():
    """全セッション一覧を取得（メッセージ数付き）"""
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT 
                s.id, s.title, s.created_at, s.updated_at,
                COUNT(m.id) as message_count
            FROM sessions s
            LEFT JOIN messages m ON s.id = m.session_id
            GROUP BY s.id
            ORDER BY s.updated_at DESC
            """
        )
        rows = await cursor.fetchall()

    return {
        "sessions": [
            {
                "session_id": row[0],
                "title": row[1] or "新規チャット",
                "created_at": row[2],
                "updated_at": row[3],
                "message_count": row[4],
            }
            for row in rows
        ]
    }


@router.get("/history/{session_id}")
async def get_history(session_id: str):
    """指定セッションの会話履歴を取得"""
    async with get_db() as db:
        # セッション存在確認
        cursor = await db.execute(
            "SELECT id FROM sessions WHERE id = ?", (session_id,)
        )
        if not await cursor.fetchone():
            raise HTTPException(status_code=404, detail="Session not found")

        # メッセージ取得
        cursor = await db.execute(
            "SELECT id, role, content, created_at, reasoning, search_sources FROM messages "
            "WHERE session_id = ? ORDER BY created_at",
            (session_id,),
        )
        rows = await cursor.fetchall()

    import json
    return {
        "messages": [
            {
                "id": str(row[0]),
                "role": row[1],
                "content": row[2],
                "timestamp": row[3],
                "reasoning": row[4] if len(row) > 4 else None,
                "sources": json.loads(row[5]) if len(row) > 5 and row[5] else None,
            }
            for row in rows
        ]
    }


@router.delete("/history/{session_id}")
async def delete_session(session_id: str):
    """セッションと関連メッセージを削除"""
    async with get_db() as db:
        await db.execute("DELETE FROM integrity_stats WHERE session_id = ?", (session_id,))
        await db.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        await db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        await db.commit()

    # メモリリーク防止: クールダウン履歴・検索キャリーから削除
    from app.routers.chat import _followup_histories
    if session_id in _followup_histories:
        del _followup_histories[session_id]
    from app.core.chat_search import clear_search_carryover
    clear_search_carryover(session_id)

    # Docker サンドボックスのコンテナも削除
    from app.core.sandbox import cleanup_sandbox
    cleanup_sandbox(session_id)

    return {"success": True}
