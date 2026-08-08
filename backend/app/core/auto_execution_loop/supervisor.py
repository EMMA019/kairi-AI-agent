import json
import re
import asyncio
import uuid
import time
from typing import AsyncGenerator, Optional
from datetime import datetime
from pathlib import Path
from app.utils.logger import get_logger

logger = get_logger(__name__)
from app.core.llm_client import call_model
from app.routers.settings import get_settings
from app.core.supervisor import get_supervisor_system_prompt, run_supervisor

async def _analyze_with_supervisor(
    escalation_history: list,
    user_input: str,
    instruction: str,
    supervisor_sys_prompt: str,
    supervisor_dynamic_sys: str,
    mode: str,
    history_messages: list,
    yield_sse_func=None,
) -> Optional[str]:
    """
    Supervisorにエラー分析＋修正指示を依頼。
    
    Returns:
        新しい instruction（文字列）、または None（分析失敗）
    """
    try:
        if yield_sse_func:
            yield_sse_func({"type": "status", "status": "thinking"})
        
        escalation_context = "\n".join([
            f"【エラー #{i+1}】\n{e}"
            for i, e in enumerate(escalation_history[-3:])  # 最新3件のみ
        ])
        
        analysis_prompt = (
            f"【前回のツール実行でエラーが発生しました】\n"
            f"{escalation_context}\n\n"
            f"【元の指示】\n{instruction}\n\n"
            f"上記エラーを分析し、修正したコードやコマンドを、"
            f"再度 Executor が実行できる形で instruction.facts_to_present に指示してください。"
            f"絶対に推測で原因をでっち上げず、エラーメッセージに基づいて正確に分析してください。"
        )
        
        supervisor_json, reasoning = await run_supervisor(
            user_input=user_input + "\n\n" + analysis_prompt + "\n\n" + supervisor_dynamic_sys,
            search_results=None,
            memory_text=None,
            history_messages=history_messages,
            mode=mode,
            system_instruction=supervisor_sys_prompt,
        )
        
        if yield_sse_func and reasoning:
            yield_sse_func({"type": "reasoning", "content": reasoning})
        
        instruction_dict = supervisor_json.get("instruction", {})
        if isinstance(instruction_dict, dict):
            facts = instruction_dict.get("facts_to_present", [])
            order = instruction_dict.get("logical_order", [])
            new_instruction = ""
            if facts:
                new_instruction += "【必ず含めるべき事実】\n"
                for f in facts:
                    new_instruction += f"- {f}\n"
            if order:
                new_instruction += "\n【回答の構成（順序）】\n"
                for o in order:
                    new_instruction += f"- {o}\n"
            return new_instruction if new_instruction.strip() else None
        
        return None
        
    except Exception as e:
        logger.error(f"Supervisor analysis error: {e}")
        return None