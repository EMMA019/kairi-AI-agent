"""
チャット検索: carryover / clip / 実行 / 関連度不足時の拒否。
"""
from __future__ import annotations

import asyncio
import re
from datetime import date, datetime, timezone, timedelta
from typing import AsyncGenerator, Literal, Optional
from zoneinfo import ZoneInfo

from app.core.search import web_search
from app.core.search_relevance import (
    is_search_effectively_empty,
    SEARCH_UNSUPPORTED_PLACEHOLDER,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

_MAX_SEARCH_CARRY_SESSIONS = 200
_last_search_by_session: dict[str, dict] = {}
JST = timezone(timedelta(hours=9))
ET = ZoneInfo("America/New_York")

_TODAYISH_KW = (
    "今日",
    "本日",
    "大引け",
    "終値",
    "today",
    "どうだった",
    "どう動",
    "前場",
    "後場",
    "寄り",
    "昼休み",
    "どんな感じ",
)


def parse_explicit_calendar_date(
    text: str,
    *,
    default_year: int | None = None,
) -> date | None:
    """文中の 7/29・7月29日・2026-07-29 を抽出。なければ None。"""
    if not text:
        return None
    now = datetime.now(JST)
    year_default = default_year if default_year is not None else now.year
    m = re.search(r"(?:(\d{4})[年/\-])?(\d{1,2})[月/\-](\d{1,2})日?", text)
    if not m:
        return None
    year = int(m.group(1)) if m.group(1) else year_default
    try:
        return date(year, int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _previous_weekday(d: date) -> date:
    d = d - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def last_us_equity_session_date(now_jst: datetime | None = None) -> date:
    """
    直近の米国株レギュラーセッション確定日（settled / 引け済み）。
    平日 16:00 ET 未満 → 前営業日、以降 → 当日（土日は金曜へ）。
    場中の「今日の市況」には使わず current_us_trading_date を使うこと。
    """
    now = now_jst or datetime.now(JST)
    et = now.astimezone(ET)
    d = et.date()
    if d.weekday() >= 5:
        return _previous_weekday(d)
    if et.hour < 16:
        return _previous_weekday(d)
    return d


def settled_us_session_date(now_jst: datetime | None = None) -> date:
    """last_us_equity_session_date の別名（意図を明示）。"""
    return last_us_equity_session_date(now_jst)


def current_us_trading_date(now_jst: datetime | None = None) -> date:
    """
    進行中（または当日）の米国株取引カレンダー日（ET）。
    週末・祝日は直近の前営業日へ。
    """
    now = now_jst or datetime.now(JST)
    et = now.astimezone(ET)
    d = et.date()
    if d.weekday() >= 5:
        return _previous_weekday(d)
    try:
        from app.core.market_calendar import get_us_holidays

        holidays = {h["date"] for h in get_us_holidays(d.year)}
        while d.weekday() >= 5 or d in holidays:
            d = _previous_weekday(d)
            # 年またぎ祝日セットを更新
            holidays |= {h["date"] for h in get_us_holidays(d.year)}
    except Exception:
        pass
    return d


def resolve_market_anchor_date(
    user_input: str,
    *,
    market: Literal["jp", "us"] = "jp",
    now_jst: datetime | None = None,
    purpose: Literal["auto", "settled", "live"] = "auto",
) -> date:
    """
    市況クエリの日付アンカー。
    明示日付があればそれを優先。
    米国:
      - purpose=settled → 直近確定終値日
      - purpose=live → 当日取引日（場中向け）
      - purpose=auto → プレ/ザラ場中は live、それ以外は settled
    """
    now = now_jst or datetime.now(JST)
    explicit = parse_explicit_calendar_date(user_input, default_year=now.year)
    if explicit:
        return explicit
    if market == "us":
        from app.core.market_session import us_session_is_live

        if purpose == "settled":
            return settled_us_session_date(now)
        if purpose == "live":
            return current_us_trading_date(now)
        # auto
        if us_session_is_live(now):
            return current_us_trading_date(now)
        return settled_us_session_date(now)
    return now.date()


# メガキャップ程度の社名→検索用ティッカー（検索クエリ保持用。網羅リストではない）
_US_COMPANY_ALIASES: list[tuple[tuple[str, ...], str, str]] = [
    (("google", "alphabet", "googl", "goog", "グーグル", "アルファベット"), "GOOGL", "Alphabet OR GOOGL"),
    (("amazon", "amzn", "アマゾン"), "AMZN", "Amazon OR AMZN"),
    (("microsoft", "msft", "マイクロソフト"), "MSFT", "Microsoft OR MSFT"),
    (("apple", "aapl", "アップル"), "AAPL", "Apple OR AAPL"),
    (("nvidia", "nvda", "エヌビディア"), "NVDA", "Nvidia OR NVDA"),
    (("meta", "facebook", "メタ"), "META", "Meta OR META"),
    (("broadcom", "avgo", "ブロードコム"), "AVGO", "Broadcom OR AVGO"),
    (("tesla", "tsla", "テスラ"), "TSLA", "Tesla OR TSLA"),
]


# 検査・医療略語（裸ティッカー誤認防止）
_LAB_TICKER_DENY: frozenset[str] = frozenset({
    "ALT", "AST", "GPT", "GTP", "RBC", "WBC", "PLT", "HDL", "LDL", "BUN", "CRP",
    "CHOL", "ALB", "MCV", "MCH", "MCHC", "GA", "TP", "HB", "HBA", "HGB", "HT",
    "INR", "PT", "APTT", "BNP", "TSH", "PSA", "CEA", "AFP", "IgE", "IgG", "IgA",
    "IgM", "Na", "NA", "K", "CL", "CA", "FE", "UA", "UN", "CRE", "eGFR", "EGFR",
})

_MEDICAL_LAB_KW = (
    "献血", "採血", "採決", "血圧", "脈拍", "検査", "生化学", "血球",
    "ヘモグロビン", "ヘマトクリット", "血小板", "白血球", "赤血球",
    "γ-GTP", "グリコアルブミン", "基準値", "GPT)", "（GPT", "(GPT",
    "アルブミン対", "総蛋白", "コレステロール　", "グリコアルブミン",
)

_FINANCE_TICKER_CUES = (
    "株", "銘柄", "ティッカー", "ticker", "stock", "$", "米国株",
    "NASDAQ", "Nasdaq", "NYSE", "nyse",
    "米国市場", "アメリカ市場", "Wall Street", "ダウ", "Dow", "ナスダック", "S&P",
)


def is_medical_lab_context(text: str) -> bool:
    """献血・採血結果・検査表など、株シード抽出を無効化すべき文脈。"""
    t = text or ""
    return any(k in t for k in _MEDICAL_LAB_KW)


def _has_finance_ticker_cues(text: str) -> bool:
    t = text or ""
    if any(k in t for k in _FINANCE_TICKER_CUES):
        return True
    if re.search(r"\$[A-Z]{1,5}\b", t):
        return True
    return False


def _company_alias_hit(alias: str, text: str, text_l: str) -> bool:
    if not alias.isascii():
        # メタ ⊆ メタボ を拒否: 前後が仮名/漢字なら不一致
        for m in re.finditer(re.escape(alias), text):
            start, end = m.start(), m.end()
            before = text[start - 1] if start > 0 else ""
            after = text[end] if end < len(text) else ""
            if before and re.match(r"[ぁ-んァ-ヶー一-龥]", before):
                continue
            if after and re.match(r"[ぁ-んァ-ヶー一-龥]", after):
                continue
            return True
        return False
    # 短ASCIIは単語境界（googl ⊆ google 誤爆防止）
    if len(alias) <= 5 and alias.isalpha():
        return (
            re.search(rf"(?<![A-Za-z0-9]){re.escape(alias)}(?![A-Za-z0-9])", text_l)
            is not None
        )
    return alias in text_l


def extract_us_company_search_seeds(user_input: str) -> list[dict[str, str]]:
    """発話から米国個別銘柄の検索シードを抽出。"""
    text = user_input or ""
    if is_medical_lab_context(text):
        return []
    text_l = text.lower()
    seeds: list[dict[str, str]] = []
    seen: set[str] = set()

    for aliases, ticker, query_name in _US_COMPANY_ALIASES:
        if any(_company_alias_hit(a, text, text_l) for a in aliases):
            if ticker not in seen:
                seeds.append({"ticker": ticker, "query_name": query_name})
                seen.add(ticker)

    # 裸ティッカーは金融手がかりがあるときだけ（検査表 ALT/RBC 誤認防止）
    # 境界は ASCII 英数のみ（IBM株 のように直後が日本語でも拾う）
    if _has_finance_ticker_cues(text):
        for m in re.finditer(r"(?<![A-Za-z0-9])([A-Z]{2,5})(?![A-Za-z0-9])", text):
            t = m.group(1)
            if t in seen or t in {"US", "ETF", "CEO", "AI", "IPO", "NY", "OR"}:
                continue
            if t in _LAB_TICKER_DENY:
                continue
            seeds.append({"ticker": t, "query_name": t})
            seen.add(t)
    return seeds


_US_MOVE_KW = (
    "上がっ", "上げ", "下げ", "下がっ", "急騰", "急落", "反発", "暴落", "高騰",
    "surge", "rally", "plunge", "soar", "sink",
)
_US_NEWS_ASK_KW = (
    "ニュース", "決算", "なにかあった", "何かあった", "何があった", "なにがあった",
    "どうして", "なんで", "材料", "理由", "catalyst", "いいニュース", "悪いニュース",
)
_US_MARKET_CARRY_MARKERS = (
    "米国市場", "アメリカ市場", "wall street", "dow", "nasdaq", "s&p", "us stock",
    "米国株", "nyse", "ダウ", "ナスダック",
)


def user_asserts_us_price_move(user_input: str) -> bool:
    text = user_input or ""
    text_l = text.lower()
    return any(k in text for k in _US_MOVE_KW) or any(k in text_l for k in ("surge", "rally", "plunge", "soar"))


def user_asks_company_news(user_input: str) -> bool:
    text = user_input or ""
    return any(k in text for k in _US_NEWS_ASK_KW)


def prior_turn_was_us_market(session_id: str | None) -> bool:
    """直前検索キャリーが米国市況系なら True（市況→個別フォロー用）。"""
    if not session_id:
        return False
    prev = _last_search_by_session.get(session_id)
    if not prev:
        return False
    blob = " ".join(
        [str(prev.get("user_input") or "")]
        + [str(q) for q in (prev.get("queries") or [])]
    ).lower()
    return any(m in blob for m in _US_MARKET_CARRY_MARKERS)


def is_soft_us_single_stock_query(
    user_input: str,
    *,
    session_id: str | None = None,
) -> bool:
    """
    「米国市場」無しでも個別株＋今日/騰落/材料聞き、または市況フォローなら soft-US。
    表内の過去日付だけでは立てない（検査結果の誤発火防止）。
    """
    text = user_input or ""
    if is_medical_lab_context(text):
        return False
    if any(k in text for k in ("日本市場", "日経", "東証", "TOPIX", "東京株式", "日本株", "国内市場")):
        return False
    seeds = extract_us_company_search_seeds(text)
    if not seeds:
        return False
    # 今日系キーワードのみ（明示カレンダー日付だけでは不可）
    if any(k in text for k in _TODAYISH_KW):
        return True
    if user_asserts_us_price_move(text) or user_asks_company_news(text):
        return True
    if prior_turn_was_us_market(session_id):
        return True
    return False


def wants_company_why_up(user_input: str) -> bool:
    """騰落主張・材料聞きなら why-up クエリを優先（場中/引け後問わず）。"""
    return user_asserts_us_price_move(user_input) or user_asks_company_news(user_input)


def build_us_market_search_queries(
    user_input: str,
    *,
    now_jst: datetime | None = None,
    company_focus: bool = False,
) -> list[str]:
    """米国今日系の検索クエリ（場中=live、引け後=closes）。企業言及を消さない。"""
    from app.core.market_session import us_session_is_live

    now = now_jst or datetime.now(JST)
    explicit = parse_explicit_calendar_date(user_input)
    live = us_session_is_live(now) and explicit is None
    purpose: Literal["auto", "settled", "live"] = "live" if live else "settled"
    # 明示過去日は settled 記事
    if explicit is not None:
        purpose = "settled"
        live = False

    us_d = resolve_market_anchor_date(
        user_input, market="us", now_jst=now, purpose=purpose
    )
    d = us_d.isoformat()
    d_en = format_anchor_date_en(us_d)
    company_seeds = extract_us_company_search_seeds(user_input)
    why_up = wants_company_why_up(user_input) or company_focus

    if live:
        index_qs = [
            f"US stocks today {d_en}",
            f"Dow S&P Nasdaq live OR trading {d}",
            f"stock market movers earnings {d_en}",
        ]
    else:
        index_qs = [
            f"Wall Street closes {d_en}",
            f"Dow S&P Nasdaq close {d}",
            f"stocks end higher OR lower {d_en}",
        ]

    if not company_seeds:
        return index_qs[:3]

    company_qs = []
    for seed in company_seeds[:2]:
        name = seed["query_name"]
        ticker = seed["ticker"]
        if live or why_up:
            company_qs.append(f"{name} stock news why up OR surge {d_en}")
            company_qs.append(f"{ticker} stock {d} rally OR jump OR catalyst")
        else:
            company_qs.append(f"{name} stock news {d_en}")
            company_qs.append(f"{ticker} earnings OR close {d}")
    # 企業優先。soft-US/個別フォーカスは指数を最大1本
    index_n = 1 if company_focus else 2
    merged = company_qs[:2] + index_qs[:index_n]
    return merged[:4]


def format_anchor_date_en(d: date) -> str:
    """July 29, 2026 形式。"""
    return d.strftime("%B %d, %Y").replace(" 0", " ")


def store_search_carryover(
    session_id: str,
    search_results_text: str | None,
    search_queries: list,
    user_input: str,
):
    """検索成功時にセッションへ結果を保存する。"""
    if not search_results_text or not search_results_text.strip():
        return
    if len(_last_search_by_session) >= _MAX_SEARCH_CARRY_SESSIONS and session_id not in _last_search_by_session:
        oldest_key = next(iter(_last_search_by_session))
        del _last_search_by_session[oldest_key]
    _last_search_by_session[session_id] = {
        "text": search_results_text,
        "queries": list(search_queries or []),
        "user_input": user_input,
    }


def clear_search_carryover(session_id: str) -> None:
    """セッション削除時に検索キャリーを捨てる。"""
    _last_search_by_session.pop(session_id, None)


def maybe_carry_search_results(
    session_id: str,
    user_input: str,
    history_messages: list,
    search_needed: bool,
    search_results_text: str | None,
) -> str | None:
    """今ターン検索なしでも、直前ターンが検索済みかつ同一トピックなら結果を再注入する。

    overlap は **現在の user_input のみ** で判定（history 内の旧トピック語で誤発火しない）。
    閾値は 2 語以上。新トピック語（介入・円安等）だけの発話はキャリーしない。
    """
    if search_needed or search_results_text:
        return search_results_text
    prev = _last_search_by_session.get(session_id)
    if not prev or not prev.get("text"):
        return search_results_text

    # 明示の新トピック（前ターン銘柄に引きずられない）
    _TOPIC_RESET_KW = ("介入", "円安", "円高", "利上げ", "利下げ")
    current = user_input or ""
    if any(kw in current for kw in _TOPIC_RESET_KW):
        return search_results_text

    stop = {
        "それ", "これ", "あれ", "どう", "そう", "けど", "だけど", "って", "感じ",
        "思う", "教えて", "ください", "です", "ます", "した", "いる", "ある",
        "だった", "よね", "なに", "何が", "the", "and", "was", "for", "about",
        "かな", "する", "して", "ってか",
    }

    def _tokens(text: str) -> set[str]:
        found = set(re.findall(r"[一-龥ァ-ヶー]{2,}|[A-Za-z][A-Za-z0-9_\-]{2,}", text or ""))
        return {t for t in found if t.lower() not in stop and t not in stop}

    topic_tokens = _tokens(prev.get("user_input", ""))
    for q in prev.get("queries") or []:
        topic_tokens |= _tokens(str(q))
    if not topic_tokens:
        return search_results_text

    # history は使わない（旧トピック語の自己一致で誤キャリーするため）
    overlap = [t for t in topic_tokens if t in current]
    if len(overlap) >= 2:
        logger.info(f"🔁 フォローアップへ前ターン検索結果を再注入 (overlap={overlap[:5]})")
        return prev["text"]
    return search_results_text


def clip_search_results(text: str, max_bytes: int = 100_000) -> str:
    if not text or len(text) <= max_bytes:
        return text
    logger.warning(f"⚠️ 検索結果が大きすぎます ({len(text):,} bytes) → {max_bytes:,} bytesにクリップ")
    half = max_bytes // 2
    return (
        text[:half]
        + f"\n\n[...検索結果が長すぎるため途中でカット ({len(text) - max_bytes} bytes削減)...]\n\n"
        + text[-half:]
    )


def extract_smart_snippet(text: str, max_chars: int = 15000) -> str:
    if not text or len(text) <= max_chars:
        return text
    head = max_chars * 2 // 5
    tail = max_chars * 3 // 5
    return text[:head] + "\n\n[...中間セクション省略（トークン節約）...]\n\n" + text[-tail:]


def sanitize_conversational_query(q_text: str) -> str:
    if not q_text or len(q_text) <= 20:
        return q_text
    if any(k in q_text for k in ["半導体", "SOX", "200A", "2243", "AVGO"]) and any(
        k in q_text for k in ["銘柄", "組み込", "リバランス", "思惑", "狙い"]
    ):
        return "半導体株 ETF 注目銘柄 リバウンド 見通し 2026"
    if any(k in q_text for k in ["ポートフォリオ", "比率", "リバランス"]) and any(
        k in q_text for k in ["銘柄", "組み込", "おすすめ", "何がいい", "かな"]
    ):
        return "米国株 日本株 分散 高配当 ETF おすすめ 銘柄 2026"
    cleaned = re.sub(r"[ｗw！!？?。、,（）()]", " ", q_text)
    cleaned = re.sub(
        r"(?:だったんだ|なんだけど|だけど|思惑外れてる|外れてる|見ての通り|なので|から|ってこと|って|どう思う|いいと思う|いいかな|教えて|したい|しようと思ってます|思いますか|なんだよね|よね|だよね)",
        " ",
        cleaned,
    )
    tokens = [t for t in re.split(r"\s+", cleaned) if len(t) >= 2 and t not in ["今は", "けど", "なら", "なので"]]
    return " ".join(tokens[:5]) if tokens else q_text[:30]


def _is_todayish_market_query(user_input: str, *, now_jst: datetime | None = None) -> bool:
    """今日系キーワード、または明示日付付き市況質問を日付正規化対象にする。"""
    text = user_input or ""
    if any(k in text for k in _TODAYISH_KW):
        return True
    return parse_explicit_calendar_date(text) is not None


def balance_search_queries(
    user_input: str,
    search_needed: bool,
    search_queries: list,
    *,
    session_id: str | None = None,
) -> tuple[bool, list]:
    """市場・ネガティブ問いに対するクエリバランス補完（地域スコープ付き）。"""
    now_jst = datetime.now(JST)
    jp_anchor = resolve_market_anchor_date(user_input, market="jp", now_jst=now_jst)
    us_anchor = resolve_market_anchor_date(user_input, market="us", now_jst=now_jst)
    today_jp = jp_anchor.isoformat()
    today_us = us_anchor.isoformat()
    today_us_en = format_anchor_date_en(us_anchor)

    market_keywords = [
        "暴落", "下落", "懸念", "株", "相場", "市場", "半導体", "インテル", "AVGO", "ブロードコム",
        "急落", "調整", "バブル", "SOX", "組み込", "リバランス", "銘柄", "ポートフォリオ", "ETF",
        "日経", "ダウ", "ナスダック", "TOPIX", "金融", "セクター", "業種",
        "前場", "後場",
    ]
    negative_keywords = ["失敗", "問題", "危険", "批判", "欠点", "リスク", "悪化", "衰退", "デメリット", "バグ", "被害"]

    jp_scope = any(
        k in user_input
        for k in ("日本市場", "日経", "東証", "TOPIX", "東京株式", "日本株", "国内市場")
    )
    us_scope = any(
        k in user_input
        for k in ("米国市場", "アメリカ市場", "NY", "ナスダック", "Nasdaq", "S&P", "ダウ", "Dow", "Wall Street", "米国株")
    )
    soft_us = is_soft_us_single_stock_query(user_input, session_id=session_id)
    todayish = _is_todayish_market_query(user_input, now_jst=now_jst)
    # planner と同じ: 「今日の市場」単独は日本寄り（soft-US 個別株があるときは日本既定にしない）
    if todayish and not jp_scope and not us_scope and not soft_us and any(
        k in user_input for k in ("市場", "相場", "market", "Market")
    ):
        jp_scope = True
    sector_finance = any(k in user_input for k in ("金融", "銀行", "保険", "証券"))
    sector_semi = any(k in user_input for k in ("半導体", "SOX", "電機"))
    wants_topix = "TOPIX" in user_input or "トピックス" in user_input
    wants_sector = any(k in user_input for k in ("セクター", "業種", "ローテーション")) or sector_finance or sector_semi

    # soft-US: 「米国市場」無しの個別株＋今日/騰落/材料聞き/市況フォロー
    if soft_us and not jp_scope:
        search_needed = True
        search_queries = build_us_market_search_queries(
            user_input, now_jst=now_jst, company_focus=True
        )
        logger.info(f"🇺🇸 soft-US 個別株クエリに正規化: {search_queries}")
        return search_needed, search_queries[:4]

    if any(kw in user_input for kw in market_keywords) or jp_scope or us_scope:
        search_needed = True

        # 今日系の日本/米国は地域特化クエリに正規化（最大4本）
        # 明示日付（例: 7/29）があればその日を使い、JST今日で上書きしない
        if todayish and jp_scope and not us_scope:
            from app.core.market_session import get_jp_session_bucket, jp_cash_price_query_word

            price_word = jp_cash_price_query_word(now_jst)
            # 過去日の明示質問は終値記事が正しい
            explicit = parse_explicit_calendar_date(user_input)
            if explicit is not None and jp_anchor < now_jst.date():
                price_word = "終値"
            search_queries = [
                f"日経平均 {price_word} {today_jp}",
                f"東京株式市場 市況 {today_jp}",
                f"TOPIX {price_word} {today_jp}",
                f"業種別騰落率 東証 {today_jp}",
            ]
            if get_jp_session_bucket(now_jst) == "closed" and now_jst.hour >= 16:
                search_queries[3] = f"日経225先物 夜間取引 {today_jp}"
            logger.info(f"🇯🇵 日本市場今日系クエリに正規化: {search_queries}")
            return search_needed, search_queries[:4]

        if todayish and us_scope and not jp_scope:
            search_queries = build_us_market_search_queries(user_input, now_jst=now_jst)
            logger.info(f"🇺🇸 米国市場今日系クエリに正規化: {search_queries}")
            return search_needed, search_queries[:4]

        # 日本市場フォロー（金融/TOPIX/セクター）— 今日でなくても補強
        soft_jp = jp_scope or (sector_finance and not us_scope) or (wants_sector and not us_scope and "ローテーション" in user_input)
        if soft_jp and not us_scope and (wants_topix or wants_sector or sector_finance):
            extras = []
            if wants_topix or wants_sector:
                extras.append(f"TOPIX 終値 騰落 {today_jp}")
            if sector_finance or wants_sector:
                extras.append(f"東証 業種別騰落 銀行 保険 {today_jp}")
            if sector_semi:
                extras.append(f"半導体 関連株 騰落 東京市場 {today_jp}")
            merged = list(search_queries or [])
            for e in extras:
                if e not in merged:
                    merged.append(e)
            search_queries = merged[:4]
            logger.info(f"🇯🇵 日本市場フォロークエリ補強: {search_queries}")
            return search_needed, search_queries

        if len(search_queries) == 1 and (
            len(search_queries[0]) > 30 or any(p in search_queries[0] for p in ["思惑", "短期", "見ての通り", "比率"])
        ):
            if any(k in user_input for k in ["半導体", "SOX", "SOXX", "インテル", "AVGO", "200A", "2243"]):
                search_queries[0] = "半導体株 ETF 見通し 動向 注目銘柄 2026"
            elif any(k in user_input for k in ["リバランス", "組み込", "ポートフォリオ", "高配当"]):
                if jp_scope and not us_scope:
                    search_queries[0] = "日本株 高配当 ETF おすすめ 注目銘柄 2026"
                elif us_scope and not jp_scope:
                    search_queries[0] = "US dividend ETF stock picks outlook 2026"
                else:
                    search_queries[0] = "米国株 日本株 高配当 ETF おすすめ 注目銘柄 2026"

        has_rebound_query = any(
            w in q.lower()
            for q in search_queries
            for w in ["rebound", "recovery", "high", "反発", "回復", "見通し", "outlook", "終値", "close", "TOPIX", "業種"]
        )
        if not has_rebound_query and len(search_queries) < 2:
            if any(k in user_input for k in ["半導体", "SOX", "SOXX", "インテル", "AVGO", "200A", "2243"]):
                search_queries.append("semiconductor ETF stock market outlook 2026")
            elif jp_scope and not us_scope:
                search_queries.append(f"日経平均 市況 見通し {today_jp}")
            elif us_scope and not jp_scope:
                search_queries.append(f"US stock market outlook {today_us}")
            else:
                search_queries.append("US Japan stock dividend ETF market outlook 2026")
            logger.info(f"📈 市場調査クエリに補完クエリを追加: {search_queries[-1]}")
    elif search_needed and any(kw in user_input for kw in negative_keywords) and len(search_queries) < 2:
        search_queries.append(f"{search_queries[0]} solutions improvements latest update 2026")
        logger.info(f"⚖️ リサーチクエリに多角的バランス補完クエリを追加しました: {search_queries[-1]}")

    return search_needed, search_queries


def should_skip_deep_fetch(user_input: str) -> bool:
    """終値・大引け・今日の市況はスニペットで足りるのでディープフェッチ省略。
    ただし明示日付（8/6 等）を含む市況クエリはスニペットが薄いリスクがあるため skip しない。"""
    text = user_input or ""
    # 明示日付つき市況クエリ → 終値確定値を得るため deep fetch を許可
    if parse_explicit_calendar_date(text) and any(
        k in text for k in ("市場", "市況", "前場", "後場", "終値", "どうだった", "どんな感じ")
    ):
        return False
    return any(
        k in text
        for k in (
            "終値",
            "大引け",
            "今日の日本市場",
            "今日の米国市場",
            "本日の市場",
            "市況",
            "前場",
            "後場",
        )
    )


def _format_us_market_snapshot_for_prompt(user_input: str = "") -> str:
    """
    米国主要指数ETFスナップショット。
    場中・プレ → 直近値（取引中）。引け後 → セッション終値（朝ラップ混同防止）。
    """
    from app.core.market_session import us_session_is_live
    from app.core.tools.market_data import fetch_us_etf_session_closes, _quote_dict_yf

    tickers = [
        ("DIA", "ダウ (DIA)"),
        ("SPY", "S&P500 (SPY)"),
        ("QQQ", "ナスダック100 (QQQ)"),
        ("SOXX", "半導体 SOXX"),
    ]
    now = datetime.now(JST)
    explicit = parse_explicit_calendar_date(user_input)
    live = us_session_is_live(now) and explicit is None
    purpose: Literal["auto", "settled", "live"] = "live" if live else "settled"
    if explicit is not None:
        purpose = "settled"
        live = False

    anchor = resolve_market_anchor_date(
        user_input, market="us", now_jst=now, purpose=purpose
    )

    if live:
        lines = [
            f"【米国市場スナップショット session_date={anchor.isoformat()} status=取引中（推測禁止・指数はここを優先）】",
            "※【P0】現在はレギュラー/プレマーケット取引中。下記は直近値であり終値ではない。",
            "  『終値』『大引け』と呼ぶこと、前日確定終値を本日の市況として語ることを禁止。",
            "※ 指数レベルは ETF 近似。記事の物語と数値は日付・時刻で照合すること。",
            "※ 表は DIA / SPY / QQQ / SOXX を欠落させず、未取得は『直近値未取得』と明示すること。",
        ]
        for ticker, label in tickers:
            try:
                q = _quote_dict_yf(ticker, enrich_vol_atr=False) or {}
            except Exception:
                q = {}
            price = q.get("current_price")
            if price is None:
                lines.append(f"- {label}: 直近値未取得")
                continue
            prev = q.get("previous_close")
            chg = q.get("change")
            pct = q.get("change_pct")
            parts = [f"{float(price):,.2f}"]
            if chg is not None and pct is not None:
                sign = "+" if chg >= 0 else ""
                parts.append(f"{sign}{float(chg):,.2f}（{sign}{float(pct):.2f}%）")
            prev_s = f"{float(prev):,.2f}" if prev is not None else "未確認"
            lines.append(
                f"- {label} 直近値（取引中） as_of={anchor.isoformat()}: "
                f"{' '.join(parts)} | 前日終値: {prev_s}"
            )
        return "\n".join(lines)

    batch = fetch_us_etf_session_closes(anchor, [t for t, _ in tickers])
    quotes = (batch or {}).get("quotes") or {}
    src = (batch or {}).get("source") or "yfinance"
    lines = [
        f"【米国市場スナップショット session_date={anchor.isoformat()} source={src}（推測禁止・指数はここを優先）】",
        "※【P0】朝刊ラップ（News-for-DATE / Premarket / Before-the-Open）は前日終値＋当日見通しのことが多い。",
        "  それを DATE の確定終値として書いてはならない。引け後記事（Wall Street ends / stocks close）と下記 as_of を優先。",
        "※ 指数レベルは ETF 日足の近似。記事の物語と数値は as_of 日付で照合すること。",
        "※ 表は DIA / SPY / QQQ / SOXX を欠落させず、未取得は『当該日終値バー未取得』と明示すること。",
    ]
    unmatched_count = 0
    for ticker, label in tickers:
        q = quotes.get(ticker) or {}
        if not q.get("ok") or q.get("close") is None:
            lines.append(f"- {label}: 当該日終値バー未取得")
            unmatched_count += 1
            continue
        close = float(q["close"])
        as_of = q.get("as_of") or "?"
        prev = q.get("previous_close")
        chg = q.get("change")
        pct = q.get("change_pct")
        matched = bool(q.get("matched_session"))
        parts = [f"{close:,.2f}"]
        if chg is not None and pct is not None:
            sign = "+" if chg >= 0 else ""
            parts.append(f"{sign}{chg:,.2f}（{sign}{pct:.2f}%）")
        prev_s = f"{float(prev):,.2f}" if prev is not None else "未確認"
        if matched:
            lines.append(
                f"- {label} 終値 as_of={as_of}: {' '.join(parts)} | 前日終値: {prev_s}"
            )
        else:
            unmatched_count += 1
            lines.append(
                f"- {label}: session_date={anchor.isoformat()} のバー無し。"
                f"直近バー as_of={as_of} 終値 {' '.join(parts)} "
                f"（前日終値扱い・{anchor.isoformat()}終値として断定するな）| その前: {prev_s}"
            )
    if unmatched_count >= 2:
        lines.insert(1, f"🔴 警告: {unmatched_count}/{len(tickers)} ETFが指定日確定バー未取得。以下のETF数値は前営業日ベースの可能性が高く、当日終値と断定してはならない。可能なら検索結果の引け後記事を優先せよ。")
    return "\n".join(lines)


def _format_us_single_stock_quotes_for_prompt(user_input: str) -> str:
    """個別株シードのクォートをプロンプト先頭用に整形。失敗時は空文字。"""
    seeds = extract_us_company_search_seeds(user_input)
    if not seeds:
        return ""
    try:
        from app.core.tools.market_data import _quote_dict_yf
    except Exception:
        return ""

    from app.core.market_session import us_session_is_live

    now = datetime.now(JST)
    purpose: Literal["auto", "settled", "live"] = (
        "live" if us_session_is_live(now) else "settled"
    )
    as_of = resolve_market_anchor_date(
        user_input, market="us", now_jst=now, purpose=purpose
    ).isoformat()
    lines = [f"【個別株クォート as_of={as_of}】"]
    for seed in seeds[:2]:
        ticker = seed["ticker"]
        try:
            q = _quote_dict_yf(ticker, enrich_vol_atr=False)
        except Exception as e:
            logger.warning(f"single-stock quote failed for {ticker}: {e}")
            continue
        if not q or q.get("error"):
            continue
        price = q.get("current_price")
        prev = q.get("previous_close")
        chg = q.get("change")
        pct = q.get("change_pct")
        kind = q.get("price_kind") or "session_close_or_last"
        price_s = f"{price:.2f}" if isinstance(price, (int, float)) else str(price)
        prev_s = f"{prev:.2f}" if isinstance(prev, (int, float)) else str(prev)
        chg_s = f"{chg:+.2f}" if isinstance(chg, (int, float)) else str(chg)
        pct_s = f"{pct:+.2f}%" if isinstance(pct, (int, float)) else str(pct)
        label = "直近値（取引中）" if purpose == "live" else "終値/直近"
        lines.append(
            f"- {ticker}: {label} {price_s} | 前日終値 {prev_s} | "
            f"騰落 {chg_s} ({pct_s}) | price_kind={kind}"
        )
    if len(lines) <= 1:
        return ""
    lines.append(
        "※上記は確定クォート。騰落率・終値を断定するときはこのブロックを優先し、"
        "記事スニペットの途中経過レンジと混同しないこと。"
    )
    return "\n".join(lines)


async def run_web_search(
    *,
    user_input: str,
    search_queries: list,
    search_providers: list,
    session_id: str | None = None,
) -> AsyncGenerator[dict, None]:
    """
    検索を実行し、SSE用イベント dict を yield。
    最後に {"type": "_result", "text": ..., "sources": ...} を返す。
    """
    search_results_text = None
    search_sources: list = []
    tasks = []
    # 日本市況は TOPIX/業種クエリを含めて最大4本
    qblob = " ".join(search_queries or [])
    jp_market = any(
        k in (user_input or "")
        for k in ("日本市場", "日経", "東証", "TOPIX", "東京株式", "日本株", "国内市場")
    ) or any(k in qblob for k in ("日経", "TOPIX", "東証", "東京株式"))
    us_scope_explicit = any(
        k in (user_input or "")
        for k in ("米国市場", "アメリカ市場", "NY", "ナスダック", "Nasdaq", "S&P", "ダウ", "Dow", "Wall Street", "米国株")
    )
    us_market = us_scope_explicit or any(
        k in qblob.lower() for k in ("dow", "nasdaq", "s&p", "us stock", "wall street")
    )
    soft_us = is_soft_us_single_stock_query(user_input, session_id=session_id)
    company_seeds = extract_us_company_search_seeds(user_input)
    # 米国場中は企業+指数で最大4本。引け後の指数のみは2本のまま。soft-US/企業は最大4。
    from app.core.market_session import us_session_is_live

    us_live = us_market and us_session_is_live()
    max_queries = 4 if (jp_market or us_live or soft_us or company_seeds or (us_market and len(search_queries or []) > 2)) else 2
    if (us_market or soft_us) and not jp_market:
        max_queries = max(max_queries, min(4, len(search_queries or [])))
    from app.routers.settings import app_settings
    from app.core.ui_status import pipeline_detail

    _ui_locale = app_settings.get().get("locale", "en")
    for q in search_queries[:max_queries]:
        yield {"type": "status", "status": "searching", "query": q}
        yield {
            "type": "pipeline",
            "stage": "search",
            "detail": pipeline_detail("searching", _ui_locale, q=q),
        }
        tasks.append(web_search(q, providers=search_providers))
        logger.info(f"検索実行: '{q}' (Providers: {search_providers}) (Original: '{user_input}')")

    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_raw_sources = []
    direct_url_fallback_texts = []
    for i, res in enumerate(results):
        q = search_queries[i]
        if isinstance(res, Exception):
            logger.error(f"検索実行エラー '{q}': {res}")
        else:
            text, sources = res
            if "URL (" in text and "の内容:" in text:
                direct_url_fallback_texts.append(text)
            all_raw_sources.extend(sources)

    # 個別株クォート（soft-US / 企業シード）→ 明示 us_scope のときだけ指数スナップ
    snapshot_block = ""
    single_quote_block = ""
    if company_seeds and not jp_market:
        try:
            single_quote_block = _format_us_single_stock_quotes_for_prompt(user_input)
        except Exception as e:
            logger.warning(f"US single-stock quote prefetch failed: {e}")
    if jp_market:
        try:
            from app.core.tools.market_data import format_jp_market_snapshot_for_prompt
            snapshot_block = format_jp_market_snapshot_for_prompt(user_input)
        except Exception as e:
            logger.warning(f"JP market snapshot failed: {e}")
    elif us_scope_explicit:
        # 明示「米国市場」のみ指数スナップ（soft-US 単独は個別クォートのみ）
        try:
            snapshot_block = _format_us_market_snapshot_for_prompt(user_input)
        except Exception as e:
            logger.warning(f"US market snapshot failed: {e}")

    combined_texts = list(direct_url_fallback_texts)
    # 個別クォートを最優先（終値誤帰属防止）
    if single_quote_block:
        combined_texts.insert(0, single_quote_block)
    if snapshot_block:
        combined_texts.insert(0 if not single_quote_block else 1, snapshot_block)
    if all_raw_sources:
        from app.core.search.reranker import rerank
        from app.core.search.formatter import format_for_prompt
        from app.core.source_evaluator import evaluate_source_authority
        from app.core.search.router import fetch_url

        global_top_sources = rerank(user_input, all_raw_sources, top_k=20)

        deep_fetched_text = ""
        skip_deep = should_skip_deep_fetch(user_input)
        if skip_deep:
            logger.info("⏩ 市場終値/今日系のため Tier1 ディープフェッチをスキップ")
        for src in global_top_sources:
            if skip_deep:
                break
            url = src.get("url", "")
            title = src.get("title", "")
            source_label = src.get("source", "")
            eval_res = evaluate_source_authority(url, title, source_label)

            if eval_res["tier"] == 1 and url:
                logger.info(f"🚀 Tier 1 記事の本文取得(ディープフェッチ)実行: {url} (Title: {title})")
                yield {"type": "status", "status": "scraping_promotion", "url": url}
                try:
                    scraped_content = await fetch_url(url)
                    if scraped_content and not scraped_content.startswith("❌") and len(scraped_content.strip()) > 50:
                        content_snippet = extract_smart_snippet(scraped_content, 15000)
                        deep_fetched_text = f"【Tier 1記事 本文抽出: {title} ({url})】\n{content_snippet}\n\n"
                        break
                except Exception as e:
                    logger.warning(f"Tier 1記事の本文取得失敗 {url}: {e}")

        global_text = format_for_prompt(global_top_sources, user_input)
        combined_texts.append(f"【統合検索結果（関連度トップ20件）】\n{global_text}")
        if deep_fetched_text:
            combined_texts.append(deep_fetched_text)
        search_sources = global_top_sources

    if combined_texts:
        search_results_text = clip_search_results("\n\n".join(combined_texts))

    if search_sources:
        unique_sources = []
        seen_urls = set()
        for s in search_sources:
            if s["url"] not in seen_urls:
                seen_urls.add(s["url"])
                unique_sources.append(s)
        search_sources = unique_sources
        yield {"type": "sources", "data": search_sources}

    yield {"type": "_result", "text": search_results_text, "sources": search_sources}


def finalize_search_context(
    *,
    session_id: str,
    user_input: str,
    messages: list,
    search_needed: bool,
    search_queries: list,
    search_results_text: Optional[str],
    direct_url_texts: list[str] | None = None,
) -> tuple[Optional[str], bool]:
    """
    URL本文統合・carryover・実質空判定・carryover保存。
    Returns: (search_results_text, search_unsupported)
    """
    if direct_url_texts:
        existing_text = search_results_text or ""
        search_results_text = clip_search_results(existing_text + "\n\n" + "\n\n".join(direct_url_texts))
        logger.info("ユーザー指定URLのスクレイピング本文をコンテキストに統合完了")

    if not search_results_text:
        search_results_text = maybe_carry_search_results(
            session_id, user_input, messages, search_needed, search_results_text
        )

    search_unsupported = False
    if search_needed:
        if is_search_effectively_empty(user_input, search_queries, search_results_text):
            search_unsupported = True
            search_results_text = SEARCH_UNSUPPORTED_PLACEHOLDER
            logger.warning("🚫 検索結果が実質空のため推測禁止プレースホルダに置換")

    if search_results_text and not search_unsupported:
        store_search_carryover(session_id, search_results_text, search_queries, user_input)

    # IBKR 口座照会: 検索の有無に関係なくスナップショットを先頭注入
    try:
        from app.core.ibkr.intent import prepend_ibkr_snapshot

        search_results_text = prepend_ibkr_snapshot(user_input, search_results_text)
    except Exception as e:
        logger.warning(f"IBKR snapshot inject failed: {e}")

    return search_results_text, search_unsupported
