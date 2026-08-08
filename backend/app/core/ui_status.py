"""Localized UI / pipeline status strings for SSE progress (settings.locale)."""
from __future__ import annotations

from app.core.reply_language import normalize_locale

_PIPELINE = {
    "intent_analysis": {
        "en": "Analyzing intent and whether search is needed...",
        "ja": "ユーザーの意図と検索要否を分析中...",
    },
    "fact_checking": {
        "en": "Cross-checking search results and context...",
        "ja": "検索結果とコンテキストを照合・検証中...",
    },
    "composing": {
        "en": "Composing the answer...",
        "ja": "回答を構成・生成中...",
    },
    "searching": {
        "en": "Gathering information: {q}",
        "ja": "情報収集中: {q}",
    },
    "re_run_tests": {
        "en": "Re-running with test results applied…",
        "ja": "テスト結果を反映して再実行中…",
    },
    "fix_and_retry": {
        "en": "Retrying after error fix…",
        "ja": "エラー修正のため再実行中…",
    },
    "empty_tool_retry": {
        "en": "Retrying because the tool returned empty…",
        "ja": "ツール結果が空だったため再試行中…",
    },
    "empty_regen": {
        "en": "Regenerating after an empty response…",
        "ja": "空応答だったため再生成中…",
    },
    "save_long_then_body": {
        "en": "Saving long text to a file, then putting it back into the answer…",
        "ja": "長文をファイル保存してから本文へ載せ直します…",
    },
    "compose_from_search": {
        "en": "Composing answer from search results…",
        "ja": "検索結果から回答を構成中…",
    },
    "system_error": {
        "en": "A system error occurred. Could not complete the request.",
        "ja": "システムエラーが発生しました。処理を完了できませんでした。",
    },
}


def pipeline_detail(key: str, locale: str | None = None, **kwargs: object) -> str:
    loc = normalize_locale(locale)
    entry = _PIPELINE.get(key) or {}
    template = entry.get(loc) or entry.get("en") or key
    try:
        return template.format(**kwargs)
    except (KeyError, ValueError):
        return template


def get_ui_locale() -> str:
    """Current settings.locale for user-facing filter footnotes."""
    try:
        from app.routers.settings import app_settings

        return normalize_locale(app_settings.get().get("locale", "en"))
    except Exception:
        return "en"


_DISCLAIMERS = {
    "finance_estimate": {
        "en": (
            "\n\nNote: Some ratios, market indicators, or prices may include estimates "
            "or peripheral reference data not explicitly stated in the source articles. "
            "Please verify the latest figures from official disclosures."
        ),
        "ja": (
            "\n\n※一部の比率・市場指標や価格等はソース記事に明記されていない"
            "推計または周辺参考データを含む場合があります。"
            "正確な最新数値は公式開示データをご確認ください。"
        ),
    },
    "travel": {
        "en": (
            "\n\nNote: Details such as {categories} may change. "
            "Please confirm with official sites or venues before you go."
        ),
        "ja": (
            "\n\n※{categories}等の情報は変動する場合があります。"
            "お出かけ前に公式サイトや店舗へ直接ご確認いただくことをおすすめします。"
        ),
    },
    "generic_ref": {
        "en": (
            "\n\nNote: Information such as {categories} may be approximate or subject to change. "
            "Please check the latest details on the relevant official sites."
        ),
        "ja": (
            "\n\n※{categories}等の情報は参考値または変動する場合があります。"
            "最新の情報は各公式サイト等をご確認ください。"
        ),
    },
}


def disclaimer(key: str, locale: str | None = None, **kwargs: object) -> str:
    loc = normalize_locale(locale) if locale is not None else get_ui_locale()
    entry = _DISCLAIMERS.get(key) or {}
    template = entry.get(loc) or entry.get("en") or ""
    try:
        return template.format(**kwargs)
    except (KeyError, ValueError):
        return template


def has_finance_estimate_disclaimer(text: str) -> bool:
    if not text:
        return False
    markers = (
        "※一部の比率",
        "公式開示",
        "Some ratios, market indicators",
        "official disclosures",
        "peripheral reference data",
    )
    return any(m in text for m in markers)


def has_generic_ref_disclaimer(text: str) -> bool:
    if not text:
        return False
    markers = (
        "※正確な",
        "※最新の情報",
        "※各種情報",
        "※お出かけ前に",
        "※一部の比率",
        "Please confirm with official",
        "Please check the latest",
        "Some ratios, market indicators",
        "subject to change",
    )
    return any(m in text for m in markers)
