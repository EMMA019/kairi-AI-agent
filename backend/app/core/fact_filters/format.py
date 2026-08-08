import re
from datetime import date, timedelta
from typing import Optional
from app.utils.logger import get_logger
from app.core.source_evaluator import verify_entity_claim_attribution

logger = get_logger(__name__)



def correct_common_typos(text: str) -> str:
    """
    進行形で発生するLLMのカタカナタイポや、Web検索・OCRの文字化け（例: リーム→リスク）を
    出力直前に自動検知・補正するフィルター。
    """
    if not text or not isinstance(text, str):
        return text
    
    # 1. 致命的な「リーム」タイポ（リスクの文字化け・ハルシネーション誤変換）の自動置換
    risk_typo_pattern = re.compile(
        r'(未入金|倒産|連鎖|信用|資金|回収|為替|市場|経営|流動性|セキュリティ|サイバー|価格|破綻|デフォルト|金利|インフレ|デフレ|カントリー|システミック|取引|運用|風評|法的|コンプライアンス|オペレーショナル|地政学|事故|災害|システム|情報漏洩|紛失|障害|遅延|契約|炎上|悪化|低迷|急落|急騰|凍結|焦げ付き)リーム'
    )
    text = risk_typo_pattern.sub(r'\1リスク', text)
    
    # 「リスク」と書くべき文脈で「〇〇のリーム」等もフォロー
    text = re.sub(r'(未入金|倒産|連鎖|信用|資金|回収|為替|市場|経営|破綻|漏洩|障害)(?:の|や|と|における|による|に伴う|に関する)リーム', r'\1の可能性・リスク', text)
    
    # さらに単独で「未入金リーム」「連鎖倒産リーム」にヒットするように念押し
    text = text.replace("未入金リーム", "未入金リスク")
    text = text.replace("倒産リーム", "倒産リスク")
    text = text.replace("連鎖倒産リーム", "連鎖倒産リスク")
    
    # 2. 頻出カタカナ・IT用語タイポ補正
    common_typo_map = [
        (re.compile(r'シシテム|シテスム|シスエム'), 'システム'),
        (re.compile(r'プローグラム|プログム'), 'プログラム'),
        (re.compile(r'コミニュケーション'), 'コミュニケーション'),
        (re.compile(r'シュミレーション|シムレーション'), 'シミュレーション'),
    ]
    for pat, rep in common_typo_map:
        text = pat.sub(rep, text)
        
    return text



def clean_broken_markdown_tables(text: str) -> str:
    """
    未完成・破綻マークダウン表（|------|------|等）のクリーンアップフィルター：
    テーブルの区切り線だけ出力されて直前に表ヘッダーがない孤立行や、
    データ行が存在しない壊れた表罫線をクリーンアップする。
    """
    if not text or not isinstance(text, str):
        return text

    lines = text.splitlines()
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if re.match(r'^\|[\s:-]+\|([\s:-]+\|)+$', stripped):
            if cleaned and cleaned[-1].strip().startswith('|'):
                cleaned.append(line)
            else:
                logger.warning(f"🚨 データのない孤立マークダウン表罫線を検知・除去しました: {stripped}")
                continue
        else:
            cleaned.append(line)
    return "\n".join(cleaned)



DEFAULT_MEMORY_PROJECT_KEYWORDS = [
    "顔写真保護",
    "顔写真保護アプリ",
    "写真保護アプリ",
]

# 「Naoさんの趣味（競馬、サッカー、猫など）」のような無断パーソナライズ文
_HOBBY_PERSONALIZATION_RE = re.compile(
    r"(趣味|好み|嗜好|好きなもの)[（(][^）)]{2,40}[）)]"
    r"|(?:競馬|サッカー|猫).{0,12}(?:趣味|好き)"
    r"|(?:趣味|好き).{0,12}(?:競馬|サッカー|猫)"
)


def strip_omakase_skill_questions(
    text: str,
    user_input: Optional[str] = None,
) -> str:
    """おまかせ開発依頼なのにスキル確認を聞き返す文を除去する。"""
    if not text or not isinstance(text, str):
        return text
    try:
        from app.core.omakase_policy import (
            contains_forbidden_skill_question,
            is_omakase_dev_request,
        )
    except Exception:
        return text
    if not is_omakase_dev_request(user_input or ""):
        return text
    if not contains_forbidden_skill_question(text):
        return text

    sentences = re.split(r'(?<=[。！？\n])', text)
    kept = []
    for s in sentences:
        if contains_forbidden_skill_question(s):
            logger.warning(f"おまかせ後のスキル確認質問を自動削除: {s[:60]}...")
            continue
        kept.append(s)
    cleaned = "".join(kept).strip()
    return cleaned if cleaned else text


def strip_unrequested_memory_mentions(
    text: str,
    user_input: Optional[str] = None,
    memory_keywords: Optional[list[str]] = None,
) -> str:
    """
    記憶参照違反・過去プロジェクト無断適用の自動クリーニング：
    ユーザーの直近の質問・指示（user_input）に含まれていない過去プロジェクトや
    趣味パーソナライズ（競馬・サッカー・猫等）を AI が引き合いに出した場合に除去する。
    """
    if not text or not isinstance(text, str):
        return text

    keywords = list(memory_keywords or DEFAULT_MEMORY_PROJECT_KEYWORDS)
    user_text = str(user_input or "")

    # 明示的な記憶利用許可があるときは趣味パーソナライズ除去をスキップ
    try:
        from app.core.memory_policy import user_allows_memory_use
        memory_allowed = user_allows_memory_use(user_text)
    except Exception:
        memory_allowed = False

    if any(kw in user_text for kw in keywords) and memory_allowed:
        return text

    active_keywords = [kw for kw in keywords if kw not in user_text]

    paragraphs = re.split(r'(\r?\n\r?\n)', text)
    cleaned_paragraphs = []

    for p in paragraphs:
        if active_keywords and any(kw in p for kw in active_keywords):
            logger.debug(f"記憶参照違反（無関係な過去プロジェクト言及）を自動削除: {p[:50]}...")
            continue
        if not memory_allowed and _HOBBY_PERSONALIZATION_RE.search(p):
            hobby_terms = [t for t in ("競馬", "サッカー", "猫") if t in p and t not in user_text]
            if hobby_terms or "趣味（" in p or "趣味(" in p:
                # 段落全体ではなく、違反文だけを除去して有用な文は残す
                sentences = re.split(r'(?<=[。！？\n])', p)
                kept = []
                for s in sentences:
                    if _HOBBY_PERSONALIZATION_RE.search(s) and (
                        any(t in s and t not in user_text for t in ("競馬", "サッカー", "猫"))
                        or "趣味（" in s
                        or "趣味(" in s
                    ):
                        logger.warning(f"記憶参照違反（無断趣味パーソナライズ）を自動削除: {s[:60]}...")
                        continue
                    kept.append(s)
                p = "".join(kept).strip()
                if not p:
                    continue
        cleaned_paragraphs.append(p)

    cleaned_text = "".join(cleaned_paragraphs).strip()
    return cleaned_text if cleaned_text else text



DEFAULT_FINANCIAL_USER_KEYWORDS = [
    "株", "銘柄", "株価", "相場", "配当", "決算", "投資", "ティッカー", "為替", "FX",
    "市況", "日経", "ダウ", "ナスダック", "S&P", "証券", "チャート", "金利", "中央銀行",
    "stock", "share", "ticker", "dividend", "earnings", "invest", "market"
]



def strip_unrequested_yahoo_finance(
    text: str,
    user_input: Optional[str] = None,
    financial_keywords: Optional[list[str]] = None,
) -> str:
    """
    非金融・一般トレンド質問時のYahoo Finance末尾案内誤付与の自動除去：
    ユーザーの質問（user_input）が株式・銘柄・投資に関するものでない場合（一般的なトレンドやニュース等）、
    AIが末尾に付与した Yahoo Finance への定型誘導・リンク行を自動削除する。
    """
    if not text or not isinstance(text, str):
        return text

    keywords = financial_keywords or DEFAULT_FINANCIAL_USER_KEYWORDS
    user_text = str(user_input or "")

    # ユーザーが金融・株価・銘柄について明確に質問している場合は削除しない
    if any(kw in user_text for kw in keywords):
        return text

    paragraphs = re.split(r'(\r?\n\r?\n)', text)
    cleaned_paragraphs = []

    for p in paragraphs:
        if ("Yahoo Finance" in p or "finance.yahoo.com" in p) and ("📊" in p or "最新のチャート" in p or "市場データ" in p):
            logger.debug("非金融質問への回答末尾から不必要なYahoo Finance案内を自動削除しました")
            continue
        cleaned_paragraphs.append(p)

    cleaned_text = "".join(cleaned_paragraphs).strip()
    return cleaned_text if cleaned_text else text



_TERMINAL_CHARS = set("。．！？!?…‼⁉」』）)]\"'”’")
_TOOL_PROMISE_CORE = (
    r"(?:まず[、,]?)?(?:残りの)?(?:主要(?:指数)?)?(?:指数)?(?:データ|情報|記事|詳細)を"
    r"(?:取得|検索|確認|調べ)(?:し(?:ます|て(?:き|まい)|ますね)|する(?:わ|ね|よ)?)"
)
_TOOL_PROMISE_PATTERN = re.compile(
    r"(?:"
    + _TOOL_PROMISE_CORE
    + r"|(?:検索|スクレイピング|データ取得)(?:して|しに)(?:き|まい)(?:ます|る)(?:ね|よ|わ)?"
    r"|(?:少々|少し)?お待ちください"
    r")[。．！!…]*\s*$"
)


def _is_protected_trailing_line(line: str) -> bool:
    """コードブロック・表・箇条書き・見出しは文末トリム対象外。"""
    stripped = line.strip()
    if not stripped:
        return True
    if stripped.startswith("```") or stripped.startswith("|"):
        return True
    if re.match(r"^#{1,6}\s+", stripped):
        return True
    if re.match(r"^[-*+]\s+", stripped) or re.match(r"^\d+[.)]\s+", stripped):
        return True
    return False


def _ends_with_valid_terminal(text: str) -> bool:
    """正当な終端文字・絵文字・コードブロック閉じで終わっているか。"""
    s = text.rstrip()
    if not s:
        return True
    if s.endswith("```"):
        return True
    last = s[-1]
    if last in _TERMINAL_CHARS:
        return True
    # 末尾が絵文字（簡易: サロゲートペア / 一般的な絵文字範囲）
    if ord(last) >= 0x1F300 or (0x2600 <= ord(last) <= 0x27BF):
        return True
    # 結合絵文字の最終コードポイント
    if len(s) >= 2 and 0xFE0F == ord(last):
        return True
    return False


def trim_incomplete_trailing_sentence(text: str) -> str:
    """
    句読点・！？等で終わらない不完全な末尾文をシステマチックに刈り取る。
    コードブロック・表・箇条書き・見出しは保護。切り戻しが全文の50%超なら適用しない。
    """
    if not text or not isinstance(text, str):
        return text

    original = text
    text = text.rstrip()
    if not text:
        return original.rstrip() if original.endswith(("\n", " ")) else text

    # 未閉じコードフェンスは終端文字チェックより先に処理
    if text.count("```") % 2 == 1:
        lines = text.splitlines()
        if len(lines) >= 2:
            last = lines[-1].rstrip()
            if last and not last.startswith("```"):
                body = "\n".join(lines[:-1]).rstrip()
                if body.count("```") % 2 == 1:
                    body = body + "\n```"
                if body and len(body) >= len(text) * 0.35:
                    logger.info(f"✂️ 未閉じコードフェンス末尾を刈り取り: {last[:40]!r}")
                    return body
        return text

    if _ends_with_valid_terminal(text):
        return original.rstrip() if original.endswith(("\n", " ")) else text

    lines = text.splitlines()
    if not lines:
        return text

    last_line = lines[-1]
    # コードっぽい途中切れ行は保護対象外
    if re.search(r"[=+\-*/(<\[{]\s*$", last_line.rstrip()) or re.match(
        r"^[A-Za-z_][A-Za-z0-9_]*$", last_line.strip()
    ):
        pass
    elif _is_protected_trailing_line(last_line):
        return text

    # 末尾行内で最後の正当終端位置を探す
    cut_pos = -1
    for i in range(len(text) - 1, -1, -1):
        if text[i] in _TERMINAL_CHARS:
            # その位置以降が未保護の不完全文か確認
            remainder = text[i + 1 :].strip()
            if remainder and not _is_protected_trailing_line(remainder.splitlines()[0] if remainder.splitlines() else ""):
                cut_pos = i + 1
                break
            # 終端そのもので終わっているなら完結
            if not remainder:
                return text

    if cut_pos <= 0:
        # 終端文字が一切ない → 末尾行全体を落とす（複数行ある場合のみ）
        if len(lines) >= 2:
            trimmed = "\n".join(lines[:-1]).rstrip()
            if trimmed and len(trimmed) >= len(text) * 0.5:
                logger.info(f"✂️ 不完全末尾行を除去: {last_line[:40]!r}")
                return trimmed
        return text

    trimmed = text[:cut_pos].rstrip()
    if not trimmed:
        return text
    if len(trimmed) < len(text) * 0.5:
        logger.info("✂️ 文末トリムを安全弁によりスキップ（50%超の削除）")
        return text

    removed = text[cut_pos:].strip()
    if removed:
        logger.info(f"✂️ 不完全末尾文を刈り取り: {removed[:60]!r}")
    return trimmed


def strip_dangling_tool_promises(text: str) -> str:
    """
    ツール実行予告で終わる末尾文を除去する。
    例: 「まず、残りの主要指数データを取得します。」
    改行が潰れて同一行になっていても、末尾の予告文だけを刈り取る。
    """
    if not text or not isinstance(text, str):
        return text

    # 末尾のツール予告文のみ除去（先行文は必ず残す）
    trailing_promise = re.compile(
        r"(?:(?<=[。．！？!?\n])|^)\s*"
        + _TOOL_PROMISE_CORE
        + r"[。．！!…]*\s*$"
    )
    new_text, n = trailing_promise.subn("", text)
    if n:
        logger.info("✂️ ツール実行予告の末尾文を除去しました")
        return new_text.rstrip()

    # 予告文だけの短文（他の文が無い）なら全体を除去
    stripped = text.strip()
    if _TOOL_PROMISE_PATTERN.fullmatch(stripped):
        logger.info(f"✂️ ツール実行予告のみの応答を除去: {stripped[:50]!r}")
        return ""
    return text


def strip_excuse_hallucinations(text: str) -> str:
    """
    自己正当化・言い訳ハルシネーション除去フィルター（動詞ベース包括版）：
    「〇〇と混同した」「〇〇と勘違いした」「〇〇の日程を取り違えた」等の
    事実無根な弁明文章を動詞パターンで包括的に検知・除去する。
    """
    if not text or not isinstance(text, str):
        return text

    lines = text.splitlines()
    cleaned = []
    excuse_patterns = [
        # 動詞ベース包括パターン（「〜と混同」「〜と勘違い」「〜を取り違え」等）
        re.compile(r'.*(?:と混同(?:し(?:てしまい|まし)|した)|と勘違い(?:し(?:てしまい|まし)|した)|を取り違え(?:てしまい|まし|た)|を誤って適用|の日程と間違え).*', re.IGNORECASE),
        # セクション見出しパターン（「誤りの原因について」等）
        re.compile(r'^[\s*#-]*(?:誤りの原因|間違いの原因|混同の原因|誤認の理由)(?:について)?.*', re.IGNORECASE),
        # 弁明構文パターン（「これは〇〇を〇〇したものです」）
        re.compile(r'.*これは.*(?:混同|勘違い|取り違え|誤認).*(?:したもの|によるもの).*', re.IGNORECASE),
    ]
    for line in lines:
        stripped = line.strip()
        if any(pat.match(stripped) for pat in excuse_patterns):
            logger.info(f"🧹 言い訳ハルシネーション行を除去しました: {stripped}")
            continue
        cleaned.append(line)
    return "\n".join(cleaned)


_FALSE_ATTR_PHRASE_RE = re.compile(
    r"(ご指摘いただいた通り|ご指摘の通り|おっしゃる通り|おっしゃるとおり|"
    r"仰る通り|仰るとおり|ご案内の通り|ご案内のとおり)"
    r"(?:です)?"  # 「おっしゃる通りです」ごと消さないと「Nao、です」が残る
    r"[、,]?\s*"
)

# 誤帰属判定用: ユーザー発話に無いと「ご指摘の通り」が不正になりやすい固有主張
_CLAIM_TOKEN_PATTERNS = [
    re.compile(r"\d{1,2}/\d{1,2}"),
    re.compile(r"\d{1,2}月\d{1,2}日"),
    re.compile(r"未明"),
    re.compile(r"引け後"),
    re.compile(r"アフターアワー"),
    re.compile(r"after[\s-]?hours?", re.IGNORECASE),
    re.compile(r"日本時間"),
    re.compile(r"JST", re.IGNORECASE),
]


def _extract_claim_tokens(fragment: str) -> list[str]:
    tokens: list[str] = []
    for pat in _CLAIM_TOKEN_PATTERNS:
        tokens.extend(pat.findall(fragment))
    # findall がタプルを返すことはないが、念のため正規化
    return [t if isinstance(t, str) else t[0] for t in tokens if t]


def _repair_broken_attribution_opener(text: str) -> str:
    """誤帰属除去後の『Nao、です。』『Nao、。』『、です。』を修復する。"""
    if not text:
        return text
    # 名前＋壊れた同意オープナー行頭 → 中立挨拶
    text = re.sub(
        r"(^|\n)\s*[A-Za-zぁ-んァ-ン一-龥]{1,24}、(?:です)?[。．]\s*",
        r"\1",
        text,
    )
    text = re.sub(r"、です([。．])", r"\1", text)
    text = re.sub(r"、。", "。", text)
    return text


def strip_false_user_attribution(text: str, user_input: str = "") -> str:
    """
    ユーザーが言っていない内容を「ご指摘いただいた通り／おっしゃる通り」で回収する誤帰属を除去する。
    後続文の固有主張（日付・未明・引け後等）が user_input に無いときだけフレーズを置換する。
    """
    if not text or not isinstance(text, str):
        return text
    if not _FALSE_ATTR_PHRASE_RE.search(text):
        return text

    user = user_input or ""
    neutral = "検索結果によれば、"

    def _replace(match: re.Match) -> str:
        # マッチ以降〜文末（。！？または改行）までを主張断片とみなす
        tail = text[match.end() :]
        end_m = re.search(r"[。！？\n]", tail)
        fragment = tail[: end_m.start()] if end_m else tail[:160]
        claim_tokens = _extract_claim_tokens(fragment)

        if claim_tokens:
            # いずれかの固有主張がユーザー文にあれば、本当に指摘された可能性 → 残す
            if any(tok.lower() in user.lower() for tok in claim_tokens):
                return match.group(0)
            logger.info(
                "🧹 ユーザー誤帰属フレーズを中立化しました: %r (claims=%s)",
                match.group(1),
                claim_tokens,
            )
            return neutral

        # 固有主張が無い場合でも、ユーザーが指摘・同意文脈を書いていなければ除去
        user_ack = any(
            k in user for k in ("指摘", "だよね", "でしょ", "だろ", "通り", "よね？", "よね?")
        )
        if user_ack:
            return match.group(0)
        logger.info("🧹 ユーザー誤帰属フレーズを除去しました: %r", match.group(1))
        return ""

    cleaned = _FALSE_ATTR_PHRASE_RE.sub(_replace, text)
    # 「、」が二重になったり先頭カンマが残るのを軽く整える
    cleaned = re.sub(r"^[、,\s]+", "", cleaned)
    cleaned = re.sub(r"([。！？\n])[、,\s]+", r"\1", cleaned)
    cleaned = _repair_broken_attribution_opener(cleaned)
    return cleaned

