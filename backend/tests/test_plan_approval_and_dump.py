"""プラン誤承認（続きを作成して）と Supervisor 独白リークの回帰。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.chat_orchestrator import (
    is_continuation_utterance,
    is_plan_approval_utterance,
    is_spec_approval_utterance,
)
from app.core.fact_filters.markup import (
    looks_like_supervisor_dump,
    strip_internal_markup,
    strip_supervisor_dump,
)


def test_continuation_not_plan_approval():
    assert is_continuation_utterance("続きを作成して")
    assert is_continuation_utterance("続きを作って")
    assert is_continuation_utterance("続けてください")
    assert not is_plan_approval_utterance("続きを作成して")
    assert not is_plan_approval_utterance("続きを作成して、JUMPから再開して")
    assert not is_spec_approval_utterance("続きを作成して")


def test_short_plan_approvals_still_work():
    assert is_plan_approval_utterance("はい")
    assert is_plan_approval_utterance("OK")
    assert is_plan_approval_utterance("進めて")
    assert is_plan_approval_utterance("作って")
    assert is_plan_approval_utterance("作成して")
    # 部分一致だった頃の誤ヒットパターン
    assert not is_plan_approval_utterance("作成")  # 単語だけは弱いので不可
    assert not is_plan_approval_utterance(
        "JUMPとか2マス進むとか作ってほしい"
    )


def test_spec_casual_approval():
    assert is_spec_approval_utterance("とりまそんな感じで")
    assert is_spec_approval_utterance("◎")


def test_supervisor_dump_detection_and_strip():
    dump = (
        "ユーザーは JUMP が欲しい。\n"
        "mode は task。\n"
        "instruction.facts_to_present に実行モデルへの指示を書く。\n"
        "この内容を JSON で出力する。\n"
        "<read_file><read_file><search_codebase><run_command>`\n"
        "<read\n"
        "<file><edit>\n"
        "*(⚠️ 最大実行ループ数 40 に到達しました。作業は未完了の可能性があります。「続きを作成して」と指示してください)*"
    )
    assert looks_like_supervisor_dump(dump)
    cleaned = strip_supervisor_dump(dump)
    assert "facts_to_present" not in cleaned
    assert "<read_file>" not in cleaned or looks_like_supervisor_dump(cleaned) is False
    # バナーは strip 対象外でも残せる（loop 側で救出）
    assert "続きを作成して" in dump


def test_strip_orphan_tool_tag_cluster():
    text = "進捗です。\n<read_file><edit><list_dir>\n完了報告。"
    cleaned = strip_internal_markup(text)
    assert "<read_file>" not in cleaned
    assert "進捗です" in cleaned
    assert "完了報告" in cleaned
