"""OSS 配布向け: 秘密マスク・医療誤検索・同梱ドキュメントの煙テスト。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.chat_search import (
    extract_us_company_search_seeds,
    is_soft_us_single_stock_query,
)
from app.routers import settings as settings_mod


ROOT = Path(__file__).resolve().parents[2]


def test_start_bat_and_build_script_exist():
    assert (ROOT / "start_kairi.bat").is_file()
    assert (ROOT / "scripts" / "prepare_embedded_python.ps1").is_file()
    assert (ROOT / "kairi_desktop.py").is_file()
    bat = (ROOT / "start_kairi.bat").read_text(encoding="utf-8", errors="ignore")
    assert "runtime\\python" in bat


def test_settings_mask_hides_secrets():
    raw = {
        **settings_mod._DEFAULT_SETTINGS,
        "deepseek_api_key": "sk-secret-real-value",
        "brave_api_key": "BSAsecret",
        "api_token": "tok-123",
    }
    pub = settings_mod._public_settings(raw)
    assert pub["deepseek_api_key"] == settings_mod._SECRET_MASK
    assert pub["deepseek_api_key_set"] is True
    assert pub["brave_api_key"] == settings_mod._SECRET_MASK
    assert "sk-secret" not in str(pub)
    assert pub["api_token"] == settings_mod._SECRET_MASK


def test_settings_update_skips_masked_secret():
    s = settings_mod.Settings.__new__(settings_mod.Settings)
    s._settings = {
        **settings_mod._DEFAULT_SETTINGS,
        "deepseek_api_key": "sk-keep-me",
    }
    s._last_mtime = 0
    # _save を呼ばないよう一時差し替え
    s._save = lambda: None  # type: ignore
    s._sync_env = lambda: None  # type: ignore
    s.update({"deepseek_api_key": "********", "user_name": "Nao"})
    assert s._settings["deepseek_api_key"] == "sk-keep-me"
    assert s._settings["user_name"] == "Nao"


def test_lab_paste_still_not_stock_search():
    text = "献血したんだけど、採決結果どう思う？血圧・脈拍\nALT（GPT）\n2026/7/30\nRBC 518"
    assert extract_us_company_search_seeds(text) == []
    assert is_soft_us_single_stock_query(text) is False


def test_mit_license_and_english_readme_exist():
    assert (ROOT / "LICENSE").is_file()
    lic = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "MIT License" in lic
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "BYOK" in readme
    assert "how’s the market" in readme or "how's the market" in readme
    assert (ROOT / "README.ja.md").is_file()
    assert (ROOT / "docs" / "DEMO.md").is_file()


def test_settings_example_defaults_english():
    import json

    example = ROOT / "backend" / "storage" / "settings.example.json"
    data = json.loads(example.read_text(encoding="utf-8"))
    assert data.get("locale") == "en"
    for k in (
        "deepseek_api_key",
        "openai_api_key",
        "anthropic_api_key",
        "brave_api_key",
        "license_key",
        "api_token",
    ):
        assert data.get(k, "") == ""
