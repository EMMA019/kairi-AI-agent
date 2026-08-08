"""
最終応答の成功／空洞完了／失敗判定。
空本文や「ファイル作成完了」だけのメタ宣言を成功扱いにしない。
"""
from __future__ import annotations

import re
from typing import Optional

from app.core.fact_filters.markup import looks_incomplete_output

_FAIL_MARKERS = (
    "応答の生成に失敗",
    "フィルタリングされました",
    "応答が生成されなかった",
    "出力が空です",
    "処理を完了できませんでした",
)

_HOLLOW_COMPLETE = re.compile(
    r"(ファイル作成完了|作成完了|作成済み|実装が完了|実装完了|完了いたしました|"
    r"ファイルを作成しました|保存しました|書き込みました|"
    r"実行・検証は.{0,20}スキップ|上記プランを直ちに実行|"
    r"File created|Successfully (?:created|wrote|saved))",
    re.IGNORECASE,
)

_WANTS_CODE_BODY = re.compile(
    r"(フルコード|全文|本文に書|コードだけ|一発で|書き直さなくて|"
    r"実装して|コードを書|コード書|作って|書いて|"
    r"please implement|full code|complete code)",
    re.IGNORECASE,
)

_HAS_CODE_FENCE = re.compile(r"```[\w+-]*\n[\s\S]{80,}```")
_HAS_SUBSTANTIVE = re.compile(r"[。．！？\n].{80,}|def |class |import |function |const |export ")


def wants_code_in_chat(user_input: str) -> bool:
    return bool(_WANTS_CODE_BODY.search(user_input or ""))


def is_failure_fallback(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    return any(m in t for m in _FAIL_MARKERS)


def is_hollow_completion(text: str, user_input: str = "") -> bool:
    """
    メタ完了宣言だけで実体（コード／十分な説明）が無い応答。
    """
    t = (text or "").strip()
    if not t:
        return True
    if is_failure_fallback(t):
        return True
    if looks_incomplete_output(t):
        return True

    hollow_hit = bool(_HOLLOW_COMPLETE.search(t))
    has_code = bool(_HAS_CODE_FENCE.search(t))
    substantive = len(t) >= 400 and bool(_HAS_SUBSTANTIVE.search(t))

    if hollow_hit and not has_code and len(t) < 800:
        return True
    if wants_code_in_chat(user_input) and hollow_hit and not has_code:
        return True
    if wants_code_in_chat(user_input) and not has_code and not substantive and len(t) < 600:
        # 「作成しました」系でコードも長い説明も無い
        if hollow_hit or len(t) < 200:
            return True
    return False


_MARKET_QUERY_HINTS = (
    "市場",
    "前場",
    "後場",
    "日経",
    "TOPIX",
    "トピックス",
    "株",
    "どうだった",
    "どんな感じ",
    "業種",
    "セクター",
    "銀行",
    "市況",
    # English (public / locale=en)
    "market",
    "markets",
    "stock",
    "stocks",
    "s&p",
    "dow",
    "nasdaq",
    "index",
    "indices",
    "equities",
    "wall street",
)


def is_aborted_short_market_reply(text: str, user_input: str = "") -> bool:
    """
    市況質問なのに本文が数文字で途切れたケース（例: 「か」のみ）。
    履歴汚染を防ぐため DB 保存前に弾く。
    """
    t = (text or "").strip()
    if not t or len(t) > 24:
        return False
    u = user_input or ""
    if not any(k in u for k in _MARKET_QUERY_HINTS):
        return False
    return True


def response_ok(text: str, user_input: str = "") -> bool:
    """done.ok 用。True = ユーザー向けに成功とみなしてよい。"""
    if is_failure_fallback(text):
        return False
    if is_aborted_short_market_reply(text, user_input):
        return False
    if is_hollow_completion(text, user_input):
        return False
    try:
        from app.core.acceptance_checker import response_marks_incomplete
        if response_marks_incomplete(text):
            return False
    except Exception:
        if "完了ゲート未達" in (text or "") or "最大実行ループ数" in (text or ""):
            return False
    return bool((text or "").strip())


def build_done_payload(content: str, user_input: str = "") -> dict:
    ok = response_ok(content, user_input)
    payload = {"type": "done", "content": content or "", "ok": ok}
    try:
        from app.core.acceptance_checker import response_marks_incomplete
        if response_marks_incomplete(content or ""):
            payload["incomplete"] = True
    except Exception:
        if "完了ゲート未達" in (content or ""):
            payload["incomplete"] = True
    return payload
