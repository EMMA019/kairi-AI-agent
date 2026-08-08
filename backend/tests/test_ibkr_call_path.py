# -*- coding: utf-8 -*-
"""IBKR 意図検出・ショートカット・スナップショット注入のテスト。"""
from __future__ import annotations

from unittest.mock import patch

from app.core.ibkr.intent import (
    detect_ibkr_intent,
    format_ibkr_snapshot_for_prompt,
    ibkr_supervisor_shortcut,
    prepend_ibkr_snapshot,
)
from app.core.chat_search import finalize_search_context

# 文字化け回避のため Unicode エスケープも併用
Q_BALANCE = "IBKR\u306e\u6b8b\u9ad8\u306f\uff1f"  # IBKRの残高は？
Q_POS = "IBKR\u306e\u30dd\u30b8\u30b7\u30e7\u30f3\u898b\u305b\u3066"  # IBKRのポジション見せて
Q_FILLS = "IBKR\u306e\u76f4\u8fd1\u7d04\u5b9a\u306f\uff1f"  # IBKRの直近約定は？


def test_detect_balance():
    assert detect_ibkr_intent(Q_BALANCE) == "account"
    assert detect_ibkr_intent("IBKR balance please") == "account"


def test_detect_positions():
    assert detect_ibkr_intent(Q_POS) == "positions"


def test_detect_fills():
    assert detect_ibkr_intent(Q_FILLS) == "fills"


def test_detect_ignores_unrelated():
    assert detect_ibkr_intent("today weather?") is None
    assert detect_ibkr_intent("Nikkei close?") is None


def test_supervisor_shortcut_has_tool_not_fake_error():
    short = ibkr_supervisor_shortcut(Q_BALANCE)
    assert short is not None
    facts = " ".join(short["instruction"]["facts_to_present"])
    assert "ibkr_account_summary" in facts
    assert "エラーが発生したこと" not in facts


def test_snapshot_inject_contains_ok():
    fake = {"ok": True, "data": {"account": "DU1", "tags": {"NetLiquidation": "1000"}}}
    with patch("app.core.ibkr.intent.fetch_account_summary", return_value=fake):
        text = format_ibkr_snapshot_for_prompt(Q_BALANCE)
    assert "IBKR" in text
    assert "NetLiquidation" in text
    assert '"ok": true' in text.lower().replace(" ", "") or '"ok": true' in text or "true" in text


def test_prepend_puts_block_first():
    fake = {"ok": False, "error": "ibkr_disabled", "message": "off"}
    with patch("app.core.ibkr.intent.fetch_account_summary", return_value=fake):
        out = prepend_ibkr_snapshot(Q_BALANCE, "OTHER_SEARCH foo")
    assert out.startswith("【IBKR") or out.startswith("\u3010IBKR")
    assert "OTHER_SEARCH foo" in out


def test_finalize_injects_even_without_search():
    fake = {"ok": False, "error": "gateway_unavailable", "message": "down"}
    with patch("app.core.ibkr.intent.fetch_account_summary", return_value=fake):
        text, unsupported = finalize_search_context(
            session_id="test-ibkr",
            user_input=Q_BALANCE,
            messages=[],
            search_needed=False,
            search_queries=[],
            search_results_text=None,
        )
    assert unsupported is False
    assert text is not None
    assert "gateway_unavailable" in text
