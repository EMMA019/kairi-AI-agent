"""<<<FINAL_ANSWER>>> empty-body / CoT leak regression tests."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.fact_filters.markup import (
    FINAL_ANSWER_MARKER,
    clean_assistant_visible,
    normalize_final_answer_body,
    split_final_answer,
)


def test_split_final_answer_no_marker():
    pre, body, had = split_final_answer("Hello world")
    assert had is False
    assert body == "Hello world"
    assert pre == ""


def test_split_final_answer_with_body():
    raw = f"long cot planning\n{FINAL_ANSWER_MARKER}\n\nMarkets rose today."
    pre, body, had = split_final_answer(raw)
    assert had is True
    assert "cot" in pre.lower() or "planning" in pre
    assert "Markets rose" in body
    assert FINAL_ANSWER_MARKER not in body


def test_split_final_answer_marker_only_empty_body():
    raw = f"\n\n{FINAL_ANSWER_MARKER}\n"
    pre, body, had = split_final_answer(raw)
    assert had is True
    assert not body.strip()
    visible, empty = normalize_final_answer_body(raw)
    assert empty is True
    assert visible == ""


def test_clean_assistant_visible_drops_marker_only():
    assert clean_assistant_visible(f"cot\n{FINAL_ANSWER_MARKER}\n") == ""
    assert "rose" in clean_assistant_visible(
        f"cot\n{FINAL_ANSWER_MARKER}\nMarkets rose."
    )


def test_english_market_short_abort_hint():
    from app.core.completion_status import is_aborted_short_market_reply

    assert is_aborted_short_market_reply("ok", "How did the market perform on July 31?")
    assert not is_aborted_short_market_reply(
        "US stocks finished higher on July 31 with tech leading.",
        "How did the market perform on July 31?",
    )


def test_empty_final_answer_triggers_synthesis():
    """Marker-only executor output must synthesize from search_results."""
    from app.core.auto_execution_loop.loop import auto_execute_with_retry

    async def fake_executor(*_a, **_k):
        yield f"\n\n{FINAL_ANSWER_MARKER}\n"

    synth_chunks = ["US markets finished higher on July 31."]

    async def fake_synth_executor(*_a, **_k):
        for c in synth_chunks:
            yield c

    call_n = {"n": 0}

    def exec_router(*_a, **_k):
        call_n["n"] += 1
        if call_n["n"] == 1:
            return fake_executor()
        return fake_synth_executor()

    async def _run():
        with patch(
            "app.core.auto_execution_loop.loop.run_executor",
            side_effect=exec_router,
        ), patch(
            "app.core.auto_execution_loop.loop.ToolHandler",
        ) as TH:
            th = MagicMock()
            th.tool_results = []
            th.has_escalation = False
            th.escalation_history = []
            TH.return_value = th

            return await auto_execute_with_retry(
                user_input="How did the market perform on July 31?",
                instruction="Summarize US market.",
                supervisor_sys_prompt="sup",
                supervisor_dynamic_sys="",
                executor_sys_prompt="exec",
                executor_dynamic_sys="",
                mode="chat",
                session_id="test-fa",
                history_messages=[],
                search_results="【一般検索結果】Dow up 1%",
                memory_text=None,
                max_tool_loops=3,
                max_supervisor_retries=1,
                yield_sse_func=None,
            )

    final, _tools, _esc = asyncio.run(_run())

    assert "Markets finished higher" in final or "finished higher" in final
    assert FINAL_ANSWER_MARKER not in final
    assert call_n["n"] >= 2  # original + synthesis
