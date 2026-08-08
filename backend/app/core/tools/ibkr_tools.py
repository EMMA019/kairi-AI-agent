"""
IBKR 閲覧専用チャットツール。

発注・取消・変更は実装しない（コードパス不在）。
"""
from __future__ import annotations

from app.core.ibkr.client import (
    fetch_account_summary,
    fetch_positions,
    fetch_recent_fills,
    to_json,
)
from app.core.ibkr.schema import FILL_LIMIT_DEFAULT
from app.core.tools.registry import tool_registry


@tool_registry.register(
    name="ibkr_account_summary",
    description=(
        "Interactive Brokers（TWS/Gateway）から口座サマリーを取得する（読み取り専用）。"
        "NetLiquidation / Cash / BuyingPower 等。口座残高・余力の質問で使用。"
        "接続できない場合は ok=false のエラーJSONを返す。数値を推測で埋めてはいけない。"
    ),
)
def ibkr_account_summary() -> str:
    return to_json(fetch_account_summary())


@tool_registry.register(
    name="ibkr_positions",
    description=(
        "Interactive Brokers の現在ポジション一覧を取得する（読み取り専用）。"
        "銘柄・数量・平均取得単価。保有銘柄の質問で使用。"
        "接続できない場合は ok=false。推測禁止。"
    ),
)
def ibkr_positions() -> str:
    return to_json(fetch_positions())


@tool_registry.register(
    name="ibkr_recent_fills",
    description=(
        "Interactive Brokers の直近約定履歴を取得する（読み取り専用・既定20件・最大50件）。"
        "今日の売買確認で使用。接続できない場合は ok=false。推測禁止。"
    ),
)
def ibkr_recent_fills(limit: int = FILL_LIMIT_DEFAULT) -> str:
    return to_json(fetch_recent_fills(limit=limit))
