import json
import re
from typing import Any
from app.core.llm_client import call_model, DEFAULT_DEEPSEEK_CHAT_MODEL
from app.core.kv_store import kv_store
from app.utils.logger import get_logger

logger = get_logger(__name__)

MEMORY_SYSTEM_PROMPT = """あなたは会話からユーザーに関する記憶（メモリ）を自動抽出・更新するバックグラウンドエージェントです。
以下の会話内容を分析し、KVストア（ユーザーのプロフィール、好み、旅行や予定の日程スケジュール、将来のプロジェクト約束、開発ルールなどの記憶）に
追加、更新、または削除すべき情報があるか判定してください。

とくにユーザーが「〜に行くこと覚えておいて」「〜と覚えて」「日程を覚えて」などと明示的に指示した場合や重要な予定・旅行日程は必ず保存してください。
【厳格な禁止事項（一般知識・雑学の記憶禁止）】:
1. 会話の中で話題になった「一般知識・雑学・技術解説・レシピ・歴史・商品概要」（例: ヨーグルトの作り方、リンゴの歴史や栽培地域、発酵のメカニズム等）を「ユーザーのプロフィール(profile)」として記憶することを禁じます。
2. ウェブ検索結果や相場動向（例: 米国株の終値、経済ニュース）を記憶として保存することも禁止です。
3. 単なる「OK」「GO」「承認します」などの一時的な相槌や承認ステータスは絶対に保存しないでください。
保存して良いのは「ユーザー自身の明確な特徴・嗜好(preference)・重要予定(schedule)・プロジェクト開発の約束(project/rule)」等に限定してください。

追加すべき記憶がない場合（単なる雑学トークや質問対応の場合）は空の配列 `[]` を出力してください。
出力形式は以下のJSONの配列のみとしてください。それ以外のテキストは一切出力しないでください。

[
  {
    "action": "add" | "update" | "delete",
    "target_id": null,
    "category": "project" | "profile" | "preference" | "rule" | "exclusion" | "schedule",
    "quote": "ユーザー発言からの直接引用",
    "summary": {
      "target": "対象（例：伊豆旅行（7/19〜7/20）、顔写真保護アプリ開発等）",
      "stance": "予定" | "約束" | "好き" | "苦手" | "ルール",
      "note": "具体的な日程や行き先、詳細要約",
      "tags": ["旅行", "予定", "重要"]
    }
  }
]
"""

async def extract_and_save_memory(session_id: str, user_input: str, ai_response: str):
    """
    非同期で会話内容からメモリを抽出し、KVストアを更新する。

    ※ 現行チャット経路は Supervisor の kv_action + memory_policy ゲートを正とする。
      本関数はレガシー互換用。明示保存指示がない場合は LLM を呼ばず即 return。
    """
    from app.core.memory_policy import should_accept_kv_action, user_requests_memory_save

    if not user_requests_memory_save(user_input):
        logger.debug("extract_and_save_memory: 明示保存指示なしのためスキップ")
        return

    # すでに保存されている全メモリ一覧を渡し、重複や上書きを防ぐ
    current_memory = await kv_store.format_summary()
    
    prompt = f"【現在のメモリ状態】\n{current_memory}\n\n【今回の会話】\nユーザー: {user_input}\nAI: {ai_response}\n\n"
    prompt += "追加・更新・削除すべきメモリがあれば、JSON配列形式で出力してください。"
    
    try:
        from app.routers.settings import app_settings
        settings = app_settings.get()
        provider = settings.get("planner_provider", "deepseek")
        model_name = settings.get("planner_model", "deepseek-v4-flash")

        response_text = await call_model(
            system_instruction=MEMORY_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            model_name=model_name,
            provider=provider,
            max_tokens=1000
        )
        
        # JSONの配列部分を抽出
        match = re.search(r'\[.*\]', response_text, re.DOTALL)
        if match:
            json_str = match.group(0)
            actions = json.loads(json_str)
            
            for action_data in actions:
                action = action_data.get("action")
                ok, reason = should_accept_kv_action(user_input, action_data)
                if not ok:
                    logger.warning(f"自動メモリ抽出を拒否 ({reason}): {action_data.get('summary', {}).get('target')}")
                    continue
                if action == "add":
                    await kv_store.add(action_data)
                    logger.info(f"自動メモリ抽出: 追加 - {action_data.get('summary', {}).get('target')}")
                elif action == "update" and action_data.get("target_id"):
                    await kv_store.update(action_data["target_id"], action_data)
                    logger.info(f"自動メモリ抽出: 更新 - ID {action_data['target_id']}")
                elif action == "delete" and action_data.get("target_id"):
                    await kv_store.delete(action_data["target_id"])
                    logger.info(f"自動メモリ抽出: 削除 - ID {action_data['target_id']}")
    except json.JSONDecodeError:
        pass # JSONがない場合は何もしない
    except Exception as e:
        logger.error(f"Memory extraction failed: {e}")
