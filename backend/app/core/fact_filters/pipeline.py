"""
グラウンディング統合パイプライン。

正規表現パッチを個別に増やすのではなく、この1関数経由で後処理する。
引用契約（citation）が代替できるフィルタは CONSOLIDATION_NOTES に記録し、
段階的に薄くしていく。
"""
from __future__ import annotations

from typing import Optional
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 引用契約で代替済み / 縮小予定のフィルタ（削除は eval 全パス後）
CONSOLIDATION_NOTES = {
    "verify_temporal_leadership_claims": "partial→citation.verify_citations (known risky names)",
    "verify_numbers_exist_in_source": "partial→citation absolute-number disclaimer",
    "strip_excuse_hallucinations": "kept (orthogonal to citations)",
    "trim_incomplete_trailing_sentence": "kept (truncation, not grounding)",
}


def apply_grounding_pipeline(
    text: str,
    source_text: str = "",
    user_input: str = "",
) -> str:
    """Executor最終出力に対する統合グラウンディング後処理。"""
    if not text:
        return text

    from .currency import check_currency_consistency
    from .financial import (
        verify_numbers_exist_in_source,
        soften_ungrounded_earnings_timing,
        correct_jp_session_price_labels,
        soften_stale_night_futures_claims,
        soften_us_morning_wrap_as_close,
    )
    from .temporal import (
        verify_chronological_rationalization,
        strip_outdated_past_event_predictions,
        strip_out_of_period_event_mentions,
        verify_holiday_and_weekend_claims,
        strip_unverified_day_of_week,
        fix_relative_date_labels,
    )
    from .entity import (
        verify_temporal_leadership_claims,
        filter_unknown_entity_listings,
        deduplicate_spot_listings,
        verify_exit_and_address_entanglement,
    )
    from .safety import (
        sanitize_buffer_contamination,
        sanitize_internal_tool_mentions,
        enforce_variable_numerical_claims,
    )
    from .markup import strip_internal_markup
    from .format import (
        correct_common_typos,
        strip_unrequested_memory_mentions,
        strip_omakase_skill_questions,
        strip_unrequested_yahoo_finance,
        clean_broken_markdown_tables,
        strip_excuse_hallucinations,
        strip_false_user_attribution,
        trim_incomplete_trailing_sentence,
        strip_dangling_tool_promises,
    )
    from .citation import verify_citations, reset_citation_metrics, record_trim_metric

    reset_citation_metrics()
    before = text

    text = strip_internal_markup(text)
    _, text = check_currency_consistency(text)
    _, text = verify_numbers_exist_in_source(text, source_text or "")
    # レガシー: 役職ハルシネーション（citation と併用、段階的縮小）
    text = verify_temporal_leadership_claims(text, source_text or "")
    text = verify_chronological_rationalization(text, source_text or "")
    text = filter_unknown_entity_listings(text)
    text = enforce_variable_numerical_claims(text, source_text or "", user_input=user_input or "")
    text = correct_common_typos(text)
    text = strip_unrequested_memory_mentions(text, user_input=user_input)
    text = strip_omakase_skill_questions(text, user_input=user_input)
    text = strip_unrequested_yahoo_finance(text, user_input=user_input)
    text = strip_outdated_past_event_predictions(text)
    text = deduplicate_spot_listings(text)
    text = verify_exit_and_address_entanglement(text)
    text = sanitize_internal_tool_mentions(text)
    text = clean_broken_markdown_tables(text)
    text = strip_out_of_period_event_mentions(text)
    text = verify_holiday_and_weekend_claims(text)
    text = fix_relative_date_labels(text)
    text = strip_excuse_hallucinations(text)
    text = strip_false_user_attribution(text, user_input=user_input or "")
    text = soften_ungrounded_earnings_timing(text, source_text or "")
    text = correct_jp_session_price_labels(text, source_text or "")
    text = soften_stale_night_futures_claims(text, source_text or "")
    text = soften_us_morning_wrap_as_close(text, source_text or "")
    text = sanitize_buffer_contamination(text)
    text = strip_unverified_day_of_week(text, source_text=source_text or "", strip_if_no_source=True)

    # 中核: 引用契約
    text = verify_citations(text, source_text or "")
    text = strip_dangling_tool_promises(text)
    text = trim_incomplete_trailing_sentence(text)

    if text != before:
        record_trim_metric(True)
    return text
