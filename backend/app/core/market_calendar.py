"""
Market Calendar — 市場開閉カレンダー（ルールベース自動計算）

祝日ルールに基づいて任意の年の米国・日本市場の開閉を自動判定。
静的JSONではないため、2026年でも2030年でも正確に計算可能。

【注意】
これはルールベースの推定値です。確実な情報が必要な場合は
公式サイト（nyse.com, jpx.co.jp）で確認してください。
"""
import datetime
from typing import Optional
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 日本の祝日法に基づくルール設定
# 米国市場の祝日ルール（NYSE/NASDAQ互換）


def _easter(year: int) -> datetime.date:
    """復活祭（Easter Sunday）を計算（メーウス・ジョーンズ・ブッチャーアルゴリズム）"""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return datetime.date(year, month, day)


def _nth_weekday(year: int, month: int, weekday: int, n: int, reverse: bool = False) -> datetime.date:
    """第n回目の指定曜日（reverse=Trueなら最後からn回目）"""
    if reverse:
        # 最終週
        if month == 12:
            last_day = datetime.date(year, 12, 31)
        else:
            last_day = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)
        offset = (last_day.weekday() - weekday) % 7
        return last_day - datetime.timedelta(days=offset - 7 * (n - 1))
    else:
        first_day = datetime.date(year, month, 1)
        offset = (weekday - first_day.weekday()) % 7
        return first_day + datetime.timedelta(days=offset + 7 * (n - 1))


def _adjust_weekend(d: datetime.date) -> datetime.date:
    """祝日が土日に当たった場合の振替"""
    if d.weekday() == 5:  # 土曜→金曜
        return d - datetime.timedelta(days=1)
    elif d.weekday() == 6:  # 日曜→月曜
        return d + datetime.timedelta(days=1)
    return d


def _spring_equinox(year: int) -> datetime.date:
    """春分の日（3月20日or21日） - 簡易計算式"""
    # 1851〜2099年用の計算式
    if year <= 2099:
        day = int(20.8431 + 0.242194 * (year - 1980) - (year - 1980) // 4)
    else:
        day = int(21.851 + 0.242194 * (year - 1980) - (year - 1980) // 4)
    return datetime.date(year, 3, day)


def _autumn_equinox(year: int) -> datetime.date:
    """秋分の日（9月22日or23日） - 簡易計算式"""
    if year <= 2099:
        day = int(23.2488 + 0.242194 * (year - 1980) - (year - 1980) // 4)
    else:
        day = int(24.2488 + 0.242194 * (year - 1980) - (year - 1980) // 4)
    return datetime.date(year, 9, day)


# ============================================================
# サマータイム判定（米国DST: 第2日曜3月〜第1日曜11月）
# ============================================================
def _is_us_dst(dt: datetime.datetime) -> bool:
    """
    JSTの日時が米国DST期間中か判定。
    
    DST期間: 3月第2日曜 02:00 ET 〜 11月第1日曜 02:00 ET
    JST換算: 3月第2日曜 15:00 〜 11月第1日曜 15:00
    
    naive datetime（タイムゾーンなし）で日付比較を行う。
    """
    year = dt.year
    # DST開始: 3月第2日曜 02:00 ET → JST 15:00
    dst_start = _nth_weekday(year, 3, 6, 2)  # 3月第2日曜
    dst_start_dt = datetime.datetime(year, 3, dst_start.day, 15, 0)
    # DST終了: 11月第1日曜 02:00 ET → JST 15:00
    dst_end = _nth_weekday(year, 11, 6, 1)  # 11月第1日曜
    dst_end_dt = datetime.datetime(year, 11, dst_end.day, 15, 0)
    
    # JST（UTC+9）同士で比較（tzinfoを付けないnaive datetime）
    return dst_start_dt.date() <= dt.date() < dst_end_dt.date()


def _jst_to_et(jst_dt: datetime.datetime) -> datetime.datetime:
    """JST (UTC+9) を ET (UTC-4 or UTC-5) に変換"""
    dst = _is_us_dst(jst_dt)
    utc_offset = datetime.timedelta(hours=4) if dst else datetime.timedelta(hours=5)
    # JST→UTC→ET
    utc = jst_dt - datetime.timedelta(hours=9)
    return utc - utc_offset


def _is_us_trading_hours(jst_dt: datetime.datetime) -> bool:
    """米国市場の取引時間内か（9:30〜16:00 ET）"""
    et_dt = _jst_to_et(jst_dt)
    # 取引時間: 09:30〜16:00 ET
    market_open = et_dt.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = et_dt.replace(hour=16, minute=0, second=0, microsecond=0)
    return market_open <= et_dt < market_close


def _is_jp_trading_hours(jst_dt: datetime.datetime) -> bool:
    """日本市場の取引時間内か（前場9:00〜11:30, 後場12:30〜15:00）"""
    hour = jst_dt.hour
    minute = jst_dt.minute
    # 前場: 9:00〜11:30
    if (hour == 9 and minute >= 0) or (hour == 10) or (hour == 11 and minute < 30):
        return True
    # 後場: 12:30〜15:00
    if (hour == 12 and minute >= 30) or (hour == 13) or (hour == 14):
        return True
    return False


def get_us_holidays(year: int) -> list[dict]:
    """
    米国株式市場（NYSE/NASDAQ）の祝日リストを返す。
    """
    holidays = []
    
    # 1. ニューイヤーズデイ（1月1日、土日振替）
    holidays.append({
        "date": _adjust_weekend(datetime.date(year, 1, 1)),
        "name": "New Year's Day",
        "type": "closed",
    })
    
    # 2. MLKデー（1月第3月曜）
    holidays.append({
        "date": _nth_weekday(year, 1, 0, 3),
        "name": "Martin Luther King Jr. Day",
        "type": "closed",
    })
    
    # 3. 大統領デー（2月第3月曜）
    holidays.append({
        "date": _nth_weekday(year, 2, 0, 3),
        "name": "Presidents' Day",
        "type": "closed",
    })
    
    # 4. グッドフライデー（復活祭の2日前）
    easter = _easter(year)
    holidays.append({
        "date": easter - datetime.timedelta(days=2),
        "name": "Good Friday",
        "type": "closed",
    })
    
    # 5. メモリアルデー（5月最終月曜）
    holidays.append({
        "date": _nth_weekday(year, 5, 0, 1, reverse=True),
        "name": "Memorial Day",
        "type": "closed",
    })
    
    # 6. 独立記念日（7月4日、土日振替）
    holidays.append({
        "date": _adjust_weekend(datetime.date(year, 7, 4)),
        "name": "Independence Day",
        "type": "closed",
    })
    
    # 7. レイバーデー（9月第1月曜）
    holidays.append({
        "date": _nth_weekday(year, 9, 0, 1),
        "name": "Labor Day",
        "type": "closed",
    })
    
    # 8. 感謝祭（11月第4木曜）
    holidays.append({
        "date": _nth_weekday(year, 11, 3, 4),
        "name": "Thanksgiving Day",
        "type": "closed",
    })
    
    # 9. クリスマス（12月25日、土日振替）
    holidays.append({
        "date": _adjust_weekend(datetime.date(year, 12, 25)),
        "name": "Christmas Day",
        "type": "closed",
    })
    
    return holidays


def get_us_early_closes(year: int) -> list[dict]:
    """
    米国株式市場の短縮取引日を返す。
    """
    early_closes = []
    
    # 感謝祭の翌日（13:00 ET閉場）
    thanksgiving = _nth_weekday(year, 11, 3, 4)
    early_closes.append({
        "date": thanksgiving + datetime.timedelta(days=1),
        "name": "Day after Thanksgiving",
        "type": "early_close",
        "close_time": "13:00 ET",
    })
    
    # クリスマスイブ（13:00 ET閉場）
    christmas = datetime.date(year, 12, 24)
    if christmas.weekday() < 5:  # 平日のみ
        early_closes.append({
            "date": christmas,
            "name": "Christmas Eve",
            "type": "early_close",
            "close_time": "13:00 ET",
        })
    
    return early_closes


def get_jp_holidays(year: int) -> list[dict]:
    """
    日本株式市場（東京証券取引所）の祝日リストを返す。
    """
    holidays = []
    
    # 元日
    holidays.append({"date": datetime.date(year, 1, 1), "name": "元日", "type": "closed"})
    
    # 成人の日（1月第2月曜）
    holidays.append({"date": _nth_weekday(year, 1, 0, 2), "name": "成人の日", "type": "closed"})
    
    # 建国記念の日（2月11日）
    holidays.append({"date": datetime.date(year, 2, 11), "name": "建国記念の日", "type": "closed"})
    
    # 天皇誕生日（2月23日）
    holidays.append({"date": datetime.date(year, 2, 23), "name": "天皇誕生日", "type": "closed"})
    
    # 春分の日
    holidays.append({"date": _spring_equinox(year), "name": "春分の日", "type": "closed"})
    
    # 昭和の日（4月29日）
    holidays.append({"date": datetime.date(year, 4, 29), "name": "昭和の日", "type": "closed"})
    
    # 憲法記念日（5月3日）
    holidays.append({"date": datetime.date(year, 5, 3), "name": "憲法記念日", "type": "closed"})
    
    # みどりの日（5月4日）
    holidays.append({"date": datetime.date(year, 5, 4), "name": "みどりの日", "type": "closed"})
    
    # こどもの日（5月5日）
    holidays.append({"date": datetime.date(year, 5, 5), "name": "こどもの日", "type": "closed"})
    
    # 海の日（7月第3月曜）
    holidays.append({"date": _nth_weekday(year, 7, 0, 3), "name": "海の日", "type": "closed"})
    
    # 山の日（8月11日）
    holidays.append({"date": datetime.date(year, 8, 11), "name": "山の日", "type": "closed"})
    
    # 敬老の日（9月第3月曜）
    holidays.append({"date": _nth_weekday(year, 9, 0, 3), "name": "敬老の日", "type": "closed"})
    
    # 秋分の日
    holidays.append({"date": _autumn_equinox(year), "name": "秋分の日", "type": "closed"})
    
    # スポーツの日（10月第2月曜）
    holidays.append({"date": _nth_weekday(year, 10, 0, 2), "name": "スポーツの日", "type": "closed"})
    
    # 文化の日（11月3日）
    holidays.append({"date": datetime.date(year, 11, 3), "name": "文化の日", "type": "closed"})
    
    # 勤労感謝の日（11月23日）
    holidays.append({"date": datetime.date(year, 11, 23), "name": "勤労感謝の日", "type": "closed"})
    
    return holidays


def check_market_status(dt: Optional[datetime.datetime] = None) -> dict:
    """
    指定日時の市場ステータスを返す（取引時間および時差・開場前/引け後の考慮あり）。
    
    Returns:
        {
            "datetime": "YYYY-MM-DD HH:MM (JST)",
            "et_datetime": "YYYY-MM-DD HH:MM (EDT/EST)",
            "us_market": "open" | "pre_market" | "post_market" | "closed" | "early_close",
            "us_close_time": "16:00 ET" | "13:00 ET" | None,
            "jp_market": "open" | "closed",
            "jp_reason": "weekend" | "holiday_name" | "outside_trading_hours" | None,
            "us_reason": "weekend" | "holiday_name" | "pre_market_before_open" | "post_market_closed_for_day" | None,
            "disclaimer": "※ルールベース推定値です。確実な情報は公式サイトで確認してください。"
        }
    """
    JST = datetime.timezone(datetime.timedelta(hours=9))
    if dt is None:
        dt = datetime.datetime.now(JST)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=JST)
    else:
        dt = dt.astimezone(JST)
    
    date = dt.date()
    year = date.year
    
    # 米国現地時間 (ET) の算出
    et_dt = _jst_to_et(dt)
    is_dst = _is_us_dst(dt)
    et_tz_label = "EDT (夏時間)" if is_dst else "EST (冬時間)"
    et_datetime_str = f"{et_dt.strftime('%Y-%m-%d %H:%M')} ({et_tz_label})"
    
    us_holidays = get_us_holidays(year)
    us_early_closes = get_us_early_closes(year)
    jp_holidays = get_jp_holidays(year)
    
    # 週末チェック (米国は現地時間et_dtの日付で判定、日本はdtで判定)
    et_date = et_dt.date()
    is_us_weekend = et_date.weekday() >= 5
    is_jp_weekend = date.weekday() >= 5
    
    # ========================================
    # 米国市場
    # ========================================
    if is_us_weekend:
        us_status = "closed"
        us_reason = "weekend"
        us_close = None
    else:
        # 祝日チェック（現地日付et_dateでチェック）
        us_holiday_name = None
        for h in us_holidays:
            if h["date"] == et_date:
                us_holiday_name = h["name"]
                break
        
        if us_holiday_name:
            us_status = "closed"
            us_reason = us_holiday_name
            us_close = None
        else:
            # 短縮取引日チェック（日付ベース）
            early_close_time = None
            for e in us_early_closes:
                if e["date"] == et_date:
                    early_close_time = e["close_time"]
                    break
            
            # 取引時間内・開場前・引け後チェック
            if _is_us_trading_hours(dt):
                us_status = "open"
                us_reason = None
                us_close = early_close_time or "16:00 ET"
                if early_close_time:
                    us_status = "early_close"
            else:
                et_time_min = et_dt.hour * 60 + et_dt.minute
                if et_time_min < 9 * 60 + 30:
                    us_status = "pre_market"
                    us_reason = "pre_market_before_open"
                    us_close = None
                else:
                    us_status = "post_market"
                    us_reason = "post_market_closed_for_day"
                    us_close = None
    
    # ========================================
    # 日本市場
    # ========================================
    if is_jp_weekend:
        jp_status = "closed"
        jp_reason = "weekend"
    else:
        # 祝日チェック
        jp_holiday_name = None
        for h in jp_holidays:
            if h["date"] == date:
                jp_holiday_name = h["name"]
                break
        
        if jp_holiday_name:
            jp_status = "closed"
            jp_reason = jp_holiday_name
        else:
            # 取引時間内チェック
            if _is_jp_trading_hours(dt):
                jp_status = "open"
                jp_reason = None
            else:
                jp_status = "closed"
                jp_reason = "outside_trading_hours"
    
    weekdays_ja = ["月", "火", "水", "木", "金", "土", "日"]
    jp_weekday = weekdays_ja[dt.weekday()]
    
    return {
        "datetime": f"{dt.strftime('%Y-%m-%d')} ({jp_weekday}) {dt.strftime('%H:%M')} (JST)",
        "et_datetime": et_datetime_str,
        "us_market": us_status,
        "us_reason": us_reason,
        "us_close_time": us_close,
        "jp_market": jp_status,
        "jp_reason": jp_reason,
        "disclaimer": "※ルールベース推定値です。確実な情報は公式サイト(nyse.com/jpx.co.jp)で確認してください。"
    }


def format_market_status(dt: Optional[datetime.datetime] = None) -> str:
    """市場ステータスと現地時間を人間が読める形式で返す（Supervisor/Executor用）"""
    status = check_market_status(dt)
    JST = datetime.timezone(datetime.timedelta(hours=9))
    base_dt = dt if dt is not None else datetime.datetime.now(JST)
    if base_dt.tzinfo is None:
        base_dt = base_dt.replace(tzinfo=JST)
    weekdays_ja = ["月", "火", "水", "木", "金", "土", "日"]
    today_d = base_dt.date()
    tomorrow_d = today_d + datetime.timedelta(days=1)
    day_after_d = today_d + datetime.timedelta(days=2)

    def _rel_line(label: str, d: datetime.date) -> str:
        return f"{label}={d.strftime('%Y/%m/%d')} ({weekdays_ja[d.weekday()]})"

    parts = []
    parts.append(
        f"【現在の日時と時差状況】\n"
        f"日本時間 (JST): {status['datetime']}\n"
        f"現地ニューヨーク時間 (ET): {status.get('et_datetime', 'N/A')}\n"
        f"【相対日付対応表（JST・厳守）】{_rel_line('今日', today_d)} / "
        f"{_rel_line('明日', tomorrow_d)} / {_rel_line('あさって', day_after_d)}\n"
        f"⚠️ 日付に「明日」「あさって」を付けるときは上記対応表のみ。2日後を『明日』と呼ぶことは禁止。"
    )
    
    # 米国市場
    us_status = status["us_market"]
    if us_status == "open":
        us_text = f"🟢 米国株式市場: レギュラーセッション取引中 ({status['us_close_time']}まで)"
    elif us_status == "early_close":
        us_text = f"🟡 米国株式市場: 短縮取引中 ({status['us_close_time']}まで)"
    elif us_status == "pre_market":
        us_text = (
            f"🟡 米国株式市場: 本日レギュラーセッション開場前（プレマーケット／時間外時間帯）。\n"
            f"   → 現地NYの早朝であり、今日の通常取引（09:30 ET / 日本時間夜）はまだ開場していません。\n"
            f"   → 「今日の市場が終了・クローズした」と誤認せず、「今日の市場はまだ始まっていません（開場前）」と正確に認識し、前営業日の確定終値をベースに語ってください。"
        )
    elif us_status == "post_market":
        us_text = (
            f"🔴 米国株式市場: 本日のレギュラーセッション取引終了（引け後／時間外アフターマーケット）。\n"
            f"   → 確定した本日の終値をベースに解説してください。"
        )
    else:
        us_text = f"🔴 米国株式市場: 本日は終日休場 ({status['us_reason']}) です。前営業日の確定終値をベースに語ってください。"
    parts.append(us_text)
    
    # 日本市場（取引時間外と週末/祝日休場を混同しない）
    jp_icon = {"open": "🟢", "closed": "🔴"}
    jp_text = f"{jp_icon.get(status['jp_market'], '⚪')} 日本株式市場: "
    if status["jp_market"] == "open":
        jp_text += "取引中"
    elif status.get("jp_reason") == "outside_trading_hours":
        jp_text += "取引時間外（本日は通常営業日）"
    elif status.get("jp_reason") == "weekend":
        jp_text += "休場 (週末)"
    elif status.get("jp_reason"):
        jp_text += f"休場 ({status['jp_reason']})"
    else:
        jp_text += "休場"
    parts.append(jp_text)
    
    # 向こう7日間のスケジュールカレンダーを作成・追加（祝日見落とし・休日営業誤認の完全防止）
    schedule_lines = ["【📅 向こう7日間の市場開閉＆祝日スケジュール表（予定の言及時は必ず参照・祝日無視の厳格禁止）】"]
    for i in range(1, 8):
        target_dt = base_dt + datetime.timedelta(days=i)
        target_date = target_dt.date()
        wd_str = weekdays_ja[target_date.weekday()]
        
        # 日中12:00 JST時点のステータス判定でその日の休場/祝日/営業をチェック
        check_dt = datetime.datetime(target_date.year, target_date.month, target_date.day, 12, 0, tzinfo=JST)
        st = check_market_status(check_dt)
        
        if st["jp_reason"] and st["jp_reason"] not in ["weekend", "outside_trading_hours"]:
            jp_st = f"🔴 休場 (祝日: {st['jp_reason']})"
        elif target_date.weekday() in [5, 6]:
            jp_st = "🔴 休場 (週末)"
        else:
            jp_st = "🟢 通常営業日"
            
        if st["us_reason"] and st["us_reason"] not in ["pre_market_before_open", "post_market_closed_for_day", "weekend"]:
            us_st = f"🔴 休場 (祝日: {st['us_reason']})"
        elif target_date.weekday() in [5, 6]:
            us_st = "🔴 休場 (週末)"
        else:
            us_st = "🟢 通常営業日"
            
        schedule_lines.append(f"・{target_date.strftime('%Y/%m/%d')} ({wd_str}): 🇯🇵 東証: {jp_st} | 🇺🇸 米国: {us_st}")
        
    parts.append("\n".join(schedule_lines))
    parts.append(f"⚠️ {status['disclaimer']}")
    
    return "\n".join(parts)