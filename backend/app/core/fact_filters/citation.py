"""
引用契約（Citation Contract）検証ステージ。

時事的な固有名詞・数値断定に検索結果番号 [n] が付いていない場合、
不確実表現へ変換するか除去する。正規表現パッチ群を段階的に置き換える中核。

※ 読みやすさ優先: 全カタカナ/CapWord一括置換はしない。
  役職付き固有名と既知リスク名、強い時事断定のみ対象。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from app.utils.logger import get_logger
from app.core.fact_filters.name_normalize import source_mentions_name

logger = get_logger(__name__)


@dataclass
class CitationMetrics:
    truncation_detected: int = 0
    trim_applied: int = 0
    uncited_assertions: int = 0
    citations_found: int = 0


# プロセスローカルな直近メトリクス（integrity_stats 保存用）
_last_metrics = CitationMetrics()


def get_last_citation_metrics() -> CitationMetrics:
    return _last_metrics


def reset_citation_metrics() -> None:
    global _last_metrics
    _last_metrics = CitationMetrics()


_CITATION_RE = re.compile(r"\[(\d{1,3})\]")
_SENTENCE_SPLIT = re.compile(r"(?<=[。．！？!?…])")

# 強い時事断定のみ（%・契約・氏 などは誤爆が多いので除外）
_ASSERTION_TRIGGERS = re.compile(
    r"(?:騎手|議長|CEO|監督|優勝|制覇|終値|オッズ|配当|"
    r"利下げ|利上げ|が発表|と報じ|によると)"
)

# 役職・役割サフィックス付き固有名のみ（一般カタカナは対象外）
_ROLE_NAME_RE = re.compile(
    r"([ァ-ヶーA-Za-z][ァ-ヶーA-Za-z·・\.\-]{1,40}?)"
    r"(騎手|議長|CEO|監督|首相|大統領|選手)"
)

_KNOWN_RISKY_NAMES = [
    "ムーア", "Moore", "パウエル", "Powell", "イエレン", "Yellen",
]

# 1応答あたりの「（要確認）」付与上限（読みやすさ）
_MAX_YOUKAKUNIN = 3

_PLACEHOLDER = "（氏名はソース未記載）"


def _source_has(name: str, source_text: str) -> bool:
    return source_mentions_name(name, source_text or "")


def _count_youkakunin(text: str) -> int:
    return len(re.findall(r"（要確認）", text or ""))


def _soften_name_in_text(text: str, name: str, *, add_marker: bool) -> str:
    pattern = re.compile(
        rf"([^。．！？\n]*{re.escape(name)}[^。．！？\n]*[。．！？]?)"
    )

    def _soften(m: re.Match) -> str:
        s = m.group(1)
        if name not in s:
            return s
        replaced = s.replace(name, _PLACEHOLDER)
        if not replaced.rstrip().endswith(("。", "！", "？", "!", "?")):
            replaced = replaced.rstrip() + "。"
        if add_marker and "要確認" not in replaced and "未確認" not in replaced:
            replaced = replaced.rstrip("。") + "（要確認）。"
        return replaced

    return pattern.sub(_soften, text)


def _collect_risky_name_candidates(text: str) -> list[str]:
    """役職付き固有名 + 既知リスク名のみ（一般語カタカナは採らない）。"""
    found: list[str] = []
    for m in _ROLE_NAME_RE.finditer(text or ""):
        found.append(m.group(1))
    for n in _KNOWN_RISKY_NAMES:
        if n in (text or ""):
            found.append(n)
    uniq = []
    seen = set()
    for n in sorted(found, key=len, reverse=True):
        key = n.lower()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(n)
    return uniq


def verify_citations(
    text: str,
    source_text: str = "",
    *,
    soften_uncited: bool = True,
) -> str:
    """
    引用契約の検証。
    - ソースにない役職付き固有名・既知リスク名を除去/不確実化
    - 強い時事断定文に [n] が無い場合は文末に「（要確認）」を付与（上限付き）
    """
    global _last_metrics
    if not text or not isinstance(text, str):
        return text

    metrics = CitationMetrics()
    metrics.citations_found = len(_CITATION_RE.findall(text))
    src = source_text or ""
    src_stripped = src.strip()
    # プレースホルダだけの「実質空」ソースは固有名一括照合しない
    source_usable = bool(src_stripped) and "クエリに十分関連する情報は見つかりませんでした" not in src_stripped

    names_to_check = _collect_risky_name_candidates(text)

    for name in names_to_check:
        if not name or len(name) < 2:
            continue
        if name not in text and not re.search(re.escape(name), text, flags=re.IGNORECASE):
            continue
        # ソースがあるときは照合、無い/実質空でも役職付き・既知リスクは落とす
        if source_usable and _source_has(name, src):
            continue
        metrics.uncited_assertions += 1
        if soften_uncited:
            add_marker = _count_youkakunin(text) < _MAX_YOUKAKUNIN
            variants = {name}
            for m in re.finditer(re.escape(name), text, flags=re.IGNORECASE):
                variants.add(m.group(0))
            for variant in variants:
                if variant in text:
                    text = _soften_name_in_text(text, variant, add_marker=add_marker)
            logger.info(f"📎 ソース未記載の固有名を不確実化: {name}")

    # 2) ソースにない絶対数値 → 末尾免責（実質的なソースがある時だけ）
    if source_usable:
        abs_nums = re.findall(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", text)
        unverified_abs = []
        for num in abs_nums:
            digits = num.replace(",", "")
            if num in src or digits in src:
                continue
            unverified_abs.append(num)
        if unverified_abs:
            metrics.uncited_assertions += len(set(unverified_abs))
            if soften_uncited:
                from app.core.ui_status import disclaimer, has_finance_estimate_disclaimer

                if not has_finance_estimate_disclaimer(text):
                    text = text.rstrip() + disclaimer("finance_estimate")
                    logger.info(f"📎 ソース未記載の絶対数値を検知し免責を付与: {unverified_abs[:5]}")

    # 3) 強い時事断定トリガ文に引用が無い場合（要確認は上限）
    if soften_uncited and source_usable:
        parts = _SENTENCE_SPLIT.split(text)
        new_parts = []
        youkakunin_budget = max(0, _MAX_YOUKAKUNIN - _count_youkakunin(text))
        for part in parts:
            if not part or not part.strip():
                new_parts.append(part)
                continue
            has_trigger = bool(_ASSERTION_TRIGGERS.search(part))
            has_cite = bool(_CITATION_RE.search(part))
            if (
                has_trigger
                and not has_cite
                and "要確認" not in part
                and "未確認" not in part
                and youkakunin_budget > 0
            ):
                metrics.uncited_assertions += 1
                softened = part.rstrip()
                if softened.endswith(("。", "．", "!", "？", "?", "！")):
                    softened = softened[:-1] + "（要確認）" + softened[-1]
                else:
                    softened = softened + "（要確認）"
                new_parts.append(softened)
                youkakunin_budget -= 1
                logger.debug(f"📎 引用なし時事断定を不確実化: {part[:40]!r}")
            else:
                new_parts.append(part)
        text = "".join(new_parts)

    _last_metrics = metrics
    return text


def record_trim_metric(applied: bool = True) -> None:
    global _last_metrics
    if applied:
        _last_metrics.trim_applied += 1


def record_truncation_metric() -> None:
    global _last_metrics
    _last_metrics.truncation_detected += 1
