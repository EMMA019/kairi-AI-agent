"""レーダー誤マッチ・ATH・カレンダー休場ラベル・ブリーフHN除外の回帰テスト。"""
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

from app.core.monitor.watchlist import (
    extract_matched_targets_and_entities,
    systematic_screen_and_score,
)
from app.core.monitor.engine import (
    passes_radar_alert_gate,
    process_news_for_radar,
)
from app.core.market_calendar import format_market_status
from app.core.briefing.generator import (
    _is_briefing_noise_source,
    _is_stale_jp_close_headline,
)
from app.core.news.fetcher import ON_DEMAND_FEEDS
from app.core.news.database import (
    rank_news_items_for_chat,
    filter_news_by_freshness,
    _is_noise_news_source,
)

JST = timezone(timedelta(hours=9))


def test_education_does_not_match_cat_or_dividend_etfs():
    targets, entities = extract_matched_targets_and_entities(
        "grand canyon education outlines path to hybrid locations".lower()
    )
    assert "CAT" not in entities
    assert "^HDV" not in targets
    assert "^DGRO" not in targets
    assert "^DIV_TOP_ETFS" not in targets


def test_quarter_does_not_match_ter_soxx():
    targets, entities = extract_matched_targets_and_entities(
        "lvmh fashion and leather division reports 1% organic growth in second quarter".lower()
    )
    assert "TER" not in entities
    assert "^SOXX" not in targets


def test_earnings_does_not_match_gs_via_substring():
    targets, entities = extract_matched_targets_and_entities(
        "company reported strong quarterly earnings beat".lower()
    )
    assert "GS" not in entities


def test_path_does_not_trigger_ath_catalyst():
    item = {
        "title": "Grand Canyon Education outlines path to 80 hybrid locations",
        "summary": "Company plans to open a law school.",
        "source": "Seeking Alpha",
        "url": "https://example.com/path-to-growth",
    }
    scored = systematic_screen_and_score(item)
    cats = " ".join(scored.get("detected_catalysts") or [])
    assert "最高値" not in cats
    assert "時価総額最高" not in cats


def test_real_ath_still_detected():
    item = {
        "title": "Nvidia hits all-time high as AI demand soars",
        "summary": "Shares set a record high.",
        "source": "Reuters",
        "url": "https://example.com/nvda-ath",
    }
    scored = systematic_screen_and_score(item)
    cats = " ".join(scored.get("detected_catalysts") or [])
    assert "最高値" in cats or "時価総額" in cats


def test_jp_outside_hours_not_labeled_kyujitsu():
    # 金曜 08:15 JST = 取引時間外だが通常営業日
    dt = datetime(2026, 7, 31, 8, 15, tzinfo=JST)
    text = format_market_status(dt)
    assert "取引時間外（本日は通常営業日）" in text
    assert "休場 (outside_trading_hours)" not in text


def test_briefing_excludes_hacker_news():
    assert _is_briefing_noise_source({"source": "Hacker News", "url": "https://news.ycombinator.com/item?id=1"})
    assert not _is_briefing_noise_source({"source": "Reuters", "url": "https://www.reuters.com/x"})


def test_preopen_drops_stale_nikkei_close_headline():
    today = datetime(2026, 7, 31, 8, 15, tzinfo=JST)
    stale = {
        "title": "日経平均終値930円安、SK好決算「力不足」",
        "published": "2026-07-30T06:00:00Z",
        "summary": "",
    }
    assert _is_stale_jp_close_headline(stale, "preopen", today) is True
    assert _is_stale_jp_close_headline(stale, "postclose", today) is False


def test_surge_only_fails_radar_gate():
    """ターゲット + Reuters + shares surge だけでは通知しない。"""
    item = {
        "title": "Nvidia shares surge on optimism",
        "summary": "Shares surge in premarket trading.",
        "source": "Reuters",
        "url": "https://www.reuters.com/nvidia-surge",
    }
    scored = systematic_screen_and_score(item)
    assert scored.get("importance", 0) >= 75
    assert not (scored.get("detected_catalysts") or [])
    ok, reason = passes_radar_alert_gate(scored)
    assert ok is False
    assert "カタリスト" in reason


def test_earnings_miss_passes_radar_gate():
    item = {
        "title": "Nvidia reports unexpected earnings miss",
        "summary": "Company posted an earnings miss versus consensus.",
        "source": "Reuters",
        "url": "https://www.reuters.com/nvidia-miss",
    }
    scored = systematic_screen_and_score(item)
    assert scored.get("importance", 0) >= 75
    assert scored.get("detected_catalysts")
    ok, _ = passes_radar_alert_gate(scored)
    assert ok is True


def test_macro_fomc_reuters_passes_without_ticker():
    item = {
        "title": "Fed delivers surprise rate cut after FOMC",
        "summary": "Policy makers approved an emergency cut.",
        "source": "Reuters",
        "url": "https://www.reuters.com/fed-rate-cut",
    }
    scored = systematic_screen_and_score(item)
    assert "CENTRAL_BANK_MACRO" in (scored.get("detected_catalyst_ids") or [])
    assert scored.get("importance", 0) >= 75
    ok, _ = passes_radar_alert_gate(scored)
    assert ok is True


def test_surge_only_not_notified_end_to_end():
    item = {
        "title": "Nvidia shares surge on optimism",
        "summary": "Shares surge in premarket trading.",
        "source": "Reuters",
        "url": "https://www.reuters.com/nvidia-surge-e2e",
        "guid": "surge-only-e2e",
    }

    async def _run():
        with patch(
            "app.core.monitor.engine.send_discord_alert", new_callable=AsyncMock
        ) as mock_send, patch(
            "app.core.monitor.engine.get_recent_alerts",
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            "app.core.monitor.engine.init_monitor_db", new_callable=AsyncMock
        ), patch(
            "app.core.monitor.engine.log_rejected_news", new_callable=AsyncMock
        ), patch(
            "app.core.monitor.engine.save_alert_history", new_callable=AsyncMock
        ):
            alerts = await process_news_for_radar([item], dry_run=True)
            assert alerts == []
            mock_send.assert_not_called()

    asyncio.run(_run())


def test_hn_removed_from_on_demand_feeds():
    names = [f.get("name", "") for f in ON_DEMAND_FEEDS]
    assert "Hacker News" not in names
    assert not any("hnrss" in (f.get("url") or "") for f in ON_DEMAND_FEEDS)


def test_rank_news_excludes_hn_and_spam():
    items = [
        {
            "title": "Show HN: cool project",
            "summary": "discussion",
            "source": "Hacker News",
            "url": "https://news.ycombinator.com/item?id=1",
        },
        {
            "title": "10 best stocks to buy right now",
            "summary": "Motley Fool stock advisor picks",
            "source": "Motley Fool",
            "url": "https://example.com/best-stocks",
        },
        {
            "title": "Nvidia reports unexpected earnings miss",
            "summary": "Earnings miss versus Wall Street.",
            "source": "Reuters",
            "url": "https://www.reuters.com/nvda-miss-chat",
            "published": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
        },
    ]
    assert _is_noise_news_source(items[0]) is True
    ranked = rank_news_items_for_chat(items, limit=10)
    assert len(ranked) == 1
    assert "Nvidia" in ranked[0]["title"]


def test_freshness_filter_drops_old():
    old = {
        "title": "Old story",
        "published": (datetime.utcnow() - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%S"),
        "source": "Reuters",
        "url": "https://www.reuters.com/old",
    }
    fresh = {
        "title": "Fresh story",
        "published": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
        "source": "Reuters",
        "url": "https://www.reuters.com/fresh",
    }
    kept = filter_news_by_freshness([old, fresh], max_age_days=2)
    assert len(kept) == 1
    assert kept[0]["title"] == "Fresh story"


def test_search_news_ranked_prefers_high_score_pool(tmp_path, monkeypatch):
    async def _run():
        import app.core.news.database as dbmod

        monkeypatch.setattr(dbmod, "DB_PATH", str(tmp_path / "news_ranked.db"))
        await dbmod.init_db()
        now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
        await dbmod.save_news(
            [
                {
                    "title": "10 best stocks to buy right now",
                    "url": "https://example.com/spam",
                    "source": "Motley Fool",
                    "summary": "Motley Fool stock advisor",
                    "guid": "spam-1",
                    "published": now,
                },
                {
                    "title": "Nvidia reports unexpected earnings miss",
                    "url": "https://www.reuters.com/nvda-pool",
                    "source": "Reuters",
                    "summary": "Earnings miss versus consensus.",
                    "guid": "nvda-1",
                    "published": now,
                },
            ]
        )
        ranked = await dbmod.search_news_ranked("Nvidia", limit=10, max_age_days=7)
        assert ranked
        assert "earnings miss" in ranked[0]["title"].lower()
        assert all("best stocks" not in (r.get("title") or "").lower() for r in ranked)

    asyncio.run(_run())
