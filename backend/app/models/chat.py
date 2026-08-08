"""チャット関連の Pydantic モデル（仕様書 §3-1 準拠）"""
from pydantic import BaseModel
from typing import Literal, Optional
from datetime import datetime


class ChatRequest(BaseModel):
    message: str
    session_id: str
    mode: Literal["chat", "task", "stocks", "char"] = "chat"
    force_search: bool = False  # UIの🔍ボタン用


class ChatMessage(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    timestamp: datetime


class SessionCreate(BaseModel):
    title: Optional[str] = None


class SessionInfo(BaseModel):
    session_id: str
    title: Optional[str] = None
    created_at: str
    updated_at: str


class ModeRequest(BaseModel):
    mode: Literal["chat", "task", "stocks", "char"]
