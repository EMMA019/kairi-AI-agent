import re
from datetime import date, timedelta
from typing import Optional
from app.utils.logger import get_logger
from app.core.source_evaluator import verify_entity_claim_attribution

logger = get_logger(__name__)


# 単位変換辞書（M=Million=100万, B=Billion=10億 等の単位突合用）
UNIT_MULTIPLIERS = {
    "m": 1_000_000,
    "million": 1_000_000,
    "b": 1_000_000_000,
    "billion": 1_000_000_000,
    "k": 1_000,
    "thousand": 1_000,
    "万": 10_000,
    "億": 100_000_000,
    "兆": 1_000_000_000_000,
}


def _parse_normalized_value(num_str: str, unit_str: str) -> Optional[float]:
    """数値文字列と単位文字列から実数値（例: '25', 'M' -> 25000000.0）を計算"""
    try:
        clean_num = float(num_str.replace(",", "").strip())
        unit_clean = unit_str.strip().lower()
        mult = UNIT_MULTIPLIERS.get(unit_clean, 1.0)
        return clean_num * mult
    except Exception:
        return None


def _extract_monetary_values(text: str) -> list[tuple[str, float]]:
    """文字列から金額・数値を抽出し、(一致文字列, 実数値) のリストを返す。
    日本語の複合単位（1億2500万など）が単一の単位として正しく評価されるよう前処理を行う。
    """
    results = []
    compound_patterns = [
        (r"(\d+(?:,\d+)*(?:\.\d+)?)\s*兆\s*(\d+(?:,\d+)*(?:\.\d+)?)\s*億\s*(\d+(?:,\d+)*(?:\.\d+)?)\s*万", lambda m: (_parse_normalized_value(m.group(1), "") or 0)*10**12 + (_parse_normalized_value(m.group(2), "") or 0)*10**8 + (_parse_normalized_value(m.group(3), "") or 0)*10**4),
        (r"(\d+(?:,\d+)*(?:\.\d+)?)\s*兆\s*(\d+(?:,\d+)*(?:\.\d+)?)\s*億", lambda m: (_parse_normalized_value(m.group(1), "") or 0)*10**12 + (_parse_normalized_value(m.group(2), "") or 0)*10**8),
        (r"(\d+(?:,\d+)*(?:\.\d+)?)\s*億\s*(\d+(?:,\d+)*(?:\.\d+)?)\s*万", lambda m: (_parse_normalized_value(m.group(1), "") or 0)*10**8 + (_parse_normalized_value(m.group(2), "") or 0)*10**4),
        (r"(\d+(?:,\d+)*(?:\.\d+)?)\s*兆\s*(\d+(?:,\d+)*(?:\.\d+)?)\s*万", lambda m: (_parse_normalized_value(m.group(1), "") or 0)*10**12 + (_parse_normalized_value(m.group(2), "") or 0)*10**4),
    ]
    
    modified_text = text
    for pat, calc_fn in compound_patterns:
        for m in re.finditer(pat, modified_text):
            try:
                val = calc_fn(m)
                if val > 0:
                    results.append((m.group(0).strip(), float(val)))
            except Exception:
                pass
        modified_text = re.sub(pat, " ", modified_text)
        
    single_pattern = re.compile(r"(\d+(?:,\d+)*(?:\.\d+)?)\s*(m|million|b|billion|k|thousand|万|億|兆)?", re.IGNORECASE)
    for m in single_pattern.finditer(modified_text):
        val = _parse_normalized_value(m.group(1), m.group(2) or "")
        if val is not None and val > 0:
            results.append((m.group(0).strip(), val))
            
    return results


def verify_numbers_exist_in_source(text: str, source_text: str) -> tuple[bool, str]:
    """
    引用時の存在確認自動化（アプローチB：スマート数値突合対応）：
    回答/ファクトに含まれる数値（金額等）を抽出し、ソーステキストの実数値と単位変換を許容して突合。
    25M(25 Million) と 2500万 を同一と見なし、日本語ネイティブな読みやすい表記を維持する。
    """
    if not source_text or not text:
        return True, text
        
    # ソース側から実数値（標準化した浮動小数点数）のセットを事前構築
    source_values = set()
    for _, val in _extract_monetary_values(source_text):
        source_values.add(round(val, 2))
            
    # 回答側の数値を抽出して検証
    extracted_nums = _extract_monetary_values(text)
    
    unverified_nums = []
    for num_str, val in extracted_nums:
        # 1. 文字列がそのままソースに存在すればOK
        if num_str in source_text:
            continue
            
        # 2. 単位変換による突合（アプローチB）
        val_rounded = round(val, 2)
        matched = False
        for src_val in source_values:
            if src_val == 0:
                continue
            if abs(val_rounded - src_val) / max(abs(src_val), 1.0) < 0.01:
                matched = True
                break
        if matched:
            continue
            
        unverified_nums.append(num_str)
            
    if unverified_nums:
        unverified_nums = sorted(list(set(unverified_nums)))
        # ユーザー指示により未確認タグの自動付加は完全廃止
        logger.debug(f"ソース未確認数値検出（タグ付加は行いません）: {unverified_nums}")
        return False, text
            
    return True, text



def verify_financial_index_accuracy(text: str) -> str:
    """
    【問題②対応】金融・市場指標数値ハルシネーション及び言い訳防止フィルター：
    VIX（恐怖指数）や株価・経済指標について推測値・不正確な安値省略を警告する。
    """
    if not text or not isinstance(text, str):
        return text

    # 例: VIX指数等の誤った数値言い切り・端折り言い訳に対する警告ログ発行
    if re.search(r'(VIX|恐怖指数)', text, re.IGNORECASE):
        # 明らかな自己正当化や言い訳の文言があれば是正
        text = re.sub(
            r'「52週安値圏.*?勝手に.*?省略・端折って表現してしもうたんや',
            r'事前の検索確認を怠り、古い・不正確な数値を推測で書いてしまいました',
            text
        )
    return text



def verify_actual_vs_guidance_hallucination(text: str, source_text: Optional[str] = None) -> str:
    """
    【問題③対応】実績と将来見通し（Guidance/Outlook）の混同ハルシネーション防衛壁：
    AIがソース内の「見通し・ガイダンス」の数値を誤って「当四半期の実績」等として断定してしまうことを防ぐ。
    具体的には、回答テキスト内で「実績」として提示されている数値が、ソース上では「expect」「guidance」等の
    予測マーカーと隣接している場合に警告フラグを挿入する。
    """
    if not text or not source_text or not isinstance(text, str) or not isinstance(source_text, str):
        return text

    # 回答テキストに既に「見通し」等の免責マーカーがある場合は、正常な併記である可能性が高いためスキップ
    hedge_markers = ["見通し", "予想", "ガイダンス", "見込み", "予測", "outlook", "guidance", "expect", "will"]
    if any(marker in text.lower() for marker in hedge_markers):
        return text

    # 実績を強く主張する文脈（実績、結果、着地、第〇四半期）があるかチェック
    actual_markers = [r"実績", r"結果", r"着地", r"Q[1-4]", r"第[一二三四1-4]四半期", r"売上高は", r"設備投資は"]
    actual_pattern = re.compile("|".join(actual_markers))
    
    if not actual_pattern.search(text):
        return text

    # 金融数値（$40B, 31.9 billion等）を抽出
    extracted_nums = _extract_monetary_values(text)
    if not extracted_nums:
        return text

    source_lower = source_text.lower()
    guidance_markers = ["expect", "guidance", "outlook", "forecast", "project", "will", "increase to", "見通し", "予想", "見込み", "計画"]

    warned_numbers = []

    for num_str, _ in extracted_nums:
        # num_str がソースのどこにあるか検索
        try:
            # 正規表現でエスケープして検索（$などの記号対応）
            pattern = re.compile(re.escape(num_str), re.IGNORECASE)
            for match in pattern.finditer(source_text):
                start = max(0, match.start() - 100)
                end = min(len(source_text), match.end() + 100)
                context_window = source_text[start:end].lower()
                
                # その数値の周囲に見通しマーカーが存在するか
                if any(gm in context_window for gm in guidance_markers):
                    warned_numbers.append(num_str)
                    break # この数値はガイダンスの可能性が高い
        except Exception as e:
            logger.debug(f"[ActualVsGuidanceDefense] 正規表現エラー: {e}")

    if warned_numbers:
        logger.warning(f"[ActualVsGuidanceDefense] 実績とガイダンスの混同ハルシネーションを検知しました: {warned_numbers}")
        warn_str = "、".join(set(warned_numbers))
        if "⚠️ **[実績・見通し混同の要確認" not in text:
            hedge_note = (
                f"\n\n⚠️ **[実績・見通し混同の要確認: 該当数値({warn_str})は次期以降のガイダンス/予測である可能性があります]**\n"
                "ソーステキスト上で上記数値の周辺に「見通し・予想・expect」等の表現が確認されました。過去の実績値と混同していないか、公式IRや元記事の文脈を再確認してください。"
            )
            text = text.rstrip() + hedge_note

    return text



_EARNINGS_TIMING_CLAIM_RE = re.compile(
    r"(?:"
    r"(?:日本時間|JST)\s*\d{1,2}/\d{1,2}\s*未明に(?:決算を)?発表(?:しています|した|済み)?"
    r"|"
    r"\d{1,2}/\d{1,2}\s*未明に(?:決算を)?発表(?:しています|した|済み)?"
    r"|"
    r"未明に(?:決算を)?発表(?:しています|した|済み)?"
    r"|"
    r"引け後に発表済み"
    r"|"
    r"引け後に(?:決算を)?発表(?:しています|した|済み)?"
    r")"
)

_TIMING_SOURCE_MARKERS = (
    "after the close",
    "after-hours",
    "after hours",
    "after close",
    "引け後",
    "時間外",
    "未明",
    "early morning",
    "reported",
    "results",
    "earnings release",
    "press release",
    "発表済み",
    "を発表した",
    "発表した",
)


def soften_ungrounded_earnings_timing(text: str, source_text: Optional[str] = None) -> str:
    """
    ソースに無い決算発表時刻（JST未明／引け後など）の断定をフレーズ単位で「要確認」化する。
    過剰除去を避けるため、時刻・発表タイミング句のみ置換する。
    """
    if not text or not isinstance(text, str):
        return text
    if not _EARNINGS_TIMING_CLAIM_RE.search(text):
        return text

    src_l = (source_text or "").lower()
    has_support = any(m in src_l for m in _TIMING_SOURCE_MARKERS) or any(
        m in (source_text or "") for m in ("未明", "引け後", "時間外", "発表済み", "を発表した", "発表した")
    )
    if has_support:
        return text

    def _soft(m: re.Match) -> str:
        logger.info("🧹 ソース未確認の決算発表時刻断定を緩和: %r", m.group(0))
        return "発表時刻はソース未確認"

    return _EARNINGS_TIMING_CLAIM_RE.sub(_soft, text)


_SESSION_IN_SOURCE_RE = re.compile(r"session=(preopen|morning|lunch|afternoon|closed)")


def correct_jp_session_price_labels(text: str, source_text: Optional[str] = None) -> str:
    """
    スナップショット session=morning/preopen/afternoon なのに『前場終値』『本日の終値』と書く誤認を直す。
    """
    if not text or not isinstance(text, str):
        return text
    m = _SESSION_IN_SOURCE_RE.search(source_text or "")
    if not m:
        return text
    session = m.group(1)
    out = text
    if session in ("morning", "preopen"):
        if "前場終値" in out:
            out = out.replace("前場終値", "直近値（前場取引中）")
            logger.info("🧹 場中の『前場終値』誤認を直近値へ置換")
        # 『本日の終値』『日経平均終値』など（前日終値は除外）
        out2 = re.sub(r"(?<!前)(?<!日)日経平均(?:の)?終値", "日経平均の直近値（取引中）", out)
        out2 = re.sub(r"本日の(?:大引け)?終値", "本日の直近値（取引中）", out2)
        if out2 != out:
            logger.info("🧹 場中の『終値』誤認を直近値へ置換")
            out = out2
    elif session == "afternoon":
        if re.search(r"本日の(?:大引け)?終値|大引け確定", out):
            out = re.sub(r"本日の(?:大引け)?終値", "本日の直近値（後場取引中）", out)
            out = out.replace("大引け確定", "後場取引中（終値未確定）")
            logger.info("🧹 後場中の『本日終値』誤認を緩和")
    return out


_NIGHT_FUTURES_START_CLAIM_RE = re.compile(
    r"(?:本日|今日)\d{0,2}日?夜間取引(?:（[^）]*）)?では[、,]?"
    r"[^。\n]{0,40}(?:でスタート|で始ま|寄り付)"
)


_US_MORNING_WRAP_RE = re.compile(
    r"Stock Market News for|Premarket Movers|Before the Stock Market Opens|"
    r"5 Things to Know Before|what to know before the",
    re.IGNORECASE,
)
_US_CLOSE_ARTICLE_RE = re.compile(
    r"Wall Street ends|stocks?\s+(?:end|close)|closing bell|"
    r"ends?\s+(?:sharply\s+)?(?:higher|lower|mixed)|closes?\s+(?:sharply\s+)?(?:higher|lower)",
    re.IGNORECASE,
)


def _strip_snapshot_meta_for_wrap_check(source_text: str) -> str:
    """スナップショット指示文（『Stock Market News for DATE』例示）を朝ラップ判定から除外。"""
    if not source_text:
        return ""
    # 米スナップショットブロック全体を落とす（指示文が誤検知トリガーになるため）
    cleaned = re.sub(
        r"【米国市場スナップショット[\s\S]*?(?=\n【|\n🔗|\n\[|$)",
        "\n",
        source_text,
    )
    # 残った指示フレーズ単体も除去
    cleaned = re.sub(
        r"『Stock Market News for DATE』|『Premarket』|『Before the Open』",
        "",
        cleaned,
    )
    return cleaned


def soften_us_morning_wrap_as_close(text: str, source_text: Optional[str] = None) -> str:
    """
    『Stock Market News for DATE』朝ラップの数値を DATE 終値として断定する誤認を緩和する。
    引け後記事と矛盾する大幅下落断定には要確認注記を付与。
    """
    if not text or not isinstance(text, str):
        return text
    src = _strip_snapshot_meta_for_wrap_check(source_text or "")
    if not _US_MORNING_WRAP_RE.search(src):
        return text

    has_close_article = bool(_US_CLOSE_ARTICLE_RE.search(src))
    claims_close = bool(re.search(r"の終値|で終了|で引け|終値）", text))
    if not claims_close:
        return text

    # 当日終値を下落断定しているか（「前日の大幅下落」は除外）
    today_close_down = bool(
        re.search(
            r"(?<!前日)(?<!前営業日)(?<!前夜)(?<!前日の)(?<!前営業日の)"
            r"(?:大幅下落|急落|安で終了|安で引け|ポイント安で終了)",
            text,
        )
        or re.search(r"(?:本日|今日|7/\d+|7月\d+日).{0,40}(?:大幅下落|急落|安で終了|安で引け)", text)
    )
    wrap_down_in_src = bool(
        re.search(
            r"(?:Stock Market News for|Premarket Movers).{0,200}"
            r"(?:down|fall|fell|drop|dropped|sank|plunge|%安|ポイント安)",
            src,
            re.I | re.S,
        )
    )
    close_up = bool(re.search(r"ends?\s+(?:sharply\s+)?higher|closes?\s+higher|大幅高", src, re.I))

    if has_close_article and today_close_down and wrap_down_in_src and close_up:
        note = (
            "\n\n⚠️ **[終値日付の要確認]** 『Stock Market News for DATE』等の朝記事は"
            "前日終値の要約であることが多い。引け後の『Wall Street ends…』記事と"
            "スナップショットの as_of 日付を優先して照合してください。"
        )
        if "終値日付の要確認" not in text:
            logger.info("🧹 米朝ラップと引け後記事の終値矛盾を注記")
            text = text.rstrip() + note
        return text

    if not has_close_article and today_close_down and re.search(r"(?:確定)?終値|で終了|で引け", text):
        text2 = re.sub(
            r"(?<!前)(?<!日)(?<!の要確認】『)終値",
            "終値（朝記事由来・前日終値の可能性）",
            text,
            count=4,
        )
        if text2 != text:
            logger.info("🧹 米朝ラップのみの『終値』断定を緩和")
            text = text2
    return text


def soften_stale_night_futures_claims(text: str, source_text: Optional[str] = None) -> str:
    """
    朝の『夜間取引終値/0時』記事を、夕方に『本日夜間がスタート』と誤読する断定を緩和する。
    """
    if not text or not isinstance(text, str):
        return text
    if not _NIGHT_FUTURES_START_CLAIM_RE.search(text):
        return text
    src = source_text or ""
    # ソースに早朝・0時の夜間終値痕跡があり、今夜寄り直後の裏付けが薄い
    stale_morning = bool(
        re.search(r"夜間取引終値|0時＝|0時=|05?:|06?:", src)
        or re.search(r"夜間取引終値|0時", text)
    )
    fresh_evening = bool(
        re.search(r"(?:16|17|18|19|20|21)[:：時]", src)
        and re.search(r"先物|夜間", src)
    )
    if stale_morning and not fresh_evening:
        def _soft(m: re.Match) -> str:
            logger.info("🧹 古い夜間先物を『今夜スタート』とする誤認を緩和: %r", m.group(0)[:60])
            return "直前の夜間セッション終値（朝時点の参考値・今夜のスタート水準ではない）として"

        return _NIGHT_FUTURES_START_CLAIM_RE.sub(_soft, text)
    return text


def check_financial_arithmetic_consistency(text: str) -> str:
    """
    株価・指数に関する記述で、同一回答内における価格差と変動幅の算術的矛盾を検知・警告する。
    例: 安値66,653円・寄り68,410円（差額1,757円）とあるのに「一時2,500円超下落」のように矛盾する数値が記載されている場合。
    """
    if not text:
        return text

    # 日経平均等の数値が複数あり、さらに「〇〇円（超）下落/安」などの変動幅があるかチェック
    drop_match = re.search(r'一時([0-9,]+)円(?:超|余り)?(?:下落|安)', text)
    if not drop_match:
        return text

    try:
        drop_claimed = int(drop_match.group(1).replace(",", ""))
        # 5万〜8万円帯の日経平均価格候補を取得
        prices = [int(p.replace(",", "")) for p in re.findall(r'(6[0-9],[0-9]{3}|7[0-9],[0-9]{3}|5[0-9],[0-9]{3})円', text)]
        if len(prices) >= 2:
            max_diff = max(prices) - min(prices)
            # 実際の価格レンジ差と主張された一時下落幅が500円以上の乖離を持つ場合にアラート
            if drop_claimed > max_diff + 500 and "※【数値整合性アラート】" not in text:
                logger.warning(f"[FinancialDefense] 算術不整合検知: 価格帯差額 {max_diff}円 vs 主張下落幅 {drop_claimed}円")
                text = text.rstrip() + f"\n\n※【数値整合性アラート】文中で言及された価格帯の差額（約{max_diff:,}円）と、一時変動幅（{drop_claimed:,}円）の間に算術的な乖離が生じています。各時間帯の公式取引データをご確認ください。"
    except Exception as e:
        logger.debug(f"[FinancialDefense] 算術チェック時スキップ: {e}")

    return text

