"""
IBKR 口座照会の意図検出・コンテキスト注入・Supervisor ショートカット。

発注は扱わない。推測埋め禁止。
"""
from __future__ import annotations

import re
from typing import Any, Optional

from app.core.ibkr.client import (
    fetch_account_summary,
    fetch_positions,
    fetch_recent_fills,
    to_json,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

# \b は日本語（\w）直後で効かないため ASCII 境界のみ使う。
# IBKR/TWS にも ASCII 境界を必須化（"ibkr_autotrader" のような
# ワークスペース内プロジェクト名・ファイル名との誤マッチ防止）
_IB_REF = re.compile(
    r"(?i)(?<![A-Za-z0-9_])IBKR(?![A-Za-z0-9_])|Interactive\s*Brokers|(?<![A-Za-z0-9_])IB(?![A-Za-z0-9_])|"
    r"(?<![A-Za-z0-9_])TWS(?![A-Za-z0-9_])|デモ口座|ペーパー口座|ブローカー",
)


def detect_ibkr_intent(user_input: str) -> Optional[str]:
    """
    Returns: "account" | "positions" | "fills" | None
    """
    t = user_input or ""
    # 生のユーザー発言のみで判定する。注入されるワークスペース一覧
    # （"ibkr_autotrader" 等のプロジェクト名を含む）や動的システム
    # コンテキストは除外し、t[:200] フォールバックでもそれらを見ない。
    head = t.split("【現在のワークスペースのファイル（参考）】")[0]
    head = head.split("【動的システムコンテキスト】")[0]
    if not _IB_REF.search(head):
        return None
    blob = head[:500]
    if any(k in blob for k in ("約定", "fills", "執行履歴", "売買履歴")):
        return "fills"
    if any(k in blob for k in ("ポジション", "保有", "建玉", "持ち株")):
        return "positions"
    if any(k in blob for k in ("残高", "BuyingPower", "余力", "純資産", "NetLiquidation", "口座", "サマリー")):
        return "account"
    return "account"


def _tool_for_intent(intent: str) -> str:
    return {
        "account": "ibkr_account_summary",
        "positions": "ibkr_positions",
        "fills": "ibkr_recent_fills",
    }.get(intent, "ibkr_account_summary")


def format_ibkr_snapshot_for_prompt(user_input: str) -> str:
    intent = detect_ibkr_intent(user_input)
    if not intent:
        return ""
    try:
        if intent == "positions":
            payload = fetch_positions()
        elif intent == "fills":
            payload = fetch_recent_fills()
        else:
            payload = fetch_account_summary()
    except Exception as e:
        logger.warning(f"IBKR snapshot fetch failed: {e}")
        payload = {
            "ok": False,
            "error": "snapshot_exception",
            "message": str(e),
        }
    tool = _tool_for_intent(intent)
    return (
        "【IBKR 確定スナップショット（推測禁止・このJSONを優先）】\n"
        f"※ intent={intent} tool={tool}\n"
        f"{to_json(payload)}\n"
        "※ ok=false / 取得失敗の場合は数値を推測で埋めず『未確認』と書くこと。\n"
    )


def prepend_ibkr_snapshot(user_input: str, search_results_text: Optional[str]) -> Optional[str]:
    block = format_ibkr_snapshot_for_prompt(user_input)
    if not block:
        return search_results_text
    logger.info("注入: IBKR スナップショットをコンテキスト先頭に追加")
    if search_results_text and search_results_text.strip():
        return block + "\n\n" + search_results_text
    return block


def ibkr_supervisor_shortcut(user_input: str) -> Optional[dict[str, Any]]:
    intent = detect_ibkr_intent(user_input)
    if not intent:
        return None
    tool = _tool_for_intent(intent)
    return {
        "mode": "chat",
        "hearing_state": None,
        "spec_document": None,
        "search_used": False,
        "memory_inject": False,
        "silence": False,
        "tone": "casual",
        "instruction": {
            "facts_to_present": [
                "コンテキスト先頭の【IBKR 確定スナップショット】JSON のみを根拠にする",
                f"スナップショットが無い場合のみ先に <mcp_call tool=\"{tool}\" /> を出力し、結果を待つ",
                "ok=false のときは未確認と書き、残高・株数を推測しない",
                "システム障害の謝罪を捏造しない（JSON の error/message をそのまま伝える）",
            ],
            "logical_order": [
                "スナップショットまたはツール結果を確認する",
                "数値または未確認を簡潔に報告する",
            ],
            "tone_directive": None,
        },
        "plan": None,
        "violation_risk": None,
    }
