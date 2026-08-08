"""
「おまかせ」開発依頼の判定ヘルパー。

おまかせ = 方向性の委任。記憶利用の許可ではない。
同時に hearing（スキル確認の質問連打）への逃避も禁止する。
"""
from __future__ import annotations

import re

_OMAKASE_PATTERNS = [
    r"おまかせ",
    r"お任せ",
    r"全部任せて",
    r"全部おまかせ",
    r"全部お任せ",
    r"任せる",
    r"任せます",
    r"あなたに任",
    r"好きにやって",
    r"いい感じにやって",
    r"leave\s+it\s+to\s+you",
    r"up\s+to\s+you",
]

_DEV_REQUEST_PATTERNS = [
    r"開発依頼",
    r"作って",
    r"つくって",
    r"作りたい",
    r"実装して",
    r"システムを考えて",
    r"システムを作",
    r"アプリを",
    r"エージェント",
    r"稼げる",
    r"収益",
    r"マネタイズ",
    r"ビジネス",
    r"build\s+(me\s+)?a",
    r"create\s+(me\s+)?a",
]

# おまかせ後に聞いてはいけない浅い質問
_FORBIDDEN_SKILL_QUESTIONS = [
    r"コードを書けますか",
    r"コーディングは可能",
    r"ノーコード",
    r"どんなスキル",
    r"作業が得意",
    r"作業時間は",
    r"趣味[（(]",
]


def is_omakase(user_input: str) -> bool:
    text = (user_input or "").strip()
    if not text:
        return False
    return any(re.search(p, text, re.IGNORECASE) for p in _OMAKASE_PATTERNS)


def is_dev_or_monetize_request(user_input: str) -> bool:
    text = (user_input or "").strip()
    if not text:
        return False
    return any(re.search(p, text, re.IGNORECASE) for p in _DEV_REQUEST_PATTERNS)


def is_omakase_dev_request(user_input: str) -> bool:
    """おまかせ付きの開発/マネタイズ依頼 → hearing 禁止対象。"""
    return is_omakase(user_input) and is_dev_or_monetize_request(user_input)


def contains_forbidden_skill_question(text: str) -> bool:
    t = text or ""
    return any(re.search(p, t, re.IGNORECASE) for p in _FORBIDDEN_SKILL_QUESTIONS)
