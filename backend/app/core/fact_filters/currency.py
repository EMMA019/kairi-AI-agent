import re
from datetime import date, timedelta
from typing import Optional
from app.utils.logger import get_logger
from app.core.source_evaluator import verify_entity_claim_attribution

logger = get_logger(__name__)



# ==============================================================================
# Nao路線：構造的ファクトバリデーション＆数値・為替強制制御（Structural Enforcement）
# ==============================================================================

# 公式固定/参照為替レート（計算誤りやレート矛盾を排除するためコード側で一元管理）
OFFICIAL_EXCHANGE_RATES_JPY = {
    "EUR": 175.0,  # ユーロ
    "GBP": 205.0,  # ポンド
    "USD": 155.0,  # ドル
}

# 勝手な「外貨→円」換算の除去対象。兆/億/万付きの大口換算のみ。
# ※ `(?:兆|億|万)?` を optional にすると `1ドル＝162円台` のスポットまで消え
#   `1ドル台後半` になる（実害再現済み）。
_NUM = r"\d+(?:,\d+)*(?:\.\d+)?"
_LARGE_JPY_AMT = (
    rf"(?:日本円(?:にして|で)?)?\s*約?\s*"
    rf"(?:"
    rf"{_NUM}\s*兆(?:\s*{_NUM})?\s*(?:億|万)?\s*"  # 1兆 / 1兆500億
    rf"|"
    rf"{_NUM}\s*(?:億|万)\s*"  # 237億 / 5700万
    rf")"
    rf"円(?:相当)?"
)
_RE_JPY_CONV_PAREN = re.compile(rf"[（\(]\s*{_LARGE_JPY_AMT}\s*[）\)]")
_RE_JPY_CONV_EQ = re.compile(rf"(?:＝|=)\s*{_LARGE_JPY_AMT}")
_RE_FX_OTHER_PAREN = re.compile(
    r"[（\(]\s*(?:約|＝|=)?\s*\d+(?:,\d+)*(?:\.\d+)?\s*(?:兆|億|万)\s*"
    r"(?:ユーロ|ドル|ポンド|EUR|USD|GBP)(?:相当)?\s*[）\)]"
)
_RE_FX_OTHER_EQ = re.compile(
    r"(?:＝|=)\s*(?:約)?\s*\d+(?:,\d+)*(?:\.\d+)?\s*(?:兆|億|万)\s*"
    r"(?:ユーロ|ドル|ポンド|EUR|USD|GBP)(?:相当)?"
)


def strip_unauthorized_jpy_conversions(text: str) -> str:
    """外貨記事に勝手に付けた大口円換算を除去。ドル円スポット（＝162円台）は残す。"""
    if not text:
        return text
    if not any(
        cur in text
        for cur in ["ポンド", "ユーロ", "ドル", "GBP", "EUR", "USD", "£", "€", "$", "ポンド台", "ドル台"]
    ):
        return text
    text = _RE_JPY_CONV_PAREN.sub("", text)
    text = _RE_JPY_CONV_EQ.sub("", text)
    text = _RE_FX_OTHER_PAREN.sub("", text)
    text = _RE_FX_OTHER_EQ.sub("", text)
    text = re.sub(r"[^\S\r\n]{2,}", " ", text)
    return text


def check_currency_consistency(text: str) -> tuple[bool, str]:
    """
    内部整合性チェック（複数通貨換算の相互検算）：
    回答内に2つ以上の為替換算や金額表記が出てきた場合、それぞれの暗黙レートを検知し、
    矛盾（例: 167円/ポンドと100円/ポンドの混在）があれば自動警告フラグを立てる。
    """
    text = strip_unauthorized_jpy_conversions(text)

    gbp_100m_bug = re.search(r"1億ポンド.*?100億円|100億円.*?1億ポンド", text)
    eur_pound_mix = re.search(r"(?:ユーロ|EUR|€).*?(?:ポンド|GBP|£)|(?:ポンド|GBP|£).*?(?:ユーロ|EUR|€)", text)
    
    warnings = []
    if gbp_100m_bug:
        warnings.append("⚠️ **【為替換算レート不整合エラー】** 1億ポンドを100億円とするような実レート（約200円/£）と乖離した計算が検知されました。為替換算はLLM推論ではなく公式レート計算を優先してください。")
    if eur_pound_mix and any(w in text for w in ["誤認", "取り違え", "注意", "誤り", "違い", "比較", "訂正", "ではなく"]):
        pass
    elif eur_pound_mix and "ユーロ" in text and "ポンド" in text:
        warnings.append("⚠️ **【通貨単位混在注意】** ユーロ(€)とポンド(£)が同一文章内で混在しています。元のソース単位をご確認ください。")
        
    if warnings:
        warning_str = "\n\n".join(warnings)
        if warning_str not in text:
            return False, f"{text}\n\n{warning_str}"
            
    return True, text



def convert_and_normalize_currency(amount: float, currency: str) -> str:
    """
    為替換算はLLMにやらせない：
    外部API/固定レートを通した確実な算術換算のみを実行し、文字列として返す。
    """
    rate = OFFICIAL_EXCHANGE_RATES_JPY.get(currency.upper(), 160.0)
    jpy_val = amount * rate
    if jpy_val >= 10000:
        oku = jpy_val / 10000
        return f"約{oku:.1f}億円（公式換算レート: 1{currency}={rate}円計算）"
    else:
        return f"約{jpy_val:,.0f}万円（公式換算レート: 1{currency}={rate}円計算）"

