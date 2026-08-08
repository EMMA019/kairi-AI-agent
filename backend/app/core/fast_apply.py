"""
Fast Apply — Morph 方式のマージ専用レイヤー（自前実装）

【コンセプト】
Executor はファイル全文を書き直す代わりに、変更する行だけを
「// ... existing code ...」マーカー付きスニペットとして出力する。
本モジュールが apply モデル（DeepSeek 等、温度0）に
「元ファイル + 編集スニペット」を渡し、マージ済みの完全なファイルを生成させる。

【安全設計】
- マージ結果は機械検証（マーカー残留 / スニペット行の反映率 / サイズ健全性）
- 検証に失敗した場合は書き込まず、呼び出し側が <replace> / <file> にフォールバック
- 巨大ファイルは apply モデルの出力上限を超えるため事前に拒否
"""
import re

from app.core.llm_client import call_model
from app.utils.logger import get_logger

logger = get_logger(__name__)

# apply モデルの出力トークン上限を超えないための入力サイズ上限（文字数）
MAX_ORIGINAL_CHARS = 20_000

# 「変更しない部分」を表す省略マーカー行
# 例: "// ... existing code ...", "# ... 既存コード ...", "<!-- ... existing code ... -->"
_MARKER_LINE_PATTERN = re.compile(
    r'^\s*(?:(?://|#|--|;|/\*|<!--|\*)\s*)?'
    r'\.{2,}\s*(?:existing\s+code|既存(?:の)?コード|unchanged|省略|中略)\s*\.{2,}'
    r'\s*(?:\*/|-->)?\s*$',
    re.IGNORECASE,
)

_APPLY_SYSTEM_PROMPT = """あなたは「Fast Apply」、コードマージ専用のエンジンです。会話はしません。

<code> に元ファイルの全文、<update> に編集スニペットが与えられます。
編集スニペットには変更する行だけが書かれており、変更しない領域は
「// ... existing code ...」のようなマーカー行で省略されています。

あなたの仕事は、編集スニペットを元ファイルにマージし、マージ後のファイル全文を出力することです。

【絶対ルール】
1. 出力はマージ後のファイル全文「のみ」。説明・挨拶・Markdownコードフェンス(```)・XMLタグは一切出力しない。
2. 省略マーカー行（... existing code ... 等）は、元ファイルの対応する未変更コードに置き換える。マーカーを出力に残さない。
3. 編集スニペットに書かれた変更は一字一句そのまま反映する。勝手なリファクタリング・整形・改善は禁止。
4. 編集スニペットが触れていない元ファイルのコードは、一切変更せず完全に保持する。
5. インデント・空行・コメントなど元ファイルの書式を維持する。"""


def has_lazy_markers(snippet: str) -> bool:
    """スニペットに省略マーカー行が含まれるかを判定する。"""
    return any(_MARKER_LINE_PATTERN.match(line) for line in snippet.splitlines())


def _strip_think_blocks(text: str) -> str:
    """DeepSeek reasoner 等が付ける <think> ブロックを除去する。"""
    return re.sub(r'<think>[\s\S]*?</think>\s*', '', text)


def _strip_code_fences(text: str) -> str:
    """出力全体を包む Markdown コードフェンスがあれば剥がす。"""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[-1] if "\n" in stripped else ""
    if stripped.rstrip().endswith("```"):
        stripped = stripped.rstrip()
        stripped = stripped.rsplit("\n", 1)[0] if "\n" in stripped else ""
    return stripped


def validate_merge(original: str, snippet: str, merged: str) -> tuple[bool, str]:
    """
    マージ結果を機械検証する。

    Returns:
        (ok, 失敗理由)
    """
    if not merged.strip():
        return False, "マージ結果が空でした"

    # 1. マーカー残留チェック（マーカーが残る = マージ未完了）
    for line in merged.splitlines():
        if _MARKER_LINE_PATTERN.match(line):
            return False, f"マージ結果に省略マーカーが残っています: {line.strip()!r}"

    # 2. スニペットの実コード行が反映されているか（マーカー行・空行を除く）
    snippet_lines = [
        line.strip() for line in snippet.splitlines()
        if line.strip() and not _MARKER_LINE_PATTERN.match(line)
    ]
    merged_line_set = {line.strip() for line in merged.splitlines()}
    if snippet_lines:
        missing = [line for line in snippet_lines if line not in merged_line_set]
        coverage = 1.0 - (len(missing) / len(snippet_lines))
        if coverage < 0.9:
            return False, (
                f"編集スニペットの反映率が低すぎます ({coverage:.0%})。"
                f"未反映例: {missing[0][:80]!r}"
            )

    # 3. サイズ健全性（部分編集なのに元ファイルより大幅に短い = 破壊の疑い）
    original_lines = max(len(original.splitlines()), 1)
    merged_lines = len(merged.splitlines())
    snippet_line_count = len(snippet_lines)
    is_partial_edit = snippet_line_count < original_lines * 0.6
    if is_partial_edit and merged_lines < original_lines * 0.5:
        return False, (
            f"マージ結果が元ファイルより大幅に短くなっています "
            f"(元: {original_lines}行 → 結果: {merged_lines}行)。コード消失の疑いがあるため破棄しました"
        )

    return True, ""


async def apply_edit(
    original: str,
    snippet: str,
    instruction: str = "",
) -> tuple[bool, str]:
    """
    元ファイルに編集スニペットをマージし、マージ後の全文を返す。

    Returns:
        (成功したか, マージ後の全文 または 失敗理由)
    """
    if len(original) > MAX_ORIGINAL_CHARS:
        return False, (
            f"ファイルが大きすぎます ({len(original)}文字 > {MAX_ORIGINAL_CHARS}文字)。"
            "<replace> タグでピンポイント置換してください"
        )

    user_content = (
        f"<instruction>{instruction or 'Apply the update snippet to the code.'}</instruction>\n"
        f"<code>{original}</code>\n"
        f"<update>{snippet}</update>"
    )

    # apply モデルの選択: 専用設定があれば優先、なければ DeepSeek chat（安価・低温度）
    try:
        from app.routers.settings import app_settings
        settings = app_settings.get()
        provider = settings.get("fast_apply_provider") or settings.get("executor_provider", "deepseek")
        model_name = settings.get("fast_apply_model") or settings.get("executor_model", "deepseek-v4-flash")
    except Exception:
        provider, model_name = "deepseek", "deepseek-v4-flash"

    try:
        raw = await call_model(
            system_instruction=_APPLY_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
            model_name=model_name,
            max_tokens=8192,
            provider=provider,
            temperature=0.0,
        )
    except Exception as e:
        logger.error(f"Fast Apply モデル呼び出しエラー: {e}")
        return False, f"applyモデル呼び出しエラー: {e}"

    merged = _strip_code_fences(_strip_think_blocks(raw))

    ok, reason = validate_merge(original, snippet, merged)
    if not ok:
        logger.warning(f"Fast Apply 検証失敗: {reason}")
        return False, reason

    # 末尾改行を保証（既存の <file> 保存処理と同じ流儀）
    if not merged.endswith("\n"):
        merged += "\n"
    return True, merged
