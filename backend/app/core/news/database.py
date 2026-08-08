"""
News DB — ローリングニュースプール（72時間保持）+ フィード健全性
"""
from __future__ import annotations

import aiosqlite
import json
import os
from datetime import datetime, timedelta
from typing import Any, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "news.db"
)

RETENTION_HOURS = 72


async def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS news (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guid TEXT,
                title TEXT,
                url TEXT,
                published TEXT,
                source TEXT,
                summary TEXT,
                category TEXT,
                importance INTEGER,
                sentiment TEXT,
                stock_codes TEXT,
                tags TEXT,
                body_text TEXT,
                companion_url TEXT,
                companion_summary TEXT,
                companion_source TEXT,
                fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # 既存DB向けマイグレーション（列がなければ追加）
        cols = {
            r[1]
            for r in await (await db.execute("PRAGMA table_info(news)")).fetchall()
        }
        for col, decl in [
            ("companion_url", "TEXT"),
            ("companion_summary", "TEXT"),
            ("companion_source", "TEXT"),
            ("fetched_at", "DATETIME"),
        ]:
            if col not in cols:
                await db.execute(f"ALTER TABLE news ADD COLUMN {col} {decl}")

        await db.execute("CREATE INDEX IF NOT EXISTS idx_news_guid ON news(guid)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_news_url ON news(url)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_news_title ON news(title)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_news_published ON news(published)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_news_fetched_at ON news(fetched_at)")

        await db.execute("""
            CREATE TABLE IF NOT EXISTS feed_health (
                feed_name TEXT PRIMARY KEY,
                feed_url TEXT,
                last_success DATETIME,
                last_failure DATETIME,
                consecutive_failures INTEGER DEFAULT 0,
                last_item_count INTEGER DEFAULT 0,
                total_successes INTEGER DEFAULT 0,
                total_failures INTEGER DEFAULT 0,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()

    purged = await purge_old_news(RETENTION_HOURS)
    logger.info(f"News DB initialized (rolling pool, purged={purged}).")


async def purge_old_news(retention_hours: int = RETENTION_HOURS) -> int:
    """fetched_at / created_at が retention_hours より古い行を削除。"""
    cutoff = (datetime.utcnow() - timedelta(hours=retention_hours)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            DELETE FROM news
            WHERE COALESCE(fetched_at, created_at) < ?
            """,
            (cutoff,),
        )
        await db.commit()
        return cur.rowcount or 0


async def is_duplicate(db: aiosqlite.Connection, item: dict) -> bool:
    guid = item.get("guid")
    url = item.get("url")
    title = item.get("title")

    if guid:
        cursor = await db.execute("SELECT id FROM news WHERE guid = ?", (guid,))
        if await cursor.fetchone():
            return True
    if url:
        cursor = await db.execute("SELECT id FROM news WHERE url = ?", (url,))
        if await cursor.fetchone():
            return True
    if title:
        cursor = await db.execute("SELECT id FROM news WHERE title = ?", (title,))
        if await cursor.fetchone():
            return True
    return False


async def save_news(items: list[dict]) -> int:
    """ニュースのリストをDBに保存。重複はスキップ。"""
    inserted = 0
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        for item in items:
            if await is_duplicate(db, item):
                continue

            stock_codes = json.dumps(item.get("stock_codes", []), ensure_ascii=False)
            tags = json.dumps(item.get("tags", []), ensure_ascii=False)
            guid = item.get("guid") or item.get("url") or ""

            await db.execute(
                """
                INSERT INTO news (
                    guid, title, url, published, source, summary,
                    category, importance, sentiment, stock_codes, tags, body_text,
                    companion_url, companion_summary, companion_source, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guid,
                    item.get("title"),
                    item.get("url"),
                    item.get("published"),
                    item.get("source"),
                    item.get("summary"),
                    item.get("category"),
                    item.get("importance"),
                    item.get("sentiment"),
                    stock_codes,
                    tags,
                    item.get("body_text"),
                    item.get("companion_url"),
                    item.get("companion_summary"),
                    item.get("companion_source"),
                    item.get("fetched_at") or now,
                ),
            )
            inserted += 1
        await db.commit()
    return inserted


async def update_companion(
    news_id: int,
    companion_url: str,
    companion_summary: str = "",
    companion_source: str = "",
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE news SET
                companion_url = ?,
                companion_summary = ?,
                companion_source = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (companion_url, companion_summary, companion_source, news_id),
        )
        await db.commit()


async def get_pool_news(hours: float = 18, limit: int = 200) -> list[dict]:
    """直近 hours 時間のプール記事を新しい順で返す。"""
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT * FROM news
            WHERE COALESCE(fetched_at, created_at) >= ?
            ORDER BY COALESCE(fetched_at, created_at) DESC
            LIMIT ?
            """,
            (cutoff, limit),
        )
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            r = dict(row)
            try:
                r["stock_codes"] = json.loads(r["stock_codes"]) if r.get("stock_codes") else []
                r["tags"] = json.loads(r["tags"]) if r.get("tags") else []
            except Exception:
                r["stock_codes"] = []
                r["tags"] = []
            results.append(r)
        return results


async def count_pool() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        row = await (await db.execute("SELECT COUNT(*) FROM news")).fetchone()
        return int(row[0]) if row else 0


async def record_feed_success(feed_name: str, feed_url: str, item_count: int) -> None:
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO feed_health (
                feed_name, feed_url, last_success, consecutive_failures,
                last_item_count, total_successes, updated_at
            ) VALUES (?, ?, ?, 0, ?, 1, ?)
            ON CONFLICT(feed_name) DO UPDATE SET
                feed_url = excluded.feed_url,
                last_success = excluded.last_success,
                consecutive_failures = 0,
                last_item_count = excluded.last_item_count,
                total_successes = total_successes + 1,
                updated_at = excluded.updated_at
            """,
            (feed_name, feed_url, now, item_count, now),
        )
        await db.commit()


async def record_feed_failure(feed_name: str, feed_url: str) -> int:
    """連続失敗回数を返し、3以上なら呼び出し側で警告する。"""
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO feed_health (
                feed_name, feed_url, last_failure, consecutive_failures,
                total_failures, updated_at
            ) VALUES (?, ?, ?, 1, 1, ?)
            ON CONFLICT(feed_name) DO UPDATE SET
                feed_url = excluded.feed_url,
                last_failure = excluded.last_failure,
                consecutive_failures = consecutive_failures + 1,
                total_failures = total_failures + 1,
                updated_at = excluded.updated_at
            """,
            (feed_name, feed_url, now, now),
        )
        row = await (
            await db.execute(
                "SELECT consecutive_failures FROM feed_health WHERE feed_name = ?",
                (feed_name,),
            )
        ).fetchone()
        await db.commit()
        return int(row[0]) if row else 1


async def get_feed_health() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await (
            await db.execute(
                "SELECT * FROM feed_health ORDER BY consecutive_failures DESC, feed_name ASC"
            )
        ).fetchall()
        return [dict(r) for r in rows]


async def update_news_analysis(news_id: int, analysis: dict):
    stock_codes = json.dumps(analysis.get("stocks", []), ensure_ascii=False)
    tags = json.dumps(analysis.get("tags", []), ensure_ascii=False)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE news SET
                importance = ?,
                sentiment = ?,
                category = ?,
                stock_codes = ?,
                tags = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                analysis.get("importance"),
                analysis.get("sentiment"),
                analysis.get("sector"),
                stock_codes,
                tags,
                news_id,
            ),
        )
        await db.commit()


async def update_news_body(news_id: int, body_text: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE news SET
                body_text = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (body_text, news_id),
        )
        await db.commit()


async def get_unprocessed_news() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM news WHERE importance IS NULL ORDER BY published DESC LIMIT 50"
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


def _parse_news_datetime(item: dict) -> Optional[datetime]:
    """published / fetched_at / created_at から日時を推定。"""
    for key in ("published", "fetched_at", "created_at"):
        raw = item.get(key)
        if not raw:
            continue
        if isinstance(raw, datetime):
            return raw.replace(tzinfo=None) if raw.tzinfo else raw
        s = str(raw).strip()
        try:
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
            return dt.replace(tzinfo=None) if dt.tzinfo else dt
        except ValueError:
            pass
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%a, %d %b %Y %H:%M:%S %z"):
            try:
                dt = datetime.strptime(s, fmt)
                return dt.replace(tzinfo=None) if dt.tzinfo else dt
            except ValueError:
                continue
    return None


def filter_news_by_freshness(items: list[dict], max_age_days: int) -> list[dict]:
    """max_age_days より古い記事を除外。日付不明は残す（RSS 要約のみ等）。"""
    if max_age_days <= 0:
        return items
    cutoff = datetime.utcnow() - timedelta(days=max_age_days)
    kept = []
    for it in items:
        dt = _parse_news_datetime(it)
        if dt is None or dt >= cutoff:
            kept.append(it)
    return kept


def _is_noise_news_source(item: dict) -> bool:
    src = (item.get("source") or "").lower()
    url = (item.get("url") or "").lower()
    return (
        "hacker news" in src
        or "ycombinator" in url
        or "hnrss" in url
        or "news.ycombinator.com" in url
    )


def rank_news_items_for_chat(items: list[dict], limit: int = 15) -> list[dict]:
    """スパム/HN除外のうえ systematic_screen_and_score で並べ替え。"""
    from app.core.monitor.watchlist import systematic_screen_and_score

    scored: list[dict] = []
    for item in items:
        if _is_noise_news_source(item):
            continue
        s = systematic_screen_and_score(item)
        if (s.get("importance") or 0) <= 0:
            continue
        scored.append(s)
    scored.sort(
        key=lambda x: (
            -(x.get("importance") or 0),
            0 if x.get("is_high_trust_source") else 1,
        )
    )
    return scored[:limit]


async def search_news(query: str = None, limit: int = 15) -> list[dict]:
    """チャットUIからの呼び出し用（後方互換）。キーワード OR 検索。"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        sql = "SELECT * FROM news WHERE 1=1"
        params: list[Any] = []

        if query:
            import re

            clean_q = re.sub(
                r"(教えて|気になる|について|ください)", "", query, flags=re.IGNORECASE
            ).strip()
            # after:YYYY-MM-DD は SQL ではなく呼び出し側の鮮度フィルタで扱う
            clean_q = re.sub(r"\bafter:\S+", "", clean_q, flags=re.IGNORECASE).strip()
            keywords = [w for w in re.split(r"\s+", clean_q) if len(w) >= 2]
            if not keywords and clean_q:
                keywords = [clean_q]
            if keywords:
                conditions = []
                for kw in keywords:
                    conditions.append(
                        "(title LIKE ? OR summary LIKE ? OR tags LIKE ? OR stock_codes LIKE ?)"
                    )
                    like_kw = f"%{kw}%"
                    params.extend([like_kw, like_kw, like_kw, like_kw])
                sql += " AND (" + " OR ".join(conditions) + ")"

        sql += " ORDER BY COALESCE(fetched_at, created_at) DESC, importance DESC LIMIT ?"
        params.append(limit)
        cursor = await db.execute(sql, tuple(params))
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            r = dict(row)
            try:
                r["stock_codes"] = json.loads(r["stock_codes"]) if r.get("stock_codes") else []
                r["tags"] = json.loads(r["tags"]) if r.get("tags") else []
            except Exception:
                pass
            results.append(r)
        return results


async def search_news_ranked(
    query: str = None,
    limit: int = 15,
    max_age_days: int = 7,
) -> list[dict]:
    """プール検索 → 鮮度フィルタ → スコア並べ替え。"""
    try:
        await init_db()
    except Exception:
        pass
    raw = await search_news(query, limit=max(limit * 4, 40))
    fresh = filter_news_by_freshness(raw, max_age_days)
    return rank_news_items_for_chat(fresh, limit=limit)
