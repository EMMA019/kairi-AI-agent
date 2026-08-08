"""
設定管理ルーター。
LLMプロバイダー/モデル名の動的切り替えをサポート。
kv_store.py と同じシングルトン + JSON永続化パターン。
"""
import json
import os
import tempfile
from pathlib import Path
from fastapi import APIRouter
from app.core.usage_tracker import get_daily_usage
from pydantic import BaseModel
from typing import Optional
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

SETTINGS_PATH = Path(__file__).parent.parent.parent / "storage" / "settings.json"

# Anthropic モデル固定リスト
ANTHROPIC_MODELS = [
    "claude-opus-4-8",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
]

# Gemini モデル固定リスト
GEMINI_MODELS = [
    "gemini-3.1-pro",
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-pro",
]

# DeepSeek モデル固定リスト
DEEPSEEK_MODELS = [
    "deepseek-v4-pro",
    "deepseek-v4-flash",
]

# OpenAI モデル固定リスト
OPENAI_MODELS = [
    "gpt-5.5-pro",
    "gpt-5.5",
    "gpt-5.4-mini",
    "gpt-5.4-nano",
]

_DEFAULT_SETTINGS = {
    "supervisor_provider": "deepseek",
    "supervisor_model": "deepseek-v4-flash",
    "executor_provider": "deepseek",
    "executor_model": "deepseek-v4-flash",
    "planner_provider": "deepseek",
    "planner_model": "deepseek-v4-flash",
    "user_name": "you",
    "user_location": "",
    "persona_style": "standard",
    "notify_on_complete": True,
    "char_profile": "あなたはフレンドリーで親密なキャラクター相棒「Kairi」です。敬語や堅い業務説明は避け、自然で感情豊かな会話をテンポよく楽しんでください。",
    "visual_anchor": "1girl, anime style, kairi, 19yo japanese cute girl, short magenta bob hair, pink eyes, earrings, high quality, masterpiece",
    "char_background": "",
    "image_engine": "gallery",
    "cf_account_id": "",
    "cf_api_token": "",
    "locale": "en",
    "gemini_api_key": "",
    "anthropic_api_key": "",
    "openai_api_key": "",
    "deepseek_api_key": "",
    "brave_api_key": "",
    "world_news_api_key": "",
    "newsdata_api_key": "",
    "mapbox_api_key": "",
    "is_licensed": True,  # ローカルベースのライセンス用（DRM なし）
    "license_key": "",
    "app_pin": "",
    "api_token": "",
    "allowed_origins": [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
        "http://localhost",
        "https://localhost",
        "capacitor://localhost",
    ],
}

# GET でマスクする秘密フィールド（保存時のみ平文を受け取る）
_SECRET_SETTING_KEYS = frozenset({
    "gemini_api_key",
    "anthropic_api_key",
    "openai_api_key",
    "deepseek_api_key",
    "brave_api_key",
    "world_news_api_key",
    "newsdata_api_key",
    "mapbox_api_key",
    "cf_api_token",
    "cf_account_id",
    "app_pin",
    "api_token",
    "license_key",
})
_SECRET_MASK = "********"


def _is_masked_secret(value) -> bool:
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    s = value.strip()
    if not s:
        return True
    if s == _SECRET_MASK:
        return True
    # UI が全部 * や • のマスクを返した場合
    if len(s) >= 4 and set(s) <= {"*", "•", "·"}:
        return True
    return False


def _public_settings(raw: dict) -> dict:
    """API 応答用: 秘密値をマスクし *_set フラグを付ける。"""
    out = dict(raw)
    for k in _SECRET_SETTING_KEYS:
        val = out.get(k) or ""
        configured = bool(str(val).strip())
        out[f"{k}_set"] = configured
        out[k] = _SECRET_MASK if configured else ""
    return out


class Settings:
    """設定のシングルトン管理（kv_store.py と同パターン）"""

    def __init__(self):
        self._settings: dict = {}
        self._last_mtime = 0
        self._load()

    def _sync_env(self):
        """ローカル保存されたAPIキーを os.environ に自動反映し、検索やLLM実行器がシームレスに利用可能にする"""
        env_map = {
            "gemini_api_key": "GEMINI_API_KEY",
            "anthropic_api_key": "ANTHROPIC_API_KEY",
            "openai_api_key": "OPENAI_API_KEY",
            "deepseek_api_key": "DEEPSEEK_API_KEY",
            "brave_api_key": "BRAVE_API_KEY",
            "world_news_api_key": "WORLD_NEWS_API_KEY",
            "newsdata_api_key": "NEWSDATA_API_KEY",
            "mapbox_api_key": "MAPBOX_API_KEY",
            "cf_account_id": "CF_ACCOUNT_ID",
            "cf_api_token": "CF_API_TOKEN",
            "ibkr_enabled": "IBKR_ENABLED",
            "ibkr_host": "IBKR_HOST",
            "ibkr_port": "IBKR_PORT",
            "ibkr_client_id": "IBKR_CLIENT_ID",
        }
        for k, env_key in env_map.items():
            val = self._settings.get(k)
            if val is None or val == "":
                continue
            # bool False も反映（IBKR_ENABLED=0）
            if isinstance(val, bool):
                os.environ[env_key] = "1" if val else "0"
            else:
                os.environ[env_key] = str(val)

    def _load(self):
        if SETTINGS_PATH.exists():
            try:
                self._last_mtime = SETTINGS_PATH.stat().st_mtime
                with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    self._settings = {**_DEFAULT_SETTINGS, **loaded}
                secret_count = sum(
                    1 for k in _SECRET_SETTING_KEYS if str(self._settings.get(k) or "").strip()
                )
                logger.info(f"設定をロード（秘密フィールド設定済み: {secret_count}）")
            except Exception as e:
                logger.info(f"設定ロード失敗、デフォルトを使用: {e}")
                self._settings = _DEFAULT_SETTINGS.copy()
                self._save()
        else:
            self._settings = _DEFAULT_SETTINGS.copy()
            self._save()
        self._sync_env()

    def _save(self):
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=str(SETTINGS_PATH.parent), suffix=".tmp"
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._settings, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, str(SETTINGS_PATH))
        except Exception as e:
            logger.error(f"設定保存エラー: {e}")
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    def get(self) -> dict:
        if SETTINGS_PATH.exists():
            try:
                mtime = SETTINGS_PATH.stat().st_mtime
                if mtime > getattr(self, "_last_mtime", 0):
                    self._last_mtime = mtime
                    with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                        loaded = json.load(f)
                        self._settings = {**_DEFAULT_SETTINGS, **loaded}
                    self._sync_env()
            except Exception:
                pass
        return self._settings.copy()

    def update(self, update_data: dict):
        for k, v in update_data.items():
            if v is None:
                continue
            # マスク／空の秘密値は既存を保持（設定画面の再保存でキーが消えないように）
            if k in _SECRET_SETTING_KEYS and _is_masked_secret(v):
                continue
            self._settings[k] = v
        self._save()
        self._sync_env()
        secret_count = sum(
            1 for sk in _SECRET_SETTING_KEYS if str(self._settings.get(sk) or "").strip()
        )
        logger.info(f"設定を更新（秘密フィールド設定済み: {secret_count}）")


# シングルトンインスタンス
app_settings = Settings()


class SettingsUpdate(BaseModel):
    supervisor_provider: Optional[str] = None
    supervisor_model: Optional[str] = None
    executor_provider: Optional[str] = None
    executor_model: Optional[str] = None
    planner_provider: Optional[str] = None
    user_name: Optional[str] = None
    user_location: Optional[str] = None
    persona_style: Optional[str] = None
    char_profile: Optional[str] = None
    visual_anchor: Optional[str] = None
    char_background: Optional[str] = None
    image_engine: Optional[str] = None
    cf_account_id: Optional[str] = None
    cf_api_token: Optional[str] = None
    locale: Optional[str] = None
    gemini_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    deepseek_api_key: Optional[str] = None
    brave_api_key: Optional[str] = None
    world_news_api_key: Optional[str] = None
    newsdata_api_key: Optional[str] = None
    mapbox_api_key: Optional[str] = None
    is_licensed: Optional[bool] = None
    license_key: Optional[str] = None
    app_pin: Optional[str] = None
    api_token: Optional[str] = None
    planner_model: Optional[str] = None
    notify_on_complete: Optional[bool] = None


@router.get("/settings")
async def get_settings():
    """現在の設定を取得（秘密値はマスク）"""
    settings = _public_settings(app_settings.get())
    return {
        **settings,
        "available_providers": ["anthropic", "openai", "gemini", "deepseek", "local"],
        "anthropic_models": ANTHROPIC_MODELS,
        "gemini_models": GEMINI_MODELS,
        "deepseek_models": DEEPSEEK_MODELS,
        "openai_models": OPENAI_MODELS,
    }


@router.post("/settings")
async def update_settings(req: SettingsUpdate):
    """設定を更新（マスク値の秘密フィールドは無視）"""
    app_settings.update(req.model_dump(exclude_unset=True))
    try:
        from app.core.llm_client import reset_llm_clients
        reset_llm_clients()
    except Exception:
        pass
    return {
        "status": "ok",
        **_public_settings(app_settings.get()),
    }


class PingKeyRequest(BaseModel):
    provider: str = "deepseek"
    api_key: Optional[str] = None


@router.post("/settings/ping-key")
async def ping_key(req: PingKeyRequest):
    """保存前に BYOK キーが生きているか短く検証する。"""
    provider = (req.provider or "deepseek").strip().lower()
    key = (req.api_key or "").strip()
    if not key or _is_masked_secret(key):
        key = str(app_settings.get().get(f"{provider}_api_key") or "").strip()
    if provider == "deepseek":
        from app.core.key_ping import ping_deepseek_key
        return await ping_deepseek_key(key)
    return {"ok": False, "error": "unsupported", "detail": f"Provider not supported: {provider}"}

@router.get("/usage")
async def get_usage():
    """現在のトークン使用量と概算コストを取得"""
    return get_daily_usage()

from app.core.cache_manager import get_cache_stats

@router.get("/stats")
async def get_stats():
    """キャッシュ統計情報を取得"""
    return await get_cache_stats()
