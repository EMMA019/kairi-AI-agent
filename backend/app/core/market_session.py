"""
TSE Market Session & Holiday Calendar Router — 東京株式市場（東証）機械ルーティング

【目的】
- ユーザーから市場動向・株価・日経平均等の質問が来た際、LLMに現在時間帯を推測させず、
  Python側の時刻・カレンダー判定（休場判定＋9段階営業日ルーティング）に基づいて
  正確なセッションコンテキスト（場前／寄り直後／前場／昼休み／後場／クロージング・オークション／大引け速報／夜間／休場）を強制注入する。
- ザラ場中の現在値誤認（記事内の前場終値を現在値と言う等）および制度改定（14:55〜15:00のクロージング・オークション）を完璧に処理する。
"""
from datetime import datetime, date
import zoneinfo
from typing import Optional
from app.utils.logger import get_logger

logger = get_logger(__name__)

# JSTタイムゾーン
try:
    JST = zoneinfo.ZoneInfo("Asia/Tokyo")
except Exception:
    import datetime as _dt
    JST = _dt.timezone(_dt.timedelta(hours=9))

try:
    ET = zoneinfo.ZoneInfo("America/New_York")
except Exception:
    import datetime as _dt
    ET = _dt.timezone(_dt.timedelta(hours=-5))

# 固定祝日・年末年始の簡易チェックおよびjpholidayによる判定
NEW_YEAR_HOLIDAYS = {(12, 31), (1, 1), (1, 2), (1, 3)}

# 大阪取引所 日経225先物 夜間（概略・カレンダー日をまたぐ）
# 日中終了後 ~16:30 開始 → 翌 ~05:55 終了（祝日・臨時変更あり）
_OSE_NIGHT_START_MIN = 16 * 60 + 30  # 16:30
_OSE_NIGHT_END_MIN = 5 * 60 + 55  # 05:55


def get_jp_session_bucket(now: Optional[datetime] = None) -> str:
    """東証セッション粗い区分: preopen / morning / lunch / afternoon / closed."""
    if now is None:
        now = datetime.now(JST)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=JST)
    else:
        now = now.astimezone(JST)
    mins = now.hour * 60 + now.minute
    if mins < 9 * 60:
        return "preopen"
    if mins < 11 * 60 + 30:
        return "morning"
    if mins < 12 * 60 + 30:
        return "lunch"
    if mins < 15 * 60:
        return "afternoon"
    return "closed"


def get_us_session_bucket(now: Optional[datetime] = None) -> str:
    """
    米国株の粗いセッション区分（ET 基準）:
    pre_market / open / post_market / closed（週末・祝日）。
    """
    if now is None:
        now = datetime.now(JST)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=JST)
    else:
        now = now.astimezone(JST)

    et = now.astimezone(ET)
    et_date = et.date()
    if et_date.weekday() >= 5:
        return "closed"

    try:
        from app.core.market_calendar import get_us_holidays

        for h in get_us_holidays(et_date.year):
            if h.get("date") == et_date:
                return "closed"
    except Exception:
        pass

    mins = et.hour * 60 + et.minute
    if mins < 9 * 60 + 30:
        return "pre_market"
    if mins < 16 * 60:
        return "open"
    return "post_market"


def us_session_is_live(now: Optional[datetime] = None) -> bool:
    """プレ／ザラ場中か（ライブ検索・直近値スナップショット向け）。"""
    return get_us_session_bucket(now) in ("pre_market", "open")


def jp_cash_price_query_word(now: Optional[datetime] = None) -> str:
    """
    検索クエリ用の価格語。場中に『終値』を硬直指定すると記事・回答が誤認する。
    preopen/morning/afternoon → 現在値 / 市況
    lunch → 前場終値
    closed → 終値
    """
    bucket = get_jp_session_bucket(now)
    if bucket == "lunch":
        return "前場終値"
    if bucket == "closed":
        return "終値"
    return "現在値"


def get_ose_night_futures_phase(now: Optional[datetime] = None) -> str:
    """
    日経225先物・夜間セッションの粗い位相。
    - night_active: 夜間ザラ場中（夕方〜翌朝）
    - night_just_ended: 夜間終了直後〜現金寄り前（朝の『夜間終値』記事が正当）
    - day_cash: 現金市場中心の時間帯（夜間は非アクティブ）
    - evening_pre_night: 大引け後〜夜間寄り前
    """
    if now is None:
        now = datetime.now(JST)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=JST)
    else:
        now = now.astimezone(JST)
    mins = now.hour * 60 + now.minute
    if mins <= _OSE_NIGHT_END_MIN:
        return "night_active"  # 0:00–05:55 は前日夕方開始の夜間の続き
    if mins < 9 * 60:
        return "night_just_ended"
    if mins < _OSE_NIGHT_START_MIN:
        if mins >= 15 * 60:
            return "evening_pre_night"
        return "day_cash"
    return "night_active"  # 16:30–23:59


def is_tse_holiday(target_date: date) -> bool:
    """東証の休場日（土日・祝日・年末年始）を機械判定"""
    # 土日チェック (5: 土曜日, 6: 日曜日)
    if target_date.weekday() >= 5:
        return True
    
    # 年末年始休場 (12/31〜1/3)
    if (target_date.month, target_date.day) in NEW_YEAR_HOLIDAYS:
        return True
    
    # jpholidayによる日本の祝日判定
    try:
        import jpholiday
        if jpholiday.is_holiday(target_date):
            return True
    except ImportError:
        # jpholidayがインストールされていない場合の主要祝日フォールバック判定 (2026年等対応)
        # 固定祝日
        fixed_holidays = {
            (1, 1), (2, 11), (2, 23), (4, 29), (5, 3), (5, 4), (5, 5),
            (8, 11), (11, 3), (11, 23)
        }
        if (target_date.month, target_date.day) in fixed_holidays:
            return True
        # ※ハッピーマンデー等はjpholidayを推奨
    
    return False


def get_tse_market_session_context(user_input: str = "") -> str:
    """
    現在のJST日時およびユーザー入力から、市場セッションのコンテキスト文字列を生成する。
    日本株・相場関連のキーワードが含まれている場合、または明示的な市場照会時に
    該当セッションの厳格な指示を生成。
    """
    # トリガー判定: 日本株・市場関連キーワード
    MARKET_KEYWORDS = [
        "日経", "株", "市場", "東証", "TOPIX", "相場", "市況", "前場", "後場",
        "寄り", "引け", "マザーズ", "グロース", "キオクシア", "アドバンテスト",
        "半導体", "終値", "円安", "円高", "為替", "ダウ", "ナスダック"
    ]
    if user_input and not any(kw in user_input for kw in MARKET_KEYWORDS):
        return ""

    now_jst = datetime.now(JST)
    current_date = now_jst.date()
    current_time_str = now_jst.strftime("%H:%M")
    hour = now_jst.hour
    minute = now_jst.minute
    time_minutes = hour * 60 + minute

    # 1. 休場日判定 (土日・祝日・年末年始)
    if is_tse_holiday(current_date):
        session_label = "休場日セッション (Market Closed / Holiday)"
        instruction = (
            f"【市場セッション機械判定: {current_date.strftime('%Y年%m月%d日')} ({session_label})】\n"
            f"本日は東京株式市場の休場日（土日／祝日／年末年始等）です。\n"
            f"現在進行形のザラ場取引値や日中価格の変動として語ることを厳格に禁止します。\n"
            f"直近営業日の確定終値をベースに、休場期間中の欧米市場動向（米国株・為替等）や今後の注目材料を中心に解説してください。"
        )
        logger.info(f"📈 東証セッション判定: {session_label}")
        return "\n\n" + instruction

    # 2. 営業日の9段階時間帯ルーティング
    if time_minutes < 9 * 60:
        # 00:00 - 08:59
        session_label = "場前（寄り前）セッション"
        instruction = (
            "取引開始前の時間帯です。前日終値と、昨晩の米国株動向・日経平均先物の気配・ADRに基づいた本日の相場見通しを中心に解説してください。"
        )
    elif 9 * 60 <= time_minutes <= 9 * 60 + 5:
        # 09:00 - 09:05
        session_label = "寄り付き直後（価格形成期・特別気配）セッション"
        instruction = (
            "東証は現在寄り付き直後（価格形成期）です。特別気配や板寄せによって一部銘柄の初値が未確定であり、指数が不安定に乱高下しやすい時間帯です。\n"
            "【🔴 P0】この時点の値を『終値』『前場終値』と呼ぶことは禁止。\n"
            "始値気配と寄り付きからの大まかな流れを中心に慎重に解説し、単一瞬間の乱高下値を確定的な日中トレンドとして言い切ることは避けてください。"
        )
    elif 9 * 60 + 6 <= time_minutes < 11 * 60 + 30:
        # 09:06 - 11:29
        session_label = "前場（ザラ場）セッション"
        instruction = (
            "東証は現在、前場の取引中です。寄り付きからの株価推移とセクター動向、直近の材料を定性的に解説してください。\n"
            "【🔴 P0: 場中の終値誤認禁止】前場はまだ終了していない。"
            "スナップショットの直近値を『終値』『前場終値』『大引け』と呼ぶことは厳格に禁止。"
            "必ず『直近値（前場取引中）』『現在値』と明示すること。\n"
            "ニュース記事中の古いタイムスタンプの数値を今の瞬間値として断言するリスクを避け、寄り付きからの全体のトレンド・方向性に注目して解説すること。"
        )
    elif 11 * 60 + 30 <= time_minutes < 12 * 60 + 30:
        # 11:30 - 12:29
        session_label = "昼休みセッション"
        instruction = (
            "前場の取引が終了し、現在は昼休み時間帯です。\n"
            "『前場の終値は〇〇円』と確定値として明示し、午後の後場見通しや昼休みに報じられた材料・為替の動きを整理してください。"
        )
    elif 12 * 60 + 30 <= time_minutes <= 14 * 60 + 54:
        # 12:30 - 14:54
        session_label = "後場（ザラ場）セッション"
        instruction = (
            "東証は現在、後場の取引中です。前場終値からの推移および日中全体のトレンド、セクター資金の流入・流出動向を解説してください。\n"
            "【🔴 P0: 場中の終値誤認禁止】後場中の直近値を『本日の終値』『大引け』と呼ぶことは禁止。『直近値（後場取引中）』と明示せよ。\n"
            "※『前場どうだった』と聞かれても、スナップショットの直近値（後場）を前場終値として使ってはいけない。"
            "前場終値は morning_close（または明示された前場終値）のみ。無い場合は『前場終値は未確認』とし、直近値と混同しないこと。\n"
            "※記事中の午前終値などを現在の取引値として混同しないよう注意し、定性的な相場の流れと構造を解説すること。"
        )
    elif 14 * 60 + 55 <= time_minutes < 15 * 60:
        # 14:55 - 14:59
        session_label = "クロージング・オークション期セッション (TSE Closing Auction Phase)"
        instruction = (
            "【東証 2024年11月導入制度適用中】東証は現在、大引け直前の『クロージング・オークション（14:55〜15:00の終値決定用板寄せ時間）』に入っています。\n"
            "ザラ場取引は14:55時点で終了しており、現在表示されている価格は14:55最終値または参考気配値です。\n"
            "14:55時点の株価推移をまとめつつ、間もなく（15時ちょうどに）本日の正式な終値が決定・確定することを明記して解説してください。"
        )
    elif 15 * 60 <= time_minutes <= 15 * 60 + 30:
        # 15:00 - 15:30
        session_label = "大引け直後（速報期）セッション"
        instruction = (
            "本日の取引が終了し、終値が確定した直後の速報時間帯です。\n"
            "確定した本日の終値を中心に、1日の相場概況、買い材料・売り材料、セクター動向を速報ベースでわかりやすく総括してください。"
        )
    else:
        # 15:31 - 23:59
        session_label = "引け後/場外（夜間）セッション"
        instruction = (
            "本日の東証取引は終了しています。確定した本日の終値と相場概況を総括しつつ、\n"
            "今夜の欧米市場（米国株・為替動向）の注目ポイントや日経平均先物等の動きについて解説してください。"
        )

    futures_note = _ose_night_futures_instruction(now_jst)

    full_context = (
        f"【東証市場セッション機械判定 (現在時刻 JST {current_time_str} - {session_label})】\n"
        f"{instruction}\n"
        f"{futures_note}\n\n"
        f"《役割分担原則》数値・価格・高安は構造化ファクトまたは信頼できる検索結果の数値に正確に基づき、"
        f"ニュース記事は「相場が動いた理由・セクター分析・文脈解説」を担当するものとして厳格に使い分けること。"
    )
    logger.info(f"📈 東証セッション判定: {session_label} ({current_time_str})")
    return "\n\n" + full_context


def _ose_night_futures_instruction(now_jst: datetime) -> str:
    """日経225先物・夜間セッションの時間軸誤認を防ぐ機械指示。"""
    phase = get_ose_night_futures_phase(now_jst)
    d = now_jst.strftime("%Y-%m-%d")
    if phase == "night_just_ended":
        return (
            f"【日経225先物・夜間セッション (JST {now_jst.strftime('%H:%M')} / {phase})】\n"
            f"直前の夜間取引は終了済み（概ね05:55頃）。朝の『{d} 夜間取引終値』記事はこの確定値として引用してよい。\n"
            "ただし現金寄り前の気配と混同しないこと。"
        )
    if phase in ("evening_pre_night", "night_active") and now_jst.hour >= 15:
        return (
            f"【🔴 P0: 日経225先物・夜間時間軸 (JST {now_jst.strftime('%H:%M')} / {phase})】\n"
            "大阪取引所の夜間取引は概ね16:30開始→翌05:55終了でカレンダー日をまたぐ。\n"
            "早朝〜午前に出た『○日夜間取引終値』『○日0時＝…円』記事は【直前夜間セッションの確定値】であり、\n"
            "本日夕方の『今夜の夜間がスタートした水準』ではない。\n"
            "それを『本日夜間取引では…でスタートしています』と書いてはならない。"
            "言及するなら『直前夜間セッション終値（朝時点）』と明示し、今夜の気配・寄りは別ソースで確認すること。"
        )
    if phase == "night_active" and now_jst.hour < 9:
        return (
            f"【日経225先物・夜間セッション進行中 (JST {now_jst.strftime('%H:%M')})】\n"
            "現在は夜間ザラ場中。直近の先物价を『現金の終値』や『大引け』と混同しないこと。"
        )
    return (
        f"【日経225先物メモ (phase={phase})】夜間と現金セッションの日付・時刻を混同しないこと。"
    )
