import json
import re
import asyncio
import uuid
import time
from typing import AsyncGenerator, Optional
from datetime import datetime
from pathlib import Path
from app.utils.logger import get_logger

logger = get_logger(__name__)

from app.core.tools.handler import ToolHandler
from app.core.llm_client import stream_model
from app.core.executor import run_executor
from app.routers.settings import get_settings

from .heuristics import _detect_test_failure, _detect_error, _detect_success
from .compression import _smart_compress_loop_history
from .supervisor import _analyze_with_supervisor


def _error_signature(error_info: str) -> str:
    """エラー文本を重複検出用の正規化シグネチャに変換する（同一エラーの反復検出用）。"""
    return re.sub(r"\s+", " ", str(error_info or "")).strip()[:150]


def _snapshot_visible(text: str) -> str:
    """ユーザーに見せられる本文だけを抽出して保持用に返す。"""
    try:
        from app.core.fact_filters.markup import clean_assistant_visible
        return clean_assistant_visible(text or "")
    except Exception:
        return re.sub(r"<[^>]+>", "", text or "").strip()


def _remember_good(current: str, candidate: str) -> str:
    try:
        from app.core.fact_filters.markup import normalize_final_answer_body

        body, empty_after = normalize_final_answer_body(candidate or "")
        if empty_after:
            # Marker-only: never treat CoT preamble as last_good
            return current
        vis = _snapshot_visible(body)
    except Exception:
        vis = _snapshot_visible(candidate)
    if vis and len(vis) >= 8:
        return vis
    return current


def _ui_progress(key: str, **kwargs) -> str:
    from app.routers.settings import app_settings
    from app.core.ui_status import pipeline_detail

    return pipeline_detail(key, app_settings.get().get("locale", "en"), **kwargs)


def _clear_ui_with_progress(yield_sse_func, detail: str) -> None:
    """
    clear_buffer で画面を空にしない。進捗を pipeline + chunk で残し、
    「裏で動いてるのに応答空」の体感と無駄リトライを減らす。
    """
    if not yield_sse_func:
        return
    yield_sse_func({"type": "clear_buffer"})
    yield_sse_func({"type": "pipeline", "stage": "working", "detail": detail})
    yield_sse_func({"type": "status", "status": "responding"})
    yield_sse_func({"type": "chunk", "content": f"⏳ {detail}\n"})

async def auto_execute_with_retry(
    user_input: str,
    instruction: str,
    supervisor_sys_prompt: str,
    supervisor_dynamic_sys: str,
    executor_sys_prompt: str,
    executor_dynamic_sys: str,
    mode: str,
    session_id: str,
    history_messages: list,
    search_results: Optional[str] = None,
    memory_text: Optional[str] = None,
    max_tool_loops: int = 40,
    max_supervisor_retries: int = 5,
    yield_sse_func=None,
) -> tuple[str, str, list]:
    """
    自律実行ループのメイン処理。
    
    Returns:
        (final_response, tool_results_summary, escalation_history)
    """
    loop_count = 0
    loop_history = []
    final_accumulated_response = ""
    last_good_user_visible = ""  # clear_buffer / 過剰掃除後の復元用
    continuation_attempted = False
    exec_history = history_messages
    escalation_history = []
    empty_result_retry_count = 0
    empty_output_retry_count = 0
    
    tool_handler = ToolHandler(
        session_id=session_id,
        mode=mode,
        allow_mocks="モック" in user_input or "ダミー" in user_input or "仮実装" in user_input,
    )
    
    # ワークスペースパスの解決
    try:
        from app.routers.workspace import get_workspace_dir
        ws_dir = str(get_workspace_dir())
    except Exception:
        from pathlib import Path
        ws_dir = str(Path(__file__).parent.parent.parent / "workspace")
    
    executed_tool_counts = {}  # 同一ツール呼び出しの発生回数（3回目で無限ループ判定）
    error_signature_counts = {}  # 同一エラー文本の発生回数（2回目で自動修正を打ち切り）
    force_tool_synthesis = False  # 重複ツール停止時など、生ログを本文にせず合成へ回す
    files_written_this_run = False
    last_gate_meta: dict | None = None
    gate_fix_attempts = 0
    MAX_GATE_REINJECT = 3

    def _spec_internal_from_prompts() -> str | None:
        blob = f"{executor_sys_prompt or ''}\n{instruction or ''}"
        m = re.search(
            r"<spec_internal>\n?(.*?)\n?</spec_internal>",
            blob,
            re.DOTALL | re.IGNORECASE,
        )
        return m.group(1).strip() if m else None

    def _run_task_completion_gate() -> dict:
        nonlocal last_gate_meta
        from app.core.build_gate import run_completion_gate

        meta = run_completion_gate(ws_dir, spec_internal=_spec_internal_from_prompts())
        last_gate_meta = meta
        return meta

    def _gate_reinject_message(meta: dict) -> str:
        from app.core.acceptance_checker import AcceptanceReport

        acc = meta.get("acceptance_report")
        build = meta.get("build") or {}
        parts = [
            "【システム完了ゲート・未達】完了宣言は禁止。次を満たしてから再出力すること。\n",
        ]
        if isinstance(acc, AcceptanceReport):
            parts.append(acc.format_for_agent())
        else:
            failed = (meta.get("acceptance") or {}).get("failed_ids") or []
            if failed:
                parts.append("Acceptance NG: " + ", ".join(failed))
        if not build.get("success") and not build.get("skipped"):
            parts.append(
                f"\nBuild NG (exit={build.get('exit_code')}):\n"
                f"```\n{(build.get('output') or '')[-1500:]}\n```\n"
                "ワークスペースルートでビルドが通るまで修正すること。"
            )
        parts.append(
            "\n未達項目だけを <file>/<replace> で直し、再度ビルドが通る状態にすること。"
        )
        return "\n".join(parts)

    boundary_instruction = (
        "\n\n【構造的モダリティ分離（出力境界トークン）の厳守ルール】\n"
        "思考ログ・内部分析・途中メモとユーザーへの最終出力本文がバッファ上で混在するのを完全に防ぐため、"
        "ユーザーへの最終的な回答本文を開始する直前に必ず `<<<FINAL_ANSWER>>>` という区切りトークンを出力し、"
        "その後にのみ最終回答テキストを出力してください。\n"
        "※ツール呼び出し（<search>, <file> 等）のみを行うターンでは `<<<FINAL_ANSWER>>>` は不要です。"
    )
    universal_closed_world_instruction = (
        "\n\n【全ドメイン適用：動的・時系列クエリにおける完全閉世界（Closed-World）原則とパラメトリック記憶の遮断】\n"
        "現在は2026年です。政治、経済・金融（FRB/中央銀行/指標等）、企業人事（CEO/役員等）、スポーツ（選手/所属/監督）、"
        "エンタメ、テクノロジー等の時系列動向・最新ファクトに関する質問に対しては、事前学習データ（パラメトリック記憶）にある"
        "過去の固有名詞や人名（例：FRBパウエル議長等）を絶対にそのまま出力せず、必ず直近の検索結果（ソーステキスト）に明示的に"
        "記載されている最新の人名・固有エンティティのみを正確に拾って回答すること。\n"
        "ソーステキストに個人名の記載がなく役職名・肩書のみ（『FRB議長』『同社CEO』『現職監督』等）記載されている場合は、"
        "勝手に過去の記憶から個人名を推測・補完・上書きせず、ソース通りに『FRB議長』『同社CEO』のように役職名・一般名詞のみで記述してください。"
    )
    if "完全閉世界（Closed-World）原則" not in executor_sys_prompt:
        executor_sys_prompt += universal_closed_world_instruction

    # ソースなしターン: 時事的固有名詞の新規断定を禁止
    if not search_results:
        no_source_guard = (
            "\n\n【🔴 ソースなしターン：固有名詞断定の厳禁】\n"
            "このターンは検索ソースがありません。"
            "会話履歴・ユーザー発言に明示されていない時事的固有名詞"
            "（人名・騎手・役職・所属・記録値・オッズ・日付付きイベント結果）を新規に断定することを禁止します。"
            "必要なら『〜だったはず（要確認）』の不確実表現にするか、"
            "先に <search query=\"...\" /> タグで検索を実行してください。"
            "パラメトリック記憶（事前学習データ）からの補完は絶対に行わないこと。"
        )
        if "ソースなしターン" not in executor_sys_prompt:
            executor_sys_prompt += no_source_guard

    if "<<<FINAL_ANSWER>>>" not in executor_sys_prompt:
        executor_sys_prompt += boundary_instruction
    
    while loop_count < max_tool_loops:
        loop_count += 1
        
        # モード別セーフティ・ループ上限：チャットでも指数クォート数本＋本文生成の余地を残す
        is_coding_task = any(tag in final_accumulated_response for tag in ["<file", "<replace", "<run_command"])
        chat_tool_cap = 8
        if mode not in ["coding", "task"] and loop_count > chat_tool_cap and not is_coding_task:
            logger.info(
                f"🛑 チャット・検索モードのツールループ上限({chat_tool_cap}回)に達したため完了します。"
            )
            if tool_handler.tool_results or search_results:
                force_tool_synthesis = True
            break
        
        if yield_sse_func:
            yield_sse_func({"type": "status", "status": "responding"})
        
        # --- Executor呼び出し ---
        if loop_count == 1:
            exec_user_input = user_input + "\n\n【動的システムコンテキスト】\n" + executor_dynamic_sys
            # 🔴 Claude Code準拠: 初回にプロジェクト全体コンテキストを自動注入
            if mode in ["task", "research", "coding"]:
                try:
                    from app.core.project_context import gather_project_context
                    proj_ctx = await gather_project_context(ws_dir)
                    if proj_ctx:
                        exec_user_input += "\n\n" + proj_ctx
                except Exception as e:
                    logger.warning(f"プロジェクトコンテキスト収集失敗: {e}")
            exec_history = history_messages
        else:
            exec_user_input = loop_history[-1]["content"]
            
            # 🔴 Claude Code準拠: 重要度に基づいた賢い圧縮
            compressed_loop = await _smart_compress_loop_history(loop_history)
            
            exec_history = (
                history_messages
                + [{"role": "user", "content": user_input + "\n\n【動的システムコンテキスト】\n" + executor_dynamic_sys}]
                + compressed_loop
            )
        
        stream_response = ""
        tool_tag_detected = False
        
        # --- Executorのストリーミングを読み取り ---
        stream = run_executor(
            user_input=exec_user_input,
            instruction=instruction,
            search_results=search_results,
            memory_text=memory_text,
            history_messages=exec_history,
            mode=mode,
            system_instruction=executor_sys_prompt,
        )
        
        buffer = ""
        in_xml_block = False
        _TOOL_TAG_NAMES = (
            r'file|replace|edit|run_command|read_url|read_file|list_dir|search|search_news|'
            r'search_codebase|grep_search|view_file|mcp_call|escalate'
        )
        tool_tag_start_pattern = re.compile(
            rf'<({_TOOL_TAG_NAMES})(?:\s|>|/>)'
        )
        self_closing_pattern = re.compile(
            rf'<({_TOOL_TAG_NAMES})[^>]*/>',
            re.DOTALL
        )
        closing_tag_pattern = re.compile(
            rf'</({_TOOL_TAG_NAMES})>',
            re.DOTALL
        )
        
        async def stream_with_newline(original_stream):
            tag_buf = ""
            in_tag = False
            in_think_block = False
            # Hold SSE until <<<FINAL_ANSWER>>> so plain-text CoT is not shown as the answer
            from app.core.fact_filters.markup import FINAL_ANSWER_MARKER

            sse_hold = ""
            fa_released = False
            _tool_or_think_prefix = re.compile(
                rf'^</?(?:think|{_TOOL_TAG_NAMES})',
                re.IGNORECASE,
            )
            _partial_prefix = re.compile(
                r'^</?(?:t(?:h(?:i(?:n(?:k)?)?)?)?|'
                r'm(?:c(?:p(?:_(?:c(?:a(?:l(?:l)?)?)?)?)?)?)?|'
                r'f(?:i(?:l(?:e)?)?)?|search|read_|run_|list_|view_|grep_|escalat)',
                re.IGNORECASE,
            )

            def _emit_user(text: str):
                nonlocal sse_hold, fa_released
                if not text or in_think_block:
                    return
                if not yield_sse_func:
                    return
                if fa_released:
                    yield_sse_func({"type": "chunk", "content": text})
                    return
                sse_hold += text
                idx = sse_hold.find(FINAL_ANSWER_MARKER)
                if idx >= 0:
                    fa_released = True
                    after = sse_hold[idx + len(FINAL_ANSWER_MARKER) :]
                    sse_hold = ""
                    if after:
                        yield_sse_func({"type": "chunk", "content": after})
                # else: keep holding preamble (CoT) off the UI

            async for c in original_stream:
                if in_tag:
                    tag_buf += c
                    # 判定できるまで（`>` or 十分な長さ + 非タグ確定）バッファ
                    if ">" not in tag_buf and "\n" not in tag_buf and len(tag_buf) < 80:
                        continue

                    match_think = re.search(r'<think\b[^>]*>', tag_buf, re.IGNORECASE)
                    match_end_think = re.search(r'</think\s*>', tag_buf, re.IGNORECASE)

                    if match_think:
                        before_think = tag_buf[:match_think.start()]
                        if before_think and not in_think_block:
                            _emit_user(before_think)
                            yield before_think
                        in_think_block = True
                        tag_buf = tag_buf[match_think.end():]
                        in_tag = "<" in tag_buf
                        if not in_tag:
                            tag_buf = ""
                        continue

                    if match_end_think:
                        in_think_block = False
                        tag_buf = tag_buf[match_end_think.end():]
                        in_tag = "<" in tag_buf
                        if tag_buf and not in_tag:
                            _emit_user(tag_buf)
                            yield tag_buf
                            tag_buf = ""
                        continue

                    tool_match = re.search(rf'<({_TOOL_TAG_NAMES})\b', tag_buf, re.IGNORECASE)
                    if tool_match:
                        if tool_match.start() > 0 and not in_think_block:
                            before_tool = tag_buf[:tool_match.start()]
                            _emit_user(before_tool)
                            yield before_tool
                        # ツールタグ本体は SSE に出さず内部のみ
                        yield tag_buf
                        tag_buf = ""
                        in_tag = False
                        continue

                    # 未完了だがツール/think の接頭に見える → まだ SSE に出さない
                    if _tool_or_think_prefix.search(tag_buf) or _partial_prefix.search(tag_buf):
                        if "\n" in tag_buf or len(tag_buf) >= 80:
                            # 不完全ツールタグ: 内部へだけ渡してユーザーには出さない
                            yield tag_buf
                            tag_buf = ""
                            in_tag = False
                        continue

                    # 通常の `<`（比較演算子や HTML 以外の断片）→ ユーザーへ
                    if not in_think_block:
                        _emit_user(tag_buf)
                        yield tag_buf
                    tag_buf = ""
                    in_tag = False
                    continue
                else:
                    if "<" in c:
                        idx = c.find("<")
                        before_lt = c[:idx]
                        if before_lt and not in_think_block:
                            _emit_user(before_lt)
                            yield before_lt
                        in_tag = True
                        tag_buf = c[idx:]
                        continue
                    if not in_think_block:
                        _emit_user(c)
                        yield c
                    continue

            # ストリーム終了: 未完了のツール/think は SSE に出さない
            if tag_buf:
                if in_tag and (
                    _tool_or_think_prefix.search(tag_buf)
                    or _partial_prefix.search(tag_buf)
                    or re.search(rf'<({_TOOL_TAG_NAMES})', tag_buf, re.IGNORECASE)
                ):
                    yield tag_buf  # 内部のみ（ツール検出用）
                elif not in_think_block:
                    _emit_user(tag_buf)
                    yield tag_buf
            # No FINAL_ANSWER marker → flush held text (legacy / tool-only turns)
            if not fa_released and sse_hold and yield_sse_func:
                yield_sse_func({"type": "chunk", "content": sse_hold})
                sse_hold = ""
            yield '\n'
        
        async for chunk in stream_with_newline(stream):
            buffer += chunk
            
            while '\n' in buffer and not tool_tag_detected:
                line, buffer = buffer.split('\n', 1)
                
                if not in_xml_block:
                    match = tool_tag_start_pattern.search(line)
                    if match:
                        in_xml_block = True
                        stream_response += line + '\n'
                        # 同じ行内で完結するセルフクロージングタグ or 閉じタグをチェック
                        if self_closing_pattern.search(line) or closing_tag_pattern.search(line):
                            in_xml_block = False
                            tool_tag_detected = True
                            break
                        continue
                
                if in_xml_block:
                    stream_response += line + '\n'
                    if self_closing_pattern.search(line) or closing_tag_pattern.search(line):
                        in_xml_block = False
                        tool_tag_detected = True
                        break
                else:
                    stream_response += line + '\n'
            
            if tool_tag_detected:
                break
        
        # ストリーム末尾で改行を伴わずにバッファに残ったタグやテキストを処理・救済
        if not tool_tag_detected and buffer.strip():
            line = buffer.strip()
            stream_response += line + '\n'
            if (
                tool_tag_start_pattern.search(line)
                or self_closing_pattern.search(line)
                or closing_tag_pattern.search(line)
                or in_xml_block
            ):
                tool_tag_detected = True
        elif buffer:
            stream_response += buffer + '\n'

        # --- ツール実行 ---
        if tool_tag_detected:
            try:
                current_response, tool_events = await tool_handler.execute_tools(stream_response)
            except Exception as e:
                logger.error(f"ToolHandler error: {e}")
                return stream_response, f"ツール実行エラー: {e}", escalation_history
            
            # エスカレーション検出
            if tool_handler.has_escalation:
                escalation_history.extend(tool_handler.escalation_history)
                logger.info(f"🔃 エスカレーション検出 ({len(escalation_history)}件)")
                
                if len(escalation_history) < max_supervisor_retries:
                    # Supervisorでエラー分析＋修正指示を生成
                    supervisor_result = await _analyze_with_supervisor(
                        escalation_history=escalation_history,
                        user_input=user_input,
                        instruction=instruction,
                        supervisor_sys_prompt=supervisor_sys_prompt,
                        supervisor_dynamic_sys=supervisor_dynamic_sys,
                        mode=mode,
                        history_messages=history_messages,
                        yield_sse_func=yield_sse_func,
                    )
                    
                    if supervisor_result:
                        new_instruction = supervisor_result
                        tool_results_msg = (
                            "【システムからの分析結果】\n"
                            f"前回の実行でエラーが発生したため、Supervisorが分析しました。\n"
                            f"修正指示: {new_instruction}\n"
                        )
                        loop_history.append({"role": "assistant", "content": stream_response})
                        loop_history.append({"role": "user", "content": tool_results_msg})
                        instruction = new_instruction  # 修正指示で上書き
                        _clear_ui_with_progress(yield_sse_func, _ui_progress("re_run_tests"))
                        final_accumulated_response = ""
                        continue  # 再実行
                else:
                    # 上限到達
                    final_accumulated_response += stream_response + "\n"
                    break
            
            # ツール結果のエラーチェック
            has_tool_results = bool(tool_handler.tool_results and any(r.strip() for r in tool_handler.tool_results))
            
            if has_tool_results:
                has_error = False
                error_abort = False
                for result in tool_handler.tool_results:
                    error_info = _detect_error(result)
                    if error_info:
                        has_error = True
                        logger.info(f"🔧 エラー検出、自動修正を試みます (loop {loop_count})")

                        # 同一エラーの反復検出: 同じエラー文本が2回出たら自動修正では解決不能と
                        # 判断し、空転（LLMコール浪費）を止めて回答合成パスへ引き渡す。
                        error_sig = _error_signature(error_info)
                        error_signature_counts[error_sig] = error_signature_counts.get(error_sig, 0) + 1
                        if error_signature_counts[error_sig] >= 2:
                            logger.warning(f"⛔ 同一エラーが2回反復したため自動修正を中止します: {error_sig[:100]}")
                            error_abort = True
                            break

                        if loop_count < max_supervisor_retries:
                            error_context = (
                                "【ツール実行エラー】\n"
                                f"{error_info}\n\n"
                                "上記エラーを分析し、修正したコードを再実行してください。\n"
                                "※外部MCPサーバーの正しい呼び出し形式: <mcp_call server=\"サーバー名\" tool=\"ツール名\" args='{\"key\":\"value\"}' />\n"
                                "（server= と tool= は分離し、tool= にサーバー名を含めない。args は必須。"
                                "Roblox_Studio のほぼ全ツールは args に \"datamodel_type\": \"Edit\" が必須。"
                                "サーバー一覧は list_servers、ツール一覧は list_tools で確認可能）"
                            )
                            loop_history.append({"role": "assistant", "content": stream_response})
                            loop_history.append({"role": "user", "content": error_context})
                            
                            supervisor_result = await _analyze_with_supervisor(
                                escalation_history=[error_info],
                                user_input=user_input,
                                instruction=instruction,
                                supervisor_sys_prompt=supervisor_sys_prompt,
                                supervisor_dynamic_sys=supervisor_dynamic_sys,
                                mode=mode,
                                history_messages=history_messages,
                                yield_sse_func=yield_sse_func,
                            )
                            if supervisor_result:
                                instruction = supervisor_result
                                _clear_ui_with_progress(yield_sse_func, _ui_progress("fix_and_retry"))
                                final_accumulated_response = ""
                                continue
                            else:
                                # Supervisor応答なし（JSONパース失敗等）→ 同じ指示で空転しないよう打ち切る
                                error_abort = True
                                break
                        else:
                            error_abort = True
                            break
                if error_abort:
                    # エラー自動修正の打ち切り: while ループ自体を終了する
                    # （従来は for しか抜けず、max_tool_loops まで空転してLLMコールを浪費していた）
                    logger.warning("🛑 エラー自動修正の上限に到達したためループを終了し、現在の結果で回答を合成します")
                    final_accumulated_response += stream_response + "\n"
                    force_tool_synthesis = True
                    break
                
                if not has_error:
                    # 完全タグでシグネチャ抽出（args内のLuau比較演算子 > 等で切断されないように）
                    tag_match = re.search(r'<(mcp_call|search|read_url)\b[\s\S]*?(?:/>|</\1>)', stream_response)
                    if not tag_match:
                        tag_match = re.search(r'<(mcp_call|search|read_url)[^>]*>', stream_response)
                    sig = tag_match.group(0) if tag_match else None
                    if sig:
                        executed_tool_counts[sig] = executed_tool_counts.get(sig, 0) + 1
                    # 3回目以降の同一呼び出しのみ無限ループと判定
                    # （エラー修正後の再試行や search_game_tree の再確認等、正当な2回目は許容）
                    if sig and executed_tool_counts[sig] >= 3:
                        logger.warning(f"🛑 同一ツール呼び出しの重複検出により無限ループをシャットダウンします ({executed_tool_counts[sig]}回目): {sig[:200]}")
                        # 生の tool_results をユーザー本文に連結しない。合成パスへ回す。
                        loop_history.append({"role": "assistant", "content": stream_response})
                        tool_msg = "【システムからのツール実行結果】\n" + "\n\n".join(tool_handler.tool_results)
                        loop_history.append({"role": "user", "content": tool_msg})
                        if tool_handler.tool_results:
                            dump = "\n\n".join(tool_handler.tool_results)
                            search_results = (
                                f"{search_results}\n\n{dump}".strip() if search_results else dump
                            )
                        final_accumulated_response = ""
                        force_tool_synthesis = True
                        break

                    loop_history.append({"role": "assistant", "content": stream_response})
                    tool_msg = "【システムからのツール実行結果】\n" + "\n\n".join(tool_handler.tool_results)
                    loop_history.append({"role": "user", "content": tool_msg})
                    last_good_user_visible = _remember_good(last_good_user_visible, stream_response)

                    from app.core.completion_status import wants_code_in_chat
                    wrote_file = bool(
                        re.search(
                            r"<(?:file|replace|edit)\b",
                            stream_response,
                            re.IGNORECASE,
                        )
                    )
                    if wrote_file:
                        files_written_this_run = True
                    if wrote_file and mode in ("task", "coding"):
                        # Completion gate: acceptance + build — reinject if not ok
                        try:
                            gate = _run_task_completion_gate()
                            if not gate.get("ok") and gate_fix_attempts < MAX_GATE_REINJECT:
                                gate_fix_attempts += 1
                                if yield_sse_func:
                                    yield_sse_func({
                                        "type": "status",
                                        "status": "incomplete",
                                        "detail": "completion_gate",
                                    })
                                loop_history.append({"role": "assistant", "content": stream_response})
                                loop_history.append({
                                    "role": "user",
                                    "content": _gate_reinject_message(gate),
                                })
                                _clear_ui_with_progress(
                                    yield_sse_func,
                                    "完了ゲート未達 → 未達項目を修正中…",
                                )
                                final_accumulated_response = ""
                                continue
                        except Exception as gate_err:
                            logger.warning(f"completion gate error: {gate_err}")

                    if wrote_file and mode in ("task", "coding", "research"):
                        if wants_code_in_chat(user_input):
                            loop_history.append({
                                "role": "user",
                                "content": (
                                    "【システム通知・最重要】ユーザーはコード本文をチャットで求めている。\n"
                                    "「ファイル作成完了」だけのメタ報告は禁止。\n"
                                    "1) 保存パスを1行\n"
                                    "2) 変更点の要点を短く\n"
                                    "3) 続けてコード全文を ```言語 フェンスでチャットに出力（省略禁止）\n"
                                    "長すぎて切れそうなら先に <file> 済みの内容をそのままフェンスで貼ること。\n"
                                    "可能なら <run_command>python -m py_compile 対象.py</run_command> で構文チェック。"
                                ),
                            })
                        else:
                            loop_history.append({
                                "role": "user",
                                "content": (
                                    "【システム通知】ファイル保存済み。次ターンではパスと要点を短く伝え、"
                                    "必要なら python -m py_compile で構文チェックしてください。"
                                    "「作成完了」だけの空疎な一文で終わらないこと。"
                                ),
                            })
                    _clear_ui_with_progress(
                        yield_sse_func,
                        "ファイル保存／ツール完了 → 回答を組み立て中…" if wrote_file else "ツール完了 → 回答を続けます…",
                    )
                    final_accumulated_response = ""
                    continue
            else:
                # ツールタグは検出したが結果が空 → 自動リトライ（最大2回）
                logger.warning(f"⚠️ ツール実行結果が空: {stream_response[:100]}...")
                loop_history.append({"role": "assistant", "content": stream_response})
                if empty_result_retry_count < 2 and loop_count < max_supervisor_retries:
                    empty_result_retry_count += 1
                    logger.info(f"🔄 空のツール結果を検出。リトライします ({empty_result_retry_count}/2)")
                    retry_msg = (
                        "【システム通知（自動リトライ）】\n"
                        "ツールタグを検出できましたが、実行結果が空でした（Docker未起動やタイムアウトの可能性）。\n"
                        "もし環境に依存するコマンドを実行していた場合は、一度コマンド実行を省き、<file> や <replace> によるファイル操作のみで作業を進めてください。"
                    )
                    loop_history.append({"role": "user", "content": retry_msg})
                    _clear_ui_with_progress(yield_sse_func, _ui_progress("empty_tool_retry"))
                    final_accumulated_response = ""
                    continue
                else:
                    no_result_msg = (
                        "【システム通知】\n"
                        "ツールタグを検出しましたが、実行結果が空でした。\n"
                        "コマンドが完了するまで少し待ってから、もう一度試してください。\n"
                        "エラーが続く場合は、環境設定（Docker、Flutter SDK等）を確認してください。"
                    )
                    loop_history.append({"role": "user", "content": no_result_msg})
                    final_accumulated_response += stream_response + "\n" + no_result_msg + "\n"
                    break  # 無限ループ防止のため一旦会話モードへ
        else:  # tool_tag_detected == False
            # --- 🔴 新規追加: Executor出力が完全空（0文字）の場合のリトライ ---
            if not stream_response.strip():
                logger.warning(f"⚠️ Executorからの出力が完全空（0文字）です (loop {loop_count})")
                if empty_output_retry_count < 1 and loop_count < max_supervisor_retries:
                    empty_output_retry_count += 1
                    logger.info("🔄 空出力を検出したため自動リトライします")
                    retry_msg = (
                        "【システム警告（自動差し戻し）】\n"
                        "直前の応答が空（0文字）でした。空の再生成を繰り返さず、"
                        "具体的なテキストかツールタグ（<file>, <read_file> 等）を必ず1つ以上出力してください。"
                    )
                    # 空 assistant を history に積まない（トークン浪費防止）
                    loop_history.append({"role": "user", "content": retry_msg})
                    _clear_ui_with_progress(yield_sse_func, _ui_progress("empty_regen"))
                    final_accumulated_response = ""
                    continue
                else:
                    err_msg = "*(⚠️ 応答の生成に失敗しました。もう一度お試しください)*"
                    final_accumulated_response += err_msg + "\n"
                    break

            # ツールタグなし → 通常の回答として返す
            from app.core.fact_filters.markup import normalize_final_answer_body

            logger.warning(
                f"🔍 [DEBUG] LLMの生出力(ツールなし): {repr(stream_response[:500])}"
                + ("…" if len(stream_response) > 500 else "")
            )
            body, empty_after_marker = normalize_final_answer_body(stream_response)
            if empty_after_marker:
                # <<<FINAL_ANSWER>>> with no prose → force synthesis; drop CoT preamble
                logger.warning(
                    "⚠️ FINAL_ANSWER marker with empty body — will synthesize from search/tools"
                )
                force_tool_synthesis = True
                loop_history.append({"role": "assistant", "content": stream_response})
                _clear_ui_with_progress(
                    yield_sse_func,
                    _ui_progress("compose_from_search"),
                )
                # Leave final_accumulated empty so need_synth runs
                break

            visible = body if body.strip() else stream_response
            final_accumulated_response += visible + "\n"
            last_good_user_visible = _remember_good(last_good_user_visible, stream_response)

            # 長文コードの chat 直書きを検知 → file 誘導（1回）
            # ユーザーが本文要求でも、途切れ防止のため一旦 file に落としてから読み戻す
            code_fences = len(re.findall(r"```", visible))
            long_code_dump = (
                mode in ("task", "coding", "research")
                and code_fences >= 2
                and len(visible) > 2500
                and not re.search(r"<file\b", stream_response, re.IGNORECASE)
                and loop_count < 2
            )
            if long_code_dump:
                logger.info("📝 長文コードのチャット直書きを検知 → <file> 誘導")
                loop_history.append({"role": "assistant", "content": stream_response})
                loop_history.append({
                    "role": "user",
                    "content": (
                        "【システム警告】長いコードがチャット直書きです（途切れ・トークン浪費の原因）。\n"
                        "今すぐ `<file path=\"...\">全文</file>` で保存し、次ターンで"
                        "パス＋要点＋コード全文フェンスを出力してください。メタ完了宣言のみは禁止。"
                    ),
                })
                _clear_ui_with_progress(yield_sse_func, _ui_progress("save_long_then_body"))
                continue

            # ハルシネーションチェック（ツール指示があるのにタグがない）
            tool_keywords = any(kw in instruction for kw in [
                '<read_url', '<search',
                'ファイルを作成', 'ファイルを修正', 'コードを修正', 'コードを書',
                'コマンドを実行',
            ])
            has_any_xml = bool(re.search(
                r'<(file|replace|run_command|read_url|read_file|list_dir|search|search_news|'
                r'search_codebase|grep_search|view_file|mcp_call|escalate)',
                stream_response
            ))
            
            if mode == "task" and tool_keywords and not has_any_xml and loop_count < 2:
                logger.warning(f"⚠️ ハルシネーション検出: ツール指示を無視 (loop {loop_count})")
                retry_msg = (
                    "【システム警告（自動差し戻し）】\n"
                    "テキストで「修正しました」と報告していますが、"
                    "実際のXMLタグ（<file>, <replace>, <run_command> 等）が出力されていません。\n"
                    "口頭でのロールプレイは禁止されています。\n"
                    "直ちに正しいXMLタグを出力してください。"
                )
                loop_history.append({"role": "assistant", "content": stream_response})
                loop_history.append({"role": "user", "content": retry_msg})
                continue
            
            break  # 通常の会話として終了
            
    hit_loop_cap = loop_count >= max_tool_loops
    if hit_loop_cap:
        logger.warning(f"⚠️ 最大ツール実行ループ数 ({max_tool_loops}) に到達したためループを終了しました。")
        final_accumulated_response += (
            f"\n\n*(⚠️ 最大実行ループ数 {max_tool_loops} に到達しました。"
            "作業は未完了の可能性があります。「続きを作成して」と指示してください)*"
        )
        if yield_sse_func:
            yield_sse_func({
                "type": "status",
                "status": "incomplete",
                "detail": f"max_tool_loops_{max_tool_loops}",
            })

    # Final completion gate for task/coding after file writes
    if files_written_this_run and mode in ("task", "coding"):
        try:
            gate = last_gate_meta or _run_task_completion_gate()
            if not gate.get("ok"):
                from app.core.acceptance_checker import format_incomplete_banner

                banner = format_incomplete_banner(
                    gate.get("acceptance_report"),
                    gate.get("build"),
                    hit_loop_cap=hit_loop_cap,
                )
                final_accumulated_response += banner
                acc = gate.get("acceptance_report")
                if acc and hasattr(acc, "format_for_agent"):
                    final_accumulated_response += "\n\n" + acc.format_for_agent()
                if yield_sse_func:
                    yield_sse_func({
                        "type": "status",
                        "status": "incomplete",
                        "detail": "completion_gate",
                        "acceptance": gate.get("acceptance"),
                        "build_ok": (gate.get("build") or {}).get("success"),
                    })
        except Exception as e:
            logger.warning(f"final completion gate: {e}")
    
    tool_results_summary = "\n".join(tool_handler.tool_results) if tool_handler.tool_results else ""
    # 重複停止などで search_results にマージ済みでも、summary が空なら再構築
    if not tool_results_summary and search_results and force_tool_synthesis:
        tool_results_summary = search_results

    from app.core.fact_filters.markup import (
        looks_like_tool_dump,
        strip_tool_dump_blocks,
        normalize_final_answer_body,
    )

    # Normalize FINAL_ANSWER before empty/synth decisions (marker-only must count as empty)
    _body, _empty_marker = normalize_final_answer_body(final_accumulated_response)
    if _empty_marker:
        final_accumulated_response = ""
        force_tool_synthesis = True
    elif "<<<FINAL_ANSWER>>>" in (final_accumulated_response or ""):
        final_accumulated_response = _body

    # 空本文ガード: pipeline 前に last_good を優先復元（ツール生ダンプは復元しない）
    if not final_accumulated_response.strip() and not force_tool_synthesis:
        if last_good_user_visible.strip() and not looks_like_tool_dump(last_good_user_visible):
            logger.warning("⚠️ 最終応答が空のため last_good_user_visible を復元します")
            final_accumulated_response = last_good_user_visible
        else:
            for msg in reversed(loop_history):
                if msg.get("role") == "assistant" and msg.get("content"):
                    clean_content = _snapshot_visible(msg["content"])
                    if clean_content and not looks_like_tool_dump(clean_content):
                        final_accumulated_response = clean_content
                        break

    def _synth_system_prompt(extra: str) -> str:
        """Synthesis must NOT inherit FINAL_ANSWER boundary (it causes empty-body loops)."""
        base = executor_sys_prompt or ""
        # Drop conflicting boundary rules from the main executor prompt
        base = re.sub(
            r"【構造的モダリティ分離（出力境界トークン）の厳守ルール】[\s\S]*?"
            r"(?=【|\Z)",
            "",
            base,
            count=1,
        )
        base = base.replace("<<<FINAL_ANSWER>>>", "")
        return (
            base
            + "\n\n# Synthesis mode\n"
            "Write the user-facing answer directly in plain prose/markdown.\n"
            "Do NOT output <<<FINAL_ANSWER>>>, <think>, tool XML, or planning notes.\n"
            + (extra or "")
        )

    def _extract_synth_text(rebuilt: str) -> str:
        from app.core.fact_filters.markup import (
            strip_internal_markup,
            split_final_answer,
        )

        body, empty_m = normalize_final_answer_body(rebuilt)
        if empty_m:
            pre, _, _ = split_final_answer(rebuilt)
            cleaned = strip_internal_markup(pre).strip()
            if len(cleaned) >= 80:
                logger.warning(
                    "⚠️ Synth returned empty FINAL_ANSWER body; using cleaned preamble"
                )
                return cleaned
            cleaned_all = strip_internal_markup(rebuilt).strip()
            return cleaned_all
        if "<<<FINAL_ANSWER>>>" in (rebuilt or ""):
            return strip_internal_markup(body).strip()
        return strip_internal_markup(rebuilt).strip()

    async def _synthesize_from_tools(prompt: str, sys_extra: str) -> str:
        rebuilt = ""
        s_stream = run_executor(
            user_input=prompt,
            instruction=instruction,
            search_results=search_results or tool_results_summary,
            memory_text=memory_text,
            history_messages=exec_history[-4:] if exec_history else [],
            mode=mode,
            system_instruction=_synth_system_prompt(sys_extra),
        )
        async for chunk in s_stream:
            rebuilt += chunk
            # Stream only post-strip deltas would be complex; emit raw then UI clear on done
            if yield_sse_func:
                yield_sse_func({"type": "chunk", "content": chunk})
        return _extract_synth_text(rebuilt)

    def _deterministic_tool_fallback() -> str:
        """Last resort when LLM synthesis fails — never return empty if we have data."""
        blob = (tool_results_summary or "") + "\n" + (search_results or "")
        # Pull a few quote-ish lines if present
        lines = []
        for line in blob.splitlines():
            s = line.strip()
            if not s:
                continue
            if any(
                k in s
                for k in (
                    "ticker",
                    "current_price",
                    "previous_close",
                    "change_pct",
                    "^GSPC",
                    "^DJI",
                    "^IXIC",
                    "Dow",
                    "S&P",
                    "Nasdaq",
                )
            ):
                lines.append(s)
            if len(lines) >= 12:
                break
        head = "\n".join(lines[:12]) if lines else blob[:1200].strip()
        return (
            "I gathered market data for your question, but the final write-up step failed. "
            "Here are the key tool/search snippets — ask me to summarize again if needed:\n\n"
            f"{head}"
        )

    need_synth = (
        force_tool_synthesis or not final_accumulated_response.strip()
    ) and bool(tool_results_summary or search_results)
    if need_synth:
        logger.info("⚠️ ツール実行後に最終回答が未生成だったため、ツール結果をもとに集約回答を生成します")
        _clear_ui_with_progress(yield_sse_func, _ui_progress("compose_from_search"))
        try:
            from app.core.completion_status import wants_code_in_chat
            code_hint = ""
            if wants_code_in_chat(user_input):
                code_hint = (
                    "ユーザーはコード全文をチャットで求めている。"
                    "「作成完了」だけの報告は禁止。パス・要点のあとコード全文をフェンスで出せ。"
                )
            final_prompt_msg = (
                "検索結果・ツール実行結果を踏まえて、ユーザーの質問に対する最終回答を自然な文章で作成してください。"
                "XMLタグや生ログ（[Local Tool:…]【一般検索結果】【引用契約】等）はそのまま出力せず、整理して回答してください。"
                "ファイルを作成した場合はパスと要点を必ず含めてください。"
                "Do not output <<<FINAL_ANSWER>>> or long internal planning notes—write the answer only."
                + code_hint
            )
            final_accumulated_response = await _synthesize_from_tools(
                final_prompt_msg,
                "\n\n【重要】XMLタグやツールタグ・ツール生ログは一切出力しないでください。"
                "結果を踏まえた最終的な回答のみを自然な対話で出力すること。メタ完了宣言だけで終わらないこと。"
                "<<<FINAL_ANSWER>>> は出力禁止。",
            )
        except Exception as e:
            logger.error(f"Final synthesis error: {e}")
            final_accumulated_response = ""

    # 空洞完了（「ファイル作成完了」だけ等）→ 1回だけ本体合成
    try:
        from app.core.completion_status import is_hollow_completion, wants_code_in_chat
        if (
            is_hollow_completion(final_accumulated_response, user_input)
            and (tool_results_summary or search_results)
        ):
            logger.warning("⚠️ 空洞完了を検知したため、本体回答を再合成します")
            _clear_ui_with_progress(
                yield_sse_func, "Rewriting a full answer from tool results…"
            )
            hollow_prompt = (
                "The previous response had no usable user-facing body. "
                "Using only the search/tool results, write a complete market answer now. "
                "No <<<FINAL_ANSWER>>>, no <think>, no tool XML."
            )
            if wants_code_in_chat(user_input):
                hollow_prompt += " Include full code in fences."
            rebuilt = await _synthesize_from_tools(
                hollow_prompt,
                "\nメタ完了禁止。XMLツールタグ禁止。本文を書け。<<<FINAL_ANSWER>>>禁止。",
            )
            if rebuilt.strip() and not is_hollow_completion(rebuilt, user_input):
                final_accumulated_response = rebuilt
            elif rebuilt.strip() and len(rebuilt) > len(final_accumulated_response or ""):
                final_accumulated_response = rebuilt
    except Exception as e:
        logger.warning(f"Hollow completion rebuild failed: {e}")

    if not final_accumulated_response.strip():
        if (
            last_good_user_visible.strip()
            and not looks_like_tool_dump(last_good_user_visible)
        ):
            final_accumulated_response = last_good_user_visible
        elif tool_results_summary or search_results:
            final_accumulated_response = _deterministic_tool_fallback()
        else:
            final_accumulated_response = (
                "*(⚠️ Response generation failed or was filtered. Please try again.)*"
            )
            logger.warning("⚠️ 最終応答が空になったため、フォールバックメッセージを挿入しました。")

    # --- 物理分離構造パース: <<<FINAL_ANSWER>>> 以降を厳格抽出 ---
    if "<<<FINAL_ANSWER>>>" in final_accumulated_response:
        parts = final_accumulated_response.split("<<<FINAL_ANSWER>>>")
        final_accumulated_response = parts[-1].strip()

    from app.core.fact_filters.markup import (
        strip_internal_markup,
        strip_supervisor_dump,
        looks_like_supervisor_dump,
        looks_like_tool_dump,
        strip_tool_dump_blocks,
        looks_incomplete_output,
        sanitize_preserving_body,
    )
    final_accumulated_response = strip_internal_markup(final_accumulated_response)
    # 進捗プレースホルダを最終本文から除去
    final_accumulated_response = re.sub(r"(?m)^⏳[^\n]*\n?", "", final_accumulated_response)
    final_accumulated_response = re.sub(
        r"(?m)^(?:まず、ユーザーの発言を分析します[^\n]*\n+|Output format:[^\n]*\n+|user_intent_analysis:[^\n]*\n+)+",
        "",
        final_accumulated_response,
    )
    final_accumulated_response = strip_tool_dump_blocks(final_accumulated_response)
    if looks_like_supervisor_dump(final_accumulated_response):
        logger.warning("⚠️ 最終本文に Supervisor 独白を検出したため除去します")
        stripped_sup = strip_supervisor_dump(final_accumulated_response)
        # incomplete バナーだけは残す
        banner_m = re.search(
            r"\*\(\s*⚠️[^)]*(?:続きを作成して|未完了)[^)]*\)\*",
            final_accumulated_response,
        )
        if stripped_sup.strip() and not looks_like_supervisor_dump(stripped_sup):
            final_accumulated_response = stripped_sup
        elif banner_m:
            final_accumulated_response = banner_m.group(0)
        else:
            final_accumulated_response = (
                "*(作業中に内部メモが本文へ漏れました。状態を確認のうえ「続きを作成して」で再開してください)*"
            )

    # ツール生ダンプが残っていたら破棄して再合成（エコー対策）
    if looks_like_tool_dump(final_accumulated_response):
        logger.warning("⚠️ 最終本文にツール生ダンプを検出したため除去・再合成します")
        stripped = strip_tool_dump_blocks(final_accumulated_response)
        if looks_like_tool_dump(stripped) or len(stripped) < 20:
            final_accumulated_response = ""
            if tool_results_summary or search_results:
                try:
                    dump_prompt = (
                        "直前の出力にはツール生ログが含まれていました。"
                        "検索結果・ツール実行結果だけを根拠に、ユーザーへの最終回答を自然な文章で書いてください。"
                        "生ログ・XMLタグ・【引用契約】は出力禁止。"
                    )
                    rebuilt = await _synthesize_from_tools(
                        dump_prompt,
                        "\nメタ完了禁止。XMLツールタグ禁止。ツール生ログ禁止。本文を書け。",
                    )
                    if rebuilt.strip() and not looks_like_tool_dump(rebuilt):
                        final_accumulated_response = rebuilt
                    else:
                        final_accumulated_response = strip_tool_dump_blocks(rebuilt)
                except Exception as e:
                    logger.warning(f"Tool-dump resynthesis failed: {e}")
            if not final_accumulated_response.strip():
                final_accumulated_response = (
                    "作業結果はツール側に反映されましたが、チャット本文の生成に失敗しました。"
                    "「続きを本文に書いて」と送るか、作成ファイルのパスを指定してください。"
                )
        else:
            final_accumulated_response = stripped

    # 途切れ検知 → 1回だけ継続生成
    if looks_incomplete_output(final_accumulated_response) and not continuation_attempted:
        continuation_attempted = True
        logger.info("🔄 不完全出力を検知したため継続生成を1回試みます")
        try:
            cont_prompt = (
                "直前の回答が途中で切れています。続きの文章またはコードのみを出力してください。"
                "Markdown表の途中ならセルを完成させて表を閉じてください。"
                "前文の繰り返し・XMLツールタグ・thinkタグは禁止です。"
            )
            cont_history = exec_history + [
                {"role": "assistant", "content": final_accumulated_response},
                {"role": "user", "content": cont_prompt},
            ]
            cont_stream = run_executor(
                user_input=cont_prompt,
                instruction=instruction,
                search_results=search_results,
                memory_text=memory_text,
                history_messages=cont_history,
                mode=mode,
                system_instruction=executor_sys_prompt + "\n続きのみ。ツールタグ・think禁止。表途中なら完成させよ。",
                enable_thinking=False,
            )
            continuation = ""
            cont_buf = ""
            async for chunk in cont_stream:
                cont_buf += chunk
                # 生チャンクを出さず、内部マークアップ除去後に差分だけ SSE
                cleaned = strip_internal_markup(cont_buf)
                if cleaned.startswith(continuation):
                    delta = cleaned[len(continuation):]
                else:
                    delta = cleaned
                    continuation = ""
                if delta:
                    continuation = cleaned
                    if yield_sse_func:
                        yield_sse_func({"type": "chunk", "content": delta})
            continuation = strip_internal_markup(cont_buf)
            if continuation.strip():
                final_accumulated_response = (
                    final_accumulated_response.rstrip() + "\n" + continuation
                )
        except Exception as e:
            logger.warning(f"Continuation generation failed: {e}")

    pre_sanitize = final_accumulated_response
    try:
        from app.core.fact_filters.pipeline import apply_grounding_pipeline

        def _run_pipeline(t: str) -> str:
            return apply_grounding_pipeline(t, str(search_results or ""), user_input=user_input)

        final_accumulated_response = sanitize_preserving_body(pre_sanitize, _run_pipeline)
    except Exception as e:
        logger.warning(f"Fact filter validation warning in auto_execution_loop: {e}")
        final_accumulated_response = strip_internal_markup(pre_sanitize)

    if not final_accumulated_response.strip():
        if last_good_user_visible.strip() and not looks_like_tool_dump(last_good_user_visible):
            logger.warning("⚠️ サニタイズ後も空のため last_good_user_visible を復元します")
            final_accumulated_response = strip_internal_markup(last_good_user_visible)
        elif tool_results_summary or search_results:
            logger.warning("⚠️ サニタイズ後も空のため tool/search フォールバックを挿入します")
            final_accumulated_response = _deterministic_tool_fallback()
        else:
            final_accumulated_response = (
                "*(⚠️ Response generation failed or was filtered. Please try again.)*"
            )

    # 最終ガード: それでもダンプならフォールバック（生ログを返さない）
    if looks_like_tool_dump(final_accumulated_response):
        logger.warning("⚠️ 最終ガードでツール生ダンプを遮断しました")
        if tool_results_summary or search_results:
            final_accumulated_response = _deterministic_tool_fallback()
        else:
            final_accumulated_response = (
                "Tool results were collected, but the chat write-up failed. "
                "Please ask me to summarize again."
            )

    return final_accumulated_response.strip(), tool_results_summary, escalation_history


