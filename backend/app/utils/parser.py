"""
LLMの出力からXMLタグをパースするユーティリティ。
demo.py の parse_response() + validate_json_data() を移植。
"""
import re
import json
from typing import Optional


def find_json_objects(text: str) -> list[str]:
    """
    テキスト中からネストされたJSON文字列をすべて抽出する共通ユーティリティ。
    正規表現ではなくブレース・カウントで正確にパースする。
    """
    objs = []
    nest = 0
    start = -1
    in_string = False
    escape = False
    for i, c in enumerate(text):
        if c == '"' and not escape:
            in_string = not in_string
        elif not in_string:
            if c == '{':
                if nest == 0:
                    start = i
                nest += 1
            elif c == '}':
                nest -= 1
                if nest == 0 and start != -1:
                    objs.append(text[start:i+1])
                    start = -1
        escape = (c == '\\') if not escape else False
    return objs


def validate_json_data(json_data: dict) -> dict:
    """LLMが仕様外の値を出した場合に備えたフォールバック処理"""
    if not json_data:
        return json_data

    # response_style のバリデーション
    if json_data.get("response_style") not in ("共感", "簡潔"):
        json_data["response_style"] = "簡潔"

    # intent のバリデーション
    if json_data.get("intent") not in ("chat", "task", "empathy"):
        json_data["intent"] = "chat"

    # kv_write のバリデーション
    kv = json_data.get("kv_write")
    if isinstance(kv, dict):
        if not kv.get("trigger"):
            kv["category"] = None
            kv["quote"] = None
            kv["summary"] = None
        else:
            category = kv.get("category")
            # category のバリデーション: 不正/欠損なら書き込み自体を破棄
            if category not in ("profile", "preference", "agreement"):
                kv["trigger"] = False
                kv["category"] = None
                kv["quote"] = None
                kv["summary"] = None
                return json_data
            
            summary = kv.get("summary")
            if isinstance(summary, dict):
                # target が欠損している場合のフォールバック
                if not summary.get("target"):
                    summary["target"] = "不明"
                
                stance = summary.get("stance")
                if category == "profile":
                    # profile は事実情報なので stance は不要。
                    # stance が不正値なら note に移動
                    if stance and stance not in ("好き", "苦手", "条件付き"):
                        summary["note"] = stance
                        summary["stance"] = None
                    elif not stance:
                        summary["stance"] = None
                    # note が存在しない場合は None で初期化
                    if "note" not in summary:
                        summary["note"] = None
                    # note が非None・非strの場合のみ文字列に変換
                    if summary["note"] is not None and not isinstance(summary["note"], str):
                        summary["note"] = str(summary["note"])
                else:
                    # preference / agreement は stance 必須
                    if stance not in ("好き", "苦手", "条件付き"):
                        summary["stance"] = None
                    # preference/agreement では note は不要なので除去
                    summary.pop("note", None)
            else:
                # summary が dict でない場合のフォールバック
                kv["summary"] = {"target": "不明", "stance": None, "note": None} if category == "profile" else {"target": "不明", "stance": None}

    return json_data


def parse_response(text: str) -> tuple[str, str, Optional[dict]]:
    """
    LLMの出力から思考プロセスと最終回答を安全に分離するパーサー。
    ローカルLLMやGeminiが <thinking> タグを忘れたり、JSONコードブロックだけで返してきたケースにも対応。
    
    Returns:
        (thinking_content, response_content, json_data)
    """
    thinking_content = ""
    response_content = text.strip()
    json_data = None

    # 1. まず <thinking>...</thinking> タグを探す
    thinking_blocks = re.findall(r"<thinking>(.*?)</thinking>", text, re.DOTALL)
    response_match = re.search(r"<response>(.*?)</response>", text, re.DOTALL)

    # 2. もし <thinking> タグがない場合、最初の {...} のJSONブロックを探す
    # （Gemini等がタグを落として thinking\n{...} のように出力したケースへの対応）
    if not thinking_blocks:
        # ネストされた {} に対応するため、re.search ではなく再帰的な処理や貪欲なマッチを使用する
        # 最も外側の { から、最後の } までを取得する
        json_str_match = re.search(r"\{.*\"reasoning\".*\}", text, re.DOTALL)
        if json_str_match:
            block = json_str_match.group(0)
            
            # ただし、これだと後ろの回答文の中に } があった場合に巻き込んでしまう。
            # より安全に、JSONとしてパース可能な最小のブロックを探す
            start_idx = text.find("{")
            if start_idx != -1:
                brace_count = 0
                end_idx = -1
                for i in range(start_idx, len(text)):
                    if text[i] == '{':
                        brace_count += 1
                    elif text[i] == '}':
                        brace_count -= 1
                        if brace_count == 0:
                            end_idx = i
                            break
                
                if end_idx != -1:
                    block = text[start_idx:end_idx+1]
                    if '"reasoning"' in block:
                        thinking_blocks = [block]
                        
                        # JSONブロック以降のテキストをレスポンスとする
                        response_content = text[end_idx+1:].strip()
                        # 先頭の不要な "thinking" や改行を削除
                        if response_content.startswith("</thinking>"):
                            response_content = response_content.replace("</thinking>", "", 1).strip()

    # JSON解析処理
    for block in thinking_blocks:
        thinking_content += block.strip() + "\n\n"
        candidate = None
        
        # Markdownの ```json ... ``` で囲まれている場合の除去
        clean_block = re.sub(r"```json\n(.*?)\n```", r"\1", block, flags=re.DOTALL)
        
        try:
            json_str_match = re.search(r"\{.*\}", clean_block, re.DOTALL)
            if json_str_match:
                parsed = json.loads(json_str_match.group(0))
                candidate = validate_json_data(parsed)
        except json.JSONDecodeError:
            pass
        
        # fallback: 正規表現で個別フィールドを抽出
        if not candidate:
            temp_data = {}
            for key in ("intent", "response_style"):
                m = re.search(rf'"{key}"\s*:\s*"([^"]+)"', clean_block)
                if m: temp_data[key] = m.group(1)
            
            m = re.search(r'"require_search"\s*:\s*(true|false)', clean_block)
            if m: temp_data["require_search"] = m.group(1) == "true"
            
            m = re.search(r'"needs_followup"\s*:\s*(true|false)', clean_block)
            if m: temp_data["needs_followup"] = m.group(1) == "true"
            
            if "require_search" in temp_data:
                candidate = validate_json_data(temp_data)
        
        if candidate is not None:
            json_data = candidate

    thinking_content = thinking_content.strip()

    # response_contentの再構築
    if response_match:
        response_content = response_match.group(1).strip()
    elif thinking_blocks and text == response_content:
        # タグベースで分割
        if "</thinking>" in text:
            parts = text.split("</thinking>", 1)
            response_content = parts[1].replace("<response>", "").replace("</response>", "").strip()
        else:
            # タグはないが、JSONブロックで見つけた場合 (すでに上で分割済みなら text != response_content)
            # しかし念のため fallback
            response_content = response_content.replace("<response>", "").replace("</response>", "").strip()

    # もし response_content の先頭に "銀だこについてですね" のような文字の前に
    # 余分な thinking という文字が残っていたら消す
    if response_content.startswith("thinking"):
        response_content = response_content[len("thinking"):].strip()

    return thinking_content, response_content, json_data
