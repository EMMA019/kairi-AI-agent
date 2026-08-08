"""
ブリーフィング生成 — ローリングプールから下書き Markdown を作る。

寄り前 JST 08:15 / 大引け後 JST 16:00。
外部への自動公開はせず、storage/briefings/ に保存して目視確認用とする。
"""
from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Literal, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

JST = timezone(timedelta(hours=9))
BriefKind = Literal["preopen", "postclose"]

BRIEFING_DIR = Path(__file__).resolve().parents[3] / "storage" / "briefings"

# 寄り前ブリーフ用: 米国確定値（ETF 代理）とドル円
US_SETTLED_TICKERS: list[tuple[str, str]] = [
    ("DIA", "ダウ (DIA)"),
    ("SPY", "S&P500 (SPY)"),
    ("QQQ", "ナスダック100 (QQQ)"),
    ("SOXX", "半導体 SOXX"),
    ("USDJPY=X", "USD/JPY"),
]

_COMMENTARY_SYSTEM = """あなたは日本株投資家向けの市場ブリーフィング編集者です。
与えられたヘッドライン要旨と数値スナップショットだけを根拠に、「今日のポイント」を日本語で3〜5行書いてください。

厳守:
- 入力にない数値・日付・固有名詞・カタリストを追加しない
- 推測や「おそらく」「〜だろう」で事実を補完しない
- 投資助言・売買推奨は書かない
- Markdownの箇条書き（- ）のみ。見出しや装飾は不要
"""


def _now_jst() -> datetime:
    return datetime.now(JST)


_BRIEFING_EXCLUDE_SOURCES = {
    "hacker news",
    "hnrss",
}


def _is_briefing_noise_source(item: dict) -> bool:
    src = (item.get("source") or "").strip().lower()
    url = (item.get("url") or "").strip().lower()
    if src in _BRIEFING_EXCLUDE_SOURCES or "hacker news" in src:
        return True
    if "news.ycombinator.com" in url or "hnrss.org" in url:
        return True
    return False


def _is_stale_jp_close_headline(item: dict, kind: BriefKind, today: datetime) -> bool:
    """寄り前ブリーフで前日の『日経終値○○円安』を今日のポイントに載せない。"""
    if kind != "preopen":
        return False
    title = (item.get("title") or "") + " " + (item.get("summary") or "")
    if not re.search(r"日経.*終値|終値.*日経|930円安|円安で終了", title):
        return False
    pub = (item.get("published") or "").strip()
    if not pub:
        return True  # 日付不明の終値見出しは寄り前では降格
    try:
        # ざっくり YYYY-MM-DD を拾う
        m = re.search(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})", pub)
        if not m:
            return True
        from datetime import date as date_cls

        d = date_cls(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return d < today.date()
    except Exception:
        return True


async def _score_and_rank(
    items: list[dict],
    top_k: int = 5,
    *,
    kind: BriefKind = "preopen",
    now: Optional[datetime] = None,
) -> list[dict]:
    from app.core.monitor.watchlist import systematic_screen_and_score, systematic_deduplicate

    now = now or _now_jst()
    filtered = [
        it for it in items
        if not _is_briefing_noise_source(it) and not _is_stale_jp_close_headline(it, kind, now)
    ]
    scored = [systematic_screen_and_score(dict(it)) for it in filtered]
    scored.sort(key=lambda x: x.get("importance", 0), reverse=True)

    kept: list[dict] = []
    for c in scored:
        if c.get("importance", 0) < 50 and len(kept) >= 1:
            continue
        is_dup, _ = await systematic_deduplicate(c, kept)
        if not is_dup and c.get("importance", 0) >= 50:
            kept.append(c)
        if len(kept) >= top_k:
            return kept

    # バックフィルでも HN / 前日終値見出しは入れない
    if len(kept) < top_k:
        for c in scored:
            if c in kept:
                continue
            is_dup, _ = await systematic_deduplicate(c, kept)
            if not is_dup:
                kept.append(c)
            if len(kept) >= top_k:
                break
    return kept


def _format_story(item: dict, idx: int) -> str:
    title = (item.get("title") or "").strip()
    source = (item.get("source") or "").strip()
    url = (item.get("url") or "").strip()
    summary = (item.get("summary") or item.get("companion_summary") or "").strip()
    summary = re.sub(r"<[^>]+>", "", summary)
    if len(summary) > 280:
        summary = summary[:280] + "…"

    lines = [f"### {idx}. {title}"]
    if item.get("companion_url"):
        lines.append(
            f"- 初出（ペイウォール）: [{source}]({url})"
            if url
            else f"- 初出（ペイウォール）: {source}"
        )
        lines.append(
            f"- 無料ソース: [{item.get('companion_source') or 'free'}]({item['companion_url']})"
        )
        if item.get("companion_summary"):
            cs = re.sub(r"<[^>]+>", "", item["companion_summary"])
            lines.append(f"- 要旨: {cs[:280]}")
    else:
        if url:
            lines.append(f"- 出典: [{source}]({url})")
        else:
            lines.append(f"- 出典: {source}")
        if summary:
            lines.append(f"- 要旨: {summary}")

    importance = item.get("importance")
    if importance is not None:
        lines.append(f"- 重要度スコア: {importance}")
    catalysts = item.get("detected_catalysts") or []
    if catalysts:
        lines.append(f"- カタリスト: {', '.join(catalysts[:3])}")
    return "\n".join(lines)


def _fmt_quote_row(label: str, q: dict[str, Any] | None) -> str:
    if not q or q.get("current_price") is None:
        return f"| {label} | 取得失敗 | — |"
    price = q["current_price"]
    chg = q.get("change")
    pct = q.get("change_pct")
    if isinstance(price, (int, float)):
        price_s = f"{price:,.2f}"
    else:
        price_s = str(price)
    if chg is not None and pct is not None:
        sign = "+" if chg >= 0 else ""
        chg_s = f"{sign}{chg:,.2f} ({sign}{pct:.2f}%)"
    else:
        chg_s = "—"
    return f"| {label} | {price_s} | {chg_s} |"


_US_QUOTE_CACHE_PATH = BRIEFING_DIR / "us_settled_quotes_cache.json"


def _load_us_quote_cache() -> dict[str, Any]:
    try:
        import json

        if _US_QUOTE_CACHE_PATH.is_file():
            return json.loads(_US_QUOTE_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.debug(f"US quote cache load failed: {e}")
    return {}


def _save_us_quote_cache(payload: dict[str, Any]) -> None:
    try:
        import json

        BRIEFING_DIR.mkdir(parents=True, exist_ok=True)
        _US_QUOTE_CACHE_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning(f"US quote cache save failed: {e}")


def _us_settled_quotes_section() -> str:
    """寄り前用: 米国市場の確定値テーブル。失敗時は前回成功キャッシュを as_of 付きで使用。"""
    header = [
        "## 米国市場確定値（前夜）",
        "",
        "| 指標 | 終値 | 前日比 |",
        "| --- | ---: | ---: |",
    ]
    try:
        from app.core.tools.market_data import _quotes_batch

        tickers = [t for t, _ in US_SETTLED_TICKERS]
        batch = _quotes_batch(tickers, prefer_yfinance=True, enrich_vol_atr=False)
        quotes = (batch or {}).get("quotes") or {}
        ok_count = sum(
            1 for t, _ in US_SETTLED_TICKERS if (quotes.get(t) or {}).get("current_price") is not None
        )
        if ok_count >= 2:
            as_of = _now_jst().strftime("%Y-%m-%d %H:%M JST")
            cache_quotes = {
                t: quotes.get(t)
                for t, _ in US_SETTLED_TICKERS
                if (quotes.get(t) or {}).get("current_price") is not None
            }
            _save_us_quote_cache(
                {
                    "as_of": as_of,
                    "source": (batch or {}).get("source") or "yfinance",
                    "quotes": cache_quotes,
                }
            )
            rows = [_fmt_quote_row(label, quotes.get(ticker)) for ticker, label in US_SETTLED_TICKERS]
            src = (batch or {}).get("source") or "yfinance"
            header.extend(rows)
            header.append("")
            header.append(f"source={src} as_of={as_of}（API取得値。欠損は取得失敗と表示）")
            header.append("")
            return "\n".join(header)

        # レート制限等で全滅/ほぼ全滅 → キャッシュ
        cached = _load_us_quote_cache()
        cq = cached.get("quotes") or {}
        if cq:
            rows = []
            for ticker, label in US_SETTLED_TICKERS:
                q = cq.get(ticker) or quotes.get(ticker)
                rows.append(_fmt_quote_row(label, q))
            header.extend(rows)
            header.append("")
            header.append(
                f"source=cache as_of={cached.get('as_of', '?')} "
                f"（API失敗のため前回成功値。当日確定値として断定しない）"
            )
            header.append("")
            logger.warning("US settled quotes: using cache after API miss")
            return "\n".join(header)

        rows = [_fmt_quote_row(label, quotes.get(ticker)) for ticker, label in US_SETTLED_TICKERS]
        header.extend(rows)
        header.append("")
        header.append("source=yfinance（API取得値。欠損は取得失敗と表示）")
        header.append("")
        return "\n".join(header)
    except Exception as e:
        logger.warning(f"US settled quotes for briefing failed: {e}")
        cached = _load_us_quote_cache()
        cq = cached.get("quotes") or {}
        if cq:
            rows = [_fmt_quote_row(label, cq.get(ticker)) for ticker, label in US_SETTLED_TICKERS]
            return "\n".join(
                header
                + rows
                + [
                    "",
                    f"source=cache as_of={cached.get('as_of', '?')}（例外時フォールバック）",
                    "",
                ]
            )
        rows = [_fmt_quote_row(label, None) for _, label in US_SETTLED_TICKERS]
        return "\n".join(header + rows + ["", "（取得失敗）", ""])


def _jp_snapshot_section() -> str:
    """大引け後用: 日経・TOPIX-17＋日経前日比を明示。"""
    try:
        from app.core.tools.market_data import (
            format_jp_market_snapshot_for_prompt,
            get_jp_market_snapshot,
            _fmt_pct,
        )

        text = format_jp_market_snapshot_for_prompt("日本市場スナップショット")
        lines = ["## 日本市場スナップショット", ""]
        if text and text.strip():
            lines.append(text.strip())
            lines.append("")

        snap = get_jp_market_snapshot(include_sectors=True, prefer_yfinance=True)
        n225 = (snap.get("indices") or {}).get("^N225") or {}
        if n225.get("current_price") is not None:
            lines.append(f"**日経平均 前日比**: {_fmt_pct(n225)}")
            lines.append("")
        else:
            lines.append("**日経平均 前日比**: 取得失敗")
            lines.append("")
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"JP snapshot for briefing failed: {e}")
    return "## 日本市場スナップショット\n\n（取得失敗または休場）\n"


def _stories_source_blob(stories: list[dict]) -> str:
    return "\n".join(
        f"{s.get('title', '')}\n{s.get('summary', '')}\n{s.get('companion_summary', '')}"
        for s in stories
    )


async def _generate_commentary(
    stories: list[dict],
    snapshot_text: str,
) -> str:
    """
    「今日のポイント」3〜5行。失敗時は空文字（配信は止めない）。
    出力は呼び出し側で grounding する。
    """
    if not stories and not (snapshot_text or "").strip():
        return ""

    story_lines = []
    for i, s in enumerate(stories, 1):
        title = (s.get("title") or "").strip()
        summary = re.sub(
            r"<[^>]+>",
            "",
            (s.get("companion_summary") or s.get("summary") or ""),
        ).strip()[:400]
        story_lines.append(f"{i}. {title}\n要旨: {summary}")

    user_blob = (
        "【ヘッドライン】\n"
        + ("\n\n".join(story_lines) if story_lines else "（なし）")
        + "\n\n【数値スナップショット】\n"
        + ((snapshot_text or "").strip() or "（なし）")
        + "\n\n上記のみを根拠に今日のポイントを書いてください。"
    )

    try:
        from app.core.llm_client import call_model
        from app.routers.settings import app_settings

        settings = app_settings.get()
        provider = settings.get("planner_provider", "deepseek")
        model_name = settings.get("planner_model", "deepseek-v4-flash")

        raw = await call_model(
            system_instruction=_COMMENTARY_SYSTEM,
            messages=[{"role": "user", "content": user_blob}],
            model_name=model_name,
            provider=provider,
            max_tokens=800,
            temperature=0.2,
            enable_thinking=False,
        )
        text = (raw or "").strip()
        if not text:
            return ""
        # 余計な見出しを落とす
        text = re.sub(r"^#+\s*.*$", "", text, flags=re.MULTILINE).strip()
        return text
    except Exception as e:
        logger.warning(f"briefing commentary LLM failed: {e}")
        return ""


def render_briefing_markdown(
    kind: BriefKind,
    stories: list[dict],
    *,
    calendar_text: str = "",
    include_jp_snapshot: bool = False,
    include_us_quotes: bool = False,
    commentary: str = "",
    us_quotes_section: str = "",
    jp_snapshot_section: str = "",
    generated_at: Optional[datetime] = None,
) -> str:
    now = generated_at or _now_jst()
    label = "寄り前ブリーフ" if kind == "preopen" else "大引け後ブリーフ"
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M JST")

    parts = [
        f"# Kairi {label} — {date_str}",
        f"生成時刻: {time_str}",
        "",
        "> 下書き。配信前に目視確認すること。投資助言ではありません。数値・日付は出典と照合済みの範囲のみ記載。",
        "",
    ]

    if calendar_text:
        parts.append("## 市場カレンダー")
        parts.append("")
        parts.append(calendar_text.strip())
        parts.append("")

    if include_us_quotes:
        section = us_quotes_section or _us_settled_quotes_section()
        parts.append(section.strip())
        parts.append("")

    if include_jp_snapshot:
        section = jp_snapshot_section or _jp_snapshot_section()
        parts.append(section.strip())
        parts.append("")

    if commentary and commentary.strip():
        parts.append("## 今日のポイント")
        parts.append("")
        parts.append(commentary.strip())
        parts.append("")

    parts.append("## 注目ヘッドライン")
    parts.append("")
    if not stories:
        parts.append("（該当時間のプールに注目記事がありませんでした）")
    else:
        for i, s in enumerate(stories, 1):
            parts.append(_format_story(s, i))
            parts.append("")

    parts.append("---")
    parts.append(
        "免責: 本ブリーフは公開情報の要約であり投資助言ではありません。"
        "ペイウォール記事は無料ソースで裏取りした範囲のみ事実として扱います。"
    )
    return "\n".join(parts).strip() + "\n"


async def generate_briefing(
    kind: BriefKind,
    *,
    dry_run: bool = False,
    hours: Optional[float] = None,
) -> dict[str, Any]:
    """
    プールから記事を取り、スコアリング・ペイウォール差し替え・フィルタ後に保存。
    """
    from app.core.news.database import get_pool_news, init_db as init_news_db
    from app.core.news.paywall import attach_companions
    from app.core.market_calendar import format_market_status
    from app.core.fact_filters.pipeline import apply_grounding_pipeline

    await init_news_db()

    if hours is None:
        hours = 18.0 if kind == "preopen" else 10.0

    pool = await get_pool_news(hours=hours, limit=250)
    logger.info(f"📝 briefing[{kind}] pool={len(pool)} hours={hours}")

    stories = await _score_and_rank(pool, 5, kind=kind)
    stories = await attach_companions(stories, max_lookups=5)

    calendar_text = format_market_status()
    include_us = kind == "preopen"
    include_snap = kind == "postclose"

    us_section = _us_settled_quotes_section() if include_us else ""
    jp_section = _jp_snapshot_section() if include_snap else ""
    snapshot_for_llm = us_section if include_us else jp_section

    commentary_raw = await _generate_commentary(stories, snapshot_for_llm)
    source_blob = _stories_source_blob(stories) + "\n" + snapshot_for_llm
    commentary = ""
    if commentary_raw:
        commentary = apply_grounding_pipeline(
            commentary_raw,
            source_blob,
            user_input="市場ブリーフィング解説",
        ).strip()

    raw_md = render_briefing_markdown(
        kind,
        stories,
        calendar_text=calendar_text,
        include_jp_snapshot=include_snap,
        include_us_quotes=include_us,
        commentary=commentary,
        us_quotes_section=us_section,
        jp_snapshot_section=jp_section,
    )

    filtered_md = apply_grounding_pipeline(raw_md, source_blob, user_input="市場ブリーフィング")

    now = _now_jst()
    filename = f"{now.strftime('%Y-%m-%d')}_{kind}.md"
    out_path = BRIEFING_DIR / filename
    if not dry_run:
        BRIEFING_DIR.mkdir(parents=True, exist_ok=True)
        out_path.write_text(filtered_md, encoding="utf-8")
        logger.info(f"📝 briefing saved: {out_path}")

        try:
            await _maybe_notify_discord(kind, filtered_md)
        except Exception as e:
            logger.warning(f"briefing discord notify failed: {e}")

    return {
        "kind": kind,
        "path": str(out_path),
        "story_count": len(stories),
        "pool_count": len(pool),
        "markdown": filtered_md,
        "dry_run": dry_run,
        "has_commentary": bool(commentary),
    }


async def _maybe_notify_discord(kind: BriefKind, markdown: str) -> None:
    """全文を Discord に分割送信。Webhook 未設定ならログのみ。"""
    from app.core.notify.discord import send_discord_text

    label = "寄り前" if kind == "preopen" else "大引け後"
    header = f"**Kairi {label}ブリーフ**\n"
    await send_discord_text(header + markdown, dry_run=False)


def list_briefing_files() -> list[dict[str, Any]]:
    """保存済みブリーフ一覧（新しい順）。"""
    if not BRIEFING_DIR.exists():
        return []
    files = sorted(BRIEFING_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    out = []
    for p in files:
        st = p.stat()
        out.append(
            {
                "filename": p.name,
                "size": st.st_size,
                "mtime": datetime.fromtimestamp(st.st_mtime, tz=JST).isoformat(),
            }
        )
    return out


_SAFE_BRIEFING_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}_(preopen|postclose)\.md$")


def read_briefing_file(filename: str) -> str:
    """パストラバーサル対策付きで本文を読む。不正名は ValueError。"""
    name = Path(filename).name
    if name != filename or not _SAFE_BRIEFING_NAME.match(name):
        raise ValueError("invalid briefing filename")
    path = BRIEFING_DIR / name
    if not path.is_file():
        raise FileNotFoundError(name)
    return path.read_text(encoding="utf-8")
