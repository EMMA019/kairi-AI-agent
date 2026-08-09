"""
内部マークアップ（think / ツールタグ）の除去と、途切れ検知。
ユーザー本文に XML・思考ログが漏れないようにする。
"""
from __future__ import annotations

import re
from typing import Tuple
from app.utils.logger import get_logger

logger = get_logger(__name__)

TOOL_TAG_NAMES = (
    r"file|replace|edit|run_command|read_url|read_file|list_dir|list|search|search_news|"
    r"search_codebase|grep_search|view_file|mcp_call|escalate|read"
)

# Supervisor の JSON/独白がユーザー本文に漏れたときの手掛かり（2つ以上で判定）
_SUPERVISOR_DUMP_MARKERS = (
    "user_intent_analysis",
    "facts_to_present",
    "hearing_state",
    "spec_document",
    "kv_action",
    "violation_risk",
    "logical_order",
    "この内容を JSON で出力",
    '"mode": "task"',
    '"mode":"task"',
    "mode は task",
    "output する JSON",
)

_TOOL_OPEN = re.compile(rf"<(?:{TOOL_TAG_NAMES})\b", re.IGNORECASE)
_THINK_OPEN = re.compile(r"<think\b", re.IGNORECASE)
_THINK_CLOSE = re.compile(r"</think\s*>", re.IGNORECASE)


def strip_internal_markup(text: str) -> str:
    """
    think / ツールXML（完全・不完全）・孤児閉じタグを除去する。
    """
    if not text or not isinstance(text, str):
        return text

    original = text

    # 完全な think ブロック
    text = re.sub(r"<think\b[^>]*>.*?</think\s*>", "", text, flags=re.DOTALL | re.IGNORECASE)
    # 未閉じ think（末尾まで）
    text = re.sub(r"<think\b[^>]*>(?:(?!</think).)*$", "", text, flags=re.DOTALL | re.IGNORECASE)
    # 孤児 </think>
    text = _THINK_CLOSE.sub("", text)

    # 完全なツールタグ（自己閉じ）
    text = re.sub(
        rf"<(?:{TOOL_TAG_NAMES})\b[^>]*/>",
        "",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    # 完全な開閉タグ
    text = re.sub(
        rf"<(?:{TOOL_TAG_NAMES})\b[^>]*>.*?</(?:{TOOL_TAG_NAMES})\s*>",
        "",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    # 未閉じツール開始タグ（`>` 無しで行末または文字列末尾）
    text = re.sub(
        rf"<(?:{TOOL_TAG_NAMES})\b[^>\n]*$",
        "",
        text,
        flags=re.MULTILINE | re.IGNORECASE,
    )
    # 開きだけ残ったタグ（閉じなし）— タグ直後が空白のみのときだけ（本文を巻き込まない）
    text = re.sub(
        rf"<(?:{TOOL_TAG_NAMES})\b[^>]*>\s*$",
        "",
        text,
        flags=re.MULTILINE | re.IGNORECASE,
    )
    text = re.sub(rf"</(?:{TOOL_TAG_NAMES})\s*>", "", text, flags=re.IGNORECASE)

    # 連続したツールタグ断片（`<read_file><edit><list_dir>` など）
    text = re.sub(
        rf"(?:<(?:{TOOL_TAG_NAMES})\b[^>\n]*>\s*){{2,}}",
        "",
        text,
        flags=re.IGNORECASE,
    )
    # 孤立した開始タグ断片（閉じ `>` なしの行）
    text = re.sub(
        rf"(?m)^\s*<(?:{TOOL_TAG_NAMES})\b[^>\n]*\s*$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    # 単独の空ツールタグ行
    text = re.sub(
        rf"(?m)^\s*<(?:{TOOL_TAG_NAMES})\b[^>]*>\s*$",
        "",
        text,
        flags=re.IGNORECASE,
    )

    # バッククォート1個だけの残骸行
    text = re.sub(r"(?m)^\s*`\s*$", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    cleaned = text.strip()
    if cleaned != original.strip():
        logger.info("🧹 内部マークアップ（think/ツールタグ）を除去しました")
    return cleaned

# synth prompt constraint-echo markers (2+ hits = meta preamble)
_META_ECHO_PATTERNS = [
    re.compile(r"\bno think\b", re.IGNORECASE),
    re.compile(r"\bno tool xml\b", re.IGNORECASE),
    re.compile(r"\bplanning notes?\b", re.IGNORECASE),
    re.compile(r"\bfinal answer\b", re.IGNORECASE),
    re.compile(r"FINAL_ANSWER"),
    re.compile(r"\bthe instruction\b", re.IGNORECASE),
    re.compile(r"\brule \d+\b", re.IGNORECASE),
    re.compile(r"\buser-facing\b", re.IGNORECASE),
    re.compile(r"\bSupervisor\b"),
    re.compile(r"\bcode fences?\b", re.IGNORECASE),
    re.compile(r"\bpreamble\b", re.IGNORECASE),
    re.compile(r"出力してはいけません"),
    re.compile(r"出力禁止"),
    re.compile(r"指示どおり"),
]


def strip_meta_reasoning_preamble(text: str) -> str:
    """合成/再生成パスでモデルが平文で漏らすメタ推論プリアンブルを除去する。

    合成プロンプトは <think> や <<<FINAL_ANSWER>>> を禁止するため、
    モデルが「no think, no tool XML, no planning notes...」のような
    制約エコー思考を平文で前置きすると既存フィルタを素通りする。
    実回答は概ね最初のMarkdown見出しから始まるので、見出し前の
    ブロックに制約エコー語彙が2個以上あればプリアンブルと判定して除去。
    見出しが無い、または1個以下なら何もしない（誤爆防止）。
    """
    if not text or not isinstance(text, str):
        return text
    t = text.strip()
    m = re.search(r"(?m)^#{1,6}\s+\S", t)
    if not m:
        return text
    head = t[: m.start()].strip()
    if not head:
        return t
    hits = sum(1 for pat in _META_ECHO_PATTERNS if pat.search(head))
    if hits >= 2:
        logger.info("🧹 メタ推論プリアンブル（制約エコー）を除去しました")
        return t[m.start():]
    return text


def looks_like_supervisor_dump(text: str) -> bool:
    """Supervisor の JSON/モード独白が本文に漏れているか。"""
    if not text or not isinstance(text, str):
        return False
    hits = sum(1 for m in _SUPERVISOR_DUMP_MARKERS if m in text)
    if hits >= 2:
        return True
    # ツールタグが本文に大量
    if len(_TOOL_OPEN.findall(text)) >= 3:
        return True
    return False


def strip_supervisor_dump(text: str) -> str:
    """
    Supervisor 独白っぽい塊を落とす。残りが短すぎる場合は呼び出し側で差し替え。
    """
    if not text or not isinstance(text, str):
        return text
    original = text
    text = strip_internal_markup(text)
    # JSON 風のキー行・「mode は task」系の内部独白行（instruction.facts_to_present 含む）
    text = re.sub(
        r"(?m)^\s*(?:[-*]|\d+\.)?\s*"
        r"(?:[\w.]+\.)?(?:user_intent_analysis|facts_to_present|hearing_state|spec_document|"
        r"kv_action|violation_risk|logical_order|verified_facts|unverified_facts|"
        r"tone_directive|search_used|memory_inject|silence)\b.*$",
        "",
        text,
    )
    text = re.sub(
        r"(?m)^.*\binstruction\.facts_to_present\b.*$",
        "",
        text,
    )
    text = re.sub(
        r"(?m)^\s*(?:mode\s*は\s*task|この内容を JSON で出力|output する JSON).*$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\n{3,}", "\n\n", text)
    cleaned = text.strip()
    if cleaned != original.strip():
        logger.info("🧹 Supervisor 独白風の本文を除去しました")
    return cleaned


def looks_incomplete_output(text: str) -> bool:
    """継続生成が必要そうな不完全出力かどうか。"""
    if not text or not isinstance(text, str):
        return False
    s = text.rstrip()
    if not s:
        return False

    if _THINK_OPEN.search(s) and not _THINK_CLOSE.search(s):
        return True
    if _TOOL_OPEN.search(s):
        # 開いたツールタグが閉じられていない
        opens = len(_TOOL_OPEN.findall(s))
        closes = len(re.findall(rf"</(?:{TOOL_TAG_NAMES})\s*>", s, flags=re.IGNORECASE))
        self_closes = len(re.findall(rf"<(?:{TOOL_TAG_NAMES})\b[^>]*/>", s, flags=re.IGNORECASE))
        if opens > closes + self_closes:
            return True

    if s.count("```") % 2 == 1:
        return True

    last_line = s.splitlines()[-1].rstrip()

    # 単独バッククォート / 未閉じインラインコード残骸
    if re.match(r"^\s*`\s*$", last_line):
        return True
    # 奇数個のインラインバッククォートで終わる（フェンスは上記で処理済み）
    if last_line.count("`") % 2 == 1 and "```" not in last_line:
        return True

    # Markdown 表の途中切れ（| 始まりでセル未完、または末尾が裸バッククォート）
    if last_line.lstrip().startswith("|"):
        cells = [c.strip() for c in last_line.strip("|").split("|")]
        if any(c.endswith("`") and c.count("`") % 2 == 1 for c in cells):
            return True
        # 閉じ `|` がなく途中で切れている、またはセルが空で異常に短い
        if not last_line.rstrip().endswith("|") and len(last_line) > 2:
            return True
        if cells and cells[-1] == "" and last_line.count("|") >= 2:
            # "| foo | `" のような途中切れ
            if "`" in last_line:
                return True

    # コードっぽい途中切れ
    if re.search(
        r"(?:^|\n)\s*(?:if|for|while|def|class|return|import|from|elif|else)\b.*[:=\(\{\[]\s*$",
        last_line,
    ):
        return True
    if re.search(r"[=+\-*/%<>]$", last_line) and not last_line.strip().startswith("#"):
        return True
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", last_line) and len(last_line) <= 40:
        # 単独識別子で終わる（例: lag）
        if len(s.splitlines()) >= 3:
            return True

    # 日本語本文が句点・閉じ括弧なしで終わる（短文挨拶は除外）
    _TERMINALS = set("。．！？!?…‼⁉」』）)]\"'”’")
    if len(s) >= 40 and s[-1] not in _TERMINALS and not last_line.startswith("```"):
        # 英数字のみの識別子やURL末尾は除外
        if re.search(r"[ぁ-んァ-ン一-龥]", last_line):
            return True

    return False


def sanitize_preserving_body(text: str, sanitize_fn) -> str:
    """
    sanitize_fn 適用後に空になったら、マークアップ除去のみのスナップショットへ戻す。
    「掃除で本文ゼロ」を禁止する。
    """
    if not text or not isinstance(text, str):
        return text
    pre = text
    markup_only = strip_internal_markup(pre)
    try:
        after = sanitize_fn(pre)
    except Exception as e:
        logger.warning(f"sanitize_preserving_body: sanitize failed: {e}")
        return markup_only
    if after and after.strip():
        return after
    if markup_only and markup_only.strip():
        logger.warning("⚠️ サニタイズ後に空になったため、マークアップ除去版を復元します")
        return markup_only
    return after if after is not None else ""


FINAL_ANSWER_MARKER = "<<<FINAL_ANSWER>>>"


def split_final_answer(text: str) -> tuple[str, str, bool]:
    """
    Split executor output on <<<FINAL_ANSWER>>>.
    Returns (preamble, body, had_marker).
    If marker present and body empty → treat as empty user answer (caller should synthesize).
    """
    if not text or not isinstance(text, str):
        return "", "", False
    if FINAL_ANSWER_MARKER not in text:
        return "", text, False
    parts = text.split(FINAL_ANSWER_MARKER)
    preamble = FINAL_ANSWER_MARKER.join(parts[:-1])
    body = parts[-1]
    return preamble, body, True


def normalize_final_answer_body(text: str) -> tuple[str, bool]:
    """
    Return (user_visible_body, empty_after_marker).
    empty_after_marker True means marker was present but body is whitespace-only.
    """
    preamble, body, had = split_final_answer(text or "")
    if not had:
        return text or "", False
    if not (body or "").strip():
        return "", True
    return body.strip(), False


def clean_assistant_visible(text: str) -> str:
    """loop_history 復元用: ツールXMLを落として可視本文だけ残す。"""
    if not text:
        return ""
    body, empty_marker = normalize_final_answer_body(text)
    if empty_marker:
        return ""
    cleaned = strip_internal_markup(body)
    cleaned = re.sub(r"<[^>]+>.*?</[^>]+>|<[^>]+/>", "", cleaned, flags=re.DOTALL).strip()
    cleaned = strip_tool_dump_blocks(cleaned)
    return cleaned


_TOOL_DUMP_MARKERS = (
    "[Local Tool:",
    "[MCP Tool:",
    "【一般検索結果:",
    "【引用契約】",
    "【システムからのツール実行結果】",
)


def looks_like_tool_dump(text: str) -> bool:
    """ユーザー向け本文にツール生ログが混入しているか。"""
    if not text or not isinstance(text, str):
        return False
    return any(m in text for m in _TOOL_DUMP_MARKERS)


def strip_tool_dump_blocks(text: str) -> str:
    """
    Local/MCP ツール結果・一般検索結果ブロックを除去する。
    provider（brave/tavily 等）を問わない。
    """
    if not text or not isinstance(text, str):
        return text

    # [Local Tool: ...] / [MCP Tool: ...] + JSON or 後続テキスト
    text = re.sub(
        r"\[(?:Local|MCP) Tool:[^\]]*\]\s*\n\{[\s\S]*?\n\}",
        "",
        text,
    )
    text = re.sub(
        r"\[(?:Local|MCP) Tool:[^\]]*\]\s*(?:\n(?!\[(?:Local|MCP) Tool:|【)[^\n]*)*",
        "",
        text,
    )

    # 【一般検索結果: …】〜次セクション or 末尾（引用契約・番号付きソース含む）
    text = re.sub(
        r"【一般検索結果:.*?】[\s\S]*?(?=(?:【一般検索結果:)|(?:\[(?:Local|MCP) Tool:)|(?:\Z))",
        "",
        text,
    )
    text = re.sub(r"【引用契約】[^\n]*\n?", "", text)
    text = re.sub(r"【システムからのツール実行結果】\s*", "", text)

    # 番号付き検索ソース行（tavily/brave/jina 等）
    text = re.sub(
        r"(?m)^\s*\[\d+\]\s*\[[^\]]*(?:tavily|brave|jina|news|wikipedia|duckduckgo)[^\]]*\][\s\S]*?"
        r"(?=^\s*\[\d+\]\s*\[|\Z)",
        "",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
