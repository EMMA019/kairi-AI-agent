"""
greeting / char モードのショートサーキット。
"""
from __future__ import annotations

import json
import re
from typing import AsyncGenerator, Optional
from app.core.cache_manager import check_greeting_short_circuit
from app.core.chat_pipeline import (
    stream_simple_executor,
    build_greeting_system_prompt,
    build_facts_instruction,
)
from app.core.chat_persist import save_messages
from app.routers.settings import app_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def try_greeting_mode(
    *,
    user_input: str,
    mode: str,
    force_search: bool,
    messages: list,
    filtered_kv_text: str,
    is_hyper_gal: bool,
    session_id: str,
) -> AsyncGenerator[dict, None]:
    """
    挨拶ショートサーキット。処理した場合は SSE イベントを yield し、
    最後に {"type": "_handled"} を送る。未処理なら何も yield しない。
    """
    if mode != "chat" or force_search:
        return
    greeting_json = check_greeting_short_circuit(user_input)
    if not greeting_json:
        return

    yield {"type": "mode_switch", "mode": "chat"}
    settings_dict = app_settings.get()
    persona_style = settings_dict.get("persona_style", "standard")
    locale = settings_dict.get("locale", "en")
    greeting_sys = build_greeting_system_prompt(persona_style, locale=locale)
    greeting_instruction = build_facts_instruction(greeting_json.get("instruction") or {})
    async for ev, payload in stream_simple_executor(
        user_input=user_input,
        instruction=greeting_instruction,
        system_instruction=greeting_sys,
        history_messages=messages,
        memory_text=filtered_kv_text if greeting_json.get("memory_inject") else None,
        mode="chat",
        is_hyper_gal=is_hyper_gal,
    ):
        if ev == "chunk":
            yield {"type": "chunk", "content": payload}
        elif ev == "done":
            await save_messages(
                session_id,
                user_input,
                payload,
                json.dumps(greeting_json, ensure_ascii=False),
                greeting_json,
                None,
                [],
            )
            yield {"type": "done", "content": payload, "ok": bool((payload or "").strip())}
    yield {"type": "_handled"}


async def try_char_mode(
    *,
    user_input: str,
    mode: str,
    messages: list,
    filtered_kv_text: str,
    is_hyper_gal: bool,
    session_id: str,
) -> AsyncGenerator[tuple[dict, Optional[str]], None]:
    """
    char モード。yield する値は (sse_dict, updated_user_input_or_None)。
    処理完了時は ({"type": "_handled"}, user_input) 。
    """
    entered = mode == "char" or user_input.strip().startswith("/char") or user_input.strip().startswith("/roleplay")
    if not entered:
        return

    if user_input.strip().startswith("/char") or user_input.strip().startswith("/roleplay"):
        user_input = re.sub(r"^/(char|roleplay)\s*", "", user_input).strip()
        if not user_input:
            user_input = "よろしくね！"

    yield ({"type": "mode_switch", "mode": "char"}, user_input)

    from app.core.char_persona import get_char_system_prompt

    settings_dict = app_settings.get()
    persona_style = settings_dict.get("persona_style", "standard")
    char_profile = settings_dict.get("char_profile", "")
    visual_anchor = settings_dict.get("visual_anchor", "")
    user_name = settings_dict.get("user_name", "you")
    locale = settings_dict.get("locale", "en")
    char_sys = get_char_system_prompt(
        user_name, char_profile, persona_style, visual_anchor, locale=locale
    )
    char_instruction = (
        "Stay in character and keep the conversation natural and fun."
        if str(locale).lower().startswith("en")
        else "キャラクターになりきって、ユーザーとの会話を自然かつテンポよく楽しく盛り上げてください。"
    )
    async for ev, payload in stream_simple_executor(
        user_input=user_input,
        instruction=char_instruction,
        system_instruction=char_sys,
        history_messages=messages,
        memory_text=filtered_kv_text or None,
        mode="char",
        is_hyper_gal=is_hyper_gal,
    ):
        if ev == "chunk":
            yield ({"type": "chunk", "content": payload}, None)
        elif ev == "done":
            await save_messages(
                session_id,
                user_input,
                payload,
                json.dumps({"mode": "char", "status": "char_fast_response"}, ensure_ascii=False),
                {"mode": "char", "fast": True},
                None,
                [],
            )
            yield ({"type": "done", "content": payload, "ok": bool((payload or "").strip())}, None)
    yield ({"type": "_handled"}, user_input)
