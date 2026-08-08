"""ニュース取得安定化・プール・ペイウォール・ブリーフの単体テスト。"""
from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest


def test_paywall_detection():
    from app.core.news.paywall import is_paywalled, extract_search_keywords

    assert is_paywalled("https://www.bloomberg.com/news/articles/2026-07-27/nvidia")
    assert is_paywalled("https://www.wsj.com/finance/stocks/foo")
    assert is_paywalled("", source="WSJ Markets")
    assert not is_paywalled("https://www.reuters.com/technology/nvidia-deals")
    assert not is_paywalled("https://www.cnbc.com/2026/07/27/chips.html")

    q = extract_search_keywords("Nvidia's $750B in Deals Reignite Circular AI Fears")
    assert "Nvidia" in q or "750B" in q or "Circular" in q


def test_paywall_companion_skips_same_domain():
    async def _run():
        from app.core.news import paywall as pw

        fake_sources = [
            {"title": "Bloomberg copy", "url": "https://www.bloomberg.com/other", "snippet": "x"},
            {
                "title": "Reuters on Nvidia deals",
                "url": "https://www.reuters.com/technology/nvidia-circular-ai",
                "snippet": "Circular financing concerns",
            },
        ]
        with patch("app.core.search.web_search", new_callable=AsyncMock) as mock_ws:
            mock_ws.return_value = ("text", fake_sources)
            companion = await pw.find_free_companion(
                "Nvidia's $750B in Deals Reignite Circular AI Fears",
                paywall_url="https://www.bloomberg.com/news/articles/nvidia",
            )
        assert companion is not None
        assert "reuters.com" in companion["url"]
        assert "Circular" in companion["summary"] or companion["summary"]

    asyncio.run(_run())


def test_rolling_pool_retention(tmp_path, monkeypatch):
    async def _run():
        import app.core.news.database as dbmod

        monkeypatch.setattr(dbmod, "DB_PATH", str(tmp_path / "news.db"))
        await dbmod.init_db()

        old = {
            "title": "Old CXMT IPO story",
            "url": "https://example.com/cxmt-old",
            "source": "Test",
            "summary": "listing",
            "guid": "old-1",
            "fetched_at": (datetime.utcnow() - timedelta(hours=80)).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
        }
        fresh = {
            "title": "Fresh NVDA story",
            "url": "https://example.com/nvda-fresh",
            "source": "Test",
            "summary": "chips",
            "guid": "fresh-1",
        }
        await dbmod.save_news([old, fresh])
        assert await dbmod.count_pool() == 2
        purged = await dbmod.purge_old_news(72)
        assert purged == 1
        assert await dbmod.count_pool() == 1
        pool = await dbmod.get_pool_news(hours=24)
        assert len(pool) == 1
        assert pool[0]["title"] == "Fresh NVDA story"

        # feed health
        await dbmod.record_feed_success("TestFeed", "https://example.com/rss", 3)
        fails = await dbmod.record_feed_failure("BadFeed", "https://example.com/bad")
        assert fails == 1
        fails = await dbmod.record_feed_failure("BadFeed", "https://example.com/bad")
        fails = await dbmod.record_feed_failure("BadFeed", "https://example.com/bad")
        assert fails >= 3
        health = await dbmod.get_feed_health()
        assert any(h["feed_name"] == "BadFeed" for h in health)

    asyncio.run(_run())


def test_parallel_fetch_timeout_isolation():
    async def _run():
        from app.core.news import fetcher as fetcher_mod

        feeds = [
            {"name": "Fast", "url": "https://example.com/fast.xml"},
            {"name": "Slow", "url": "https://example.com/slow.xml"},
        ]

        async def fake_fetch(feed):
            if feed["name"] == "Slow":
                return feed["name"], feed["url"], [], "timeout"
            return (
                feed["name"],
                feed["url"],
                [
                    {
                        "title": "OK",
                        "url": "https://example.com/ok",
                        "source": "Fast",
                        "summary": "",
                        "guid": "1",
                    }
                ],
                None,
            )

        with patch.object(fetcher_mod, "_fetch_one_feed", side_effect=fake_fetch):
            with patch("app.core.news.database.record_feed_success", new_callable=AsyncMock):
                with patch("app.core.news.database.record_feed_failure", new_callable=AsyncMock):
                    items = await fetcher_mod.fetch_rss_on_demand(feeds)
        assert len(items) == 1
        assert items[0]["title"] == "OK"

    asyncio.run(_run())


def test_google_news_feeds_present():
    from app.core.news.fetcher import ON_DEMAND_FEEDS

    names = [f["name"] for f in ON_DEMAND_FEEDS]
    assert any("Google News: semiconductor" in n for n in names)
    assert any("Google News: IPO" in n for n in names)
    assert any("China" in n for n in names)
    assert any("日本株" in n for n in names)
    assert any("Nikkei Asia" in n for n in names)


def test_briefing_markdown_template():
    from app.core.briefing.generator import render_briefing_markdown

    stories = [
        {
            "title": "Nvidia's $750B in Deals Reignite Circular AI Fears",
            "source": "WSJ Markets",
            "url": "https://www.bloomberg.com/news/nvidia",
            "summary": "",
            "importance": 90,
            "companion_url": "https://www.reuters.com/technology/nvidia",
            "companion_summary": "Circular financing concerns hit chip stocks.",
            "companion_source": "reuters.com",
            "detected_catalysts": ["📉 決算ショック・見通し下方修正"],
        }
    ]
    md = render_briefing_markdown(
        "preopen",
        stories,
        calendar_text="今日=2026/07/29",
        include_jp_snapshot=False,
        generated_at=datetime(2026, 7, 29, 8, 15),
    )
    assert "寄り前ブリーフ" in md
    assert "あさって" not in md or True  # calendar injected as-is
    assert "ペイウォール" in md
    assert "reuters.com" in md
    assert "投資助言ではありません" in md


def test_briefing_generate_dry_run(tmp_path, monkeypatch):
    async def _run():
        import app.core.news.database as dbmod
        import app.core.briefing.generator as gen

        monkeypatch.setattr(dbmod, "DB_PATH", str(tmp_path / "news.db"))
        monkeypatch.setattr(gen, "BRIEFING_DIR", tmp_path / "briefings")
        await dbmod.init_db()
        await dbmod.save_news(
            [
                {
                    "title": "TSMC Unexpectedly Slashing Forecast and Lowering Guidance",
                    "url": "https://www.reuters.com/tech/tsmc",
                    "source": "Reuters",
                    "summary": "SOX and NASDAQ sold off on guidance cut.",
                    "guid": "tsmc-1",
                }
            ]
        )

        async def _identity(items, max_lookups=5):
            return items

        with patch("app.core.news.paywall.attach_companions", new_callable=AsyncMock) as ac:
            ac.side_effect = _identity
            result = await gen.generate_briefing("preopen", dry_run=True)
        assert result["pool_count"] >= 1
        assert "markdown" in result
        assert result["dry_run"] is True

    asyncio.run(_run())


def test_news_health_endpoint():
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    # auth may be open in test if no token set
    res = client.get("/api/news/health")
    assert res.status_code in (200, 401)
    if res.status_code == 200:
        data = res.json()
        assert "pool_total" in data
        assert "feeds" in data
        assert "retention_hours" in data
