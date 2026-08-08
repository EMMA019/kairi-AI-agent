"""Localized pipeline / UI status strings."""
from app.core.ui_status import disclaimer, pipeline_detail


def test_pipeline_detail_en():
    assert "Analyzing" in pipeline_detail("intent_analysis", "en")
    assert "Gathering information: foo" == pipeline_detail("searching", "en", q="foo")


def test_pipeline_detail_ja():
    assert "分析" in pipeline_detail("intent_analysis", "ja")
    assert pipeline_detail("searching", "ja", q="日経") == "情報収集中: 日経"


def test_finance_disclaimer_locale():
    en = disclaimer("finance_estimate", "en")
    ja = disclaimer("finance_estimate", "ja")
    assert "Some ratios, market indicators" in en
    assert "※一部の比率" in ja
    assert "※" not in en
