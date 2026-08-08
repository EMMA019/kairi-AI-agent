import re
from app.utils.logger import get_logger

logger = get_logger(__name__)

try:
    from janome.tokenizer import Tokenizer
    tokenizer = Tokenizer()
except ImportError:
    logger.warning("janome がインストールされていません。固有名詞の判定がスキップされます。")
    tokenizer = None

SEARCH_TRIGGERS = {
    "temporal": ["最新", "現在", "今", "今日", "今年", "最近", "先週", "先月", "今月"],
    "factual":  ["いくら", "何円", "何時", "何日", "何人", "何%", "何パーセント"],
    "explicit": ["調べて", "検索して", "ニュース", "株価", "為替", "天気"],
}

def has_proper_noun_or_english(text: str) -> bool:
    """
    英語（ティッカーシンボル等）や固有名詞が含まれているか判定する。
    """
    # 英語（アルファベット）が含まれていれば、ティッカーや英単語として固有名詞とみなす
    if re.search(r'[A-Za-z]+', text):
        return True
        
    # Janomeを使った固有名詞判定
    if tokenizer:
        for token in tokenizer.tokenize(text):
            pos = token.part_of_speech.split(',')
            if pos[0] == '名詞' and pos[1] == '固有名詞':
                return True
    return False

def should_search(user_input: str) -> bool:
    """
    ルールベースでの強制検索トリガー判定（モデルの自己判断に依存しない）
    フェーズ2: 形態素解析を用いて、固有名詞がない日常会話では無駄な検索を行わないよう改善
    """
    # 1. 確実に検索が必要な明示的キーワード（「〜調べて」「ニュース」など）
    if any(kw in user_input for kw in SEARCH_TRIGGERS["explicit"]):
        return True
        
    # 2. 時間的・事実的キーワードが含まれている場合
    has_temporal = any(kw in user_input for kw in SEARCH_TRIGGERS["temporal"])
    has_factual = any(kw in user_input for kw in SEARCH_TRIGGERS["factual"])
    has_date_pattern = bool(re.search(r'\d{4}年|\d+月|\d+日|¥\d+|\$\d+', user_input))
    
    if has_temporal or has_factual or has_date_pattern:
        # 単なる「今から寝る」「これいくら？」などの雑談を弾くため、
        # 固有名詞や英語が含まれている場合のみ検索を実行する
        if has_proper_noun_or_english(user_input):
            return True
            
    return False
