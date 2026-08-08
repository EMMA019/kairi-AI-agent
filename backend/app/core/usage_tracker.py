import sqlite3
import datetime
from pathlib import Path
from app.utils.logger import get_logger

logger = get_logger(__name__)

DB_PATH = Path(__file__).parent.parent.parent / "storage" / "usage.db"

# モデルごとの単価 (100万トークンあたりのUSD)
MODEL_PRICING = {
    "gemini-3.1-pro": {"prompt": 1.25, "completion": 5.0},
    "gemini-3.5-flash": {"prompt": 0.075, "completion": 0.3},
    "gemini-3.1-flash-lite": {"prompt": 0.075, "completion": 0.3},
    "deepseek-v4-pro": {"prompt": 0.55, "completion": 2.19},
    "deepseek-v4-flash": {"prompt": 0.14, "completion": 0.28},
    "gpt-5.5-pro": {"prompt": 2.5, "completion": 10.0},
    "gpt-5.5": {"prompt": 2.5, "completion": 10.0},
    "gpt-5.4-mini": {"prompt": 0.15, "completion": 0.6},
}

# 1日の上限予算 (USD)
DAILY_BUDGET_USD = 1.0


def _init_db():
    """DBとテーブルの初期化"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS token_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                date_str TEXT NOT NULL,
                model_name TEXT NOT NULL,
                prompt_tokens INTEGER NOT NULL,
                completion_tokens INTEGER NOT NULL,
                estimated_cost_usd REAL NOT NULL
            )
        ''')
        # date_str のインデックスを作成して検索を高速化
        conn.execute('CREATE INDEX IF NOT EXISTS idx_date ON token_usage(date_str)')
        conn.commit()

_init_db()


def record_usage(model_name: str, prompt_tokens: int, completion_tokens: int):
    """API利用履歴をDBに記録する"""
    now = datetime.datetime.now(datetime.timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    timestamp = now.isoformat()

    # コスト計算
    cost = 0.0
    pricing = MODEL_PRICING.get(model_name)
    if pricing:
        cost = (prompt_tokens / 1_000_000) * pricing["prompt"] + (completion_tokens / 1_000_000) * pricing["completion"]
    else:
        # 未知のモデルのデフォルト単価 (高めに設定して安全寄りに)
        cost = (prompt_tokens / 1_000_000) * 1.0 + (completion_tokens / 1_000_000) * 2.0

    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "INSERT INTO token_usage (timestamp, date_str, model_name, prompt_tokens, completion_tokens, estimated_cost_usd) VALUES (?, ?, ?, ?, ?, ?)",
                (timestamp, date_str, model_name, prompt_tokens, completion_tokens, cost)
            )
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to record token usage: {e}")


def get_daily_usage(date_str: str = None) -> dict:
    """指定した日（デフォルトは本日 UTC）の合計使用量とコストを取得"""
    if not date_str:
        date_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.execute(
                "SELECT SUM(prompt_tokens), SUM(completion_tokens), SUM(estimated_cost_usd) FROM token_usage WHERE date_str = ?",
                (date_str,)
            )
            row = cursor.fetchone()
            
            prompt_tokens = row[0] or 0
            completion_tokens = row[1] or 0
            total_cost = row[2] or 0.0
            
            # モデル別の集計
            cursor = conn.execute(
                "SELECT model_name, SUM(prompt_tokens), SUM(completion_tokens), SUM(estimated_cost_usd) FROM token_usage WHERE date_str = ? GROUP BY model_name",
                (date_str,)
            )
            models_usage = [
                {
                    "model_name": m_row[0],
                    "prompt_tokens": m_row[1],
                    "completion_tokens": m_row[2],
                    "cost_usd": m_row[3]
                } for m_row in cursor.fetchall()
            ]
            
            return {
                "date": date_str,
                "total_prompt_tokens": prompt_tokens,
                "total_completion_tokens": completion_tokens,
                "total_cost_usd": total_cost,
                "daily_budget_usd": DAILY_BUDGET_USD,
                "is_budget_exceeded": total_cost >= DAILY_BUDGET_USD,
                "models": models_usage
            }
    except Exception as e:
        logger.error(f"Failed to get daily usage: {e}")
        return {
            "date": date_str,
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "total_cost_usd": 0.0,
            "daily_budget_usd": DAILY_BUDGET_USD,
            "is_budget_exceeded": False,
            "models": []
        }

def check_budget() -> bool:
    """本日の予算を超過していないかチェック。超過していれば False を返す"""
    usage = get_daily_usage()
    if usage["is_budget_exceeded"]:
        logger.warning(f"Daily budget exceeded: ${usage['total_cost_usd']:.4f} / ${DAILY_BUDGET_USD:.4f}")
        return False
    return True
