"""
Cache Manager — LLM応答のセマンティックキャッシュ＆検索結果キャッシュ

【ポリシー】
- KVメモリの勝手参照は絶対に行わない（Supervisorの記憶ルールを遵守）
- 同じ入力＋同じコンテキストのLLM応答をキャッシュしてAPIコスト削減
- 検索結果はTTLベースでキャッシュ（APIレート制限対策）
"""
import json
import hashlib
import re
import time
import unicodedata
from typing import Optional
from pathlib import Path
import aiosqlite
from app.utils.logger import get_logger

logger = get_logger(__name__)

CACHE_DB_PATH = Path(__file__).parent.parent.parent / "cache" / "cache.db"
WORKSPACE_DIR = Path(__file__).parent.parent.parent / "workspace"

# ストップワード（クエリ正規化時に除去）
_STOP_WORDS = {
    # 日本語の指示語・依頼語
    "教えて", "ください", "お願い", "まとめて", "おしえて", "きいて",
    # 時間修飾語
    "最新", "今日の", "最近の", "昨日の", "明日の", "今週の", "今月の",
    # 一般的な主題語（検索には不要）
    "ニュース", "ニュ―ス", "情報", "話題", "レポート", "報告",
    # 英語ストップワード
    "the", "a", "an", "is", "are", "was", "were", "be", "been",
    "in", "on", "at", "to", "for", "of", "with", "by", "about",
    "and", "or", "but", "not", "do", "does", "did", "have", "has",
    "it", "its", "this", "that", "these", "those", "what", "which",
    "who", "whom", "how", "when", "where", "why",
    # 日本語助詞
    "を", "が", "の", "は", "に", "で", "と", "へ", "や", "から",
    "まで", "より", "も", "でも", "しか", "だけ", "ばかり", "までに",
    "くらい", "ほど", "など", "やら", "か", "な", "ね", "よ", "さ",
    "わ", "ぞ", "ぜ", "とも", "および", "ならびに",
}

# 英訳マッピング（日本語キーワード→英語）
_JA_TO_EN = {
    "世界": "world",
    "政治": "politics",
    "経済": "economy",
    "社会": "society",
    "国際": "international",
    "ビジネス": "business",
    "テクノロジー": "technology",
    "テック": "tech",
    "株式": "stock",
    "株": "stock",
    "相場": "market",
    "為替": "forex",
    "市場": "market",
    "雇用統計": "employment",
    "GDP": "gdp",
    "金利": "interest rate",
    "インフレ": "inflation",
    "企業": "company",
    "決算": "earnings",
    "予想": "forecast",
    "見通し": "outlook",
    "リスク": "risk",
    "投資": "investment",
    "不動産": "real estate",
    "商品": "commodity",
    "原油": "oil",
    "エネルギー": "energy",
    "環境": "environment",
    "日本": "japan",
    "中国": "china",
    "米国": "usa",
    "アメリカ": "usa",
    "ヨーロッパ": "europe",
    "欧州": "europe",
    "ロシア": "russia",
    "ウクライナ": "ukraine",
    "中東": "middle east",
}


# 日本語はスペース分割できないため、長いフレーズから先に除去する
_STOP_PHRASES = sorted(
    (w for w in _STOP_WORDS if len(w) >= 2 and not w.isascii()),
    key=len,
    reverse=True,
)

# LLM キャッシュを飛ばす時事・市場カテゴリ（search planner の category）
_FRESHNESS_CATEGORIES = frozenset({"finance", "news", "market"})

# 短い「株」単体は使わず、時事鮮度が必要な語に限定
_FRESHNESS_KEYWORDS = (
    "株価", "相場", "半導体", "AVGO", "インテル", "SOX", "SOXX",
    "暴落", "最高値", "利下げ", "利上げ", "インフレ", "為替",
    "論文", "スクレイピング",
)


def should_bypass_llm_cache(
    *,
    search_needed: bool = False,
    category: str = "general",
    user_input: str = "",
) -> tuple[bool, str]:
    """
    Supervisor LLM キャッシュを bypass すべきか。
    Returns: (bypass, reason)
    """
    if search_needed:
        return True, "search_needed"
    cat = (category or "general").lower().strip()
    if cat in _FRESHNESS_CATEGORIES:
        return True, f"category:{cat}"
    text = user_input or ""
    for kw in _FRESHNESS_KEYWORDS:
        if kw in text:
            return True, f"keyword:{kw}"
    return False, ""


def _normalize_query(text: str) -> str:
    """
    クエリ正規化: 大文字小文字・全半角・句読点・ストップワード除去・英訳
    
    CLINE級のキャッシュヒットを実現するため、
    「最新ニュースを教えて」と「ニュース教えて」が同一キャッシュキーになるよう正規化。
    """
    text = text.strip()
    
    # NFKC正規化（全角英数・スペース・記号・半角カタカナ等を標準的な文字に一括変換）
    text = unicodedata.normalize("NFKC", text)
    
    # 記号の正規化
    text = text.replace('、', ',').replace('。', '.')
    text = text.replace('？', '?').replace('！', '!')
    text = text.replace('・', ' ').replace('／', '/')
    
    # 小文字に統一
    text = text.lower()
    
    # 句読点や記号をスペースに変換（単語分割の準備）
    text = re.sub(r'[,.\?!:;()\[\]{}<>「」『』【】""''（）［］｛｝]', ' ', text)
    
    # --- 第0段階: 日本語ストップフレーズ除去（無スペース入力向け）---
    for phrase in _STOP_PHRASES:
        if phrase in text:
            text = text.replace(phrase, " ")
    
    # 連続する空白を1つに
    text = re.sub(r'\s+', ' ', text).strip()
    
    # --- 第1段階: ストップワード除去（スペース分割語）---
    words = text.split()
    filtered_words = []
    for w in words:
        if w.lower() not in _STOP_WORDS:
            filtered_words.append(w)
    text = ' '.join(filtered_words)
    
    # --- 第2段階: 日本語キーワードを英訳 ---
    words = text.split()
    translated_words = []
    for w in words:
        if w in _JA_TO_EN:
            translated_words.append(_JA_TO_EN[w])
        else:
            translated_words.append(w)
    text = ' '.join(translated_words)
    
    # --- 第3段階: 冗長な重複除去 ---
    words = text.split()
    unique_ordered = []
    seen = set()
    for w in words:
        if w not in seen:
            seen.add(w)
            unique_ordered.append(w)
    text = ' '.join(unique_ordered)
    
    return text.strip()


def _make_hash(user_input: str, system_prompt_hash: str, mode: str, model: str) -> str:
    """キャッシュキー生成（正規化後の入力を使用）"""
    key = f"{_normalize_query(user_input)}|{system_prompt_hash}|{mode}|{model}"
    return hashlib.md5(key.encode('utf-8')).hexdigest()


async def init_cache_db():
    """キャッシュDBの初期化（LRU + 圧縮対応）"""
    CACHE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(str(CACHE_DB_PATH)) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        
        # LLM応答キャッシュ
        await db.execute("""
            CREATE TABLE IF NOT EXISTS llm_cache (
                cache_key TEXT PRIMARY KEY,
                user_input TEXT,
                system_prompt_hash TEXT,
                mode TEXT,
                model TEXT,
                provider TEXT,
                response TEXT,
                reasoning TEXT,
                supervisor_json TEXT,
                response_size INTEGER DEFAULT 0,
                created_at REAL,
                last_access_at REAL,
                ttl_seconds INTEGER DEFAULT 1800,
                hit_count INTEGER DEFAULT 1
            )
        """)
        
        # 検索結果キャッシュ
        await db.execute("""
            CREATE TABLE IF NOT EXISTS search_cache (
                query_hash TEXT PRIMARY KEY,
                query TEXT,
                query_normalized TEXT,
                providers TEXT,
                results TEXT,
                sources TEXT,
                created_at REAL,
                last_access_at REAL,
                ttl_seconds INTEGER DEFAULT 1800,
                hit_count INTEGER DEFAULT 1
            )
        """)
        
        # コマンド実行結果キャッシュ
        await db.execute("""
            CREATE TABLE IF NOT EXISTS command_cache (
                cmd_hash TEXT PRIMARY KEY,
                command TEXT,
                workspace_git_hash TEXT,
                file_hash TEXT,
                result TEXT,
                result_size INTEGER DEFAULT 0,
                created_at REAL,
                last_access_at REAL,
                ttl_seconds INTEGER DEFAULT 3600,
                hit_count INTEGER DEFAULT 1
            )
        """)
        
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_llm_cache_created 
            ON llm_cache(created_at)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_search_cache_created
            ON search_cache(created_at)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_command_cache_created
            ON command_cache(created_at)
        """)
        
        try:
            await db.execute("ALTER TABLE search_cache ADD COLUMN query_normalized TEXT")
        except Exception:
            pass
            
        try:
            await db.execute("ALTER TABLE llm_cache ADD COLUMN response_size INTEGER DEFAULT 0")
        except Exception:
            pass
            
        try:
            await db.execute("ALTER TABLE llm_cache ADD COLUMN last_access_at REAL")
        except Exception:
            pass
            
        try:
            await db.execute("ALTER TABLE search_cache ADD COLUMN last_access_at REAL")
        except Exception:
            pass
            
        try:
            await db.execute("ALTER TABLE command_cache ADD COLUMN last_access_at REAL")
        except Exception:
            pass
        
        await db.commit()
    logger.info("Cache DB initialized with LRU support")


# LRU最大エントリ数
_MAX_CACHE_ENTRIES = {
    "llm_cache": 500,
    "search_cache": 1000,
    "command_cache": 200,
}


async def _lru_evict(table: str):
    """LRU削除: キャッシュが最大数を超えたら最終アクセスが最も古いエントリを削除"""
    max_entries = _MAX_CACHE_ENTRIES.get(table, 500)
    try:
        async with aiosqlite.connect(str(CACHE_DB_PATH)) as db:
            cursor = await db.execute(f"SELECT COUNT(*) FROM {table}")
            count = (await cursor.fetchone())[0]
            
            if count > max_entries:
                # 最終アクセスが古い順に、超過分を削除
                delete_count = count - max_entries + 50  # 50件バッファ
                await db.execute(
                    f"DELETE FROM {table} WHERE rowid IN "
                    f"(SELECT rowid FROM {table} ORDER BY last_access_at ASC LIMIT ?)",
                    (delete_count,)
                )
                await db.commit()
                logger.info(f"🧹 LRU evict: {table} ({delete_count}件削除)")
    except Exception as e:
        logger.warning(f"LRU evict error ({table}): {e}")


async def get_llm_cache(
    user_input: str,
    system_prompt: str,
    mode: str,
    model: str,
    provider: str,
    max_age_seconds: int = 1800,
) -> Optional[dict]:
    """LLM応答キャッシュから取得"""
    prompt_hash = hashlib.md5(system_prompt.encode('utf-8')).hexdigest()
    cache_key = _make_hash(user_input, prompt_hash, mode, model)
    
    try:
        async with aiosqlite.connect(str(CACHE_DB_PATH)) as db:
            cursor = await db.execute(
                "SELECT response, reasoning, supervisor_json, created_at, hit_count "
                "FROM llm_cache WHERE cache_key = ?",
                (cache_key,)
            )
            row = await cursor.fetchone()
            
            if row and (time.time() - row[3]) < max_age_seconds:
                # ヒット数と最終アクセス時刻を更新
                await db.execute(
                    "UPDATE llm_cache SET hit_count = ?, last_access_at = ? WHERE cache_key = ?",
                    (row[4] + 1, time.time(), cache_key)
                )
                await db.commit()
                
                logger.info(f"✅ LLM応答キャッシュヒット: {cache_key[:12]}... (hit_count: {row[4] + 1})")
                return {
                    "response": row[0],
                    "reasoning": row[1],
                    "supervisor_json": json.loads(row[2]) if row[2] else None,
                    "from_cache": True,
                }
    except Exception as e:
        logger.warning(f"Cache read error: {e}")
    
    return None


async def set_llm_cache(
    user_input: str,
    system_prompt: str,
    mode: str,
    model: str,
    provider: str,
    response: str,
    reasoning: Optional[str] = None,
    supervisor_json: Optional[dict] = None,
    ttl_seconds: int = 1800,
):
    """LLM応答をキャッシュに保存"""
    prompt_hash = hashlib.md5(system_prompt.encode('utf-8')).hexdigest()
    cache_key = _make_hash(user_input, prompt_hash, mode, model)
    
    try:
        async with aiosqlite.connect(str(CACHE_DB_PATH)) as db:
            await db.execute(
                """INSERT OR REPLACE INTO llm_cache 
                (cache_key, user_input, system_prompt_hash, mode, model, provider,
                 response, reasoning, supervisor_json, response_size, created_at, last_access_at, ttl_seconds)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    cache_key, _normalize_query(user_input), prompt_hash,
                    mode, model, provider,
                    response, reasoning,
                    json.dumps(supervisor_json, ensure_ascii=False) if supervisor_json else None,
                    len(response) + len(reasoning or ""),
                    time.time(), time.time(), ttl_seconds,
                )
            )
            await db.commit()
        
        # LRU evict
        await _lru_evict("llm_cache")
    except Exception as e:
        logger.warning(f"Cache write error: {e}")


async def get_search_cache(
    query: str,
    providers: list[str],
    max_age_seconds: int = 1800,
) -> Optional[dict]:
    """検索結果キャッシュから取得（短めのTTL）"""
    query_hash = hashlib.md5(
        _normalize_query(query).encode('utf-8')
    ).hexdigest()
    provider_str = ",".join(sorted(providers))
    
    try:
        async with aiosqlite.connect(str(CACHE_DB_PATH)) as db:
            cursor = await db.execute(
                "SELECT results, sources, created_at FROM search_cache WHERE query_hash = ? AND providers = ?",
                (query_hash, provider_str)
            )
            row = await cursor.fetchone()
            
            if row and (time.time() - row[2]) < max_age_seconds:
                await db.execute(
                    "UPDATE search_cache SET hit_count = hit_count + 1, last_access_at = ? WHERE query_hash = ?",
                    (time.time(), query_hash)
                )
                await db.commit()
                logger.info(f"✅ 検索キャッシュヒット: {query[:30]}...")
                return {
                    "results": row[0],
                    "sources": json.loads(row[1]) if row[1] else [],
                }
    except Exception as e:
        logger.warning(f"Search cache read error: {e}")
    
    return None


async def set_search_cache(
    query: str,
    providers: list[str],
    results: str,
    sources: list,
    ttl_seconds: int = 1800,
):
    """検索結果をキャッシュに保存"""
    query_hash = hashlib.md5(
        _normalize_query(query).encode('utf-8')
    ).hexdigest()
    provider_str = ",".join(sorted(providers))
    
    try:
        async with aiosqlite.connect(str(CACHE_DB_PATH)) as db:
            await db.execute(
                """INSERT OR REPLACE INTO search_cache
                (query_hash, query, query_normalized, providers, results, sources, created_at, ttl_seconds)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    query_hash, query, _normalize_query(query), provider_str,
                    results, json.dumps(sources, ensure_ascii=False) if sources else None,
                    time.time(), ttl_seconds,
                )
            )
            await db.commit()
    except Exception as e:
        logger.warning(f"Search cache write error: {e}")


async def get_command_cache(
    command: str,
    git_hash: str,
    affected_files: Optional[list[str]] = None,
    max_age_seconds: int = 3600,
) -> Optional[str]:
    """
    コマンド実行結果キャッシュから取得（ファイル内容ハッシュ付き）
    
    Args:
        command: 実行したコマンド
        git_hash: ワークスペースのGitハッシュ
        affected_files: コマンドが影響するファイルのパス一覧（内容ハッシュ計算用）
    """
    file_hash = _calc_file_hash(affected_files)
    cmd_key = hashlib.md5(f"{command}|{git_hash}|{file_hash}".encode('utf-8')).hexdigest()
    
    try:
        async with aiosqlite.connect(str(CACHE_DB_PATH)) as db:
            cursor = await db.execute(
                "SELECT result, created_at FROM command_cache WHERE cmd_hash = ?",
                (cmd_key,)
            )
            row = await cursor.fetchone()
            
            if row and (time.time() - row[1]) < max_age_seconds:
                await db.execute(
                    "UPDATE command_cache SET hit_count = hit_count + 1, last_access_at = ? WHERE cmd_hash = ?",
                    (time.time(), cmd_key)
                )
                await db.commit()
                logger.info(f"✅ コマンドキャッシュヒット: {command[:40]}...")
                return row[0]
    except Exception as e:
        logger.warning(f"Command cache read error: {e}")
    
    return None


def _calc_file_hash(affected_files: Optional[list[str]]) -> str:
    """影響を受けるファイルの内容ハッシュを計算（高速化・除外対応）"""
    if not affected_files:
        return ""
    
    try:
        from app.routers.workspace import get_workspace_dir, IGNORE_DIRS
        base_dir = get_workspace_dir()
    except Exception:
        base_dir = WORKSPACE_DIR
        IGNORE_DIRS = set()
    
    combined = []
    for fpath in affected_files:
        if any(part in IGNORE_DIRS for part in Path(fpath).parts):
            continue
        full_path = base_dir / fpath
        if full_path.exists():
            try:
                if full_path.stat().st_size > 1_000_000:
                    continue
                content = full_path.read_bytes()
                combined.append(hashlib.md5(content).hexdigest())
            except Exception:
                combined.append("")
    return hashlib.md5("|".join(combined).encode()).hexdigest() if combined else ""


async def set_command_cache(
    command: str,
    git_hash: str,
    result: str,
    affected_files: Optional[list[str]] = None,
    ttl_seconds: int = 3600,
):
    """
    コマンド実行結果をキャッシュに保存（ファイル内容ハッシュ付き）
    
    Args:
        command: 実行したコマンド
        git_hash: ワークスペースのGitハッシュ
        result: 実行結果
        affected_files: コマンドが影響するファイルのパス一覧
    """
    file_hash = _calc_file_hash(affected_files)
    cmd_key = hashlib.md5(f"{command}|{git_hash}|{file_hash}".encode('utf-8')).hexdigest()
    
    try:
        async with aiosqlite.connect(str(CACHE_DB_PATH)) as db:
            await db.execute(
                """INSERT OR REPLACE INTO command_cache
                (cmd_hash, command, workspace_git_hash, file_hash, result, created_at, ttl_seconds)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (cmd_key, command, git_hash, file_hash, result, time.time(), ttl_seconds)
            )
            await db.commit()
    except Exception as e:
        logger.warning(f"Cache write error: {e}")


# --- Greeting Short-Circuit (定型応答ショートサーキット) ---

GREETING_PATTERNS = {
    r'^(おはよう|おはよ|おは|good morning|おやすみ|おやすみなさい)': {
        "mode": "chat",
        "tone": "casual",
        "memory_inject": False,
        "search_used": False,
        "silence": False,
        "instruction": {
            "facts_to_present": ["ユーザーが挨拶をしている"],
            "logical_order": ["挨拶を返す", "簡単な気遣いの言葉を添える"],
            "tone_directive": None
        },
        "violation_risk": None,
        "kv_action": {"action": "none", "category": None, "quote": None, "summary": None},
    },
    r'^(こんにちは|こんばんは|やっほー|やあ|hello|hi|hey)': {
        "mode": "chat",
        "tone": "casual",
        "memory_inject": False,
        "search_used": False,
        "silence": False,
        "instruction": {
            "facts_to_present": ["ユーザーが挨拶をしている"],
            "logical_order": ["明るく挨拶を返す", "今日の気分を軽く尋ねる"],
            "tone_directive": None
        },
        "violation_risk": None,
        "kv_action": {"action": "none", "category": None, "quote": None, "summary": None},
    },
    r'^(ありがとう|あざ|さんきゅ|thanks|thank you|ありがと)': {
        "mode": "chat",
        "tone": "casual",
        "memory_inject": False,
        "search_used": False,
        "silence": False,
        "instruction": {
            "facts_to_present": ["ユーザーが感謝している"],
            "logical_order": ["どういたしましてと返す", "他に手伝えることがあれば聞く"],
            "tone_directive": None
        },
        "violation_risk": None,
        "kv_action": {"action": "none", "category": None, "quote": None, "summary": None},
    },
    r'^(わかった|了解|おっけー|りょ|りょうかい)': {
        "mode": "chat",
        "tone": "casual",
        "memory_inject": False,
        "search_used": False,
        "silence": False,
        "instruction": {
            "facts_to_present": ["ユーザーが了解した"],
            "logical_order": ["簡潔に承諾する", "次のアクションを促す"],
            "tone_directive": None
        },
        "violation_risk": None,
        "kv_action": {"action": "none", "category": None, "quote": None, "summary": None},
    },
}


def check_greeting_short_circuit(user_input: str) -> Optional[dict]:
    """定型挨拶を検出してショートサーキット用JSONを返す"""
    normalized = user_input.strip()
    for pattern, response in GREETING_PATTERNS.items():
        if re.match(pattern, normalized, re.IGNORECASE):
            logger.info(f"⚡ 定型応答ショートサーキット: {normalized[:20]}...")
            return response
    return None

async def get_cache_stats() -> dict:
    """キャッシュの統計情報（ヒット率など）を取得"""
    stats = {}
    try:
        async with aiosqlite.connect(CACHE_DB_PATH) as db:
            for table in ["llm_cache", "search_cache", "command_cache"]:
                try:
                    async with db.execute(f"SELECT COUNT(*), SUM(hit_count) FROM {table}") as cursor:
                        row = await cursor.fetchone()
                        count = row[0] if row and row[0] is not None else 0
                        hits = row[1] if row and row[1] is not None else 0
                        # hit_count DEFAULT 1 なので、実際には 1 回目は生成。キャッシュヒットは hit_count - 1
                        actual_hits = max(0, hits - count)
                        stats[table] = {
                            "entries": count,
                            "hits": actual_hits
                        }
                except Exception:
                    stats[table] = {"entries": 0, "hits": 0}
                    
        total_entries = sum(s["entries"] for s in stats.values())
        total_hits = sum(s["hits"] for s in stats.values())
        stats["total"] = {
            "entries": total_entries,
            "hits": total_hits
        }
    except Exception as e:
        logger.error(f"Failed to get cache stats: {e}")
    return stats
