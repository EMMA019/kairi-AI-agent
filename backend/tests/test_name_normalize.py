"""固有名表記ゆれ・検索関連度の単体テスト。"""
from app.core.fact_filters.name_normalize import (
    source_mentions_name,
    names_likely_match,
    katakana_to_romaji,
)
from app.core.fact_filters.citation import verify_citations
from app.core.search_relevance import is_search_effectively_empty


def test_murphy_katakana_matches_latin_source():
    src = "[1] The winner was ridden by O. Murphy. Final odds were 11.8."
    assert source_mentions_name("マーフィー", src)
    assert names_likely_match("マーフィー", "Murphy")


def test_unknown_name_not_in_source():
    src = "[1] Kalpana won. Jockey name is not mentioned."
    assert not source_mentions_name("ムーア", src)
    assert not source_mentions_name("ゼブラトン", src)


def test_citation_keeps_murphy_variant():
    src = "[1] The winner was ridden by O. Murphy."
    out = verify_citations("鞍上はマーフィー騎手でした[1]。", src)
    assert "マーフィー" in out
    assert "ソース未記載" not in out


def test_citation_softens_unknown_jockey():
    src = "[1] Race postponed. No jockey listed."
    out = verify_citations("ゼブラトン騎手が騎乗しました。", src)
    assert "ゼブラトン" not in out


def test_citation_does_not_destroy_common_katakana():
    src = "[1] AMD doubled in 2026. Mortgage rates rose."
    raw = (
        "ミニSaaSはAPIサービスです。ユーザーがキーワードを登録し、"
        "クレジットをプリペイドで購入します。"
    )
    out = verify_citations(raw, src)
    assert "API" in out
    assert "ユーザー" in out
    assert "キーワード" in out
    assert "クレジット" in out
    assert "ソース未記載" not in out
    assert out.count("（要確認）") <= 3


def test_search_effectively_empty_on_irrelevant():
    assert is_search_effectively_empty(
        "カルパナの騎手は誰",
        ["Kalpana King George jockey"],
        "【統合検索結果】\nToday's weather in Tokyo is sunny. Stock tips for beginners.",
    )


def test_search_not_empty_when_relevant():
    assert not is_search_effectively_empty(
        "カルパナの騎手は誰",
        ["Kalpana jockey"],
        "[1] Kalpana won King George. Jockey O. Murphy rode the winner.",
    )


def test_katakana_romaji_murphy_prefix():
    roma = katakana_to_romaji("マーフィー")
    assert roma.startswith("ma")
    assert "fi" in roma or "fu" in roma
