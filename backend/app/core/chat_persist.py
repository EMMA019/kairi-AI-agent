"""
チャット履歴の読み書き・トリミング。
"""
from __future__ import annotations

import json
import re
from app.core.database import get_db
from app.core.context_compressor import compress_messages_stage2
from app.utils.logger import get_logger

logger = get_logger(__name__)


def trim_history_content(content: str) -> str:
    if not content:
        return content

    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)
    content = re.sub(r"<think>(?:(?!</think>).)*$", "", content, flags=re.DOTALL)
    content = re.sub(
        r"(?m)^(?:まず、ユーザーの発言を分析します[^\n]*\n+|Output format:[^\n]*\n+|user_intent_analysis:[^\n]*\n+)+",
        "",
        content,
    )
    try:
        from app.core.fact_filters.markup import strip_tool_dump_blocks

        content = strip_tool_dump_blocks(content)
    except Exception:
        content = re.sub(
            r"【一般検索結果:.*?】\s*(?:\[[^\]]+\[Tier.*?\]\].*?\n?)+",
            "",
            content,
            flags=re.DOTALL,
        ).strip()

    if len(content) < 4000:
        return content

    def replace_code_block(match):
        block = match.group(0)
        if len(block) > 800:
            lang = match.group(1) or ""
            return f"```{lang}\n(※過去の長大なコード/ログ出力一部省略)\n```"
        return block

    content = re.sub(r"```([a-zA-Z0-9_-]*)\s*[\s\S]*?```", replace_code_block, content)

    if len(content) > 4000:
        content = content[:2000] + "\n\n(※過去の対話ログ一部省略)\n\n" + content[-2000:]

    return content


async def get_conversation_messages(session_id: str) -> list[dict]:
    """DB からセッションの会話履歴を取得（長大ブロックを自動トリミング）。"""
    try:
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT role, content, reasoning, search_sources, thinking_json FROM messages WHERE session_id = ? ORDER BY created_at",
                (session_id,),
            )
            rows = await cursor.fetchall()
            messages = []
            for row in rows:
                msg = {
                    "role": row[0],
                    "content": trim_history_content(row[1]),
                    "reasoning": row[2] if len(row) > 2 else None,
                }
                raw_sources = row[3] if len(row) > 3 and row[3] else None
                if raw_sources and len(str(raw_sources)) > 5000:
                    msg["sources"] = None
                else:
                    msg["sources"] = json.loads(raw_sources) if raw_sources else None
                raw_thinking = row[4] if len(row) > 4 else None
                if raw_thinking and len(str(raw_thinking)) > 10000:
                    msg["thinking_json"] = None
                else:
                    msg["thinking_json"] = raw_thinking
                messages.append(msg)
            return await compress_messages_stage2(messages, max_keep=3)
    except Exception as e:
        logger.error(f"履歴取得エラー: {e}")
        return []


def trim_for_db(content: str, max_len: int = 30000) -> str:
    if not content or len(content) <= max_len:
        return content
    half = max_len // 2
    return content[:half] + "\n\n(※システム保護のため一部省略)\n\n" + content[-half:]


async def save_messages(
    session_id: str,
    user_message: str,
    ai_response: str,
    raw_response: str,
    json_data: dict | None,
    reasoning: str | None = None,
    search_sources: list[dict] | None = None,
):
    """ユーザーメッセージとAI応答をDBに保存（コンテンツは自動トリミング）。"""
    try:
        async with get_db() as db:
            trimmed_user = trim_for_db(user_message)
            trimmed_ai = trim_for_db(ai_response)
            trimmed_raw = trim_for_db(raw_response, max_len=5000)
            title = user_message[:30] + "..." if len(user_message) > 30 else user_message
            await db.execute(
                "INSERT OR IGNORE INTO sessions (id, title) VALUES (?, ?)",
                (session_id, title),
            )
            await db.execute(
                "UPDATE sessions SET title = ? WHERE id = ? AND title IS NULL",
                (title, session_id),
            )
            await db.execute(
                "INSERT INTO messages (session_id, role, content) VALUES (?, 'user', ?)",
                (session_id, trimmed_user),
            )
            await db.execute(
                "INSERT INTO messages (session_id, role, content, raw_response, thinking_json, reasoning, search_sources) "
                "VALUES (?, 'assistant', ?, ?, ?, ?, ?)",
                (
                    session_id,
                    trimmed_ai,
                    trimmed_raw,
                    json.dumps(json_data, ensure_ascii=False) if json_data else None,
                    reasoning,
                    json.dumps(search_sources, ensure_ascii=False) if search_sources else None,
                ),
            )

            if json_data:
                instruction = json_data.get("instruction", {})
                verified_facts = 0
                unverified_facts = 0
                if isinstance(instruction, dict):
                    v_facts = instruction.get("verified_facts")
                    u_facts = instruction.get("unverified_facts")
                    if isinstance(v_facts, list):
                        verified_facts = len(v_facts)
                    if isinstance(u_facts, list):
                        unverified_facts = len(u_facts)

                citations = len(search_sources) if search_sources else 0
                excluded_sources = 0
                truncation_detected = 0
                trim_applied = 0
                uncited_assertions = 0
                try:
                    from app.core.fact_filters.citation import get_last_citation_metrics

                    m = get_last_citation_metrics()
                    truncation_detected = int(getattr(m, "truncation_detected", 0) or 0)
                    trim_applied = int(getattr(m, "trim_applied", 0) or 0)
                    uncited_assertions = int(getattr(m, "uncited_assertions", 0) or 0)
                    if getattr(m, "citations_found", 0):
                        citations = max(citations, int(m.citations_found))
                except Exception:
                    pass

                await db.execute(
                    "INSERT INTO integrity_stats ("
                    "session_id, verified_facts, unverified_facts, excluded_sources, citations, "
                    "truncation_detected, trim_applied, uncited_assertions"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        session_id,
                        verified_facts,
                        unverified_facts,
                        excluded_sources,
                        citations,
                        truncation_detected,
                        trim_applied,
                        uncited_assertions,
                    ),
                )

            await db.execute(
                "UPDATE sessions SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (session_id,),
            )
            await db.commit()
    except Exception as e:
        logger.error(f"メッセージ保存エラー: {e}")
