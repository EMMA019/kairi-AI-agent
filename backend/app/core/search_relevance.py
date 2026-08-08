"""
検索結果が「実質空」（件数ゼロ or クエリ関連度不足）かを判定する。

関連の薄いヒットを「結果あり」と誤認して事実断定を許さないための軽量ヒューリスティック。
追加 LLM は使わない。
"""
from __future__ import annotations

import re
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 関連トークン重なり率の下限（これ未満は実質空）
DEFAULT_MIN_OVERLAP_RATIO = 0.18
DEFAULT_MIN_HIT_TOKENS = 1

_STOP = {
    "それ", "これ", "あれ", "どう", "そう", "けど", "だけど", "って", "感じ",
    "思う", "教えて", "ください", "です", "ます", "した", "いる", "ある",
    "だった", "よね", "なに", "何が", "について", "お願い", "して",
    "the", "and", "was", "for", "about", "with", "from", "that", "this",
    "what", "who", "when", "where", "how", "into", "http", "https", "www",
    "検索", "結果", "情報", "最新", "詳細",
}

_EMPTY_MARKERS = [
    "結果は見つかりません",
    "見つかりませんでした",
    "no results",
    "0件",
    "クエリに十分関連する情報は見つかりませんでした",
]


SEARCH_UNSUPPORTED_INSTRUCTION = (
    "【重要・検索結果不足】検索では質問に十分関連する情報を確認できませんでした。"
    "固有名・数値・役職・順位・結果などの事実を、推測や学習知識で埋めてはいけません。"
    "「検索結果からは確認できませんでした」と明確に伝えてください。"
)

SEARCH_UNSUPPORTED_PLACEHOLDER = (
    "【検索結果】クエリに十分関連する情報は見つかりませんでした。"
    "事実の断定・固有名の補完は禁止です。"
)


def _tokens(text: str) -> set[str]:
    found = set(re.findall(r"[一-龥ァ-ヶー]{2,}|[A-Za-z][A-Za-z0-9_\-]{2,}", text or ""))
    out = set()
    for t in found:
        tl = t.lower()
        if tl in _STOP or t in _STOP:
            continue
        if len(t) < 2:
            continue
        out.add(t)
        out.add(tl)
    return out


def query_result_overlap_ratio(
    user_input: str,
    search_queries: list | None,
    results_text: str,
) -> tuple[float, int, int]:
    """
    クエリ語が結果本文にどれだけ含まれるか。
    Returns: (ratio, hit_count, token_count)
    """
    q_tokens: set[str] = set()
    q_tokens |= _tokens(user_input or "")
    for q in search_queries or []:
        q_tokens |= _tokens(str(q))
    # 表記ゆれ用に lower のみのセットへ
    norms = {t.lower() for t in q_tokens if len(t) >= 2}
    if not norms:
        return 1.0, 0, 0  # 判定不能→空扱いにしない

    body = (results_text or "").lower()
    hits = sum(1 for t in norms if t in body)
    ratio = hits / max(len(norms), 1)
    return ratio, hits, len(norms)


def is_search_effectively_empty(
    user_input: str,
    search_queries: list | None,
    results_text: str | None,
    *,
    min_overlap_ratio: float = DEFAULT_MIN_OVERLAP_RATIO,
    min_hit_tokens: int = DEFAULT_MIN_HIT_TOKENS,
) -> bool:
    """
    検索必須ターンで、結果を「根拠として使えない」とみなすか。
    """
    text = (results_text or "").strip()
    if not text:
        return True

    lower = text.lower()
    if any(m.lower() in lower for m in _EMPTY_MARKERS) and len(text) < 400:
        return True

    # プレースホルダのみ
    if text.startswith("【検索結果】クエリに十分関連"):
        return True

    ratio, hits, n_tok = query_result_overlap_ratio(user_input, search_queries, text)
    if n_tok == 0:
        return False
    if hits < min_hit_tokens or ratio < min_overlap_ratio:
        logger.info(
            f"📉 検索結果の関連度不足: hits={hits}/{n_tok} ratio={ratio:.2f} "
            f"(min_hits={min_hit_tokens}, min_ratio={min_overlap_ratio})"
        )
        return True
    return False
