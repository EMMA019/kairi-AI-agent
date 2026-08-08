"""Regression: FX spot quotes must not be mangled by JPY-conversion strippers."""
from app.core.fact_filters import check_currency_consistency, filter_fact
from app.core.fact_filters.currency import strip_unauthorized_jpy_conversions
from app.core.fact_filters.pipeline import apply_grounding_pipeline


def test_usd_jpy_spot_equals_form_preserved():
    raw = "7月30日、ドル円は1ドル＝162円台後半で推移していましたが、短時間で1ドル＝157円台後半まで約5円急騰しました。"
    cleaned = strip_unauthorized_jpy_conversions(raw)
    assert "162円台後半" in cleaned
    assert "157円台後半" in cleaned
    assert "1ドル台" not in cleaned
    assert cleaned == raw


def test_filter_fact_keeps_fx_spot():
    fact = "介入前は1ドル＝162円台後半、介入観測で一時1ドル＝157円台。"
    out = filter_fact(fact)
    assert "162円台後半" in out
    assert "157円台" in out
    assert "1ドル台" not in out


def test_check_currency_consistency_keeps_fx_spot():
    raw = "介入後はドル円が163.50円まで買い戻される場面もあり、1ドル＝162円台から動いた。"
    _, cleaned = check_currency_consistency(raw)
    assert "163.50円" in cleaned
    assert "162円台" in cleaned
    assert "1ドル台" not in cleaned


def test_grounding_pipeline_keeps_fx_spot():
    body = (
        "1ドル＝162円台後半で推移してましたが、介入観測で1ドル＝157円台後半まで円高が進みました。"
        "一方で介入後は163.50円まで買い戻される場面もありました。"
    )
    out = apply_grounding_pipeline(body, body, user_input="為替介入したわね")
    assert "162円台後半" in out
    assert "157円台後半" in out
    assert "163.50円" in out
    assert "1ドル台" not in out


def test_large_jpy_conversion_still_stripped():
    raw = "30億ポンド（約5700億円）を支出。イサク獲得（1億2500万ポンド＝約237億円）が最高額。"
    cleaned = strip_unauthorized_jpy_conversions(raw)
    assert "5700億円" not in cleaned
    assert "237億円" not in cleaned
    assert "30億ポンド" in cleaned
    assert "1億2500万ポンド" in cleaned
