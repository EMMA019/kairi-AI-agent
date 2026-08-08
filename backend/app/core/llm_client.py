"""
LLM 呼び出しラッパー（Anthropic Claude, OpenAI 互換 API, Gemini 公式 SDK）。
ローカルLLM (Ollama等) にも対応。
2026年6月現在の最新フラッグシップモデルに最適化済み。
"""
from __future__ import annotations

import os
import re
import base64
from typing import AsyncGenerator
try:
    import anthropic
except ImportError:
    anthropic = None

try:
    import openai
except ImportError:
    openai = None

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None
from app.utils.logger import get_logger
from app.core.usage_tracker import check_budget, record_usage
from fastapi import HTTPException
import tiktoken
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type

logger = get_logger(__name__)

def _parse_gemini_parts(content: str) -> list:
    """メッセージ文字列からテキストと画像を分離してGeminiのPartリストを作成する"""
    parts = []
    # <attached_image filename="..." mime="...">base64...</attached_image> を検索
    pattern = re.compile(r'<attached_image\s+filename="[^"]*"\s+mime="([^"]+)">\n(.*?)\n</attached_image>', re.DOTALL)
    
    last_end = 0
    for match in pattern.finditer(content):
        # 画像の前のテキストを追加
        if match.start() > last_end:
            text_part = content[last_end:match.start()].strip()
            if text_part:
                parts.append(types.Part.from_text(text=text_part))
        
        # 画像パートを追加
        mime_type = match.group(1)
        b64_data = match.group(2).strip()
        try:
            image_bytes = base64.b64decode(b64_data)
            parts.append(types.Part.from_bytes(data=image_bytes, mime_type=mime_type))
        except Exception as e:
            logger.warning(f"画像データのデコードに失敗しました: {e}")
            
        last_end = match.end()
        
    # 残りのテキストを追加
    if last_end < len(content):
        text_part = content[last_end:].strip()
        if text_part:
            parts.append(types.Part.from_text(text=text_part))
            
    # もしパーツが1つもなければ（空文字の場合など）、空のテキストを入れる
    if not parts:
        parts.append(types.Part.from_text(text=content))
        
    return parts

_anthropic_client: anthropic.AsyncAnthropic | None = None
_openai_client: openai.AsyncOpenAI | None = None
_gemini_client: genai.Client | None = None

# 2026年5月リリースの最新フラッグシップ（Fable 5一時停止中のため）
DEFAULT_ANTHROPIC_MODEL = "claude-opus-4-8"
# 2026年2月リリースの最新フラッグシップ
DEFAULT_GEMINI_MODEL = "gemini-3.1-pro"
# 2026年6月時点最新
DEFAULT_DEEPSEEK_REASONER_MODEL = "deepseek-v4-pro"
DEFAULT_DEEPSEEK_CHAT_MODEL = "deepseek-v4-flash"

_deepseek_client: openai.AsyncOpenAI | None = None


def get_provider() -> str:
    """環境変数からデフォルトのLLMプロバイダーを取得（指定がなければanthropic）"""
    return os.environ.get("LLM_PROVIDER", "anthropic").lower()


def get_anthropic_client() -> anthropic.AsyncAnthropic:
    """Anthropic クライアントのシングルトンを取得"""
    global _anthropic_client
    if _anthropic_client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("claude")
        if not api_key:
            raise ValueError(
                "Environment variable 'ANTHROPIC_API_KEY' is not set."
            )
        api_key = api_key.strip().strip('\"\'')
        _anthropic_client = anthropic.AsyncAnthropic(api_key=api_key)
        logger.info("Anthropic クライアントを初期化しました")
    return _anthropic_client


def get_openai_client() -> openai.AsyncOpenAI:
    """OpenAI クライアントのシングルトンを取得"""
    global _openai_client
    if _openai_client is None:
        api_key = os.environ.get("OPENAI_API_KEY", "").strip().strip('\"\'')
        base_url = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1")
        _openai_client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)
        logger.info(f"OpenAI 互換クライアントを初期化しました: {base_url}")
    return _openai_client

_local_client: openai.AsyncOpenAI | None = None

def get_local_client() -> openai.AsyncOpenAI:
    """Local LLM クライアントのシングルトンを取得"""
    global _local_client
    if _local_client is None:
        api_key = os.environ.get("LOCAL_API_KEY", "ollama").strip().strip('\"\'')
        base_url = os.environ.get("LOCAL_API_BASE", "http://localhost:11434/v1")
        _local_client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)
        logger.info(f"Local LLM クライアントを初期化しました: {base_url}")
    return _local_client


def get_deepseek_client() -> openai.AsyncOpenAI:
    """DeepSeek クライアントのシングルトンを取得"""
    global _deepseek_client
    if _deepseek_client is None:
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("Environment variable 'DEEPSEEK_API_KEY' is not set.")
        api_key = api_key.strip().strip('\"\'')
        base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        if not base_url.endswith("/v1"):
            base_url = f"{base_url.rstrip('/')}/v1"
        _deepseek_client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)
        logger.info(f"DeepSeek クライアントを初期化しました: {base_url}")
    return _deepseek_client


def reset_llm_clients() -> None:
    """設定キー変更後にシングルトンを破棄（次回呼び出しで新キーを読む）。"""
    global _deepseek_client, _openai_client, _gemini_client, _local_client, _anthropic_client
    _deepseek_client = None
    _openai_client = None
    _gemini_client = None
    _local_client = None
    _anthropic_client = None


def get_gemini_client() -> genai.Client:
    """Gemini クライアント（公式SDK）のシングルトンを取得"""
    global _gemini_client
    if _gemini_client is None:
        raw_api_key = os.environ.get("GEMINI_API_KEY")
        if not raw_api_key:
            raise ValueError("Environment variable 'GEMINI_API_KEY' is not set.")
        
        # AQ. から始まるキー等を確実に読み込む
        api_key = raw_api_key.strip().strip('\"\'')
        _gemini_client = genai.Client(api_key=api_key)
        logger.info("Gemini クライアント(公式SDK)を初期化しました")
    return _gemini_client


def _ensure_request_size(system_instruction: str, messages: list, max_bytes: int = 10_000_000) -> tuple[str, list]:
    """413対策: リクエスト全体のサイズをチェックし、超えてたらメッセージをトリミング"""
    sys_size = len(system_instruction.encode('utf-8'))
    total = sys_size
    breakdown = {"system": sys_size, "messages": []}
    for i, m in enumerate(messages):
        content_size = len(str(m.get("content", "")).encode('utf-8'))
        sources_size = len(str(m.get("sources", "")).encode('utf-8'))
        thinking_size = len(str(m.get("thinking_json", "")).encode('utf-8'))
        reasoning_size = len(str(m.get("reasoning", "")).encode('utf-8'))
        msg_total = content_size + sources_size + thinking_size + reasoning_size
        total += msg_total
        # 大きなメッセージだけ記録（10KB超）
        if msg_total > 10_000:
            breakdown["messages"].append({
                "idx": i, "role": m.get("role", "?"),
                "content": content_size, "sources": sources_size,
                "thinking": thinking_size, "reasoning": reasoning_size,
                "total": msg_total
            })
    
    logger.info(f"📦 リクエストサイズ: {total:,} bytes (上限: {max_bytes:,})")
    logger.info(f"📦 内訳: system={sys_size:,} | メッセージ{len(messages)}件")
    for b in breakdown["messages"]:
        logger.info(f"📦  msg[{b['idx']}]({b['role']}): content={b['content']:,} sources={b['sources']:,} thinking={b['thinking']:,} reasoning={b['reasoning']:,} = {b['total']:,}")
    
    if total <= max_bytes:
        return system_instruction, messages
    
    # 超過 → 古いメッセージから優先的にトリミング
    logger.warning(f"⚠️ リクエストサイズ超過 ({total:,} > {max_bytes:,}) → 強制トリミング")
    trimmed = messages.copy()
    
    # 最新メッセージは保持、古いものから削っていく
    keep_count = max(1, len(trimmed) // 2)
    keep_messages = trimmed[-keep_count:]
    old_messages = trimmed[:-keep_count]
    
    for msg in old_messages:
        content = msg.get("content", "")
        if len(str(content)) > 200:
            msg["content"] = content[:200] + "...[トリミング]..."
    
    trimmed = old_messages + keep_messages
    
    # それでも超過なら最新だけ残す
    total = len(system_instruction.encode('utf-8'))
    for m in trimmed:
        total += len(str(m.get("content", "")).encode('utf-8'))
    
    if total > max_bytes:
        # 最終手段: 最新2件だけ + 全フィールドを強制トリミング
        trimmed = trimmed[-2:] if len(trimmed) >= 2 else trimmed
        for msg in trimmed:
            content = str(msg.get("content", ""))
            if len(content) > 500:
                msg["content"] = content[:250] + "...[413回避のため強制カット]..." + content[-250:]
            # sources と thinking もクリア（これらが57MBの原因になるのを防ぐ）
            if msg.get("sources") and len(str(msg.get("sources", ""))) > 1000:
                msg["sources"] = None
            if msg.get("thinking_json") and len(str(msg.get("thinking_json", ""))) > 2000:
                msg["thinking_json"] = None
    
    # API送信前に必要なロールとコンテンツだけをクリーンに保ち、sourcesやthinking_jsonなどのメタデータを完全に除去
    sanitized = []
    for m in trimmed:
        role = m.get("role", "user")
        content = m.get("content", "")
        if content is None:
            content = ""
        sanitized.append({"role": role, "content": str(content)})
        
    logger.info(f"📦 トリミング・サニタイズ後: {sum(len(str(m.get('content',''))) for m in sanitized):,} bytes")
    return system_instruction, sanitized


def _deepseek_thinking_kwargs(enable_thinking: bool) -> dict:
    """DeepSeek V4 thinking モード制御。

    雑談で reasoning が長いと max_tokens を食い潰して本文が途切れるため、
    chat 系は disabled。公式は low/medium を high にマップするため effort 下げでは解決しない。

    注意: インストール済み openai SDK は reasoning_effort を create() の直引数として
    受け付けないため、thinking / reasoning_effort はすべて extra_body 経由で渡す。
    """
    if enable_thinking:
        return {
            "extra_body": {
                "thinking": {"type": "enabled"},
                "reasoning_effort": "high",
            },
        }
    return {"extra_body": {"thinking": {"type": "disabled"}}}


@retry(
    wait=wait_exponential(multiplier=1, min=2, max=10),
    stop=stop_after_attempt(2),
    retry=retry_if_exception_type(Exception),
    reraise=True
)
async def _call_model_inner(
    system_instruction: str,
    messages: list,
    model_name: str | None = None,
    max_tokens: int = 16384,
    provider: str | None = None,
    temperature: float = 0.7,
    enable_thinking: bool = True,
) -> str:
    """
    LLM を呼び出し、完全なレスポンスを返す（非ストリーミング）。
    検索判定などバックグラウンドの1回目の呼び出しで使用。
    """
    system_instruction, messages = _ensure_request_size(system_instruction, messages)
    effective_provider = provider or get_provider()

    if effective_provider == "gemini":
        client = get_gemini_client()
        model = model_name or DEFAULT_GEMINI_MODEL
        
        # OpenAI形式のメッセージリストをGeminiネイティブ形式に変換
        contents = []
        for msg in messages:
            role = "user" if msg["role"] == "user" else "model"
            contents.append(
                types.Content(role=role, parts=_parse_gemini_parts(msg["content"]))
            )
            
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            max_output_tokens=max_tokens,
            temperature=temperature,  # ← 追加
        )
        
        # 公式SDKで非同期呼び出し
        response = await client.aio.models.generate_content(
            model=model,
            contents=contents,
            config=config,
        )
        return response.text or ""
        
    elif effective_provider == "deepseek":
        client = get_deepseek_client()
        model = model_name or DEFAULT_DEEPSEEK_CHAT_MODEL
        oai_messages = [{"role": "system", "content": system_instruction}] + messages
        response = await client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=oai_messages,
            temperature=temperature,
            **_deepseek_thinking_kwargs(enable_thinking),
        )
        msg = response.choices[0].message
        content = getattr(msg, "content", "") or ""
        reasoning = getattr(msg, "reasoning_content", "") or ""
        return f"<think>\n{reasoning}\n</think>\n{content}" if reasoning else content
        
    elif effective_provider == "openai":
        client = get_openai_client()
        model = model_name or "gpt-5.5"
        oai_messages = [{"role": "system", "content": system_instruction}] + messages
        response = await client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=oai_messages,
            temperature=temperature,  # ← 追加
        )
        return response.choices[0].message.content or ""
        
    elif effective_provider == "local":
        client = get_local_client()
        model = model_name or "llama3"
        oai_messages = [{"role": "system", "content": system_instruction}] + messages
        response = await client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=oai_messages,
            temperature=temperature,  # ← 追加
        )
        return response.choices[0].message.content or ""
        
    else:
        client = get_anthropic_client()
        model = model_name or DEFAULT_ANTHROPIC_MODEL
        response = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_instruction,
            messages=messages,
            temperature=temperature,  # ← 追加
        )
        return response.content[0].text


def _escalate_for_truncation(reason: str) -> str:
    """トークン上限・安全フィルタ等で途切れた場合のエスカレーションタグを生成する。"""
    return (
        f"\n\n<escalate>応答が途切れました（原因: {reason}）。"
        "前の回答を最初から生成し直してください。</escalate>"
    )


async def _stream_model_inner(
    system_instruction: str,
    messages: list,
    model_name: str | None = None,
    max_tokens: int = 16384,
    provider: str | None = None,
    temperature: float = 0.7,
    enable_thinking: bool = True,
) -> AsyncGenerator[str, None]:
    """
    LLM をストリーミングモードで呼び出し、テキストチャンクを逐次 yield。
    ユーザーとのチャット応答で使用。
    注: async generator には tenacity retry が効かないため付与しない。
    """
    system_instruction, messages = _ensure_request_size(system_instruction, messages)
    effective_provider = provider or get_provider()

    if effective_provider == "gemini":
        client = get_gemini_client()
        model = model_name or DEFAULT_GEMINI_MODEL
        
        # OpenAI形式のメッセージリストをGeminiネイティブ形式に変換
        contents = []
        for msg in messages:
            role = "user" if msg["role"] == "user" else "model"
            contents.append(
                types.Content(role=role, parts=_parse_gemini_parts(msg["content"]))
            )
            
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            max_output_tokens=max_tokens,
            temperature=temperature,  # ← 追加
        )
        
        # 公式SDKでストリーミング呼び出し
        response_stream = await client.aio.models.generate_content_stream(
            model=model,
            contents=contents,
            config=config,
        )
        async for chunk in response_stream:
            if chunk.text:
                yield chunk.text
            # finish_reason 検出（MAX_TOKENS / SAFETY 等で途切れた場合にescalate）
            candidates = getattr(chunk, "candidates", None) or []
            if candidates:
                finish_reason = getattr(candidates[0], "finish_reason", None)
                if finish_reason is not None:
                    reason_name = getattr(finish_reason, "name", None) or str(finish_reason)
                    logger.info(f"📡 Gemini finish_reason={reason_name}")
                    # FinishReason enum: STOP=1, MAX_TOKENS=2, SAFETY=3, RECITATION=4, OTHER=5
                    # 文字列比較と数値比較の両方に対応
                    reason_upper = reason_name.upper() if isinstance(reason_name, str) else ""
                    is_truncated = (
                        reason_upper in ("MAX_TOKENS", "SAFETY", "RECITATION", "OTHER")
                        or reason_name in (2, 3, 4, 5)
                        or str(finish_reason) in ("2", "3", "4", "5")
                    )
                    # STOP / FINISH_REASON_UNSPECIFIED は正常終了
                    is_ok = reason_upper in ("STOP", "FINISH_REASON_UNSPECIFIED", "UNSPECIFIED", "1", "0") or reason_name in (0, 1)
                    if is_truncated or (not is_ok and reason_upper and reason_upper != "STOP"):
                        if reason_upper in ("MAX_TOKENS",) or reason_name == 2 or str(finish_reason) == "2":
                            logger.warning(f"⚠️ Gemini応答がトークン上限で途切れました: finish_reason={reason_name}")
                            yield _escalate_for_truncation(f"Gemini MAX_TOKENS ({reason_name})")
                        elif reason_upper in ("SAFETY",) or reason_name == 3 or str(finish_reason) == "3":
                            logger.warning(f"⚠️ Gemini応答がセーフティフィルタで遮断されました: finish_reason={reason_name}")
                            yield _escalate_for_truncation(f"Gemini SAFETY ({reason_name})")
                        elif not is_ok:
                            logger.warning(f"⚠️ Gemini応答が異常終了しました: finish_reason={reason_name}")
                            yield _escalate_for_truncation(f"Gemini {reason_name}")

    elif effective_provider == "deepseek":
        client = get_deepseek_client()
        model = model_name or DEFAULT_DEEPSEEK_CHAT_MODEL
        oai_messages = [{"role": "system", "content": system_instruction}] + messages
        stream = await client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=oai_messages,
            stream=True,
            temperature=temperature,
            **_deepseek_thinking_kwargs(enable_thinking),
        )
        is_thinking = False
        has_finished_thinking = False
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            
            # 思考プロセス（reasoning_content）もフロントにストリームして100秒タイムアウトを回避
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                if not is_thinking:
                    is_thinking = True
                    yield "<think>\n"
                yield reasoning
                
            content = getattr(delta, "content", None)
            if content:
                if is_thinking and not has_finished_thinking:
                    has_finished_thinking = True
                    yield "\n</think>\n\n"
                yield content
            
            finish_reason = getattr(chunk.choices[0], "finish_reason", None)
            if finish_reason:
                logger.info(f"📡 DeepSeek finish_reason={finish_reason}")
            if finish_reason == "length":
                logger.warning("⚠️ DeepSeek応答がトークン上限で途切れました")
                yield _escalate_for_truncation("DeepSeek length")

        # ストリーム終了時にまだ</think>を出力していなければ出力する
        if is_thinking and not has_finished_thinking:
            yield "\n</think>\n\n"

    elif effective_provider == "openai":
        client = get_openai_client()
        model = model_name or "gpt-5.5"
        oai_messages = [{"role": "system", "content": system_instruction}] + messages
        stream = await client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=oai_messages,
            stream=True,
            temperature=temperature,  # ← 追加
        )
        async for chunk in stream:
            if chunk.choices:
                content = chunk.choices[0].delta.content
                if content:
                    yield content
                finish_reason = getattr(chunk.choices[0], "finish_reason", None)
                if finish_reason:
                    logger.info(f"📡 OpenAI finish_reason={finish_reason}")
                if finish_reason == "length":
                    logger.warning("⚠️ OpenAI応答がトークン上限で途切れました")
                    yield _escalate_for_truncation("OpenAI length")
                
    elif effective_provider == "local":
        client = get_local_client()
        model = model_name or "llama3"
        oai_messages = [{"role": "system", "content": system_instruction}] + messages
        stream = await client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=oai_messages,
            stream=True,
            temperature=temperature,  # ← 追加
        )
        async for chunk in stream:
            if chunk.choices:
                content = getattr(chunk.choices[0].delta, "content", None)
                if content:
                    yield content
                finish_reason = getattr(chunk.choices[0], "finish_reason", None)
                if finish_reason:
                    logger.info(f"📡 Local finish_reason={finish_reason}")
                if finish_reason == "length":
                    logger.warning("⚠️ Local LLM応答がトークン上限で途切れました")
                    yield _escalate_for_truncation("Local length")
                
    else:
        client = get_anthropic_client()
        model = model_name or DEFAULT_ANTHROPIC_MODEL
        async with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system_instruction,
            messages=messages,
            temperature=temperature,  # ← 追加
        ) as stream:
            async for text in stream.text_stream:
                yield text
            # Anthropic: ストリーム終了後に最終メッセージの stop_reason を確認
            try:
                final_message = await stream.get_final_message()
                stop_reason = getattr(final_message, "stop_reason", None)
                if stop_reason:
                    logger.info(f"📡 Anthropic stop_reason={stop_reason}")
                if stop_reason == "max_tokens":
                    logger.warning("⚠️ Anthropic応答がトークン上限で途切れました")
                    yield _escalate_for_truncation("Anthropic max_tokens")
            except Exception as e:
                logger.debug(f"Anthropic stop_reason取得スキップ: {e}")

def _estimate_tokens(text: str) -> int:
    try:
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return len(text) // 2

async def call_model(
    system_instruction: str,
    messages: list,
    model_name: str | None = None,
    max_tokens: int = 16384,
    provider: str | None = None,
    temperature: float = 0.7,
    enable_thinking: bool = True,
) -> str:
    if not check_budget():
        raise HTTPException(status_code=429, detail="API utilization limit (daily budget) exceeded. Please try again tomorrow.")
        
    prompt_text = system_instruction + "".join([m.get("content", "") for m in messages])
    prompt_tokens = _estimate_tokens(prompt_text)
    
    result = await _call_model_inner(
        system_instruction, messages, model_name, max_tokens, provider, temperature, enable_thinking
    )
    
    completion_tokens = _estimate_tokens(result)
    actual_model = model_name or "default-model"
    record_usage(actual_model, prompt_tokens, completion_tokens)
    
    return result

async def stream_model(
    system_instruction: str,
    messages: list,
    model_name: str | None = None,
    max_tokens: int = 16384,
    provider: str | None = None,
    temperature: float = 0.7,
    enable_thinking: bool = True,
) -> AsyncGenerator[str, None]:
    """予算チェック後、ストリーム生成を実行するラッパー。例外発生時は自動リトライ用のエスカレーションタグを返す。"""
    if not check_budget():
        yield "【エラー】本日のAPI利用上限に達しました。明日またお試しください。"
        return
        
    prompt_text = system_instruction + "".join([m.get("content", "") for m in messages])
    prompt_tokens = _estimate_tokens(prompt_text)
    
    completion_text = ""
    try:
        async for chunk in _stream_model_inner(
            system_instruction, messages, model_name, max_tokens, provider, temperature, enable_thinking
        ):
            completion_text += chunk
            yield chunk
    except Exception as e:
        logger.error(f"Stream interrupted: {e}")
        # 例外が発生した場合、auto_execution_loop にリトライさせるためのエスカレーションタグを出力
        yield f"\n\n<escalate>API接続エラーにより応答が途切れました。前の回答を生成し直してください。({e})</escalate>"
        
    completion_tokens = _estimate_tokens(completion_text)
    actual_model = model_name or "default-model"
    record_usage(actual_model, prompt_tokens, completion_tokens)
