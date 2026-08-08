"""pytest 共通フィクスチャ — テスト間のイベントループ汚染を防ぐ。"""
from __future__ import annotations

import asyncio

import pytest


@pytest.fixture(autouse=True)
def _fresh_event_loop():
    """各テストに新しいイベントループを割り当て、閉じてから次へ進む。"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        yield
    finally:
        try:
            if not loop.is_closed():
                loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        try:
            loop.close()
        except Exception:
            pass
        asyncio.set_event_loop(None)
