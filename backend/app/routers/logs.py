"""違和感ログ API ルーター（種類タグ付き）"""
import json
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter

from app.models.memory import ViolationLog
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()

VIOLATION_LOG_DIR = Path(__file__).parent.parent.parent / "storage" / "violation_logs"


@router.post("/log/violation")
async def log_violation(log: ViolationLog):
    """違和感ログを記録（日別JSONファイルに保存）"""
    VIOLATION_LOG_DIR.mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    log_file = VIOLATION_LOG_DIR / f"{today}.json"

    # 既存ログを読み込み
    existing_logs = []
    if log_file.exists():
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                existing_logs = json.load(f)
        except (json.JSONDecodeError, Exception):
            existing_logs = []

    # 新規ログを追加
    log_entry = log.model_dump()
    log_entry["timestamp"] = datetime.now().isoformat()
    existing_logs.append(log_entry)

    # 保存
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(existing_logs, f, ensure_ascii=False, indent=2)

    logger.info(f"違和感ログ記録: type={log.violation_type}")

    return {"success": True}


@router.get("/log/violations")
async def get_violations(date: str = None):
    """違和感ログを取得（日付指定可）"""
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    log_file = VIOLATION_LOG_DIR / f"{date}.json"

    if not log_file.exists():
        return {"logs": [], "date": date}

    try:
        with open(log_file, "r", encoding="utf-8") as f:
            logs = json.load(f)
    except (json.JSONDecodeError, Exception):
        logs = []

    return {"logs": logs, "date": date}
