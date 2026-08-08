import json
import re
from datetime import datetime
from pathlib import Path
from app.utils.logger import get_logger

logger = get_logger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
PROMPTS_DIR = BASE_DIR / "prompts"

HIGH_CONFIDENCE_THRESHOLD = 0.75
LOW_CONFIDENCE_THRESHOLD = 0.40

# 金融ジャーゴン短文は前ターン話題へのゼロ照応を禁止（曖昧な「介入」を規制話に固定しない）
_FINANCE_JARGON_TOPIC_RE = re.compile(r"介入|円安|円高|利上げ|利下げ|為替")
_EXPLICIT_ANAPHORA_RE = re.compile(r"(それ|これ|そこ|あれ|あそこ)")


def is_finance_jargon_topic_shift(user_input: str) -> bool:
    """明示代名詞なしの金融ジャーゴン短文 → 前ターン主語を引き継がない。"""
    text = user_input or ""
    if not _FINANCE_JARGON_TOPIC_RE.search(text):
        return False
    if _EXPLICIT_ANAPHORA_RE.search(text):
        return False
    return True


def fuzzy_match_entities(user_input: str, last_assistant_entities: list[dict]) -> list[dict]:
    """
    ユーザーの入力と直前ターンの候補リストを比較し、各エンティティの一致度スコアを算出する。
    """
    if not user_input or not last_assistant_entities:
        return []

    matches = []
    input_lower = user_input.lower()

    # 位置指定キーワードの判定
    pos_keywords = {
        1: ["1番", "①", "1つ目", "一つ目", "最初の"],
        2: ["2番", "②", "2つ目", "二つ目", "真ん中の", "次の"],
        3: ["3番", "③", "3つ目", "三つ目", "最後の"],
        4: ["4番", "④", "4つ目", "四つ目"],
        5: ["5番", "⑤", "5つ目", "五つ目"],
    }

    scores = {}
    for i, entity in enumerate(last_assistant_entities):
        name = entity.get("name", "").strip()
        if not name:
            continue
        name_lower = name.lower()
        score = 0.0

        # 1. 完全または強い部分一致
        if len(name_lower) >= 2 and (name_lower in input_lower or input_lower in name_lower):
            if len(name_lower) >= 4 or name_lower == input_lower:
                score = max(score, 0.95)
            else:
                score = max(score, 0.85)

        # 2. リスト番号指定による一致
        pos = entity.get("list_position")
        if pos and pos in pos_keywords:
            if any(kw in user_input for kw in pos_keywords[pos]):
                score = max(score, 0.92)

        # 3. トークン・キーワード部分一致
        parts = [p for p in re.split(r"[\s・/／\(\)（）の〜\-~&＆とや、,.]+", name) if len(p) >= 2]
        if parts:
            matched_parts = sum(1 for p in parts if p.lower() in input_lower)
            if matched_parts > 0:
                overlap_ratio = matched_parts / len(parts)
                score = max(score, min(0.90, overlap_ratio * 0.88 + 0.15))

        scores[i] = score

    max_base_score = max(scores.values()) if scores else 0.0

    # 4. どの名前・番号にもヒットしなかった場合で、代名詞や短いリアクション（そこ、それ、いいね等）のみの時
    zero_anaphora_keywords = [
        "いいね", "そこ", "それ", "あれ", "あそこ", "どれ", "どっち", "どちら", "もっと",
        "特徴", "なんで", "どうして", "どこ", "おすすめ", "異端", "詳しく", "どう", "これ",
        "お願い", "そうする", "それで", "それに", "うん", "はい", "なるほど"
    ]
    is_short_ellipsis = any(kw in user_input for kw in zero_anaphora_keywords) and len(user_input.strip()) <= 45
    if max_base_score == 0.0 and is_short_ellipsis:
        if len(last_assistant_entities) == 1:
            scores[0] = 0.85
        else:
            for i in scores:
                scores[i] = 0.50

    for i, entity in enumerate(last_assistant_entities):
        if i in scores and scores[i] > 0.0:
            matches.append({"entity": entity, "score": scores[i]})

    matches.sort(key=lambda x: x["score"], reverse=True)
    return matches


def resolve_zero_anaphora(user_input: str, last_assistant_entities: list[dict]) -> dict:
    """
    直前ターンの候補との一致度スコアに応じて、3段階＋1のモードに分岐させる。
    - direct_answer: 高確信度で単一候補一致 → 即答モード
    - soft_confirm_inline: 中確信度 → 回答内に「〇〇やんな/ですね」と主語を自然に織り込んで進める
    - disambiguate: 複数候補が拮抗 → 聞き返しを許可
    - no_anchor: 該当なし → 通常話題として処理
    """
    if is_finance_jargon_topic_shift(user_input):
        return {"mode": "no_anchor"}

    matches = fuzzy_match_entities(user_input, last_assistant_entities)

    high_matches = [m for m in matches if m["score"] > HIGH_CONFIDENCE_THRESHOLD]
    low_matches = [m for m in matches if LOW_CONFIDENCE_THRESHOLD < m["score"] <= HIGH_CONFIDENCE_THRESHOLD]
    all_valid = [m for m in matches if m["score"] > LOW_CONFIDENCE_THRESHOLD]

    if len(high_matches) == 1:
        return {"mode": "direct_answer", "anchor": high_matches[0]["entity"], "score": high_matches[0]["score"]}
    elif len(high_matches) > 1:
        return {"mode": "disambiguate", "candidates": high_matches}
    elif len(low_matches) == 1 and len(all_valid) == 1:
        return {"mode": "soft_confirm_inline", "anchor": low_matches[0]["entity"], "score": low_matches[0]["score"]}
    elif len(all_valid) > 1:
        return {"mode": "disambiguate", "candidates": all_valid}
    else:
        return {"mode": "no_anchor"}


def build_entity_registry_context(history_messages: list, current_input: str) -> str:
    """
    全会話・複数ターン広域エンティティインデックスを照合するとともに、
    確信度段階分岐 (`resolve_zero_anaphora`) による最適な文脈承継アンカーを生成・注入する。
    """
    if not history_messages or not current_input or not isinstance(current_input, str):
        return ""

    # 金融ジャーゴンの話題転換では前銘柄レジストリを注入しない
    if is_finance_jargon_topic_shift(current_input):
        return ""

    candidate_map = []
    list_pattern = re.compile(r"(?:[①②③④⑤⑥⑦⑧⑨⑩]|\d+[\.、\)]|[-・\*])\s*([^\n—–-]{2,60})(?:\s*[—–-]\s*([^\n]+))?")

    for msg in history_messages[-10:]:
        content = msg.get("content", "")
        if not content or not isinstance(content, str):
            continue
        for match in list_pattern.finditer(content):
            item = match.group(1).strip()
            desc = (match.group(2) or "").strip()
            if 2 <= len(item) <= 60 and item.lower() not in ["はい", "いいえ", "その他", "まとめ", "特徴", "理由"]:
                candidate_map.append((item, desc))

    matched_entries = []
    if candidate_map:
        for item, desc in candidate_map:
            parts = [p for p in re.split(r"[\s・/／]", item) if len(p) >= 3]
            if any(part.lower() in current_input.lower() for part in parts) or (len(item) >= 4 and item.lower() in current_input.lower()):
                matched_entries.append(f"- 過去の言及項目: 「{item}」" + (f" ({desc})" if desc else ""))

    # 直前アシスタントのメッセージから直近の話題・候補を抽出してエンティティリストを作成
    last_assistant_content = ""
    for msg in reversed(history_messages):
        if msg.get("role") == "assistant" and msg.get("content"):
            last_assistant_content = msg.get("content", "")
            break

    last_assistant_entities = []
    if last_assistant_content:
        for idx, match in enumerate(list_pattern.finditer(last_assistant_content)):
            item = match.group(1).strip()
            desc = (match.group(2) or "").strip()
            if 2 <= len(item) <= 60 and item.lower() not in ["はい", "いいえ", "その他", "まとめ", "特徴", "理由"]:
                last_assistant_entities.append({"name": item, "description": desc, "list_position": idx + 1})
        # リスト形式でなくても過去数ターンの直近候補があればフォールバック追加
        if not last_assistant_entities and candidate_map:
            for idx, (item, desc) in enumerate(candidate_map[-3:]):
                last_assistant_entities.append({"name": item, "description": desc, "list_position": idx + 1})

    anaphora_result = resolve_zero_anaphora(current_input, last_assistant_entities)
    zero_anaphora_anchor = ""

    if anaphora_result["mode"] == "direct_answer":
        target = anaphora_result["anchor"]["name"]
        zero_anaphora_anchor = (
            f"\n\n【🗣️ Zero-Subject & Ellipsis Resolution Anchor (確信度: 高 / {anaphora_result['score']:.2f})】\n"
            f"ユーザー入力「{current_input}」は、直前ターンの提示項目「{target}」への明確な言及またはゼロ照合・主語承継です。\n"
            f"⚠️ 【即答モード厳守・深読み・疑心暗鬼・的外れな問い返しの厳格禁止】:\n"
            f"1. 深読み・疑心暗鬼・的外れな問い返しの厳格禁止: 「〇〇のことですか？それとも勘違いですか？」等の過剰確認を一切行わないこと。\n"
            f"2. スマートな文脈承継: 対象項目「{target}」を主語としてダイレクトかつスマートに回答を展開すること。"
        )
    elif anaphora_result["mode"] == "soft_confirm_inline":
        target = anaphora_result["anchor"]["name"]
        zero_anaphora_anchor = (
            f"\n\n【🗣️ Zero-Subject & Ellipsis Resolution Anchor (確信度: 中 / {anaphora_result['score']:.2f})】\n"
            f"ユーザー入力「{current_input}」は、直前ターンの提示項目「{target}」を指している可能性が高いです。\n"
            f"⚠️ 【ソフトコンファーム（会話内織り込み）モード厳守・深読み・疑心暗鬼・的外れな問い返しの厳格禁止】:\n"
            f"「〇〇のことでしょうか？」と質問・聞き返しで会話をストップさせることは禁止。「{target}ですね／あのお店は〜」のように、主語を回答本文内に自然に織り込んで解説を進めること。万が一違っていた場合でもユーザーが軽やかに訂正しやすいスムーズな対話を維持してください。"
        )
    elif anaphora_result["mode"] == "disambiguate":
        cands = [c["entity"]["name"] for c in anaphora_result["candidates"][:3]]
        zero_anaphora_anchor = (
            f"\n\n【🗣️ Zero-Subject & Ellipsis Resolution Anchor (確信度: 拮抗・複数候補検出)】\n"
            f"ユーザー入力「{current_input}」に対して、直前ターンの提示候補から複数の拮抗する項目（{', '.join(cands)} 等）が検出されました。\n"
            f"⚠️ 【聞き返し（明確化）許可モード】複数の候補が混同・拮抗しているため、独断で1つに絞り込んで断定せず、「{cands[0]} と {cands[1]} のどちらについてでしょうか？／どれが気になりますか？」と簡潔かつ親切に聞き返して確認を行うことが許可・推奨されます。"
        )

    if matched_entries:
        return (
            "\n\n【🧠 Multi-turn Entity-Context Matcher (広域インデックス照合結果)】\n"
            "ユーザーの言及キーワードに関連する過去の提示項目が全会話インデックスから検出されました：\n"
            + "\n".join(matched_entries[:5])
            + zero_anaphora_anchor
            + "\n⚠️ 直近の主語（別のトピックやアーティスト）に引っ張られず、上記項目および親エンティティの正確なファクトを検索確認の上で解説してください。"
        )

    if zero_anaphora_anchor:
        return zero_anaphora_anchor

    # 照合ヒットがなくても、直近数ターンに選択肢リストが存在すれば広域インデックスとして提示
    recent_items = [f"- {item}" + (f" ({desc[:30]})" if desc else "") for item, desc in candidate_map[-6:]] if candidate_map else []
    if recent_items:
        return (
            "\n\n【🧠 Multi-turn Entity-Context Registry (会話全体の提示項目インデックス)】\n"
            "過去のやり取りで以下の選択肢・候補が列挙されています。個別タイトルへの言及時は、直近主語だけに吸着させず本インデックスを参照してください：\n"
            + "\n".join(recent_items)
        )
    return ""


