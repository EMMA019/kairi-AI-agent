"""
検索結果の単純リランカー（キーワード + 品質 + 鮮度 + 重複排除）
"""
from datetime import datetime
import re
from urllib.parse import urlparse
from app.utils.logger import get_logger

logger = get_logger(__name__)

HIGH_QUALITY_DOMAINS = {
    "reuters.com": 30.0,
    "bloomberg.com": 30.0,
    "nikkei.com": 30.0,
    "wsj.com": 30.0,
    "cnbc.com": 30.0,
    "ft.com": 30.0,
    "bloomberg.co.jp": 30.0,
    "jp.reuters.com": 30.0,
    "investing.com": 20.0,
    "finance.yahoo.com": 15.0,
    "bbc.com": 20.0,
    "cnn.com": 20.0,
    "nhk.or.jp": 20.0,
}

LOW_QUALITY_DOMAINS = {
    "yahoo.co.jp": -10.0,
    "msn.com": -10.0,
    "5ch.net": -30.0,
    "togetter.com": -20.0,
    "livedoor.jp": -15.0,
    "prtimes.jp": -5.0,
}

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _tokenize(text: str) -> set[str]:
    text_lower = text.lower()
    words = set(re.findall(r"[a-z0-9]+", text_lower))
    jp_chars = re.findall(r"[\u3040-\u9fff]+", text)
    for jp in jp_chars:
        for i in range(len(jp) - 1):
            words.add(jp[i : i + 2])
    return words


def _get_domain_score(url: str) -> float:
    try:
        domain = urlparse(url).netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        for hq_domain, score in HIGH_QUALITY_DOMAINS.items():
            if domain == hq_domain or domain.endswith("." + hq_domain):
                return score
        for lq_domain, score in LOW_QUALITY_DOMAINS.items():
            if domain == lq_domain or domain.endswith("." + lq_domain):
                return score
    except Exception:
        pass
    return 0.0


def _calculate_jaccard_similarity(tokens1: set[str], tokens2: set[str]) -> float:
    if not tokens1 and not tokens2:
        return 1.0
    if not tokens1 or not tokens2:
        return 0.0
    intersection = len(tokens1 & tokens2)
    union = len(tokens1 | tokens2)
    return intersection / union


def _age_points(age_days: int, weight: float) -> float:
    if 0 <= age_days <= 2:
        return 25.0 * weight
    if age_days <= 7:
        return 8.0 * weight
    if age_days > 30:
        return -20.0 * weight
    return -10.0 * weight


def _extract_dates(blob: str) -> list[datetime]:
    dates: list[datetime] = []
    for m in re.finditer(r"(20\d{2})[年/\-](\d{1,2})[月/\-](\d{1,2})", blob):
        try:
            dates.append(datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except ValueError:
            pass
    for m in re.finditer(
        r"\b(January|February|March|April|May|June|July|August|September|October|November|December|"
        r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2}),?\s+(20\d{2})\b",
        blob,
        flags=re.IGNORECASE,
    ):
        try:
            mon = _MONTHS[m.group(1).lower()]
            dates.append(datetime(int(m.group(3)), mon, int(m.group(2))))
        except ValueError:
            pass
    return dates


def _freshness_score(query: str, title: str, snippet: str) -> float:
    blob = f"{title} {snippet}"
    now = datetime.now()
    score = 0.0
    freshness_query = any(
        k in (query or "").lower()
        for k in ("今日", "本日", "today", "終値", "大引け", "市況", "前場", "後場", "close", "market")
    )
    weight = 1.5 if freshness_query else 1.0
    dates = _extract_dates(blob)
    for d in dates:
        score += _age_points((now - d).days, weight)

    # 今日系市況: 明示日付が古すぎる記事は強く落とす（最高値更新の過去記事対策）
    if freshness_query and dates:
        newest = max(dates)
        age = (now.date() - newest.date()).days
        if age > 3:
            score -= 55.0
        elif age > 1:
            score -= 25.0
    elif freshness_query and not dates:
        # 日付なしの英語プレマーケット雑多は市況クエリで弱体化
        if re.search(r"\b(?:premarket|after hours|biggest moves)\b", blob, re.I):
            score -= 30.0
        # 市況クエリで日付が全くない記事は基本的に鮮度不明として減点
        else:
            score -= 15.0

    # 下落相場なのに「最高値更新」「大幅続伸」だけの古い文脈を落とす
    if freshness_query and re.search(r"最高値|大幅続伸|1636円高|6万6", blob):
        if re.search(r"急落|続落|大幅安|売り優勢|下落", query or ""):
            score -= 20.0
        # クエリが前場でも、スナップショット注入側と矛盾しやすい定型見出しは減点
        if re.search(r"前場|市況|日経", query or ""):
            score -= 15.0

    # 引け後の先物/夜間クエリ: 朝の『0時＝』『夜間取引終値』記事を降格（今夜スタートと誤認しやすい）
    q = query or ""
    if re.search(r"先物|夜間", q) and re.search(r"夜間取引終値|0時＝|0時=", blob):
        try:
            from zoneinfo import ZoneInfo

            hour = datetime.now(ZoneInfo("Asia/Tokyo")).hour
        except Exception:
            hour = datetime.now().hour
        if hour >= 16 or hour < 6:
            score -= 35.0

    # 米市況の終値クエリ: 朝ラップ（前日終値要約）を降格、引け後記事を昇格
    us_close_query = bool(
        re.search(r"close|closes|wall street|dow|nasdaq|s&p|米国市場|米国株", q, re.I)
    ) and bool(re.search(r"close|closes|end|ends|終値|どうだった", q, re.I))
    if us_close_query:
        if re.search(
            r"stock market news for|premarket movers|before the (?:stock )?market opens|"
            r"5 things to know before|what to know before|opening bell",
            blob,
            re.I,
        ):
            score -= 40.0
        if re.search(
            r"\bends?\b|\bcloses?\b|closing bell|wall street.*(higher|lower|fall|rise|mixed)",
            blob,
            re.I,
        ):
            score += 22.0
        # 前日セッションの大幅下落見出し（当日終値クエリ時）を減点
        if re.search(
            r"drops? more than|closes? down sharply|drag(?:s|ged)? .* lower|"
            r"1,?100|1100.*(drop|fall|安)|AI stocks? drag",
            blob,
            re.I,
        ) and not re.search(r"\bends?\s+(?:sharply\s+)?higher|\bcloses?\s+higher", blob, re.I):
            score -= 30.0
        # クエリ内の明示日付とタイトル日付がズレる記事を減点
        q_dates = _extract_dates(q)
        blob_dates = dates
        if q_dates and blob_dates:
            q_day = max(q_dates).date()
            newest_blob = max(blob_dates).date()
            if abs((newest_blob - q_day).days) >= 1:
                score -= 20.0

    return max(-80.0, min(40.0, score))


_JP_NOISE = re.compile(
    r"\b(?:mortgage|refinance|HELOC|home equity|CD rates?|APY|best account|"
    r"best CD|savings interest|Zillow|Rosen Law|class action|"
    r"Pride Festival|van-ramming|Pirates|Mets|Cubs|grand slam|"
    r"Cerezo Osaka|Borussia Dortmund|prediction markets|Wall Street is here|"
    r"Visa is cutting|ACCESS Newswire|PACSUN|back-to-school|"
    r"Amcor to report|Sorona|SUNON Unveils|ErP 2026|FTSE4Good|DESILO|"
    r"single stock futures|SpaceX|Kalshi)\b|"
    r"住宅ローン|変動金利型住宅|定期預金おすすめ",
    re.IGNORECASE,
)
_JP_MARKET_QUERY = re.compile(
    r"日経|TOPIX|東京株式|東証|日本市場|日本株|業種別|市況|終値|大引け|前場|後場",
    re.IGNORECASE,
)
_JP_SIGNAL = re.compile(
    r"日経|TOPIX|東証|東京株式|業種|市況|終値|大引け|前場|後場|銀行株|保険株|半導体",
    re.IGNORECASE,
)


def _jp_market_noise_penalty(query: str, title: str, snippet: str) -> float:
    """日本市況クエリなのに米住宅ローン/CD/スポーツ訴訟が混ざるのを降格。"""
    q = query or ""
    if not _JP_MARKET_QUERY.search(q):
        return 0.0
    blob = f"{title} {snippet}"
    penalty = 0.0
    if _JP_NOISE.search(blob):
        penalty -= 45.0
    if _JP_SIGNAL.search(blob):
        penalty += 12.0
    return penalty


def rerank(query: str, results: list[dict], top_k: int = 10, threshold: float = 0.0) -> list[dict]:
    if not results or len(results) <= 1:
        return results

    try:
        query_tokens = _tokenize(query)
        if not query_tokens:
            return results[:top_k]

        scored = []
        for item in results:
            score = 0.0
            title = item.get("title", "")
            snippet = item.get("snippet", "")
            url = item.get("url", "")

            title_tokens = _tokenize(title)
            snippet_tokens = _tokenize(snippet)
            url_tokens = _tokenize(url)

            score += len(query_tokens & title_tokens) * 10.0
            score += len(query_tokens & url_tokens) * 5.0
            score += len(query_tokens & snippet_tokens) * 2.0

            query_lower = query.lower()
            if query_lower in title.lower():
                score += 20.0
            if query_lower in snippet.lower():
                score += 10.0

            score += _get_domain_score(url)
            score += _freshness_score(query, title, snippet)
            score += _jp_market_noise_penalty(query, title, snippet)
            scored.append((score, item, title_tokens | snippet_tokens))

        scored.sort(key=lambda x: x[0], reverse=True)

        deduplicated = []
        seen_tokens_list = []
        for score, item, item_tokens in scored:
            is_duplicate = False
            for seen_tokens in seen_tokens_list:
                if _calculate_jaccard_similarity(item_tokens, seen_tokens) > 0.6:
                    is_duplicate = True
                    break
            if not is_duplicate:
                deduplicated.append(item)
                seen_tokens_list.append(item_tokens)
            if len(deduplicated) >= top_k:
                break

        top_score = scored[0][0] if scored else 0
        logger.info(
            f"リランキング完了: {len(results)}件 → {len(deduplicated)}件 "
            f"(重複排除済) / 最高スコア: {top_score:.1f}"
        )
        return deduplicated

    except Exception as e:
        logger.error(f"リランキングに失敗しました: {e}")
        return results[:top_k]
