"""Search formatter must pass published dates into the prompt block."""
from app.core.search.formatter import format_results, format_for_prompt


def test_format_results_keeps_published():
    raw = [
        {
            "title": "円急騰 為替介入か",
            "snippet": "7月30日に円が急騰",
            "url": "https://example.com/a",
            "source": "news",
            "published": "2026-07-30T12:00:00+09:00",
        }
    ]
    out = format_results(raw, query="為替介入")
    assert out
    assert out[0].get("published") == "2026-07-30T12:00:00+09:00"


def test_format_for_prompt_includes_published():
    results = [
        {
            "title": "ドル円、163.50円まで買い戻し",
            "snippet": "買い戻し",
            "url": "https://example.com/b",
            "source": "yahoo",
            "display_source": "yahoo",
            "published": "2026-07-29",
        },
        {
            "title": "日時なし記事",
            "snippet": "snippet",
            "url": "https://example.com/c",
            "source": "web",
            "display_source": "web",
        },
    ]
    text = format_for_prompt(results, query="為替介入")
    assert "(published: 2026-07-29)" in text
    assert "(published: unknown)" in text
    assert "ドル円、163.50円まで買い戻し" in text
