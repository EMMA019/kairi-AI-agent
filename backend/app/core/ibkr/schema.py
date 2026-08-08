"""
Fixed JSON shapes for IBKR read-only tools.

チャット／プロンプトが依存するキーをここに固定する。
フィールド追加は後方互換で行い、削除・改名はしない。
"""
from __future__ import annotations

from typing import Any

# 直近約定のデフォルト／上限（プランレビュー: 10〜20 から開始）
FILL_LIMIT_DEFAULT = 20
FILL_LIMIT_MAX = 50

# account_summary.data に必ず載せるタグ（無い場合は null）
ACCOUNT_SUMMARY_TAGS = (
    "NetLiquidation",
    "TotalCashValue",
    "BuyingPower",
    "GrossPositionValue",
    "UnrealizedPnL",
    "RealizedPnL",
    "AvailableFunds",
    "Currency",
)

# positions 1件の固定キー
POSITION_KEYS = (
    "symbol",
    "localSymbol",
    "secType",
    "currency",
    "exchange",
    "conId",
    "position",
    "avgCost",
)

# fills 1件の固定キー
FILL_KEYS = (
    "time",
    "symbol",
    "localSymbol",
    "side",
    "shares",
    "price",
    "commission",
    "currency",
    "execId",
    "orderId",
)


def error_payload(
    error: str,
    message: str,
    *,
    host: str | None = None,
    port: int | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "ok": False,
        "error": error,
        "message": message,
    }
    if host is not None:
        out["host"] = host
    if port is not None:
        out["port"] = port
    if extra:
        out.update(extra)
    return out


def ok_payload(data: Any, **meta: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"ok": True, "data": data}
    out.update(meta)
    return out


def empty_account_tags() -> dict[str, Any]:
    return {k: None for k in ACCOUNT_SUMMARY_TAGS}


def normalize_position(row: dict[str, Any]) -> dict[str, Any]:
    return {k: row.get(k) for k in POSITION_KEYS}


def normalize_fill(row: dict[str, Any]) -> dict[str, Any]:
    return {k: row.get(k) for k in FILL_KEYS}
