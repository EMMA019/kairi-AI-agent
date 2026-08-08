"""ユーザー誤帰属フレーズ除去と決算発表時刻ガードの単体テスト。"""
from app.core.fact_filters.format import strip_false_user_attribution
from app.core.fact_filters.financial import soften_ungrounded_earnings_timing
from app.core.fact_filters.pipeline import apply_grounding_pipeline


def test_strip_false_attribution_when_user_did_not_mention_timing():
    user = "MSFTとMETA決算はどうだったん？"
    text = "ご指摘いただいた通り、MSFTとMETAは日本時間7/30未明に決算を発表しています。"
    out = strip_false_user_attribution(text, user_input=user)
    assert "ご指摘いただいた通り" not in out
    assert "検索結果によれば" in out
    assert "MSFTとMETA" in out


def test_keep_attribution_when_user_mentioned_timing():
    user = "7/30未明だよね"
    text = "ご指摘いただいた通り、MSFTとMETAは日本時間7/30未明に決算を発表しています。"
    out = strip_false_user_attribution(text, user_input=user)
    assert "ご指摘いただいた通り" in out


def test_strip_ossharu_toori():
    user = "カルパナどうだった？"
    text = "おっしゃる通り、カルパナは未明に結果が出ています。"
    out = strip_false_user_attribution(text, user_input=user)
    assert "おっしゃる通り" not in out


def test_strip_ossharu_toori_desu_does_not_leave_nao_desu():
    """実害: Nao、おっしゃる通りです。 → Nao、です。 に壊さない。"""
    user = "為替介入したわね"
    text = (
        "Nao、おっしゃる通りです。昨夜から今朝にかけての報道を確認しましたので、"
        "整理してご説明します。\n\n## 結論\n介入が観測されています。"
    )
    out = strip_false_user_attribution(text, user_input=user)
    assert "おっしゃる通り" not in out
    assert "Nao、です" not in out
    assert "昨夜から今朝にかけての報道を確認しました" in out
    assert "介入が観測されています" in out


def test_soften_ungrounded_earnings_timing_without_source():
    text = "MSFTとMETAは日本時間7/30未明に決算を発表しています。"
    out = soften_ungrounded_earnings_timing(text, source_text="MSFT META earnings preview scheduled")
    assert "未明に" not in out
    assert "発表時刻はソース未確認" in out


def test_keep_earnings_timing_when_source_supports():
    text = "MSFTは引け後に発表済みです。"
    source = "Microsoft reported results after the close on Tuesday."
    out = soften_ungrounded_earnings_timing(text, source_text=source)
    assert "引け後に発表済み" in out


def test_pipeline_false_attribution_and_timing():
    user = "MSFTとMETA決算はどうだったん？"
    raw = "ご指摘いただいた通り、MSFTとMETAは日本時間7/30未明に決算を発表しています。"
    source = "MSFT and META earnings calendar: expected this week (preview)."
    out = apply_grounding_pipeline(raw, source, user_input=user)
    assert "ご指摘いただいた通り" not in out
    assert "未明に決算を発表" not in out
    assert "発表時刻はソース未確認" in out or "検索結果によれば" in out
