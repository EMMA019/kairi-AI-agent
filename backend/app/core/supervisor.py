import json
import re
from typing import Any
from app.core.llm_client import call_model, DEFAULT_DEEPSEEK_REASONER_MODEL
from app.utils.logger import get_logger

logger = get_logger(__name__)

import os

def get_supervisor_system_prompt(category: str = "general") -> str:
    import os
    base_dir = os.path.join(os.path.dirname(__file__), '..', 'prompts')
    
    prompt = ""
    # Base prompt
    prompt_path = os.path.join(base_dir, 'supervisor_prompt.md')
    try:
        with open(prompt_path, 'r', encoding='utf-8') as f:
            prompt += f.read().strip() + "\n\n"
    except Exception as e:
        logger.error(f"Failed to load supervisor_prompt.md: {e}")
        return "あなたは沈黙AIの「思考・監督モデル」です。ユーザーへの回答は直接行わず、JSON形式のみを出力してください。"

    # Domain specific rules
    if category == "finance":
        cat_file = "supervisor_prompt_finance.md"
    elif category == "coding":
        cat_file = "supervisor_prompt_coding.md"
    elif category == "travel":
        cat_file = "supervisor_prompt_travel.md"
    else:
        cat_file = None
        
    if cat_file:
        try:
            with open(os.path.join(base_dir, cat_file), 'r', encoding='utf-8') as f:
                prompt += f.read().strip() + "\n\n"
        except FileNotFoundError:
            pass

    try:
        from app.routers.settings import app_settings
        from app.core.reply_language import build_reply_language_instruction

        locale = app_settings.get().get("locale", "en")
        prompt += "\n\n" + build_reply_language_instruction(locale).strip() + "\n"
        prompt += (
            "When writing `instruction.facts_to_present` / tone directives for the executor, "
            "use the reply language above (do not force Japanese translation of English sources "
            "when locale prefers English).\n"
        )
    except Exception:
        pass

    return prompt.strip()


def extract_json(text: str) -> dict[str, Any]:
    reasoning = ""
    reasoning_match = re.search(r'<think>\n?(.*?)\n?</think>', text, re.DOTALL)
    if reasoning_match:
        reasoning = reasoning_match.group(1).strip()

    text_for_json = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
    if not text_for_json and reasoning:
        text_for_json = reasoning

    def find_json_objects(s: str):
        from app.utils.parser import find_json_objects as _find
        return _find(s)

    objs = find_json_objects(text_for_json)
    if not objs and reasoning:
        objs = find_json_objects(reasoning)

    if not reasoning and objs:
        idx = text_for_json.find('{')
        if idx > 0:
            prefix = text_for_json[:idx].strip()
            prefix = re.sub(r'```(?:json)?$', '', prefix).strip()
            if len(prefix) > 10:
                reasoning = prefix

    data = None
    for obj_str in reversed(objs):
        try:
            parsed = json.loads(obj_str)
            if isinstance(parsed, dict) and ("instruction" in parsed or "search_used" in parsed or "silence" in parsed):
                data = parsed
                break
        except json.JSONDecodeError:
            continue

    if data is None:
        logger.error(f"Supervisor JSON parse error. Raw text: {text}")
        data = {
            "mode": "chat",
            "hearing_state": None,
            "spec_document": None,
            "search_used": False,
            "memory_inject": False,
            "silence": False,
            "tone": "casual",
            "instruction": {
                "facts_to_present": ["エラーが発生したこと"],
                "logical_order": ["適切に応答する"],
                "tone_directive": None
            },
            "plan": None,
            "violation_risk": None
        }

    if isinstance(data.get("instruction"), dict):
        inst = data["instruction"]
        inst.setdefault("tone_directive", None)
        
        # 新しいスキーマ(verified_facts / unverified_facts)を正規化して facts_to_present と統合する
        verified = inst.get("verified_facts", [])
        unverified = inst.get("unverified_facts", [])
        if isinstance(verified, list) or isinstance(unverified, list):
            combined = []
            if isinstance(verified, list):
                combined.extend(verified)
            if isinstance(unverified, list):
                combined.extend([f"⚠️ [未確認/二次ソース] {f}" if "未確認" not in str(f) and "二次ソース" not in str(f) else str(f) for f in unverified])
            if "facts_to_present" not in inst or not inst["facts_to_present"]:
                inst["facts_to_present"] = combined
            elif isinstance(inst["facts_to_present"], list):
                for f in combined:
                    if f not in inst["facts_to_present"]:
                        inst["facts_to_present"].append(f)
        
        if "facts_to_present" in inst:
            try:
                from app.core.fact_filter import filter_facts_to_present
                original_facts = inst["facts_to_present"]
                if isinstance(original_facts, list):
                    filtered_facts = filter_facts_to_present(original_facts)
                    inst["facts_to_present"] = filtered_facts
                    if "verified_facts" in inst and isinstance(inst["verified_facts"], list):
                        inst["verified_facts"] = filter_facts_to_present(inst["verified_facts"])
                    if "unverified_facts" in inst and isinstance(inst["unverified_facts"], list):
                        inst["unverified_facts"] = filter_facts_to_present(inst["unverified_facts"])
            except Exception as e:
                logger.error(f"Fact filter error: {e}")

    return data, reasoning


async def run_supervisor(
    user_input: str,
    search_results: str | None,
    memory_text: str | None,
    history_messages: list[dict],
    mode: str = "chat",
    system_instruction: str = "",
    category: str = "general",
) -> tuple[dict[str, Any], str]:
    """
    思考モデル (LLM) を呼び出し、回答方針 (JSON) と推論プロセス (reasoning) を取得する。
    """
    from app.core.ibkr.intent import ibkr_supervisor_shortcut

    ibkr_short = ibkr_supervisor_shortcut(user_input)
    if ibkr_short:
        logger.info("🏦 IBKR supervisor shortcut (run_supervisor)")
        return ibkr_short, ""

    context_parts = []

    if memory_text:
        context_parts.append(f"【関連メモリ】\n{memory_text}")
    if search_results:
        context_parts.append(f"【検索結果】\n{search_results}")

    context_parts.append(f"【ユーザー発言】\n{user_input}")

    prompt = "\n\n".join(context_parts)

    if mode == "task":
        prompt += "\n\n【現在のモード】 task (実装モード)\nユーザーは作業指示やコード生成を求めています。\n\n[重要: プラン提示の禁止と即実行ルール]\n地図作成・観光・お出かけ情報の検索や、シンプルなコード修正・スクリプト作成などの依頼においては、'plan' フィールドは必ず null に設定し、事前のプラン承認待ちを行わずにただちに 'instruction' へ実行指示を記述してください。\n'plan' フィールドにマークダウンを記述するのは、ユーザーが明示的に『計画を立てて』『プランを見せて』と要求した場合や、大規模リファクタリング等の極めて複雑なソフトウェアアーキテクチャ変更時のみに限定してください。\n\n[実行モデルへの指示ルール]\n'instruction' には、実行モデルに対して『ファイル作成・修正時は <file path=\"...\"> や <replace path=\"...\"> を用いること。また、状況把握が必要な場合は <read_file path=\"...\">, <list_dir path=\"...\">, <run_command>コマンド</run_command> 等を活用すること』というフォーマットルールを含めてください。\n【最重要ルール: 確認不要・連続作成指示の厳守】ユーザーが「確認せずに作って」「止めずに一気に作成して」「本物コードを作成して」等と指示している場合や実装フェーズにおいては、'instruction' 内で <read_file> や <list_dir> での事前確認ステップを指示してはなりません。直接目標のツールやファイルを一気通貫で出力させるよう指示を出してください。"

    prompt += "\n\n【重要】あなたはユーザーと直接対話するAIではなく、システム内部の「回答方針決定モジュール」です。過去の会話文脈やユーザーからの指摘にかかわらず、謝罪や返答などの文章は一切生成しないでください。必ず、指示された通りのJSON形式でのみ出力してください。"

    messages = history_messages + [{"role": "user", "content": prompt}]

    final_system_prompt = get_supervisor_system_prompt(category)

    from app.routers.settings import app_settings
    settings = app_settings.get()

    # ユーザー居住地情報をsupervisorプロンプトに注入（検索クエリ生成時の起点最適化）
    user_location = settings.get("user_location", "").strip()
    if user_location:
        final_system_prompt += f"\n\n【ユーザー居住地情報】\nユーザーの居住地は「{user_location}」です。旅行・お出かけ・乗り換え相談時には、このエリアをデフォルト出発地として検索クエリや移動手段の提案に活用してください。\n"
        
    if system_instruction:
        clean_sys_inst = re.sub(r'# 【出力フォーマット（厳守・列挙値は逸脱禁止）】.*', '', system_instruction, flags=re.DOTALL)
        final_system_prompt += "\n\n【共通システム指示（参考）】\n" + clean_sys_inst.strip()

    provider = settings.get("supervisor_provider", "deepseek")
    model_name = settings.get("supervisor_model", "deepseek-v4-flash")

    response_text = await call_model(
        system_instruction=final_system_prompt,
        messages=messages,
        model_name=model_name,
        provider=provider,
    )

    return extract_json(response_text)