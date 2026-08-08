import os
import re
import uuid
import httpx
from app.utils.logger import get_logger
from app.core.llm_client import call_model

logger = get_logger(__name__)

async def translate_text(text: str, target_lang: str = "JA") -> str:
    """
    Google Cloud Translation API を使用してテキストを翻訳します。
    API呼び出しに失敗した場合は、LLM (call_model) に自動でフォールバックします。
    """
    if not text or not text.strip():
        return text

    # Google Cloud Translation の設定を環境変数から取得
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT_ID", "gen-lang-client-0119946872")
    
    # ターゲット言語の整形 (Google Cloudの場合は 'ja', 'en' など)
    to_lang = "ja" if target_lang.upper() in ["JA", "JA-JP", "JAPANESE"] else "en" if target_lang.upper() in ["EN", "EN-US", "ENGLISH"] else target_lang.lower()

    try:
        from google.cloud import translate_v3 as translate
        
        client = translate.TranslationServiceClient()
        parent = f"projects/{project_id}/locations/global"
        
        request = {
            "parent": parent,
            "contents": [text],
            "target_language_code": to_lang,
        }
        
        # 翻訳実行 (非同期ではなく同期呼び出しになるため、ブロック回避が必要ならrun_in_executorを使うべきだが、まずは標準APIを使用)
        response = client.translate_text(request=request)
        
        if response.translations:
            translated_text = response.translations[0].translated_text
            logger.info(f"Google Cloud Translation API を使用して翻訳しました (検出言語: {response.translations[0].detected_language_code})")
            return translated_text

    except Exception as e:
        logger.warning(f"Google Cloud Translation APIエラー。LLM翻訳にフォールバックします: {e}")

    # フォールバック: LLMを使用した翻訳
    return await _translate_with_llm(text, target_lang)

async def _translate_with_llm(text: str, target_lang: str) -> str:
    lang_name = "日本語" if target_lang.upper() in ["JA", "JA-JP"] else "英語 (US)" if target_lang.upper() in ["EN", "EN-US"] else target_lang

    system_instruction = f"あなたはプロの翻訳家です。以下のテキストを {lang_name} に翻訳してください。出力は翻訳結果のテキストのみとし、解説や挨拶は一切含めないでください。"
    messages = [{"role": "user", "content": text}]

    try:
        translated = await call_model(
            system_instruction=system_instruction,
            messages=messages,
            max_tokens=2000
        )
        
        translated = re.sub(r'<think>.*?</think>\n*', '', translated, flags=re.DOTALL).strip()
        
        if translated.startswith("```"):
            lines = translated.split("\n")
            if len(lines) > 1:
                translated = "\n".join(lines[1:])
            if translated.endswith("```"):
                translated = translated[:-3].strip()
                
        logger.info("LLMフォールバック翻訳を使用しました")
        return translated if translated else text
    except Exception as e:
        logger.error(f"LLM翻訳フォールバックエラー: {e}")
        return text

async def translate_title_ja(title: str) -> str:
    """英語・韓国語等の非日本語タイトルを検知し、無料公開Web翻訳API（0円/0トークン）で爆速和訳する"""
    if not title or not title.strip():
        return title
        
    # すでに日本語（ひらがな・カタカナ・漢字）が3文字以上含まれている場合は翻訳不要
    jp_chars = sum(1 for c in title if (0x3040 <= ord(c) <= 0x309F) or (0x30A0 <= ord(c) <= 0x30FF) or (0x4E00 <= ord(c) <= 0x9FFF))
    if jp_chars >= 3:
        return title

    # まずGoogleの公開無料Web翻訳APIで高速＆無料(APIキー不要・¥0)和訳
    try:
        url = "https://translate.googleapis.com/translate_a/single"
        params = {"client": "gtx", "sl": "auto", "tl": "ja", "dt": "t", "q": title}
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                if data and isinstance(data, list) and len(data) > 0 and isinstance(data[0], list):
                    translated = "".join(item[0] for item in data[0] if isinstance(item, list) and len(item) > 0 and item[0])
                    if translated and translated.strip() and translated.strip() != title.strip():
                        return translated.strip()
    except Exception as e:
        logger.warning(f"無料Web翻訳APIエラー: {e} — 標準フォールバックへ移行")

    # 無料APIで失敗または空だった場合は既存の translate_text (Cloud / LLM) にフォールバック
    return await translate_text(title, "JA")
