import hashlib
import json
import time
from pathlib import Path
from app.utils.logger import get_logger

logger = get_logger(__name__)

CACHE_DIR = Path("storage/search_cache")
CACHE_TTL = {
    "wiki":    86400,  # Wikipedia: 24時間
    "google":  3600,   # Google: 1時間
    "brave":   1800,   # Brave: 30分
    "news":    1800,   # ニュース: 30分
    "jina":    3600,   # Jina: 1時間
    "weather": 1800,   # 天気: 30分
    "general": 3600,
}

class SearchCache:
    def __init__(self):
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.warning(f"キャッシュディレクトリの作成に失敗しました: {e}")

    def _key(self, query: str, source: str) -> str:
        return hashlib.md5(f"{source}:{query}".encode()).hexdigest()

    def get(self, query: str, source: str = "general") -> list | None:
        try:
            path = CACHE_DIR / f"{self._key(query, source)}.json"
            if not path.exists():
                return None
            data = json.loads(path.read_text(encoding="utf-8"))
            ttl = CACHE_TTL.get(source, CACHE_TTL["general"])
            if time.time() - data["timestamp"] > ttl:
                path.unlink()
                return None
            return data["results"]
        except Exception as e:
            logger.warning(f"キャッシュの読み込みに失敗しました: {e}")
            return None

    def set(self, query: str, results: list, source: str = "general"):
        try:
            path = CACHE_DIR / f"{self._key(query, source)}.json"
            path.write_text(json.dumps({
                "timestamp": time.time(),
                "results":   results,
            }, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.warning(f"キャッシュの書き込みに失敗しました: {e}")

cache = SearchCache()
