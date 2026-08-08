"""
chat.py から切り出した共通ステージヘルパー。
greeting / char モードのストリーミング重複を統合する。
"""
from __future__ import annotations

import re
from typing import AsyncGenerator, Optional
from app.core.executor import run_executor
from app.core.gyaru import to_hyper_gal_v3


def strip_think_tags(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"<think>(?:(?!</think>).)*$", "", text, flags=re.DOTALL)
    return text.strip()


def finalize_response_text(text: str, *, is_hyper_gal: bool = False) -> str:
    try:
        from app.core.fact_filters.markup import strip_internal_markup
        text = strip_internal_markup(text or "")
    except Exception:
        text = strip_think_tags(text or "")
    try:
        from app.core.fact_filter import trim_incomplete_trailing_sentence, strip_dangling_tool_promises
        text = strip_dangling_tool_promises(text)
        text = trim_incomplete_trailing_sentence(text)
    except Exception:
        pass
    if is_hyper_gal and text:
        text = to_hyper_gal_v3(text)
    return text


async def stream_simple_executor(
    *,
    user_input: str,
    instruction: str,
    system_instruction: str,
    history_messages: list,
    memory_text: Optional[str] = None,
    search_results: Optional[str] = None,
    mode: str = "chat",
    is_hyper_gal: bool = False,
    yield_chunks: bool = True,
) -> AsyncGenerator[tuple[str, Optional[str]], None]:
    """
    Executor をストリームし、(event_type, payload) を yield する。
    event_type: "chunk" | "done"
    """
    stream = run_executor(
        user_input=user_input,
        instruction=instruction,
        search_results=search_results,
        memory_text=memory_text,
        history_messages=history_messages,
        mode=mode,
        system_instruction=system_instruction,
    )
    response_text = ""
    in_think = False
    async for chunk in stream:
        if "<think>" in chunk:
            in_think = True
        if "</think>" in chunk:
            in_think = False
            response_text += chunk
            continue
        response_text += chunk
        if yield_chunks and not is_hyper_gal and not in_think:
            yield ("chunk", chunk)

    response_text = finalize_response_text(response_text, is_hyper_gal=is_hyper_gal)
    yield ("done", response_text)


def build_greeting_system_prompt(persona_style: str, locale: str = "en") -> str:
    from app.core.reply_language import build_greeting_system_prompt as _build

    return _build(persona_style, locale)


def build_facts_instruction(instruction_dict: dict) -> str:
    facts = instruction_dict.get("facts_to_present", []) if isinstance(instruction_dict, dict) else []
    order = instruction_dict.get("logical_order", []) if isinstance(instruction_dict, dict) else []
    parts = []
    if facts:
        parts.append("【必ず含めるべき事実】\n" + "\n".join(f"- {f}" for f in facts))
    if order:
        parts.append("【回答の構成（順序）】\n" + "\n".join(f"- {o}" for o in order))
    return "\n\n".join(parts)
