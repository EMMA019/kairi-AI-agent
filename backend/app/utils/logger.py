"""構造化ログ出力ユーティリティ"""
import logging
import json
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

_FILE_LOGGING_READY = False


class JSONFormatter(logging.Formatter):
    """JSON 形式のログフォーマッター"""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "extra_data"):
            log_data["data"] = record.extra_data
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_data, ensure_ascii=False)


def ensure_file_logging() -> None:
    """backend/storage/logs/kairi.log へローテーション付きで出す（起動時1回）。"""
    global _FILE_LOGGING_READY
    if _FILE_LOGGING_READY:
        return
    try:
        log_dir = Path(__file__).resolve().parents[2] / "storage" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(
            log_dir / "kairi.log",
            maxBytes=2_000_000,
            backupCount=5,
            encoding="utf-8",
        )
        fh.setFormatter(JSONFormatter())
        fh.setLevel(logging.INFO)
        root = logging.getLogger()
        root.setLevel(logging.INFO)
        # avoid duplicate file handlers
        if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
            root.addHandler(fh)
        _FILE_LOGGING_READY = True
    except Exception:
        pass


def get_logger(name: str) -> logging.Logger:
    """名前付きロガーを取得（JSON 出力）"""
    ensure_file_logging()
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        try:
            # For Windows environments with cp932 default, try to force utf-8 for json dumping emojis
            if hasattr(sys.stdout, 'reconfigure'):
                sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            pass
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = True  # also hit root file handler
    return logger
