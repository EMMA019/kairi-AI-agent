"""KVメモリ・違和感ログの Pydantic モデル（仕様書 §3-1 準拠）"""
from pydantic import BaseModel
from typing import Literal, Optional
from datetime import datetime


class Summary(BaseModel):
    target: str
    stance: Optional[Literal["好き", "苦手", "条件付き"]] = None
    note: Optional[str] = None
    tags: Optional[list[str]] = None


class KVEntry(BaseModel):
    category: Literal["profile", "preference", "agreement", "exclusion"]
    quote: str  # ユーザー発言からの直接引用（40字以内）
    summary: Summary


class KVEntryWithId(KVEntry):
    id: int


class KVAction(BaseModel):
    """AIが出力するKV操作指示"""
    action: Literal["add", "update", "delete"]
    target_id: Optional[int] = None  # update/delete時のみ必須
    category: Optional[Literal["profile", "preference", "agreement", "exclusion"]] = None
    quote: Optional[str] = None
    summary: Optional[Summary] = None


class ViolationLog(BaseModel):
    session_id: str
    user_message: str
    ai_response: str
    violation_type: Literal["先回り提案", "KV無断記憶", "質問の連投", "過剰な称賛", "検索スキップ", "思考漏れ出し", "その他"]
    reason: Optional[str] = None
    timestamp: Optional[datetime] = None

