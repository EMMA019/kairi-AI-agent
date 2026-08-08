"""ブリーフィング v1: 解説 grounding・数値テーブル・list/file API。"""
from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest


def test_us_settled_quotes_section_with_mock():
    from app.core.briefing import generator as gen

    fake_batch = {
        "source": "yfinance",
        "quotes": {
            "DIA": {"current_price": 400.5, "change": 1.2, "change_pct": 0.3},
            "SPY": {"current_price": 550.0, "change": -2.0, "change_pct": -0.36},
            "QQQ": {"current_price": 480.0, "change": 0.5, "change_pct": 0.1},
            "SOXX": {"current_price": 220.0, "change": -5.0, "change_pct": -2.2},
            "USDJPY=X": {"current_price": 155.12, "change": 0.2, "change_pct": 0.13},
        },
        "errors": [],
    }
    with patch("app.core.tools.market_data._quotes_batch", return_value=fake_batch):
        md = gen._us_settled_quotes_section()
    assert "米国市場確定値" in md
    assert "400.50" in md or "400.5" in md
    assert "SOXX" in md
    assert "155.12" in md
    # フッター定型文以外に銘柄行の取得失敗が無いこと
    assert md.count("取得失敗") == 0 or "欠損は取得失敗" in md
    assert "| ダウ (DIA) | 取得失敗 |" not in md


def test_us_settled_quotes_section_failure():
    from app.core.briefing import generator as gen

    with patch(
        "app.core.tools.market_data._quotes_batch",
        side_effect=RuntimeError("network down"),
    ):
        md = gen._us_settled_quotes_section()
    assert "取得失敗" in md
    assert "DIA" in md or "ダウ" in md


def test_commentary_grounding_strips_ungrounded_numbers():
    """LLM が入力にない％を出した場合、grounding が金融向け免責を付与する。"""
    from app.core.briefing import generator as gen
    from app.core.fact_filters.pipeline import apply_grounding_pipeline

    async def _run():
        stories = [
            {
                "title": "Nvidia circular AI financing concerns",
                "summary": "Chip stocks sold off on circular deal fears.",
                "companion_summary": "",
            }
        ]
        snapshot = "| SPY | 550.00 | -0.36% |"

        with patch("app.core.llm_client.call_model", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = (
                "- NVDAは12.5%下落し、時価総額は大きく縮んだ\n"
                "- SPYは550付近で弱い"
            )
            with patch("app.routers.settings.app_settings") as mock_settings:
                mock_settings.get.return_value = {
                    "planner_provider": "deepseek",
                    "planner_model": "deepseek-v4-flash",
                }
                raw = await gen._generate_commentary(stories, snapshot)

        assert "12.5%" in raw
        source = gen._stories_source_blob(stories) + "\n" + snapshot
        filtered = apply_grounding_pipeline(raw, source, user_input="市場ブリーフィング解説")
        assert "※一部の比率" in filtered or "参考" in filtered or "推計" in filtered

    asyncio.run(_run())


def test_render_includes_commentary_and_us_quotes():
    from app.core.briefing.generator import render_briefing_markdown

    md = render_briefing_markdown(
        "preopen",
        [{"title": "Test", "source": "Reuters", "url": "https://reuters.com/x", "summary": "ok"}],
        include_us_quotes=True,
        us_quotes_section="## 米国市場確定値（前夜）\n\n| 指標 | 終値 | 前日比 |\n| --- | ---: | ---: |\n| SPY | 550.00 | -0.36% |\n",
        commentary="- 米国は半導体主導で軟調\n- SPYは550付近",
        generated_at=datetime(2026, 7, 29, 8, 15),
    )
    assert "今日のポイント" in md
    assert "米国市場確定値" in md
    assert "半導体主導" in md


def test_discord_text_split():
    from app.core.notify.discord import _split_discord_chunks, DISCORD_CONTENT_LIMIT

    short = _split_discord_chunks("hello")
    assert short == ["hello"]

    long = "A" * (DISCORD_CONTENT_LIMIT + 100)
    chunks = _split_discord_chunks(long)
    assert len(chunks) >= 2
    assert all(len(c) <= DISCORD_CONTENT_LIMIT for c in chunks)

    with_newlines = ("line\n" * 500)
    chunks2 = _split_discord_chunks(with_newlines)
    assert len(chunks2) >= 2


def test_briefing_list_and_file_api(tmp_path, monkeypatch):
    import app.core.briefing.generator as gen

    monkeypatch.setattr(gen, "BRIEFING_DIR", tmp_path)
    (tmp_path / "2026-07-29_preopen.md").write_text("# hello\n", encoding="utf-8")

    files = gen.list_briefing_files()
    assert any(f["filename"] == "2026-07-29_preopen.md" for f in files)

    body = gen.read_briefing_file("2026-07-29_preopen.md")
    assert "hello" in body

    with pytest.raises(ValueError):
        gen.read_briefing_file("../secrets.txt")
    with pytest.raises(ValueError):
        gen.read_briefing_file("evil.md")
    with pytest.raises(FileNotFoundError):
        gen.read_briefing_file("2099-01-01_preopen.md")


def test_briefing_list_file_http_endpoints(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    import app.core.briefing.generator as gen

    monkeypatch.setattr(gen, "BRIEFING_DIR", tmp_path)
    (tmp_path / "2026-07-29_postclose.md").write_text("# post\n", encoding="utf-8")

    client = TestClient(app)
    res = client.get("/api/briefing/list")
    assert res.status_code in (200, 401)
    if res.status_code == 200:
        assert any(f["filename"] == "2026-07-29_postclose.md" for f in res.json()["files"])

    res2 = client.get("/api/briefing/file/2026-07-29_postclose.md")
    assert res2.status_code in (200, 401)
    if res2.status_code == 200:
        assert "post" in res2.json()["content"]

    res3 = client.get("/api/briefing/file/evil.md")
    assert res3.status_code in (400, 401)
    res4 = client.get("/api/briefing/file/2026-07-29_preopen.md.bak")
    assert res4.status_code in (400, 401)
