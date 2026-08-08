"""
KVメモリ管理モジュール。
demo.py の mock_kv_store + filter_kv_by_scope() + format_kv_for_prompt() を移植。
JSON ファイルで永続化。
"""
import json
from typing import Optional
from app.utils.logger import get_logger
from app.core.database import get_db

logger = get_logger(__name__)

# demo.py から移植したデフォルトKVデータ（10件）
_DEFAULT_KV_DATA = [
    {"category": "preference", "quote": "コーヒーはブラック派かな", "summary": {"target": "コーヒー", "stance": "好き", "tags": ["飲み物", "カフェ", "ブラック", "珈琲"]}},
    {"category": "preference", "quote": "辛いものはあんまり得意じゃない", "summary": {"target": "辛い食べ物", "stance": "苦手", "tags": ["辛い", "スパイス", "唐辛子", "激辛", "料理"]}},
    {"category": "profile", "quote": "猫を2匹飼ってる", "summary": {"target": "猫", "stance": "好き", "tags": ["ペット", "動物", "ねこ", "にゃんこ"]}},
    {"category": "preference", "quote": "ロックよりジャズが好き", "summary": {"target": "ジャズ", "stance": "好き", "tags": ["音楽", "ジャズ", "ロック", "楽器", "演奏"]}},
    {"category": "agreement", "quote": "毎週金曜は早めに切り上げたい", "summary": {"target": "金曜の早退", "stance": "条件付き", "tags": ["金曜", "早退", "仕事", "勤務時間"]}},
    {"category": "preference", "quote": "登山はきついから苦手", "summary": {"target": "登山", "stance": "苦手", "tags": ["山", "アウトドア", "ハイキング", "運動"]}},
    {"category": "profile", "quote": "在宅勤務がメイン", "summary": {"target": "在宅勤務", "stance": "好き", "tags": ["リモートワーク", "テレワーク", "仕事", "自宅"]}},
    {"category": "preference", "quote": "映画は静かなドラマ系が好み", "summary": {"target": "静かなドラマ映画", "stance": "好き", "tags": ["映画", "ドラマ", "映画鑑賞", "DVD", "Netflix"]}},
    {"category": "preference", "quote": "甘いお酒は苦手、辛口が好き", "summary": {"target": "辛口のお酒", "stance": "好き", "tags": ["お酒", "酒", "辛口", "ワイン", "日本酒", "ビール", "飲み会"]}},
    {"category": "agreement", "quote": "誕生日は特に祝わなくていい", "summary": {"target": "誕生日祝い", "stance": "条件付き", "tags": ["誕生日", "お祝い", "プレゼント", "記念日"]}},
]

class KVStore:
    """KVメモリの管理（CRUD + フィルタリング + Turso/SQLite永続化）"""

    def __init__(self):
        pass

    async def _init_defaults_if_empty(self):
        """空DBでもデモ記憶は自動挿入しない（猫・登山などの偽プロフィール汚染を防ぐ）。

        旧 demo データが必要な場合のみ環境変数 KAIRI_SEED_DEMO_KV=1 で有効化。
        """
        import os
        if os.environ.get("KAIRI_SEED_DEMO_KV", "").strip() != "1":
            return
        async with get_db() as db:
            result = await db.execute("SELECT COUNT(id) FROM kv_memories")
            row = await result.fetchone()
            count = row[0] if row else 0
            if count == 0:
                for entry in _DEFAULT_KV_DATA:
                    await self._insert_to_db(db, entry)
                await db.commit()
                logger.info("KVメモリのデフォルトデータをデータベースに挿入しました。")

    async def _insert_to_db(self, db, entry: dict):
        summary = entry.get("summary", {})
        tags = summary.get("tags", [])
        await db.execute(
            """
            INSERT INTO kv_memories (category, quote, target, stance, note, tags)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                entry.get("category"),
                entry.get("quote"),
                summary.get("target"),
                summary.get("stance"),
                summary.get("note"),
                json.dumps(tags, ensure_ascii=False) if tags else "[]"
            )
        )

    def _row_to_dict(self, row) -> dict:
        # id: 0, category: 1, quote: 2, target: 3, stance: 4, note: 5, tags: 6
        tags_str = row[6]
        tags = json.loads(tags_str) if tags_str else []
        return {
            "id": row[0],
            "category": row[1],
            "quote": row[2],
            "summary": {
                "target": row[3],
                "stance": row[4],
                "note": row[5],
                "tags": tags
            }
        }

    async def get_all(self) -> list[dict]:
        """全KVエントリを取得"""
        await self._init_defaults_if_empty()
        async with get_db() as db:
            result = await db.execute("SELECT id, category, quote, target, stance, note, tags FROM kv_memories ORDER BY id ASC")
            rows = await result.fetchall()
            return [self._row_to_dict(row) for row in rows]

    async def get_by_category(self, category: str) -> list[dict]:
        """指定カテゴリのKVエントリを取得"""
        await self._init_defaults_if_empty()
        async with get_db() as db:
            result = await db.execute("SELECT id, category, quote, target, stance, note, tags FROM kv_memories WHERE category = ? ORDER BY id ASC", (category,))
            rows = await result.fetchall()
            return [self._row_to_dict(row) for row in rows]

    async def set(self, key: str, value: str) -> None:
        """永続KVへの一時データ書き込みは廃止（会話圧縮による増殖を防ぐ）。

        以前は profile + tags「一時データ/スキャン結果」で INSERT していたが、
        明示保存ゲートをバイパスして市場ファクト等が無制限に増える原因だった。
        呼び出し側は履歴要約など別経路へ移すこと。このメソッドは no-op。
        """
        logger.warning(
            f"kv_store.set は廃止済み（no-op）: key={key!r} value_len={len(value or '')}"
        )
        return

    async def get(self, key: str) -> str | None:
        """任意のキーで保存されたデータを取得"""
        await self._init_defaults_if_empty()
        async with get_db() as db:
            result = await db.execute("SELECT note FROM kv_memories WHERE target = ?", (key,))
            row = await result.fetchone()
            if row:
                return row[0]
            return None

    async def add(self, entry: dict) -> dict:
        """新規KVエントリを追加（近い target があれば update にフォールバックして重複増殖を防ぐ）"""
        await self._init_defaults_if_empty()
        summary = entry.get("summary", {}) or {}
        target = summary.get("target") or ""
        similar = await self.find_similar_target(target)
        if similar and similar.get("id") is not None:
            logger.info(f"KV重複抑制: '{target}' → 既存 id={similar['id']} を更新")
            updated = await self.update(similar["id"], entry)
            return updated or similar

        async with get_db() as db:
            tags = summary.get("tags", [])
            await db.execute(
                """
                INSERT INTO kv_memories (category, quote, target, stance, note, tags)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.get("category"),
                    entry.get("quote"),
                    summary.get("target"),
                    summary.get("stance"),
                    summary.get("note"),
                    json.dumps(tags, ensure_ascii=False) if tags else "[]"
                )
            )
            # 挿入した行のIDを取得
            result = await db.execute("SELECT last_insert_rowid()")
            row = await result.fetchone()
            new_id = row[0] if row else None
            
            await db.commit()
            
            entry["id"] = new_id
            logger.info(f"KV追加: {summary.get('target', 'unknown')}")
            return entry

    async def delete(self, entry_id: int) -> bool:
        """指定IDのKVエントリを削除"""
        async with get_db() as db:
            result = await db.execute("SELECT id FROM kv_memories WHERE id = ?", (entry_id,))
            if not await result.fetchone():
                return False
            await db.execute("DELETE FROM kv_memories WHERE id = ?", (entry_id,))
            await db.commit()
            logger.info(f"KV削除: id={entry_id}")
            return True

    async def update(self, entry_id: int, entry: dict) -> Optional[dict]:
        """指定IDのKVエントリを更新"""
        async with get_db() as db:
            result = await db.execute("SELECT id, category, quote, target, stance, note, tags FROM kv_memories WHERE id = ?", (entry_id,))
            row = await result.fetchone()
            if not row:
                return None
                
            current = self._row_to_dict(row)
            
            # 部分更新
            if "quote" in entry and entry["quote"] is not None:
                current["quote"] = entry["quote"]
            if "summary" in entry and entry["summary"] is not None:
                for key, val in entry["summary"].items():
                    if val is not None:
                        current["summary"][key] = val
            if "category" in entry and entry["category"] is not None:
                current["category"] = entry["category"]
                
            tags = current["summary"].get("tags", [])
            await db.execute(
                """
                UPDATE kv_memories 
                SET category = ?, quote = ?, target = ?, stance = ?, note = ?, tags = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    current["category"],
                    current["quote"],
                    current["summary"].get("target"),
                    current["summary"].get("stance"),
                    current["summary"].get("note"),
                    json.dumps(tags, ensure_ascii=False) if tags else "[]",
                    entry_id
                )
            )
            await db.commit()
            logger.info(f"KV更新: id={entry_id}")
            return current

    async def get_exclusions(self) -> list[str]:
        """除外対象のキーワード一覧を取得"""
        exclusions = []
        async with get_db() as db:
            result = await db.execute("SELECT target, tags FROM kv_memories WHERE category = 'exclusion'")
            rows = await result.fetchall()
            for row in rows:
                exclusions.append(row[0])
                tags_str = row[1]
                tags = json.loads(tags_str) if tags_str else []
                exclusions.extend(tags)
        return exclusions

    async def filter_by_scope(self, user_input: str, top_k: int = 25) -> list[dict]:
        """
        記憶参照ポリシー（オプトイン）:
        - 明示的な「記憶を使って」等がある場合のみ、関連記憶を広く返す
        - それ以外は、今回の発話とキーワード一致したエントリだけを返す
        - profile/preference の常時全注入はしない（記憶参照違反の主因だった）
        """
        from app.core.memory_policy import (
            entry_matches_user_input,
            user_allows_memory_use,
        )

        all_memories = await self.get_all()
        candidates = [e for e in all_memories if e.get("category") != "exclusion"]
        if not candidates:
            return []

        # 明示許可時: キーワード一致を優先し、足りなければ profile/preference を補完
        if user_allows_memory_use(user_input):
            matched = [e for e in candidates if entry_matches_user_input(e, user_input)]
            if matched:
                return matched[:top_k]
            # 「記憶を使って」だけでテーマ未指定なら preference/profile/schedule を返す
            broad = [
                e for e in candidates
                if e.get("category") in ("project", "profile", "rule", "preference", "schedule", "agreement")
            ]
            return broad[:top_k]

        # デフォルト: キーワード一致のみ（一致なしなら空＝沈黙義務）
        matched = [e for e in candidates if entry_matches_user_input(e, user_input)]
        return matched[:top_k]

    async def find_similar_target(self, target: str) -> Optional[dict]:
        """正規化 target が近い既存エントリを返す（重複追加防止）。"""
        from app.core.memory_policy import normalize_target_key
        key = normalize_target_key(target)
        if not key:
            return None
        for entry in await self.get_all():
            existing = normalize_target_key((entry.get("summary") or {}).get("target") or "")
            if not existing:
                continue
            if existing == key or key in existing or existing in key:
                return entry
        return None

    def format_for_prompt(self, kv_list: list[dict]) -> str:
        """KVリストをプロンプト注入用テキストに整形"""
        if not kv_list:
            return "（現在保存されている長期記憶・プロジェクトはありません）"
        lines = ["【ユーザーの長期記憶・合意プロジェクト一覧】"]
        for kv in kv_list:
            cat = kv.get("category", "info")
            target = kv["summary"].get("target", "")
            stance = kv["summary"].get("stance", "")
            note = kv["summary"].get("note", "")
            quote = kv.get("quote", "")
            lines.append(f"- [{cat.upper()}] {target} ({stance}): {note} (引用: 「{quote}」)")
        return "\n".join(lines)

    async def format_summary(self) -> str:
        """全KVメモリの一覧をプロンプト注入用テキストに整形（AIが自分の記憶状態を把握するため）"""
        all_memories = await self.get_all()
        if not all_memories:
            return "（KVメモリは空です）"
        lines = []
        for kv in all_memories:
            cat = kv.get("category", "")
            target = kv["summary"].get("target", "")
            stance = kv["summary"].get("stance", "")
            note = kv["summary"].get("note", "")
            tags = kv["summary"].get("tags", [])
            detail = f'stance="{stance}"' if stance else f'note="{note}"'
            tags_str = ", ".join(tags) if tags else ""
            lines.append(
                f'- [ID:{kv["id"]}] category="{cat}", target="{target}", {detail}'
                + (f', tags=[{tags_str}]' if tags_str else '')
            )
        return "\n".join(lines)


# シングルトンインスタンス
kv_store = KVStore()