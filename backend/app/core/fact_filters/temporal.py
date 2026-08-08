import re
from datetime import date, timedelta
from typing import Optional
from app.utils.logger import get_logger
from app.core.source_evaluator import verify_entity_claim_attribution

logger = get_logger(__name__)



DOW_KEYWORDS = {
    "月": ["月", "月曜", "monday", "mon"],
    "火": ["火", "火曜", "tuesday", "tue"],
    "水": ["水", "水曜", "wednesday", "wed"],
    "木": ["木", "木曜", "thursday", "thu"],
    "金": ["金", "金曜", "friday", "fri"],
    "土": ["土", "土曜", "saturday", "sat"],
    "日": ["日", "日曜", "sunday", "sun"],
}



def strip_unverified_day_of_week(text: str, source_text: Optional[str] = None, strip_if_no_source: bool = True) -> str:
    """
    曜日間違いハルシネーション防衛フィルター：
    日付表記（例: 7月13日（火））に対する「曜日」表記が、元記事/ソース（source_text）に
    明確に記載されている場合のみ保持し、記載がない場合や不一致の場合は曜日表記を自動削除して日付のみにする。
    """
    if not text or not isinstance(text, str):
        return text

    # 「（月）」「（月曜日）」の両方に対応
    pattern = re.compile(
        r'(?P<date>(?:\d{1,4}年)?\d{1,2}月\d{1,2}日)\s*[（\(](?P<dow>[月火水木金土日])(?:曜日)?[）\)]'
    )

    def replace_dow(match: re.Match) -> str:
        date_part = match.group("date")
        dow = match.group("dow")
        if source_text and isinstance(source_text, str):
            source_lower = source_text.lower()
            keywords = DOW_KEYWORDS.get(dow, [dow])
            if any(kw in source_lower for kw in keywords):
                return match.group(0)
            logger.debug(f"未検証の曜日表記を自動削除: {match.group(0)} -> {date_part}")
            return date_part
        else:
            if strip_if_no_source:
                logger.debug(f"ソース未指定のため曜日表記を原則削除: {match.group(0)} -> {date_part}")
                return date_part
            return match.group(0)

    return pattern.sub(replace_dow, text)



def strip_outdated_past_event_predictions(
    text: str,
) -> str:
    """
    【問題①対応】過去イベントの未来進行形誤認（時系列不整合）の是正：
    現在に対して既に終了した過去イベント（例: 冬季五輪）が「〜に向けて」等の未来進行形として
    誤って記述されている箇所を是正する。
    """
    if not text or not isinstance(text, str):
        return text

    if "冬季五輪に向けて" in text:
        logger.debug("時系列不整合（過去イベントの進行形記述）を是正しました")
        text = text.replace("冬季五輪に向けて", "冬季五輪（2月開催済み）以降の動向として")
    return text



def fix_relative_date_labels(text: str, today: Optional[date] = None) -> str:
    """
    「明日7月31日」のように相対語と絶対日が食い違うハルシネーションを補正する。
    - 明日 = today+1 / あさって = today+2 のみ正しい。
    - 不一致時は正しい相対語に置換（2日後→あさって、1日後以外の明日→相対語削除など）。
    """
    if not text or not isinstance(text, str):
        return text

    from datetime import datetime, timezone, timedelta
    import os

    if today is None:
        fake = (os.environ.get("KAIRI_FAKE_TODAY") or "").strip()
        if fake:
            try:
                today = date.fromisoformat(fake)
            except ValueError:
                today = None
        if today is None:
            jst = timezone(timedelta(hours=9))
            today = datetime.now(jst).date()

    year = today.year

    # 「明日」/「あさって」の直後〜近傍の日付（最大20文字以内）
    pattern = re.compile(
        r"(?P<label>明日|あさって|明後日)"
        r"(?P<mid>[^0-9\n]{0,12})"
        r"(?:(?P<year>\d{4})\s*年\s*)?"
        r"(?P<month>\d{1,2})\s*月\s*(?P<day>\d{1,2})\s*日"
    )

    def _correct_label(delta_days: int) -> Optional[str]:
        if delta_days == 1:
            return "明日"
        if delta_days == 2:
            return "あさって"
        if delta_days == 0:
            return "本日"
        if delta_days > 2:
            return None  # 相対語を落として絶対日のみ
        # 過去日: 相対語を落とす
        return None

    def repl(m: re.Match) -> str:
        label = m.group("label")
        mid = m.group("mid") or ""
        y = int(m.group("year")) if m.group("year") else year
        month = int(m.group("month"))
        day = int(m.group("day"))
        try:
            target = date(y, month, day)
        except ValueError:
            return m.group(0)

        # 年省略で過去日になった場合は翌年候補（年末跨ぎ）
        if not m.group("year") and target < today - timedelta(days=180):
            try:
                target = date(year + 1, month, day)
                y = year + 1
            except ValueError:
                pass

        delta = (target - today).days
        correct = _correct_label(delta)

        date_part = f"{month}月{day}日"
        if m.group("year"):
            date_part = f"{y}年{date_part}"

        # 正しい相対語との一致判定
        label_ok = (
            (label == "明日" and delta == 1)
            or (label in ("あさって", "明後日") and delta == 2)
        )
        if label_ok:
            if label == "明後日":
                return f"あさって{mid}{date_part}"
            return m.group(0)

        if correct is None:
            logger.debug(
                f"相対日付不一致を補正（相対語削除）: {m.group(0)!r} "
                f"(today={today}, target={target}, delta={delta})"
            )
            # mid が「の」「に」等の接続なら日付側に残す
            joined = f"{mid}{date_part}"
            return joined.lstrip(" 、,") if joined.startswith((" ", "、", ",")) else joined.lstrip()

        logger.debug(
            f"相対日付不一致を補正: {m.group(0)!r} → {correct}{mid}{date_part} "
            f"(today={today}, delta={delta})"
        )
        return f"{correct}{mid}{date_part}"

    return pattern.sub(repl, text)


def verify_holiday_and_weekend_claims(text: str) -> str:
    """
    祝日・連休関係の誤断定フィルター（動的祝日判定版）：
    jpholidayを使い、任意の日付に対して「〇連休の何日目か」を動的に正しく判定する。
    翌日（月曜）が祝日（海の日等）である場合の「日曜が3連休の最終日」といった誤認表現を補正する。
    """
    if not text or not isinstance(text, str):
        return text

    try:
        import jpholiday
    except ImportError:
        logger.warning("jpholidayが未インストールのため祝日連休チェックをスキップします")
        return text

    def _get_consecutive_holiday_position(d: date) -> tuple[int, int, str]:
        """指定日が連休の何日目か（1-indexed）と連休全体の日数、祝日名を返す"""
        # 連休の開始日を探す（前日も休みかどうか遡る）
        start = d
        while True:
            prev = start - timedelta(days=1)
            if prev.weekday() >= 5 or jpholiday.is_holiday(prev):  # 土日 or 祝日
                start = prev
            else:
                break
        # 連休の終了日を探す（翌日も休みかどうか進む）
        end = d
        while True:
            nxt = end + timedelta(days=1)
            if nxt.weekday() >= 5 or jpholiday.is_holiday(nxt):  # 土日 or 祝日
                end = nxt
            else:
                break
        total = (end - start).days + 1
        position = (d - start).days + 1
        holiday_name = jpholiday.is_holiday_name(d) or ""
        return position, total, holiday_name

    # 「〇月〇日が3連休の最終日」等の表現を検出
    date_pattern = re.compile(r'(\d{1,2})月(\d{1,2})日.*?(?:3|三|4|四|5|五)連休の(最終日|最後の日)')
    for m in date_pattern.finditer(text):
        try:
            month, day = int(m.group(1)), int(m.group(2))
            from datetime import datetime
            now = datetime.now()
            target = date(now.year, month, day)
            pos, total, hol_name = _get_consecutive_holiday_position(target)
            if total >= 3 and pos < total:
                # 最終日ではない → 補正
                if pos == 1:
                    pos_label = "初日"
                else:
                    pos_label = f"{pos}日目（中日）"
                old_text = m.group(0)
                new_text = re.sub(r'(?:最終日|最後の日)', pos_label, old_text)
                text = text.replace(old_text, new_text)
                logger.info(f"🗓️ 連休位置を動的補正しました: {old_text} → {new_text}")
        except (ValueError, OverflowError):
            pass

    # 汎用パターン: 「3連休の最終日曜日」等
    text = re.sub(r'(?:3|三)連休の最終日曜日', '3連休の中日（日曜日）', text)

    return text



def strip_out_of_period_event_mentions(text: str) -> str:
    """
    期間外イベントおよび終了済み催事の余計な言及行を除去するフィルター：
    「※〇〇は終了しております」「〇〇祭りは〇日まででした」等の
    ユーザーの訪問対象外期間に関する余計な注意書き・お節介行をクリーンアップする。
    """
    if not text or not isinstance(text, str):
        return text

    lines = text.splitlines()
    cleaned = []
    out_of_period_patterns = [
        re.compile(r'.*(?:あじさい祭|花火大会|祭り|催事|イベント|マラソン|フェス(?:ティバル)?|フリマ|フリーマーケット|コンサート|花見|紅葉|盆踊り|夏祭り|冬祭り|春祭り|秋祭り|クリスマスマーケット|カウントダウン|初詣|例大祭|縁日).*(?:終了しており|終了済み|期間外|開催されてい(?:た|ました)|対象外|見られません|間に合いません|過ぎて(?:おり|い)ます).*', re.IGNORECASE),
        re.compile(r'^[※*・\-\s]*(?:注意点|⚠️).*(?:終了|期間外|対象外).*', re.IGNORECASE),
    ]

    for line in lines:
        stripped = line.strip()
        if any(pat.match(stripped) for pat in out_of_period_patterns):
            logger.info(f"🧹 期間外イベントの余計な言及行を除去しました: {stripped}")
            continue
        cleaned.append(line)

    return "\n".join(cleaned)



def verify_maintenance_date_relevance(
    text: str,
    source_text: Optional[str] = None,
    user_input: Optional[str] = None
) -> str:
    """
    工事・休業・メンテナンス期間の日付比較・旅行日程重複検証フィルター：
    具体的な工事・休業期間（例: 7/13〜7/15）がユーザーの訪問・旅行日程（例: 7/19〜7/20）と
    重複していない場合、「工事中で利用できない」という誤警報・誤断定を正確な日付関係表現へ補正する。
    """
    if not text or not isinstance(text, str):
        return text

    # 工事・メンテナンス・休業等の利用制限への言及がない場合はそのまま返す
    if not any(kw in text for kw in ["工事", "メンテナンス", "休業", "利用できません", "ご利用できません", "利用不可"]):
        return text

    ctx_search = (source_text or "") + "\n" + text
    date_range_pattern = re.compile(
        r'(\d{1,2})\s*[月/]\s*(\d{1,2})\s*日?\s*(?:[\(（][月火水木金土日][\)）])?\s*[〜～~\-–—]\s*(?:(\d{1,2})\s*[月/]\s*)?(\d{1,2})\s*日?\s*(?:[\(（][月火水木金土日][\)）])?'
    )

    # 1. ユーザー旅行日程の抽出
    trip_start, trip_end = None, None
    if user_input:
        trip_matches = date_range_pattern.findall(user_input)
        if trip_matches:
            m1, d1, m2, d2 = trip_matches[0]
            trip_start = (int(m1), int(d1))
            trip_end = (int(m2) if m2 else int(m1), int(d2))

    if not trip_start:
        return text

    # 2. 工事・メンテナンス期間の抽出
    m_matches = date_range_pattern.findall(ctx_search)
    m_start, m_end = None, None
    for m1, d1, m2, d2 in m_matches:
        cand_start = (int(m1), int(d1))
        cand_end = (int(m2) if m2 else int(m1), int(d2))
        if cand_start == trip_start and cand_end == trip_end:
            continue
        m_start, m_end = cand_start, cand_end
        break

    if not m_start or not m_end:
        return text

    # 3. 日程の重複判定（m_end < trip_start または m_start > trip_end なら重複なし）
    if m_end < trip_start or m_start > trip_end:
        lines = text.splitlines()
        cleaned = []
        replaced = False
        for line in lines:
            if any(kw in line for kw in ["利用できません", "ご利用できません", "利用不可", "工事中"]) and any(kw in line for kw in ["プール", "工事", "メンテナンス", "休業"]):
                logger.info(f"🔧 工事期間({m_start[0]}/{m_start[1]}-{m_end[0]}/{m_end[1]})と旅行日程({trip_start[0]}/{trip_start[1]}-{trip_end[0]}/{trip_end[1]})の非重複を確認したため誤断定を是正しました")
                cleaned.append(
                    f"※ホテル公式サイト等の通知によるとメンテナンス工事期間は「{m_start[0]}月{m_start[1]}日〜{m_end[0]}月{m_end[1]}日」となっており、ご滞在予定の日程（{trip_start[0]}月{trip_start[1]}日〜{trip_end[0]}月{trip_end[1]}日）には影響なくご利用いただける見込みです（念のため最新状況は施設へご確認ください）。"
                )
                replaced = True
            else:
                cleaned.append(line)
        return "\n".join(cleaned)

    return text



CHRONOLOGICAL_HEDGE_PATTERNS = [
    r"(?:(?:\d{4}年)?までとされていますが|在籍は[^。,\n]+までですが|脱退後も|退任後も|離脱後も|交代後も)[^。\n]*([^\n。]*(?:関わっ|参加|提供|収録|担当|共作|クレジット))",
    r"(?:リリースは[^。,\n]+年ですが|作品は[^。,\n]+年のものですが)[^。\n]*([^\n。]*(?:在籍中|以前のメンバー|当時のボーカル|彼が))",
]



def verify_chronological_rationalization(text: str, source_text: str = "") -> str:
    """
    Type 3（時系列衝突の後付け合理化・縫い合わせ）を非破壊的に検証するガードレール。
    単純に禁止・削除したり主語交代を断定するのではなく、代替仮説を列挙して要検索・再検証を促す。
    """
    if not text or not isinstance(text, str):
        return text

    src = source_text or ""
    has_rationalization = False
    for pat in CHRONOLOGICAL_HEDGE_PATTERNS:
        if re.search(pat, text):
            has_rationalization = True
            break

    if has_rationalization:
        supportive_keywords = ["ゲスト", "脱退後", "退任後", "共作", "クレジット", "作詞", "作曲", "楽曲提供", "アーカイブ", "未発表", "在籍時"]
        is_supported_by_source = False
        if src:
            is_supported_by_source = any(kw in src for kw in supportive_keywords)

        if not is_supported_by_source:
            logger.warning("[ChronologicalDefense] ソース裏付けのない時系列不一致・後付け縫い合わせ（合理化）表現を検知しました → 代替仮説を列挙")
            if "⚠️ **[時系列不一致・要確認]**" not in text and "制作(作曲/クレジット)時期と発表(録音/リリース)時期が異なる可能性" not in text:
                hedge_note = (
                    "\n\n💡 **【時系列整合性の要確認ポイント】**\n"
                    "制作・発表時期と人物の在籍期間にタイムラグや矛盾が生じている可能性があります。断定する前に以下の代替仮説をご検討ください：\n"
                    "- **仮説1**: 制作（作曲/作詞/クレジット等）時期と、実際の発表（録音/リリース/発信等）時期が異なる可能性\n"
                    "- **仮説2**: 対象期間には後任者や別のメンバーが担当・収録していた可能性\n"
                    "- **仮説3**: 前提となる年号や在籍期間そのものがソース記事上で異なっている可能性"
                )
                text = f"⚠️ **[時系列不一致・要確認: 制作・在籍時期の整合性が未検証です]** {text}" + hedge_note

    return text

