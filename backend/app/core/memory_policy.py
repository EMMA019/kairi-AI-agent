"""
KVメモリの保存・参照ポリシー（「記憶を勝手に使わない」の機械ゲート）

プロンプトだけの注意書きでは DeepSeek が無視するため、ここを正としてコード側で拒否する。
"""
from __future__ import annotations

import re
from typing import Any, Optional

# 明示的な「記憶を使ってよい」指示
_MEMORY_USE_PATTERNS = [
    r"記憶を使",
    r"記憶を参照",
    r"記憶に基づ",
    r"過去の相談を踏ま",
    r"過去の(?:話|相談|会話|プロジェクト)を",
    r"前の(?:話|相談|約束)を踏ま",
    r"覚えてる[？?]?",
    r"覚えてますか",
    r"覚えてるかな",
    r"前に話した",
    r"以前(?:話|相談)した",
    r"私の(?:好み|趣味|プロフィール|好みに合わせ)",
    r"俺の(?:好み|趣味)",
    r"僕の(?:好み|趣味)",
    r"KVメモリ",
    r"長期記憶",
]

# 明示的な「保存して」指示
_MEMORY_SAVE_PATTERNS = [
    r"覚えておいて",
    r"覚えといて",
    r"覚えていて",  # 覚えていてほしい/ください/ね を包含
    r"覚えてほしい",
    r"覚えてね",
    r"覚えてて",
    r"記憶しておいて",
    r"記憶して(?:ください|くれ|て|ほしい)",
    r"メモして",
    r"メモっといて",
    r"記録して",
    r"忘れないで",
    r"忘れんといて",
    r"remember\s+(?:this|that|it)",
    r"please\s+remember",
]

# ペルソナ変更（カテゴリ persona のみ許可）
_PERSONA_PATTERNS = [
    r"ギャルモード",
    r"関西弁にして",
    r"子供口調",
    r"ペルソナ",
    r"口調にして",
    r"モードにして",
    r"モードON",
    r"アナリストモード",
]

# 忘却・除外
_FORGET_PATTERNS = [
    r"忘れて",
    r"忘れろ",
    r"記憶から消",
    r"記憶を消",
    r"削除して",
    r"もう覚えないで",
]

# 会話メタ・ニュース・AI自己紹介など「ユーザーの長期特徴」ではないゴミ
_JUNK_TARGET_RE = re.compile(
    r"("
    r"画像|写真|selfie|リクエスト|エラー|API|"
    r"移籍|サッカー|プレミア|トッテナム|チェルシー|リバプール|"
    r"マンチェスター|日本人選手|カルパナ|キングジョージ|競馬|"
    r"アシスタント|キャラクター|カイリ|かいり|応答|会話の流れ|"
    r"ソース|出典|検索結果|ニュース|ディール|"
    r"本日の|今日の食事|夕飯|カレーの写真|海の写真|学校の写真|"
    r"過去の話題|ユーザーの反応|動作背景|運用状況|"
    r"Morph|DeepSeek|MiniMAX|GLM-|Gemini|OpenRouter|Kimi|マルチプロバイダ|"
    r"開発依頼|方向性|現状|参考ソース|収益化|意図変更|投資手段|"
    r"ジタン|ゴロワーズ|Gitanes|アルファベット株|"
    # 市場・指標のエフェメラル要約（圧縮/会話由来）
    r"日経|TOPIX|前場|後場|終値|始値|業種|セクター|半導体|"
    r"銀行セクター|金融セクター|FOMC|日銀|金融政策|"
    r"Microsoft決算|MSFT決算|SKハイニックス|原油|為替・金利|"
    r"支援材料|懸念材料|今後の注目|注目イベント|"
    # 会話メタ・未完了タスクメモ
    r"ユーザーの追加質問|未回答|最終指示|改善方針|改善点|"
    r"ユーザー最終要求|ユーザーからのフィードバック|実運用に向けた方向性|"
    r"ペアトレード|改良(?:版)?コード|学術リソース"
    r")",
    re.IGNORECASE,
)

_EPHEMERAL_KV_TAGS = {"一時データ", "スキャン結果"}

# quote がユーザー発言の引用でないとき（AIが要約を quote にしている）
_QUOTE_IS_META_RE = re.compile(
    r"^(ユーザー|アシスタント|AI|カイリ|過去の|画像|会話)",
)


def user_allows_memory_use(user_input: str) -> bool:
    """明示的に記憶参照を許可したか。『おまかせ』は許可にならない。"""
    text = (user_input or "").strip()
    if not text:
        return False
    return any(re.search(p, text, re.IGNORECASE) for p in _MEMORY_USE_PATTERNS)


# 保有・ポジション文脈（ニュース質問だけでは inject しない）
_HOLDINGS_CONTEXT_RE = re.compile(
    r"保有|ポジション|含み|取得価|何株|自分の銘柄|ポートフォリオ|持ってる株|持株"
)


def user_in_holdings_context(user_input: str) -> bool:
    """保有・ポジション・含み損など、プロファイル注入が妥当な発話か。"""
    return bool(_HOLDINGS_CONTEXT_RE.search(user_input or ""))


def _is_ascii_ticker_token(token: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9._^]{0,11}", token or ""))


def _ascii_token_in_text(token: str, text_lower: str) -> bool:
    """ASCII トークンは単語境界で照合（googl ⊆ google を防ぐ）。"""
    if not _is_ascii_ticker_token(token):
        return False
    return (
        re.search(
            rf"(?<![A-Za-z0-9]){re.escape(token.lower())}(?![A-Za-z0-9])",
            text_lower,
        )
        is not None
    )


def _token_matches_user_text(token: str, text: str, text_lower: str) -> bool:
    tok = (token or "").strip()
    if len(tok) < 2:
        return False
    if _is_ascii_ticker_token(tok):
        return _ascii_token_in_text(tok, text_lower)
    return tok in text


def user_requests_memory_save(user_input: str) -> bool:
    text = (user_input or "").strip()
    if not text:
        return False
    return any(re.search(p, text, re.IGNORECASE) for p in _MEMORY_SAVE_PATTERNS)


def user_requests_persona_change(user_input: str) -> bool:
    text = (user_input or "").strip()
    return any(re.search(p, text, re.IGNORECASE) for p in _PERSONA_PATTERNS)


def user_requests_forget(user_input: str) -> bool:
    text = (user_input or "").strip()
    return any(re.search(p, text, re.IGNORECASE) for p in _FORGET_PATTERNS)


def normalize_target_key(target: str) -> str:
    """重複判定用に target を正規化。"""
    t = (target or "").strip().lower()
    t = re.sub(r"[\s　_\-—–・/（）()【】\[\]「」『』]+", "", t)
    t = re.sub(r"[のはをがにとで]", "", t)
    return t


# 旧デモシード（偽プロフィール）。purge-junk で除去対象にする
_DEMO_SEED_QUOTES = {
    "コーヒーはブラック派かな",
    "辛いものはあんまり得意じゃない",
    "猫を2匹飼ってる",
    "ロックよりジャズが好き",
    "毎週金曜は早めに切り上げたい",
    "登山はきついから苦手",
    "在宅勤務がメイン",
    "映画は静かなドラマ系が好み",
    "甘いお酒は苦手、辛口が好き",
    "誕生日は特に祝わなくていい",
}


def is_demo_seed_memory(entry: dict) -> bool:
    quote = str(entry.get("quote") or "").strip()
    return quote in _DEMO_SEED_QUOTES


def is_junk_memory(entry: dict) -> bool:
    """ニュース・会話メタ・AI自己説明など長期記憶に不適切なエントリか。"""
    if is_demo_seed_memory(entry):
        return True
    summary = entry.get("summary") or {}
    target = str(summary.get("target") or "")
    note = str(summary.get("note") or "")
    quote = str(entry.get("quote") or "")
    category = str(entry.get("category") or "")
    stance = str(summary.get("stance") or "")
    tags = summary.get("tags") or []
    tag_set = {str(t).strip() for t in tags if t is not None}

    if category == "persona":
        return False

    # 圧縮由来の一時タグは常に junk（明示保有でもタグ付きは圧縮由来）
    if tag_set & _EPHEMERAL_KV_TAGS:
        return True

    # ユーザー本人の嗜好・保有・予定はニュース語を含んでも許容
    # ただし「GOOGL保有」のように明示保有のみ。単なる話題名の profile は落とす。
    # 「非保有者」などに含まれる「保有」は除外
    user_owned = bool(
        re.search(r"(?<!非)保有|持ってる|飼って|住んで|勤め|勤務", f"{note}{quote}{target}")
    )
    explicit_save_quote = bool(
        re.search(r"覚えておいて|記憶しておいて|記憶して|メモして", quote)
    )
    if category in ("preference", "schedule") and stance in ("好き", "苦手", "条件付き", "予定", "約束"):
        return False
    if user_owned and category == "profile" and explicit_save_quote:
        if not re.search(r"(移籍金|画像リクエスト|APIエラー|キャラクター設定|移籍市場)", f"{target}{note}"):
            return False

    blob = f"{target}\n{note}\n{quote}"
    if _JUNK_TARGET_RE.search(blob):
        return True

    if _QUOTE_IS_META_RE.search(quote.strip()):
        return True

    # quote が短すぎ／ターゲット名だけのものは会話断片
    if len(quote.strip()) < 4 and category == "profile":
        return True

    # 「話題の固有名詞をそのまま記憶」パターン（明示保存の引用がない）
    if category == "profile" and not explicit_save_quote:
        qn = re.sub(r"[\s　]+", "", quote)
        tn = re.sub(r"[\s　]+", "", target)
        if qn and tn and (qn == tn or qn in tn or tn in qn):
            return True

    return False


def quote_supported_by_user(user_input: str, quote: str) -> bool:
    """quote が今回のユーザー発言に実際に含まれるか（捏造引用を防ぐ）。"""
    q = (quote or "").strip()
    u = (user_input or "").strip()
    if not q or not u:
        return False
    if q in u:
        return True
    # ゆるい一致: 句読点除去後に主要部分が含まれる
    q_norm = re.sub(r"[\s　、。！？!?,.]+", "", q)
    u_norm = re.sub(r"[\s　、。！？!?,.]+", "", u)
    if len(q_norm) >= 6 and q_norm in u_norm:
        return True
    # 長い quote は先頭20文字で判定
    if len(q_norm) >= 20 and q_norm[:20] in u_norm:
        return True
    return False


def should_accept_kv_action(user_input: str, kv_action: dict) -> tuple[bool, str]:
    """
    Supervisor の kv_action を受け入れるか。

    Returns:
        (ok, reason)
    """
    if not isinstance(kv_action, dict):
        return False, "kv_action が不正"

    action = kv_action.get("action") or "none"
    if action in (None, "none", ""):
        return False, "action=none"

    category = (kv_action.get("category") or "").strip()
    quote = kv_action.get("quote") or ""
    summary = kv_action.get("summary") or {}

    if action == "delete":
        if user_requests_forget(user_input) or user_allows_memory_use(user_input):
            return True, "forget/use"
        return False, "削除は明示的な忘却指示が必要"

    if action == "update":
        if user_requests_memory_save(user_input) or user_allows_memory_use(user_input):
            return True, "explicit save/use"
        return False, "更新は明示的な記憶指示が必要"

    if action != "add":
        return False, f"未知の action: {action}"

    # --- add ---
    if category == "persona":
        if user_requests_persona_change(user_input):
            return True, "persona change"
        return False, "persona は明示的な口調変更時のみ"

    if category == "exclusion":
        if user_requests_forget(user_input):
            return True, "exclusion"
        return False, "exclusion は忘却指示時のみ"

    # 明示保存が必須（「おまかせ」「はい」では保存しない）
    if not user_requests_memory_save(user_input):
        return False, "明示的な保存指示がない（おまかせ等は不可）"

    if is_junk_memory(kv_action):
        return False, "ジャンク（ニュース/会話メタ/AI自己説明）"

    if not quote_supported_by_user(user_input, quote):
        # 明示保存時でも quote はユーザー発言由来であること
        # 例外: quote が空で summary.note にユーザー文がある場合は note を見る
        note = str(summary.get("note") or "")
        if not quote_supported_by_user(user_input, note):
            return False, "quote がユーザー発言に存在しない"

    target = str(summary.get("target") or "")
    if not target.strip():
        return False, "target が空"

    return True, "explicit save"


def collect_memory_guard_keywords(memories: list[dict], user_input: str) -> list[str]:
    """
    後処理で無断言及を落とすためのキーワード一覧。
    ユーザー入力に既に出てくる語は除外（正当な言及を消さない）。
    """
    keywords: list[str] = []
    user = user_input or ""
    for m in memories or []:
        summary = m.get("summary") or {}
        target = str(summary.get("target") or "").strip()
        if len(target) < 2:
            continue
        if target in user:
            continue
        # 長すぎる target はノイズ
        if len(target) > 40:
            # 括弧前だけ使う
            target = re.split(r"[（(—\-]", target, 1)[0].strip()
        if 2 <= len(target) <= 40 and target not in user:
            keywords.append(target)
        for tag in summary.get("tags") or []:
            tag_s = str(tag).strip()
            if 2 <= len(tag_s) <= 20 and tag_s not in user and tag_s not in keywords:
                # 汎用語は除外
                if tag_s in {"好き", "苦手", "予定", "旅行", "重要", "仕事", "音楽"}:
                    continue
                keywords.append(tag_s)
    return keywords


def entry_matches_user_input(entry: dict, user_input: str) -> bool:
    """今回の発話と意味的に接点がある記憶か（キーワード一致）。"""
    text = (user_input or "").strip()
    if not text:
        return False
    text_lower = text.lower()
    summary = entry.get("summary") or {}
    target = str(summary.get("target") or "")
    note = str(summary.get("note") or "")
    tags = summary.get("tags") or []

    # target 全体または意味のある部分トークン
    if target and len(target) >= 2 and target in text:
        return True
    for tok in re.split(r"[\s　/／・、,（）()]+", target):
        if _token_matches_user_text(tok, text, text_lower):
            return True
    # target 内の ASCII ティッカー断片（例: MSFT保有状況 → MSFT）。社名エイリアス表は持たない。
    for m in re.finditer(r"[A-Za-z][A-Za-z0-9]{1,9}", target):
        if _ascii_token_in_text(m.group(0), text_lower):
            return True

    for tag in tags:
        tag_s = str(tag).strip()
        if _token_matches_user_text(tag_s, text, text_lower):
            return True

    # note の固有っぽい単語（長め）。ASCII は境界照合。
    for tok in re.findall(r"[A-Za-z]{3,}|\d{2,}|[一-龥ぁ-んァ-ン]{3,}", note):
        if _token_matches_user_text(tok, text, text_lower):
            return True
    return False
