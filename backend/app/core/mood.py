"""
ムード管理モジュール（固定値版）。
Milestone 1 後に効果を再評価し、必要なら lazy 減衰ロジック等を追加。
"""
import json
from pathlib import Path

STORAGE_PATH = Path(__file__).parent.parent.parent / "storage" / "mood.json"

# demo.py と同じデフォルト値
_DEFAULT_MOOD = {"familiarity": 0.5, "activeness": 0.5}


def get_mood() -> dict:
    """現在のムード値を取得（固定値版）"""
    if STORAGE_PATH.exists():
        try:
            with open(STORAGE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, Exception):
            pass
    return _DEFAULT_MOOD.copy()


def set_mood(mood: dict) -> dict:
    """ムード値を設定（将来の拡張用）"""
    STORAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STORAGE_PATH, "w", encoding="utf-8") as f:
        json.dump(mood, f, ensure_ascii=False, indent=2)
    return mood
