"""
Context Compressor — 会話履歴の2段階圧縮（413エラー対策版）

【413 Request Entity Too Large 対策】
- openresty（リバースプロキシ）の上限1MBを超えないよう圧縮を強化
- 第1段階: 長大なコードブロック/ログを意味を保ったまま圧縮（400文字上限）
- 第2段階: 古い会話ターンを軽量LLMで要約（最新3ターンのみ保持）
"""
import json
import re
from typing import Optional
from app.utils.logger import get_logger

logger = get_logger(__name__)


def compress_content_stage1(content: str, max_length: int = 2000) -> str:
    """
    第1段階: 長大なコードブロック・ログ出力を圧縮。
    max_length: 2000文字
    """
    if not content or len(content) <= max_length:
        return content
    
    # コードブロックの圧縮
    def _compress_code_block(match):
        block = match.group(0)
        lang = match.group(1) or ""
        inner = match.group(2)
        
        lines = inner.split('\n')
        if len(lines) <= 20:
            return block
        
        head = '\n'.join(lines[:8])
        tail = '\n'.join(lines[-8:])
        return f"```{lang}\n{head}\n... [{len(lines) - 16} lines omitted] ...\n{tail}\n```"
    
    content = re.sub(r'```(\w*)\n([\s\S]*?)```', _compress_code_block, content)
    
    # <file>タグ内の圧縮
    def _compress_file_tag(match):
        path = match.group(1)
        inner = match.group(2)
        lines = inner.split('\n')
        if len(lines) <= 20:
            return match.group(0)
        
        head = '\n'.join(lines[:8])
        tail = '\n'.join(lines[-8:])
        return f'<file path="{path}">\n{head}\n... [{len(lines) - 16} lines omitted] ...\n{tail}\n</file>'
    
    content = re.sub(r'<file path="([^"]+)">\n([\s\S]*?)</file>', _compress_file_tag, content)
    
    # 画像（Base64）の圧縮（完全省略）
    content = re.sub(r'<attached_image\s+filename="([^"]+)"\s+mime="[^"]+">\n.*?\n</attached_image>', r'[Attached Image Omitted: \1]', content, flags=re.DOTALL)
    
    # それでも長い場合: 先頭1000文字 + 末尾1000文字
    if len(content) > max_length:
        half = max_length // 2
        content = content[:half] + "\n\n(※過去の対話ログ一部省略)\n\n" + content[-half:]
    
    return content


async def compress_messages_stage2(
    messages: list[dict],
    max_keep: int = 3,
) -> list[dict]:
    """
    第2段階: 古いターンを圧縮（会話履歴の長期保存対策）。
    max_keep: 3ターンのみ保持（413エラー対策で6→3に強化）
    
    Returns:
        圧縮されたメッセージリスト（最新3ターン + LLM要約）
    """
    if not messages:
        return []
    
    total_tokens_estimate = sum(len(m.get("content", "")) for m in messages)
    logger.info(f"📊 圧縮前: {len(messages)}ターン, 推定{total_tokens_estimate}文字")
    
    if len(messages) <= max_keep:
        logger.info(f"メッセージ圧縮: {len(messages)}ターン → {len(messages)}ターン（圧縮不要）")
        return messages
    
    # 最新のターンを保持
    keep_messages = messages[-max_keep:]
    
    # 古いターンを圧縮（長大なコードブロックやファイル内容をトリミング）
    old_messages = messages[:-max_keep]
    compressed_old = []
    
    for msg in old_messages:
        content = msg.get("content", "")
        content = compress_content_stage1(content, max_length=2000)
        compressed_old.append({**msg, "content": content})
    
    # 古いターンをLLMを使って要約する
    from app.core.llm_client import call_model
    from app.routers.settings import get_settings

    settings = await get_settings()
    planner_model = settings.get("planner_model", "deepseek-v4-flash")
    planner_provider = settings.get("planner_provider", "deepseek")

    old_convo_str = ""
    for msg in compressed_old:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        old_convo_str += f"[{role}]: {content}\n\n"

    system_instruction = (
        "あなたはAIアシスタントのコンテキスト圧縮モジュールです。\n"
        "以下の古い会話履歴を読み、重要な事実（ファクト）を抽出し、以下のJSON形式のみを出力してください。\n"
        "{\n"
        "  \"summary\": \"会話全体の簡潔な要約（箇条書き等）\",\n"
        "  \"key_facts\": [\n"
        "    {\"target\": \"銘柄名や話題（例：半導体株, 予算）\", \"note\": \"関連ファクトや方針（例：短期狙いだった, 10万円以内）\"}\n"
        "  ]\n"
        "}\n"
        "細かい挨拶や不要な相槌は省き、後続の会話でAIが文脈を見失わないための引き継ぎメモを作成してください。"
    )
    
    try:
        # LLMでの要約実行（高速なプランナーモデル等を使用）
        summary_result = await call_model(
            system_instruction=system_instruction,
            messages=[{"role": "user", "content": old_convo_str}],
            model_name=planner_model,
            provider=planner_provider,
            temperature=0.3
        )
    except Exception as e:
        logger.error(f"要約圧縮中のLLM呼び出しエラー: {e}")
        # フォールバック: 元の切り詰めロジック
        summary_result = "\n".join([f"[{m.get('role', 'unknown')}]: {m.get('content', '')[:200]}..." for m in compressed_old[-5:]])

    import re
    import json

    # DeepSeek Reasoning などの <think> タグを除去する
    summary_result = re.sub(r'<think>.*?</think>', '', summary_result, flags=re.DOTALL).strip()

    # JSON抽出のみ。key_facts は履歴要約に折り込む（永続KVへの書き込みは禁止＝増殖防止）
    extracted_summary = summary_result
    try:
        from app.utils.parser import find_json_objects
        objs = find_json_objects(summary_result)
        if objs:
            data = json.loads(objs[0])
            extracted_summary = data.get("summary", extracted_summary)
            key_facts = data.get("key_facts", []) or []
            fact_lines = []
            for fact in key_facts:
                if not isinstance(fact, dict):
                    continue
                target = (fact.get("target") or "").strip()
                note = (fact.get("note") or "").strip()
                if target and note:
                    fact_lines.append(f"- {target}: {note}")
            if fact_lines:
                extracted_summary = (
                    f"{extracted_summary}\n\n【引き継ぎファクト】\n" + "\n".join(fact_lines)
                )
                logger.info(f"圧縮 key_facts を要約に折込（KV未書き込み）: {len(fact_lines)}件")
    except Exception as e:
        logger.error(f"圧縮モジュールのJSONパースエラー: {e}")

    summary_text = (
        "【過去の会話の重要コンテキスト要約】\n"
        f"※これより前に行われた合計{len(old_messages)}ターンの会話の要約です。\n\n"
        f"{extracted_summary}\n\n"
        "【要約終了】"
    )
    
    # 圧縮結果を先頭に挿入
    result = [{"role": "user", "content": summary_text}] + keep_messages
    
    total_after = sum(len(m.get("content", "")) for m in result)
    logger.info(f"📉 圧縮後: {len(result)}ターン, 推定{total_after}文字 (削減率{((total_tokens_estimate - total_after) / max(total_tokens_estimate, 1) * 100):.0f}%)")
    
    return result